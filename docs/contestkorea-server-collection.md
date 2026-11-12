# 콘테스트코리아 조건부 수집·추천 운영

## 저장 조건

매일 09:10 KST의 공통 Render Cron Job이 콘테스트코리아와 데이콘을 각각 수집한다. 콘테스트코리아 공모전·대외활동은 아래 조건을 모두 만족한 공고만 새 스냅샷에 저장한다.

- 한국 시간 기준 **접수 중 또는 접수 예정**. 상시 접수는 접수 중으로 취급한다.
- 참가 대상에 **대학생 또는 누구나**가 명시되어 있고, 제외·추가 제한 등으로 자격이 모호하지 않다. `대학원생`만 있는 공고, `누구나 (대학생 제외)`, `대학생, 해당자 ▶` 등은 제외한다.
- 원본 ID·제목·유효한 원문 URL이 있으며 기간을 확정할 수 있다. 연도 없는 기간은 같은 공고 원문의 접수기간으로 확인한다. 현재 연도나 공고 ID로 연도를 추측하지 않는다.

확실히 대상이 아닌 공고는 상세 요청 전에도 걸러낸다. 마감·대상/기간 미확인 공고는 저장하지 않는다. 단, API 분야 조회나 상세 페이지의 네트워크 실패는 정상 0건으로 처리하지 않는다. 전체 실행을 실패로 기록하고 마지막 성공 스냅샷을 보존한다. 조건에 맞는 공고가 실제로 0개이면 success/0으로 저장한다. Basic DEMO의 분야별 최근 10건 표본 한계는 그대로다.

추천에는 **접수 중과 예정 모두** 포함한다. 예정 카드는 `접수 예정` 배지, 한국 시간의 `접수 시작`, 접수 마감을 표시한다. 응답 캐시가 `opens_at`을 넘기지 않도록 하여 시작 시각 이후 조회에서는 `접수 중`으로 재판정한다. 화면을 계속 열어 둔 경우 기존 60초 재확인 주기에 반영된다. 마감된 공고는 조회 시점에도 제외하며 진로 목표와 관련 없는 공고로 카드를 채우지 않는다.

## 저장량 절약

| 테이블 | 역할 |
| --- | --- |
| `contestkorea_collection_runs` | 날짜·실행 방식·결과·건수 등 작은 운영 기록 |
| `contestkorea_daily_snapshots` | 날짜별 마지막 성공 실행 |
| `contestkorea_item_versions` | SHA-256으로 동일 내용을 구분한 최소 공고 JSONB. 변동 없는 공고는 날짜가 바뀌어도 한 번만 저장 |
| `contestkorea_daily_items` | 날짜·원본 ID·32바이트 내용 해시로 연결한 이력 |

공고 JSON에는 ID, 종류, 제목, 분야, 주최, 참가 대상, 접수 기간, 원문 링크와 필요한 경우 원문 확인 기간만 저장한다. HTML·포스터·첨부파일·원본 API 응답·매일 바뀌는 파생 상태는 저장하지 않는다. 같은 날 재실행은 참조를 교체하고, 어느 날짜에서도 참조하지 않는 내용 버전은 같은 트랜잭션에서 정리한다. 이전 날짜가 참조하는 내용은 이력 보존을 위해 유지한다. 임의의 보관 만료일을 설정하거나 과거 이력을 일괄 삭제하지 않는다.

공고 추천 경로는 이제 두 출처 모두 PostgreSQL만 조회한다. API 메모리 캐시의 만료나 학생 새로고침으로 콘테스트코리아 네트워크 요청이 발생하지 않는다.

## 명령과 Render 설정

기존 `team18-dacon-daily` Cron Job 하나의 Docker Command를 다음으로 바꾼다. Schedule `10 0 * * *`, Root Directory 비움, Docker context `.`, Dockerfile `./crawling/dacon/Dockerfile`은 유지한다.

```bash
# 매일 09:10 KST: 두 출처가 각각 성공/실패를 기록
python -m crawling.activities.run --mode scheduled
# 전체 즉시 재수집
python -m crawling.activities.run --mode manual
# 콘테스트코리아만 즉시 재수집
python -m crawling.activities.run --source contestkorea --mode manual
# 두 출처의 마지막 성공 상태 / 특정 날짜
python -m crawling.activities.run --status
python -m crawling.activities.run --source contestkorea --status --date 2026-11-12
```

Cron 환경에 **`CONTESTKOREA_API_KEY`를 추가**하고 `ROADMAP_DB_BACKEND=postgres`, 운영 API와 동일 DB의 `ROADMAP_DATABASE_URL`(직접 또는 Session pooler 5432)을 설정한다. Web Service 환경에 있는 키가 Cron으로 자동 복사되지는 않는다. DB와 출처별 잠금을 공유하므로 동일 출처의 예약·수동이 겹치면 already_running으로 끝난다. 한 출처 실패가 다른 출처 실행을 막지는 않는다. 수동은 Render One-off Job의 startCommand로 위 명령을 사용한다. Trigger Run 버튼은 기존 실행을 취소하므로 사용하지 않는다. [Render 수동 실행 방법](dacon-server-collection.md#서버에서-지금-수동-실행)

## 적용·검증 범위

운영 Supabase에 `20261112015320_contestkorea_filtered_snapshots.sql`을 적용했다. 네 테이블 모두 RLS 활성화와 anon/authenticated 조회 권한 철회를 확인했다. 저장소 코드·Blueprint 변경은 작성했지만 이 작업에서 Git push, Render 등록/배포는 수행하지 않았다. 운영 DB의 첫 수집은 배포 후 필요하며, 검증 시점의 운영 콘테스트코리아 실행·스냅샷은 0건이고 마지막 성공 시각은 없다.

2026-11-12 10:52:19 KST 실제 API 수집을 **격리된 TLS PostgreSQL**에 실행했다. 접수 중 80건·예정 5건, 합계 85건(공모전 52·대외활동 33)이 저장됐다. 전 항목의 기간·참가 대상 조건을 재검증했다. 공고 JSON의 `sum(pg_column_size(payload))`는 39,782바이트이며 인덱스·날짜 참조·운영 기록 공간은 별도다. 이 수치를 운영 DB 저장 건수로 해석하지 않는다.

관련 Python 106개 테스트가 통과했다. 필터, 사전 제외로 상세 요청 감소, 같은 날 갱신, 다음 날 본문 중복 방지, 과거 이력, 참조 없는 버전 회수, 실패/DB 쓰기 롤백, 동시 실행 차단, 예정 공고의 추천 포함과 시작 시각 전환을 검사한다. DB에 저장한 실제 공고의 추천 라우트 응답과 3회 반복 조회 중 공급자 호출·HTTP 연결 0회도 확인했다. 테스트 DB의 학생 인증/목표만 대체했으며 공고 조회·점수 계산은 실제 코드다.

실제 예정 공고 `2026년 제3회 AMT AI 작곡대회 – KILLING DANCE 챌린지`가 저장 → 추천 응답으로 연결됐으며 `status=upcoming`, `opens_at=2026-11-16T00:00:00+09:00`을 확인했다. 웹 프로덕션 빌드와 브라우저 회귀 테스트가 통과했고 390px 모바일에서 예정 배지·접수 시작일 표시를 확인했다. 최종 Linux Docker 이미지 빌드와 해당 이미지의 `--source contestkorea --status` 명령으로 격리 DB의 성공 85건 조회도 검증했다.

```sql
SELECT collection_date, succeeded_at AT TIME ZONE 'Asia/Seoul' AS last_success_kst, collected_count
FROM public.contestkorea_daily_snapshots ORDER BY collection_date DESC;
SELECT collection_date, mode, status, collected_count, error_code
FROM public.contestkorea_collection_runs ORDER BY run_order DESC LIMIT 20;
SELECT count(*) AS content_versions, sum(pg_column_size(payload)) AS json_bytes
FROM public.contestkorea_item_versions;
```
