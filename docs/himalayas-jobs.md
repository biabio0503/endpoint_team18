# Himalayas 원격 채용공고 조회

이 수집 서비스는 Himalayas 공식 검색 API에서 공고를 조회하며 DB에 저장하거나 직접 AI 분석을 수행하지 않는다. 별도 [Gemini 기술 스택 분석 파이프라인](job-skill-analysis.md)은 `fetch_jobs_with_keywords()`로 모델 검색어를 전달하고, 수집된 본문을 분석한다. 본문 `description_html`은 API 원본이고, `description_text`는 태그와 스크립트·스타일 내용을 제거하면서 문단과 목록의 줄바꿈을 보존한 텍스트다. 후속 분석은 `description_text`를 사용할 수 있다. 원본 HTML은 실행하거나 신뢰할 수 있는 HTML로 취급하지 않는다.

## 호출

`apps/api`에서:

```python
from app.services.himalayas import fetch_jobs

result = fetch_jobs('데이터 분석 분야에 관심이 있어요', '데이터 분석가', limit=20)
# result는 JSON 직렬화 가능한 dict; result['jobs'][0]['description_text'] 사용 가능
```

FastAPI의 `GET /api/roadmap-inputs/{request_id}/jobs?limit=20`도 같은 결과를 반환한다. 기존 로그인 또는 세션으로 본인 입력을 조회하며, 요청 중 입력이 변경되면 409를 반환한다. `limit`은 1~100, 기본 20이다. 검색 결과가 없거나 일부·전체 요청이 실패한 경우도 200 응답 본문의 `status`, `searches`, `errors`로 구별한다. 공개 API는 키 없이 동작하며, 선택적으로 서버 환경변수 `HIMALAYAS_API_KEY`를 설정할 수 있다. 키를 클라이언트에 노출하지 않는다.

외부 요청 예: `GET https://himalayas.app/jobs/api/search?q=Data%20Analyst&page=1&sort=relevant`. 각 검색어의 첫 페이지를 먼저 조회한 후 분석 가능한 고유 후보가 `limit`보다 적거나 직접 관련 표본의 목표가 부족하면 비어 있지 않은 검색어에 한해 두 번째 페이지를 조회한다. 검색어별 최대 두 페이지이며 `limit`은 Himalayas 검색 요청에 전달하지 않는다. 429로 제한되면 이후 요청을 중단한다.

## 결과 계약과 선정 기준

- 기존 최상위 필드 `source`, `source_url`, `market_scope`, 입력값, `search_keywords`, `keyword_details`, `status`, `total_collected`, `retrieved_at`, `jobs`, `searches`, `errors`는 유지한다. API 응답에는 `input_revision`도 포함된다. `total_collected`는 최종 `jobs` 개수다.
- `keyword_details`의 `direct`와 `related`는 검색어의 직무 관계다. 희망 직무가 목표 문장보다 우선하며 사전은 완전하지 않다. 알 수 없는 한국어는 검색하지 않고 `unmapped_role` 또는 `unmapped_goal`을 반환한다. 알 수 없는 영어 직무는 일반적인 직무 명칭이 포함된 짧은 문자열만 원문 검색한다.
- `jobs`는 guid로 병합한 전체 후보 중 분석에 사용할 최종 공고다. 기존 원본 데이터와 `matched_keywords`는 유지하고, `match_reason`, `seniority_group`, `analysis_eligible`, `analysis_reasons`, `source_verified`를 추가한다. `description_html`은 원문이며 `description_text`는 HTML을 제거한 것이다. 원본 Unix 초는 UTC ISO 8601 문자열로 바꾸고 `application_link`는 변형하지 않는다.
- `match_type`은 제목의 완전한 직무명 또는 모든 직무 단어의 일치(단어 순서·back-end 표기 변형 허용)를 기준으로 `direct`나 `related`로 분류한다. 제목에서 확인할 수 없으면 카테고리만 일치해도 `unverified`이며 표본에서 제외한다. `match_reason`은 `title_role_match`, `title_and_category_role_match`, `title_role_tokens_match` 또는 `no_title_role_match`이다. 카테고리는 제목 일치를 보강하는 근거로만 기록한다. 일반적인 단어 또는 본문 기술만으로 직무를 확정하지 않는다.
- `seniority` 원본은 유지한다. 공식 API의 Entry-level, Mid-level, Senior, Manager, Director, Executive 및 추가 동의어를 `entry`, `mid`, `senior`, `unknown`으로 나눈다. Manager와 Executive는 senior로 취급한다. 명시 값이 충돌하거나 해석할 수 없거나, 명시 값과 제목이 충돌하면 unknown이다. 명시 값이 없을 때 제목의 경력 표현을 보조로 사용한다.
- 본문이 없거나 공백, 마감일이 조회 시각보다 이전이거나, 관련성이 `unverified`인 고유 후보는 표본에서 제외한다. 마감일이 없으면 제외하지 않는다. 출처 URL이 확인되지 않으면 `source_verified: false`로 표시하며 이것만으로 제외하지 않는다. 반환 공고는 `analysis_eligible: true`, `analysis_reasons: ["eligible"]`이다. 지원 가능 지역을 추론하지 않는다.
- 관련성은 경력보다 우선한다. 직접 공고가 충분하면 최대 `limit // 5`개를 관련 공고에 배정하고, 직접 공고가 부족하면 관련 공고로 남은 자리를 채운다. 각 등급에서 entry → mid → senior → unknown 순으로 고려하되, senior가 전체 상한의 `limit // 4`에 도달하면 unknown을 먼저 선택한다. 대안이 없으면 senior를 더 선택한다. 같은 경력 그룹에서는 검색어별 선택 수가 적은 후보를 순환 선택하고, 동률이면 이미 선택된 동일 기업 수가 적은 후보를 우선한다. 같은 후보는 한 번만 선택한다. 분류·비율은 결정적인 초기 규칙이며 실제 시장 분포나 개인 추천 순위가 아니다.
- 추가된 `selection_summary`의 `total_candidates`는 페이지별 수신 건수의 합(중복 포함), `unique_candidates`는 고유 guid 수, `duplicate_occurrences`는 둘의 차이다. `eligible_candidates`는 제외 조건을 통과한 고유 후보 수다. `excluded_count`는 제외된 고유 후보 수이며 `excluded_by_reason`의 `unverified`, `missing_description`, `expired`는 각각의 고유 후보 수다. 한 후보에 사유가 여러 개일 수 있으므로 사유별 합계는 `excluded_count`보다 클 수 있다. `unverified_excluded`는 같은 사유 카운트의 편의 필드다. `eligible_not_selected`는 조건을 통과했지만 상한 또는 표본 구성 때문에 선택되지 않은 수다. `source_unverified_candidates`는 전체 고유 후보에서 원문 URL이 확인되지 않은 수다. `selected_count`, `direct_count`, `related_count`, `seniority_distribution`은 최종 결과의 구성이다.
- `searches`의 `received_count`는 중복을 포함한 키워드별 수신 건수다. `success`는 조회가 정상 완료된 경우이며 결과가 적거나 0건이어도 성공이다. `partial`은 성공 페이지와 오류가 공존하고, `error`는 성공 페이지가 없거나 검색어를 만들 수 없는 경우다. 제한적인 재시도를 수행하며 429 대기가 3초를 넘거나 재시도 후에도 429이면 이후 요청을 건너뛴다. `totalCount`로 조회를 종료하지 않는다.

[Himalayas 공식 API 문서](https://himalayas.app/docs/remote-jobs-api)에 따라 화면에 표시할 때는 Himalayas 출처와 링크를 명시하고 지원에는 `application_link`를 사용해야 한다. 이 결과는 전 세계 원격공고이며 거주 국가에서 지원 가능하다는 뜻이 아니다. API 데이터의 갱신 주기 및 조기 마감에 유의한다.

## 검증

```sh
python -m unittest discover -s apps/api/tests/unit -p 'test_himalayas*.py' -v
python -m unittest discover -s apps/api/tests/integration -p 'test_himalayas_api.py' -v
```

첫 번째는 모의 HTTP 응답을 사용하고, 두 번째는 모의 검색과 임시 SQLite를 사용한다. 실제 API 응답과 다르다. 실 API 검증은 별도 네트워크 접근이 가능한 환경에서 위 함수를 실행해야 한다.
