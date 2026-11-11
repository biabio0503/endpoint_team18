# 4단계: 프로젝트 경험 분석과 직무 요구 비교

기존 `05. 분석 내용 확인`과 결과 화면의 `직무 역량 비교` 탭에 구현했다. 새 페이지, 숙련도 점수, 합격 가능성, 기술 기반 수강 추천, 실행 로드맵은 추가하지 않는다. 학교 과목 이수를 프로젝트 기술 경험으로 해석하지 않는다.

## 처리와 검증 경계

1. 인증한 소유자의 계획을 잠근 짧은 트랜잭션에서 입력 버전과 문서 기준을 읽는다. 삭제되지 않은 현재 `ready`, 또는 현재 버전의 부분 추출 확인을 마친 `partial`만 사용한다. 실제 추출 행·본문·상태가 모두 유효해야 한다. 빈 본문, pending, failed, needs_ocr, 미확인 partial은 제외 사유를 표시한다.
2. 사용자가 기존 확인 화면에서 명시적으로 분석을 실행하면 외부 Gemini에 `document_id`, `extraction_revision`, `extracted_text`, 위치 필드만 허용한 `segments`를 보낸다. 위치는 문자 범위·페이지·문단·OCR 문단·bbox·이미지 참조다. 원본 파일, 파일명, 사용자 ID, 세션, 과목 자료는 전송하지 않는다. 본문 자체에 포함된 개인정보는 전송될 수 있음을 화면에서 안내한다.
3. 기존 `_generate` 전송 계층과 운영자가 설정한 `GEMINI_API_KEY`·`GEMINI_MODEL`을 사용한다. 별도 프로젝트 Pydantic 스키마가 기술명, 활동, 개인/팀/미확인 범위, 역할, 결과물, 원문 구절을 검증한다. 외부 본문은 시스템 지시와 분리한 JSON 데이터이며 프롬프트 안의 명령은 무시하도록 지시한다.
4. 서버가 문서 ID와 추출 버전을 확인하고, 정확한 연속 원문 구절과 기술명/명시적 별칭을 검증한다. 역할·결과물은 독립적으로 검증해 구절에 없는 필드만 null로 바꾼다. `validation_adjustments`는 카드의 필드 정리 기록이며 분석 실패가 아니다. 활동은 기술명과 수행 내용이 함께 있는 원문에서 복원하므로 모델이 넣은 역할·수량이나 과장한 범위가 저장되지 않는다. 수행 근거가 없는 후보는 제외하고 `errors`에 코드·후보 인덱스·기술명(검증 전 모델 값)을 기록한다. 행 연결이 불명확한 표의 기술 언급은 활동을 주장하지 않는 unknown 카드로 유지한다.
5. `evidence_start/end`는 Python Unicode 문자 위치이며 end는 제외한다. 구절과 겹치는 기존 모든 segment의 페이지·문단을 유지한다. 기술명 뒤의 한국어 조사는 검증 시 구분하지만 이름끼리 부분 문자열 매칭하지 않는다. 반복 항목은 중복 제거한다.
6. `personal`은 원문 1인칭, 같은 표의 `본인 기여 여부` 머리글·동일 행 셀, 또는 `본인이 직접 수행한 작업` 목록 문맥으로 검증한다. 좌표가 있으면 같은 페이지/문단/이미지의 bbox와 열·행 정렬을 사용한다. 좌표가 없으면 명시적 구분자(`|`, 탭, 두 칸 이상 공백)가 있는 행만 표로 연결한다. 불명확한 행·겹친 셀·반복 인용은 unknown이다. 목록은 다음 제목·빈 문단·다른 열에서 종료한다. `팀원 담당`과 `미수행`은 개인 수행 문맥보다 우선하며 `일부 설정`을 전체 구축으로 확대하지 않는다. 인용문 자체는 연속 원문으로 보존하고 판정에 사용한 머리글·셀은 `contribution_basis.context`에 각각 문자 범위와 위치를 저장한다. 이름이 있는 팀원을 업로더와 연결하지 않는다. 문서상 개인 수행은 `document_supported`, 사용자의 ‘맞아요’는 `confirmed_experience`로 구분한다.
7. 외부 호출 중 DB 트랜잭션을 유지하지 않는다. 저장 직전 전체 입력 버전과 문서 기준을 다시 검사하여 변경되었으면 HTTP 409를 반환한다. 외부 호출 실패는 HTTP 200 응답 안의 분석 상태와 오류로 표현한다.

## 저장 구조와 무효화

| 테이블 | 저장 내용 / 유효 기준 |
| --- | --- |
| `job_skill_snapshots` | 계획별 검증된 채용 분석 JSON, snapshot ID, 생성 시 input revision, 생성 시각. 목표·희망 직무·모델·분석 규칙의 해시가 같으면 재사용 |
| `project_experience_analyses` | 문서 ID·추출 버전·모델/규칙 버전별 분석 JSON. 검증 항목 각각에 experience ID. 문서 추출 행에 FK 연결 |
| `project_experience_answers` | experience ID별 최신 사용자 상태·별도 correction JSON·답변 시 입력 버전·시각. 분석 행에 FK 연결 |
| `skill_experience_answers` | 공고 기술별 unknown/no_experience 답변. 채용 snapshot ID·현재 전체 문서 기준 해시·정규화 기술 키에 연결 |

`confirmed`, `corrected`, `unknown`, `no_experience`를 구분한다. `corrected`만 별도 수정 객체를 받으며 AI 분석 JSON은 변경하지 않는다. 답변 변경 시 input revision을 증가시켜 오래된 화면 저장을 막는다. 동일 답변 재저장은 버전을 증가시키지 않는다. 답변 이력 전체가 아닌 최신 답변을 보관하는 MVP다.

문서 삭제·재추출·교체 시 현재 문서와 정확히 일치하는 분석만 조회한다. 이전 experience ID에는 확인을 저장할 수 없다. 원문 추출 정리가 완료되면 분석과 답변도 FK CASCADE로 삭제된다. 새 문서가 추가되거나 문서 상태가 바뀌면 기술 단위 경험 없음/보류 답변도 문서 기준이 달라져 다시 확인해야 한다. 삭제 문서의 스냅샷을 우회 조회하는 API는 없다.

프로젝트 규칙 버전은 `project-experience-v2:{model}`이다. v1 결과는 v2 캐시로 재사용하지 않으며 GET은 외부 호출을 하지 않는다. 이후 명시적인 POST는 저장된 추출 본문·segments에 새 추출/검증 규칙을 적용한다. 같은 v2 결과는 기본 POST에서 재사용하고, `refresh: true`일 때만 다시 Gemini를 호출한다. 두 경로 모두 OCR·문서 재추출·원본 파일 읽기를 호출하지 않는다. 성공한 재분석은 새 analysis/experience ID를 부여하고, 이전 분석은 `:superseded:{analysis_id}` 버전으로 보관한다. 이전 사용자 확인·수정 답변은 원래 분석에 남으며 새 카드에 이름이나 배열 순서로 연결하지 않는다. 재분석 전체 실패 시 기존 결과와 답변을 유지하고 `refresh_errors`로 별도 안내한다.

## 비교 알고리즘과 상태

서버에 저장된 기존 채용 분석 `skills`를 그대로 사용한다. 새 공고 추출 프롬프트나 클라이언트 제공 분석 JSON은 받지 않는다. 기존 `normalize_skill`과 명시적 별칭만 재사용한다. Python 3/Python, Postgres/PostgreSQL, Amazon Web Services/AWS는 일치한다. Java/JavaScript, SQL/PostgreSQL, React/React Native, PyTorch/TensorFlow는 다른 키다. 불명확한 이름의 의미 관계는 추론하지 않는다.

사용자 수정이 있으면 수정 기술명으로 매칭하며 `match_source=user_correction`을 표시한다. 이때 원래 문서 인용이 수정 기술을 검증한 것처럼 취급하지 않는다. 같은 기술의 여러 문서 근거는 개별 유지한다. 공고별 중복 집계, 필수·우대·단순 언급·판단 불가, 직접/연관 직무, 경력 분포와 인용은 기존 분석 값 그대로 전달한다.

| `student_status` | 판정 |
| --- | --- |
| `confirmed_experience` | 맞아요, 또는 개인 수행으로 수정한 사용자 답변 |
| `document_supported` | 검증된 문서에 개인 수행 표현이 있으나 아직 답변 없음 |
| `needs_confirmation` | 팀/미확인 수행, 사용자 보류, 개인 수행으로 확인되지 않은 수정, 상충하는 사용자 답변 |
| `not_verified` | 현재 자료에서 해당 기술 근거 없음. 문서 없음도 정보 부족으로 취급 |
| `no_experience` | 사용자 본인이 경험 없다고 명시적으로 답변 |

동일 기술의 긍정 확인과 경험 없음 답변이 충돌하면 `needs_confirmation`으로 되돌린다. 확인된 경험은 숙련도 보증이 아니다. `no_experience`만 `consider_learning` 후보로 표시하며, 나머지 미확인 상태는 `verify_experience_first`다. 공고 빈도는 학습 우선순위가 아니며 해외 원격 시니어 요구를 국내 대학생의 필수 준비사항으로 일반화하지 않는다.

최상위 비교 `status`는 처리 결과다. 직무와 프로젝트 분석이 모두 success이면 success, 재사용할 직무 분석은 있지만 일부 정보/분석이 빠지면 partial, 직무 스냅샷이 아직 없으면 error다. 기술별 경험 상태와 다르다.

## API 예시

모든 경로의 `{id}`는 현재 인증 소유자의 계획이다. SQLite는 세션 쿠키, PostgreSQL은 Supabase Bearer 인증을 사용한다. 쓰기 요청은 기존 Origin 검사도 적용한다. 다른 소유자의 계획은 404, 인증 없음은 401, 잘못된 요청은 422, 변경된 버전은 409다.

| 메서드 | 경로 | 요청 |
| --- | --- | --- |
| POST | `/api/roadmap-inputs/{id}/project-experience-analysis` | `{"expected_input_revision":8}` — 저장 결과 재사용. 명시적 재분석은 `"refresh":true` 추가 |
| GET | `/api/roadmap-inputs/{id}/project-experience-analysis` | 현재 유효한 분석과 답변 조회. 외부 호출 없음 |
| PATCH | `/api/roadmap-inputs/{id}/project-experiences/{experience_id}/confirmation` | 아래 답변 예시 |
| POST | `/api/roadmap-inputs/{id}/job-skill-analysis` | 기존 `{}` 유지. 명시적 새 분석만 `{"refresh":true}` |
| GET | `/api/roadmap-inputs/{id}/skill-comparison` | 서버 스냅샷과 최신 답변 비교. 외부 호출 없음 |
| POST | `/api/roadmap-inputs/{id}/skill-comparison/answers` | 공고 기술의 경험 없음/보류 답변 |

확인 요청 예시(숫자와 내용은 가상):

```json
{"expected_input_revision":8,"status":"confirmed"}
```

수정 요청 예시:

```json
{
  "expected_input_revision":9,
  "status":"corrected",
  "correction":{
    "skill_name":"Python",
    "activity":"결측값 전처리 코드를 작성했습니다.",
    "contribution_scope":"personal",
    "role":"데이터 처리 담당",
    "output":null
  }
}
```

`unknown`, `no_experience`는 correction 없이 전송한다. 답변 응답은 갱신된 `input_revision`과 전체 현재 프로젝트 분석이다. 이후 답변에는 새 버전을 사용한다.

공고 기술 답변 예시:

```json
{"expected_input_revision":10,"snapshot_id":"서버-반환-ID","skill_name":"SQL","status":"no_experience"}
```

비교 응답 축약 예시(가상):

```json
{
  "status":"success",
  "input_revision":11,
  "career_goal":"데이터 분석 분야",
  "target_role":"데이터 분석가",
  "job_analysis":{"status":"success","snapshot_id":"서버-ID","analyzed_input_revision":8,"analysis_summary":{"analyzed_jobs":2}},
  "project_analysis":{"status":"success","analyzed_documents":1,"verified_experiences":1},
  "comparisons":[{
    "skill_name":"Python",
    "student_status":"confirmed_experience",
    "preparation_candidate":"experience_confirmed",
    "job_requirement":{"mentioned_job_count":2,"required_job_count":1,"preferred_job_count":1},
    "project_evidence":[{"document_id":"문서-ID","extraction_revision":1,"evidence_text":"제가 Python 코드를 작성했습니다.","evidence_start":0,"evidence_end":21,"locations":[{"paragraph":1}],"user_confirmation":"confirmed","source":"document_ai","user_answer":{"status":"confirmed","correction":null,"source":"user"}}],
    "job_evidence":[{"job_id":"공고-ID","requirement_type":"required","source_url":"https://himalayas.app","evidence_text":"Python is required."}]
  }]
}
```

실제 응답에는 문서별 상태·제외 사유·제한 사항, 공고별 검증 근거·분포, 분석 당시 버전, 서버 snapshot ID가 포함된다. FastAPI `/docs`에도 새 요청 스키마가 등록된다.

## 마이그레이션 적용

- SQLite: `apps/api/migrations/006_project_experiences.sql`. 기존 migration runner가 앱 시작 시 한 번만 실행한다. 기존 데이터와 테이블을 삭제하지 않는다.
- Supabase PostgreSQL: `supabase/migrations/20261109051837_project_experience_comparison.sql`. CLI `migration new`로 생성했다. 운영 앱 시작에서는 PostgreSQL 마이그레이션을 실행하지 않는다.
- 기존 core, documents, auth owner mapping 마이그레이션 적용 상태를 먼저 확인한다. 새 파일은 테이블 네 개와 인덱스, FK, RLS, 권한 회수만 추가한다. 동일 이름 테이블이 있으면 조용히 넘어가지 않고 실패하여 스키마 불일치를 감지한다.
- 새 테이블은 서버 DB 연결 전용이다. public 스키마에 RLS를 활성화하고 PUBLIC/anon/authenticated 접근 권한을 회수한다. 브라우저에서 직접 읽거나 쓰는 정책은 만들지 않는다. 소유권은 기존 FastAPI 인증·계획 관계로 검증한다. [Supabase 공식 RLS 안내](https://supabase.com/docs/guides/database/postgres/row-level-security).

기존 배포의 마이그레이션 관리 절차에 따라 준비된 파일을 적용한다. SQL 직접 적용 환경의 예시는 다음과 같다(운영 연결 문자열은 서버 환경변수로만 제공):

```sh
psql "$ROADMAP_DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file supabase/migrations/20261109051837_project_experience_comparison.sql
```

Supabase CLI로 이력을 관리하는 환경에서는 먼저 현재 버전의 `supabase db push --help`와 migration history를 확인하고, 새 migration만 적용 대상으로 삼는다. 직접 SQL을 실행했다면 같은 파일을 CLI로 중복 적용하지 않도록 해당 환경의 이력 관리도 맞춰야 한다. DB reset, 기존 데이터 삭제, 운영 DB 자동 적용은 수행하지 않았다.

## 호출량과 오류 처리

- 계획·직무 기준이 같은 성공/부분 성공 job snapshot을 재사용한다. 사용자 답변·과목·문서만 바뀌면 기존 직무 분석을 재호출하지 않는다. 목표·희망 직무·모델·규칙 버전이 달라지면 해당 기준의 스냅샷만 조회한다.
- 같은 문서 ID·추출 버전·모델/규칙의 성공/부분 성공 프로젝트 분석은 재사용한다. 명시적 실행 시 실패 또는 미실행 문서만 재시도한다. 일부 검증 거부가 있는 partial도 보존한다.
- GET 비교와 사용자 답변 저장에는 Gemini/Himalayas 호출이 없다. 클라이언트 메모리 결과를 재사용할 때도 최신 서버 비교를 조회하여 같은 input revision에서 분석이 새로 완료된 상황을 반영한다.
- 문서당 60,000자, 요청당 현재 등록 문서 수 이내다. 초과 문서는 자르지 않고 `document_too_long`으로 표시한다. 대용량 청킹은 후속 과제다.
- 기존 Gemini 전송 계층의 시도별 60초, 최대 2회, RetryInfo 최대 30초 대기를 사용한다. 429 재시도 실패 시 남은 문서 호출을 중단한다. 앞서 검증한 문서는 저장하며 다음 실행에서 재사용한다. 키·본문·개인정보를 로그에 출력하지 않는다.
- 동시 최초 요청은 외부 호출이 중복될 수 있지만 DB uniqueness와 잠금으로 한 문서 버전의 저장 결과·확인을 덮어쓰지 않는다. 분산 실행 큐나 공급자 호출용 lease는 이번 MVP에 포함하지 않았다.
- job snapshot은 자동 만료하지 않는다. 원래 수집 시각·분석 버전을 표시한다. 현재 UI의 오류/partial 재분석 버튼은 명시적 refresh다. 성공 스냅샷의 새 표본 수집은 API `refresh:true`로 요청할 수 있다.

## 자동·브라우저 검증

```sh
ROADMAP_DB_BACKEND=sqlite ROADMAP_AUTO_SEED_DEV=0 apps/api/.venv/bin/python -m pytest apps/api/tests -q
(cd apps/web && node --experimental-vm-modules --test tests/unit/*.test.mjs)
(cd apps/web && ROADMAP_API_ORIGIN=https://api.example.com npm run build)
```

2026-11-09 검증: 백엔드 전체 **141 passed, 2 skipped**, 기존 subtest 30개 통과. 추가된 프로젝트 단위/API 테스트는 문서별 근거, 개인/팀/미확인, 환각 ID·구절·역할 거부, 별칭/비병합, partial·빈 문서, 삭제·재추출, 사용자 수정 출처, 409·소유권, 429·부분 성공·재사용을 포함한다. 기존 채용공고 및 수강 추천 회귀도 통과했다.

격리 PostgreSQL은 `localhost:55439/team18_document_test`에서 신규 migration 포함 모든 SQL 적용, 기존 문서 테스트 및 같은 프로젝트 API 시나리오 9개, RLS·권한·JSONB·FK CASCADE 검증을 통과했다. 기존 PostgreSQL 테스트의 과거 쿠키 인증 fixture는 현재 Bearer 인증을 모의하는 fixture로 갱신했다. 외부 Supabase Auth 호출은 하지 않았다. 운영 DB에는 접속하지 않았다.

```sh
# 명시적으로 초기화해도 되는 로컬 테스트 DB에만 허용됨
ROADMAP_TEST_POSTGRES_URL=postgresql://USER@127.0.0.1:PORT/team18_document_test \
ROADMAP_ALLOW_TEST_DB_RESET=1 apps/api/.venv/bin/python -m pytest apps/api/tests/integration/test_documents_postgres.py -q
```

브라우저는 fake Auth/API 전용이다. 실제 사용자 계정과 외부 AI를 사용하지 않는다.

```sh
cd apps/web
NEXT_PUBLIC_SUPABASE_URL=https://job-skills-test.supabase.co \
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=test-key ROADMAP_API_ORIGIN=http://127.0.0.1:8000 npm run dev -- --port 15101
# 별도 터미널
node tests/e2e/job-skills.mjs
node tests/e2e/project-experiences.mjs
```

프런트 단위 테스트 **11개 통과**. 두 브라우저 시나리오 통과: 명시적 분석 실행, 확인·수정·보류, 원문 펼치기, 프로젝트/공고 근거, 경험 없음과 자료 부족 구분, 재사용·무효화, 기존 수강 추천, 390px 화면. Next.js 운영 빌드 통과. 화면 이미지: `/tmp/team18-project-comparison-ui.png`.

## 실제 연동 재현

```sh
apps/api/.venv/bin/python apps/api/app/scripts/project_experience_live.py --limit 3 --output /tmp/project-experience-live.json
```

기존 환경의 Gemini 키·모델을 읽되, DB와 파일 저장소는 항상 임시 SQLite/로컬 폴더로 교체한다. 합성 TXT 문서 실제 업로드 → 기존 worker 텍스트 추출 → 실제 Gemini → 서버 원문 검증 → API 사용자 확인 저장 → 실제 Himalayas/Gemini 공고 분석 → 비교 API → 재조회 호출 수 검증 순서다. 공고 표본에 Python·SQL이 없으면 예시 검증을 `incomplete`로 보고하며 실제 없는 기술을 만들지 않는다.

샌드박스에서는 DNS가 차단되어 Gemini 연결에 실패했다. 호스트 네트워크에서 실제 처리 검증을 따로 진행했다. Mock 테스트 성공과 실연동 성공을 구분한다.

### 실제 검증 기록 — 2026-11-09

설정된 `gemini-3.5-flash-lite`를 변경하지 않았다. 먼저 최대 3개, 이어서 5개 공고를 요청했다. 프로젝트 경험 추출·확인·SQL 미확인·캐시 검증은 성공했으나 해당 표본에는 Python 요구가 없어 예시 충족 상태는 `incomplete`였다. 실제 없는 Python 요구를 보충하지 않았다.

마지막 최대 10개 표본으로 전체 예시를 확인했다:

| 항목 | 실제 결과 |
| --- | --- |
| 원본 문서 → 추출 본문 | 합성 TXT 1개, 원문과 정확히 일치 |
| 프로젝트 Gemini 분석 | success, Python·Matplotlib·Docker 3개 경험 |
| 문서 원문 검증 | 세 항목 모두 실제 문자 범위와 일치 |
| 사용자 확인 | Python confirmed 저장 및 재조회 유지 |
| 공고 분석 | 10개 분석 완료, 정규화 기술 22개 |
| 공고 검증 제한 | 2개 공고의 항목 합계 9개가 원문/기술명 대조에서 제외됨. job status와 전체 비교는 partial |
| Python 비교 | confirmed_experience, 프로젝트 근거 1건 + 공고 근거 3건 |
| SQL 비교 | not_verified, 프로젝트 근거 0건 + 공고 근거 6건. 경험 없음으로 변경되지 않음 |
| 재조회 | 프로젝트 분석 POST, 기존 공고 분석 POST, 비교 GET 후 추가 Gemini 작업 0회 |
| 초기 Gemini 작업 | 프로젝트 1회 + 직무 검색어 1회 + 공고 배치 2회. 전송 계층 내부 재시도 수와 구분한 작업 단위 집계 |

최종 재현 명령: `apps/api/.venv/bin/python apps/api/app/scripts/project_experience_live.py --limit 10 --output /tmp/team18-project-experience-live-10.json`. 시나리오 검증 자체의 `status=success`는 위 체크가 모두 통과했다는 의미이며, 실제 비교 응답의 `status=partial`과 다르다. 원본 보고서는 `/tmp/team18-project-experience-live-10.json`, 앞선 소표본은 `/tmp/team18-project-experience-live.json`, `/tmp/team18-project-experience-live-5.json`에 저장했다. 테스트용 합성 프로젝트를 실제 학생의 경험으로 보고하지 않는다.

## 주요 변경 파일

- API/저장: `api/routes/project_experiences.py`, 기존 `job_skill_analysis.py`, `main.py`, `repositories/experience_analysis.py`.
- 분석/검증/비교: `services/gemini_projects.py`, `project_experience_schemas.py`, `project_experience.py`. 기존 공고 분석 알고리즘·수강 추천 구현은 변경하지 않았다.
- 스키마: SQLite `006_project_experiences.sql`, Supabase `20261109051837_project_experience_comparison.sql`.
- 화면: 기존 review 페이지, `ProjectExperienceReview.js`, `ProjectEvidence.js`, `JobSkillAnalysis.js`, `jobSkillAnalysis.mjs`, 기존 CSS.
- 검증: `test_project_experience.py`, `project_experience_scenario.py`, `test_project_experience_api.py`, PostgreSQL Auth fixture·문서 시나리오, 기존 API/OpenAPI 테스트, 프런트 로더 단위 테스트와 프로젝트 E2E, `scripts/project_experience_live.py`.

원문이 실제 존재한다는 검증은 문서의 사실성·작성자 신원·활동 요약의 의미 정확성을 보증하지 않는다. 동기 분석은 운영 프록시의 타임아웃과 Gemini 할당량 제약을 받는다. 개인화 수강 추천, 점수, 실행 로드맵, 공모전 추천 변경은 요청 범위대로 미구현이다.

## v2 ClassBridge 회귀 수정 — 2026-11-11

배포에서 보고된 `role_or_output_not_in_evidence` 5건에는 탈락 후보 기술명이 없어 특정 오류를 PyMuPDF/pytest 누락과 일대일로 연결할 수 없다. 수정 전 코드는 선택 필드 하나의 불일치만으로도 전체 후보를 제외했고, 활동 설명은 검증하지 않았으며, 개인 수행은 인용 안의 1인칭만 허용했다. 따라서 **후보 자체 미추출**, **선택 필드 때문에 탈락**, **개인 수행 문맥 미인식**을 구분해서 검증했다. 새 오류에는 후보 기술명·인덱스를 남긴다.

동일한 합성 Gemini 응답(표 후보 8개 + 상세 작업 후보 5개, 상세 후보에 근거 없는 role/output 포함)을 현재 HEAD의 수정 전 검증기와 v2에 넣어 비교했다. 아래 ‘수정 전’은 이 통제된 재현 결과이며, 실제 배포에서 저장되지 않은 후보를 복구한 결과가 아니다.

| 기술 | 수정 전 합성 재현 | 수정 후 상세 카드 |
| --- | --- | --- |
| FastAPI | 직접 구현만 유지 | FastAPI REST API 9개 설계 및 구현 |
| PostgreSQL | 직접 설계만 유지 | PostgreSQL 테이블 6개 설계 |
| Redis | 직접 구현만 유지 | Redis 큐·재시도 구현 |
| PyMuPDF | 상세 후보 탈락 | PyMuPDF 문서 파싱 및 OCR 서비스 연동 |
| pytest | 상세 후보 탈락 | pytest 자동화 테스트 42개 작성 |

수정 전 8개 카드·선택 필드 오류 5건 → 수정 후 13개 카드·전체 탈락 오류 0건. 상세 작업 5개는 개인 수행 문맥을 확인했고, 표 요약과 별도 원문 위치를 유지한다. 두 기술이 함께 쓰인 셀은 기술별 카드로 분리한다. Docker/GitHub Actions는 일부 설정, Next.js/TypeScript는 팀원 담당이다.

### 실행한 검증과 범위

```sh
PYTHONPATH=apps/api/app apps/api/.venv/bin/python -m pytest \
  apps/api/tests/unit \
  apps/api/tests/integration/test_project_experience_api.py \
  apps/api/tests/integration/test_job_skill_analysis_api.py \
  apps/api/tests/integration/test_roadmap_api.py \
  apps/api/tests/integration/test_document_ocr_api.py -q -rs
node --experimental-vm-modules --test apps/web/tests/unit/*.test.mjs
node apps/web/tests/e2e/project-experiences.mjs
apps/api/.venv/bin/python apps/api/app/scripts/classbridge_experience_live.py \
  --output /tmp/team18-classbridge-live.json
git diff --check
```

- API 전체 단위 + 관련 SQLite 통합: **322 passed, 5 skipped, 30 subtests passed**. skip은 별도 opt-in이 필요한 기존 실모델 과목 추천 1개와 격리 PostgreSQL 환경이 필요한 OCR 4개다. Google SDK의 기존 deprecation warning 1건이 있다.
- 위 범위 중 프로젝트 단위·API 통합·로드맵 통합: **70 passed**. 역할만/산출물만/둘 다 불일치와 활동 근거 없음, 수량·역할 복원, 페이지/문단 bbox, 뒤섞인 OCR 순서, 다른 페이지/이미지/행, 겹친 셀, 좌표 없는 명확/모호한 행, 목록 종료, 팀원 담당·미수행 우선순위, 중복 인용을 검증했다.
- 웹 단위: **15 passed**. 브라우저 E2E: **PASS**. 실제 검증기의 합성 응답을 화면에 공급해 5개 상세 작업, 인용과 별도 문맥, 일부 설정, 팀원 범위, 선택 필드 정리 시 경고 없음, 재분석 버튼, 사용자 답변 분리, 390px 화면을 확인했다. 이 E2E의 인증·API 응답은 모의다.
- API 통합에서 v1→v2 재분석과 명시적 `refresh`가 동일한 저장 본문/segments를 사용하고 OCR 호출·추출 작업 예약이 **0회**임을 검증했다. 후보 순서를 뒤집어도 새 카드에 예전 답변이 연결되지 않으며, 예전 확인·수정 답변은 이전 분석에 보존된다. 실패한 refresh는 기존 결과·답변을 유지한다.
- 실제 Gemini: 설정된 **gemini-3.5-flash-lite**, 합성 ClassBridge 본문·좌표로 호스트 네트워크에서 응답 2회를 확인했다(각 호출의 재시도 없음). 첫 응답은 상세 5개 모두 보존됐으나 FastAPI 문장을 Python 근거로 쓴 후보 1개를 기술명 검사에서 제외했다. 표 셀 인용 지시를 보완한 최종 응답은 **11개 후보 모두 검증 통과, 오류 0건, 상세 5/5 보존**. Python 직접 사용, Docker/GitHub Actions 일부 설정, Next.js/TypeScript 팀원 담당도 확인됐다. 다음 섹션의 Playwright 작업은 unknown으로 남았다.
- 실제 PDF/OCR 재실행, 원래 배포 후보 복구, 운영 DB 재분석은 이 검증 범위에 포함되지 않는다. 회귀 입력은 사용자 보고 내용을 옮긴 합성 fixture이며 원본 PDF가 아니다.

로컬 검증 산출물: `/tmp/team18-classbridge-before-after.json`, `/tmp/team18-classbridge-live-first.json`, `/tmp/team18-classbridge-live.json`, `/tmp/team18-classbridge-review-ui.png`. 최종 실제 응답을 저장한 뒤 서버의 이미지 구분·빈 행 경계를 더 보수적으로 처리하고 이전 답변 보존을 추가했으며, 이 추가 경계는 위 단위·통합 테스트로 확인했다.

### 이번 수정 파일

| 파일 | 변경 |
| --- | --- |
| `apps/api/app/services/project_experience.py` | 독립 필드 검증, 활동 복원, 후보별 오류, v2 버전 |
| `apps/api/app/services/project_evidence.py` | 원문 위치·표 좌표·목록 문맥 판정 (신규) |
| `apps/api/app/services/gemini_projects.py` | 상세 작업·표 셀 추출 지시와 위치 payload |
| `apps/api/app/services/project_experience_schemas.py` | 명시적 refresh 요청 |
| `apps/api/app/api/routes/project_experiences.py` | 저장 본문 재분석·실패 시 유지 |
| `apps/api/app/repositories/experience_analysis.py` | 재분석 교체·이전 분석/답변 보존 |
| `apps/api/tests/unit/test_project_experience.py` | 독립 검증·활동·좌표·문맥 회귀 |
| `apps/api/tests/fixtures/classbridge.py` | 읽기 순서가 섞인 합성 ClassBridge 자료 (신규) |
| `apps/api/tests/integration/project_experience_scenario.py` | 카드 비교·버전·캐시·OCR 미호출·답변 분리 |
| `apps/api/tests/integration/test_project_experience_api.py` | 새 통합 시나리오 실행 |
| `apps/api/app/scripts/classbridge_experience_live.py` | 합성 자료로 실제 모델 1회 확인 (신규) |
| `apps/web/src/features/roadmap/ProjectEvidence.js` | 원문 인용과 판정 문맥을 별도 표시 |
| `apps/web/src/features/roadmap/ProjectExperienceReview.js` | 명시적 재분석 및 실패 안내 |
| `apps/web/tests/e2e/project-experiences.mjs` | 실제 검증기 결과로 ClassBridge 화면 회귀 |
| `docs/project-experience-comparison.md` | v2 동작·재현·검증 범위 기록 |
