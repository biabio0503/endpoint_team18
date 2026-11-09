# Himalayas 원격 채용공고 조회

이 서비스는 Himalayas 공식 검색 API에서 공고를 조회하며 DB에 저장하거나 AI 분석을 수행하지 않는다. 본문 `description_html`은 API 원본이고, `description_text`는 태그와 스크립트·스타일 내용을 제거하면서 문단과 목록의 줄바꿈을 보존한 텍스트다. 후속 분석은 `description_text`를 사용할 수 있다. 원본 HTML은 실행하거나 신뢰할 수 있는 HTML로 취급하지 않는다.

## 호출

`apps/api`에서:

```python
from app.services.himalayas import fetch_jobs

result = fetch_jobs('데이터 분석 분야에 관심이 있어요', '데이터 분석가', limit=20)
# result는 JSON 직렬화 가능한 dict; result['jobs'][0]['description_text'] 사용 가능
```

FastAPI의 `GET /api/roadmap-inputs/{request_id}/jobs?limit=20`도 같은 결과를 반환한다. 기존 로그인 또는 세션으로 본인 입력을 조회하며, 요청 중 입력이 변경되면 409를 반환한다. `limit`은 1~100, 기본 20이다. 검색 결과가 없거나 일부·전체 요청이 실패한 경우도 200 응답 본문의 `status`, `searches`, `errors`로 구별한다. 공개 API는 키 없이 동작하며, 선택적으로 서버 환경변수 `HIMALAYAS_API_KEY`를 설정할 수 있다. 키를 클라이언트에 노출하지 않는다.

외부 요청 예: `GET https://himalayas.app/jobs/api/search?q=Data%20Analyst&page=1&sort=relevant`. 검색어별 최대 두 페이지이며 `limit`은 Himalayas 검색 요청에 전달하지 않는다. 결과 상한에 도달하면 추가 페이지를 조회하지 않지만 나머지 검색어의 첫 페이지는 조회하여 이미 수집된 공고의 검색어를 합친다. 따라서 상한에 도달한 뒤 검색어별 첫 페이지에만 있는 새 공고는 반환되지 않는다.

## 결과 계약

- 최상위: `source`, `source_url`, `market_scope`, 입력값, `search_keywords`, `keyword_details`, `status`, `total_collected`, `retrieved_at`, `jobs`, `searches`, `errors`. API 응답에는 `input_revision`도 포함된다.
- `keyword_details`는 검색어마다 `direct` 또는 `related`를 기록한다. 목표 직무가 있으면 목표 문장보다 우선한다. 알 수 없는 한국어 직무나 문장은 검색하지 않고 `unmapped_role` 또는 `unmapped_goal` 오류를 반환한다. 알 수 없는 영어 직무는 짧은 영문 문자열에 일반적인 직무 명칭이 포함된 경우에만 원문 검색한다. 사전은 완전하지 않다.
- 공고: `id`(원본 `guid`), `source`, `source_url`(공식 Himalayas 공고 URL로 확인된 guid만), `title`, `company`, `company_slug`, `categories`, `parent_categories`, `seniority`, `employment_type`, `description_html`, `description_text`, `excerpt`, `published_at`, `expires_at`, `location_restrictions`, `timezone_restrictions`, `application_link`, `matched_keywords`, `match_type`. 누락된 정보는 null이다. 원본 Unix 초는 UTC ISO 8601 문자열로 바꾼다. `application_link`는 변형하지 않는다.
- `match_type`은 제목과 카테고리에 직무 키워드가 실제로 나타나는 경우 `direct` 또는 `related`, 그렇지 않으면 `unverified`다. 검색 엔진의 결과라는 사실만으로 일치를 확정하지 않으며 공고를 제외하지 않는다. 신입·경력 조건을 적용하지 않는다.
- `searches`에는 키워드별 상태, 성공 페이지 수와 응답 공고 수(중복 포함)가 담긴다. `success`는 조회한 페이지가 모두 성공한 경우이며 0건도 성공이다. `partial`은 성공 페이지와 오류가 공존, `error`는 성공 페이지가 없거나 검색어를 만들 수 없는 경우다. 제한적인 재시도를 수행하며 429 대기가 3초를 넘거나 재시도 후에도 429이면 이후 키워드를 건너뛴다. `totalCount`로 조회를 종료하지 않는다.

[Himalayas 공식 API 문서](https://himalayas.app/docs/remote-jobs-api)에 따라 화면에 표시할 때는 Himalayas 출처와 링크를 명시하고 지원에는 `application_link`를 사용해야 한다. 이 결과는 전 세계 원격공고이며 거주 국가에서 지원 가능하다는 뜻이 아니다. API 데이터의 갱신 주기 및 조기 마감에 유의한다.

## 검증

```sh
python -m unittest discover -s apps/api/tests/unit -p 'test_himalayas.py' -v
python -m unittest discover -s apps/api/tests/integration -p 'test_himalayas_api.py' -v
```

첫 번째는 모의 HTTP 응답을 사용하고, 두 번째는 모의 검색과 임시 SQLite를 사용한다. 실제 API 응답과 다르다. 실 API 검증은 별도 네트워크 접근이 가능한 환경에서 위 함수를 실행해야 한다.
