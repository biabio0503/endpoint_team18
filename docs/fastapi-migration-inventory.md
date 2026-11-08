# FastAPI 전환 전 API 기준

현재 구현은 `apps/api/app/main.py`의 표준 라이브러리 HTTP 서버다. 아래는 전환 작업을 위한 기존 경로 목록이며 FastAPI 전환이 완료되었다는 의미가 아니다. 웹 호출은 `apps/web/src/lib/api/client.js`를 거쳐 `/api`에 상대 경로로 전송된다. 각 입력 화면과 결과 화면에서 이 클라이언트를 사용한다.

| 메서드 | 경로 | 주요 계약 |
| --- | --- | --- |
| GET | `/api/health`, `/api/health/db` | 서버 및 DB 상태 |
| GET | `/api/reference`, `/api/universities` | 기준 데이터 |
| GET | `/api/universities/{id}/departments`, `/api/departments/{id}/catalogs` | 학교·학과별 기준 데이터 |
| POST | `/api/roadmap-inputs` | 201, 세션 발급 및 계획 생성 |
| GET | `/api/roadmap-inputs/resume`, `/api/roadmap-inputs/{id}` | 세션의 최근 계획 또는 소유 계획 조회 |
| PATCH | `/api/roadmap-inputs/{id}` | `expected_input_revision`, `changes`; 충돌 시 409 |
| GET | `/api/roadmap-inputs/{id}/courses` | 목록·선택·확인 상태와 페이지 및 검색 조건 |
| PATCH | `/api/roadmap-inputs/{id}/course-selections` | `catalog_id`, `expected_selection_revision`, `changes` |
| POST | `/api/roadmap-inputs/{id}/course-selection-review` | 입력·선택 revision과 누락 과목 여부 |
| POST | `/api/roadmap-inputs/{id}/course-recommendations` | 빈 JSON 객체, Gemini 추천 및 revision 재검사 |
| GET, POST | `/api/roadmap-inputs/{id}/documents` | 문서 목록 또는 multipart 파일·입력 revision |
| DELETE | `/api/roadmap-inputs/{id}/documents/{document_id}` | 입력 revision, 삭제 및 정리 대기 |
| POST | `/api/roadmap-inputs/{id}/documents/{document_id}/retry-extraction` | 입력 revision, 재추출 대기 |
| GET | `/api/roadmap-inputs/{id}/documents/{document_id}/extractions/{revision}` | 추출 본문과 근거 구간 |
| POST | `/api/roadmap-inputs/{id}/documents/{document_id}/extractions/{revision}/confirmation` | 부분 추출 확인, 입력 revision |

쓰기 요청은 설정된 Origin과 일치해야 한다. 개인 자원은 만료되는 HttpOnly SameSite=Strict 쿠키의 해시로 소유자를 확인한다. 오류는 `error`, `message` JSON을 사용한다. 요청별 세부 검증과 응답은 위 소스 및 통합 테스트가 기준이다. 현재 PostgreSQL에서는 문서 경로가 503이며 문서 처리는 SQLite와 로컬 파일 저장소에 결합되어 있다. PostgreSQL 전환 시 행 잠금, 작업 lease, 파일 정리와 소유권을 함께 이관해야 한다.
