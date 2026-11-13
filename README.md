# 대학생 개인화 진로 로드맵

> 최신 통합 검수 결과와 배포 적용 조건은 [게스트 서비스 검수 보고서](docs/guest-service-audit-2026-11-09.md)를 확인하세요. 과거 [인증 작업 상태](docs/auth-stage1-status.md)는 해당 단계의 기록입니다. 이번 추가 마이그레이션과 수정 코드는 아직 운영에 배포하지 않았습니다.

추천 품질 개선의 공고별 고정 fixture, 수정 전후 지표, 저장 결과 호환과 회귀 검증은 [추천 품질 진단 보고서](docs/recommendation-quality-audit-2026-11-09.md)에 정리했습니다. 이 개선은 별도 마이그레이션이나 운영 데이터 변경 없이 검토할 수 있습니다.

공모전·대외활동 탭은 저장한 진로 목표로 콘테스트코리아 실제 공고를 추천합니다. 문서·직무 분석·로드맵 생성 없이 이용하며, 기간·참가 대상과 원문 근거를 확인한 공고만 표시합니다. [구현·실제 API·배포 검증 기록](docs/activity-recommendations.md)을 참고하세요.

대학생이 진로 목표와 학업 정보를 저장하고, 문서와 이수 과목을 확인한 뒤 Gemini 기반 수강 후보와 실행 로드맵을 생성하는 서비스입니다. 운영은 Supabase Auth, SQLite 개발 환경은 세션 쿠키로 소유자를 구분합니다. 기존 분석 확인 화면에서 프로젝트 경험을 분석·확인·수정하고, 직무 역량 비교 탭에서 Himalayas 요구 기술과 원문 근거를 비교합니다. 로드맵 실행 이력과 작업 완료 체크를 저장하며 입력·근거 변경 시 이전 기준임을 표시합니다. [5단계 구현·검증·운영 적용 안내](docs/personalized-roadmaps.md)를 참고하세요. 새 PostgreSQL 마이그레이션과 배포는 별도 적용이 필요합니다.

## 구성과 주요 기능

- Next.js / React 프런트엔드: `/`, `/input/basic`, `/input/documents`, `/input/courses`, `/input/review`, `/result`.
- FastAPI / Uvicorn 백엔드: 계획 생성·이어쓰기·수정, 학교·학과·교육과정 조회, 이수 선택과 확인, 수강 후보 추천, PDF/DOCX/TXT 문서 관리.
- 운영 저장소: Supabase PostgreSQL(서버의 psycopg 3)과 비공개 Supabase Storage. Gemini는 백엔드에서만 호출합니다. 개발과 격리 테스트는 SQLite와 로컬 파일 저장소도 지원합니다.
- 브라우저 → Vercel Next.js `/api/*` rewrite → Render FastAPI → PostgreSQL / Storage / Gemini. API는 쓰기 요청 Origin, 운영 Supabase Bearer 인증(로컬 SQLite는 HttpOnly 세션 쿠키), 계획 소유권을 검사합니다.

문서 원본과 추출 결과는 버전 관리되며, 부분 추출 확인·재추출·삭제를 지원합니다. PostgreSQL의 문서 작업은 lease로 중복 처리를 방지하고 후속 요청에서 복구합니다. Render Free에서는 요청이 없을 때 즉시 실행이 보장되지 않습니다. 스캔 PDF와 DOCX 본문 이미지에는 선택적 Google Cloud Vision OCR을 지원하며 기본값은 비활성화입니다. [설정·비용 보호·마이그레이션·검증 안내](docs/google-vision-ocr.md)를 확인하세요.

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
| `ROADMAP_OCR_PROVIDER` | 기본 `none`; 승인된 설정 후 `google_vision` |
| `ROADMAP_OCR_MONTHLY_UNIT_LIMIT`, `ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT` | 미국 태평양 시간 월 최대 900단위(DST 반영), 문서 최대 50단위 |
| `GOOGLE_APPLICATION_CREDENTIALS` | 백엔드 전용 서비스 계정/ADC 파일 경로 |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | 서버 전용 Gemini 키와 모델 (기본 모델 `gemini-3.5-flash`) |
| `CONTESTKOREA_API_KEY` | 서버 전용 콘테스트코리아 Basic DEMO v1.1 키 |
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

Render Root Directory는 `apps/api`, Build는 `pip install -r requirements.txt`, Start는 `uvicorn app.main:app --host 0.0.0.0 --port $PORT`입니다. Vercel Root Directory는 `apps/web`이며 기존 Next.js `/api/*` rewrite를 사용합니다. `front/`의 스텝업 React 시안을 `apps/web`의 운영 화면에 적용했습니다. 상단 메뉴·사이드바·대시보드와 반응형 카드 UI는 새 디자인을 사용하며, Google/게스트 인증과 문서 처리·경험 분석·과목 선택·로드맵 저장은 기존 API 연결을 유지합니다. `front/`는 독립 실행 가능한 디자인 참고본으로 남아 있으며 Vercel 배포 경로는 변경하지 않습니다. 현재 PostgreSQL TLS `sslmode=require`는 암호화하지만 서버 인증서를 검증하지 않는 임시 기술 부채입니다. 연결 정책은 별도 검토가 필요합니다. 실제 운영 이력과 저장소 마이그레이션 버전 차이는 [배포 안내](docs/render-deployment.md)에 기록되어 있으며 자동 수정하지 않습니다.

## Gemini 채용공고 기술 스택 분석

저장된 목표·희망 직무 → Gemini 검색어 → Himalayas 최대 20개 공고 → Gemini 배치 추출 → 서버 근거 검증·고유 공고 빈도 집계가 연결되어 있습니다. `POST /api/roadmap-inputs/{request_id}/job-skill-analysis`에 `{}`를 보내며, 기존 결과 화면의 직무 역량 비교 탭에서 사용자가 분석 실행 버튼을 눌러 호출합니다. 탭 이동·새로고침은 저장된 근거만 조회합니다. 기존 수강 추천과 GET 공고 조회는 유지됩니다.

설정, 응답 계약, 실제 세 직무 검증 명령과 제한은 [기술 스택 분석 문서](docs/job-skill-analysis.md)를 참고하세요. 4단계부터 검증 결과를 계획별 서버 스냅샷으로 재사용합니다.

## 프로젝트 경험과 직무 요구 비교

기존 **05. 분석 내용 확인**에서 외부 Gemini 처리 안내를 읽고 ‘프로젝트 경험 분석 실행’을 누릅니다. 현재 유효한 문서 본문만 분석하며, 각 경험에 맞아요·수정할게요·잘 모르겠어요·경험 없음 답변을 저장할 수 있습니다. **직무 역량 비교** 탭에서 프로젝트 근거와 공고 근거를 함께 확인합니다. 자료에서 찾지 못한 경험은 경험 없음으로 판단하지 않습니다.

추가 환경변수는 없습니다. **DB 마이그레이션은 필요합니다.** SQLite는 앱 시작 시 `006_project_experiences.sql`을 적용하고, 운영 PostgreSQL은 `20261109051837_project_experience_comparison.sql`을 별도 적용해야 합니다. 운영 DB 자동 초기화나 마이그레이션 자동 실행은 하지 않습니다. 저장 구조·API 예시·적용 방법·테스트·실제 연동 기록은 [프로젝트 경험 비교 문서](docs/project-experience-comparison.md)를 참고하세요.

## 게스트 통합 검수 수정 (2026-11-09)

외부 직무 근거가 없으면 AI 호출 없이 제한 안내 로드맵을 저장합니다. 기술 요구와 수강 후보를 만들어 채우지 않습니다. 당시 준비 중이던 공모전·대외활동은 위 실데이터 추천으로 연결했습니다. AI 요청의 동시 실행·재실행 간격·사용자별 및 전역 사용량은 DB에 저장해 제한합니다. 과목 중복 제외는 동일 ID와 명시적으로 검증된 동일·대체 관계만 사용합니다. 페이지 크기는 기본 20개, 10/20/50개 선택이며 검색은 300ms 지연 처리합니다.

추가 PostgreSQL 마이그레이션 `20261109073304_guest_service_guardrails.sql`을 먼저 적용해야 합니다. 자세한 검증 범위, 한도, 근거 관계 등록 조건, 운영 미검증 항목은 위 검수 보고서를 확인하세요.
