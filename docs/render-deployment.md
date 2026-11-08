# Render 배포 준비 상태

**Phase 3 코드는 구현됐으며 최초 배포에서는 문서 플래그를 OFF로 유지한다.** 운영 문서 테이블·Storage 버킷 적용과 실서비스 쓰기 검증은 아직 승인 전이다. [운영 사전 검사](phase3-production-preflight.md)와 [문서 이관 절차](phase3-document-migration.md)를 따른다.

기존 Render Web Service의 설정을 대시보드에서 직접 확인한다. 이 저장소 변경만으로 기존 서비스 설정이 바뀌지는 않는다.

| 항목 | 설정 |
| --- | --- |
| Root Directory | `apps/api` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Python | Environment에 `PYTHON_VERSION=3.14.7` |
| Health Check Path | `/api/health` |

Render의 Environment에 `ROADMAP_DB_BACKEND=postgres`, `ROADMAP_DATABASE_URL`, `ROADMAP_AUTO_SEED_DEV=0`, `ROADMAP_APP_ORIGIN`을 설정한다. `ROADMAP_APP_ORIGIN`은 브라우저에서 사용하는 프론트엔드의 정확한 HTTPS 출처다. 추천 기능에는 `GEMINI_API_KEY`, 필요시 `GEMINI_MODEL`도 서버에 설정한다. Render가 `PORT`를 제공하며 앱은 `0.0.0.0`에 바인딩한다. 비밀값을 Git이나 프론트엔드에 넣지 않는다.

Supabase Dashboard의 Connect에서 **Session pooler** 연결 문자열과 포트 5432를 확인한다. 요청마다 독립 연결을 열고 닫으며 `sslmode=require`를 강제한다. DSN의 `sslrootcert`와 `PGSSLROOTCERT`는 사용하지 않으므로 CA Secret File은 필요하지 않다. 기존 Render 서비스의 `PGSSLROOTCERT`와 CA Secret File을 제거해도 된다. 연결 문자열과 비밀번호는 Git에 커밋하지 않는다.

**임시 보안 수준:** `require`는 TLS 암호화를 요구하지만 서버 인증서와 호스트 이름을 검증하지 않는다. 따라서 서버를 사칭하는 중간자 공격을 방어하지 못한다. 해커톤 MVP 이후에는 신뢰할 CA를 설정하고 `verify-full`로 복원해야 한다. libpq의 기본 CA 파일 자동 사용을 방지하기 위해 연결별로 `/dev/null` 아래의 존재할 수 없는 경로를 내부 지정한다. 이 경로에 인증서를 만들 필요는 없다.

배포 후 `/api/health/db`와 학교·학과·카탈로그 조회를 확인한다. `tls_required`는 TLS가 아닌 연결을 거부한 경우다. 쓰기 테스트는 격리된 DB에서 수행한다.

Next.js 서버 빌드 환경에 `ROADMAP_API_ORIGIN=https://<render-service>.onrender.com`을 설정하고 다시 빌드한다. 브라우저는 `/api/*`를 사용한다. 프록시를 거쳐 `Set-Cookie`, 후속 `Cookie`, 원래 브라우저 `Origin`이 전달되는지 실제 HTTPS 환경에서 확인한다. 허용 출처는 하나이며 프리뷰 출처는 별도 설정이 필요하다.

자동 배포가 켜진 경우 GitHub 연결 브랜치에 push하면 Render가 새 빌드와 배포를 시작한다. 배포 로그에서 의존성 설치, 설정 오류 및 포트 바인딩을 확인한다. `/api/health`는 프로세스 생존만, `/api/health/db`는 DB 연결도 확인한다. DB 오류 메시지는 내부 연결 정보를 노출하지 않는다. 학교·학과·과목 목록과 계획 생성, 수정 및 복원을 확인한다. 실제 운영 DB에서 파괴적 SQL을 실행하지 않는다.

Free 서비스는 유휴 시 중지될 수 있고 로컬 파일은 영구 보관되지 않는다. PostgreSQL 문서 원본은 비공개 Supabase Storage에 저장되며 작업은 DB lease와 후속 문서 요청으로 재개한다. 상시 작업 실행은 보장되지 않는다. 최초 Environment에는 `ROADMAP_POSTGRES_DOCUMENTS_ENABLED=0`, `SUPABASE_URL`, `SUPABASE_STORAGE_BUCKET=roadmap-documents`, 서버 키 변수 하나만 설정한다. DB·버킷 점검 후 승인된 활성화 단계에서만 플래그를 `1`로 바꾼다.

로컬 SQLite 개발: `cd apps/api`, 가상환경에서 `pip install -r requirements.txt`, `ROADMAP_DB_BACKEND=sqlite ROADMAP_INSECURE_LOCAL_COOKIE=1 uvicorn app.main:app --host 127.0.0.1 --port 8000`. 프론트엔드는 `apps/web`에서 `npm install` 후 `npm run dev`; 기본 프록시는 `http://127.0.0.1:8000`이다.
