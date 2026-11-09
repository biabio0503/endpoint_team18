# 추천 품질 진단과 개선 — 2026-11-09

기준은 GitHub `biabio0503/endpoint_team18`의 `main`, `d720ac8cb7669dd577d0340eed8684dd7275d496`이다. GitHub 커넥터로 원격 SHA와 깨끗한 로컬 HEAD의 일치를 확인한 후 작업했다. 운영 DB·스토리지·배포·환경 파일을 변경하지 않았다. 새 화면, 준비 기간 입력, 마이그레이션, 의존성 추가는 없다.

## 관찰 사례와 재현 범위

사용자가 관찰한 저장 결과는 해외 공고 20개, 비교 기술 69개, 실제 생성 입력의 미확인 기술 SQL·Python·Excel이다. **화면의 CAD·CATIA·CISSP·SolidWorks 노출은 그 활동이 추천됐다는 증거가 아니다.** 기존 `validate_result`는 전체 `basis.skills`를 준비 상태 요약에 넣고, `focused_skills`/`model_input`은 경험 없음·확인된 경험 최대 12개와 미확인 최대 3개만 전달한다. 저장된 `generation_scope.included_skills`와 실제 `roadmap[].skill_targets`/`related_skills`를 따로 봐야 한다.

해당 69개 기술의 운영 스냅샷 원본은 확보하지 않았다. 로컬의 과거 검증 JSON에는 다른 표본(26개·49개 기술)이 있었지만, 이를 운영 사례의 원인 확정에 사용하지 않았다. 아래 수치는 **새로 작성한 고정 합성 fixture의 결과**이며 운영 정확도, 실제 채용시장 분포, 운영 사례의 정확한 재생산을 뜻하지 않는다.

현재 코드에서 재현한 결함은 다음과 같다.

- 제목에 Data Analyst가 함께 들어가면 핵심 업무가 순수 기계설계·보안인 공고도 채택된다. 반면 제목이 순수 `Mechanical Design Engineer`/`Security Analyst`인 검색 잡음은 기존 코드도 제외했다. 이 두 경우를 구분했다.
- 제조 분석 목표에 일반 분석가 공고가 연관 검색어로 채워진다. 제목 매칭 뒤 목표의 명시된 도메인을 확인하지 않았다.
- 원문 문자열 존재와 기술명 존재는 검증하지만, 회사 고객의 도구 소개도 직무 기술로 집계한다. 필수/우대 제목이 인용 바로 밖에 있으면 요구 수준을 놓친다.
- `Power BI`와 `PowerBI` 별칭이 없어 별도 기술로 집계한다. 기존 동일 ID의 공고 집계는 이미 중복을 제거했다. 이번에는 `select_jobs` 경계에서도 동일 ID 중복을 막고 회귀 테스트를 추가했다.
- 정렬은 모든 언급 공고 수와 이름 순서였다. 맥락 언급과 직접 직무의 업무·요건 근거를 구분하지 않아 상위 기술과 생성 입력에 영향을 준다.

## 경로별 추적과 변경

| 단계 | 경로 | 확인 및 변경 |
|---|---|---|
| 목표 → 검색어 | `gemini_jobs.generate_job_keywords`, `RoleInterpretation` | DB의 목표·희망 직무를 같이 전달, 최대 3개 검색어·관계 검증. fixture에서는 응답을 고정. 해석 모델/프롬프트의 실패는 이 fixture로 재현하지 않아 변경하지 않음 |
| 검색 → 공고 분류 | `himalayas._match`, `normalize_job`, `job_relevance.classify_job` | 기존 제목·토큰 매칭을 유지하면서 핵심 업무와 명시된 직무/제조 도메인의 충돌을 검사. 요구조건·회사 소개로 직무를 판정하지 않음. 일반 분석 목표의 제조 분석 공고는 연관 표본으로 보존 |
| 공고 선정 | `himalayas.select_jobs`, `_fetch_jobs` | 불일치 제외 사유, 제목, 업무 근거와 출처를 `selection_summary.decisions`에 기록. 경력/기업 다양성·직접/연관 표본 선택은 유지. 부족한 표본을 타 직무로 채우지 않음 |
| 원문 검증 | `job_skill_analysis.verify_skills`, `job_relevance.evidence_context` | 정확한 인용·위치 검증 유지. 기술이 나온 문장과 원문의 국소 제목으로 필수/우대/업무/회사 맥락 구분. 회사 맥락·부정된 요건은 인용을 보존하되 핵심 추천에서 제외. 알려진 기술명은 `technical_competency` 분류로 이름 검증을 우회할 수 없음 |
| 정규화·집계 | `normalize_skill`, `aggregate_skills` | PowerBI/MS Power BI/Microsoft Power BI → Power BI. Unicode·공백 정규화. 같은 기술의 같은 공고는 1회. SQL/PostgreSQL, Java/JavaScript, CAD/AutoCAD, CATIA/SolidWorks는 별도 제품으로 보존 |
| 정렬·경험 비교 | `skill_priority`, `current_comparison` | 추천 가능 여부 → 직접 직무의 독립 근거 공고 수 → 전체 독립 근거 공고 수 → 필수/우대 수 → 확인된 경험 순으로 비교. 단순 언급 빈도와 추천 근거 수를 별도 제공. 문서 미기재는 `not_verified` 유지 |
| 생성 입력·검증 | `capture_basis`, `focused_skills`, `model_input`, `validate_result` | 기존 12개/3개 상한 유지. 맥락뿐인 기술·인용은 생성에서 제외. 출력도 실제 전달한 기술 범위로 검증. 유효한 기술이 없으면 기존 무과금 제한 안내 사용 |
| 과목 | `available_courses`, `selected_courses` | 이미 이수한 과목과 검증된 대체과목 제외는 기존 구현이 정상. 변경 없이 신규 fixture·기존 회귀 테스트로 검증 |
| 화면 | `JobSkillAnalysis`, `RoadmapPanels` | 기존 탭 안에서 작은 표본·1개 공고 근거·선정 이유·원문 링크 안내. 전체 비교, 생성 입력 포함 여부, 실제 활동 단계 수를 분리. 서버 경험 비교 정렬 반영 |

공고의 `mentioned_job_count`/빈도는 검증된 모든 언급을 나타내고, `supporting_job_count`는 실제 업무·요건에 해당하는 독립 공고만 센다. 회사 소개의 CAD 1건과 제조 분석 업무의 CAD 2건을 섞어 필수 학습 기술로 승격하지 않는다. 필수/우대 집계는 공고별 배타적이며, 같은 공고의 반복 인용은 횟수를 늘리지 않는다. 1개 공고 기술도 임의로 삭제하지 않고 요구 수준·이유·출처를 표시한다.

## 고정 fixture와 사전 판정

[원문·고정 추출 응답·공고별 기대 판정](../apps/api/tests/fixtures/recommendation-quality/cases.json), [재생 실행기](../apps/api/tests/fixtures/recommendation-quality/evaluate.py). **제품 코드를 수정하기 전에** 12개 공고의 `Responsibilities`, `Requirements`, `Preferred`, `About the company`, 직무별 포함 여부/이유를 기록하고 수정 전 결과를 저장했다. 외부 검색·Gemini 응답은 고정하고 이후의 실제 분류·검증·집계·경험 비교·생성 입력·출력 검증 코드를 실행한다. 검색어 간 및 페이지 내 동일 ID 중복도 넣었다.

표의 ○는 기대 포함, —는 기대 제외다. 일반 분석의 상위 핵심 기술 정답은 SQL/Python/Excel/Power BI/Tableau/PostgreSQL로 미리 정했다. 제조 특화 도구는 일반 분석에서 보조 근거로 남을 수 있으나 상위 핵심 5개의 적합 판정에는 넣지 않았다. 제조 분석 목표의 정답에는 CAD/CATIA/SolidWorks를 포함한다.

| 공고 ID / 제목 | 일반 분석 | 기계설계 | 보안 | 제조 분석 | 판정 근거 |
|---|:---:|:---:|:---:|:---:|---|
| data-a / Junior Data Analyst | ○ | — | — | — | 매출 분석·대시보드. SQL/Python/Excel/Power BI 필수, Tableau 우대. CAD/CATIA/CISSP/SolidWorks는 회사 고객 소개뿐 |
| data-b / Data Analyst | ○ | — | — | — | 고객 지표 분석. PowerBI 표기 변형 포함 |
| data-c / BI Analyst | ○ | — | — | — | 매출 BI 분석. PostgreSQL과 SQL은 별개 |
| mixed-mechanical / Data Analyst / Mechanical Design Engineer | — | ○ | — | — | 제목에 분석가가 있어도 업무는 부품·조립체·3D 모델 설계뿐 |
| mechanical / Mechanical Design Engineer | — | ○ | — | — | 순수 기계설계. CAD/CATIA/SolidWorks/AutoCAD/GD&T 필수 |
| cad / CAD Designer | — | ○ | — | — | 3D 부품 설계. CAD/SolidWorks 필수, CATIA 우대 |
| mixed-security / Security Data Analyst / Security Analyst | — | — | ○ | — | 업무는 보안 경보 조사·침해 대응. SIEM/Splunk/CISSP/Python/SQL 필수 |
| security / Security Analyst | — | — | ○ | — | 순수 보안 업무. Python/SQL은 우대 |
| soc / SOC Analyst | — | — | ○ | — | 보안 관제·위협 탐지. CISSP 우대 |
| manufacturing-a / Manufacturing Data Analyst | ○ | — | — | ○ | 제조 불량 분석에 CAD 속성을 결합. CAD 필수, CATIA/SolidWorks 메타데이터 해석 우대 |
| manufacturing-b / Data Analyst - Manufacturing | ○ | — | — | ○ | 생산 데이터·대시보드. CAD 부품 속성 해석 우대 |
| sales / Sales Manager | — | — | — | — | 분석 소프트웨어 판매. Excel 언급만으로 분석가가 되지 않음 |

기계설계 목표에서 제조 데이터 분석 공고를 제외하는 이유는 CAD가 아니라 핵심 업무가 설계가 아닌 분석이기 때문이다. 반대로 제조 분석에서는 CAD 등 설계 도구가 실제 분석 맥락에 연결되므로 보존한다.

## 동일 입력의 수정 전후 결과 — fixture 기준

[수정 전 JSON](audits/recommendation-quality-2026-11-09/before.json), [수정 후 JSON](audits/recommendation-quality-2026-11-09/after.json). 상위 5개는 추천에 사용할 수 있는 기술의 표시 순서다. 적합 개수의 분모는 실제 노출된 5개다. 중복 명칭 수는 동일 기술로 사전 정의한 Power BI 표기 때문에 추가로 생긴 항목 수다.

| 목표 | 기대 공고 | 채택 공고 전→후 | 오채택 전→후 | 누락 전→후 | 상위 5 적합/분모 전→후 | 중복 명칭 전→후 |
|---|---:|---:|---:|---:|---|---:|
| 일반 데이터 분석가 | 5 | 7→5 | 2→0 | 0→0 | 3/5→5/5 | 1→0 |
| CAD 중심 기계설계 | 3 | 3→3 | 0→0 | 0→0 | 5/5→5/5 | 0→0 |
| 보안 분석가 | 3 | 3→3 | 0→0 | 0→0 | 5/5→5/5 | 0→0 |
| 제조 데이터 분석가 | 2 | 6→2 | 4→0 | 0→0 | 5/5→5/5 | 1→0 |

| 목표 | 상위 기술 5개: 수정 전 | 수정 후 |
|---|---|---|
| 일반 분석 | Python, SQL, CAD, Excel, CATIA | SQL, Python, Excel, Power BI, PostgreSQL |
| 기계설계 | CAD, CATIA, SolidWorks, AutoCAD, GD&T | CAD, SolidWorks, CATIA, AutoCAD, GD&T |
| 보안 | CISSP, SIEM, Splunk, Python, SQL | SIEM, Splunk, CISSP, Python, SQL |
| 제조 분석 | Python, SQL, CAD, CATIA, Excel | Python, SQL, CAD, Excel, Power BI |

일반 분석의 오채택은 `mixed-mechanical`, `mixed-security`다. 제조 분석은 그 둘에 일반 도메인의 `data-a`, `data-b`가 더해진다. 제조 사례에서 기술 적합도만 보면 수정 전도 5/5이므로, 공고 오채택과 함께 측정해야 한다. 수정 후 제조 CAD는 독립 공고 2개, CATIA·SolidWorks는 각각 1개 우대 근거로 남는다. 작은 표본임을 UI와 로드맵 한계에 표시한다.

## 프로젝트 경험을 바꾼 결과 — fixture 기준

아래 SQL 문서는 `I used SQL to analyze sales data.`로 고정했다. 문서 원문 검증 → 본인 확인 상태 비교 → 실제 `model_input` → 상태별 고정 생성 응답 → 실제 `validate_result`까지 실행했다. **활동/수강 선택은 공개된 결정적 모델 stub이며 실제 Gemini의 추천 성능 측정이 아니다.** 이 단계의 기존 정상 동작은 바꾸지 않았다.

| 동일 목표·공고, 경험만 변경 | 수정 전→후 학생 상태 / 활동 유형 | 검증된 활동 전→후 | 수강 후보 전→후 |
|---|---|---|---|
| 문서에 SQL 없음 | not_verified / verify_experience 유지 | SQL 경험 확인 자료 정리 유지 | sql-intro 잠정 후보 유지 |
| SQL 개인 문구는 있으나 본인 미확인 | document_supported / verify_experience 유지 | SQL 경험 확인 자료 정리 유지 | sql-intro 잠정 후보 유지 |
| 같은 SQL 근거를 본인이 확인 | confirmed_experience / deepen 유지 | SQL 분석 결과 검증 유지 | sql-advanced 유지 |
| 본인이 SQL 경험 없음으로 응답 | no_experience / learn 유지 | SQL 조회 예제 작성 유지 | sql-intro 유지 |

`sql-intro`는 SQL 입문, `sql-advanced`는 SQL 분석 프로젝트다. 경험 확인 전에는 입문 과목을 확정 학습 지시로 바꾸지 않는다. 모든 경우 `completed`와 `equivalent`는 실제 `eligible_courses`와 추천 결과에서 제외된다. 같은 과목명만 같다는 이유로 임의 동등 처리를 하지 않는다.

| 상태 | 실제 생성 입력: 수정 전 | 수정 후 |
|---|---|---|
| 문서 없음 / 본인 미확인 | Python, SQL, CAD | SQL, Python, Excel |
| SQL 확인 / 경험 없음 응답 | SQL, Python, CAD, Excel | SQL, Python, Excel, Power BI |

이 fixture에서는 수정 전 CAD가 생성 입력에도 유입된다. 사용자가 관찰한 운영 저장 결과의 생성 입력 SQL·Python·Excel과는 다른 사례다. 두 결과를 혼동하지 않는다. UI는 이제 각 기술에 **생성 입력 포함 여부와 실제 제안 활동 단계 수**를 따로 표시하며, 입력 범위 기록이 없는 과거 결과는 알 수 없다고 표시한다.

## 저장 결과 호환과 호출 한도

- 새 직무 분석 버전 `job-skills-v2`, 새 로드맵 규칙 `personalized-roadmap-v3`. 이전 버전의 현재 목표/직무에 해당하는 저장 스냅샷은 읽기 fallback으로 조회한다. 저장된 기술명·인용·답변 키를 수정하지 않는다.
- 기존 실행의 `result_json`, `basis_json`, 완료 기록을 덮어쓰지 않는다. 규칙 차이는 `is_stale`로 표시하되 문서 기준이 같으면 상세·근거·완료 체크가 그대로 보인다. 문서 삭제/재추출 시 기존 상세 제한 정책도 유지한다.
- 명시적 직무 분석 POST는 v2를 사용한다. 실패하면 이전 결과를 돌려준다. v1 근거로 새 로드맵을 생성하려는 POST는 `job_analysis_outdated`를 반환하고 기존 직무 비교 탭의 분석 재실행을 안내한다. 백그라운드 유료 업그레이드는 하지 않는다.
- 게스트 복원·페이지 진입·포커스·탭 이동·새로고침은 GET만 수행한다. 기존 `guarded_call`, 단위 예약 16, 예산/동시 호출/재시도 상한은 변경하지 않았다. 맥락 언급만 있어 생성에 쓸 기술이 없으면 기존 무과금 제한 안내로 처리한다.
- 기존 6개 화면과 결과 5탭 유지. 준비 기간 입력 없음. 공고 원문/과목 출처 링크 유지.

## 실제 검증 명령과 결과

저장소 루트에서 실행했다. API 테스트와 E2E는 임시 SQLite/합성 인증/고정 AI 응답만 사용한다. 운영 데이터와 유료 모델 호출은 없다.

```sh
# 동일 fixture의 수정 전 결과: Git의 원본 코드에서 재생
quality_baseline=$(mktemp -d /tmp/team18-quality-baseline.XXXXXX)
git archive d720ac8cb7669dd577d0340eed8684dd7275d496 apps/api/app | tar -x -C "$quality_baseline"
PYTHONPATH="$quality_baseline/apps/api/app" apps/api/.venv/bin/python \
  apps/api/tests/fixtures/recommendation-quality/evaluate.py /tmp/team18-quality-before-replay.json
cmp docs/audits/recommendation-quality-2026-11-09/before.json /tmp/team18-quality-before-replay.json

# 수정 후 재생
PYTHONPATH=apps/api/app apps/api/.venv/bin/python \
  apps/api/tests/fixtures/recommendation-quality/evaluate.py \
  docs/audits/recommendation-quality-2026-11-09/after.json

# 백엔드 전체 회귀
PYTHONPATH=apps/api/app ROADMAP_TEST_POSTGRES_URL='' ROADMAP_DB_BACKEND=sqlite \
  ROADMAP_DATABASE_URL='' GEMINI_API_KEY='' RENDER=false \
  apps/api/.venv/bin/python -m pytest apps/api/tests -q

# 프런트 단위 회귀
node --experimental-vm-modules --test apps/web/tests/unit/*.test.mjs

# 프런트 빌드 (apps/web에서 실행, 실제 배포 주소를 사용하지 않음)
ROADMAP_API_ORIGIN=https://api.example.invalid \
  NEXT_PUBLIC_SUPABASE_URL=https://job-skills-test.supabase.co \
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=test-key NEXT_PUBLIC_SUPABASE_ANON_KEY='' npm run build

# 각각 별도 터미널에서 로컬 E2E 서버 실행
apps/api/.venv/bin/python apps/api/tests/integration/guest_ui_server.py
# 아래 Next 명령은 apps/web에서 실행
ROADMAP_API_ORIGIN=http://127.0.0.1:18081 \
  NEXT_PUBLIC_SUPABASE_URL=https://job-skills-test.supabase.co \
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=test-key NEXT_PUBLIC_SUPABASE_ANON_KEY='' \
  npm run dev -- --hostname 127.0.0.1 --port 15101

# 루트에서 브라우저 회귀
node apps/web/tests/e2e/job-skills.mjs
node apps/web/tests/e2e/roadmaps.mjs
node apps/web/tests/e2e/guest-flow.mjs
git diff --check
```

| 검증 | 결과 / 로그 |
|---|---|
| 수정 전 재생 | `cmp` exit 0, 사전 기록과 바이트 단위 일치 |
| 수정 후 재생 | exit 0, 4개 목표의 기대 포함/제외 및 상위 기술 조건 충족 |
| 백엔드 전체 | [203 passed, 2 skipped, 30 subtests passed](audits/recommendation-quality-2026-11-09/api.txt). 경고 2개는 기존 SDK/TestClient deprecation |
| 프런트 단위 | [12 passed](audits/recommendation-quality-2026-11-09/web-unit.txt) |
| 빌드 | [성공, 기존 앱 6개 경로 확인](audits/recommendation-quality-2026-11-09/build.txt) |
| 공고 브라우저 | [PASS](audits/recommendation-quality-2026-11-09/browser-jobs.txt): 표본·1개 공고·출처·명시적 분석·모바일 |
| 로드맵 브라우저 | [PASS](audits/recommendation-quality-2026-11-09/browser-roadmaps.txt): 5탭, 생성 입력/활동 구별, 완료 복원, 이력, 429/409, 모바일 |
| 실제 로컬 API 게스트 브라우저 | [PASS](audits/recommendation-quality-2026-11-09/browser-guest.txt): 6화면, 계획/문서/이수 저장 복원, 제한 안내 저장, 자동 AI 없음 |

첫 전체 API 실행은 샌드박스가 로컬 포트 bind를 차단하여 서버를 쓰는 13개 테스트가 setup 오류였다. 로컬 포트 권한으로 같은 명령을 재실행해 모두 통과했다. 첫 프런트 단위 실행은 `--experimental-vm-modules` 누락으로 기존 세션 테스트 5개가 실행되지 않았고, 위 명령으로 12개 모두 통과했다. 코드 실패를 숨기기 위한 테스트 제외는 하지 않았다. 선택적 DB/네트워크 통합 테스트의 skip 사유는 아래 한계에 명시한다.

## 남은 한계

- 12개 합성 공고와 4개 목표의 회귀 지표다. 실시간 Himalayas 검색, 실제 Gemini의 목표 해석·추출·추천 의미 품질, 운영 69개 기술 결과를 재측정하지 않았다.
- 이번 직무 충돌 규칙은 데이터 분석·기계설계·보안과 제조 도메인에 한정한 보수적 영어/한국어 패턴이다. 다른 직무는 기존 동적 제목 매칭을 유지한다. 임의 언어·표현·혼합 업무에 완전한 분류를 보장하지 않는다. 불명확한 본문에서는 제목 근거만 남을 수 있다.
- 자유 서술형 `technical_competency`의 의미 타당성은 모델 판단이 남아 있다. 알려진 기술의 이름 검증 우회만 막았고, 모든 요약 역량을 문자열 일치로 해결하지 않는다. 같은 공고의 신원은 제공된 GUID 기준이므로 서로 다른 GUID로 재게시된 공고까지 동일 고용 기회라고 추정해 합치지는 않는다.
- 작은 표본을 유지하므로 제조 사례는 2개다. 한 공고의 우대 기술을 시장 전체 요구로 일반화하지 않는다.
- 테스트 2개는 격리 PostgreSQL 미설정과 실제 Gemini API 키/`GEMINI_LIVE_TEST=1` 미설정으로 건너뛰었다. 실제 PostgreSQL/배포 환경 검증은 하지 않았다. 새 SQL은 기존 테이블의 소유 계획 범위 조회뿐이며 스키마/운영 설정 변경은 없다.
- E2E의 인증과 유료 API는 합성이며, 실제 운영 인증 제공자에 접속하지 않았다. 기존 예산·소유권·동시성 테스트는 통과했다.

## 추가 회귀 수정 — main ab98413

원격과 로컬 `main`이 `ab98413cf2f0775174cac7f8cb6992634b28689c`로 일치하고 작업 트리가 깨끗한 상태에서 시작했다. `job_relevance.py`의 두 재현 사례를 수정했다.

- `source_segments`: 판정용 문자열에만 Unicode/공백/아포스트로피 정규화를 적용한다. 직선·곡선·modifier apostrophe, 대소문자, Markdown 제목/강조, `What you'll do`/`What you will do`/`What you'll be doing`을 처리한다. `About us` 다음 업무 제목에서 `context → duty`로 전환하며 원문과 인용 위치는 바꾸지 않는다.
- `evidence_context`: 독립 절을 분리하고 부정된 요건의 주어·목적어 범위에 해당 기술이 있을 때만 부정을 적용한다. 같은 요건을 공유하는 `CAD and CATIA` 목록은 유지한다. `No CAD experience is required, but SQL proficiency is required.`는 CAD `mentioned`/추천 불가, SQL `required`/추천 가능으로 검증된다. 짧은 인용이 `No`를 빠뜨려도 인용과 겹치는 원문 절을 확인하며, 다른 문장의 같은 기술 근거를 빌리지 않는다.

새 회귀는 제목 변형 9개, 부정/긍정 절 변형 8개, 공유 기술 목록·Power BI 별칭 1개, 짧은 인용·별도 문장 경계 1개로 총 19개다. 첫 18개를 수정 전 실행했을 때 **17 failed, 1 passed**로 재현했다. 수정 후 추천 품질 테스트는 기존 16개를 포함해 **35 passed**다.

실제 실행 명령:

```sh
PYTHONPATH=apps/api/app ROADMAP_TEST_POSTGRES_URL='' ROADMAP_DB_BACKEND=sqlite \
  ROADMAP_DATABASE_URL='' GEMINI_API_KEY='' RENDER=false \
  apps/api/.venv/bin/python -m pytest apps/api/tests/unit \
  apps/api/tests/integration/test_job_skill_analysis_api.py \
  apps/api/tests/integration/test_project_experience_api.py \
  apps/api/tests/integration/test_roadmap_api.py \
  apps/api/tests/integration/test_guest_guardrails.py -q
node --experimental-vm-modules --test apps/web/tests/unit/*.test.mjs
PYTHONPATH=apps/api/app apps/api/.venv/bin/python \
  apps/api/tests/fixtures/recommendation-quality/evaluate.py /tmp/team18-quality-ab98413-followup.json
cmp docs/audits/recommendation-quality-2026-11-09/after.json /tmp/team18-quality-ab98413-followup.json
git diff --check
```

결과는 백엔드 **186 passed, 1 skipped, 30 subtests passed**(5.93초), 프런트 단위 **12 passed**, `cmp`와 `git diff --check` exit 0이다. skip은 실제 Gemini API 키와 `GEMINI_LIVE_TEST=1`이 필요한 선택적 테스트이며, 경고는 기존 SDK deprecation이다. 로드맵 통합 테스트에는 이전 규칙의 저장 결과·원문 근거·완료 기록 조회, 명시적 업그레이드, 실패 시 이전 결과 보존, 조회 시 유료 호출 없음이 포함된다. 기존 4개 직무 fixture 지표는 그대로다.

이 추가 수정에서는 모델·저장 버전·프런트 코드·운영 데이터·배포 설정을 변경하지 않았다. 기존 저장 결과를 재작성하지 않으며 명시적 직무 분석 재실행에 수정된 검증 코드가 적용된다. 부정 판정은 지원하는 영어 절/요건 표현에 대한 규칙이며 임의 자연어의 완전한 의미 분석을 보장하지 않는다. 위의 최초 작업 당시 전체 테스트/E2E/빌드 결과와 이번 추가 회귀 실행 범위를 구분한다.
