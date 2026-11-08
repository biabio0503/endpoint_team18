# 인증 통합 작업 상태 — 미완료

이 변경은 배포 준비가 되지 않았습니다. PostgreSQL 인증 경로는 아래 DB 변경이 적용되기 전까지 작동하지 않습니다. 운영 DB에는 아직 적용하지 않았습니다. 기존 쿠키 소유자의 데이터는 삭제하거나 임의로 계정에 연결하지 않습니다. 기존 직접 DB 연결은 RLS를 우회하는 권한을 사용할 수 있으므로 API의 소유권 검사가 필수입니다. 현재 개인 테이블은 Data API 역할에 대한 권한이 철회되어 있으며 RLS가 켜져 있습니다.

## 필요한 마이그레이션 초안

Supabase CLI로 마이그레이션 파일을 생성했지만 격리된 DB에서 아직 검증하지 못했습니다. 검증 후 적용해야 합니다. 기존 `session_owners.owner_id`와 참조를 유지하고 새로운 사용자에만 Auth ID를 연결합니다. 기존 쿠키 소유자는 NULL로 남습니다. 기존 사용자를 계정에 연결하려면 별도의 소유권 증명 및 이관 절차가 필요합니다.

```sql
ALTER TABLE public.session_owners
  ADD COLUMN auth_user_id uuid REFERENCES auth.users(id),
  ADD CONSTRAINT session_owners_auth_user_id_key UNIQUE (auth_user_id);
```

이 마이그레이션은 계정 삭제 정책, RLS 정책, 계정 분리와 동시 최초 로그인에 대한 격리 테스트 및 보안 검토가 필요합니다. 운영 데이터에 적용하지 마세요.

## 설정

- 백엔드: `ROADMAP_DB_BACKEND=postgres`, `ROADMAP_DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` 및 문서 저장소 설정은 `apps/api/.env.example` 참조.
- 프런트: `apps/web/.env.example`의 URL과 publishable key를 설정합니다. 두 키는 동일 프로젝트의 공개 키여야 합니다. 서비스 역할 키와 Google secret은 프런트에 두지 않습니다.
- Supabase Dashboard Authentication에서 Anonymous Sign-Ins 및 Google provider를 활성화하고 Site URL과 정확한 서비스 출처의 redirect URL을 등록합니다. 게스트 남용 방지용 CAPTCHA 설정과 클라이언트 연동은 후속 작업입니다.
- Google Cloud Auth Platform에서 동의 화면과 대상 사용자를 설정하고 웹 OAuth 클라이언트를 만든 뒤 Supabase가 표시하는 콜백 URL을 승인된 redirect URI에 등록합니다. Client ID와 secret은 Supabase Google provider 설정에만 입력합니다. 자세한 내용은 [Google 로그인](https://supabase.com/docs/guides/auth/social-sign-in/auth-google)과 [익명 로그인](https://supabase.com/docs/guides/auth/auth-anonymous)을 참조합니다.
- 비공개 Storage 버킷과 PostgreSQL 문서 설정은 기존 `docs/phase3-production-preflight.md` 참조.

게스트 Google Identity Linking은 후속 작업입니다. 계정 병합이나 삭제는 구현하지 않았습니다. 기존 SQLite 쿠키 개발 모드는 별도로 남아 있으나 변경된 웹 클라이언트와의 통합 검증은 하지 않았습니다.
