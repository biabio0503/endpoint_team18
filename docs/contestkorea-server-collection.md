# 콘테스트코리아 누적 수집·추천 운영

## 현재 범위와 공식 계약

2026-11-10 발급 메일의 **API 명세서_Basic_콘테스트코리아(261110).pdf, DEMO v1.1, 2쪽**을 확인했다. 기본 응답은 분야별 최근 10건이지만, 같은 쪽에 **`limitsu=100`으로 반환 건수를 조정하는 옵션**이 명시되어 있다. 따라서 10건이 계약상 고정 상한이라는 기존 설명을 수정한다. [발급 명세 메일](https://mail.google.com/mail/u/0/#all/1a1c4652933c2940)

수집기는 메뉴 응답에서 확인한 네 분야만 목록 API에 요청한다. 대회·공모전은 학문•과학•IT (`030310001`), 아이디어•건축•창업 (`031410001`), 대외활동은 교육 • 강연 • 멘토링 • 세미나 (`040410001`), 전시 • 박람 • 행사 • 축제 (`040510001`)다. 발급 명세 1~3쪽의 `STR_IDXWORD`·`STR_BCODE`와 공고 자체의 대표 분야 `STR_MENU`로 판정한다. 공백·구분 기호를 무시하되 분야 전체 이름이 일치해야 하며, 복수 분야는 같은 종류의 허용 분야가 하나라도 있으면 포함한다. 범위 밖 홍보 공고는 상세 확인 전에 제외한다. 허용 메뉴가 누락되면 나머지는 수집하고 `missing_categories`에 코드를 기록하며 partial 또는 failed로 처리한다. 이전 범위 밖 후보는 재확인·추천에서 제외하되 이력은 보존한다. 데이콘·데이커에는 이 제한을 적용하지 않는다.

각 허용 분야에서 공식 `limitsu`만 100 → 200 → 400 → 800 → 1,000으로 늘린다. 요청보다 적게 반환하거나 같은 ID 집합이 반복되면 종료한다. **1,000은 이 서비스의 요청/응답 크기 보호 상한이며 공급자가 약속한 최대값이 아니다.** 분야별 결과가 상한에 도달하거나 확장이 중단되면 `limited_categories`로 표시한다. 명세에는 페이지 번호·cursor·전체 건수·전체 이력 조회 계약이 없어 전체 수집은 보장하지 않는다. 반환된 범위 안에서 ID 중복을 제거하고, 공모전/대외활동에 중복 노출된 상세도 실행당 한 번만 요청한다.

명세에 없는 파라미터는 사용하지 않는다. 2026-11-12 실측에서 학문·과학·IT 분야는 기본 요청 10건, `limitsu=100` 100건, `limitsu=200` 200건을 반환했다. 키와 키가 포함된 요청 URL은 로그·문서·DB에 저장하지 않는다. 발급 메일의 사용 기한은 **2026-11-24**이며 이후 사용에는 갱신된 키가 필요하다.

## 날짜 이력과 현재 후보

| 테이블 | 용도 |
| --- | --- |
| `contestkorea_collection_runs` | 모든 실행의 날짜·mode·success/partial/failed·건수·metrics |
| `contestkorea_daily_snapshots`, `contestkorea_daily_items` | 날짜별 마지막 완전 성공 수집 목록. 같은 날짜만 교체하며 과거 날짜는 유지 |
| `contestkorea_item_versions` | 동일 내용을 SHA-256으로 한 번만 저장. 과거 날짜가 참조하는 버전 보존 |
| `activity_candidates` | 출처 + 원본 ID별 최신 확인 내용과 현재 후보 상태. 날짜 목록과 독립 |

`20261112021404_activity_candidates.sql`은 **모든 과거 날짜에서 각 ID의 최신 버전**을 가져온다. 최신 날짜에 없는 공고도 복원한다. 이관 시 과거 성공 시각을 그대로 사용하고 `historical`로 표시한다. 첫 서버 실행이 이관된 자료를 분류하며 이미 마감된 자료를 원문 조회 대상으로 보내지 않는다. 이전 날짜 이력은 삭제하지 않는다.

현재 후보는 다음 상태를 구별한다.

- `active`: 참가 대상이 대학생/누구나이고 접수 중·예정. 상시 접수 포함.
- `expired`: 확인된 접수 마감 시각이 지남. 추천 조회 때도 재판정한다.
- `closed`, `cancelled`: 원문에서 접수 조기 마감·취소를 확인함.
- `unknown`, `ineligible`: 원문 기간 미정 또는 참가 대상 조건 미충족.
- `missing_since`: 오늘 목록에 없다는 관찰. 이것만으로 제외하지 않는다.
- `check_status=parse_error/network_error`: 재확인 실패. 기존 본문·마감·`last_success_at` 보존.
- `pending` + `last_success_at IS NULL`: 신규 발견 후 상세 검증 실패. 출처·원본 ID·URL·발견/시도/재시도 시각을 보존하며 추천 로더에서는 제외한다. 과거 성공 자료를 이관한 `pending`은 성공 시각이 있으므로 구별된다.

서버는 목록에서 빠진 **미마감 active 후보**를 원문 재확인 대상으로 유지한다. 처음 빠졌을 때는 바로 확인하고 이후 성공 확인은 20시간, 실패 재시도는 1시간 간격을 둔다. 같은 날 수동 반복 실행이 누락 후보를 계속 재조회하지 않는다. 만료·취소·확인된 마감 공고는 누락 재확인 대상에서 제외한다. 마감·취소 공고가 목록에 다시 등장해도 API 내용 서명이 같으면 기존 상세 검증 결과를 재사용한다(`reused_details`). 목록 내용이 바뀌었을 때만 상세를 다시 확인한다. 재사용으로 마지막 원문 성공 시각을 갱신하지 않는다. `last_seen_at`(목록 발견), `last_checked_at`(시도), `last_success_at`(성공)을 구분하며 실패로 성공 시각을 앞당기지 않는다. 마지막 성공 후 26시간이 지났거나 최근 확인에 실패했으면 화면에 지연 표시와 실제 마지막 확인 시각을 보여준다. 유효 기간 내에는 후보를 유지한다.

추가로 **아직 한 번도 검증에 성공하지 못한 후보**는 목록에서 빠져도 `next_check_at`에 재시도한다. 신규 실패는 UPSERT로 보존하고, 다시 실패해도 같은 출처·원본 ID 행을 유지한다. 상세에서 확인한 미마감 기간이 남아 있으면 API 목록의 오래된 마감일 때문에 사전 제외하지 않고 상세를 다시 확인한다. 변경 없는 종료 공고의 상세 재사용은 유지한다.

## 원문 검증과 부분 성공

`접수기간`, `접수 기간`, 줄바꿈, `신청기간`, `모집기간`, `참가 신청 기간`을 정규화한다. 날짜 표기 차이는 공유 KST 파서로 처리한다. **대회 개최·제출·심사 기간으로 접수 기간을 대신하지 않는다.** 원문의 접수기간은 API의 축약 날짜보다 우선하므로 연장/변경된 마감도 반영한다. 접수 상태 표에서 조기 마감·취소를 확인한다. 단순 메뉴의 ‘마감’ 문구로 공고를 닫지 않는다.

명시적인 `미정`/`추후 공지`는 정상적인 기간 미확인이다. 접수기간 표 자체가 없거나 날짜 구조가 잘못되면 파싱 실패, 연결/HTTP 실패는 네트워크 실패다. 일부 실패가 있으면 `partial`로 기록하고 **확인된 개별 공고의 갱신은 반영**한다. 마지막 성공 날짜 스냅샷은 교체하지 않는다. 신규 오류 공고를 적격 후보로 만들지 않으며, 기존 오류 공고는 마지막 성공 내용을 보존한다. 실제 적격 0건은 `success/0`이 가능하지만 누적 후보의 일괄 삭제를 뜻하지 않는다.

연도가 있는 목록 접수기간만으로 신규 공고의 마감이 확실하면 상세 조회를 건너뛴다. 연도 미상이나 원문에서 확인한 미마감 연장이 있는 공고는 원문을 확인한다. 원문에서 마감·취소가 확인되면 추천하지 않는다.

CLI와 `--status`의 `recent_runs[].metrics`에서 다음을 확인한다: `skipped_closed`(목록에서 마감으로 판정해 상세를 생략한 신규 고유 공고), `detail_requests`(목록 공고의 실제 상세 요청), `total_detail_requests`(누락·실패 후보 재확인 포함), `missing_categories`(종류별 누락 코드), `fetched_items`(분야별 확장 응답에서 ID 중복을 제거한 건수 합), `discovered_unique`(출처 내 고유 공고), `eligible_items`, `unknown_periods`, `parse_failures`, `network_failures`, `failed_categories`, `rejected_items`, `limited_categories`, `rechecked_items`, `recheck_failures`, `reused_details`. 원본 ID가 여러 분야에 걸치면 `fetched_items`와 `discovered_unique`가 다르다. 재확인 오류는 `recheck_failures`에 별도로 집계한다.

## 추천과 중복 통합

학생 요청은 PostgreSQL만 읽는다. 추천 API는 `include_event_context=True`로 성공 이력이 있는 출처를 읽으며, 마감한 정확 시각 출처도 대회 판정 근거로 보존한다. **동일 대회를 먼저 묶은 뒤** 접수 상태·마감과 목표 관련성을 판정하고 마지막에 상위 12개를 선택한다. 한 출처만 관련성이 있어도 확인된 모든 원문 링크를 유지한다. 추천 이유와 `evidence`에는 표현이 실제 있는 출처 이름·원문 URL·근거 문구를 사용한다. 출처 내부 원본 ID를 변경하지 않는다.

같은 회차·접수 날짜의 출처를 통합한 후 원문에 명시된 시각을 날짜 전용 마감보다 우선한다. 데이콘/데이커 수집의 `application_end_precision`과 응답의 `deadline_precision`은 `time`/`date`를 구분한다. 기존 자료에 필드가 없으면 원문 기간에서 정밀도를 복원하며, 계산된 하루 끝 시각 자체를 명시 시각의 증거로 사용하지 않는다. 카드 표시·추천 제외·`valid_until`은 동일한 통합 기간을 사용하고 정확 마감 정각부터 제외한다. 날짜가 다르거나 회차·공식 URL이 충돌하면 통합하지 않는다.

명시적으로 ‘접수하기/신청하기’에 연결된 URL을 `official_application_url`로 저장하며, `url`은 각 출처 원문 링크다. 홈페이지나 콘테스트코리아 상세 링크를 공식 신청 주소로 추정하지 않는다. 공식 신청 URL이 같으면 우선 근거로 사용하되 접수 기간·명시된 회차 충돌은 별개로 유지한다. 공식 URL이 없으면 주최기관·대회명·확정 접수 기간이 모두 일치해야 한다. 확인된 공식 URL이 서로 다르면 제목만으로 합치지 않는다. 카드의 `source_links`에 출처별 원본 ID·원문 링크·마지막 확인 시각을 모두 담는다.

## 실행·적용

운영자가 수집할 때마다 출처별 PostgreSQL 세션 잠금이 중복 실행을 막는다. 한 출처가 failed/partial이어도 다른 출처는 실행되며 CLI는 불완전 실행에 종료 코드 1을 반환한다.

```bash
python -m crawling.activities.run --mode manual
python -m crawling.activities.run --source contestkorea --mode manual
python -m crawling.activities.run --status
python -m crawling.activities.run --status --date 2026-11-12
```

수집 환경에 `CONTESTKOREA_API_KEY`, `ROADMAP_DB_BACKEND=postgres`, 동일 운영 DB의 `ROADMAP_DATABASE_URL`(직접/Session pooler, 6543 제외)이 필요하다. [수동 실행 절차](dacon-server-collection.md#서버에서-지금-수동-실행)를 유지한다.

**배포 전 새 마이그레이션을 적용한 뒤 API·프론트를 배포한다.** 새 후보 테이블은 RLS를 켜고 anon/authenticated/PUBLIC 권한을 철회한 서버 전용 테이블이다. 이 작업은 저장소 수정과 격리 DB 검증까지 수행했다. 운영 DB 적용, Git push, Render 배포·09:10 실제 실행은 수행하지 않았다. 검토 시작 시 운영 두 출처 스냅샷은 모두 0건이었다. 실제 공고 검증 결과와 재현/검증 명령은 [검증 기록](activity-collection-review.md)을 참고한다.

`044241c` 후속 로컬 수정에는 새 `20261112030228_activity_candidate_verification_retry.sql`이 필요하다. 기존 마이그레이션은 수정하지 않았으며 성공 후보와 과거 날짜 이력이 있는 DB에 추가 적용해 보존을 확인했다. 이번 독립 검수의 재현·검증 범위는 [5개 회귀 검증 기록](activity-review-044241c.md)을 참고한다.

```sql
SELECT source, state, count(*) FROM public.activity_candidates GROUP BY source, state;
SELECT source, original_id, state, missing_since, last_seen_at, last_checked_at,
       last_success_at, next_check_at, check_status
FROM public.activity_candidates WHERE state IN ('active','pending')
ORDER BY last_success_at;
SELECT collection_date, mode, status, collected_count, metrics, error_code
FROM public.contestkorea_collection_runs ORDER BY run_order DESC LIMIT 20;
```
