# Phase 3 문서 이관과 배포

PostgreSQL 문서 API는 `ROADMAP_POSTGRES_DOCUMENTS_ENABLED=1`일 때만 활성화된다. 기본값은 비활성화이며, 마이그레이션과 비공개 버킷을 준비하기 전에 켜지 않는다. 운영 환경을 변경하거나 배포하기 전에 사용자 승인이 필요하다.

## 데이터와 Storage

두 마이그레이션을 순서대로 적용한다. 첫 파일은 `project_documents`와 `document_extractions`, 두 번째 파일은 `document_upload_reservations`를 만든다. 테이블은 RLS가 활성화되며 anon/authenticated 권한과 공개 정책이 없다. FastAPI는 기존 익명 세션의 `session_owners → roadmap_inputs` 관계로 소유권을 확인한다. 서버 전용 Storage 키는 RLS를 우회하므로 브라우저에 전달하지 않는다.

업로드는 계획 행을 잠가 revision과 문서 수를 검사하고 UUID 예약을 커밋한다. Storage 업로드는 잠금 밖에서 진행한다. 성공 후 계획과 예약을 다시 잠가 revision 및 만료 여부를 확인하고 문서·추출 작업 생성과 예약 확정을 한 트랜잭션으로 처리한다. 실패하거나 프로세스가 종료되면 예약이 남고 15분 만료 후 정리 대상이 된다. 중복 요청은 서로 다른 키를 사용하고 revision 충돌 시 해당 예약만 정리한다.

정리 작업은 DB에 기록된 정확한 UUID만 삭제한다. 실패한 예약의 기록은 남겨 하루마다 재확인하므로, Storage 요청이 시간 초과된 뒤 늦게 완료되더라도 후속 요청이 있으면 다시 정리할 수 있다. 완료된 예약도 키 충돌에 대비해 보관하고 정리 대상에서 제외한다. 이 기록은 계속 증가하므로 향후 운영 정책에 따른 보관·감사 설계가 필요하다.

## 작업 실행 및 한계

업로드, 재추출, 삭제 및 문서 목록 요청 이후 서버는 프로세스당 한 작업 실행을 시도한다. 한 번에 만료된 예약 최대 하나와 추출 또는 삭제 작업 최대 하나를 처리한다. PostgreSQL `FOR UPDATE SKIP LOCKED`, 120초 lease, token과 revision 검사는 중복 완료와 오래된 결과 반영을 막는다. 문서 목록은 pending 상태에서 프론트엔드가 주기적으로 조회하므로 중단된 작업을 다시 시작할 기회가 생긴다.

이 실행은 Render Free에서 보장된 영구 워커가 아니다. 요청이 없거나 프로세스가 중지되면 정리는 지연되며, 나중에 인증된 문서 목록 요청이 필요하다. Storage 장애가 지속될 때는 재시도도 요청이 있을 때만 일어난다. 별도의 무료 스케줄러를 추가하지 않았다. 추출 자체의 완료 시간도 플랫폼 실행 시간에 좌우된다.

## 사전 검증 및 운영 적용 순서

1. 격리 DB에서 두 마이그레이션과 API 테스트를 실행한다. `ROADMAP_TEST_POSTGRES_URL`은 명시적 포트가 있는 `team18_document_test`라는 이름의 로컬 일회용 DB만 가리켜야 한다. `ROADMAP_ALLOW_TEST_DB_RESET=1`도 필요하다. 테스트는 해당 DB의 public 스키마를 삭제한다. 원격 호스트, DSN query override, libpq의 대상 변경 환경변수, Render 환경, Supabase 마이그레이션 스키마가 발견되면 거부한다. `python -O`에서도 검사가 유지된다.
2. 운영 스키마·마이그레이션 이력, 버킷 이름, 과목과 관계 개수, 백업 및 복원 가능성을 확인한다. 이전 적용 여부와 구조가 다르면 중단한다. 각 SQL은 기존 객체를 무조건 재생성하지 않고 충돌 시 실패한다.
3. 사용자 승인 후 Supabase 마이그레이션 이력을 사용하는 정상 절차로 두 파일을 순서대로 적용한다. 실패하면 트랜잭션과 이력을 확인하고 원인을 해결한다. 사용자 데이터를 삭제해 복구하지 않는다.
4. Dashboard에서 `roadmap-documents` 또는 설정된 이름의 **비공개** 버킷을 만들고 크기 제한이 10MB 이상인지 확인한다. 공개 URL이나 anon/authenticated 직접 접근 정책을 추가하지 않는다.
5. Render에 환경변수를 설정하고 코드를 배포한 다음에만 기능 플래그를 켠다. 실제 테스트 파일로 업로드, 추출, 재추출, 권한 및 삭제를 확인한다. 실패 시 플래그를 끄고 저장된 작업과 예약을 보존한다.
6. Vercel 외부 rewrite를 거치는 10MB multipart 및 세션 쿠키 전달을 실제 배포에서 확인한다. 로컬 빌드는 이 경로를 검증하지 않는다.

## Render 환경변수

- 기존: `ROADMAP_DB_BACKEND=postgres`, `ROADMAP_DATABASE_URL`, `ROADMAP_AUTO_SEED_DEV=0`, `ROADMAP_APP_ORIGIN`
- 최초 배포: `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (또는 기존 `SUPABASE_SERVICE_ROLE_KEY`), `SUPABASE_STORAGE_BUCKET=roadmap-documents`, **`ROADMAP_POSTGRES_DOCUMENTS_ENABLED=0`**
- 승인된 DB·버킷 변경 및 점검 후에만 `ROADMAP_POSTGRES_DOCUMENTS_ENABLED=1`로 변경한다.
- 키 변수는 하나만 설정한다. 새 `sb_secret_...` 값은 `apikey` 헤더로 보내며, 기존 JWT `service_role` 값은 `apikey`와 `Authorization: Bearer`로 보낸다. 두 변수를 함께 설정하거나 공개 키를 넣으면 실패하도록 처리한다. 로컬 점검은 가짜 키와 모의 HTTP로 수행하며 실제 키는 Render에만 저장한다.

비밀값은 Render 서버 환경에만 저장한다. 빌드 명령은 `pip install -r requirements.txt`, 시작 명령은 `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, 헬스 경로는 `/api/health`다. 기존 `sslmode=require` 동작을 유지하며 TLS 서버 인증서 검증 복구와 SQLite 제거는 후속 작업이다.

운영 사전 검사 결과와 승인할 변경 범위는 [운영 적용 검증 기록](phase3-production-preflight.md)을 참고한다.
