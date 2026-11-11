# OCR 운영 적용 사전 점검 — 2026-11-11

**판정: 로컬·격리 검증은 통과했다. 운영 적용과 실제 Google 연결은 보류한다.** 운영 Supabase 스키마·백업 복구 가능성·Render의 실제 설정은 이번 작업에서 조회하거나 변경하지 않았다. 아래 운영 명령은 담당자가 후속 승인 후 실행할 절차이며, 이번에 실행한 명령이 아니다. Google 결제 연결, 실제 Vision/Gemini 호출, 운영 마이그레이션, push, 배포를 하지 않았다.

현재는 `ROADMAP_OCR_PROVIDER=none`을 유지한다. 이 설정에서는 일반 PDF·DOCX·TXT 추출과 기존 분석 흐름을 유지하며 OCR이 필요한 영역은 기존 `needs_ocr`/`partial` 규칙으로 처리한다. 실제 Google 클라이언트 생성 자체를 차단한 Mock 테스트로 검증했다.

## 1. 코드 기준과 미커밋 파일

로컬 브랜치는 `main`, HEAD와 저장된 `origin/main`은 `b2e0955f7fbd060a3d75aafe272f7053b30b4001`이다. `git ls-remote origin refs/heads/main`으로 GitHub의 현재 main도 같은 커밋임을 확인했다. 커밋 제목은 `클라우드 비전 OCR 통합1`이다. 따라서 **기존 OCR 통합은 main에 있고, 태평양 시간 수정 및 이번 점검 자료는 아직 배포 커밋에 포함되지 않았다.**

점검 시작 시 수정된 추적 파일 10개:

- `README.md`
- `apps/api/.env.example`
- `apps/api/app/providers/google_vision_ocr.py`
- `apps/api/app/repositories/plans.py`
- `apps/api/app/services/document_ocr.py`
- `apps/api/tests/unit/test_document_ocr.py`
- `apps/web/src/features/intake/Documents.js`
- `docs/google-vision-ocr.md`
- `docs/phase3-document-migration.md`
- `docs/render-deployment.md`

점검 시작 시 미추적 파일 5개:

- `apps/api/app/services/ocr_billing.py`
- `apps/api/migrations/010_document_ocr_billing_period.sql`
- `apps/api/tests/unit/test_ocr_billing_period.py`
- `apps/api/tests/unit/test_ocr_budget_boundaries.py`
- `supabase/migrations/20261111021219_document_ocr_billing_period.sql`

이번 점검에서 추가한 파일:

- 이 보고서 `docs/ocr-production-preflight.md`
- [읽기 전용 운영 비교 SQL](../supabase/checks/ocr_preflight.sql)
- [이력 보존·점검 SQL 테스트](../apps/api/tests/unit/test_ocr_preflight.py)

기존 `docs/google-vision-ocr.md`, `docs/render-deployment.md`에는 이 보고서 링크를 추가했다. OCR 실행 코드와 마이그레이션 SQL은 이번 점검에서 수정하지 않았다. 최종 작업 트리는 수정 10개·미추적 8개다. 배포 준비 시 미추적 파일도 리뷰 대상에 포함하고, 실제 배포할 커밋 SHA를 확정해야 한다. Render 자동 배포가 켜져 있다면 push가 배포를 시작할 수 있으므로 승인 전 push하지 않는다.

## 2. 마이그레이션 순서와 운영 스키마 비교

SQLite와 PostgreSQL SQL은 서로 바꾸어 실행하지 않는다.

| 대상 | 적용 순서 | 실행 방식 |
| --- | --- | --- |
| SQLite | 기존 `001`~`008` → `009_document_ocr_units.sql` → `010_document_ocr_billing_period.sql` | 앱의 `repositories.plans.migrate()`가 파일별 `BEGIN IMMEDIATE`와 이력 기록을 함께 수행 |
| PostgreSQL | 기존 core·문서·인증·분석·AI guard 마이그레이션 → `20261110091129_document_ocr_units.sql` → `20261111021219_document_ocr_billing_period.sql` | 운영 담당자가 미적용 파일만 트랜잭션으로 적용; 앱 시작 시 자동 적용하지 않음 |

PostgreSQL의 기존 선행 파일은 파일명 오름차순으로 `20261108035123`, `20261108035354`, `20261108122001`, `20261108122527`, `20261108133033`, `20261109051837`, `20261109061229`, `20261109073304`다. OCR 테이블은 `project_documents`의 FK를 사용하며, 기존 서비스 전체에는 나머지 선행 스키마도 필요하다.

**이력 불일치 확인이 선행 조건이다.** [이전 배포 기록](render-deployment.md)에는 운영 문서 이력이 `20261108125912`, 업로드 예약 이력이 `20261108125921`로 기록되어 있다. 저장소 파일 버전과 다르며, 해당 기록은 현재 운영 스키마의 증거가 아니다. SQL 내용·테이블·제약 조건을 대조하기 전에는 일괄 `db push`, `--include-all`, 이력 repair, 기존 SQL 재실행을 하지 않는다.

운영 연결 정보는 승인된 기기에서 저장소 밖의 권한 `0600`인 libpq service/pass 파일로 관리한다. 예시의 `team18_ops`는 담당자가 Supabase Dashboard Connect의 **직접 연결 또는 Session pooler** 대상과 DB 이름을 검증해서 만든 서비스 별칭이다. 비밀번호를 명령 인수·Git·터미널 출력에 넣지 않는다. `psql`/`pg_dump`는 운영 서버 major 이상 버전을 사용한다.

저장소 루트에서 실행할 읽기 전용 비교 명령:

```sh
# OCR_AUDIT_DIR: 저장소 밖의 접근 제한·암호화 보관 경로, 담당자가 사전에 설정
umask 077
psql -X --dbname='service=team18_ops' --set=ON_ERROR_STOP=1 \
  --file=supabase/checks/ocr_preflight.sql > "$OCR_AUDIT_DIR/before.txt" 2>&1
```

이 SQL은 `REPEATABLE READ READ ONLY`, 잠금 대기 3초·문장 30초 제한으로 동작한다. 테이블·새 컬럼이 없어도 그 상태를 보고한다. 문서 본문·파일명·문서 ID·인증 정보는 출력하지 않는다. `DO` 블록 결과는 NOTICE이므로 stderr도 보관해야 한다. 권한 부족이나 시간 초과가 발생하면 결과를 통과로 취급하지 않는다. 대형 테이블의 전체 체크섬 계산은 비용이 있으므로 점검 시간에 실행한다.

운영자가 비교할 항목:

| 결과 | 통과 기준 |
| --- | --- |
| migration history | 실제 SQL과 저장소 선행 파일의 대응이 모두 확인됨; 이름만 같은 이력을 신뢰하지 않음 |
| 테이블·컬럼 | 기존 문서 테이블 3개, OCR 테이블 존재; OCR 컬럼 `matches=true` 9개 |
| 제약 조건 | `(document_id, unit_key)` PK, 문서 FK, 양수 revision, 상태/usage_month CHECK, `billing_period` NOT NULL 및 태평양 시간 CHECK; 모두 validated |
| 인덱스 | 기존 PK·`document_ocr_units_month` 유지, `document_ocr_units_billing_period` 존재 |
| 권한 | RLS 활성, `anon_any`/`authenticated_any`/`public_any` 모두 false, OCR 공개 policy 없음 |
| 데이터 보존 | 이관 전후 각 `snapshot`의 행 수와 `legacy_fingerprint` 동일; 문서·추출·분석 기록 포함 |
| 사용량 | 전후 `budget`의 기간별 units/reserved/completed/failed/cached 동일; 모두 예산에 포함 |
| 무결성 | `invalid_billing_period_rows=0`, `orphan_ocr_units=0`; 겨울·여름 경계 `matches=true` |
| 작업 중지 | active lease 두 항목 0, 모든 실제 워커 종료도 별도로 확인 |

테이블이 없던 최초 적용에서는 OCR snapshot이 없음→0행으로 생성되는 것이 정상이다. 이전 ledger가 있던 환경에서 사라지거나 0행이 되면 중단한다. 태평양 시간으로 재집계한 과거 사용량이 900보다 많으면 삭제하지 않는다. 현재 기간이 이미 한도를 넘었다면 남은 예산은 0이어야 한다. SQL의 `remaining_at_hard_ceiling`은 900 기준 참고치이며, 더 낮게 설정한 실제 서버 한도까지 조회하지는 못한다.

MD5 집계값은 이관 중의 우발적 변경 비교용이며 보안 서명이나 백업 대체물이 아니다. 원문 대신 집계만 출력해도 점검 결과는 내부 자료로 보관한다. 행 수·체크섬 비교를 위해 이관 전후 모든 문서·분석 쓰기를 중지해야 한다.

## 3. DB 백업 및 데이터 보존

백업은 쓰기 중지 후 취득한다. OCR ledger만 복사하면 문서 FK·추출 revision·분석 근거와 일치하지 않을 수 있으므로 관련 데이터를 같은 스냅샷으로 보관한다. 이관 전 OCR 사용량 집계와 이력, 파일 해시도 함께 남긴다.

```sh
# 담당자가 검증한 team18_ops에 대한 논리 백업. 이번 작업에서는 실행하지 않음.
pg_dump --dbname='service=team18_ops' --format=custom \
  --file="$OCR_AUDIT_DIR/pre-ocr.dump"
pg_restore --list "$OCR_AUDIT_DIR/pre-ocr.dump" > "$OCR_AUDIT_DIR/restore-list.txt"
shasum -a 256 "$OCR_AUDIT_DIR/pre-ocr.dump" > "$OCR_AUDIT_DIR/pre-ocr.dump.sha256"
```

오류 없이 종료했는지, 대상 schema/data/ACL/constraint/index 및 `supabase_migrations` 이력이 실제 포함됐는지 확인한다. 이 명령은 클러스터 역할·역할 암호·서비스 설정을 백업하지 않는다. 복구에 필요한 역할/grant/RLS, Supabase Auth·API·Storage 설정도 별도 보관하고, 관리형 스키마·권한 때문에 덤프가 불완전하면 진행하지 않는다. 소유권·권한을 무조건 제거하는 옵션으로 오류를 숨기지 않는다. TLS 설정도 승인된 백업 클라이언트 구성을 사용한다.

**복원 목록 열람만으로 백업 검증이 끝나지 않는다.** 운영과 분리된 접근 제한 DB에 복원하고, 위 SQL의 행 수·체크섬·권한을 재확인한다. 복구용 DB는 실제 개인 문서가 포함될 수 있으므로 접근·보존·폐기 정책을 적용하고 Google/Gemini 자격증명과 외부 호출을 차단한다. 테스트 스위트가 스키마를 초기화하므로 실제 데이터가 든 복원 DB에는 `ROADMAP_ALLOW_TEST_DB_RESET=1` 테스트를 실행하지 않는다. 현재 자동 테스트는 합성 데이터만 사용한다.

Supabase의 DB 백업은 Storage 객체 본문을 포함하지 않는다. 원본 문서 객체와 key 연결도 별도 백업/복구 절차로 검증해야 한다. Free 플랜에서 유료 플랜의 자동 백업/PITR이 제공된다고 가정하지 않는다. 비용이 드는 백업 옵션을 이번 작업에서 활성화하지 않았다. [Supabase 백업 문서](https://supabase.com/docs/guides/platform/backups)

SQLite 로컬 이관 시에는 앱과 워커를 중지하고 SQLite backup API로 DB 사본을 만든다. WAL 사용 여부를 무시한 실행 중 파일 복사는 사용하지 않는다. `010`은 `ocr_billing_period` UDF가 필요하므로 일반 sqlite CLI로 직접 적용하지 않고 새 코드의 migration runner를 사용한다. 기존 row를 새 테이블로 복사한 뒤 교체하는 단계 전체가 한 트랜잭션이다. UTC 시각 파싱 실패는 이관을 실패시켜야 하며, 사용량 행을 버리고 성공 처리하지 않는다.

검증된 보존 범위는 OCR의 키·UTC created_at·legacy usage_month·status·error_code·cache, 문서 metadata·revision, 과거/현재 추출 기록이다. PostgreSQL 새 SQL은 `billing_period`만 추가·채우며 기존 RLS/grant/PK/FK를 보존한다. SQLite는 재구성 후 FK와 인덱스를 재확인했다. `usage_month`는 UTC 감사용으로 유지하고 예산 계산에는 사용하지 않는다.

## 4. 승인 후 운영 적용 순서

1. 위 미커밋 파일 전체를 리뷰하고 배포 SHA·SQL 해시를 확정한다. 현재 운영 SHA와 설정을 비밀값 없이 기록한다. 자동 배포가 변경 창보다 먼저 일어나지 않도록 배포 담당자가 제어한다.
2. 모든 실행 환경에서 OCR을 `none`으로 설정하고, 문서·분석 쓰기 유입과 모든 구버전 프로세스/워커를 중지한다. Render의 이전 배포 인스턴스, 별도 worker, 개발자 로컬 프로세스, staging의 동일 자격증명 사용도 포함한다. 환경변수 저장이나 lease 만료만으로 프로세스 종료를 대신하지 않는다.
3. 진행 중 Vision 호출이 없고 이전 프로세스가 모두 종료됐는지 확인한다. 기존 예약은 그대로 보존한다. 읽기 전용 점검과 백업·격리 복원 검증을 완료한다.
4. 운영 스키마 비교 결과로 필요한 SQL만 선정한다. ledger가 없으면 OCR 두 파일을 순서대로 적용한다. ledger만 있고 billing_period가 없으면 두 번째 파일만 적용한다. 둘 다 있으면 재실행하지 않고 구조·이력부터 대조한다. 예상하지 못한 부분 적용 상태는 자동 복구하지 않는다.
5. 각 승인된 migration 파일은 **트랜잭션 단위**로 적용한다. 다음은 ledger가 없는 환경의 수동 SQL 실행 예시다. 이미 적용된 파일은 명령에서 제외한다.

```sh
# 변경 명령: 승인된 점검 시간에만 담당자가 실행. 이번 작업에서는 실행하지 않음.
PGOPTIONS='-c lock_timeout=5s -c statement_timeout=120s' \
psql -X --dbname='service=team18_ops' --set=ON_ERROR_STOP=1 --single-transaction \
  --file=supabase/migrations/20261110091129_document_ocr_units.sql \
  --file=supabase/migrations/20261111021219_document_ocr_billing_period.sql
```

수동 psql은 Supabase migration history를 자동 기록하지 않는다. 실제 운영에서는 이력이 대조된 승인 migration 도구를 우선 사용하고, 수동 실행이 필요하면 실행한 정확한 SQL/해시를 증빙으로 정상 이력 등록 절차까지 준비한다. CLI 버전별 동작이 다르므로 `supabase --help`와 해당 하위 명령 도움말을 확인한다. 이미 같은 SQL을 실행한 뒤 CLI로 다시 적용하지 않는다. [CLI v3 변경 안내](https://supabase.com/changelog/supabase-cli-v3)

6. 읽기 전용 SQL을 `after.txt`로 다시 실행한다. `before.txt`의 snapshot/budget과 데이터 보존을 비교하고 새 컬럼·CHECK·index·RLS를 확인한다. 예상 외 차이 또는 권한 노출이면 앱을 재개하지 않는다.
7. 새 SHA를 Render에 배포하되 `ROADMAP_OCR_PROVIDER=none`을 유지한다. 새/구버전 혼합 실행이 없음을 확인한다. `/api/health`, `/api/health/db`만 통과해도 OCR 스키마가 맞다는 뜻은 아니므로 6단계를 생략하지 않는다.
8. 유료 분석을 실행하지 않는 기존 조회, 일반 텍스트 문서 업로드/읽기/삭제, 이미지 문서의 `needs_ocr`/`partial` 및 재시도 불가 사유를 승인된 합성 문서로 확인한다. 업로드·삭제 쓰기 검증은 사전 합의된 검증 환경에서 수행한다. 실제 Gemini 분석 버튼도 비용 가능성이 있으므로 Mock 검증과 구분한다.
9. UI의 기존 스켈레톤·partial 확인·분석 근거 연결을 확인하고 작업 유입을 재개한다. 실제 Google 활성화는 별도 결정으로 남긴다.

현재 SQL 해시(SHA-256):

| 파일 | 해시 |
| --- | --- |
| SQLite `009_document_ocr_units.sql` | `12432ec5468cbed656e981656ba5ef426dade996d94e64679f1eaad9e4324a7e` |
| SQLite `010_document_ocr_billing_period.sql` | `c5c6feb207095fb6541143ad8c0987ab5346fff68c1c349a7662aa344b16e2fd` |
| PostgreSQL `20261110091129_document_ocr_units.sql` | `0a2837c9e45df8505735c4c72c0c4531c4574cdff85f0b28c16962ed00f06bb6` |
| PostgreSQL `20261111021219_document_ocr_billing_period.sql` | `b56b1bcbd8b04c8125cea88f4db5be1006e28fcb1f709cb436021e9f0507ea83` |

## 5. Render 설정과 의존성

| 항목 | 적용 예정 값 / 확인 사항 |
| --- | --- |
| Root Directory | `apps/api` |
| Python | `PYTHON_VERSION=3.14.7` |
| Build / Start | `pip install -r requirements.txt` / `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health | `/api/health`; 별도로 `/api/health/db` 검증 |
| DB | `ROADMAP_DB_BACKEND=postgres`, 검증한 서버 전용 `ROADMAP_DATABASE_URL`, `ROADMAP_AUTO_SEED_DEV=0` |
| Origin / cookie | 실제 HTTPS 프론트 출처 `ROADMAP_APP_ORIGIN`; `ROADMAP_INSECURE_LOCAL_COOKIE`는 미설정 또는 `0` |
| 기존 문서·Storage | `ROADMAP_POSTGRES_DOCUMENTS_ENABLED`, `SUPABASE_URL`, `SUPABASE_STORAGE_BUCKET`, `SUPABASE_PUBLISHABLE_KEY`는 실제 운영 값 확인·유지 |
| 서버 Storage 키 | `SUPABASE_SECRET_KEY` 또는 `SUPABASE_SERVICE_ROLE_KEY` 중 하나만 유지; 브라우저 노출 금지 |
| OCR | **`ROADMAP_OCR_PROVIDER=none`** |
| 월간 / 문서 한도 | `ROADMAP_OCR_MONTHLY_UNIT_LIMIT=900`, `ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT=50` |
| Google 인증 | 현재 미설정; 향후 별도 승인 시 `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/google-vision-service-account.json` |
| 기존 Gemini | `GEMINI_API_KEY`, `GEMINI_MODEL`, `ROADMAP_AI_*`의 운영 값을 유지; OCR 예산과 별개 |
| 프론트 빌드 | 실제 backend의 `ROADMAP_API_ORIGIN`; 새 공개 OCR 설정 변수는 없음 |

인증 Secret File은 현재 필요하지 않다. 향후 승인 시 `google-vision-service-account.json`을 Render Secret File로 추가하며 파일 내용은 로그/저장소에 남기지 않는다. Render에서 Secret File 저장은 배포를 시작하고, 환경변수의 Save only는 실행 중 프로세스에 반영되지 않는다는 점을 변경 창에 반영한다. [Render 설정 문서](https://render.com/docs/configure-environment-variables)

고정 의존성은 `google-cloud-vision==3.16.0`, `pypdfium2==5.15.2`, `Pillow==12.0.0`이다. 기존 pypdf/python-docx/psycopg를 유지한다. 로컬 Python 3.14.7에서 설치 버전·`pip check`·렌더링 테스트를 확인했다. **실제 Render Linux 빌드와 메모리 상한은 이번에 검증하지 않았다.** 승인된 배포에서 wheel 설치와 `ZoneInfo('America/Los_Angeles')` 사용 가능 여부를 확인해야 한다. 시스템 tzdata가 없으면 활성화하지 않는다.

이미지는 최대 변 2,000px, PDF 배율 최대 2, PNG 요청 최대 8MiB로 제한된다. SDK는 `retry=None`, timeout 25초이고 PDFium 렌더링은 프로세스 내 잠금으로 직렬화한다. 요청 worker도 프로세스 내 한 개다. 전체 프로세스 수를 늘리면 메모리 동시 사용은 늘어나므로 최초 검증은 기존 단일 uvicorn 설정으로 수행한다. lease 120초/최대 20초 주기 갱신이 있지만 Render Free 중단 후 즉시 완료를 보장하지 않는다. 원본과 ledger를 로컬 임시 디스크에 두면 안 된다.

기존 DB 연결은 TLS 암호화만 강제하고 서버 인증서를 검증하지 않는 기술 부채가 남아 있다. 이번 OCR 점검에서 변경하지 않았으며, 운영 보안 정책과 대조해야 한다.

## 6. 검증 결과 및 재실행 방법

모든 OCR detection은 Mock이다. 자동 fixture는 provider를 `none`으로 설정하고 실제 `vision.ImageAnnotatorClient` 생성 시 실패하도록 막는다. OCR 활성 경로를 검증하는 개별 테스트만 Mock provider를 주입하거나 모의 클라이언트를 사용한다. 인증 정보는 읽거나 출력하지 않았다.

| 검사 | 이번 실행 결과 |
| --- | --- |
| 최종 전체 백엔드, SQLite, 기본 OCR off | 330 passed, 6 skipped, 30 subtests passed |
| 격리 PostgreSQL 16, 기존 OCR/예산/기간/문서 API | 70 passed |
| 추가 사전 점검, 격리 PostgreSQL | 2 passed |
| 합성 데이터 DB dump/restore 리허설 | 문서·추출·분석·ledger 등 7개 테이블 체크섬 동일; 사용량 900건·남은 예산 0·cache 보존 |
| 프론트 단위 테스트 | 15 passed |
| 프론트 production build | 성공, 예시 API 주소 사용·배포 없음 |
| Python 의존성 | `pip check` 통과 |

SQLite suite의 건너뜀은 PostgreSQL 전용 검사 5개와 실제 Gemini API 검사 1개다. PostgreSQL 대상 OCR 검사는 위 별도 실행에 포함했고, 실제 Gemini 호출은 계속 제외했다. Starlette/httpx 및 google-genai 타입 관련 기존 deprecation 경고 2개가 남아 있다. 추가 이력 보존 테스트의 첫 실행에서는 fixture가 이미 만든 revision 1을 중복 삽입해 실패했으며, fixture를 수정한 재실행은 통과했다. 운영 코드 실패는 없었다.

주요 검증: 899→1 허용, 900→차단, 899에서 동시 10개→최대 1개, 중복/timeout/불확실한 commit/재시작, Pacific UTC 월 차이·PST/PDT 경계, READ COMMITTED 강제·DB 시계 공유, lease 갱신·삭제·revision 충돌, 캐시 재사용, 일반 PDF/로고/빈 페이지 불필요 호출 0회, 스캔/DOCX Mock 추출, 기존 분석 입력 연결이다. 추가 테스트는 과거 partial와 현재 ready 추출 revision 보존 및 읽기 전용 SQL의 없음/기존/이관 후 상태를 확인한다.

전체 합성 PostgreSQL 스키마에서도 읽기 전용 SQL을 실행했고, `pg_dump --format=custom` → 새 임시 DB에 `pg_restore --exit-on-error --single-transaction`으로 복원했다. 기존 테스트 데이터에 추가한 가짜 900건과 관련 데이터가 보존됐다. 이는 운영 백업·관리형 스키마 복원·Storage 객체 복구의 검증을 대신하지 않는다. 점검에 사용한 임시 PostgreSQL 컨테이너는 종료·제거했다.

```sh
# apps/api에서: 실제 Google 없이 SQLite 전체 회귀
PYTHONPATH=app ROADMAP_DB_BACKEND=sqlite ROADMAP_OCR_PROVIDER=none \
  ROADMAP_AUTO_SEED_DEV=0 .venv/bin/python -m pytest -q -rs

# apps/web에서
node --experimental-vm-modules --test tests/unit/*.test.mjs
ROADMAP_API_ORIGIN=https://api.example.com npm run build
```

PostgreSQL 재실행은 **새로 만든 localhost TLS 테스트 DB `team18_document_test`만** 사용한다. 실제 DSN을 재사용하지 않는다. 다음 변수의 URL은 예시이며, 임시 컨테이너의 포트로 바꾼다.

```sh
# apps/api에서. 대상 검증 보호가 있어도 운영/실데이터 DB에 실행 금지.
PYTHONPATH=app ROADMAP_DB_BACKEND=sqlite ROADMAP_OCR_PROVIDER=none \
  ROADMAP_AUTO_SEED_DEV=0 ROADMAP_OCR_TEST_BACKEND=postgres \
  ROADMAP_TEST_POSTGRES_URL='postgresql://postgres:local-test-only@127.0.0.1:55432/team18_document_test' \
  ROADMAP_ALLOW_TEST_DB_RESET=1 .venv/bin/python -m pytest -q \
  tests/unit/test_document_ocr.py tests/unit/test_ocr_budget_boundaries.py \
  tests/unit/test_ocr_billing_period.py tests/unit/test_ocr_preflight.py \
  tests/integration/test_documents_postgres.py
```

## 7. 구버전 워커·초기화·복원 위험과 롤백

예약은 PostgreSQL `READ COMMITTED` 트랜잭션과 전역 advisory lock `18180734`로 직렬화된다. `(document_id, unit_key)` PK와 결과 cache가 revision 재시도와 프로세스 재시작에도 유지된다. 예약 commit 전에 외부 호출하지 않고, failed/reserved도 모두 1단위로 계산한다. 문서를 삭제해도 cache 원문만 지우고 사용량 행은 남긴다. 이 안전성은 **동일 ledger를 사용하는 현재 코드 경로**에 적용된다.

구버전의 신규 INSERT는 `billing_period NOT NULL` 때문에 실패하지만, 이관 전에 이미 예약한 구버전 프로세스는 나중에 외부 호출할 수 있다. provider 환경변수 변경만으로 진행 중 호출을 취소할 수 없다. 모든 프로세스를 종료한 증거와 작업 유입 중지가 필요하다. lease 0행만으로 종료를 단정하지 않는다.

DB 초기화·과거 백업 복원·새 프로젝트로 복제·ledger 행 삭제는 이미 발생한 Google 사용량을 되돌리지 않는다. 이 때문에 내부 예산을 다시 900으로 만드는 우회가 생길 수 있다. DB 소유자 수준의 수동 삭제를 막는 별도 외부 사용량 원장/복원 감지 기능은 현재 없다. 테스트 reset opt-in을 운영에 설정하지 말고, OCR 사용 DB를 교체하거나 복원할 때는 **provider none 및 monthly limit 0**을 유지한다. 현재 기간의 실제 사용량과 손실된 예약 이력을 대조할 수 없으면 그 기간에는 재활성화하지 않는다. 나중에 월이 바뀌어도 구버전 프로세스 종료·외부 계정 사용량 검토 후 결정한다.

롤백 절차:

1. OCR을 `none`으로 바꾸고 모든 OCR 작업 프로세스를 중지한다. 필요한 경우 임시 한도 0도 사용한다. 이미 전송된 요청은 취소/환불된 것으로 간주하지 않는다.
2. DDL 실행 중 오류라면 트랜잭션 전체 rollback을 확인하고 `ocr_preflight.sql`로 기존 데이터·스키마를 재점검한다. 부분 실행을 추정해서 SQL을 반복하지 않는다.
3. 앱 오류라면 검증된 이전 앱 SHA로 롤백하되 OCR은 계속 `none`으로 둔다. 새 ledger·billing_period·cache·사용량은 그대로 유지한다. 구버전 OCR을 켜기 위해 새 컬럼/CHECK를 제거하지 않는다.
4. 데이터 훼손 때문에 백업 복원이 불가피하면 복원 전 최신 ledger·추출·사용량 snapshot도 보존하고, 먼저 격리 복구 환경에서 복원 절차를 검증한다. 복원 시점 이후의 예약과 변경을 대조·복구하기 전 실제 OCR을 켜지 않는다. 자동 병합·예산 환불 SQL은 제공하지 않는다.
5. native 문서 처리/조회가 복구되고 이력 보존이 확인된 뒤 서비스 재개 범위를 결정한다. OCR ledger의 DROP/TRUNCATE, 월 카운터 수동 초기화, 문서 재업로드를 통한 예약 기록 폐기는 롤백 방법이 아니다.

## 8. 실제 Google 연결 전 남은 작업

- [ ] 운영 Supabase의 현재 스키마·migration history·RLS/권한을 읽기 전용 SQL로 확인하고 이력 버전 불일치를 해결한다.
- [ ] 접근 제한 백업, 원본 Storage 객체 복구, 격리 복원 리허설을 마친다.
- [ ] 변경 파일 전체를 리뷰해 배포 SHA를 정하고, 구버전 워커 종료·Render 실제 설정·Linux 의존성·tzdata·자원 상한을 확인한다.
- [ ] 승인된 운영 변경 창에 migration과 OCR off 배포·회귀 확인을 완료한다.
- [ ] 사용자가 실제 연결을 별도로 결정할 때만 Cloud 프로젝트·결제 계정·Vision API 활성화·최소 권한 서비스 계정·로컬 ADC/Render Secret File을 준비한다. 현재는 결제 연결과 Secret File 등록도 수행하지 않는다. [기존 연결 안내](google-vision-ocr.md#google-cloud-준비와-로컬-연결)
- [ ] **동일 Cloud Billing 계정의 다른 프로젝트, 다른 클라이언트, 별도 DB/staging의 Vision 사용량은 이 DB의 900단위에 포함되지 않는다.** 계정 전체의 해당 SKU 사용량을 확인한다. 월별 가격 구간은 결제 계정 단위이며 태평양 시간 월초에 갱신된다. [Google 가격 구간 설명](https://cloud.google.com/billing/docs/how-to/pricing-table)
- [ ] 예산 알림은 과금 차단 장치가 아님을 확인하고 실제 SKU 사용량/청구 내역을 별도 감시한다. Cloud 측 집계 지연과 요청이 월 경계에 도착하는 시각까지 앱이 통제할 수는 없다. 내부 900 제한만으로 절대 무과금을 보장하지 않는다.
- [ ] 문서 이미지의 Google 전송에 대한 개인정보 안내, 보존 정책, 서비스 계정 키 관리·폐기 담당자를 확정한다.
- [ ] 실제 인증·RPC·한국어 OCR 품질·Render 장시간 작업 검증은 아직 미실행이다. 비용 가능성을 허용하지 않는 현재 요구에서는 `none`을 유지한다. 실제 검증 명령은 기존 OCR 안내에만 제공하며 자동 실행하지 않는다.
