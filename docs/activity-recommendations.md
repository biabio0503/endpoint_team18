# 공모전·대외활동 실데이터 추천 검증 (2026-11-12)

기준: 시작 시 `git fetch origin main` 완료. `HEAD`와 `origin/main` 모두 `8e500645d51e793a98bc025142f6f4bac9f55b3a`였다.

## 코드와 자동 검증

`GET /api/roadmap-inputs/{request_id}/activities`는 기존 `owned_context`와 계획 소유권 검사를 사용한다. 진로 목표만 필수이며 문서, 희망 직무, 직무 분석, 생성된 로드맵은 필요하지 않다. 현재 유효한 확인 경험과 명시적으로 경험 없음이라고 답한 보완 후보가 있으면 추가로 활용한다. 학생 입력은 서버에서만 매칭하며 공급자에게 보내지 않는다. Gemini 호출과 DB 마이그레이션은 없다.

Result의 다섯 번째 탭에 카드·로딩·빈 결과·실패·부분 실패를 연결했다. 활동 로더는 로드맵 조회와 독립적이며 같은 계획/입력 버전의 응답을 최대 5분, 마감 시각 이내에서 재사용한다. 탭을 떠나도 컴포넌트를 유지하고, 포커스/분 단위 확인/입력 변경/명시적 재시도로 다시 판정한다. 기존 방향키·Home·End 탭 동작과 테마를 사용한다.

공통 공고 목록은 프로세스별 메모리에 종류별로 30분 저장한다. 동시 수집은 종류별 잠금으로 합치고, 부분/전체 실패는 2분 후 재시도한다. 여러 Render 프로세스·인스턴스 간 공유 캐시는 아니다. ID 중복을 제거하며 만료된 캐시를 조회 실패 시 대신 보여주지 않는다. 개인화 응답은 `Cache-Control: no-store`다. 원문 확인을 포함한 최초 수집은 캐시 조회보다 오래 걸린다.

접수 기간은 한국 시간으로 재판정하고 날짜 마감은 당일을 포함한다. 명시된 시각, 연말을 넘는 기간, 상시 접수를 처리한다. 연도·자격이 불명확하거나 추가 참가 조건이 표시된 공고는 제외한다. 원문 제목/분야에 없는 기술 사용 의무를 만들지 않으며 낮은 관련성의 공고로 결과 수를 채우지 않는다.

고정 표본 결과:

| 학생 목표 | 추천 순서 | 근거 |
| --- | --- | --- |
| 데이터 분석가 | 공공데이터 분석 경진대회 → 소비자 데이터 분석과 마케팅 아이디어 공모전 | 입력 목표와 제목의 데이터 표현 |
| 마케팅 지망생 | 브랜드 마케팅 기획 공모전 → 소비자 데이터 분석과 마케팅 아이디어 공모전 → SNS 홍보 서포터즈 | 입력 목표와 제목의 마케팅·SNS 표현 |

자동 검증: API 108개 통과, 1개 건너뜀(기존 선택적 Gemini 실호출 테스트), 프론트 단위 23개 통과, Next.js 프로덕션 빌드 성공. API 검증에는 이번 활동 추천 53개, 기존 한영 과목 16쌍·이수 선택·수강 추천·로드맵·외부 fixture 회귀가 포함된다.

```sh
ROADMAP_DB_BACKEND=sqlite PYTHONPATH=apps/api/app apps/api/.venv/bin/python -m pytest \
  apps/api/tests/unit/test_activity_recommendations.py \
  apps/api/tests/integration/test_activities_api.py \
  apps/api/tests/unit/test_course_groups.py \
  apps/api/tests/unit/test_course_recommendations.py \
  apps/api/tests/unit/test_roadmap_generation.py \
  apps/api/tests/integration/test_course_equivalence_api.py \
  apps/api/tests/integration/test_p4_external.py -q -rs
node --experimental-vm-modules --test apps/web/tests/unit/*.test.mjs
cd apps/web
ROADMAP_API_ORIGIN=https://endpoint-team18.onrender.com npm run build
```

로컬 Chromium 브라우저 회귀도 통과했다. API를 고정 응답으로 대체하여 로드맵 조회 실패 상태에서도 목표만으로 활동 표시, 키보드 탭 이동, 조회 재사용, 부분/빈/전체/네트워크 오류 구분, 원문 링크 새 창 이동, 모바일 390px 레이아웃을 검사했다. 이 검사는 운영 E2E가 아니다. 스크립트는 `apps/web/tests/browser/activities.mjs`이고 Playwright가 필요하다. 테스트 빌드에는 `NEXT_PUBLIC_SUPABASE_URL=https://team18-test.supabase.co`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=fixture-public-key`를 사용하고 `next start -H 127.0.0.1 -p 3100`으로 실행한다. 이 테스트 설정을 운영에 적용하지 않는다.

## 실제 공급자 응답

서버 환경변수 `CONTESTKOREA_API_KEY`로 두 종류를 실제 조회했다. 키와 인증 요청 URL은 보고서·로그·브라우저 응답에 넣지 않는다. 키 없이 가상 공고로 대체하는 경로는 없다. `urllib` 전송은 리다이렉트를 따르지 않고, 오류는 고정 코드로 바꾼다.

실제 응답은 `[{"resultcode":"1","resultmsg":"성공","Data":[...]}]`이며 분야 코드는 `STR_BCODE`다. 공고의 `STR_MEETCODE`, `STR_MEETING`, `STR_MENU`, `STR_HOST`, `STR_TARGET`, `STR_DATE1`, `STR_URL` 7개 필드를 확인했다. 같은 분야 응답에도 다른 종류의 홍보 공고가 포함되어 원문 링크의 `Txt_gbn`으로 구분을 보정한다.

| 조회 | 분야 수 | 종류별 ID 중복 제거 후 | 실패 분야/파싱 실패/기간 원문 확인 실패 |
| --- | ---: | ---: | ---: |
| 공모전 `int_gbn=1` | 10 | 95 | 0 / 0 / 0 |
| 대외활동 `int_gbn=2` | 7 | 68 | 0 / 0 / 0 |

합친 고유 공고는 163건이다. 데모는 분야별 최근 등록 10건 표본이므로 전체 모집 목록이나 종류별 최종 추천 수를 의미하지 않는다.

중요한 실제 계약 차이: `STR_DATE1`은 `11.07~11.16`처럼 연도가 없다. 공고 ID나 현재 연도로 연도를 추정하지 않는다. 같은 `str_no`의 콘테스트코리아 공개 상세 페이지 접수기간 표에서 `2026.11.07 ~ 2026.11.16`을 확인하고, 양 끝 월·일이 API와 일치할 때만 `verified_period`로 사용한다. 원 API 기간도 보존·표시한다. 원문 조회 실패·불일치는 현재 접수 중으로 판단하지 않는다.

실제 표본을 매칭한 결과 데이터 분석가는 1건, 마케팅 지망생은 6건이었다. 예를 들어 데이터 목표에는 [2026년 공공데이터 활용 경진대회](https://www.contestkorea.com/sub/view.php?Txt_gbn=1&Txt_bcode=031410001&str_no=202611020029), 마감 `2026-12-01`이 추천됐다. 마케팅 목표에는 [2027년 경주시 SNS 알리미 모집](https://www.contestkorea.com/sub/view.php?Txt_gbn=2&Txt_bcode=040710001&str_no=202610300024), 마감 `2026-11-13`이 포함됐다. 추천 수는 현재 날짜·공고 갱신에 따라 달라진다.

Render 또는 키가 있는 로컬 환경에서 재검증:

```sh
python app/scripts/external_collect.py contestkorea
```

이 명령은 PostgreSQL 설정에서도 fixture용 SQLite 테이블이나 마이그레이션을 사용하지 않는다. 두 `sources.status`, 분야 수, 정규화 필드와 `verified_period`를 확인한다. 부분 실패도 종료 코드 1이다. 기존 `init-fixtures/enqueue/work` 경로는 자동 테스트용으로 유지한다.

## 배포 사이트 E2E

사용자 승인 후 구현 커밋 [`98c47a34bc67d41448a8978334de2185c2adf31c`](https://github.com/biabio0503/endpoint_team18/commit/98c47a34bc67d41448a8978334de2185c2adf31c)을 `main`에 반영했다. [Vercel 자동 배포](https://vercel.com/leejunsuks-projects/web/FjNXmJ5QRaqk8cD5hmK42aCJNtP5)는 성공 상태이며, Render OpenAPI의 새 `/api/roadmap-inputs/{rid}/activities` 경로와 실제 추천 응답으로 백엔드 반영을 확인했다.

2026-11-12 01:17 KST부터 운영 [Vercel 사이트](https://web-seven-xi-rblasxflsf.vercel.app/)에서 Chromium E2E를 실행하여 **통과**했다. 원본 응답을 대체하거나 네트워크를 모킹하지 않았다. 별도 게스트에 진로 목표만 저장한 테스트 계획을 만들고, 시작 화면의 ‘이어서 작성’으로 같은 저장 계획을 다시 열었다. 이 계획에는 문서·희망 직무·직무 분석·생성된 로드맵이 없다. 사용자의 기존 개인 계획을 검사한 것은 아니다.

| 확인 항목 | 운영 결과 |
| --- | --- |
| 기존 저장 계획 열기 | ‘이어서 작성’ 후 동일 계획 ID와 저장 목표 확인 |
| 활동 탭 | End 키로 이동, 실제 추천 카드·목표·입력 버전 표시 |
| 데이터 분석가 | 1건, 첫 추천은 공공데이터 활용 경진대회, 마감 2026-12-01 |
| 마케팅 지망생 | 목표 수정·저장 후 재열기, 6건, 첫 추천은 경주시 SNS 알리미, 마감 2026-11-13 |
| 추천 근거 | 학생 목표와 공고 제목에서 확인된 표현을 화면에서 검증 |
| 공모전 원문 보기 | 새 창의 `str_no`, 제목, 연도 포함 접수기간 일치 |
| 대외활동 원문 보기 | 새 창의 `str_no`, 제목, 연도 포함 접수기간 일치 |
| 탭 왕복·창 포커스 | 추가 활동 요청 없이 컴포넌트 응답 재사용 |
| 서버 공통 캐시 | 두 목표 모두 공모전·대외활동 `cache_hit=true`, 최초 수집 시각 유지 |
| 공급자 상태 | 두 종류 모두 `success`, 95건/68건, 실패 분야·파싱·기간 확인 실패 0 |

공개 공고 정보와 검증 결과만 남긴 [운영 E2E 증거](audits/activity-recommendations-2026-11-12/deployed-e2e.json)를 보존했다. 키·인증 토큰·테스트 계획 ID는 포함하지 않는다. 첫 원문 검사에서는 브라우저 새 창의 주소가 정해지기 전 검사하여 자동화가 실패했고, 실제 원문 URL 이동 완료를 기다리도록 검사만 수정한 뒤 두 목표 모두 통과했다. 서비스 코드는 이 재검증 과정에서 변경하지 않았다.

운영 한계: 공통 캐시가 비어 있으면 분야별 API와 공개 원문의 연도 확인 때문에 첫 조회가 오래 걸릴 수 있다. 캐시는 프로세스별이므로 서버 재시작·확장 후 다시 수집한다. 데모 표본과 보수적 자격 필터 때문에 적합한 공고가 있어도 추천 0건일 수 있다. 원문의 상세 참가 조건은 학생이 최종 확인해야 한다.
