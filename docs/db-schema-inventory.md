# 데이터베이스 구조 조사

조사일: 2026-11-08. 저장소의 SQL 및 Python 코드와 기본 로컬 DB를 대조했다. DB는 읽기 전용으로 열었으며 행 내용은 수집하지 않았다. 환경변수로 다른 파일을 지정할 수 있으므로 아래 실측은 기본 경로에 한정된다. Supabase 연결과 마이그레이션 실행은 하지 않았다.

## 현재 구성과 적용 상태

- DB: SQLite, Python 표준 라이브러리 `sqlite3`; ORM 없음. `apps/api/app/repositories/`의 직접 SQL 어댑터를 사용한다. PostgreSQL 드라이버는 `apps/api/requirements.txt`에 없다.
- 연결: `apps/api/app/config.py`의 `ROADMAP_DB_PATH`, 기본값 `apps/api/var/roadmap.sqlite3`. `repositories/p1.py`에서 timeout 10초, `isolation_level=None`, `sqlite3.Row`, 연결마다 `PRAGMA foreign_keys=ON`을 설정한다. DB URL이나 Supabase 연결 설정은 구현되어 있지 않다.
- 마이그레이션: 외부 도구 없이 `p1.migrate()`가 `apps/api/migrations/*.sql`을 이름순으로 읽고 `schema_migrations(name)`에 파일명을 기록한다. 각 미적용 파일은 `BEGIN IMMEDIATE`와 함께 실행된다. 서버 시작, 개발 seed, 외부 수집 CLI에서 호출하며 별도 롤백 명령은 없다.
- 기본 DB에는 **001~003만 적용**되어 있다. 004와 005는 저장소에 구현되어 있으나 이 DB에는 해당 테이블이 없다. 서버나 스크립트를 시작하면 미적용 마이그레이션이 자동 실행될 수 있다.

## 테이블 및 제약 목록

아래는 저장소의 001~005와 자체 관리 테이블을 합친 목표 스키마다. **현 DB**는 001~003 및 `schema_migrations`만 포함한다. 타입은 SQLite DDL의 선언형을 그대로 적었다. `!`는 명시적 NOT NULL, `?`는 NULL 허용, `PK`는 기본키다. SQLite의 단일 `TEXT PRIMARY KEY`는 DDL에 별도 NOT NULL이 없으므로 PK 표시와 별도로 `!`를 붙이지 않았다. PK/UNIQUE는 SQLite가 자동 유일 인덱스를 생성한다. 명시되지 않은 FK의 삭제·갱신 동작은 기본 NO ACTION이다.

### `schema_migrations` — 현 DB 존재, 코드가 생성

- 컬럼: `name TEXT PK`.
- FK/추가 UNIQUE/명시 인덱스 없음.

### `session_owners` — 001, 현 DB 존재

- 컬럼: `owner_id TEXT PK`, `token_digest TEXT!`, `expires_at TEXT!`, `created_at TEXT!`, `last_seen_at TEXT?`.
- UNIQUE: `token_digest`. FK/명시 인덱스 없음.

### `universities` — 001, 현 DB 존재

- 컬럼: `university_id TEXT PK`, `university_name TEXT!`, `is_supported INTEGER!`.
- CHECK: `is_supported IN (0,1)`. FK/추가 UNIQUE/명시 인덱스 없음.

### `departments` — 001, 현 DB 존재

- 컬럼: `department_id TEXT PK`, `university_id TEXT!`, `department_name TEXT!`, `is_supported INTEGER!`.
- FK: `university_id → universities.university_id`. CHECK: `is_supported IN (0,1)`. 추가 UNIQUE/명시 인덱스 없음.

### `course_catalogs` — 001, 현 DB 존재

- 컬럼: `catalog_id TEXT PK`, `department_id TEXT!`, `curriculum_year INTEGER?`, `version_label TEXT!`, `scope_description TEXT!`, `completeness_status TEXT!`, `source_name TEXT!`, `source_url TEXT?`, `retrieved_at TEXT!`, `published_at TEXT?`, `is_selectable INTEGER!`.
- FK: `department_id → departments.department_id`. CHECK: `completeness_status IN ('complete','partial','unknown')`, `is_selectable IN (0,1)`. 추가 UNIQUE/명시 인덱스 없음.

### `roadmap_inputs` — 001, 현 DB 존재

- 컬럼: `request_id TEXT PK`, `owner_id TEXT!`, `career_goal TEXT?`, `target_role TEXT?`, `university_id TEXT?`, `department_id TEXT?`, `catalog_id TEXT?`, `year_level INTEGER?`, `earned_credits NUMERIC?`, `gpa NUMERIC?`, `gpa_scale NUMERIC?`, `input_revision INTEGER! DEFAULT 0`, `course_selection_revision INTEGER! DEFAULT 0`, `reviewed_catalog_id TEXT?`, `reviewed_selection_revision INTEGER?`, `reported_missing_courses INTEGER! DEFAULT 0`, `reviewed_at TEXT?`, `created_at TEXT!`, `updated_at TEXT!`.
- FK: `owner_id → session_owners.owner_id`, `university_id → universities.university_id`, `department_id → departments.department_id`, `catalog_id` 및 `reviewed_catalog_id → course_catalogs.catalog_id`. 추가 UNIQUE 없음.
- INDEX: `roadmap_inputs_owner_recent(owner_id, updated_at DESC, created_at DESC, request_id DESC)`.

### `courses` — 002, 현 DB 존재

- 컬럼: `course_id TEXT PK`, `university_id TEXT!`, `canonical_name TEXT!`, `source_course_code TEXT?`, `retired_at TEXT?`.
- FK: `university_id → universities.university_id`. 추가 UNIQUE/명시 인덱스 없음. 이름이나 과목 코드에 유일 제약은 없다.

### `catalog_courses` — 002, 현 DB 존재

- 컬럼: `catalog_id TEXT!`, `course_id TEXT!`, `course_name TEXT!`, `course_code TEXT?`, `credits NUMERIC?`, `category TEXT?`, `recommended_year INTEGER?`, `recommended_term TEXT?`, `description_text TEXT?`, `description_source_url TEXT?`.
- PK: `(catalog_id, course_id)`. FK: `catalog_id → course_catalogs.catalog_id`, `course_id → courses.course_id`. CHECK: `credits IS NULL OR credits >= 0`. 추가 UNIQUE/명시 인덱스 없음.
- 003의 `catalog_course_university_insert`, `catalog_course_university_update` 트리거는 해당 행의 삽입 또는 두 키 변경 때 과목과 목록 소속 학과의 학교가 같은지 확인한다. 부모의 학교 변경까지 감시하는 제약은 아니다.

### `input_course_states` — 002, 현 DB 존재

- 컬럼: `request_id TEXT!`, `course_id TEXT!`, `source_catalog_id TEXT!`, `is_completed INTEGER!`, `updated_at TEXT!`.
- PK: `(request_id, course_id)`. FK: `request_id → roadmap_inputs.request_id`, `course_id → courses.course_id`, `(source_catalog_id, course_id) → catalog_courses(catalog_id, course_id)`. CHECK: `is_completed IN (0,1)`. 추가 UNIQUE 없음.
- INDEX: `course_states_request_completed(request_id, is_completed)`.

### `project_documents` — 004, SQL·코드 구현, 현 DB 미적용

- 컬럼: `document_id TEXT PK`, `request_id TEXT!`, `original_filename TEXT!`, `mime_type TEXT!`, `file_size_bytes INTEGER!`, `storage_key TEXT!`, `extraction_status TEXT!`, `extraction_revision INTEGER!`, `extraction_error_code TEXT?`, `partial_confirmed_at TEXT?`, `created_at TEXT!`, `extraction_attempts INTEGER! DEFAULT 0`, `extraction_lease_until TEXT?`, `extraction_lease_token TEXT?`, `removed_at TEXT?`, `cleanup_status TEXT! DEFAULT 'not_required'`, `cleanup_attempts INTEGER! DEFAULT 0`, `cleanup_lease_until TEXT?`, `cleanup_lease_token TEXT?`, `cleanup_error_code TEXT?`.
- FK: `request_id → roadmap_inputs.request_id`. UNIQUE: `storage_key`. CHECK: `extraction_status IN ('pending','ready','partial','needs_ocr','failed')`, `cleanup_status IN ('not_required','queued','running','succeeded','failed')`.
- INDEX: `project_documents_request(request_id, removed_at, created_at)`, `project_documents_jobs(extraction_status, removed_at, extraction_lease_until)`.

### `document_extractions` — 004, SQL·코드 구현, 현 DB 미적용

- 컬럼: `document_id TEXT!`, `extraction_revision INTEGER!`, `extracted_text TEXT?`, `segments TEXT! DEFAULT '[]'`, `extraction_status TEXT!`, `limitations TEXT! DEFAULT '[]'`, `error_code TEXT?`, `created_at TEXT!`, `finished_at TEXT?`.
- PK: `(document_id, extraction_revision)`. FK: `document_id → project_documents.document_id`. CHECK: `extraction_status IN ('pending','ready','partial','needs_ocr','failed')`. 추가 UNIQUE/명시 인덱스 없음. `segments`, `limitations`는 JSON 문자열이다.

### `external_sources` — 005, SQL·코드 구현, 현 DB 미적용

- 컬럼: `source_id TEXT PK`, `source_name TEXT!`, `base_url TEXT!`, `source_kinds TEXT!`, `collection_method TEXT!`, `source_environment TEXT!`, `adapter_name TEXT!`, `collection_policy TEXT!`, `freshness_ttl_seconds INTEGER?`, `is_enabled INTEGER! DEFAULT 0`, `created_at TEXT!`, `updated_at TEXT!`.
- CHECK: `source_environment IN ('fixture','live')`, `is_enabled IN (0,1)`. FK/추가 UNIQUE/명시 인덱스 없음. `source_kinds`, `collection_policy`는 JSON 문자열이다.

### `external_collection_jobs` — 005, SQL·코드 구현, 현 DB 미적용

- 컬럼: `collection_job_id TEXT PK`, `source_id TEXT!`, `job_key TEXT!`, `scope_snapshot TEXT!`, `status TEXT!`, `coverage_status TEXT!`, `counts TEXT!`, `cursor_checkpoint TEXT?`, `attempt_count INTEGER! DEFAULT 0`, `lease_until TEXT?`, `lease_token TEXT?`, `retry_at TEXT?`, `error_code TEXT?`, `created_at TEXT!`, `started_at TEXT?`, `finished_at TEXT?`.
- FK: `source_id → external_sources.source_id`. UNIQUE: `(source_id, job_key)`. CHECK: `status IN ('queued','running','succeeded','partial','failed')`, `coverage_status IN ('complete','partial','unknown')`.
- INDEX: `external_jobs_queue(status, retry_at, lease_until)`. `scope_snapshot`, `counts`는 JSON 문자열이다.

### `external_items` — 005, SQL·코드 구현, 현 DB 미적용

- 컬럼: `external_item_id TEXT PK`, `source_id TEXT!`, `source_item_key TEXT!`, `canonical_url TEXT!`, `item_kind TEXT!`, `latest_version_id TEXT?`, `latest_validation_job_id TEXT?`, `last_collected_at TEXT?`, `last_confirmed_at TEXT?`, `last_check_attempt_at TEXT?`, `check_status TEXT!`, `check_error_code TEXT?`, `recruitment_status TEXT! DEFAULT 'unknown'`, `first_seen_at TEXT!`, `updated_at TEXT!`.
- FK: `source_id → external_sources.source_id`, `latest_version_id → external_item_versions.item_version_id`, `latest_validation_job_id → external_collection_jobs.collection_job_id`. UNIQUE: `(source_id, source_item_key)`.
- CHECK: `item_kind IN ('job_posting','competition','extracurricular')`, `check_status IN ('not_checked','confirmed','failed','not_found')`, `recruitment_status IN ('open','closed','unknown')`. 명시 인덱스 없음.

### `external_item_versions` — 005, SQL·코드 구현, 현 DB 미적용

- 컬럼: `item_version_id TEXT PK`, `external_item_id TEXT!`, `collection_job_id TEXT!`, `version_no INTEGER!`, `content_hash TEXT!`, `version_fingerprint TEXT!`, `parser_version TEXT!`, `source_url TEXT!`, `title TEXT?`, `content_type TEXT!`, `raw_content BLOB!`, `source_text TEXT!`, `segments TEXT!`, `source_facts TEXT!`, `recruitment_facts TEXT!`, `parse_status TEXT!`, `limitations TEXT!`, `collected_at TEXT!`, `confirmed_at TEXT!`, `created_at TEXT!`.
- FK: `external_item_id → external_items.external_item_id`, `collection_job_id → external_collection_jobs.collection_job_id`. UNIQUE: `(external_item_id, version_no)`. CHECK: `parse_status IN ('ready','partial')`.
- INDEX: `external_versions_item(external_item_id, version_no)`; 같은 컬럼 순서의 UNIQUE 인덱스도 있다. `segments`, `source_facts`, `recruitment_facts`, `limitations`는 JSON 문자열이다. `external_items`와 이 테이블은 서로 FK를 참조한다.

## 구현 범위와 설계 구분

- 학교 → 학과 → 목록, 학교 → 과목, 목록 ↔ 과목, 요청 ↔ 과목 관계는 위 실제 SQL에 구현됐다. `p2.py`와 `main.py`에 기준 목록 조회, 과목 조회, 이수 상태 저장 및 확인 API가 있다. 목록에 없는 기존 이수 과목도 별도로 조회하고 선택 변경 시 확인 상태를 무효화한다. 학교·학과·목록 관계의 일부는 API에서 검증하며 개별 FK만으로 전체 조합을 보장하지는 않는다.
- `roadmap_inputs`는 기본 진로·학업 입력, 세션 소유권, 입력/선택 버전과 확인 상태를 저장한다. 프로젝트 문서 메타데이터와 추출 이력은 004 및 관련 API/워커에 구현되어 있지만 현재 DB에는 아직 없다. 원본 파일은 DB가 아닌 `ROADMAP_FILE_STORAGE_PATH`의 로컬 파일 저장소에 있다.
- `docs/학생 입력 데이터 명세 (ver.3)`는 제안 명세다. 명세의 `analysis_confirmations`, `roadmap_runs` 및 실제 개설 강의·시간표 확장 데이터는 현재 마이그레이션에 테이블이 없다. 명세의 UUID/TIMESTAMPTZ/JSONB는 PostgreSQL 예시이며 현재 SQLite 선언 타입이 아니다. 로그인 계정, AI 분석·결과 생성 및 실제 학교 교육과정 데이터 수집은 현재 구현 범위가 아니다.
- 005 외부 수집은 fixture 중심의 코드와 스키마가 있으나 현재 DB 미적용이다. 실제 외부 서비스 수집은 구현되어 있지 않다.

## 마이그레이션 및 초기 데이터

| 파일 | 내용 | 기본 DB 상태 |
| --- | --- | --- |
| `001_p1.sql` | 세션, 학교·학과·목록, 입력 | 적용 |
| `002_p2_courses.sql` | 과목, 목록 연결, 이수 상태 | 적용 |
| `003_catalog_university_guard.sql` | 학교 일치 검증 트리거 | 적용 |
| `004_p3_documents.sql` | 문서 메타데이터, 추출 이력 | 미적용 |
| `005_p4_external_sources.sql` | 외부 출처·작업·항목·버전 | 미적용 |

`apps/api/app/scripts/seed_dev.py`는 가상 학교 1개, 학과 1개, 목록 2개, 과목 7개, 목록 연결 8개를 `INSERT OR IGNORE`로 적재한다. 공식 자료가 아니다. 직접 실행은 기본적으로 빈 DB 여부와 무관하게 누락된 고정 ID를 추가한다. 서버 시작 시에는 `ROADMAP_AUTO_SEED_DEV` 기본값이 `1`이고 `only_if_empty=True`로 호출되어 universities에 행이 있으면 전체 seed를 건너뛴다. `external_collect.py init-fixtures`는 별도 로컬 fixture 출처 등록이며 명령 진입 시 먼저 마이그레이션을 호출한다. 테스트는 임시 DB와 fixture를 사용한다. 이 조사에서는 이들 명령을 실행하지 않았다.

## 기본 로컬 DB 행 수

읽기 전용 실측이며 004·005 테이블은 **0행이 아니라 미존재**다. `schema_migrations`도 관리 테이블로 포함했다.

| 테이블 | 행 수 |
| --- | ---: |
| `schema_migrations` | 3 |
| `session_owners` | 1 |
| `universities` | 1 |
| `departments` | 1 |
| `course_catalogs` | 2 |
| `roadmap_inputs` | 2 |
| `courses` | 7 |
| `catalog_courses` | 8 |
| `input_course_states` | 2 |
| `project_documents`, `document_extractions` | 미존재 |
| `external_sources`, `external_collection_jobs`, `external_items`, `external_item_versions` | 미존재 |

## PostgreSQL / Supabase 전환 시 검토·수정 사항

1. SQLite 연결, 행 접근, 예외 처리 및 `?` 바인딩을 PostgreSQL 드라이버와 트랜잭션 API로 교체한다. 파일 경로 대신 안전한 연결 설정과 서버 측 자격 증명 관리가 필요하다. Supabase Auth와 현재 쿠키·토큰 소유권 모델의 관계 및 접근 권한/RLS 정책을 별도로 설계해야 한다. 현재는 PostgreSQL이나 RLS가 구현되어 있지 않다.
2. `BEGIN IMMEDIATE`는 PostgreSQL에서 사용할 수 없다. 버전 충돌 검사와 문서/외부 수집 워커의 작업 선택·lease 획득을 행 잠금 또는 원자적 조건부 갱신으로 재설계하고 동시 실행을 검증한다. SQLite의 단일 쓰기 직렬화에 의존하는 동작을 그대로 가정할 수 없다.
3. 003의 `RAISE(ABORT,...)`와 SQLite 트리거 문법을 PostgreSQL 함수/트리거 또는 적절한 제약으로 바꾼다. 부모 학교 변경도 불변식에 포함할지 결정한다. 005의 `external_items` ↔ `external_item_versions` 순환 FK는 테이블 생성 후 `ALTER TABLE`로 한쪽 FK를 추가하는 등 생성 순서를 바꾼다. 기존 FK와 제약 및 인덱스를 재검증한다.
4. `INSERT OR IGNORE`를 적절한 `ON CONFLICT ... DO NOTHING`으로 바꾸고, `CASE WHEN ?`에 전달하는 정수는 PostgreSQL의 boolean 조건에 맞게 수정한다. 기존 `ON CONFLICT ... DO UPDATE`도 드라이버 자리표시자 및 타입과 함께 검증한다. 자동 실행 마이그레이션과 SQLite 전용 `executescript`, `PRAGMA`, `schema_migrations` 관리 방식을 PostgreSQL용으로 분리한다.
5. SQLite의 느슨한 타입과 PK NULL 허용 가능성에 비해 PostgreSQL은 엄격하다. 기존 값의 NULL·타입·참조 무결성과 제약 충족 여부를 이관 전에 검증한다. ID는 TEXT 유지 또는 UUID 변환을 결정하되 fixture 출처 ID 등 UUID가 아닌 식별자도 있다. 날짜 TEXT는 형식/시간대를 검증하고 `timestamptz` 사용 여부를 결정한다. `BLOB`은 `bytea`로 변환한다. 정수 플래그는 INTEGER 유지 또는 BOOLEAN으로 일괄 변환하고 SQL 비교와 Python 직렬화도 맞춘다.
6. SQLite `NUMERIC`과 PostgreSQL `numeric`의 반환 타입·정밀도 차이, 특히 Python `Decimal`의 JSON 직렬화를 처리한다. JSON 문자열은 TEXT 유지 또는 JSONB 전환을 선택하고 `json.loads`/`json.dumps`, 기본값과 드라이버 반환형을 함께 조정한다. 문자열 정렬·타임스탬프 비교도 PostgreSQL의 collation 및 타입 의미를 검증한다.
7. DB만 이관하면 업로드 원본 파일은 포함되지 않는다. 문서 저장 어댑터와 DB 메타데이터의 이관·복원, 접근 제어 및 정리 작업을 함께 계획한다. 개발용 자동 seed가 운영 데이터를 섞지 않도록 배포 설정을 명시한다. 004·005 미적용 상태를 고려하여 대상 스키마와 데이터 이관 순서를 따로 확정한다.
