# 5단계 — 개인화 수강 후보와 실행 로드맵

2026-11-09, `main` / `83a030e`에서 구현했다. 작업 시작 시 GitHub 원격 main과 로컬 HEAD가 일치함을 확인했다. 운영 마이그레이션·배포·migration repair/reset은 실행하지 않았다.

기존 `Result.js`의 다섯 탭을 유지하면서 준비 상태, 실행 로드맵, 수강 후보를 하나의 저장된 실행 결과로 연결했다. 기존 직무 역량 비교의 원문·사용자 답변 기능과 공모전·대외활동 자리도 유지한다. 과거 독립 수강 추천 API의 요청과 응답 계약은 그대로다.

## API

모든 경로의 `{id}`는 인증된 사용자의 계획이다. 기존 SQLite 세션/Supabase Bearer 인증, 소유권 검사, 쓰기 Origin 검사를 사용한다.

| 메서드 | 경로 | 동작 |
|---|---|---|
| POST | `/api/roadmap-inputs/{id}/roadmap` | 새 생성 또는 동일 기준 재사용 |
| GET | `/api/roadmap-inputs/{id}/roadmap` | 최신 유효 결과 우선, 없으면 이전 결과/상태 |
| GET | `/api/roadmap-inputs/{id}/roadmaps` | 상세 원문 없는 실행 메타데이터 이력 |
| GET | `/api/roadmap-inputs/{id}/roadmaps/{run_id}` | 해당 실행 상세, 현재 기준과 차이 표시 |
| PATCH | `/api/roadmap-inputs/{id}/roadmaps/{run_id}/tasks/{task_id}` | 해당 실행의 완료 체크 |

생성 요청:

```json
{"expected_input_revision":12,"refresh":false}
```

새 실행은 HTTP 201, 같은 기준 재사용은 200과 `reused:true`다. `refresh:true`는 기존 성공 실행을 남기고 새 실행을 생성한다. POST를 제외한 조회·진행 체크에서는 Gemini/Himalayas를 호출하지 않는다. UI도 입력 변경이나 조회만으로 로드맵 생성 요청을 보내지 않는다.

진행 체크 요청:

```json
{"is_completed":true,"expected_progress_version":0}
```

응답은 진행 상태를 포함한 실행 전체다. 작업마다 `is_completed`, `progress_version`, `updated_at`, 전체 `progress:{completed,total}`을 제공한다. 완료 체크는 기술 숙련도 판정에 사용하지 않으며 `input_revision`, `course_selection_revision`, 계획 수정 시각을 바꾸지 않는다. 같은 작업의 동시 변경은 한 요청만 성공하고 나머지는 `409 progress_conflict`가 된다. 새 실행에 완료 상태를 복사하지 않는다.

주요 오류는 `422 needs_job_analysis`, `422 insufficient_job_evidence`, `409 revision_conflict`, `409 generation_in_progress`, `409 generation_expired`, `409 evidence_unavailable`, `503 gemini_rate_limited`, `502 gemini_invalid_response`다. 다른 소유자의 계획/실행/작업은 404, 인증 없음은 401이다. 오류 HTTP 상태와 성공 결과의 자료 제한 상태 `partial`은 다르다.

## 입력·개인화·Gemini 계약

`current_comparison` → `current_project`의 현재 문서/추출/답변 검증을 재사용한다. 과목은 기존 `CourseRepository`로 현재 학교·학과·카탈로그 관계를 확인한 뒤 읽는다. 공고 수집, 직무 기술 추출, 프로젝트 경험 추출을 다시 실행하지 않는다.

전체 생성 기준에는 다음을 저장하고 해시한다.

- 기본 입력과 입력 버전, 학년·학점·GPA(점수화하지 않음).
- 직무 스냅샷 ID·분석 시각·상태, 고유 공고별 요구 집계와 검증 근거.
- 문서 기준 해시, 프로젝트 규칙/모델 버전, 현재 추출 버전·분석 ID·상태·제외 사유.
- 기술별 비교 상태, 사용자 확인/수정 답변과 검증된 짧은 근거.
- 과목 목록 내용·설명·출처·범위·완전성, 이수 선택과 목록 밖 보존 이력, 확인 시각·상태·선택 버전.
- 생성 규칙 버전과 운영자가 설정한 Gemini 모델.

서버가 준비 상태를 확정한다. AI에게 상태의 재분류를 맡기지 않는다.

| 비교 상태 | 준비 상태 | 허용 실행 방향 |
|---|---|---|
| `confirmed_experience` | 확인된 경험 | 기존 경험 적용·검증·정리, 불필요한 기초 반복 제외 |
| `document_supported` | 본인 확인 필요 | 실제 개인 수행과 근거 확인 |
| `needs_confirmation` | 확인 필요 | 답변/수행 경험 확인 |
| `not_verified` | 자료 부족, 확인 필요 | 경험 확인; 경험 없음으로 변환 금지 |
| `no_experience` | 추가 학습 검토 후보 | 기초 실습 → 적용 → 검증·기록 검토 |

생성 입력은 경험 없음/확인된 경험을 우선하여 최대 12개 기술과 미확인 기술 최대 3개를 선택한다. 각 기술의 전체 집계는 유지하되 공고 인용 최대 2개와 프로젝트 근거 최대 3개를 전달한다. 전체 프로젝트 문서·채용 HTML·파일명·세션은 전달하지 않는다. 서버의 전체 준비 상태는 모든 비교 기술을 유지하며, 실제 생성에 사용한 기술 범위는 `generation_scope`와 준비 상태 탭에 표시한다. 공고 빈도만으로 학생의 우선순위를 확정하지 않는다.

`google-genai`, 기존 `GEMINI_API_KEY`, 기존 `GEMINI_MODEL`을 사용한다. 이번 실검증에서도 설정된 `gemini-3.5-flash-lite`를 유지했다. 한 요청에서 과목 후보와 실행 단계를 함께 생성한다. 요청당 공급자 호출은 1회, 타임아웃은 기존 60초이며 SDK 및 서비스 자동 재시도는 없다. 429 이후 같은 계획의 새 생성은 60초간 제한한다. 기존 유효 결과 조회/재사용은 가능하다.

Pydantic 출력은 `GeneratedRoadmap`이다.

- `recommended_courses`: 최대 5개. 실제 `course_id`, `related_skills`, `evidence_refs`, 정확한 과목 설명 구절 또는 과목명 `course_evidence`, 추천 이유·개인화 이유, 과목 역할, 제한된 확신도.
- `roadmap`: 1~5단계(기본 지시 3~5). 단계 ID·연속 순서·제목·목적·이유·기술과 학생 상태/활동 유형·관련 후보 과목 ID·선행 단계·근거·한계.
- 단계별 `tasks`: 1~3개. 고유 ID, `task_type`, 제목, 실제 행동, 완료 기준, 결과물. 기간·날짜·주차 출력 필드는 없다.

최종 API 응답에는 서버가 계산한 준비 상태, 현재 기준 과목명/코드/학점, 과목 출처·설명 추론 여부, 실행 메타데이터, 근거 제한, 완료 상태를 추가한다. AI 생성 이유와 활동은 추천 의견으로 구분한다.

## 검증과 동시성

과목 필터·ID 검증·중복 제거·최대 5개 규칙을 기존 수강 추천과 공유한다. 새 API는 존재하지 않는/이미 이수한 과목, 중복 과목, 무관한 기술/다른 근거, 사용자 상태 변경, 잘못된 학습 방향, 없는 단계/추천 과목 참조, 순환·역순 의존, 중복 작업/빈 완료 기준을 거부한다. 모든 추천 연결에는 해당 기술의 서버 비교 근거가 필요하다.

과목 설명이 없으면 이름에 의한 추론과 제한된 확신도를 서버에서 표시한다. 미확인 이수 선택은 미이수가 아닌 잠정 후보다. partial은 현재 목록 범위만 확인한 것으로 표시한다. unavailable은 과목 후보 없이 가능한 활동을 생성한다. 과거 목록 밖 이수 기록을 삭제하거나 이름으로 병합하지 않는다. 개설·수강 가능·공식 선수관계·졸업요건은 미확인이다.

모델의 자유 문장에도 미확인 경험을 학습 활동으로 바꾸는 흔한 오류, 강의/수강을 통한 검증되지 않은 내용 주장, 공고 빈도로 최우선/필수 역량을 단정하는 표현을 보수적으로 거부한다. 이는 자연어 의미를 완벽히 증명하는 검사는 아니다. 근거 존재 검증과 AI 의견의 교육적 적합성은 구분하며, 과목 내용과 활동은 사용자가 검토해야 한다.

SQLite에서는 `BEGIN IMMEDIATE`, PostgreSQL에서는 `REPEATABLE READ`와 소유 계획 행 잠금을 사용한다. 생성 예약 시 입력값·버전·시각을 바꾸지 않는 PostgreSQL 행 갱신으로 대기 중 생성 요청이 최신 MVCC 스냅샷을 다시 읽게 한다. serialization/deadlock은 DB 읽기 트랜잭션만 제한적으로 재시도하며 Gemini 호출은 재시도하지 않는다.

`roadmap_runs`의 `WHERE status='generating'` 유니크 인덱스가 계획당 하나의 진행 중 생성을 보장한다. 3분 lease는 프로세스 종료 시 후속 요청에서 복구 가능하다. 외부 호출 전 commit하고, 응답 후 전체 기준 해시·lease를 재검사한다. 입력 버전뿐 아니라 카탈로그 내용, 새 분석 완료, 스냅샷 교체, 문서 기준이 달라도 이전 입력의 성공 결과를 저장하지 않는다. 실패는 실행 상태만 기록하고 이전 성공 결과를 보존한다.

문서 삭제·재추출·상태 변경으로 `document_basis`가 달라지면 과거 실행의 상세 JSON과 완료 체크 접근을 제한한다. 역사 조회는 문서 원문을 포함하지 않는 메타데이터만 반환한다. 보수적으로 문서 추가/상태 변경에서도 제한할 수 있다. 데이터베이스에는 과거 JSON이 보존되므로 서버 관리자의 별도 보존/삭제 정책은 후속 운영 범위다.

## 마이그레이션 — 적용 대상 엄격 분리

| 대상 | 파일 | 적용 방식 |
|---|---|---|
| SQLite | `apps/api/migrations/007_personalized_roadmaps.sql` | SQLite 앱 시작 시 기존 migration runner가 적용 |
| Supabase PostgreSQL | `supabase/migrations/20261109061229_personalized_roadmaps.sql` | 운영 승인 후 별도 적용; 앱 시작 시 실행하지 않음 |
| PostgreSQL 확인 | `supabase/checks/roadmap_preflight.sql` | 타입·FK·인덱스·RLS·권한 읽기 전용 확인 |

`roadmap_runs`와 `roadmap_task_progress`만 추가한다. 기존 테이블/데이터 재생성이나 초기화는 없다. SQLite는 JSON/Timestamp를 TEXT로, PostgreSQL은 JSONB/TIMESTAMPTZ/BOOLEAN으로 정확히 분리했다. 실행은 기존 `roadmap_inputs`에 FK CASCADE, 진행은 실행에 FK CASCADE와 `(run_id,task_id)` PK로 연결된다. `catalog_id`와 이전 스냅샷 기준은 역사 값으로 보존하며 갱신/삭제될 수 있는 현재 스냅샷에 FK로 종속시키지 않는다. 이력·캐시·진행 중 조회용 인덱스를 둔다.

Supabase CLI `migration new personalized_roadmaps`로 파일을 생성했다. public 두 테이블 모두 RLS를 켜고 PUBLIC/anon/authenticated 접근을 회수했다. 브라우저 직접 접근 정책은 만들지 않으며 서버 DB 역할이 기존 소유권 검사를 수행한다. [Supabase 공식 RLS 안내](https://supabase.com/docs/guides/database/postgres/row-level-security).

운영 적용은 이 작업에서 실행하지 않았다. 기존 migration 이력과 4단계 PostgreSQL 스키마, 백업, 서버 DB 역할을 확인한 뒤 **해당 환경에서 사용하는 한 가지 이력 관리 방식**으로 새 파일만 적용한다. SQLite 디렉터리의 SQL을 운영에 보내지 않는다. 직접 SQL을 관리하는 환경의 명령은 다음과 같다.

```sh
# 별도 운영 승인 후에만 실행. 연결 문자열을 출력하지 않는다.
psql "$ROADMAP_DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file supabase/migrations/20261109061229_personalized_roadmaps.sql
psql "$ROADMAP_DATABASE_URL" -v ON_ERROR_STOP=1 \
  --file supabase/checks/roadmap_preflight.sql
```

Supabase CLI 이력 관리 환경에서는 `supabase migration list --help`, `supabase db push --help`로 설치 버전의 명령을 확인하고 적용 목록을 검토한다. 위 직접 SQL과 CLI 적용을 중복 수행하지 않는다. repair/reset으로 이력 불일치를 자동 정리하지 않는다. 마이그레이션 적용 뒤 API/웹을 별도로 배포하고 실제 로그인한 테스트 계정으로 생성·재조회·완료 체크·소유권을 확인한다. 동기 생성의 60초 요청을 수용하도록 Render/Vercel 프록시 제한도 확인한다.

## 검증

```sh
PYTHONPATH=apps/api/app ROADMAP_DB_BACKEND=sqlite ROADMAP_AUTO_SEED_DEV=0 \
  apps/api/.venv/bin/python -m pytest apps/api/tests -q -rs
(cd apps/web && node --experimental-vm-modules --test tests/unit/*.test.mjs)
(cd apps/web && ROADMAP_API_ORIGIN=https://api.example.com npm run build)
```

백엔드 전체 179 passed, 2 skipped, 기존 subtest 30개 통과. 새 API 시나리오 14개는 격리 SQLite와 PostgreSQL 양쪽에서 실행했다. SQL 경험 확인/없음/자료 부족 구분, 동일 이름 다른 ID, 이수 과목 제외·목록 밖 보존, 설명/확인 상태 한계, 환각 참조·순환·빈 활동·잘못된 학습 방향 거부, 저장/캐시/진행 복원, 모델 호출 중 수정, 새 분석 완료·카탈로그 변경·직무 갱신, 삭제/재추출 차단, 타인 접근, 동시 생성/진행, lease 만료 복구, 429 보존을 검증한다. 기존 Himalayas, 공고 추출, 프로젝트 분석/확인, 독립 수강 추천, 인증, 문서·이수 토글 회귀도 포함한다. 전체 테스트에서 건너뛴 PostgreSQL 통합 검사는 별도 실행으로 통과했으며, 기존 독립 수강 추천의 opt-in 실호출 테스트는 건너뛰었다. 새 로드맵 실제 호출 검증은 아래 별도 스크립트로 수행했다.

PostgreSQL은 새 임시 로컬 클러스터(UTF-8, TLS, PostgreSQL 18.6)의 `team18_document_test`에서 모든 PostgreSQL migration을 적용하고 기존 문서·프로젝트 시나리오 및 새 로드맵 시나리오, JSONB/TIMESTAMPTZ·FK·인덱스·RLS·권한을 검증했다. 기존 로컬 DB나 운영 DB를 초기화하지 않았다. 선택적 PostgreSQL 통합 테스트 재현은 다음과 같으며, **초기화해도 되는 새 로컬 테스트 DB에만** 사용한다.

```sh
ROADMAP_TEST_POSTGRES_URL=postgresql://USER@127.0.0.1:PORT/team18_document_test \
ROADMAP_ALLOW_TEST_DB_RESET=1 apps/api/.venv/bin/python -m pytest \
  apps/api/tests/integration/test_documents_postgres.py -q
```

프런트 단위 테스트 11개 및 브라우저 3개 시나리오(`roadmaps.mjs`, `project-experiences.mjs`, `job-skills.mjs`) 통과. 브라우저는 가상 인증/API를 사용한다. 새 시나리오는 5개 탭, 명시적 생성, 새로고침 후 체크 복원, 재사용, 입력 변경·과목 제외, 과거 이력, 409/429 보존, 진행 충돌, 삭제 문서 차단, 390px 화면을 검증한다. 실제 DB/API 저장은 위 백엔드 통합과 실제 Gemini 테스트에서 별도로 검증했다. Next.js 운영 빌드 통과.

```sh
cd apps/web
NEXT_PUBLIC_SUPABASE_URL=https://job-skills-test.supabase.co \
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=test-key \
ROADMAP_API_ORIGIN=http://127.0.0.1:8000 npm run dev -- --port 15101
# 별도 터미널에서 각각 실행
node tests/e2e/roadmaps.mjs
node tests/e2e/project-experiences.mjs
node tests/e2e/job-skills.mjs
```

## 실제 Gemini 검증

[공유 가능한 검증 요약](roadmap-live-verification.json)을 보존했다. 전체 로컬 보고서는 `/tmp/team18-roadmap-live-final.json`이다. 이 테스트의 사용자 답변과 이수 선택은 합성이며, 실제 학생의 경력으로 보고하지 않는다. 실제 과목 기준 자료만 읽기 전용으로 복사했으며 운영 개인 데이터는 가져오지 않았다. 기존 실제 Himalayas/Gemini 분석 결과를 재사용해 3·4단계 AI를 다시 호출하지 않았다.

최종 검증은 설정된 `gemini-3.5-flash-lite`로 **2회** 생성했다. 개발 중 스키마 오류/잘못된 모델 출력을 진단한 호출은 이 최종 2회와 별개다. `title`을 스키마 메타데이터와 혼동해 제거하던 기존 전송 문제를 수정했고, 검증되지 않은 학습 단정·잘못된 참조 응답은 성공으로 저장하지 않았다. 최종 두 응답은 서버 검증과 수동 내용 확인을 통과했다.

| 항목 | 실제 결과 |
|---|---|
| 자료 | 기존 검증된 해외 공고 분석, 실제 교육과정 68과목, 프로젝트 문서 없음 |
| A: SQL 경험 없음 | 데이터베이스 등 3과목, SQL 기초 실습 → 적용/검증과 미확인 Python/도구 경험 확인, 3단계 4작업 |
| C: SQL 판단 보류 + 이전 후보 이수 | 이전 3개 과목 ID 제외, SQL/Python/Power BI 경험 확인, 3단계 3작업 |
| 상태 구분 | A의 SQL은 learning_candidates, C의 SQL은 skills_to_verify |
| 이력·재조회 | 저장 결과 유지, 동일 기준 POST/GET 추가 AI 호출 0회 |
| 완료 체크 | 새로 조회해도 1개 완료 복원, 입력 버전 변화 없음 |
| 제한 | 두 실행 모두 프로젝트 자료 없음/직무 부분 분석으로 `partial` |

SQL 경험 **확인**과 Python 경험 확인이 있는 A/B 비교는 자동 모의 API 테스트로 검증했다. 실제 호출 비교는 A/C다. 실제 없는 프로젝트 근거를 만들어 SQL 확인 상태를 꾸미지 않았다.

재현 스크립트는 기존 검증 공고 JSON과 실제 기준 자료 export JSON을 명시적으로 받는다. 임시 SQLite에만 저장하고, API 키/모델 외에는 운영 DB 설정을 사용하지 않는다. 입력 파일이 없거나 SQL 검증 근거가 없으면 자료를 만들어 대신하지 않는다.

```sh
apps/api/.venv/bin/python apps/api/app/scripts/roadmap_live.py \
  --job-snapshot /tmp/team18-job-skills-retest-20261109-0504.json \
  --catalog /tmp/team18-roadmap-real-catalog.json --compare \
  --output /tmp/team18-roadmap-live-final.json
```

남은 운영 조건은 별도 PostgreSQL migration/배포, 서버 역할 접근 확인, 실제 로그인 경로 점검이다. Gemini 할당량과 동기 HTTP 타임아웃, 보수적인 검증으로 인한 응답 거부 가능성, 자연어 추천의 의미 정확성, 과목 설명·실제 개설 정보 부재는 한계로 남는다. 외부 큐, 이전 실행 완료 상태 계승, 학기/기간 계산은 이번 범위에 넣지 않았다.

## 주요 파일

- API/저장: `apps/api/app/api/routes/roadmaps.py`, `repositories/roadmaps.py`, `main.py`, PostgreSQL 충돌 분류용 `repositories/postgres.py`.
- 생성/검증: `services/gemini_roadmap.py`, `roadmap_generation.py`, `roadmap_schemas.py`. 공통 과목 규칙은 `course_recommendations.py`, 전송 스키마 보정은 `gemini_jobs.py`.
- 화면: 기존 `apps/web/src/features/roadmap/Result.js`, 새 `RoadmapPanels.js`, 최소 스타일 추가.
- DB: SQLite `007_personalized_roadmaps.sql`, PostgreSQL `20261109061229_personalized_roadmaps.sql`, 읽기 전용 preflight.
- 테스트: `test_roadmap_generation.py`, `roadmap_scenario.py`, `test_roadmap_api.py`, PostgreSQL·OpenAPI·기존 무자동생성 회귀 갱신, `roadmaps.mjs`, `roadmap.mock.mjs`, 기존 직무 E2E 갱신.
- 실제 검증/문서: `scripts/roadmap_live.py`, 본 문서, `roadmap-live-verification.json`, README.
