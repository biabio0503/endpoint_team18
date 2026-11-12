# cd72f43 수집·추천 검토 기록

검토일: 2026-11-12 KST. 로컬과 GitHub 원격 `biabio0503/endpoint_team18`의 `크롤링` HEAD는 모두 `cd72f4328995c3b70ac83086d710e2ec99ff2d5c`였다. 이후 커밋과 작업 시작 시 미커밋 변경은 없었다. 운영 DB의 기존 두 출처 일별 스냅샷은 0건이었다. 운영 데이터는 읽기 확인만 했으며, 변경·이관 검증은 별도 로컬 PostgreSQL 17에서 수행했다.

## 수정 전 재현 / 수정 후 검증

기준 커밋의 `apps/api/app`, `crawling`, 마이그레이션을 `git archive cd72f43`로 임시 디렉터리에 꺼내 실제 기준 코드를 실행했다.

| 사례 | cd72f43 재현 | 수정 후 |
| --- | --- | --- |
| 1~10 → 다음 날 2~11 | 마감 전 1번이 추천 로더에서 사라짐 | 11개 후보 유지. 1번만 원문 재확인. 이후 조기 마감 확인 시 제외 |
| `접수 기간` | `success`, items=0, unverified=1. DB의 마지막 목록도 빈 목록으로 바뀜 | 공백/줄바꿈·동의 표기를 정상 파싱. 구조 변경은 partial/parse_error이고 마지막 성공 내용 보존 |
| 2페이지에만 2번 공고 | 같은 모의 페이지에서 IDs=[1], 더보기 0회 | IDs=[1,2], 더보기 1회. 중복 상세 요청 없음 |
| 동일 공식 신청 URL | 같은 대회 카드 2장 | 카드 1장·출처 링크 2개. 회차·기간 충돌은 별개. 12개 선정 전에 통합 |

기존 테스트의 의도도 유지했다. 예약/수동 동시 실행, 같은 날짜 재수집, 다음 날짜 이력 보존, 내용 버전 정리, 쓰기 실패 롤백, 중단된 세션 회복, 예정→접수 중 전환, 마감 시각 재판정, 한 출처 장애 격리, 학생 조회 중 외부 호출 0회를 검증했다. 기존 ‘빈 일별 목록이면 현재 후보도 삭제’ 기대값은 새 요구에 맞춰 ‘날짜 스냅샷 0건과 유효 누적 후보 유지’를 각각 검사하도록 바꿨다. 원문과 API 날짜 불일치 테스트는 원문의 접수 연장 내용을 우선하도록 바꿨다.

추가로 두 출처의 **전체 과거 날짜에서 ID별 최신 내용 이관**, 이미 지난 공고의 HTTP 재확인 제외, 당일 누락 재확인 중복 방지, 오류 후 마지막 성공 시각 보존, 부분 성공 갱신, 기간 미정과 파싱 실패 구분, API 확장 중 실패 시 먼저 받은 결과 보존, 마감 상세의 재사용, 숫자 ID의 출처 간 충돌, 공식 URL 없는 보수적 통합을 검증했다.

## 직접 실행한 자동 검증

- 관련 Python **143 passed**, 실패/skip 0. PostgreSQL 통합 테스트 포함. 기존 Starlette/httpx deprecation 경고 1건.
- 프론트엔드 `node --experimental-vm-modules --test apps/web/tests/unit/*.test.mjs`: **23 passed**.
- Next.js production build 통과. 로컬 검증용 HTTPS API origin과 테스트 공개 인증 설정을 사용했다.
- Playwright 화면 회귀 통과: 같은 카드 1장에 두 출처·두 링크·원문 확인 시각·재확인 지연 표시, 링크 새 창, 키보드 탭 전환, 캐시 재사용, 부분 실패/빈 목록/오류, 예정 배지, 390px 화면 가로 넘침 없음. API 응답은 고정 fixture이며 운영 E2E라고 해석하지 않는다.
- 기존 Dockerfile의 Linux 수집 이미지 빌드와 이미지 안의 신규 저장부·수집기·공유 identity 모듈 import 통과. 새 공유 모듈을 이미지에 COPY했다.
- `git diff --check` 통과.

```bash
DACON_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55440/team18_dacon_test \
PYTHONPATH=apps/api/app apps/api/.venv/bin/python -m pytest -q \
  apps/api/tests/unit/test_activity_collection_regressions.py \
  apps/api/tests/unit/test_activity_recommendations.py \
  apps/api/tests/unit/test_contestkorea_collection.py \
  apps/api/tests/unit/test_dacon.py \
  apps/api/tests/unit/test_deployment_config.py \
  apps/api/tests/integration/test_activity_candidates.py \
  apps/api/tests/integration/test_contestkorea_postgres.py \
  apps/api/tests/integration/test_dacon_postgres.py \
  apps/api/tests/integration/test_activities_api.py
node --experimental-vm-modules --test apps/web/tests/unit/*.test.mjs
```

테스트 DB 이름과 localhost 제한을 유지했다. 테스트마다 임의 스키마를 만들고 제거한다. 실수집 smoke와 자동 회귀는 PostgreSQL 인스턴스를 분리했다. 스키마만 달라도 advisory lock은 같은 DB에서 공유되기 때문이다.

## 실제 공개 공고 검증

최종 데이콘 수집은 **2026-11-12 11:39:55 KST**, 298개 고유 공고(데이콘 290, 데이커 8)를 격리 DB에 저장했다. 원문 접수 기간과 참가 조건을 만족한 추천 후보는 1개다. 더보기 버튼을 실제로 클릭해 첫 페이지 15건 → 다음 로딩 30건을 관찰한 뒤, 전체 순회를 실행했다. 반복 공고는 원본 ID로 한 번 저장했다. 목록의 종료/연습 공고는 상세를 재요청하지 않았다.

- [제주 AI·빅데이터 활용 AI Agent 개발 챌린지](https://daker.ai/public/hackathons/jeju-ai-bigdata-agent-challenge): 실제 접수 마감 2026-11-20 10:00 KST, 누구나 대상, 데이터 분석·AI 개발 목표의 추천 후보로 반환.
- [2026 서울관광 프롬프톤](https://www.contestkorea.com/sub/view.php?Txt_gbn=1&Txt_bcode=030310001&str_no=202611100065): 최종 파서로 2026-11-09~11-29 접수기간과 [공식 신청 페이지](https://prompt2026.sto.or.kr/%EC%B0%B8%EA%B0%80%EC%8B%A0%EC%B2%AD.html)를 원문 링크와 별도 추출.
- [Korea Local Marketing Hackathon 2026](https://www.contestkorea.com/sub/view.php?Txt_gbn=1&Txt_bcode=030310001&str_no=202611070021): 2026-11-07~11-16과 [공식 신청 URL](https://hackon.kr/e/002e1704)을 별도 추출.

최종 콘테스트코리아 재수집은 **2026-11-12 11:43:02 KST**, 17개 분야에서 반환 범위 합계 15,026건, 고유 ID 14,540개를 확인했다. **적격 후보 417건**(해당 실행 공모전 243·대외활동 174), 공식 신청 URL이 확인된 적격 후보 264건을 저장했다. 마감 상세 재사용 지표는 7,916건이다. 분야 확장 응답 실패 2건과 상세 기간 검증 실패를 합쳐 `parse_failures=45`, `network_failures=0`, `limited_categories=16`이었으므로 결과는 **partial**이다. 이 실패 때문에 확인된 417건을 폐기하거나 정상 0건으로 저장하지 않았다. 첫 실행에서 378건이 확인됐고 최종 코드의 확장 중 부분 결과 보존으로 417건까지 늘었다.

두 출처의 실제 저장 후보 **418건**을 읽어 관련성 평가·통합·상위 12개 선정을 수행했다. 추천 API 3회 모두 HTTP 200이며 `socket.socket.connect`, 공급자 요청, 크롤러 호출은 각각 **0회**였다. 콘테스트코리아 partial·데이콘/데이커 success 상태가 함께 반환됐다. 인증/학생 목표만 fixture로 대체했으며 공고 DB 로더와 추천 함수는 실제 코드를 사용했다. 실제 데이터에서 두 출처 통합 카드의 존재까지 검증한 것은 아니며, 통합 조건과 복수 링크 UI는 별도 fixture 테스트로 검증했다.

실제 제주 공고가 저장된 DB에서 오늘 발견 목록만 빈 목록으로 설정하고 서버 재확인을 실행했다. 실제 원문 조회 1회 후 후보 1건이 유지됐고, `last_seen_at`은 유지되며 `last_success_at`만 실제 성공 시각으로 갱신됐다. 이때 일별 수집 건수는 0이어도 추천 후보는 1건이었다.

실제 조기 마감/취소를 유발하거나 원문을 변경하지 않았다. 조기 마감·구조 변경·동일 대회와 다른 회차 구분은 통제된 fixture로 검증했다. 운영 Render의 09:10 실행과 배포 후 화면까지 검증한 것은 아니다.

## 남는 범위와 적용 순서

콘테스트코리아 발급 명세는 `limitsu` 반환 수 조정을 지원하지만 페이지/cursor/전체 이력 계약은 없다. 서비스의 분야별 최대 1,000건과 매일 누적·미마감 원문 재확인으로 범위를 넓혔다. 수집 시작 전 누락됐고 현재 응답 범위 밖인 공고까지 복원하지는 못한다. 데이콘은 접근 가능한 공개 목록의 더보기 범위, 데이커는 데이콘 홈에 노출된 공고 범위다. 로그인 전용/비공개 공고, 이미지에만 있는 접수 조건, 모호한 참가 자격은 추천을 보장하지 않는다.

`20261112021404_activity_candidates.sql` 적용 → API/Cron/프론트 배포 순서가 필요하다. 이 작업에서 Git push, 운영 DB 마이그레이션, Render 배포는 하지 않았다. 예약은 기존 `10 0 * * *`(09:10 KST), 수동은 `python -m crawling.activities.run --mode manual`을 유지한다. 자세한 정책·metrics·운영 SQL은 [콘테스트코리아 운영 문서](contestkorea-server-collection.md), Render 입력값은 [데이콘 운영 문서](dacon-server-collection.md)를 참고한다.

## 변경 파일

- 후보 상태·이관: `supabase/migrations/20261112021404_activity_candidates.sql`, `crawling/activities/candidates.py`, `crawling/activities/batch.py`
- 수집·저장·실행: `crawling/activities/run.py`, `crawling/contestkorea/collector.py`, `crawling/contestkorea/store.py`, `crawling/dacon/crawler.py`, `crawling/dacon/store.py`, `crawling/dacon/validation.py`, `crawling/dacon/run.py`, `crawling/dacon/Dockerfile`
- 제공자·DB 읽기: `apps/api/app/providers/external/contestkorea.py`, `apps/api/app/repositories/activity_candidates.py`, `apps/api/app/repositories/contestkorea.py`, `apps/api/app/repositories/dacon.py`
- 추천·화면: `apps/api/app/services/activity_identity.py`, `apps/api/app/services/activity_recommendations.py`, `apps/web/src/features/roadmap/ActivityRecommendations.js`
- 테스트: `apps/api/tests/unit/test_activity_collection_regressions.py`, `test_activity_recommendations.py`, `test_contestkorea_collection.py`, `test_dacon.py`; `apps/api/tests/integration/test_activity_candidates.py`, `test_contestkorea_postgres.py`, `test_dacon_postgres.py`; `apps/web/tests/browser/activities.mjs`
- 운영 문서: 이 파일, `docs/contestkorea-server-collection.md`, `docs/dacon-server-collection.md`
