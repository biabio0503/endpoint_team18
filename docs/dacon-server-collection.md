# 공모전 서버 수집 운영 인수인계

## 현재 수집 범위 (cd72f43 이후 수정)

데이콘 홈과 `/competitions`의 실제 `button.bgBtn` 더보기를 끝까지 순회한다. 페이지의 반복 ID 집합·추가 결과 없음·버튼 종료 시 멈추고, 원본 ID로 합친 뒤 상세를 한 번만 확인한다. 더보기 네트워크 실패 시 이미 발견한 공고는 보존하고 partial로 기록한다. 데이커는 데이콘 홈에 연결된 공개 공고가 발견 범위이며 데이커 전체 목록은 보장하지 않는다. 로그인 전용·비공개 공고도 포함하지 않는다.

새 `activity_candidates` 테이블을 추천에서 읽으며 성공한 날짜별 수집 목록은 이력으로 유지한다. 누락된 미마감 후보 재확인·성공 시각 보존·원문 중복 통합·마이그레이션 순서는 [누적 수집 운영 안내](contestkorea-server-collection.md)를 따른다. 수동 CLI에서 출처별 잠금을 사용한다. 출처 결과에 partial과 metrics가 추가됐으며 partial/failed는 종료 코드 1이다. 당일 성공 0건도 누적 유효 후보 삭제를 의미하지 않는다.

2026-11-12 변경 후 실수집: 고유 공고 298건(데이콘 290, 데이커 8), 적격 후보 1건. 아래의 25건 기록은 **변경 전 첫 화면 수집 당시 기록**이다. 신규 검증은 [검증 기록](activity-collection-review.md)을 참고한다.

## 서버에서 지금 수동 실행

1. GitHub 저장소의 Settings → Secrets and variables → Actions에 `ROADMAP_DATABASE_URL`과 `CONTESTKOREA_API_KEY`를 등록한다. DB 주소는 운영 API와 같은 PostgreSQL의 TLS 직접 연결 또는 세션 풀러 주소를 사용한다.
2. Actions → 공모전 수동 수집 → Run workflow에서 `main`을 선택해 실행한다. 표준 Linux 러너가 Docker 이미지로 두 출처를 수집한다. 수집하는 동안 개인 PC를 켜둘 필요는 없다.
3. 실행 로그에서 출처별 상태와 수집 건수를 확인한다. `partial`이면 확인된 후보는 갱신됐으며 실패 항목은 로그의 지표에서 확인할 수 있다.

로컬에서도 저장소 루트에서 같은 수집을 실행할 수 있다. Python과 Chromium이 설치된 환경에서 `ROADMAP_DB_BACKEND=postgres`, `ROADMAP_DATABASE_URL`, `CONTESTKOREA_API_KEY`를 설정한다.

```bash
python -m pip install -r crawling/dacon/requirements-server.txt
python -m playwright install chromium
python -m crawling.activities.run --mode manual
```

## 마지막 성공 시각·저장 건수·날짜별 이력

같은 환경에서 다음 명령으로 DB 상태를 조회한다.

```bash
python -m crawling.activities.run --status
python -m crawling.activities.run --status --date 2026-11-12
```

`snapshot.succeeded_at`, `snapshot.collected_count`, `snapshot.collection_date`가 마지막 성공 시각·건수·한국 날짜다. `recent_runs`에 mode, status, started_at, finished_at, collected_count, error_code가 담긴다. 실패의 count는 null이고 정상 0건은 success/0이다. 첫 수집 전 snapshot은 null이다.

Supabase SQL Editor에서 같은 정보와 실제 행 수를 조회할 수 있다.

```sql
SELECT s.collection_date,
       s.succeeded_at AT TIME ZONE 'Asia/Seoul' AS last_success_kst,
       s.collected_count, count(i.original_id) AS stored_rows
FROM public.dacon_daily_snapshots s
LEFT JOIN public.dacon_daily_items i USING (collection_date)
GROUP BY s.collection_date, s.succeeded_at, s.collected_count
ORDER BY s.collection_date DESC;

SELECT collection_date, mode, status,
       started_at AT TIME ZONE 'Asia/Seoul' AS started_kst,
       finished_at AT TIME ZONE 'Asia/Seoul' AS finished_kst,
       collected_count, error_code
FROM public.dacon_collection_runs ORDER BY run_order DESC LIMIT 20;

SELECT source, original_id, payload
FROM public.dacon_daily_items
WHERE collection_date = DATE '2026-11-12'
ORDER BY source, original_id;
```

## 검증

자동 검증: 실제 PostgreSQL 17의 격리 스키마에서 예약 중복 방지, 예약 성공 후 manual 재수집, 당일 원자적 교체/중복 제거, 다음 날 이력 보존, 동시 실행 already_running, 검증/DB 쓰기 실패 롤백, 연결 종료 후 잠금 회수, 정상 0건과 실패 구분을 확인했다. 추천 API 반복 조회에서 크롤러 호출 및 HTTP 연결 호출 0회, 실패 시 기존 성공 자료·콘테스트코리아 유지, 명시적 종료 공고 제외를 확인했다.

```bash
DACON_TEST_DATABASE_URL=postgresql://postgres:<test-password>@127.0.0.1:55439/team18_dacon_test \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=apps/api/app:. \
apps/api/.venv/bin/pytest -q \
  apps/api/tests/unit/test_dacon.py \
  apps/api/tests/integration/test_dacon_postgres.py \
  apps/api/tests/unit/test_activity_recommendations.py \
  apps/api/tests/integration/test_activities_api.py
node --test apps/web/tests/unit/activity-loader.test.mjs
```

PostgreSQL 테스트는 위 전용 DB 이름과 localhost만 허용하며 테스트별 임의 스키마를 만들고 제거한다. 운영 DB 초기화는 하지 않는다. 테스트 DB에는 Supabase 호환 역할 `anon`, `authenticated`가 필요하다. PostgreSQL 테스트 환경 변수가 없으면 해당 테스트는 skip된다.

실제 공개 목록 검증에서는 25건(데이콘 17, 데이커 8)을 수집했다. 제주 AI·빅데이터 AI Agent 공고는 누구나 참가 가능하며 신청 마감 `2026-11-20 10:00 KST`가 확인됐다. 소재 AI 해커톤은 대회 진행 기간과 다른 신청 마감 `2026-11-13 12:00 KST`를 확인했지만 전공 자격이 제한되어 일반 대학생 추천에서 제외했다. 데이콘은 당시 표본의 모든 공고가 종료/연습 상태여서 상세 재수집 대상이 없었으며, 공개 상세 한 건에서 `.ql-editor` 본문 구조를 별도로 검증했다.

당시 수집 범위는 데이콘 공개 첫 화면과 메인에 연결된 데이커 공고였다. 전체 대회 목록을 보장하지 않는다. 기간/대상을 확정하지 못한 공고는 추측해 추천하지 않는다. Render 실제 09:10 실행, Render 네트워크에서 원문 접근, 운영 API 배포 후 응답은 Cron 등록/배포 이후 확인해야 한다.

보안 advisor의 새 테이블 `RLS enabled, no policy` INFO는 의도한 서버 전용 설정이다. 공개 역할의 테이블 권한도 철회했으며 공개 정책을 추가하지 않는다. [Supabase RLS 점검 기준](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy)

실제 명령 검증: `python -m crawling.activities.run --mode manual`로 2026-11-12 10:28:58 KST에 **격리된 TLS PostgreSQL**에 25건 저장했다. 동일 DB를 읽는 기존 추천 라우트에서 제주 AI Agent 공고가 HTTP 200, 출처 데이커, 신청 마감 11/20 10:00, 학생의 데이터 분석 목표에 연결된 근거와 함께 반환됐다. 라우트 3회 반복 조회 중 HTTP 연결과 크롤러 호출은 모두 0회였다. 인증/학생 프로필과 콘테스트코리아 응답만 테스트에서 대체했으며 데이콘 DB 읽기와 공고·점수 계산은 실제 코드를 사용했다. 이는 운영 Render에서 실행한 결과가 아니다.

최종 자동 테스트는 관련 Python 85개와 프론트엔드 로더 4개가 통과했다. Next.js 프로덕션 빌드도 통과했다(검증용 `ROADMAP_API_ORIGIN` 사용). Dockerfile의 Python·OS 의존성·Chromium 설치 빌드는 Linux arm64에서 통과했으며 Render의 실제 인스턴스/아키텍처 빌드는 아직 확인하지 않았다.


서버의 UTC 설정에 영향받지 않도록 Playwright context의 `timezone_id=Asia/Seoul`을 고정했다. 데이커가 브라우저 시간대에 맞춰 일정 문자열을 표시하기 때문에 이 설정이 필요하다. KST 날짜 저장뿐 아니라 수집 단계의 원문 시각도 한국 시간으로 맞춘다.

시간대 수정 후 최종 Linux 재수집은 **2026-11-12 10:32:35 KST, 25건 성공**이다. 같은 날짜의 기존 스냅샷을 갱신했으며 제주 공고의 신청 마감이 **2026-11-20 10:00 KST**로 저장·반환됨을 다시 확인했다. 별도 컨테이너의 예약 명령을 실제 수동 실행과 겹쳤을 때 `already_running`으로 종료되는 것도 확인했다. 이 수치는 격리된 테스트 DB 기준이다. 운영 DB는 수집 이력/스냅샷/공고 0건이며 Render 등록·배포 후 최초 수집이 필요하다.
