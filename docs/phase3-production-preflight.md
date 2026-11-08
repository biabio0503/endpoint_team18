# Phase 3 운영 사전 검사 — 2026-11-08

상태: 운영 변경 미실행. 로컬 보완과 격리 검증은 완료했으나 백업 복구 가능성, 비공개 Storage 및 실제 문서 쓰기 검증이 완료되기 전에는 활성화하지 않는다.

## 코드와 배포 기준

- 작업 시작 시 로컬 HEAD와 GitHub main: `01adbd43474c4ba9eb747368d8dc4258282b52bb`. 작업 트리는 깨끗했다.
- 해당 커밋의 GitHub Vercel 상태는 success. 현재 Render 배포 SHA와 Dashboard 환경변수는 확인하지 못했다.
- 이번 수정은 로컬에만 있다. push, 배포, 환경변수 변경을 하지 않았다.
- Secret Key를 JWT Bearer로 보내던 코드를 수정했다. `sb_secret_...`는 apikey만, JWT service_role은 apikey와 Authorization을 사용한다. 공개 키, 두 서버 키 동시 설정은 거부한다.
- 테스트 DB 초기화는 명시적 opt-in, 로컬 호스트·포트·DB 이름, DSN override 및 Render 여부를 검사한다. 연결 후 Supabase 이력 스키마가 있으면 중단한다. 최적화 실행에서도 보호한다. **운영에서 테스트 시나리오를 실행하지 않는다.**

## 운영 DB 읽기 전용 결과

대상 프로젝트: `htuttclopxaiyhgcakkj`, PostgreSQL 17.11, Free 플랜.

| 항목 | 확인 결과 |
|---|---|
| 학교 / 학과 / 과목 / 목록 과목 | 1 / 1 / 68 / 68 |
| 사용자 계획 / 세션 | 3 / 3; 본문·토큰·사용자 행을 수집하지 않음 |
| 문서 대상 테이블 3개 | 모두 없음 |
| 기존 public 테이블 8개 | RLS 활성, anon/authenticated SELECT 권한 없음 |
| 기존 외래키 13개 | 모두 validated |
| roadmap_inputs.request_id | text, PRIMARY KEY |
| 세션·계획 시간 | timestamptz; 신규 시간 타입과 호환 |
| Storage buckets / objects | RLS 활성 |
| Storage 버킷 / 정책 | 버킷 없음 / 정책 없음 |
| Data API 노출 스키마 설정 | DB 역할 설정에서 확인되지 않음; Dashboard 최종 확인 필요 |
| Security advisor | RLS enabled/no policy 안내. 백엔드 전용 권한 모델에 해당하며 공개 정책을 추가하지 않음 |

새 SQL은 기존 교육과정·계획·세션의 행을 수정하지 않는다. text FK, 상태와 크기·revision CHECK, JSON 배열 CHECK, 인덱스, RLS 및 anon/authenticated/PUBLIC 권한 회수를 확인했다. FK 생성 중 부모 테이블 잠금이 잠깐 필요하므로 적용은 짧은 점검 시간에 수행하고 잠금 대기 제한을 둔다.

## SQL과 적용 순서

운영에 이미 적용된 아래 두 이력의 SQL 원본을 읽어 저장소에 복원했다. 공백을 제외한 원본 일치를 확인했으며 **운영에서 다시 실행하지 않는다.** 이전에는 로컬에 이 두 이력이 없어 CLI history mismatch 가능성이 있었다.

- `20261108035123_team18_core_schema_p1_p2_p3_guard.sql`
- `20261108035354_team18_2026_cse_course_theory_practice_columns.sql`

승인 후 신규 적용할 파일은 정확히 두 개다.

1. [20261108122001_phase3_documents.sql](../supabase/migrations/20261108122001_phase3_documents.sql): project_documents, document_extractions, 명시적 인덱스 3개, RLS, 권한 회수.
   - SHA256 `ddc877491e07ab98857d6bc6018f2c1e76a2a37a989c23f1cfc02806f03ec0d2`
2. [20261108122527_document_upload_reservations.sql](../supabase/migrations/20261108122527_document_upload_reservations.sql): document_upload_reservations, 2개 인덱스, RLS, 권한 회수.
   - SHA256 `ef37fdbcdad1d25349763bb2d2b04a66131c9ed733f46707022f69ac5378cece`

document_extractions는 복합 PK의 자동 인덱스를 사용한다. 테이블별 PK/UNIQUE 자동 인덱스는 위 개수와 별도로 생성된다.

적용 직전 [읽기 전용 점검 SQL](../supabase/checks/phase3_preflight.sql)을 다시 실행하고 이력과 파일 해시를 대조한다. Supabase CLI 3.0.0의 `migration up --remote=htuttclopxaiyhgcakkj`를 사용한다면 보류된 파일이 위 두 개뿐인지 먼저 확인한다. `--include-all`, 이력 삭제, 강제 repair는 사용하지 않는다. 실제 명령은 승인 전 실행하지 않았다. 각 마이그레이션을 트랜잭션 및 정상 이력 기록과 함께 적용하고, 실패 시 해당 트랜잭션 롤백과 이력을 확인한다. 앞 파일만 성공했다면 그것을 삭제하지 않고 나머지만 재시도한다.

## 백업 및 복구 게이트

**현재 복구 가능한 운영 백업을 확인하지 못했다. 마이그레이션 적용 전 필수 조건이다.** Free 플랜에는 유료 플랜의 일일 백업 보장을 가정할 수 없다. 관리자 환경에서 논리 백업을 만들고 암호화된 저장소에 보관해야 한다. SQL/데이터를 채팅이나 Git에 넣지 않는다.

- 공식 Supabase CLI `db dump --help`를 확인했다. CLI v3는 기본 대상이 local이며 원격은 `--remote`가 필요하다.
- 역할, 스키마, 데이터, 마이그레이션 이력의 백업 범위를 명시하고 파일 생성 시각·크기·checksum과 보관 위치를 기록한다. public만 덤프하면 전체 프로젝트 백업이라고 부르지 않는다.
- 별도 빈 격리 DB에 복원하고 교육과정 68개와 관계, 계획·세션 수, 권한 및 RLS를 확인한다. 운영 DB에 restore/clean을 실행하지 않는다.
- 이후 Storage 객체는 DB 백업에 포함되지 않으므로 별도 원본 보관·복구 방안이 필요하다. 현재 버킷은 없다.
- 문서 기능 장애의 기본 복구는 플래그 OFF다. 기존 테이블이나 데이터를 DROP/DELETE하는 롤백을 하지 않는다.

## Storage와 Render 설정

버킷 생성·변경 및 서버 키 발급·등록은 승인 후 수행한다.

- 버킷: `roadmap-documents`, Public=false, `file_size_limit=10485760` (10MiB). 프로젝트 전체 업로드 상한도 10485760 이상이어야 한다. 현재 전체 상한은 미확인이다.
- 허용 MIME을 제한한다면 PDF, DOCX, TXT를 허용한다. 실제 API 업로드로 확인한다.
- anon/authenticated 직접 접근 정책과 공개 URL을 만들지 않는다. 학교 앱의 owner_id를 Supabase Auth UID로 간주하지 않는다.
- 실제 서버 키가 없어 업로드·읽기·삭제·덮어쓰기·익명 접근 거부는 아직 실서비스 검증하지 못했다. 모의 HTTP의 인증 헤더 테스트만 통과했다.

Render 최초 설정:

```dotenv
SUPABASE_URL=https://htuttclopxaiyhgcakkj.supabase.co
SUPABASE_SECRET_KEY=<Render에만 입력>
SUPABASE_STORAGE_BUCKET=roadmap-documents
ROADMAP_POSTGRES_DOCUMENTS_ENABLED=0
```

`SUPABASE_SERVICE_ROLE_KEY`를 쓰는 경우 위 SECRET_KEY를 비우고 기존 JWT service_role 값만 넣는다. 둘을 동시에 설정하지 않는다. 키를 채팅, 로컬 파일, GitHub, Vercel 또는 NEXT_PUBLIC 변수에 넣지 않는다.

Root Directory `apps/api`, Build `pip install -r requirements.txt`, Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, Health `/api/health`를 유지한다. 기존 DB 설정과 `sslmode=require`는 변경하지 않는다. 승인된 DB·Storage 검증 및 코드 배포 후에만 문서 플래그를 1로 변경한다.

## 실서비스와 로컬 검증 결과

실서비스 GET만 수행했다. Render `https://endpoint-team18.onrender.com`, Vercel `https://web-seven-xi-rblasxflsf.vercel.app` 모두:

- `/api/health`, `/api/health/db`: 200, status=ok.
- `/api/reference`: 200, 학교·학과·카탈로그 각 1개.
- 존재하지 않는 계획의 문서 목록: 503 feature_unavailable. 문서 OFF 동작과 일치하지만 실제 환경변수 값·배포 SHA를 직접 확인한 것은 아니다.
- Vercel 홈: 200. Render 루트 `/`의 404는 API 루트 미정의에 따른 정상 결과다.

로컬: 전체 백엔드 60 passed, 1 skipped(Gemini live), 7 subtests passed. 새 키 헤더, 테스트 초기화 차단을 포함한다. 이후 복원한 운영 구조와 가상 과목 68개를 사용하는 PostgreSQL 문서 시나리오도 통과했다. 운영 데이터는 격리 DB로 복사하지 않았다.

실서비스 쓰기 및 큰 업로드는 승인 전이므로 다음은 미검증이다: 새 계획/세션 쿠키, 이수 토글, Gemini 실제 호출, PDF/DOCX/TXT, 부분 확인/재추출/삭제, Storage 원본 삭제, 다른 세션 접근 거부, revision 충돌, 중복 업로드, DB/Storage 장애, 재시작 후 pending 복구.

승인 후에는 기존 계획을 사용하지 않고 별도 테스트 세션과 계획을 생성한다. Vercel URL을 통해 1MiB(1048576), 5MiB(5242880), 9MiB(9437184) 합성 UTF-8 TXT를 업로드하고 HTTP 상태·시간·extraction/cleanup 상태를 기록한다. 크기별 성공을 보기 전에는 프록시 제한을 검증했다고 보고하지 않는다. 실패 시 Render 직접 경로와 비교해 프록시 제한인지 앱 제한인지 판별한다. 운영 DB 장애를 고의로 주입하거나 기존 사용자 프로세스를 재시작하는 시험은 별도 범위 승인 없이는 하지 않는다.

## 승인 범위와 진행 판단

승인이 필요한 실제 변경은 (1) 백업/복구 검증 이후 두 마이그레이션 적용, (2) 비공개 버킷 생성과 크기 설정, (3) Render 서버 키·환경변수 등록 및 OFF 상태 코드 배포, (4) 조건 충족 후 플래그 ON, (5) 테스트 전용 계획·파일의 생성과 삭제다. 현재 어느 것도 실행하지 않았다.

문제 발생 시 플래그 OFF로 신규 문서 요청을 차단하고 기존 계획·과목 API와 작업 기록을 유지한다. 이미 실행 중인 작업은 종료 전 완료될 수 있으므로 상태를 확인한다. 클라우드 검증 전에는 Phase 3 운영 완료 또는 SQLite 제거 단계로 진행 가능하다고 판단하지 않는다.

공식 참고: [API 키](https://supabase.com/docs/guides/getting-started/api-keys), [백업](https://supabase.com/docs/guides/platform/backups), [CLI v3](https://supabase.com/changelog/supabase-cli-v3).
