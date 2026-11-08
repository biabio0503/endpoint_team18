# Phase 3 문서 이관: 작업 중

이 문서는 완성된 배포 절차가 아니다. PostgreSQL 문서 API는 아직 503으로 차단되어 있고 Storage 어댑터도 라우터에 연결되지 않았다. 이 상태를 운영에 배포하여 문서 기능을 활성화할 수 없다.

2026-11-08 Supabase 운영 프로젝트를 읽기 전용으로 확인했다. `roadmap_inputs.request_id`와 `session_owners.owner_id`는 text이고 기존 문서 테이블과 Storage 버킷은 없었다. 과목과 목록 과목은 각각 68개였다. 운영 마이그레이션과 버킷 변경은 실행하지 않았다.

## 마이그레이션 검증 및 적용 계획

1. 격리된 PostgreSQL/Supabase에서 운영의 `roadmap_inputs` 구조와 `anon`, `authenticated` 역할을 준비한다. 실제 학생 데이터는 복사하지 않는다.
2. `supabase migration list --local`로 이력을 확인하고 마이그레이션을 한 번 적용한다. 두 테이블의 외래키, 상태 제약, JSON 배열, RLS, 역할 권한을 검사하고 기존 관계와 데이터를 확인한다.
3. 의도적인 오류로 트랜잭션이 롤백되는지, 재실행이 이력에 의해 방지되는지, API·동시 작업 테스트가 성공하는지 검증한다. 기존 객체가 있으면 `CREATE TABLE`은 실패한다. 이름이 같다는 이유로 다른 구조를 수용하거나 삭제하지 않는다.
4. 운영 적용 전 백업 및 복구 가능성을 확인하고 테이블 존재 여부, 컬럼 타입, 마이그레이션 이력, 과목과 관계의 개수를 다시 확인한다. 격리 검증과 코드 완성 후 Supabase 마이그레이션 절차로 한 번만 적용한다. 실패하면 트랜잭션과 이력을 확인하고 원인을 수정한다. 사용자 데이터가 들어간 테이블을 삭제해 복구하지 않는다.

## 배포 전에 남은 작업

- 업로드 예약과 보상 정리, revision 충돌 및 재시작 복구를 구현하고 격리 DB와 Storage에서 검증한다.
- PostgreSQL API와 워커 연결, 요청 기반 재개, DB 소유권 검사, 동시 작업 및 삭제 경합을 검증한다.
- 비공개 `roadmap-documents` 버킷을 만들고 브라우저에 직접 접근 권한을 부여하지 않는다. 서버 키가 RLS를 우회하므로 FastAPI의 세션과 DB 소유권 검사가 필수다.
- Render에 기존 `ROADMAP_DB_BACKEND`, `ROADMAP_DATABASE_URL`, `ROADMAP_AUTO_SEED_DEV`, `ROADMAP_APP_ORIGIN`을 유지하고 완성된 구현에 맞춰 `SUPABASE_URL`, 서버 전용 `SUPABASE_SERVICE_ROLE_KEY` 또는 `SUPABASE_SECRET_KEY`, `SUPABASE_STORAGE_BUCKET`을 설정한다. 현재 코드에서는 이 변수를 아직 읽지 않는다.
- Vercel 외부 rewrite에서 10MB multipart 및 쿠키 전달을 실제 배포로 검증한다. Vercel Functions의 4.5MB 제한은 외부 rewrite가 반드시 동일한 제한을 받는다는 증거가 아니므로 별도로 실측해야 한다.
- 기존 `sslmode=require` 동작을 유지하며 TLS 인증서 검증 복구와 SQLite 제거는 후속 작업이다.
