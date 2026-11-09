2026-11-09 Gemini 로드맵 운영 실패 조사·수정 기록

작업 기준은 원격/로컬 `main`이 일치한 `bb9a315632f2d374aaaa137c121ace2fe1a009a2`다. 최종 생성 규칙은 `personalized-roadmap-v5`다. 서버/프런트 배포, Git push, 운영 스키마 변경은 하지 않았다. 실제 검증에서는 지정된 **가상 학생 계획에만** 새 실행 이력을 추가했다.

**확인 사실과 원인의 한계**

- 운영 실패 실행 `ab4ac590-7ae4-4a1f-91e4-25a63c2dad43`: 2026-11-09 18:11:38 KST, `failed`, `gemini_invalid_response`, `personalized-roadmap-v3`, 모델 `gemini-3.5-flash-lite`, `result_json IS NULL`을 DB에서 확인했다.
- 직무 분석은 `partial`, 성공 19건/실패 1건, 비교 기술 57개였다. 실제 생성 범위는 Python(`confirmed_experience`), SQL(`document_supported`), Tableau·Power BI(`not_verified`) 네 개다. Excel과 pandas는 제한된 생성 범위 밖이다. Python만 경험 확인된 조건을 유지했다.
- 제공받은 화면 문구는 `roadmap_generation.invalid()`의 문구와 일치한다. 따라서 당시 코드 기준 **스키마 파싱 뒤 의미 검증에서 실패했을 가능성이 높다**. DB 코드만으로는 스키마 실패와 의미 검증 실패를 구별하지 못하며, 특정 실패 분기를 확정할 수 없다.
- 당시 미검증 응답을 저장하지 않았고, 서버 코드도 실패 분기를 기록하지 않았다. 원래 실패 응답을 복구하거나 그 응답을 fixture로 만들지는 못했다. 이후 같은 가상 입력의 수정 전 실제 Gemini 호출 두 번은 모두 검증을 통과했다. 이를 원래 장애가 해결됐다는 증거로 취급하지 않는다.
- 실제 재검증 중 **새로 관찰한 내용 결함**은 Python 심화 작업에서 범위 밖·미확인 pandas 사용을 제안한 것이다. 구조화된 `skill_targets`는 Python뿐인데 `$.roadmap[0].tasks[0].action`에는 `Pandas 라이브러리를 활용하여 ...`가 들어갔다. 기존 검증은 구조화된 기술명만 검사해서 이 응답을 통과시켰다. 최종 검증기는 `skill_not_allowed_in_prose`로 거부한다. **이 결함이 18:11의 실패 원인이라고 주장하지 않는다.**

**실패 경로와 수정**

`POST /api/roadmap-inputs/{rid}/roadmap` → 소유 계획 잠금/일관된 basis 캡처 → 캐시/활성 lease 확인 → `roadmap_runs` 생성 및 commit → `guarded_call`의 영속 예산·동시성 예약 → `model_input` → Gemini JSON 생성/스키마 파싱 → `validate_result` → 현재 basis/lease 재검사 → 성공 결과·초기 완료 체크 저장 순서다. 실패하면 해당 새 run만 `failed`로 마감한다. 조회와 진행 체크는 AI를 호출하지 않는다.

| 파일 | 최종 변경 |
| --- | --- |
| `apps/api/app/services/roadmap_validation.py` | 안전한 `RoadmapValidationError`, 스키마 상세 코드, 필드 경로 정규화, 기존 DB 코드와의 호환 변환 |
| `services/gemini_jobs.py`, `services/gemini_roadmap.py` | 로드맵 전용 응답 파서 연결. 일반 공고/프로젝트 호출 동작은 유지. 확인 작업 필수 필드·표현, 허용 작업 유형, 정확한 인용, 대체과목 및 본문 기술 범위 지시 강화 |
| `services/roadmap_schemas.py` | wire schema에 전달되는 설명으로 필수 필드·참조 규칙·배열/문자열 개수 제한을 명시. 기존 구조와 로컬 엄격 검증 유지 |
| `services/roadmap_generation.py` | 전달한 입력과 동일한 근거 범위만 허용. 출력은 해당 기술의 `comparison_ref`만 허용. `allowed_task_types`, `action_required_terms`, `allowed_evidence_refs`, 후보 간 `verified_equivalent_ids` 전달. 경험 상태/작업 유형 일치 검사. 비교 데이터의 범위 밖 명명 기술을 본문에서도 거부. 최종 v5로 캐시 기준 구분 |
| `api/routes/roadmaps.py`, `app/main.py` | 실패 시 run ID + 상세 코드 + 안전한 필드 경로 연결. POST 응답에 진단 메타데이터 추가. 값·문서·prompt·비밀값·예외 원문은 로그에 넣지 않음 |
| `repositories/roadmaps.py` | 기존/신규 실패 이력의 API 호환. 저장 결과나 완료 체크를 재작성하지 않음 |
| `apps/web/src/lib/api/client.js`, `features/roadmap/roadmapErrors.mjs`, `Result.js` | 오류 종류별 한국어 안내, 이전 결과/완료 체크 보존 안내, 문의 가능한 실패 실행 ID 표시 |

확인된 입력/검증 불일치 세 가지의 회귀 테스트는 수정 전 `3 failed, 26 passed`, 수정 후 통과했다. 전달하지 않은 근거를 전체 basis에서 찾아 허용하던 문제, `learn/deepen`에 `verify_experience` 작업을 허용하던 문제, 검증된 대체과목 관계를 모델에 알려주지 않던 문제다.

실제 Pandas 응답과 본문 범위 테스트는 수정 전 `4 failed`, 수정 후 모두 통과했다. 잘못된 응답 자체를 보정해 통과시키지 않는다. 해당 fixture는 계속 거부하고, 별도로 새로 생성한 정상 실제 응답을 통과시킨다.

기존 6화면·5탭을 유지한다. 준비 기간 입력/일정 생성 기능을 추가하지 않았고 기존 기간 제외 지시와 추가 필드 거부를 유지한다. 자동 재시도·repair·추가 유료 호출은 도입하지 않았다. 로드맵 provider `max_attempts=1`, SDK attempts=1, 영속 예산, 동시성, 3분 roadmap lease, 호출 상한을 유지한다.

**진단 코드와 저장 호환**

DB 스키마 변경 없이 기존 TEXT 열에 `gemini_invalid_response:<detail_code>`를 저장한다. 과거의 `gemini_invalid_response`도 그대로 읽는다. API의 상위 `error`/`error_code`는 계속 `gemini_invalid_response`이고, POST에는 `detail_code`, `field_path`, `run_id`, 이력 GET에는 `error_detail_code`가 추가된다. 실패 `result_json`은 계속 NULL이다.

필드 경로는 POST 응답과 서버의 `roadmap_validation_failed` 구조화 로그에 남긴다. DB 이력에는 상세 코드만 영속 보관한다. 경로와 basis를 찾을 때 run ID로 서버 로그를 연결한다. 로그에는 run ID, rules version, detail code, field path만 포함한다. Pydantic의 입력 값·context·오류 원문을 저장하지 않고, 알 수 없는 필드명은 `unknown_field`로 치환한다.

| 검증 | 상세 코드 |
| --- | --- |
| JSON/필수 필드/추가 필드/형/길이·개수/enum·ID 형식 | `schema_json_invalid`, `schema_field_missing`, `schema_extra_field`, `schema_type_invalid`, `schema_bounds_invalid`, `schema_value_invalid` |
| 기술 범위/중복/본문 범위 | `skill_not_allowed`, `skill_duplicate`, `skill_not_allowed_in_prose` |
| 근거 미전달/참조 종류/중복/기술 불일치/필수 비교 누락 | `evidence_not_provided`, `evidence_ref_not_allowed`, `evidence_duplicate`, `evidence_skill_mismatch`, `evidence_comparison_missing` |
| 과목 범위/이수/대체 이수/중복/대체 중복/선정 불일치/원문 인용 | `course_not_allowed`, `course_completed`, `course_equivalent_completed`, `course_duplicate`, `course_equivalent_duplicate`, `course_selection_mismatch`, `course_evidence_mismatch` |
| 단계 ID/순서/의존 중복·전방/관련 과목 | `step_id_duplicate`, `step_order_invalid`, `dependency_duplicate`, `dependency_not_previous`, `related_course_duplicate`, `related_course_not_recommended`, `related_course_skill_mismatch` |
| 경험 상태/활동 유형/혼합/확인 표현/기초 반복 | `experience_status_mismatch`, `experience_action_mismatch`, `step_action_types_mixed`, `task_type_mismatch`, `experience_verification_wording`, `confirmed_experience_basic_practice` |
| 작업 과목 주장/ID 중복/행동 중복/금지 표현 | `task_course_claim`, `task_id_duplicate`, `task_action_duplicate`, `prohibited_expression` |

운영 조회 시 `error_code = 'gemini_invalid_response' OR error_code LIKE 'gemini_invalid_response:%'`로 과거/신규를 함께 검색할 수 있다. 예산·인증·429·시간 초과 오류 코드는 바꾸지 않았다.

**Fixture와 테스트**

- `apps/api/tests/fixtures/roadmap-incident/live-scope-violation.json`: 실제 Gemini의 합성 학생 응답. 원래 운영 실패 응답이 아니라 이번 검수에서 발견한 범위 결함이다. 과목 ID는 fixture ID로 치환했고 운영 계획/문서/사용자 ID, 원문 인용, 전체 모델 입력은 제외했다.
- `live-valid-v5.json`: 최종 실제 Gemini 응답. 응답 문장을 보정하지 않았으며 fixture의 과목 ID만 익명화했다. 19/20 부분 성공, Python 심화, 나머지 경험 확인, 5개 작업을 검증한다.
- `test_roadmap_diagnostics.py`: 상세 코드·경로, schema 파싱, 민감한 추가 필드명 비노출, 허용 기술/근거/과목/인용/경험 상태/유형/의존 관계/중복/금지 표현 거부, 부분 성공, 실제 응답 fixture.
- `roadmap_scenario.py`: v2 완료 체크 1/4 → 새 생성 실패/진단 로그 → v2 1/4 보존 → 새 성공 이력/초기 체크 0, 오래된 저장 데이터 호환과 lease/동시성. 기존 실행 목록에서 빠져 있던 과거 규칙 호환·문맥 전용 근거 시나리오 두 개도 실행하도록 했다.

실행 명령(저장소 루트):

```sh
PYTHONPATH=apps/api/app ROADMAP_TEST_POSTGRES_URL='' ROADMAP_DB_BACKEND=sqlite \
  ROADMAP_DATABASE_URL='' GEMINI_API_KEY='' RENDER=false \
  apps/api/.venv/bin/python -m pytest apps/api/tests/unit \
  apps/api/tests/integration/test_recommendations.py \
  apps/api/tests/integration/test_postgres_adapter.py \
  apps/api/tests/integration/test_job_skill_analysis_api.py \
  apps/api/tests/integration/test_project_experience_api.py \
  apps/api/tests/integration/test_roadmap_api.py \
  apps/api/tests/integration/test_guest_guardrails.py -q
node --experimental-vm-modules --test apps/web/tests/unit/*.test.mjs
PYTHONPATH=apps/api/app apps/api/.venv/bin/python \
  apps/api/tests/fixtures/recommendation-quality/evaluate.py /tmp/team18-roadmap-quality-v5.json
cmp docs/audits/recommendation-quality-2026-11-09/after.json /tmp/team18-roadmap-quality-v5.json
(cd apps/web && ROADMAP_API_ORIGIN=https://api.example.com \
  NEXT_PUBLIC_SUPABASE_URL=https://job-skills-test.supabase.co \
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=test-key npm run build)
git diff --check
```

결과: **백엔드 240 passed, 1 skipped, 30 subtests passed**, **프런트 단위 15 passed**, 추천 품질 결과 비교 동일, Next 프로덕션 빌드 성공, `git diff --check` 통과. skip은 opt-in 실제 Gemini 단위 테스트이며 실제 호출 검증은 아래 별도로 수행했다. 기존 SDK deprecation 경고 1개가 있다. 최초 추천 API 테스트 2개는 sandbox localhost bind 제한으로 실행되지 않았으며, 격리 SQLite/빈 외부 자격 증명 조건을 유지한 채 허용된 실행으로 재검증해 통과했다. 최초 기본 build는 필수 `ROADMAP_API_ORIGIN` 미설정으로 중단됐고, 위의 테스트용 HTTPS 환경을 지정한 빌드는 성공했다.

**실제 Gemini/DB 검증과 운영 반영 범위**

로컬의 수정 코드를 실행하며 서버 전용 자격 증명으로 실제 `gemini-3.5-flash-lite`를 호출했다. HTTP 인증/UI를 거친 배포 API 호출은 아니다. 지정된 합성 계획의 목표를 정확히 확인한 operator probe에서 기존 `api.routes.roadmaps.generate` 경로와 실제 PostgreSQL `ai_requests` 예산/lease를 사용했다. guest 기본 한도(시간당 60, 일일 120, 전역 일일 600)로 보수적으로 예약했고 예산·동시성 검사를 우회하거나 쿨다운을 0으로 만들지 않았다. 운영 Render의 별도 환경 override 값은 이 세션에서 확인하지 않았다.

- 실제 모델 호출은 총 4회: 수정 전 2회, 중간 검수 1회, 최종 v5 1회. 자동 retry 없음.
- 추가 요청 2회는 기존 `ai_cooldown`으로 차단됐으며 모델 호출은 0회였다. 이후 probe에도 사전 쿨다운 확인을 넣었다. 생성 API의 기존 동작대로 이 두 요청의 실패 이력이 남았다.
- 중간 v4 실행 `6efe17fb-bb4e-4ef5-8da8-5c6a36c11f89`는 당시 구조 검증을 통과했으나 사람이 본문 Pandas 결함을 확인했다. 이력을 조작하지 않고 최종 규칙을 v5로 구분해 그 결과가 새 규칙의 캐시로 재사용되지 않게 했다.
- **최종 실제 성공:** `7ec265a0-42db-4c8d-8276-ad361a22b0fb`, `personalized-roadmap-v5`, `status=partial`, 오류 없음, 4단계·5개 작업, 추천 과목 2개. `partial`은 공고 1건의 분석 실패를 반영하는 정상 생성 상태다. 기존 직무/프로젝트 근거를 재사용했으며 공고 재수집이나 프로젝트 재분석 호출은 하지 않았다.
- 운영 DB 재조회에서 기존 v2 실행 `e47d50d9-e3ac-424c-a2c7-fa85fe5cc3e8`의 **완료 체크 1/4** 보존과 새 v5 **0/5**를 확인했다. 이 계획에는 검증 과정의 새 이력 6개(실제 생성 4개, 쿨다운 차단 2개)가 추가됐다. 다른 사용자 계획, 기존 결과/체크, 운영 스키마는 변경하지 않았다.

배포 대상은 기존 Render API `https://endpoint-team18.onrender.com`의 `apps/api`와 Vercel 프런트 `https://web-seven-xi-rblasxflsf.vercel.app`의 `apps/web`이다. 배포할 내용은 v5 생성 계약/검증·진단과 오류 안내이며 DB migration은 필요 없다. 이 세션에서는 **배포 및 push하지 않았다**. 원격 main에 변경을 반영하고 기존 서비스의 배포 권한으로 재배포한 뒤, 실제 HTTPS 로그인/UI에서 새 생성·실패 안내·이력 복원을 다시 확인해야 한다.

남은 미검증 범위는 원래 18:11 실패의 특정 분기, 배포된 서비스의 새 진단 로그/화면, 별도 격리 PostgreSQL 전체 회귀다. 실제 PostgreSQL의 이력 생성/보존은 확인했으나 그 사실을 격리 PostgreSQL 전체 테스트 통과로 표현하지 않는다. 본문 기술 검사는 비교에 존재하는 명명 기술과 명시된 별칭을 검사한다. 일반적인 기술 역량 표현, 알려지지 않은 기술명, 임의 자연어 의미 전체를 완전 판별한다고 보장하지 않는다. 기존 실패가 재발하면 이제 실행 ID·상세 코드·필드 경로로 해당 분기를 특정할 수 있다.
