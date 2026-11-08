# 로컬 Python 백엔드의 PostgreSQL 연결

연결 실패 로그에는 비밀값 대신 `authentication_failed`, `dns_error`, `connection_timeout`, `network_unreachable`, `tls_ca_error`, `tls_verification_failed`, `tls_hostname_mismatch`, `invalid_dsn` 또는 `connection_failed`가 표시된다. 분류는 드라이버 메시지에 의존하므로 일반 코드로 남는 경우도 있다. DNS 또는 네트워크 오류는 Session pooler 사용 여부와 IPv4/IPv6 경로를 점검한다. CA 파일은 PEM 형식이어야 하며 Render Secret Files를 사용한다면 예를 들어 `PGSSLROOTCERT=/etc/secrets/supabase-ca.crt`를 설정한다. 연결 문자열의 `sslrootcert`가 환경변수보다 우선하므로 이전 로컬 경로를 제거해야 한다. `sslrootcert=system`은 이를 지원하는 libpq에서 시스템 신뢰 저장소를 사용한다. 호스트 이름과 CA 검증은 드라이버가 연결 시 수행하며 `verify-full`을 유지한다. 분류만으로 실제 장애 원인을 확정할 수는 없다.

## 현재 상태

P1/P2의 실제 PostgreSQL 연결 및 API 검증을 완료했다. 백엔드 연결 방식은 **Session pooler**이며 `verify-full`로 서버 인증서를 검증했다. `SELECT 1`과 지정 교육과정 조회, 테스트 세션·계획의 쓰기 및 동시성 검증에 성공했다. 기존 기준 과목 데이터는 수정하지 않았다.

## 설정과 실행

1. 저장소 루트에서 `python3 -m venv apps/api/.venv` 및 `apps/api/.venv/bin/pip install -r apps/api/requirements.txt`를 실행한다. 드라이버는 `psycopg[binary]==3.2.13`, 환경 파일 로더는 `python-dotenv==1.1.1`로 고정되어 있다.
2. 기본 SQLite는 별도 설정 없이 `ROADMAP_INSECURE_LOCAL_COOKIE=1 apps/api/.venv/bin/python apps/api/app/main.py`로 실행한다. `ROADMAP_DB_PATH`로 파일 경로를 변경할 수 있다. SQLite의 기존 마이그레이션과 개발용 자동 seed는 유지된다.
3. PostgreSQL을 사용하려면 `apps/api/.env.example`을 `apps/api/.env`로 복사하고 `ROADMAP_DB_BACKEND=postgres`, `ROADMAP_DATABASE_URL`에 Dashboard > Connect에서 복사한 실제 연결 문자열, `ROADMAP_AUTO_SEED_DEV=0`을 설정한다. 기존 환경변수가 `.env`보다 우선한다. `.env`는 Git 제외 대상이며 백엔드에만 둔다. URL이나 자격 증명을 저장소와 프론트엔드에 넣지 않는다.
4. IPv4 전용 개발 환경에서는 Dashboard의 **Session pooler** 연결을 권장한다. IPv6 direct 연결이 가능한 경우 direct를 사용할 수 있다. Dashboard의 값을 그대로 사용하고 호스트·사용자·포트를 추측하지 않는다. 서버 인증서 검증을 위해 드라이버는 `sslmode=verify-full`을 적용한다. 신뢰할 수 있는 CA가 시스템에 없다면 Dashboard에서 받은 CA 파일을 안전하게 보관하고 연결 문자열의 `sslrootcert`로 지정한다. 자세한 연결 방식은 [Supabase 연결 문서](https://supabase.com/docs/guides/database/connecting-to-postgres)를 참고한다.
5. 같은 API 실행 명령을 사용한다. PostgreSQL 시작 시 연결 및 `SELECT 1`을 확인한다. 누락 또는 연결 오류는 비밀값 없는 메시지로 종료된다. PostgreSQL에서는 SQLite SQL 001~005를 자동 적용하지 않으며 `ROADMAP_AUTO_SEED_DEV` 값과 관계없이 가상 seed는 실행하지 않는다. `seed_dev.py`도 PostgreSQL에서는 거부한다.

## 변경 파일

- `apps/api/app/config.py`, `apps/api/.env.example`, `apps/api/requirements.txt`: 백엔드 선택, 백엔드 전용 환경 설정 및 의존성.
- `apps/api/app/repositories/postgres.py`, `p1.py`, `p2.py`: psycopg dict 행과 바인딩 어댑터, P1/P2 SQL의 boolean 호환성 및 PostgreSQL 행 잠금. 기존 SQLite 경로를 유지한다.
- `apps/api/app/main.py`: 숫자·시각 직렬화, 읽기 스냅샷, 쓰기 행 잠금, 안전한 오류, PostgreSQL 문서 기능 미연결 응답 및 SQLite 전용 워커/seed.
- `apps/api/app/scripts/seed_dev.py`, `external_collect.py`: PostgreSQL에서 SQLite 전용 seed와 외부 수집 실행 차단.
- `apps/api/tests/integration/test_postgres_adapter.py`, `README.md`: 경계 테스트와 실행 안내.

계획 변경과 이수 선택·확인은 트랜잭션 내 소유자와 계획 행을 `FOR UPDATE`로 잠근 뒤 버전을 확인한다. 과목 목록 조회는 repeatable-read 읽기 전용 트랜잭션을 사용한다. 코드는 기존 `?` 바인딩을 PostgreSQL 어댑터에서 `%s`로 바꾸며 SQLite 전용 SQL은 PostgreSQL로 보내지 않는다. TEXT 식별자를 UUID로 변환하지 않고 `course_code` NULL을 허용한다. 과목 이름을 이용한 병합은 하지 않는다. `theory_hours`와 `practice_hours`는 PostgreSQL의 과목 목록 API에 포함된다. SQLite에는 해당 컬럼이 없어 두 값을 `null`로 반환한다.

## 검증 결과

- Supabase 관리 도구에서 읽기 전용 `SELECT 1`: 성공. 지정한 `seoultech`, `seoultech-cse`, `seoultech-cse-2026-major-v1` 기준 학교 1, 학과 1, 목록 1, 과목 68행. 1학기 35, 2학기 33, 전공필수 7, 전공선택 61; 과목 코드 NULL 68. 기준 데이터는 변경하지 않았다.
- SQLite 기존 API·seed·외부 fixture 통합 테스트: 19개 통과. 기본 입력·복원, 토글·확인, 0개 확인, 버전 충돌, 타 세션 접근 거부 및 동시 요청은 SQLite에서 검증했다.
- PostgreSQL 경계 단위 테스트: 6개 통과. DSN 누락 및 드라이버 예외의 비밀값 없는 오류, 매개변수 바인딩/행 잠금 SQL, `Decimal`·시각 직렬화, 마이그레이션·seed 차단을 모의 검증했다. 실제 PostgreSQL 타입 왕복이나 동시성 테스트는 아니다.
- `npm run check`, `npm run build`, Python `compileall`: 성공. 별도 lint/typecheck 스크립트는 없고 Next 빌드의 검사 단계가 통과했다.
- 실제 psycopg / Session pooler: `SELECT 1` 성공. 학교 → 학과 → 목록과 68과목 API 조회 성공. `course_code` NULL 허용, PostgreSQL boolean·timestamptz·numeric 및 JSON 응답 처리 확인.
- 실제 API: 새 세션·계획 생성, 기본 정보 저장과 재조회·이어쓰기 성공; 과목 ON/OFF를 API와 DB에서 재조회해 확인했다. 0개 선택 확인과 선택 변경 시 확인 해제, 이전 revision의 409, 다른 세션의 GET/PATCH 404가 통과했다. 같은 버전의 동시 변경 2건은 각각 200과 409를 반환했다. PostgreSQL 문서 엔드포인트는 503을 반환했다.
- 실제 검증은 임시 Python HTTP 클라이언트로 로컬 `Handler`를 실행하여 수행했다. 테스트로 만든 계획 ID는 `0b709399-be98-4612-ab39-1bb9946a4078`, `d2090cc9-a435-4f61-afec-eda231037077`이며 해당 테스트 세션 및 계획은 DB에 남아 있다. 첫 계획의 진로 목표는 `STEP4 연결 검증`이다. 둘째 계획은 타 세션 소유권 검증용이다. 기준 데이터 변경이나 테스트 데이터 삭제는 수행하지 않았다.

## 후속 범위

PostgreSQL에는 P3 문서 및 P4 외부 수집 테이블이 없다. PostgreSQL 모드의 문서 엔드포인트는 `503 feature_unavailable`이며 워커와 외부 수집 CLI는 실행하지 않는다. P3/P4를 사용하려면 해당 PostgreSQL 마이그레이션, 트랜잭션/lease 동시성 및 접근 제어를 별도로 설계하고 검증해야 한다. 문서 원본은 여전히 SQLite 모드의 로컬 파일 저장소에 있으므로 향후 파일 저장 어댑터와 데이터 이관도 필요하다. 현재 세션 소유권은 백엔드에서 검사하며 Supabase Auth/RLS를 새로 구성하지 않았다.

## 통합 재검증 — 2026-11-08

| 항목 | 결과 | 확인 범위 |
| --- | --- | --- |
| PostgreSQL 연결 | 성공 | `ROADMAP_DB_BACKEND=postgres`, Session pooler의 psycopg `SELECT 1`, 연결의 TLS 활성 상태, 코드의 `sslmode=verify-full` 확인 |
| 기준 목록 | 성공 | 대상 학교 1, 학과 1, 2026학년도 목록 1, 강좌 68; 1학기 35, 2학기 33 |
| 강좌 세부 정보 | 성공 | 68개 HTTP 응답의 과목명·학년·학기·이수구분·학점·이론·실습 값을 같은 시점에 조회한 DB 행과 각각 대조; 모든 값이 일치하고 해당 필드의 NULL은 없었다. DB 값이 공식 원본 교육과정과 일치하는지에 대한 독립 검증은 수행하지 않았다. |
| HTTP API | 성공 | 새 계획 2건 생성, 기본 정보 저장·조회·이어쓰기, 학교·학과·목록 조회, 이수 ON/OFF 및 DB 재조회, 0개 확인 및 선택 변경에 따른 확인 해제 |
| 소유권과 충돌 | 성공 | 타 세션 GET/PATCH 404, 이전 입력·선택 버전 409, 같은 버전의 동시 변경 결과 200과 409 |
| 임시 데이터 정리 | 성공 | 이번 실행에서 생성한 세션·계획 2건과 그 선택 상태만 트랜잭션으로 삭제하고 계획 미존재를 확인했다. 기존 사용자 계획은 삭제하지 않았다. 대상 68개 강좌의 검증 전후 메타데이터 해시가 일치했다. |
| SQLite 회귀 | 성공 | `ROADMAP_DB_BACKEND=sqlite ... python -m unittest discover ...` 25개 통과. 주의: 이 회귀 테스트 중 기존 통합 테스트가 **임시 SQLite DB에 개발용 가상 seed를 실행했다**. Supabase에는 seed나 SQLite 마이그레이션을 실행하지 않았다. |

과목 목록 API에서 기존에 누락된 `theory_hours`, `practice_hours`를 반환하도록 수정했고 SQLite의 해당 값은 `null`이다. 테스트는 로컬 HTTP 서버에서 실제 요청과 실제 PostgreSQL을 사용했다. 비밀번호·URL·인증 토큰은 기록하지 않았다.
