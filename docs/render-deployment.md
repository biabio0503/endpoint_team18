# Render 배포 준비 상태

**미완성: PostgreSQL의 문서 API는 503을 반환하며 Supabase Storage 연결과 문서 작업 마이그레이션이 없다.** 전체 기능 배포 완료로 취급하지 않는다. 운영 DB에 마이그레이션을 실행하거나 기존 과목 데이터를 변경하지 않았다.

기존 Render Web Service의 설정을 대시보드에서 직접 확인한다. 이 저장소 변경만으로 기존 서비스 설정이 바뀌지는 않는다.

| 항목 | 설정 |
| --- | --- |
| Root Directory | `apps/api` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Python | Environment에 `PYTHON_VERSION=3.14.7` |
| Health Check Path | `/api/health` |

Render의 Environment에 `ROADMAP_DB_BACKEND=postgres`, `ROADMAP_DATABASE_URL`, `ROADMAP_AUTO_SEED_DEV=0`, `ROADMAP_APP_ORIGIN`을 설정한다. `ROADMAP_APP_ORIGIN`은 브라우저에서 사용하는 프론트엔드의 정확한 HTTPS 출처다. 추천 기능에는 `GEMINI_API_KEY`, 필요시 `GEMINI_MODEL`도 서버에 설정한다. Render가 `PORT`를 제공하며 앱은 `0.0.0.0`에 바인딩한다. 비밀값을 Git이나 프론트엔드에 넣지 않는다.

Supabase Dashboard의 Connect에서 **Session pooler** 연결 문자열과 포트 5432를 확인한다. 요청마다 독립 연결을 열고 닫으며 `sslmode=verify-full`을 강제한다. 2026-11-08 로컬 검증에서는 이 프로젝트의 pooler가 로컬 CA 파일로 연결되었지만 로컬 시스템 신뢰 저장소만으로는 `tls_verification_failed`가 발생했다. Render의 신뢰 저장소와 서비스 설정은 별도로 확인해야 한다.

인증서가 필요한 경우 Supabase Dashboard에서 CA를 받아 Render 서비스의 **Secret Files**에 `supabase-ca.crt`로 등록하고 `PGSSLROOTCERT=/etc/secrets/supabase-ca.crt`를 설정한다. 실제 파일 경로는 Render 대시보드에서 확인한다. 이 애플리케이션은 비어 있지 않은 `PGSSLROOTCERT`를 DSN의 `sslrootcert`보다 우선 적용하므로 이전 Mac 경로가 DSN에 남아 있어도 지정한 Secret File을 사용한다. 가능하면 DSN에서 이전 경로도 제거한다. 지정하지 않으면 DSN의 경로 또는 libpq 기본 설정을 사용한다. `PGSSLROOTCERT=system`은 해당 libpq가 지원할 때 시스템 CA를 사용하지만 이 프로젝트에서 신뢰 체인이 검증되는지 실제 환경에서 확인해야 한다. CA 파일, 연결 문자열과 비밀값을 Git에 커밋하지 않는다.

시작 로그의 `tls_ca_missing`, `tls_ca_unreadable`, `tls_ca_invalid_pem`은 각각 파일 부재, 읽기 실패, PEM 검증 실패를 뜻한다. `tls_verification_failed`는 신뢰 체인, `tls_hostname_mismatch`는 인증서 호스트 이름을 확인한다. 일반 연결 오류 분류만으로 Render 장애 원인을 단정하지 않는다. 배포 후 `/api/health/db`와 학교·학과·카탈로그 조회를 확인하고, 쓰기 테스트는 격리된 DB에서 수행한다.

Next.js 서버 빌드 환경에 `ROADMAP_API_ORIGIN=https://<render-service>.onrender.com`을 설정하고 다시 빌드한다. 브라우저는 `/api/*`를 사용한다. 프록시를 거쳐 `Set-Cookie`, 후속 `Cookie`, 원래 브라우저 `Origin`이 전달되는지 실제 HTTPS 환경에서 확인한다. 허용 출처는 하나이며 프리뷰 출처는 별도 설정이 필요하다.

자동 배포가 켜진 경우 GitHub 연결 브랜치에 push하면 Render가 새 빌드와 배포를 시작한다. 배포 로그에서 의존성 설치, 설정 오류 및 포트 바인딩을 확인한다. `/api/health`는 프로세스 생존만, `/api/health/db`는 DB 연결도 확인한다. DB 오류 메시지는 내부 연결 정보를 노출하지 않는다. 학교·학과·과목 목록과 계획 생성, 수정 및 복원을 확인한다. 실제 운영 DB에서 파괴적 SQL을 실행하지 않는다.

Free 서비스는 유휴 시 중지될 수 있고 로컬 파일은 영구 보관되지 않는다. 현재 문서 워커는 SQLite에서만 실행되고 파일도 로컬에 저장한다. 외부 자료 수집은 기존 fixture 도구만 확인되며 정기 수집 서비스로 배포되지 않는다.

로컬 SQLite 개발: `cd apps/api`, 가상환경에서 `pip install -r requirements.txt`, `ROADMAP_DB_BACKEND=sqlite ROADMAP_INSECURE_LOCAL_COOKIE=1 uvicorn app.main:app --host 127.0.0.1 --port 8000`. 프론트엔드는 `apps/web`에서 `npm install` 후 `npm run dev`; 기본 프록시는 `http://127.0.0.1:8000`이다.
