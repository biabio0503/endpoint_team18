# 데이콘·데이커 서버 수집

운영 명령은 저장소 루트에서 `python -m crawling.dacon.run`이다. Windows 예약 스크립트와 JSON 캐시 실행 경로는 제거했다. FastAPI는 크롤러를 import하거나 실행하지 않는다.

```bash
# 운영과 같은 Linux 이미지 빌드
docker build -f crawling/dacon/Dockerfile -t team18-dacon .
# 데이콘만 수동 수집
python -m crawling.dacon.run --mode manual
# 네트워크 수집 없이 DB 운영 상태/이력 조회
python -m crawling.dacon.run --status
python -m crawling.dacon.run --status --date 2026-11-12
```

`ROADMAP_DB_BACKEND=postgres`, `ROADMAP_DATABASE_URL`을 설정한다. API와 같은 PostgreSQL DB를 사용하며, DB 연결은 TLS를 요구한다. **직접 연결 또는 Session pooler(5432)**를 사용한다. 세션 advisory lock을 사용하므로 Transaction pooler(6543)는 거부한다. 비밀번호를 명령행에 직접 쓰지 말고 서버의 환경 변수/환경 그룹에 저장한다.

## 수집·저장 계약

1. 데이콘 공개 메인과 대회 탭의 처음 표시된 목록을 읽는다. 메인에 연결된 데이커 공고도 읽는다. 더보기/로그인/비공개 데이터 다운로드는 하지 않는다.
2. 진행·모집 중인 공고의 공개 상세, 데이콘의 연결된 규칙/일정 페이지를 확인한다. 데이커의 명시적 종료 공고도 상태로 저장한다. 상세 요청은 3초 간격이다.
3. `start_date`/`end_date`는 대회 기간이다. **참가 신청/접수 항목에 명시된 별도 기간**을 `application_start_at`/`application_end_at`에 저장한다. 데이커의 월/일 표시는 같은 페이지에 적힌 전체 일정의 연도를 근거로 해석이 유일한 경우만 보완한다. 대회 기간 자체를 신청 기간으로 복사하지 않는다.
4. 참가 자격 원문, 기간 근거, 실제 출처, 원문 링크, 소개/개요를 함께 저장한다. 소개는 `.ql-editor` 등 실제 본문에서 읽는다. 자격·신청 기간이 불명확하거나 전공/지역/학년 제한을 확인할 수 없으면 기록은 보관하되 추천하지 않는다.
5. 전체 검증 성공 후 하나의 트랜잭션으로 당일 스냅샷을 교체한다. 목록/상세 오류나 DB 쓰기 오류는 기존 성공 자료를 바꾸지 않는다. 명시적 빈 목록만 0건 성공으로 인정하고, 파싱 실패를 빈 목록으로 취급하지 않는다.

스냅샷 키는 KST 수집 시작일, 공고 키는 `(수집일, 출처, 원본 ID)`다. 같은 날 수동 성공은 그날 자료를 갱신하며 과거 날짜는 남긴다. `collected_count`는 종료·자격 미확인 공고를 포함한 검증된 전체 공고 수다. 추천 가능한 건수와는 다르다. 정상 0건 성공도 최신 스냅샷이므로 과거 공고로 대체하지 않는다.

## 중복 실행과 장애

전체 소스에 대해 PostgreSQL session advisory lock 하나를 사용한다. 잠금 획득 전에는 사이트에 접속하지 않는다. 겹친 실행은 `already_running` JSON을 반환하고 이력에 기록한다. 대기하거나 기존 실행을 취소하지 않는다. `scheduled`는 그 KST 날짜의 예약 성공 이력이 있으면 `already_succeeded`, `manual`은 매번 재수집한다. 운영 수집은 manual 모드로 실행한다.

프로세스 종료 시 연결이 닫히면서 잠금이 해제된다. SIGTERM은 실패 이력을 기록하고, 강제 종료/DB 단절로 남은 `running`은 다음 잠금 획득자가 `failed / interrupted`로 정리한다. DB 장애로 실패 이력조차 기록할 수 없으면 CLI가 실패 종료하며 Render 로그에서 확인한다. 종료 코드 1은 실패, 0은 성공/중복 실행 건너뜀이다.

## 추천 API

`GET /api/roadmap-inputs/{id}/activities`는 `dacon_daily_snapshots`의 최신 날짜와 `dacon_daily_items`만 조회한다. 최신 수집 실패 시 마지막 성공 자료를 사용하고 출처 상태를 `partial`로 표시한다. 조회할 때마다 신청 마감을 KST로 다시 평가한다. 콘테스트코리아와 동일한 목표 관련성 점수·참가 자격 기준을 사용하며 출처 이름과 접수 마감을 카드에 표시한다. 데이콘 DB 자료가 없거나 조회에 실패해도 콘테스트코리아는 계속 제공한다.

두 출처를 함께 수집하는 GitHub Actions와 로컬 실행 방법은 [운영 인수인계](../../docs/dacon-server-collection.md#서버에서-지금-수동-실행)를 참고한다.
