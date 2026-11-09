# 대학생 개인화 진로 로드맵

> 인증 통합 작업이 진행 중입니다. 현재 변경은 마이그레이션 및 실제 인증 검증이 완료되지 않아 배포할 수 없습니다. 설정과 제한은 [인증 작업 상태](docs/auth-stage1-status.md)를 확인하세요. 아래의 기존 쿠키 기반 실행 설명은 이전 구현 기준입니다.

대학생이 진로 목표와 학업 정보를 저장하고, 문서와 이수 과목을 확인한 뒤 Gemini 기반 수강 후보를 조회하는 서비스입니다. 계획은 세션 쿠키로 소유자를 구분합니다. 기존 직무 역량 비교 탭에서는 Gemini가 생성한 검색어로 Himalayas 공고를 수집하고 근거가 검증된 기술 스택을 표시합니다. 개인 역량 비교와 로드맵 생성은 준비 중입니다.

## 구성과 주요 기능

- Next.js / React 프런트엔드: `/`, `/input/basic`, `/input/documents`, `/input/courses`, `/input/review`, `/result`.
- FastAPI / Uvicorn 백엔드: 계획 생성·이어쓰기·수정, 학교·학과·교육과정 조회, 이수 선택과 확인, 수강 후보 추천, PDF/DOCX/TXT 문서 관리.
- 운영 저장소: Supabase PostgreSQL(서버의 psycopg 3)과 비공개 Supabase Storage. Gemini는 백엔드에서만 호출합니다. 개발과 격리 테스트는 SQLite와 로컬 파일 저장소도 지원합니다.
- 브라우저 → Vercel Next.js `/api/*` rewrite → Render FastAPI → PostgreSQL / Storage / Gemini. API는 쓰기 요청 Origin, HttpOnly 세션 쿠키와 계획 소유권을 검사합니다.

문서 원본과 추출 결과는 버전 관리되며, 부분 추출 확인·재추출·삭제를 지원합니다. PostgreSQL의 문서 작업은 lease로 중복 처리를 방지하고 후속 요청에서 복구합니다. Render Free에서는 요청이 없을 때 즉시 실행이 보장되지 않습니다. OCR은 제공하지 않습니다.

## 폴더와 문서

실제 구조와 책임은 [폴더 구조](docs/FOLDER_STRUCTURE.md), API·데이터 계약은 실행 중인 `/docs`, `/openapi.json`과 [AI 통합 계약](docs/ai-integration-contract.md)을 참고하세요. [배포 안내](docs/render-deployment.md), [DB 연결](docs/supabase-backend-connection.md) 및 [문서 이관 기록](docs/phase3-document-migration.md)은 운영 판단과 과거 단계 기록을 구분해 읽습니다. 기획·목업·테스트 자료와 완료된 개발 기록은 `docs/`에 보존합니다.

## 로컬 실행

Node.js 20.9 이상과 Python 3이 필요합니다. 기존 `apps/api/.env`는 덮어쓰지 마세요. 아래 명령은 로컬 SQLite를 사용합니다. 빈 학교 테이블에는 기본적으로 **가상 개발 데이터**가 적재됩니다. 기존 로컬 DB와 파일을 지우지 않습니다.

```sh
python3 -m venv apps/api/.venv
apps/api/.venv/bin/pip install -r apps/api/requirements-dev.txt
(cd apps/api && ROADMAP_DB_BACKEND=sqlite ROADMAP_INSECURE_LOCAL_COOKIE=1 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000)
```

다른 터미널에서:

```sh
cd apps/web
npm ci
npm run dev
```

`http://localhost:3000`을 엽니다. SQLite 파일은 기본적으로 `apps/api/var/roadmap.sqlite3`, 문서 원본은 `apps/api/var/files`에 있습니다. PostgreSQL에서는 SQLite 마이그레이션과 자동 개발 seed가 실행되지 않습니다.

## 환경변수

비밀값은 백엔드 또는 배포 플랫폼에만 설정하며 Git과 브라우저에 넣지 않습니다. 예시는 `apps/api/.env.example`에 있습니다.

| 변수 | 용도 |
| --- | --- |
| `ROADMAP_DB_BACKEND` | `postgres` 또는 로컬 기본값 `sqlite` |
| `ROADMAP_DATABASE_URL` | 서버 전용 PostgreSQL 연결 문자열 |
| `ROADMAP_APP_ORIGIN` | 쓰기 요청을 허용할 정확한 프런트엔드 출처 |
| `ROADMAP_POSTGRES_DOCUMENTS_ENABLED` | PostgreSQL 문서 기능 활성화 플래그 |
| `SUPABASE_URL`, `SUPABASE_STORAGE_BUCKET` | 비공개 문서 Storage 설정 |
| `SUPABASE_SECRET_KEY` | 서버 전용 Storage 키. 기존 `SUPABASE_SERVICE_ROLE_KEY`도 지원 |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | 서버 전용 Gemini 키와 모델 (기본 모델 `gemini-3.5-flash`) |
| `ROADMAP_API_ORIGIN` | Next.js 서버 rewrite 대상. 운영 빌드에는 HTTPS 출처 필요 |
| `ROADMAP_DB_PATH`, `ROADMAP_FILE_STORAGE_PATH` | 로컬 SQLite와 문서 경로 |
| `ROADMAP_AUTO_SEED_DEV` | SQLite 가상 개발 자료 자동 seed; 운영에서는 `0` |
| `ROADMAP_INSECURE_LOCAL_COOKIE` | 로컬 HTTP에서만 `1`. 운영에서는 사용하지 않음 |
| `ROADMAP_MAX_DOCUMENT_BYTES`, `ROADMAP_MAX_DOCUMENTS` | 업로드 크기와 문서 개수 제한 |
| `ROADMAP_PROXY_MAX_BODY_BYTES` | Next.js 프록시 본문 상한 |
| `ROADMAP_API_HOST`, `ROADMAP_API_PORT`, `PORT` | 로컬 바인딩과 Render 포트 |

## 테스트와 배포

```sh
(cd apps/api && ROADMAP_DB_BACKEND=sqlite ROADMAP_AUTO_SEED_DEV=0 .venv/bin/python -m pytest -q)
(cd apps/web && ROADMAP_API_ORIGIN=https://api.example.com npm run build)
```

백엔드 테스트는 임시 SQLite와 모킹을 기본으로 사용합니다. 선택적 PostgreSQL 문서 테스트는 명시적인 로컬 전용 DB와 초기화 보호 조건을 요구합니다. 운영 DB나 Storage를 초기화하지 마세요. 브라우저 E2E 스크립트 `apps/web/tests/e2e/p5-flow.mjs`는 별도로 실행한 격리 API·웹 서버와 Brave가 필요합니다.

Render Root Directory는 `apps/api`, Build는 `pip install -r requirements.txt`, Start는 `uvicorn app.main:app --host 0.0.0.0 --port $PORT`입니다. Vercel Root Directory는 `apps/web`이며 기존 Next.js `/api/*` rewrite를 사용합니다. 현재 PostgreSQL TLS `sslmode=require`는 암호화하지만 서버 인증서를 검증하지 않는 임시 기술 부채입니다. 연결 정책은 별도 검토가 필요합니다. 실제 운영 이력과 저장소 마이그레이션 버전 차이는 [배포 안내](docs/render-deployment.md)에 기록되어 있으며 자동 수정하지 않습니다.

## Gemini 채용공고 기술 스택 분석

저장된 목표·희망 직무 → Gemini 검색어 → Himalayas 최대 20개 공고 → Gemini 배치 추출 → 서버 근거 검증·고유 공고 빈도 집계가 연결되어 있습니다. `POST /api/roadmap-inputs/{request_id}/job-skill-analysis`에 `{}`를 보내며, 기존 결과 화면의 직무 역량 비교 탭에서 자동 호출합니다. 기존 수강 추천과 GET 공고 조회는 유지됩니다.

설정, 응답 계약, 실제 세 직무 검증 명령과 제한은 [기술 스택 분석 문서](docs/job-skill-analysis.md)를 참고하세요. 추가 환경변수나 DB 변경은 없습니다.
