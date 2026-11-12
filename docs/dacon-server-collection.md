# 공모전 서버 수집 운영 인수인계

## 현재 수집 범위 (cd72f43 이후 수정)

데이콘 홈과 `/competitions`의 실제 `button.bgBtn` 더보기를 끝까지 순회한다. 페이지의 반복 ID 집합·추가 결과 없음·버튼 종료 시 멈추고, 원본 ID로 합친 뒤 상세를 한 번만 확인한다. 더보기 네트워크 실패 시 이미 발견한 공고는 보존하고 partial로 기록한다. 데이커는 데이콘 홈에 연결된 공개 공고가 발견 범위이며 데이커 전체 목록은 보장하지 않는다. 로그인 전용·비공개 공고도 포함하지 않는다.

새 `activity_candidates` 테이블을 추천에서 읽으며 성공한 날짜별 수집 목록은 이력으로 유지한다. 누락된 미마감 후보 재확인·성공 시각 보존·원문 중복 통합·마이그레이션 순서는 [누적 수집 운영 안내](contestkorea-server-collection.md)를 따른다. CLI/09:10 KST 예약·출처별 잠금은 유지한다. 출처 결과에 partial과 metrics가 추가됐으며 partial/failed는 종료 코드 1이다. 당일 성공 0건도 누적 유효 후보 삭제를 의미하지 않는다.

2026-11-12 변경 후 실수집: 고유 공고 298건(데이콘 290, 데이커 8), 적격 후보 1건. 아래의 25건 기록은 **변경 전 첫 화면 수집 당시 기록**이다. 신규 검증은 [검증 기록](activity-collection-review.md)을 참고한다.

## 이전 적용 상태 (2026-11-12 KST)

콘테스트코리아도 공통 09:10 수집에 추가했다. 조건부 저장·본문 중복 절약·접수 예정 카드 정책은 [콘테스트코리아 운영 안내](contestkorea-server-collection.md)를 따른다. `--source contestkorea` 또는 `--source dacon`으로 개별 실행할 수 있다. 아래 기존 데이콘 검증 기록은 당시 결과다.

- `크롤링` 브랜치 작업 디렉터리에 크롤러, 저장소, CLI, 추천 API/카드, Render Blueprint/Dockerfile을 작성했다. Git push와 Render 배포는 아직 수행하지 않았다.
- 운영 Supabase 프로젝트 `htuttclopxaiyhgcakkj`에 추가 마이그레이션 `20261112012208_dacon_daily_snapshots.sql`을 적용했다. 서버 이력의 version과 파일명을 일치시켰다. 기존 테이블/행은 변경하지 않았다.
- 새 테이블 세 개의 RLS가 활성화되어 있고 `anon`/`authenticated`의 SELECT 권한이 없음을 조회로 확인했다. 서버 PostgreSQL 연결로만 접근한다.
- Render Cron Job **실제 등록은 미완료**다. 이 세션에는 Render API 자격 증명/서비스 연결이 없어 생성하거나 실행하지 않았다. 운영 DB에는 아직 성공 수집 스냅샷이 없다. 운영 웹 API에도 코드 재배포가 필요하다.

## Render 대시보드 입력값

변경을 저장소의 `main` 브랜치에 반영한 뒤, `render.yaml`을 Blueprint로 동기화하거나 New → Cron Job에 아래 값을 입력한다. 기존 Web Service를 새로 만들지 않는다.

| 항목 | 값 |
| --- | --- |
| Name | `team18-dacon-daily` |
| Repository | `https://github.com/biabio0503/endpoint_team18` |
| Branch | `main` |
| Runtime / Language | `Docker` |
| Root Directory | **비워 둠** (저장소 루트; `apps/api`로 지정하지 않음) |
| Docker Build Context | `.` |
| Dockerfile Path | `./crawling/dacon/Dockerfile` |
| Docker Command | `python -m crawling.activities.run --mode scheduled` |
| Schedule | `10 0 * * *` |
| Instance Type | `Starter` (Chromium 메모리 부족/OOM이면 Standard로 조정) |
| `ROADMAP_DB_BACKEND` | `postgres` |
| `ROADMAP_DATABASE_URL` | 기존 운영 API와 **동일 DB**의 직접/Session pooler 연결 문자열; 5432, 6543 불가 |
| `CONTESTKOREA_API_KEY` | 콘테스트코리아 서버 API 키 |
| `PYTHONUNBUFFERED` | `1` |

Docker 방식에는 별도 Build Command 입력란이 없다. 빌드는 `docker build -f crawling/dacon/Dockerfile .`에 해당하며 Dockerfile 내부에서 다음 명령을 실행한다.

```bash
python -m pip install -r crawling/dacon/requirements-server.txt
python -m playwright install --with-deps chromium
```

Python `3.13.8-slim-bookworm`, Playwright `1.56.0`, Chromium 및 Linux 시스템 라이브러리가 같은 이미지에 들어간다. 이미지에 `.env`/DB 비밀번호를 복사하지 않는다. 웹 서비스는 기존 Root Directory `apps/api`, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`를 유지한다. 웹 서비스에 Playwright를 설치할 필요가 없다. 프론트엔드도 출처 표시 변경을 재배포한다.

Render cron은 UTC를 사용하므로 `00:10 UTC = 09:10 Asia/Seoul`이다. 외부 Cron Job이 실행하며 PC/브라우저/FastAPI 프로세스 타이머에 의존하지 않는다. [Render Cron Jobs 공식 문서](https://render.com/docs/cronjobs)

## 서버에서 지금 수동 실행

Cron Job이 최초 빌드에 성공한 다음, 해당 `crn-...` 서비스를 기반으로 **One-off Job**을 만든다. 예약 작업과 동일한 이미지/DB 환경에서 아래 명령을 실행한다.

```bash
python -m crawling.activities.run --mode manual
```

운영자의 터미널에서 Render API로 서버 작업을 시작하는 예시다. 로컬에서는 API 요청만 보내고 수집은 Render에서 실행된다. `RENDER_API_KEY`, `RENDER_DACON_SERVICE_ID`는 운영자 환경에 설정한다.

```bash
curl --fail-with-body --request POST \
  "https://api.render.com/v1/services/${RENDER_DACON_SERVICE_ID}/jobs" \
  --header "Authorization: Bearer ${RENDER_API_KEY}" \
  --header 'Content-Type: application/json' \
  --data '{"startCommand":"python -m crawling.activities.run --mode manual"}'
```

응답의 작업 ID로 Dashboard → 해당 서비스 → One-off Jobs → 로그를 확인한다. `success`, `already_running`, `failed` 등 DB 결과가 JSON 한 줄로 출력된다. 오늘 예약 성공 여부와 관계없이 manual은 다시 수집한다. 동시에 실행 중이면 사이트 요청 없이 `already_running`으로 끝난다.

**Cron의 Trigger Run 버튼은 운영 수동 실행에 사용하지 않는다.** Render가 기존 실행을 먼저 취소하기 때문에 이 기능의 중복 실행 규칙을 우회한다. One-off Job은 별도 프로세스이고 DB 잠금을 공유한다. [One-off Jobs](https://render.com/docs/one-off-jobs), [Trigger Run 동작](https://render.com/docs/cronjobs#manually-triggering-a-run)

## 마지막 성공 시각·저장 건수·날짜별 이력

동일한 One-off Job의 `startCommand`만 다음으로 바꾸면 수집 없이 DB 상태를 로그로 출력한다.

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
