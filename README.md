# 대학생 개인화 진로 로드맵

개인화 진로 입력과 Gemini 기반 수강 후보 기능을 제공하는 로컬 웹앱입니다. Node.js 20.9 이상과 Python 3이 필요합니다. 기본 설정은 SQLite이며, 기본 입력과 과목 기능은 PostgreSQL을 선택할 수 있습니다.

먼저 API 가상환경과 문서 파싱 라이브러리를 설치합니다.

```sh
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -r apps/api/requirements.txt
```

API 서버는 학교 데이터가 전혀 없는 DB에 가상 개발용 기준 데이터를 자동으로 적재합니다. 실제 대학이나 교육과정 자료가 아닙니다. 서버 시작 전에 수동으로 적재하려면 다음을 실행합니다.

```sh
python3 apps/api/app/scripts/seed_dev.py
```

이후 터미널 두 개에서 각각 실행합니다.

```sh
(cd apps/api && ROADMAP_INSECURE_LOCAL_COOKIE=1 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000)
```

```sh
cd apps/web
npm ci
npm run dev
```

http://localhost:3000 에서 새 계획을 만들거나 이어서 작성할 수 있습니다. 최초 실행 시 `apps/api/var/roadmap.sqlite3`에 마이그레이션이 적용됩니다. 입력은 이 파일에 보관되므로 삭제하지 않으면 서버 재시작 후에도 유지됩니다. 세션은 30일 동안 유효하며 쿠키 삭제·만료 시 해당 세션의 계획에 다시 접근할 수 없습니다.

## DB 초기화와 마이그레이션

SQLite 모드의 API 시작과 가상 과목 데이터 적재 시 `apps/api/migrations`의 미적용 SQL을 순서대로 적용하고 `schema_migrations`에 기록합니다. 기존 DB는 자동 삭제하지 않습니다. 서버를 시작하지 않고 마이그레이션만 적용할 수도 있습니다.

```sh
PYTHONPATH=apps/api/app apps/api/.venv/bin/python -c 'from repositories.p1 import migrate; migrate()'
```

기본 DB는 `apps/api/var/roadmap.sqlite3`, 문서 원본은 `apps/api/var/files`입니다. 다른 DB를 사용하려면 모든 관련 명령에서 `ROADMAP_DB_PATH`를 동일하게 지정하고, 문서 복원에는 해당 파일 저장 경로도 함께 보존해야 합니다. 파일 저장소는 공개 정적 디렉터리가 아니며 저장 경로를 직접 웹에 노출하지 않습니다. 마이그레이션에는 자동 롤백 명령이 없으므로 기존 데이터를 지우지 않고 백업과 새 마이그레이션으로 관리합니다.

## 설정

| 환경변수 | 기본값 | 용도 |
|---|---|---|
| `GEMINI_API_KEY` | 미설정 | 백엔드에서만 사용하는 Gemini API 키 |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Gemini 모델 ID |
| `ROADMAP_DB_BACKEND` | `sqlite` | `sqlite` 또는 `postgres` 선택 |
| `ROADMAP_DATABASE_URL` | 미설정 | PostgreSQL 백엔드 전용 연결 문자열 |
| `ROADMAP_DB_PATH` | `apps/api/var/roadmap.sqlite3` | SQLite DB 파일 위치 |
| `ROADMAP_AUTO_SEED_DEV` | `1` | 학교 테이블이 비어 있으면 가상 개발용 기준 데이터를 자동 적재. 실제 자료를 사용하는 환경에서는 `0`으로 비활성화 |
| `ROADMAP_API_HOST` / `ROADMAP_API_PORT` | `127.0.0.1` / `8000` | API 바인드 주소와 포트 |
| `ROADMAP_API_ORIGIN` | `http://127.0.0.1:8000` | Next.js의 서버 측 API 프록시 대상. Next 빌드·실행 환경에 설정 |
| `ROADMAP_APP_ORIGIN` | `http://localhost:3000` | 쓰기 요청의 허용 Origin. 브라우저에서 접근하는 정확한 출처와 일치해야 함 |
| `ROADMAP_INSECURE_LOCAL_COOKIE` | 미설정 | 로컬 HTTP 테스트에서만 `1`로 설정. 기본 쿠키에는 Secure 속성이 적용됨 |
| `ROADMAP_FILE_STORAGE_PATH` | `apps/api/var/files` | 비공개 원본 파일 저장 경로 |
| `ROADMAP_MAX_DOCUMENT_BYTES` / `ROADMAP_MAX_DOCUMENTS` | `10485760` / `10` | 파일당 바이트와 계획당 문서 개수 제한 |
| `ROADMAP_PROXY_MAX_BODY_BYTES` | `11534336` | Next.js 프록시 본문 상한. 파일 크기 제한과 multipart 여유를 합친 값 이상으로 설정 |

세션 토큰은 서버가 안전한 난수로 만들고 DB에는 해시만 저장하므로 별도 서명 비밀키는 사용하지 않습니다. 향후 필요한 비밀은 환경의 비밀 저장소에서 주입하고 저장소에 커밋하지 않습니다. 운영 HTTPS에서는 `ROADMAP_INSECURE_LOCAL_COOKIE`를 설정하지 않습니다. 현재 서버는 로컬 개발용입니다. PostgreSQL 모드에서는 P1/P2만 연결되며 P3/P4, 클라우드 파일 저장소와 배포 구성은 후속 작업입니다. [PostgreSQL 연결 안내](docs/supabase-backend-connection.md)를 참고하세요. DB 접근은 `apps/api/app/repositories/p1.py`, 환경 설정은 `apps/api/app/config.py`, 웹 API 주소는 `apps/web/next.config.mjs`에 분리되어 있습니다.

`apps/web`에서 `npm run build`, `npm start`로 프로덕션 빌드를 확인할 수 있습니다. 백엔드 통합 테스트는 저장소 루트에서 `apps/api/.venv/bin/python -m unittest discover -s apps/api/tests/integration -p 'test_*.py' -v`로 실행합니다. SQLite 개발 seed의 학교·학과·과목은 가상 데이터입니다. 문서 업로드와 일반 텍스트 추출을 사용할 수 있습니다. 수강 후보 외 AI 분석은 준비 중입니다. [진행 문서](docs/non-ai-mvp-progress.md)를 참고하세요.

## Gemini 수강 후보

[Google AI Studio](https://aistudio.google.com/app/apikey)에서 Gemini API 키를 발급하고 `apps/api/.env.example`을 `apps/api/.env`로 복사해 백엔드에만 `GEMINI_API_KEY`를 설정합니다. 기존 `.env`가 있다면 덮어쓰지 말고 변수만 추가합니다. `GEMINI_MODEL`로 계정에서 사용 가능한 모델 ID를 바꿀 수 있습니다. 기본 `gemini-3.5-flash`는 Google 문서상 구조화 출력을 지원하는 안정 모델이지만 계정별 사용 가능 여부는 실제 연결로 확인해야 합니다. 키와 `.env`는 Git과 프론트엔드에 포함하지 않습니다. 위 설치 명령에 공식 `google-genai`와 Pydantic이 포함됩니다.

기본 정보와 과목 이수 상태를 저장한 뒤 결과 화면의 **수강 후보** 탭에서 분석을 실행합니다. 서버가 세션 소유권을 확인하고 저장된 목록과 진로 정보만 모델에 전달합니다. 이수 신고를 제외하고 반환 ID를 현재 목록과 대조해 최대 5개를 표시합니다. 설명이 없으면 과목명으로 추론하며 실제 강의 내용을 보장하지 않습니다. 목록이 미확인인 경우 미선택을 미이수로 확정하지 않습니다. 응답은 입력 버전이 바뀌면 거부하며 저장하지 않아 화면을 새로 열면 다시 분석해야 합니다. 모델 호출 시 진로 목표, 희망 직무, 학교·학과·학년, 과목명이 Google에 전송됩니다. 문서 내용은 전송하지 않습니다.

`POST /api/roadmap-inputs/{request_id}/course-recommendations`에 기존 세션 쿠키와 `{}`를 보냅니다. 쓰기 요청에는 기존 `Origin` 검증이 적용됩니다. 성공 응답 예시는 다음과 같습니다. `courses`는 기존 과목 조회와 같은 필드 및 `completion_state`를 사용하며 추천 순서입니다. `status`는 `ok` 또는 목록 자체가 비었을 때 `empty_catalog`입니다. `ok`의 빈 배열은 추천 결과가 없거나 이수 신고를 제외한 후보가 없는 경우입니다.

```json
{"courses": [{"course_id": "실제 ID", "course_name": "과목명", "is_completed": false, "completion_state": "unconfirmed"}], "status": "ok", "catalog_id": "목록 ID", "input_revision": 1, "review_status": "unconfirmed", "career_goal": "데이터 분석"}
```

키 누락, 인증, 사용량 제한, 시간 초과, 모델 호출 실패, 잘못된 응답은 각각 오류 코드와 비성공 HTTP 상태로 반환합니다. 일시적 제한·서버 오류·시간 초과는 최대 3회 시도합니다. 실패 시 가짜 추천으로 대체하지 않습니다. DB 연결 실패 및 목록 미선택도 별도 오류입니다. 키가 없어도 일반 서버 기능은 실행됩니다.

```sh
# 모킹 테스트; 실제 외부 호출 없음
apps/api/.venv/bin/python -m unittest discover -s apps/api/tests/unit -v
# API 키가 설정된 경우에만 실제 모델 및 구조화 응답 확인 (요금이 발생할 수 있음)
GEMINI_LIVE_TEST=1 apps/api/.venv/bin/python -m unittest discover -s apps/api/tests/unit -p test_course_recommendations.py -v
```

현재 추천은 선택한 단일 DB의 현재 과목 목록만 대상으로 하며 SQLite 사용자 데이터와 별도 Supabase 데이터를 자동으로 합치거나 이전하지 않습니다. 실제 교육과정의 품질과 모델 추천의 정확성은 데이터 및 모델에 따라 달라집니다. 직무 역량, 문서 분석, 전체 로드맵, 공모전 추천은 구현 범위에 포함되지 않습니다.

## 문서 처리

PDF, DOCX, UTF-8 TXT를 계획당 최대 10개, 파일당 최대 10MiB까지 업로드할 수 있습니다. PDF는 최대 100페이지, DOCX는 압축 해제 크기 30MiB와 1,000개 항목까지 허용합니다. 추출 텍스트는 최대 100만 문자이며 잘린 경우 일부 추출로 표시합니다. 이 제한들은 처리 안전을 위한 로컬 기본값입니다.

원본은 `ROADMAP_FILE_STORAGE_PATH` 아래 서버가 만든 식별자 이름으로 비공개 저장하고, 텍스트·위치와 버전은 SQLite에 보관합니다. 서버 시작 시 함께 실행되는 로컬 워커가 대기 작업과 삭제 정리를 처리하며, 중단된 작업은 lease 만료 후 재개합니다. 이미지·스캔의 OCR은 제공하지 않습니다. 일부 문서에서 이미지, 머리글·바닥글, 각주나 포함 개체 등은 읽히지 않을 수 있으며 확인된 제한은 화면에 표시합니다. 문서를 삭제하면 즉시 목록에서 제외하고 원본과 추출 이력을 정리합니다. 정리 실패는 기록되어 재시도합니다.

## 외부 자료 수집: 내부 fixture 검증

현재 실제 채용·공모전·대외활동 출처와 접근 정책은 정해지지 않았습니다. 연결된 운영 사이트와 네트워크 수집 기능은 없으며, 다음 명령은 가상 도메인 `fixtures.invalid`과 저장소 안의 가상 데이터만 사용합니다. 사용자 화면이나 공개 API에서 수집을 실행하지 않습니다.

```sh
apps/api/.venv/bin/python apps/api/app/scripts/external_collect.py init-fixtures
apps/api/.venv/bin/python apps/api/app/scripts/external_collect.py enqueue fixture-jobs --fixture-set v1 --job-key example-1
apps/api/.venv/bin/python apps/api/app/scripts/external_collect.py work --drain
apps/api/.venv/bin/python apps/api/app/scripts/external_collect.py inspect fixture-jobs
```

`enqueue`가 반환한 작업 ID는 `status <작업 ID>`로 조회하고, 실패 또는 부분 작업은 `retry <작업 ID>`로 다시 대기시킨 뒤 `work`를 실행합니다. 같은 출처·작업 키·범위의 재등록은 기존 작업을 반환하며, 같은 키에 다른 범위를 사용하면 거부합니다. `work`는 기본적으로 한 건, `--drain`은 대기 중인 전체 작업을 처리하고 실패한 작업이 있으면 종료 코드 1을 반환합니다. 실행 중 중단된 작업은 120초 점유 기한이 지난 뒤 다음 `work`에서 다시 처리됩니다.

다른 fixture 출처는 `fixture-activities`, `fixture-pdf`입니다. `fixture-jobs`의 `--fixture-set`은 `v1`, `v2`, `empty`, `partial`, `failure`를 지원합니다. PDF는 페이지별 일반 텍스트만 추출하며 명시 필드를 자동 분류하지 않아 작업 상태가 부분 확보로 남습니다. HTML fixture는 제목·문단·목록 태그의 명시 필드만 보관합니다. fixture 원문은 건당 2MiB, 작업당 100건으로 제한하고 PDF는 100페이지까지 읽습니다. 기한·시간대나 조건이 불명확하면 추정하지 않습니다. 실제 출처를 연결하려면 해당 기관의 공식 접근 방식과 이용 조건·범위·요청 제한을 확인하고 별도 어댑터와 설정을 구현해야 합니다.

## 통합 검증

다음 명령은 저장소 루트에서 실행합니다.

```sh
apps/api/.venv/bin/python -m unittest discover -s apps/api/tests/integration -p 'test_*.py' -v
npm run build --prefix apps/web
npm run check --prefix apps/web
node --check apps/web/tests/e2e/p5-flow.mjs
```

웹은 JavaScript 프로젝트이며 별도 TypeScript 타입 검사나 ESLint 설정·스크립트는 현재 없습니다. `npm run check`는 Next 설정 파일의 구문 검사이고 `npm run build`는 웹 컴파일을 확인합니다. 개발 서버와 빌드를 동시에 실행하면 같은 `.next`를 사용하므로, 빌드 전 개발 서버를 종료하거나 빌드 후 다시 시작하세요.

실제 브라우저 사용자 흐름은 Node.js 22 이상의 내장 WebSocket과 다음의 별도 DB·파일 저장소·포트로 확인할 수 있습니다. 테스트용 계획과 문서를 만들며 브라우저에는 Brave 기본 경로를 사용합니다. 다른 Chromium 계열 브라우저는 `P5_BROWSER`로 실행 파일 경로를 지정하세요.

```sh
mkdir -p /tmp/roadmap-p5
ROADMAP_DB_PATH=/tmp/roadmap-p5/roadmap.sqlite3 apps/api/.venv/bin/python apps/api/app/scripts/seed_dev.py
```

첫 번째 터미널:

```sh
(cd apps/api && ROADMAP_DB_PATH=/tmp/roadmap-p5/roadmap.sqlite3 ROADMAP_FILE_STORAGE_PATH=/tmp/roadmap-p5/files ROADMAP_INSECURE_LOCAL_COOKIE=1 ROADMAP_APP_ORIGIN=http://localhost:15100 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 19100)
```

두 번째 터미널:

```sh
cd apps/web
ROADMAP_API_ORIGIN=http://127.0.0.1:19100 npm run dev -- --port 15100
```

세 번째 터미널의 저장소 루트:

```sh
node apps/web/tests/e2e/p5-flow.mjs
```

테스트는 실제 파일 업로드와 두 브라우저 세션, 두 탭의 충돌, 저장 실패·복구, 새로고침과 이어서 작성, 과목 선택과 AI 준비 화면을 확인합니다. 학교·과목과 외부 자료는 가상 fixture입니다. 브라우저 주소와 디버깅 포트는 각각 `P5_WEB_ORIGIN`, `P5_CDP_PORT`로 바꿀 수 있습니다. AI 연동을 위한 현재 데이터 경계와 미확정 사항은 [AI 연동 준비 문서](docs/ai-integration-contract.md)를 참고하세요.
