# 현재 코드 구조

```text
apps/api/app/
  main.py                    FastAPI 진입점, 수명주기, 공통 보안·오류 처리
  config.py                  환경 설정
  api/dependencies.py        세션, 소유권, Origin, 요청·응답 공통 처리
  api/domain.py, schemas.py  입력 규칙과 API 스키마
  api/routes/                health, reference, plans, courses, recommendations, documents
  services/                  계획·과목 처리, Gemini 추천, 외부 fixture 수집
  repositories/              plans(세션·계획과 DB 연결), courses, documents, external, postgres 어댑터
  providers/                 비공개 파일 저장소, 문서 파서, 외부 fixture 어댑터
  worker/documents.py        문서 예약 작업, lease, 추출·삭제 복구
  scripts/                   로컬 seed 및 외부 fixture 수집 명령
apps/api/migrations/         SQLite 전용 마이그레이션
apps/api/tests/              격리 단위·통합 테스트
apps/web/src/app/            실제 Next.js 페이지와 공통 CSS
apps/web/src/features/       입력·문서·과목·결과 화면
apps/web/src/components/     공통 레이아웃
apps/web/src/lib/api/        API 클라이언트와 계획 세션 복원
apps/web/tests/e2e/          브라우저 사용자 흐름
supabase/migrations/         보존해야 할 PostgreSQL 마이그레이션 파일
supabase/checks/             읽기 전용 사전 검사 SQL
data/reference/              외부 수집 테스트 fixture
docs/                        운영·계약 문서, 개발 기록, 기획·목업·테스트 자료
```

`main.py`는 라우터를 등록하며 기존 `roadmap_id` 변환기는 정적 `resume`과 계획 ID를 구분합니다. 과목·계획 서비스는 기존 트랜잭션과 revision 검사를 유지합니다. 문서 라우터는 예약 및 실패 보상, 저장소는 메타데이터, provider는 파일 저장과 파싱, worker는 작업 실행과 lease를 담당합니다. Gemini 호출은 `services/gemini.py`, 후보 필터는 `services/course_recommendations.py`에 있습니다.

SQLite 경로와 seed는 로컬 개발 및 여러 격리 통합 테스트가 사용하므로 유지합니다. 외부 수집은 실제 네트워크 수집이 아닌 테스트 fixture 경로입니다. 마이그레이션·기획 문서는 기록이며 빈 자리 표시 디렉터리와 구분합니다.

## API 계약 개요

전체 요청·응답 스키마와 메서드는 실행 중인 `/openapi.json` 및 `/docs`가 기준이다. 현재 엔드포인트는 `/api/health`, `/api/health/db`, `/api/reference`, `/api/universities`, `/api/universities/{university_id}/departments`, `/api/departments/{department_id}/catalogs`, `/api/roadmap-inputs`, `/api/roadmap-inputs/resume`, `/api/roadmap-inputs/{rid}`와 계획 하위 `courses`, `course-selections`, `course-selection-review`, `course-recommendations`, `documents` 및 문서별 추출·확인·재시도 경로다. 생성은 POST, 기본 입력과 과목 선택은 PATCH, 문서 삭제는 DELETE를 사용한다. 문서 업로드는 multipart, 수정 요청은 기대 revision을 포함한다. 오류는 `error`와 `message`를 반환하며 소유권·Origin·충돌 검사를 거친다.

문서의 과거 개발 및 이관 지침은 당시 상태를 설명한다. 현재 설정과 운영 변경 전 점검은 [README](../README.md)와 [배포 안내](render-deployment.md)를 먼저 확인한다.
