# 044241c 독립 검수 5개 회귀 수정

2026-11-12 KST, `biabio0503/endpoint_team18`의 `크롤링` 브랜치에서 로컬 수정·검증했다. `git ls-remote origin refs/heads/크롤링` 결과도 `044241c8981fc0ae2366ed0e651cfc8732168192`였다. 후속 커밋과 작업 시작 전 미커밋 변경은 없었다. 운영 DB 접속·적용, push, 병합, 배포는 하지 않았다.

## 수정 전 재현 → 수정 후 결과 → 검증 경로

제품 코드 수정 전에 기존 Python 143개와 프런트엔드 23개가 통과하는 것을 확인했다. 이어서 새 PostgreSQL 회귀 19개를 실행해 **14 failed / 5 passed**를 기록했다. 다섯 문제 모두 실패로 재현됐고, 기존 확정 마감·취소 5개 사례는 통과했다. 이후 회귀 범위를 확대했다.

| 문제 | 수정 전 재현 | 수정 후 결과 | 검증한 경로 |
| --- | --- | --- | --- |
| 1. 같은 대회의 정확 마감 | 09시 카드가 당일 포함으로 표시됨. 11시 정확 시각 출처가 DB 로더에서 빠져 날짜 전용 카드가 남음 | 09시 카드 1장·원문 2개·`10:00 마감`. 09:58 응답 `valid_until=10:00`. 10시 정각과 11시 0건. 정확 시각 출처가 `expired`로 분류된 뒤에도 동일. 날짜 전용 데이커의 하루 끝 값은 명시 시각으로 취급하지 않음 | 콘테스트코리아 실제 목록/상세 처리 + 데이커 실제 상세 수집·추출 → 두 Store → PostgreSQL → 두 실제 DB 로더 → FastAPI. 저장된 API 카드의 브라우저 표시도 확인 |
| 2. 오래된 목록 날짜가 상세 연장을 덮음 | 12일 상세 11/30 저장 후 13일 목록 11/12로 상세 재요청 없이 만료 | 상세 요청 누적 1→2회. 연장 유지 시 DB 마감 11/30·추천 포함. 확정 조기 마감/취소는 제외. 네트워크/파싱 실패 때 마지막 payload·마감·성공 시각 보존 | 12·13일 `collect(known=store.known_details())` 연속 실행 → 실제 HTML 파서·Store·PostgreSQL·API. 변경 없는 과거 마감 상세 재사용 기존 테스트 유지 |
| 3. 조건부 안내를 마감으로 해석 | 조건부/가능/예정 문구 4종 모두 추천 0건 | 동일한 유효 기간에서 조건부 안내는 포함, 확정 마감·종료·취소는 제외. 안내와 현재 확정 상태가 같은 셀·같은 문장에 있어도 확정 상태 반영 | 원문 상태 셀 문구만 바꿔 목록 수집 → HTML 파서 → 후보 저장 → 실제 DB 로더·API |
| 4. 신규 상세 실패를 잃음 | 첫날 partial이나 후보 행이 없어 URL/ID와 재시도 근거가 사라짐 | 첫날 pending·성공 시각 NULL·추천 0건. 출처/ID/URL/발견·실패·다음 시도 시각 보존. 다음 날 목록에 없어도 재시도 성공 후 같은 행이 추천됨. 재실패 시 중복 없음. 목록의 날짜가 지난 경우도 재시도 | 콘테스트코리아 네트워크/파싱 실패와 데이커 상세 실패 → Store UPSERT → 실제 PostgreSQL → 누락 재확인 → API. 기존 성공 후보의 실패 보존 테스트 유지 |
| 5. 관련성 없는 출처 링크 유실 | 한쪽 제목만 관련되면 통합 카드 링크 1개 | 관련성 근거가 어느 출처에 있든 카드 1장·링크 2개. 입력 역순도 동일. 근거의 출처·URL·실제 문구 일치. 양쪽 무관하면 0건. 통합 후 상위 12개 | 실제 양쪽 수집/저장·DB 로더·API와 입력 역순 평가. 두 원문 링크를 Chromium에서 각각 클릭해 새 창 목적지 확인 |

회차, 공식 신청 URL, 접수 기간이 다른 공고의 정확 마감이 다른 카드에 적용되지 않는 PostgreSQL/API 회귀도 통과했다. 공식 URL이 없을 때 주최·제목·접수 기간이 모두 일치해야 하는 기존 판정은 유지했다.

## 구현과 마이그레이션

- 추천 API가 `include_event_context=True`로 성공 이력이 있는 현재 후보의 출처를 읽고, 동일 대회 통합 이후에 기간·관련성·상위 12개를 결정한다. 만료된 정확 시각 출처를 앞단에서 제거하지 않는다. 신규 미검증 행은 `last_success_at IS NULL`로 로더에서 제외한다.
- `application_end_precision`과 `deadline_precision`으로 원문 시각/날짜를 구분한다. 과거 성공 payload는 원문 기간 문구에서 정밀도를 복원한다. 카드·추천·캐시 만료가 같은 통합 기간 판정을 사용한다.
- 신규 마이그레이션 `20261112030228_activity_candidate_verification_retry.sql`만 추가했다. `last_success_at`을 nullable로 바꾸고 미검증 재시도 인덱스를 추가한다. 기존 마이그레이션은 변경하지 않았다.
- 기존 성공 후보와 이틀치 스냅샷·본문 버전·실행 이력이 있는 DB에 새 마이그레이션을 적용하고 모든 기존 행을 전후 비교했다. 성공 시각·내용·이력이 동일했고, RLS와 anon 권한 철회도 유지됐다.
- 서버 예약 `10 0 * * *` = 매일 **09:10 KST**를 유지했다.

## 직접 실행한 검증

- 관련 Python **189 passed**, 실패/skip 0: 기존 143개 + 신규 46개. 신규 46개는 PostgreSQL/API 37개와 대회 판정 단위 테스트 9개다. Starlette/httpx 기존 deprecation 경고 1건.
- 프런트엔드 단위 **24 passed**, 실패/skip 0: 기존 23개 + 정확 마감 시각의 캐시 만료 1개.
- Next.js production build 통과.
- Chromium 브라우저 회귀 통과: 통합 카드·정확 시각·두 출처 이름·두 링크 새 창·근거 출처·빈 결과·부분 실패·오류·키보드 탭·캐시 재사용·390px 모바일 가로 넘침 없음. 데스크톱/모바일 PNG를 직접 확인했다.
- 학생 API 반복 조회 시 외부 소켓/공급자/크롤러 호출 **0회**, 한 출처 장애 격리, `partial`의 개별 갱신, 날짜별 이력, 예약·수동 동시 실행/예약 중복 방지 기존 회귀 통과.
- 격리 PostgreSQL 17 컨테이너, `127.0.0.1:55446/team18_dacon_test`, 테스트별 임의 스키마에서 실제 마이그레이션을 실행했다. 운영 DB 설정은 사용하지 않았다.
- `git diff --check` 통과.

```bash
DACON_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55446/team18_dacon_test \
ACTIVITY_REVIEW_API_ARTIFACT=/tmp/team18-review-api-card.json \
PYTHONPATH=apps/api/app apps/api/.venv/bin/python -m pytest -q \
  apps/api/tests/unit/test_activity_collection_regressions.py \
  apps/api/tests/unit/test_activity_event_decisions.py \
  apps/api/tests/unit/test_activity_recommendations.py \
  apps/api/tests/unit/test_contestkorea_collection.py \
  apps/api/tests/unit/test_dacon.py \
  apps/api/tests/unit/test_deployment_config.py \
  apps/api/tests/integration/test_activity_candidates.py \
  apps/api/tests/integration/test_contestkorea_postgres.py \
  apps/api/tests/integration/test_dacon_postgres.py \
  apps/api/tests/integration/test_activities_api.py \
  apps/api/tests/integration/test_activity_review_regressions.py
node --experimental-vm-modules --test apps/web/tests/unit/*.test.mjs
```

브라우저는 테스트 인증 설정으로 빌드한 로컬 Next 서버에서 `apps/web/tests/browser/activities.mjs`를 실행했다. `WEB_TEST_ORIGIN`, `PLAYWRIGHT_MODULE`, `CHROMIUM_EXECUTABLE`, `ACTIVITY_REVIEW_API_ARTIFACT`, `ACTIVITY_REVIEW_CLOSED_ARTIFACT`를 지정할 수 있다. API 테스트가 만든 두 JSON을 브라우저의 카드 응답에 사용했다.

## 증거와 한계

[수정 전 기존 143개](audits/activity-review-044241c/baseline-python.txt), [신규 실패 재현](audits/activity-review-044241c/before-regressions.txt), [최종 Python](audits/activity-review-044241c/python.txt), [프런트엔드](audits/activity-review-044241c/web-unit.txt), [빌드](audits/activity-review-044241c/build.txt), [브라우저](audits/activity-review-044241c/browser.txt), [09시 API](audits/activity-review-044241c/api-0900.json), [11시 API](audits/activity-review-044241c/api-1100.json), [데스크톱](audits/activity-review-044241c/desktop.png), [모바일](audits/activity-review-044241c/mobile.png).

미래 날짜와 외부 사이트의 연장·실패·취소를 재현하기 위해 공급자 HTTP/브라우저 경계와 학생 인증·목표는 통제된 fixture를 사용했다. 실제 수집/파싱/저장/DB 로더/추천 API 코드를 실행했지만, 이번 검증을 라이브 공급자 또는 운영 E2E로 해석하지 않는다. 브라우저는 격리 DB API의 저장된 카드 응답을 사용했다. 운영 DB 적용·push·병합·배포·실제 예약 실행은 수행하지 않았다. 전역 Python 전체 테스트가 아니라 요청한 관련 테스트 범위를 실행했다.
