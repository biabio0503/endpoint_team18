# Gemini 채용공고 기술 스택 분석

## API와 처리 흐름

`POST /api/roadmap-inputs/{request_id}/job-skill-analysis`에 `{}`를 보낸다. 기존 인증·세션, Origin 및 계획 소유권 검사를 사용한다. 클라이언트의 사용자 ID·목표 재정의는 거부한다. DB에서 `career_goal`, 선택 `target_role`, 전체 `input_revision`을 읽고 트랜잭션을 종료한 뒤 외부 API를 호출한다. 완료 직전에 버전을 재확인하며, 과목·문서 등 전체 입력이 변경되거나 계획이 삭제되었다면 409를 반환한다. 분석 결과는 DB에 저장하지 않는다.

1. `gemini_jobs.generate_job_keywords`가 두 입력을 함께 Gemini에 전달한다. 희망 직무를 우선하되 목표의 구체적인 활동·분야를 반영한다. 희망 직무가 없어도 목표가 충분하면 해석하며, 부족하면 `needs_clarification`을 반환한다.
2. `RoleInterpretation`이 상태·영어 대표 직무·최대 3개 짧은 영어 검색어·`direct`/`related`를 검증한다. 중복은 제거하고 상충하는 관계는 거부한다. 잘못된 응답을 규칙 사전으로 대체하지 않는다.
3. `himalayas.fetch_jobs_with_keywords`가 검색어를 재생성하지 않고 기존 수집·중복 제거·경력 구분·마감/빈 본문 제외·직접/연관 표본 균형 로직에 전달한다. 기존 `fetch_jobs()`와 GET `/jobs`도 유지된다.
4. `gemini_jobs.extract_job_skills`가 최대 20개 선정 공고를 기본 5개씩 분석한다. ID·제목·직무 관계·경력 그룹·전체 본문·출처 URL만 보낸다. 사용자 문서·과목·프로필·세션을 보내지 않는다.
5. `verify_skills`가 ID와 근거를 검증하고, `aggregate_skills`가 정규화한 기술별 고유 공고 수를 집계한다.

[Gemini 구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output)과 [Python SDK](https://github.com/googleapis/python-genai)를 사용한다. Pydantic 스키마에서 중첩 길이/배열 제한을 제외한 구조를 모델에 전달하고, 모든 길이·개수·enum·추가 필드 제한은 서버 Pydantic 검증에 그대로 적용한다. 실제 연결에서 중첩 제한이 있는 스키마는 HTTP 400으로 거부됨을 확인했다. `gemini.py`의 수강 추천 구현은 변경하지 않는다. 수집과 출처 표시는 [Himalayas 공식 API 문서](https://himalayas.app/api)를 따른다.

## 검증과 빈도

- `job_analyses[].model_skills`: 미확정 AI 출력. `verified_skills`: 서버 검증 통과 항목. `rejected_skills`: 거부 항목과 사유. UI는 검증된 집계 결과만 표시한다.
- 배치에 없는 ID는 거부한다. 누락·중복 ID에 해당하는 공고는 실패로 처리하며 다른 정상 공고는 유지한다.
- `evidence_text`는 해당 `description_text`의 정확한 연속 부분 문자열이어야 한다. 번역·생략·공백 변경은 허용하지 않는다. `evidence_start`, `evidence_end`는 Python Unicode 문자 위치이며 끝은 제외한다.
- 기술명은 알려진 별칭을 포함해 인용에 단어 경계로 존재해야 한다. `technical_competency`는 번역·요약을 허용하므로 인용 존재만 확인하며, 역량 이름의 의미적 타당성은 모델 판단으로 남는다.
- `required`/`preferred`에는 인용의 명시적 필수/우대 표현도 요구한다. 표현이 없거나 충돌하면 `unknown`으로 낮춘다. 원래 분류는 `model_requirement_type`에 남긴다. 원문의 요구조건 제목이 인용에서 빠지면 보수적으로 판단 불가가 될 수 있다.
- 명시적 별칭만 병합한다. `Python3`/`Python 3` → Python, Postgres → PostgreSQL, Amazon Web Services → AWS. SQL/PostgreSQL, Java/JavaScript는 구분한다. 알려지지 않은 이름은 공백·대소문자 기준으로만 묶는다.
- 같은 공고에서 같은 기술이 여러 번 나와도 1개다. 요구 수준 카운터는 공고별 `required > preferred > mentioned > unknown` 중 하나만 계산한다. 각 인용의 분류는 근거에 남는다.
- `mention_frequency = mentioned_job_count / analysis_summary.analyzed_jobs`. 실패·건너뜀은 분모에서 제외한다. 정상적인 빈 기술 목록은 분석 성공으로 센다. 추출 항목이 모두 거부된 공고는 실패로 처리한다.
- 기술별 `direct_job_count`, `related_job_count`, `seniority_distribution`도 고유 공고 기준이다. 정렬은 언급 공고 수순이며 중요도·학습 우선순위가 아니다.

외부 본문은 시스템 지시와 분리한 JSON 데이터로 전달하며, 시스템 지시는 본문 내 명령을 무시하도록 명시한다. HTML을 실행하지 않는다. 링크는 모델 출력이 아닌 수집기의 검증된 출처 URL을 사용한다. 인용 검증은 원문 존재를 보장하지만 의미 해석이나 추출의 완전성을 보장하지 않는다.

## 응답 상태

응답에는 입력값, `canonical_role`, `search_keywords`, 관계 포함 `keyword_details`, `retrieved_at`, 검색어별 `searches`, 기존 `selection_summary`, `collection_summary`, `analysis_summary`, `analysis_limits`, `job_analyses`, `skills`, 단계별 `errors`, `input_revision`이 포함된다.

| 상태 | 의미 |
| --- | --- |
| `success` | 수집·배치 분석·근거 검증 완료. 기술이 0개일 수 있음 |
| `partial` | 분석 성공 공고가 있으나 일부 수집/분석 실패·건너뜀·근거 거부가 있음 |
| `error` | 검색어 실패, 미완료 수집으로 분석 공고 없음, 또는 분석 성공 0개 |
| `no_jobs` | 검색은 모두 완료했으나 선정할 관련 공고 없음 |
| `needs_clarification` | 목표·직무 정보가 부족해 검색하지 않음 |

외부 서비스 실패는 HTTP 200 안의 분석 상태와 오류로 표현한다. HTTP 성공을 분석 성공으로 해석하지 않는다. 인증 실패는 401, 다른 소유자 계획은 404, 빈 목표/잘못된 본문은 422, 입력 변경은 409다.

## 화면과 설정

기존 결과 화면의 **직무 역량 비교** 탭에서 처음 열 때 분석한다. 같은 계획·입력 버전의 결과 및 진행 중 요청은 컴포넌트 메모리에서 재사용한다. 탭 재진입·창 포커스·가시성 복귀 및 분석 완료 뒤에 최신 버전을 확인한다. 새로고침·페이지 이탈 시 캐시는 사라진다. 오류·부분 성공에는 다시 분석을 제공한다. 수강 후보 상태는 독립적으로 유지한다.

추가 환경변수·패키지·DB 마이그레이션은 없다. 기존 서버 전용 `GEMINI_API_KEY`, `GEMINI_MODEL`을 사용하며 미설정 모델은 기존과 같은 `gemini-3.5-flash`다. 선택적 `HIMALAYAS_API_KEY`도 유지한다.

| 설정 | 값 |
| --- | --- |
| 선정 공고 | 기본/최대 20 |
| 배치 | 최대 5개 |
| 공고 본문 | 최대 40,000 Unicode 문자 |
| 배치 본문 합계 | 최대 120,000 Unicode 문자 |
| Gemini 타임아웃 | 시도별 60초 |
| Gemini 재시도 | 일시적 오류에 한해 최대 1회 추가 |
| 재시도 대기 | 기본 0.5초, 공급자의 RetryInfo가 있으면 최대 30초까지 반영 |
| 출력 토큰 한도 | 16,384 |

긴 본문은 조용히 자르지 않는다. `skipped`, `description_too_long`, 실제/허용 길이, `analyzed_char_range: null`을 기록한다. 정상 공고는 `[0, 전체 길이]`를 기록한다. 배치 합계가 크면 공고 수를 줄여 나누므로 추출 요청이 4회를 넘을 수 있다. 한 배치 실패는 다른 배치의 성공을 제거하지 않는다.

제한적 재시도 후에도 429이면 남은 배치는 `gemini_rate_limit_active`로 건너뛰어 소진된 할당량에 계속 요청하지 않는다. 이전 성공 결과는 유지한다. `planned_batch_count`는 준비한 배치 수, `batch_count`는 실제 시도한 배치 수다.

## 검증 명령

저장소 루트에서 자동 테스트:

```sh
ROADMAP_DB_BACKEND=sqlite ROADMAP_AUTO_SEED_DEV=0 apps/api/.venv/bin/python -m pytest apps/api/tests -q
(cd apps/web && node --experimental-vm-modules --test tests/unit/*.test.mjs)
(cd apps/web && ROADMAP_API_ORIGIN=https://api.example.com npm run build)
```

실제 연결 테스트는 서버 환경변수 또는 `apps/api/.env`를 읽고 요청한 예시 세 직무만 전송한다. DB에 연결하지 않는다. API 비용·쿼터를 사용하는 명시적 실행이며, 예시 사이 기본 65초 대기로 분당 요청 수 제한을 고려한다.

```sh
apps/api/.venv/bin/python apps/api/app/scripts/job_skill_analysis_live.py --output /tmp/job-skill-analysis-live.json
# 개별 입력 또는 작은 표본
apps/api/.venv/bin/python apps/api/app/scripts/job_skill_analysis_live.py --case data --limit 5
apps/api/.venv/bin/python apps/api/app/scripts/job_skill_analysis_live.py --case backend
apps/api/.venv/bin/python apps/api/app/scripts/job_skill_analysis_live.py --case ml
```

스크립트는 검색어·수집/선정 수·분석 성공/실패 수·대표 기술과 근거를 출력한다. `--output`은 전체 JSON을 저장한다. DNS나 테스트 서버 포트가 차단되면 Mac 호스트 터미널에서 같은 명령을 실행한다. Mock 통과는 실제 연동 성공을 뜻하지 않는다.

브라우저 화면 검증은 별도 모의 API 테스트다. 실제 인증 계정이나 DB를 사용하지 않는다.

```sh
cd apps/web
NEXT_PUBLIC_SUPABASE_URL=https://job-skills-test.supabase.co NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=test-key ROADMAP_API_ORIGIN=http://127.0.0.1:8000 npm run dev -- --port 15101
# 별도 터미널의 apps/web에서 (기본 Brave; P5_BROWSER로 실행 파일 변경 가능)
node tests/e2e/job-skills.mjs
```

## 실제 검증 기록 — 2026-11-09

Mac 호스트 네트워크와 기존 서버 키·모델(`gemini-3.6-flash`)을 사용했다. 저장된 환경변수를 변경하지 않았다. 기본 모델 설정은 기존대로 유지된다.

| 입력 | 실제 Gemini 검색어 | 고유 후보 / 선정 | 분석 성공 | 결과 |
| --- | --- | --- | --- | --- |
| 데이터 분석가 | Data Analyst (direct), BI Analyst (related), Data Scientist (related) | 60 / 20 | 5 | partial: 배치 1개 성공, 다른 배치 오류·429 |
| 백엔드 개발자 | Backend Developer (direct), Backend Engineer (direct), Software Engineer (related) | 59 / 20 | 0 | error: 추출 요청 429 |
| 머신러닝 엔지니어 | 생성 단계에서 429 | 미실행 | 0 | error: 검색어 생성 제한 |

데이터 분석가 성공 표본에서 Power BI, DAX, Excel, Power Query, SQL 등의 기술과 검증된 원문 근거를 확인했다. 예: [Data Analyst - Power BI Specialist 공고](https://himalayas.app/companies/european-dynamics/jobs/data-analyst-power-bi-specialist)의 SQL 근거는 `Knowledge of relational databases and SQL for data retrieval;`이며 서버 부분 문자열 검증을 통과했다. 요구 수준의 명시 표현이 인용에 없어 `unknown`으로 보존했다.

공급자 진단 응답은 무료 일일 요청 한도 20회 소진을 명시했다. 따라서 세 직무 모두의 실제 기술 추출이 성공했다고 보고하지 않는다. 한도 회복 또는 충분한 할당량이 있는 서버 설정 후 위 명령으로 재검증해야 한다. 전체 실제 결과는 검증 세션의 `/tmp/team18-job-skills-live.json`에 남겼다. 이 기록은 남은 배치의 429 건너뛰기 개선 전 호출 결과다. 해당 개선은 별도의 Mock 테스트로 확인한다.

자동 검증: 백엔드 전체 회귀 **101 passed, 2 skipped**(기존 Himalayas·수강 추천 포함), 프런트엔드 단위 테스트 **9 passed**, Next.js 운영 빌드 및 브라우저 화면 테스트 통과. 기술명 별칭 보완 후 관련 단위 테스트 20개도 재확인했다. 브라우저 테스트는 자동 호출·같은 버전 캐시·새 버전 재분석·409·성공/부분/실패/공고 없음/정보 부족·근거 링크·수강 추천 유지·390px 모바일 레이아웃을 확인한다. 선택적 PostgreSQL 실DB 테스트와 기존 수강 추천 실API 테스트는 기본 실행에서 제외된다.

## 변경 파일

- 백엔드 추가: `services/job_skill_schemas.py`, `services/gemini_jobs.py`, `services/job_skill_analysis.py`, `api/routes/job_skill_analysis.py`, `scripts/job_skill_analysis_live.py`.
- 백엔드 연결: `app/main.py`, `services/himalayas.py`.
- 화면: `features/roadmap/Result.js`, `JobSkillAnalysis.js`, `jobSkillAnalysis.mjs`, `app/style.css`.
- 검증: `test_job_skill_analysis.py`, `test_job_skill_analysis_api.py`, `test_fastapi.py`, `test_recommendations.py`, `job-skill-analysis.test.mjs`, `e2e/job-skills.mjs`, 기존 `e2e/p5-flow.mjs`의 새 탭 기대 문구.
- 문서: `README.md`, `himalayas-jobs.md`, `ai-integration-contract.md`, 이 문서.

기존 수강 추천 테스트는 공유 fixture 과목을 삭제하면서 전체 회귀 실행에서 FK 충돌이 발생하던 부분을 별도의 빈 테스트 카탈로그를 생성하도록 수정했다. 운영 수강 추천 구현이나 DB 스키마는 변경하지 않았다.

## 제한과 후속 연결 지점

해외 원격 공고 표본이며 국내 전체 시장이나 학생의 필수 역량을 대표하지 않는다. 제목의 완전한 구절 또는 모든 직무 단어를 요구하므로 다른 표현의 관련 공고를 놓칠 수 있다. 사전에 없는 직무도 같은 기준을 쓰며, 검색 결과라는 이유만으로 direct로 인정하지 않는다.

개인 역량 비교·부족 역량·학습 우선순위·로드맵·기술 기반 수강 추천·영구 저장은 범위 밖이다. 향후 모듈은 `analyze_job_skills` 응답의 버전 및 검증된 `skills[].evidence`를 경계로 연결할 수 있다. 동기 HTTP 요청이므로 운영 프록시의 요청 제한 시간과 공급자 할당량은 별도로 고려해야 한다.
