## 실제 폴더 트리

아래는 현재 프로젝트 관련 디렉터리와 이 문서다. Git 내부 디렉터리 등은 제외했다. 빈 최하위 디렉터리는 Git이 보존할 수 있도록 내용 없는 `.gitkeep`을 두었으며 트리에는 반복 표시하지 않았다.

```text
.
├── apps/
│   ├── web/
│   │   ├── src/
│   │   │   ├── app/
│   │   │   │   ├── login/
│   │   │   │   └── (workspace)/
│   │   │   │       └── cases/
│   │   │   │           ├── new/
│   │   │   │           └── [caseId]/
│   │   │   │               ├── review/
│   │   │   │               └── roadmap/
│   │   │   ├── features/
│   │   │   │   ├── intake/components/
│   │   │   │   ├── review/components/
│   │   │   │   └── roadmap/components/
│   │   │   ├── components/
│   │   │   │   ├── ui/
│   │   │   │   └── layout/
│   │   │   └── lib/
│   │   │       ├── api/
│   │   │       └── auth/
│   │   ├── public/images/
│   │   └── tests/e2e/
│   └── api/
│       ├── app/
│       │   ├── api/routes/
│       │   ├── schemas/
│       │   ├── services/
│       │   ├── domain/
│       │   ├── repositories/
│       │   ├── db/
│       │   ├── providers/prompts/
│       │   ├── worker/
│       │   ├── core/
│       │   └── scripts/
│       └── tests/
│           ├── domain/
│           ├── integration/
│           └── fixtures/
├── contracts/
├── data/
│   ├── reference/
│   └── evaluation/
├── supabase/migrations/
├── docs/FOLDER_STRUCTURE.md
├── infra/
└── .github/workflows/
```

## 주요 폴더별 역할

아래 파일명은 앞으로 배치할 수 있는 예시이며 실제 파일을 뜻하지 않는다. `case`는 사용자 진로 준비 계획 한 건을 뜻한다. Next.js의 `(workspace)`는 URL에 이름을 노출하지 않고 화면을 묶는 라우트 그룹이며, `[caseId]`는 계획 식별자에 따라 달라지는 동적 경로다.

| 경로 | 담당하는 역할 | 앞으로 배치할 파일의 예시 | 배치 기준 |
|---|---|---|---|
| `apps/web/src/app` | URL 경로 정의와 페이지 조합 | `page.tsx` | 경로와 화면 진입점 중심으로 둔다. |
| `apps/web/src/app/login` | 로그인 경로 | `page.tsx` | 로그인 페이지 조합을 둔다. |
| `apps/web/src/app/(workspace)/cases` | 계획 목록·생성 및 개별 계획 경로 | `new/page.tsx`, `[caseId]/page.tsx` | `new`는 생성, 동적 경로는 한 계획의 화면을 조합한다. `review`, `roadmap`은 각각 확인과 로드맵 경로다. |
| `apps/web/src/features/intake` | 진로·학업 정보 입력과 문서 업로드 | `components/IntakeForm.tsx`, `api.ts` | 입력 기능 전용 UI와 기능별 API 호출을 둔다. |
| `apps/web/src/features/review` | 분석 결과 확인과 수정 | `components/ReviewForm.tsx`, `api.ts` | 분석 검토 기능에서만 쓰는 코드와 호출을 둔다. |
| `apps/web/src/features/roadmap` | 로드맵과 관련 추천 표시 | `components/RoadmapView.tsx`, `api.ts` | 로드맵 기능에 종속된 코드와 호출을 둔다. |
| `apps/web/src/components/ui` | 여러 기능에서 재사용하는 기본 UI | `Button.tsx` | 특정 기능의 업무 규칙을 포함하지 않는다. |
| `apps/web/src/components/layout` | 공통 화면 배치 | `WorkspaceLayout.tsx` | 여러 화면의 구조와 배치를 공유한다. |
| `apps/web/src/lib/api` | 공통 API 통신 기반 | `client.ts` | 기본 URL, 공통 요청·오류 처리 등을 둔다. 기능별 엔드포인트 호출은 해당 `features`에 둔다. |
| `apps/web/src/lib/auth` | 공통 인증 처리 | `session.ts` | 여러 화면에서 쓰는 인증 처리를 둔다. |
| `apps/web/public/images` | 공개 정적 이미지 | `logo.svg` | 사용자 비공개 업로드가 아닌 공개 자산을 둔다. |
| `apps/web/tests/e2e` | 사용자 흐름의 종단 간 검증 | `intake.spec.ts` | 화면부터 연결된 흐름을 검증한다. |
| `apps/api/app/api/routes` | HTTP 요청·응답과 인증·소유권 확인의 진입점 | `cases.py` | 요청을 검증하고 접근을 확인한 뒤 서비스에 위임한다. |
| `apps/api/app/schemas` | 요청·응답 및 구조화 데이터의 검증 형식 | `case.py` | 외부 경계의 데이터 형태와 검증을 정의한다. |
| `apps/api/app/services` | 여러 처리 단계를 연결하는 서비스 흐름 | `roadmap_service.py` | 규칙, 저장, 외부 연동을 조합한다. |
| `apps/api/app/domain` | 역량 비교, 준비기간 계산, 선수조건 등 핵심 규칙 | `competency_gap.py` | DB나 외부 API 접근 없이 업무 규칙을 표현한다. |
| `apps/api/app/repositories` | 데이터 조회와 저장 | `case_repository.py` | 영속 데이터 접근을 모은다. |
| `apps/api/app/db` | DB 연결과 ORM 모델 | `session.py`, `models.py` | 연결 및 영속화 모델을 둔다. |
| `apps/api/app/providers` | AI, 파일 저장소, 문서 파서 등 외부 연동 | `document_parser.py`, `ai_client.py` | 외부 시스템별 호출과 변환을 캡슐화한다. |
| `apps/api/app/providers/prompts` | AI 호출에 사용할 프롬프트 | `extract_experience.txt` | AI 제공자 호출에 쓰는 지시문을 관리한다. |
| `apps/api/app/worker` | 오래 걸리는 작업 실행과 상태 처리 | `analysis_job.py` | API와 같은 백엔드 서비스 로직을 공유하는 별도 실행 단위다. |
| `apps/api/app/core` | 공통 설정, 보안, 로깅, 오류 처리 | `config.py` | 여러 계층에 공통인 기반 기능을 둔다. |
| `apps/api/app/scripts` | 기준 데이터 적재와 API 명세 내보내기 등 보조 작업 | `load_reference.py` | 요청 처리와 분리된 운영 보조 실행을 둔다. |
| `apps/api/tests/domain` | 핵심 규칙 검증 | `test_competency_gap.py` | 외부 연동 없이 도메인 규칙을 검증한다. |
| `apps/api/tests/integration` | 계층과 외부 의존성의 연동 검증 | `test_cases_api.py` | API·저장소 등 구성 요소 간 연결을 검증한다. |
| `apps/api/tests/fixtures` | 테스트용 입력과 공통 자료 | `sample_case.json` | 비식별 테스트 자료를 재사용한다. |
| `contracts` | 프론트엔드와 백엔드가 합의할 API 명세와 계약 | `openapi.yaml` | Python과 TypeScript 실행 코드를 직접 공유하지 않고 인터페이스 계약을 공유한다. |
| `data/reference` | 진로 요구 역량, 교육과정, 개설 강좌 등 기준 데이터 | `competencies.csv` | 공유 가능한 기준 자료를 둔다. |
| `data/evaluation` | 분석·추천 평가용 비식별 예제와 자료 | `evaluation_cases.json` | 개인정보가 없는 평가 자료를 둔다. |
| `supabase/migrations` | DB 스키마 변경 이력 | `001_create_cases.sql` | 추후 적용 순서가 있는 스키마 변경을 관리한다. |
| `docs` | 팀 공통 문서 | `FOLDER_STRUCTURE.md` | 팀이 공유할 설명을 둔다. |
| `infra` | 추후 인프라 실행·배포 설정 | `deployment.yaml` | 운영 환경 구성을 둘 자리다. |
| `.github/workflows` | 추후 CI 작업 정의 | `ci.yml` | GitHub Actions 작업 정의를 둘 자리다. |

사용자가 업로드한 개인 프로젝트 문서와 개인정보는 저장소에 커밋할 `data/` 기준·평가 자료가 아니다. 비공개 저장소와 접근 통제를 통해 별도로 다룰 계획이며 구체적인 저장 방식은 아직 확정되지 않았다.

## 기능별 작업 위치 예시

각 행은 예상되는 작업 위치이며 모든 계층이 반드시 필요하다는 뜻은 아니다.

| 작업 | 시작할 위치와 각 역할 |
|---|---|
| 진로·학업 정보 입력 화면 추가 | `app/(workspace)/cases/new`에서 페이지를 조합하고 `features/intake`에서 입력 UI와 기능별 호출을 작성한다. 공통 입력 요소는 `components/ui`에 둔다. |
| 프로젝트 문서 업로드 처리 | `features/intake`에서 업로드 UI와 호출을 만들고, `api/routes`에서 요청과 소유권을 확인한다. `services`가 흐름을 연결하고 `providers`가 비공개 파일 저장소를 연동하며 메타데이터 저장은 `repositories`가 담당한다. |
| AI 문서 분석 연결 | `api/routes`가 분석 요청을 받고 `services`가 흐름을 조합한다. `worker`가 장시간 작업과 상태를 처리하고 `providers`와 `providers/prompts`가 파싱·AI 호출을 담당한다. 결과 저장은 `repositories`에 둔다. |
| 분석 결과 확인·수정 기능 | `app/(workspace)/cases/[caseId]/review`에서 화면을 조합하고 `features/review`에서 UI와 호출을 작성한다. `api/routes`와 `schemas`가 요청을 받고 `services`와 `repositories`가 수정 흐름과 저장을 담당한다. |
| 역량 차이 계산 규칙 | `domain`에 비교 규칙을 두고 `services`에서 기준 데이터와 확인된 경험을 연결한다. 필요한 조회는 `repositories`가 담당하고 `tests/domain`에서 규칙을 검증한다. |
| 준비기간에 따른 로드맵 생성 | `domain`에서 기간과 선수조건 규칙을 정의하고 `services`에서 생성 흐름을 조합한다. `repositories`가 결과를 저장하고 `api/routes`가 응답하며 `features/roadmap`이 표시한다. |
| 개설 강좌 데이터 가져오기 | 공유 가능한 기준 자료는 `data/reference`에 두고, 외부 수집 연동이 필요하면 `providers`, 적재 실행은 `scripts`, 저장은 `repositories`에서 담당한다. |
| 시간표·수강조건을 고려한 강좌 추천 | `domain`에서 시간 충돌과 수강조건 규칙을 정의하고 `services`에서 강좌와 사용자 정보를 조합한다. `repositories`가 자료를 조회하며 `api/routes`와 `features/roadmap`이 결과 전달과 표시를 담당한다. |

## 개발 시 파일 배치 원칙

- 특정 기능 전용 UI는 해당 `features`에, 여러 기능에서 쓰는 기본 UI는 `components/ui`에 둔다.
- `app`의 화면 경로 정의와 조합을 기능 구현 코드와 구분한다.
- HTTP 요청 처리는 `api/routes`, 서비스 흐름은 `services`, 핵심 계산 규칙은 `domain`에 둔다.
- 외부 AI나 저장소 연결은 `providers`, 데이터 조회·저장은 `repositories`에 둔다.
- 새 폴더를 추가하기 전에 기존 폴더의 책임을 확인한다.
- 폴더가 존재하는 것과 그 안의 기능이 구현되었는지는 별개다.
