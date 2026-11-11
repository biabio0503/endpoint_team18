# Google Cloud Vision 문서 OCR

운영 적용 전에는 [2026-11-11 OCR 사전 점검](ocr-production-preflight.md)의 스키마 비교 SQL, 백업·적용 순서, Render 설정, 롤백 및 예산 복원 주의사항을 따른다. 현재 실제 Google 연결과 운영 적용은 보류 상태다.

최신 예산 기준은 **`America/Los_Angeles`의 달력 월(DST 포함)**이다. 사용 시각은 UTC로 보관하고, 집계는 새 `billing_period`를 사용한다. 아래 과거 검증 기록의 UTC 월 설명은 이 수정으로 대체된다.

기존 PDF(pypdf), DOCX(python-docx), UTF-8 TXT 파싱에 선택적 `DOCUMENT_TEXT_DETECTION`을 연결했다. 원본은 기존 로컬/Supabase 비공개 Storage에 남으며 GCS 버킷은 필요 없다. 기본값은 `ROADMAP_OCR_PROVIDER=none`이다. 이 변경은 운영 DB·환경변수·배포를 자동 변경하지 않는다.

## 추출 흐름과 위치

업로드 형식 검증 → 기존 파서 → 필요한 PDF 페이지 또는 DOCX 참조 이미지 → 메모리 내 PNG → DB 1단위 예약 → Vision → 원문 텍스트와 병합 → `document_extractions` → 기존 읽힌 내용/분석 확인 화면 → 프로젝트 경험 분석이다. Vision의 `full_text_annotation.text`를 그대로 사용하며 Gemini로 OCR 내용을 요약하거나 보정하지 않는다.

- PDF: 읽을 수 있는 텍스트 레이어가 있으면 이미지·로고 때문에 OCR하지 않는다. 텍스트를 읽지 못하고 이미지 리소스가 있는 페이지를 렌더링한다. 순백색 렌더링과 이미지가 없는 빈 페이지는 호출하지 않는다. 원문 페이지 번호와 페이지 순서를 유지하며 한 페이지 실패는 다른 결과에 영향을 주지 않는다. 기존 빈 페이지 판정은 보수적으로 유지하므로 텍스트+빈 페이지 문서는 `partial`일 수 있다.
- DOCX: 본문·표의 문단을 순서대로 읽는다. 해당 문단이 실제 참조하는 내부 이미지만 처리하고 동일 이미지 바이트의 SHA-256으로 중복을 제거한다. 합쳐진 표 셀도 중복 방문하지 않는다. 이미지 전용 DOCX를 지원한다. 외부 링크 이미지는 가져오지 않는다.
- TXT: UTF-8/UTF-8 BOM 기존 동작이며 OCR하지 않는다.
- `segments.start/end`는 **병합된 추출 텍스트**의 문자 범위이며 원본 파일의 바이트 위치가 아니다. PDF `page`, DOCX `paragraph`는 기존 위치 규칙을 따른다. OCR에는 `source=google_vision`, DOCX에는 `image_ref`를 덧붙인다. Vision 문단을 원문 문자와 정확히 대응할 수 있는 경우에만 `ocr_paragraph`, `bbox`, `coordinate_space=ocr_image_pixels`를 기록한다. bbox는 최대 2,000px로 변환한 이미지 좌표이며 원본 PDF 좌표가 아니다. DOCX 페이지 번호는 만들지 않는다. 떠 있는 이미지는 연결 문단만 알 수 있어 실제 배치 순서를 limitations에 남긴다.

## 무료 사용량과 재시작 보호

[Vision 가격표](https://cloud.google.com/vision/pricing)는 Document Text Detection의 월 첫 1,000단위를 무료로 안내한다. 이미지 하나에 기능 하나를 적용하면 1단위이고 PDF는 페이지별 단위다. 앱은 이 중 **최대 900단위**까지만 예약한다.

```dotenv
ROADMAP_OCR_PROVIDER=none
ROADMAP_OCR_MONTHLY_UNIT_LIMIT=900
ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT=50
```

서버 환경변수만 사용하며 API·프론트엔드에서 한도를 변경할 수 없다. 월 한도는 0~900, 문서 한도는 0~50으로 강제하고 잘못된 숫자는 0으로 차단한다. 문서 한도는 해당 원본의 누적 서로 다른 OCR 페이지·이미지 수다. 재추출한다고 초기화하지 않는다.

`document_ocr_units`의 한 행이 잠재적인 유료 호출 1단위다. SQLite `BEGIN IMMEDIATE`, PostgreSQL `READ COMMITTED` 트랜잭션의 advisory lock `18180734`와 고유 키로 모든 사용자·프로세스가 미국 태평양 시간 월별 예산을 공유한다. PostgreSQL에서는 DB의 `clock_timestamp()`를 UTC로 정규화해 저장한다. 이 시각을 IANA `America/Los_Angeles`로 변환한 `YYYY-MM`이 `billing_period`다. 잠금 획득 후 산정한 같은 기간을 사용량 조회와 예약에 사용하며, 커밋 후 호출 직전에도 같은 변환으로 기간을 확인한다. 고정 UTC-8을 사용하지 않으므로 DST 기간은 UTC-7을 반영한다. 기존 `usage_month`는 UTC 이력 호환용으로만 남기며 예산 집계에는 사용하지 않는다. Gemini `ai_guard.py`와 사용량 테이블·lock은 별개다. 전체 문서를 한꺼번에 예약하지 않고 필요한 페이지마다 예약한다. 남은 예산이 일부뿐이면 그 부분까지 처리하고 나머지는 미완료로 남긴다. 재시도 가능 안내는 참고용이며 실제 호출 직전 원자적 예약이 최종 판단한다.

예약 커밋 **후에만** 외부 호출한다. SDK `retry=None`, 요청 timeout 25초이며 애플리케이션 자동 재호출도 없다. 인증 거부, 429, API 오류, 타임아웃, 예약 직후 프로세스 중단까지 모두 사용량을 돌려주지 않는다. 실제로 호출되지 않았을 수도 있는 예약을 보수적으로 사용량에 남긴다. 월이 바뀐 뒤 이전 월 예약으로 새 호출을 시작하지 않는다.

고유 키는 `(document_id, unit_key)`다. PDF는 페이지 번호+전처리 버전, DOCX는 이미지 해시+전처리 버전을 사용한다. 최초 예약의 extraction_revision도 남긴다. 원본은 같은 문서 ID에서 교체되지 않으므로 **revision이 달라져도** 완료 결과를 재사용하고, 미확정/실패 단위를 자동 재호출하지 않는다. 예약/실패 행을 지우거나 키 버전을 바꾸면 이 보호가 깨진다. 운영자가 임의 초기화하지 않는다. 별도 재업로드는 다른 문서이며 월 총량 제한은 그대로 적용된다.

문서 삭제 후 원본·추출 이력을 기존 cleanup으로 삭제하고 OCR `result_json`도 지운다. 사용량 행은 텍스트 없이 남긴다. 삭제 중 도착한 응답은 결과 텍스트를 복원하지 않는다.

**이 앱의 900단위 제한은 Google Cloud 프로젝트 전체의 무과금을 보장하지 않는다.** **같은 결제 계정 내 다른 프로젝트의 OCR 사용량은 현재 DB에서 추적할 수 없다.** 다른 서비스·클라이언트·별도 DB를 쓰는 앱 인스턴스의 호출, 재업로드, Google의 실제 청구 집계와 시점은 별개다. 무료량·가격은 바뀔 수 있으므로 활성화 시 공식 가격표를 다시 확인한다. 절대로 과금이 허용되지 않으면 provider를 `none`으로 유지한다. Cloud Billing 예산 알림은 지출의 자동 차단 기능이 아니다.

## 상태·재시도 API

기존 경로와 상태를 유지한다. 목록 응답에 `ocr: {enabled, available, reason, message}`와 문서별 `retry_available`, `retry_reason`, `retry_message`만 추가했다.

| 상황 | 결과 |
| --- | --- |
| 모든 필요한 텍스트 추출 완료 | `ready` |
| 읽힌 본문은 있으나 누락/실패/한도 존재 | `partial`; 기존 사용자 확인 후에만 분석 포함 |
| 본문 없음, OCR 꺼짐/인증 미설정/처리 한도 | `needs_ocr` + 구체적 error_code/limitations |
| API 오류·timeout 또는 처리했지만 글자 없음 | 본문 없으면 `failed`, 있으면 `partial` |
| 빈 TXT/PDF 등 읽을 글자가 없음 | `failed`, `empty_text` |

기존 `POST /api/roadmap-inputs/{rid}/documents/{did}/retry-extraction`으로 `needs_ocr`를 재업로드 없이 처리한다. `expected_input_revision` 검사를 유지한다. provider 비활성/인증 미설정은 422, 월 한도 소진은 429와 이유를 반환한다. 완료 여부가 불확실하거나 이미 실패한 OCR 단위는 중복 과금 방지를 위해 재호출하지 않으며 UI에 다시 읽기 제한을 알린다. 오류 원문·인증 정보는 응답이나 로그에 싣지 않는다. 재추출은 기존 규칙대로 extraction_revision을 올리고 부분 확인을 취소하여 이전 분석 근거를 무효화한다.

## 워커와 Render 자원

기존 120초 lease와 token/revision 완료 검사를 유지한다. Storage 읽기와 OCR 중에도 별도 heartbeat가 20초마다 갱신하며, 각 페이지·API 호출 전후 소유권을 확인한다. 삭제·revision 변경·token 교체·DB 연결 실패 시 새 호출을 멈춘다. 프로세스가 재시작되면 만료 작업을 다시 claim하고 저장된 페이지 결과를 사용한다. 진행 중이던 예약은 `ocr_uncertain`으로 남겨 외부 호출을 반복하지 않는다. 이미 전송된 요청을 삭제 요청이 취소할 수는 없지만 결과 게시·다음 페이지 호출은 막는다.

렌더링은 최대 2배 배율/긴 변 2,000px, PNG 최대 8MiB, DOCX 원본 이미지 최대 2천만 픽셀이다. 다중 프레임 이미지는 지원하지 않는다. 이미지는 디스크에 기록하지 않고 매번 한 장만 메모리에서 준비한다. PDFium은 프로세스 내 mutex로 직렬화한다. 운영 워커는 한 프로세스당 동시 문서 작업 1개를 권장한다. Render Free의 절전·재시작 때문에 즉시 완료나 상시 백그라운드 실행은 보장하지 않는다. 후속 문서 요청이 기존 작업을 재개한다.

의존성: `google-cloud-vision==3.16.0`, `pypdfium2==5.15.2`, `Pillow==12.0.0`. Poppler/Ghostscript/GCS는 필요 없다. Python 3.14.7에서 설치·테스트했으며 [Vision 지원 버전](https://cloud.google.com/python/docs/reference/vision/latest)과 [pypdfium2 배포 wheel](https://pypi.org/project/pypdfium2/5.15.2/)을 확인했다. [PDFium 스레드 제한](https://pypdfium2.readthedocs.io/en/stable/python_api.html#incompatibility-with-threading)에 따라 직렬화했다. Render의 실제 Linux 빌드·메모리 사용량은 배포 전 staging에서 확인해야 한다.

## Google Cloud 준비와 로컬 연결

1. 전용 Google Cloud 프로젝트, 연결된 결제 계정, 현재 Vision 실제 사용량을 확인한다. 다른 앱과 예산을 공유한다면 그 사용량을 고려해 앱 한도를 더 낮춘다.
2. Cloud Vision API (`vision.googleapis.com`)를 활성화한다. GCS 버킷은 만들지 않는다.
3. 전용 서비스 계정을 만들고 quota/billing 프로젝트에서 필요한 최소 권한을 설정한다. inline 이미지 요청은 Storage 권한이나 Editor/Owner가 필요하지 않다. 사용자 ADC의 quota project 사용에는 `serviceusage.services.use` 권한(예: `roles/serviceusage.serviceUsageConsumer`)이 필요하다. 설정에 필요한 관리자 권한과 런타임 권한은 구분한다. [공식 인증 안내](https://cloud.google.com/vision/docs/authentication)를 따른다.
4. 로컬에서는 아래 ADC를 생성하거나 서비스 계정 파일 경로를 백엔드에 설정한다. 파일은 저장소 밖에 두고 접근 권한을 제한한다. 앱은 파일 기반 service_account/authorized_user ADC만 읽는다. 자격 증명이 없을 때 metadata 서버를 탐색하지 않는다. GCE metadata ADC·Workload Identity Federation은 이번 범위에 포함하지 않았다.

```sh
# 사용자가 별도로 실행: 실제 Google 인증과 quota project 설정
# PROJECT_ID는 본인이 확인한 전용 프로젝트로 교체
gcloud auth application-default login
gcloud auth application-default set-quota-project PROJECT_ID
```

아래는 **실제 호출이 가능한 수동 검증 명령**이다. 이번 작업에서는 실행하지 않았다. 일회용 DB를 반복 생성하면 예산이 분리되므로 실사용 앱과 같은 프로젝트 무료량을 별도로 확인해야 한다. 테스트 실행마다 DB를 지우지 않는다.

```sh
cd apps/api
.venv/bin/pip install -r requirements.txt
ROADMAP_DB_BACKEND=sqlite \
ROADMAP_DB_PATH="$PWD/var/ocr-manual.sqlite3" \
ROADMAP_FILE_STORAGE_PATH="$PWD/var/ocr-manual-files" \
ROADMAP_AUTO_SEED_DEV=0 \
ROADMAP_INSECURE_LOCAL_COOKIE=1 \
ROADMAP_OCR_PROVIDER=google_vision \
ROADMAP_OCR_MONTHLY_UNIT_LIMIT=1 \
ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT=1 \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

다른 터미널에서 `cd apps/web && npm run dev`. 기존 문서 화면에서 개인 정보 없는 한 페이지 스캔 PDF를 업로드하고 읽기 완료·문자/페이지·분석 확인을 검증한다. 기존 `needs_ocr` 문서는 ‘다시 읽기’를 사용한다. 서비스 계정 파일이면 명령에 `GOOGLE_APPLICATION_CREDENTIALS=/저장소밖/서비스계정.json`을 추가한다. 기존 `.env`에 이 변수가 남아 있으면 ADC보다 우선하므로 확인한다. 원본이나 인식 텍스트를 로그로 출력하지 않는다.

## Render 설정

1. 아래 SQL을 백업·격리 검증·별도 승인 후 적용한다. 기존 Supabase Storage와 문서 기능 환경은 유지한다.
2. Render Environment → Secret Files에 서비스 계정 JSON을 `google-vision-service-account.json`으로 등록한다. 파일 경로는 `/etc/secrets/google-vision-service-account.json`이다. [Render Secret Files 안내](https://render.com/docs/configure-environment-variables)를 참고한다.
3. 백엔드에 `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/google-vision-service-account.json`, `ROADMAP_OCR_MONTHLY_UNIT_LIMIT=900`(처음에는 1 권장), `ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT=50`을 설정한다. 처음에는 `ROADMAP_OCR_PROVIDER=none`으로 배포·시작을 확인한 뒤 별도 승인으로 `google_vision`을 활성화한다.
4. 기존 Python `3.14.7`, Build `pip install -r requirements.txt`, Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`를 유지한다. 공개 `NEXT_PUBLIC_*` 변수에 Google 인증을 넣지 않는다.
5. Cloud Billing에 소액 예산과 알림 수신자를 설정하고 Vision API usage/quotas 및 실제 결제 보고서를 확인한다. 앱 ledger 수치만으로 실제 청구량을 대신 판단하지 않는다.
6. 업로드 안내/개인정보 처리방침에 스캔 페이지·DOCX 이미지가 Google Cloud Vision으로 전송됨을 알린다. 이미지에는 해당 페이지의 텍스트 외 정보도 포함될 수 있다. 운영자의 적법한 처리 근거·보존 정책·Google 데이터 처리 조건 확인이 필요하다. UI에도 활성화 시 전송 안내가 표시된다.

## 마이그레이션과 운영 적용 전 주의

- SQLite: `009_document_ocr_units.sql` 이후 `010_document_ocr_billing_period.sql`을 시작 시 적용한다. 010은 한 트랜잭션에서 테이블을 재구성하여 원래 행·키·상태·캐시·시각을 모두 보존하고 NOT NULL/CHECK와 인덱스를 추가한다. `repositories.plans.connect()`가 등록한 IANA 변환 함수가 필요하므로 일반 sqlite CLI에서 SQL만 실행하지 않는다.
- PostgreSQL: `20261110091129_document_ocr_units.sql` 이후 **`20261111021219_document_ocr_billing_period.sql`**을 적용한다. UTC `created_at`에서 LA 월을 역산하여 `billing_period`를 채우고 NOT NULL/CHECK와 인덱스를 추가한다. 원래 `usage_month`, PK/FK, RLS, 접근 권한, 캐시·상태는 유지한다. 둘 다 Supabase CLI로 생성한 마이그레이션이다. 기존 문서 테이블 뒤에 적용한다. 기존 migration 이력 불일치는 [문서 이관 안내](phase3-document-migration.md)를 먼저 확인한다.
- 테이블은 RLS 활성화, PUBLIC/anon/authenticated 접근 차단, 서버 DB 연결만 사용한다. 원문 인식 결과가 들어가므로 공개 정책을 추가하지 않는다.
- 운영 적용 전 백업/복원 가능성, 스키마·기존 이력·역할, DB를 공유하는 모든 인스턴스의 설정을 확인한다. **이 작업은 운영 SQL을 적용하지 않았다.** 앱 provider를 `none`으로 유지하고 구버전 워커를 모두 중단한 상태에서, 코드 배포 전에 두 SQL을 검토·승인하여 순서대로 적용한다. 010/새 PostgreSQL 마이그레이션 후 구버전 INSERT는 필수 billing_period가 없어 실패하므로 신·구 워커를 혼합 실행하지 않는다. 이관 후 기간당 예약이 이미 900개 이상이면 모두 보존하고 새 호출만 차단한다. 롤백은 provider를 끄고 ledger를 보존한다. ledger DROP/초기화는 월 예산과 중복 방지를 잃게 한다.

## 자동 테스트

실제 Google API를 호출하지 않는다. 테스트는 합성 PDF/DOCX/이미지와 Mock provider를 사용하고 기본 provider를 끄며 실제 Google client 생성도 차단한다.

```sh
cd apps/api
PYTHONPATH=app ROADMAP_DB_BACKEND=sqlite ROADMAP_AUTO_SEED_DEV=0 \
  .venv/bin/python -m pytest -q
# 선택: 명시적으로 만든 localhost 테스트 DB에서만 실행
PYTHONPATH=app ROADMAP_DB_BACKEND=sqlite ROADMAP_OCR_TEST_BACKEND=postgres \
ROADMAP_TEST_POSTGRES_URL=postgresql://USER:PASSWORD@127.0.0.1:PORT/team18_document_test \
ROADMAP_ALLOW_TEST_DB_RESET=1 \
  .venv/bin/python -m pytest tests/unit/test_document_ocr.py tests/unit/test_ocr_budget_boundaries.py tests/unit/test_ocr_billing_period.py tests/integration/test_documents_postgres.py -q
```

PostgreSQL 테스트는 TLS를 지원하는 로컬 일회용 PostgreSQL이 필요하다. 기존 통합 테스트는 이 **정확한 이름의 로컬 DB** public 스키마를 초기화한다. Supabase/운영 DSN을 절대 사용하지 않는다. OCR 단위 테스트는 같은 DB 안에 랜덤 별도 스키마를 만들고 정리한다. 독립 연결의 동시 예약과 독립 Python 프로세스의 월 한도 공유를 검증한다.

## 남은 한계

- 실제 Google 인증·인식 품질·청구 및 실제 Render/Supabase 배포는 검증하지 않았다. Mock은 한글/영어/기술명/숫자 전달의 보존을 검증하며 OCR 인식률을 증명하지 않는다.
- 정상 텍스트 레이어가 있는 PDF 페이지 안의 이미지 글자와 벡터 윤곽선으로만 그린 글자는 OCR 대상에서 제외한다. 잘못된 기존 텍스트 레이어, 같은 페이지 내 텍스트+스캔 영역, 복잡한 다단 배치는 완전성을 보장하지 않는다.
- DOCX 머리글/바닥글/각주/차트/SmartArt/OLE/일부 텍스트 상자, 외부 링크 이미지, 지원하지 않는 벡터·다중 프레임 이미지는 limitations에 기록한다. DOCX의 이미지 내 글자와 인접 본문 간 시각적 순서는 복원하지 않는다.
- 2,000px 축소로 작은 글자 인식률이 떨어질 수 있다. PDF 파서/렌더러의 모든 악성 입력에 대한 별도 OS 프로세스 격리나 CPU 시간 강제 종료는 구현하지 않았다. 기존 10MB·100페이지와 추가 이미지 제한을 적용한다.
- 외부 호출은 정확히 한 번 완료를 보장할 수 없다. 완료가 불확실하면 비용 보호를 위해 해당 영역이 미완료로 남는다. 오류가 난 동일 단위를 강제로 다시 호출하는 관리 UI/API는 제공하지 않는다.

## 최초 OCR 통합 변경 파일 목록

| 파일 | 변경 |
| --- | --- |
| [README.md](../README.md) | OCR 지원과 환경변수·설명 링크 |
| [config.py](../apps/api/app/config.py) | 기본 비활성화·900/50 하드 상한 |
| [.env.example](../apps/api/.env.example) | OCR 및 서버 인증 설정 예시 |
| [requirements.txt](../apps/api/requirements.txt) | 공식 SDK·PDFium·Pillow 고정 버전 |
| [document_parser.py](../apps/api/app/providers/document_parser.py) | 필요한 영역만 OCR, 병합·위치·부분 실패 |
| [document_images.py](../apps/api/app/providers/document_images.py) | 제한된 렌더링·투명 이미지 전처리 |
| [google_vision_ocr.py](../apps/api/app/providers/google_vision_ocr.py) | 인증·공식 SDK·오류 분류·재시도 차단 |
| [services/document_ocr.py](../apps/api/app/services/document_ocr.py) | 원자적 월 예산·결과 재사용·재시도 정책 |
| [worker/documents.py](../apps/api/app/worker/documents.py) | OCR 연결·lease heartbeat·소유권 확인 |
| [repositories/documents.py](../apps/api/app/repositories/documents.py) | 조건부 lease 갱신·OCR 결과 cleanup |
| [routes/documents.py](../apps/api/app/api/routes/documents.py) | 기존 retry API 활성화·상태 안내 |
| [Documents.js](../apps/web/src/features/intake/Documents.js) | 기존 화면의 문구·재시도 사유·외부 전송 안내 |
| [009_document_ocr_units.sql](../apps/api/migrations/009_document_ocr_units.sql) | SQLite 사용량 ledger |
| [20261110091129_document_ocr_units.sql](../supabase/migrations/20261110091129_document_ocr_units.sql) | PostgreSQL ledger·인덱스·RLS·접근 제한 |
| [conftest.py](../apps/api/tests/conftest.py) | 테스트의 실제 OCR client 생성 차단 |
| [test_document_ocr.py](../apps/api/tests/unit/test_document_ocr.py) | 합성 문서·SDK 오류·예산·경쟁·중단·분석 입력 테스트 |
| [document_ocr_scenario.py](../apps/api/tests/integration/document_ocr_scenario.py) | 실제 API 업로드→재시도→분석→삭제 Mock 시나리오 |
| [test_document_ocr_api.py](../apps/api/tests/integration/test_document_ocr_api.py) | 별도 SQLite 프로세스에서 API 시나리오 실행 |
| [render-deployment.md](render-deployment.md) | OCR 운영 적용 안내 연결 |
| [phase3-document-migration.md](phase3-document-migration.md) | 추가 SQL·ledger 보존 주의 |
| [google-vision-ocr.md](google-vision-ocr.md) | 이 구현·설정·비용·검증 보고서 |

`document_storage.py`, `ai_guard.py`, 프로젝트 경험 분석의 기존 구현은 그대로 사용한다. Gemini 예산·원본 Storage 구조·분석 확인 규칙은 변경하지 않았다.

## 검증 결과 — 2026-11-10

- 전체 백엔드 SQLite 격리 회귀: **299 passed, 3 skipped, 30 subtests passed**. 선택 환경 테스트는 기본 실행에서 skip. 기존 Starlette/httpx 및 google-genai의 deprecation warning 2건이 있으며 실패는 없다.
- 임시 localhost TLS PostgreSQL 16: OCR 단위·경쟁·lease·기존 문서 API **37 passed**, 최종 한도 변경 후 재시도 검사 **1 passed** 추가(총 38건). 8개 독립 Python 프로세스에 예산 3단위를 주어 정확히 3건만 호출됨을 확인했다. 실제 SQL을 적용했고 RLS `true`, anon/authenticated SELECT 권한 `false/false`를 조회했다. 운영 Supabase에는 접속하지 않았다.
- 프론트엔드 기존 테스트: `node --experimental-vm-modules --test tests/unit/*.test.mjs` **15 passed**. `ROADMAP_API_ORIGIN=https://api.example.com npm run build` 성공. 새 화면이나 탭은 추가하지 않았다.
- Python 3.14.7 설치 및 `pip check` 성공. Linux x86_64/Python 3.14용 Vision, PDFium, Pillow, grpcio wheel 다운로드 확인. `git diff --check` 통과.
- 최초 로컬 API 회귀 실행은 샌드박스의 localhost 바인딩 제한으로 실행되지 않았고, 포트 사용을 허용한 격리 실행에서 통과했다. 최초 프론트엔드 테스트의 VM module 옵션 누락은 위 명령으로 수정하여 통과했다.
- 실제 Vision 호출, 실제 Google 인증·인식 품질·청구 검증, 운영 DB 마이그레이션, Render 환경 변경, 운영 배포는 수행하지 않았다. 실제 연결은 위 수동 검증 명령으로 별도 실행해야 한다.


## 이전 검증 기록: UTC 월 900단위 보호 보강 — 2026-11-11

이 절은 태평양 시간 수정 이전의 기록이다. 현재 기간 기준과 새 SQL은 아래 「태평양 시간 billing_period 수정」 절을 따른다.

기존 OCR 구현이 반영된 `main`의 `b2e0955`를 기준으로 코드와 Mock 테스트를 보강했다. 기본 provider는 계속 `none`이며 Google Cloud 결제 계정·인증 설정·실제 API·운영 DB·운영 배포는 변경하지 않았다. 추가 SQL 마이그레이션은 없다.

### 이번 변경 파일

| 파일 | 변경 내용 |
| --- | --- |
| [services/document_ocr.py](../apps/api/app/services/document_ocr.py) | PostgreSQL 예약 격리 수준 명시, DB 기준 UTC 월, 동일 월로 확인·예약, DB 월 재확인 후 호출 |
| [test_document_ocr.py](../apps/api/tests/unit/test_document_ocr.py) | 기존 월 전환 테스트가 예산 시계를 직접 주입하도록 변경 |
| [test_ocr_budget_boundaries.py](../apps/api/tests/unit/test_ocr_budget_boundaries.py) | 899/900 정확한 경계, 동시 10개, 새 프로세스 재시작, timeout·커밋 응답 유실, 월 전환 및 비활성화 검증 |
| [google-vision-ocr.md](google-vision-ocr.md) | 이번 변경·테스트·배포 조건·남은 위험 보고 |

### 보강 이유와 관리 방식

모든 사용자/문서의 `document_ocr_units`를 UTC 월로 집계한다. 완료·실패·미확정 상태를 모두 1단위로 세고 삭제해 환급하지 않는다. 설정값이 900보다 커도 코드에서 900으로 제한한다. DB 예약 커밋 성공을 확인한 요청만 Mock/실제 provider 호출 단계로 진행한다. 완료 결과는 DB에서 재사용하고 timeout·중복 작업·결과 불확실은 같은 단위를 재호출하지 않는다.

예약 트랜잭션에 `BEGIN ISOLATION LEVEL READ COMMITTED`를 명시했다. 세션 기본값이 `REPEATABLE READ`인 경우에는 잠금 대기 전에 만든 스냅샷으로 이전 사용량을 읽을 수 있다. 전역 advisory lock을 획득한 뒤 최신 커밋을 읽도록 격리 수준을 고정했다. 이 변경은 [PostgreSQL 격리 수준 문서](https://www.postgresql.org/docs/current/transaction-iso.html)의 스냅샷 동작을 따른다.

월 판단은 모든 PostgreSQL 프로세스가 같은 DB 시계를 사용한다. 트랜잭션 시작 시각에 고정되는 `now()` 대신 [실제 현재 시각을 반환하는 clock_timestamp()](https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT)를 사용한다. SQLite는 기존 Python UTC 시계를 유지한다. 월이 바뀌면 새 월의 기록만 집계하여 예산을 열고, 과거 기록과 중복 호출 방지 키는 보존한다.

테스트의 실제 Google client 생성은 차단했다. 별도 Python 프로세스에서 실행하는 재시작 테스트도 SDK client를 차단하고 Mock Provider만 주입한다. 독립 DB 연결뿐 아니라 별도 인터프리터의 캐시·사용량 유지도 검증한다.

### 현재 설정과 향후 Render 배포

현재 권장 설정은 아래와 같다. 결제 계정 연결 전에는 그대로 유지한다.

```dotenv
ROADMAP_OCR_PROVIDER=none
ROADMAP_OCR_MONTHLY_UNIT_LIMIT=900
ROADMAP_OCR_MAX_PAGES_PER_DOCUMENT=50
GOOGLE_APPLICATION_CREDENTIALS=
```

나중에 실제 연결을 별도로 승인한 경우에만 위의 Google 준비 절차를 수행한다. Render Secret File에 서비스 계정 JSON을 저장하고 `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/google-vision-service-account.json`을 설정한다. 같은 Google 프로젝트의 다른 사용량과 실제 무료량을 확인한 뒤 `ROADMAP_OCR_PROVIDER=google_vision`으로 전환한다. 환경변수를 프론트엔드에 노출하지 않는다.

배포 순서: 기존 `20261110091129_document_ocr_units.sql`의 적용 여부·백업을 검토 → 미적용이면 별도 승인 후 적용 → provider `none` 상태로 코드와 의존성 배포 → 구버전 워커가 모두 종료되었는지 확인 → staging에서 Mock 검증 → 실제 활성화는 별도 결정. 이번 보강 자체에는 새로운 SQL이 없으며 이 작업은 운영 마이그레이션이나 배포를 실행하지 않았다. 기존 Build/Start 명령과 Supabase Storage 설정은 유지한다.

### 남은 과금 위험

이 보호는 같은 DB의 ledger와 이 코드 경로를 사용하는 호출에 적용된다. 다른 클라이언트·별도 DB·과거 버전 워커·직접 SDK 호출, ledger 삭제나 과거 백업 복원은 보호 범위 밖이다. DB 시각이 잘못되거나 Google의 실제 청구 집계 시점이 요청 시각과 다르면 앱의 UTC 월 집계와 실제 청구 월이 다를 수 있다. SDK 버전 변경 시에도 재시도 정책을 다시 검증해야 한다. Cloud Billing 알림은 자동 지출 차단 장치가 아니다. **어떠한 비용도 허용할 수 없다면 provider를 `none`으로 유지해야 한다.**

### 이번 검증 결과

| 필수/보강 시나리오 | SQLite / 격리 PostgreSQL 결과 |
| --- | --- |
| 사용량 899 + 요청 1개 | 호출 1회 허용, 총 900단위 |
| 사용량 900 + 요청 1개 | 호출 0회, `ocr_budget_exceeded`, 총 900단위 유지 |
| 사용량 899 + 동시 10개 | 정확히 1회 허용·9회 차단, 총 900단위 |
| 환경변수에 900 초과 설정 | 899/900 경계는 그대로 유지 |
| timeout 이후 동일 단위 3회 시도 | 첫 호출 1회만 실행·계상, 반복 시도는 재호출 없음 |
| 한도 도달 후 다른 문서 요청 | 외부 호출 없이 차단 |
| 독립 Python 프로세스로 재시작 | 첫 호출 1회, 재시작 후 캐시 재사용 0회, 새 문서는 한도 차단 |
| UTC 월 변경 | 이전 월 900행 보존, 새 월 예산 900부터 시작, 기존 캐시 재사용은 0단위 |
| 예약과 dispatch 사이 월 변경 | 이전 월 예약 보존, 외부 호출 0회 |
| 예약 커밋 응답 유실 | 외부 호출 0회, 저장된 예약 유지, 후속 중복 호출 차단 |
| provider 기본 비활성화 | TXT·텍스트 PDF·로고 포함 PDF·일반 DOCX 정상 파싱, 스캔은 needs_ocr, 예약 0개 |
| PostgreSQL 기본 격리 수준 REPEATABLE READ | 동시 10개 모두 잠금 전 읽기를 수행해도 1회만 허용 |
| PostgreSQL과 앱 시각이 다른 월 | DB의 UTC 월로만 사용량 계상 |

- **전체 SQLite 백엔드 회귀: 310 passed, 5 skipped, 30 subtests passed.** 선택 환경 테스트는 기본 실행에서 skip했고, PostgreSQL 대상 검증은 아래 별도 실행했다. 기존 deprecation warning 2건 외 실패는 없다.
- **격리 PostgreSQL 16: 51 passed.** `test_document_ocr.py`, `test_ocr_budget_boundaries.py`, 기존 `test_documents_postgres.py`를 실행했다. 이번 작업 전용 localhost TLS 컨테이너와 합성 데이터만 사용했다.
- 실제 Google client 생성은 금지했고, 모든 OCR 결과와 오류는 Mock이다. Google Cloud 결제 계정 연결·실제 API 호출·운영 DB 적용·Render 환경변수 변경·운영 배포는 하지 않았다.
- 이번 변경에는 프론트엔드 수정이 없으며, 이전 빌드 결과와 구분하여 이번에는 백엔드 회귀를 실행했다. `git diff --check`도 통과했다.


## 태평양 시간 billing_period 수정 — 2026-11-11

[Google Cloud 월별 가격 구간 문서](https://cloud.google.com/billing/docs/how-to/pricing-table)는 월별 SKU 구간이 태평양 시간 기준 매월 1일 자정에 초기화된다고 설명한다. 요청한 `America/Los_Angeles` IANA 타임존을 사용해 DST를 반영했다. Python `zoneinfo`와 PostgreSQL `AT TIME ZONE 'America/Los_Angeles'`를 사용하며, OS/PostgreSQL의 시간대 데이터가 필요하다. 시간대 해석이 실패하면 예산 예약을 진행하지 않는다.

- `created_at`: UTC 사용/예약 시각. 변경하지 않으며 새 예약도 UTC로 저장한다.
- `billing_period`: 해당 시각을 LA 시간으로 변환한 달력 월(`YYYY-MM`). 모든 사용자 합산 900단위 집계·예약·호출 직전 검사에 사용한다.
- `usage_month`: 이전 버전의 UTC 월을 그대로 보존하는 이력 필드. 예산에 사용하지 않는다.
- PostgreSQL `READ COMMITTED` + 전역 advisory lock, SQLite `BEGIN IMMEDIATE`, `(document_id, unit_key)` 중복 방지, 완료 결과 재사용과 실패·timeout 예약 보존은 유지한다.
- 예약 커밋 후 LA 월이 바뀌면 호출하지 않고 기존 예약을 미확정으로 보존한다. 월이 바뀌어도 과거 사용량과 캐시는 삭제하지 않는다.

| UTC 시각 | LA 기준 | 예산 기간 |
| --- | --- | --- |
| 2026-01-01 00:00 | 2025-12-31 16:00 PST | 2025-12 유지 |
| 2026-01-01 08:00 | 2026-01-01 00:00 PST | 2026-01 시작 |
| 2026-07-01 00:00 | 2026-06-30 17:00 PDT | 2026-06 유지 |
| 2026-07-01 07:00 | 2026-07-01 00:00 PDT | 2026-07 시작 |

추가 파일은 `services/ocr_billing.py`, SQLite `010_document_ocr_billing_period.sql`, PostgreSQL `20261111021219_document_ocr_billing_period.sql`, `test_ocr_billing_period.py`다. 기존 `document_ocr.py`, `repositories/plans.py`, 두 OCR 테스트 파일, provider·Documents.js 안내 문구, `.env.example`, README 및 배포 문서를 갱신했다. 새 설정 변수는 없으며 기본 provider는 `none`, 상한은 계속 900단위다.

**같은 결제 계정 내 다른 프로젝트의 OCR 사용량은 이 DB가 추적하지 못한다.** Google Cloud의 가격 구간은 결제 계정 단위로 적용될 수 있어, 이 앱의 900단위 제한이 결제 계정 전체의 무료 사용량을 보장하지 않는다. 별도 클라이언트, 직접 호출, 과거 DB 복원/ledger 초기화, 시간대 데이터 버전 차이 및 실제 청구 기록 지연도 별도 확인이 필요하다. 실제 비용을 전혀 허용하지 않는 현재 조건에서는 provider를 비활성화 상태로 유지한다.

운영 마이그레이션·배포는 실행하지 않았다. 적용 시 백업 후 OCR을 끄고 모든 구버전 워커를 종료한 다음, 새 SQL을 한 트랜잭션으로 적용하여 행 개수·고유 키·UTC 시각·상태·캐시가 보존됐는지 확인해야 한다. 새 기간은 반드시 원본 created_at에서 재계산하며 과거 UTC 월 문자열을 그대로 복사하면 안 된다. 이관 실패 시 롤백하고 기록을 삭제해 복구하지 않는다.


### 태평양 시간 수정 검증 결과

- **SQLite 전체 백엔드: 329 passed, 5 skipped, 30 subtests passed.** 선택 환경 테스트는 기본 실행에서 건너뛰고 PostgreSQL 대상으로 별도 검증했다. 기존 deprecation warning 2건 외 실패는 없다.
- **격리 PostgreSQL 16: 70 passed.** 기존 OCR·900단위 경계·다중 프로세스·문서 API에 새 기간·이관 테스트를 포함했다.
- **새 기간/이관 테스트: 19개 통과**(SQLite와 PostgreSQL 각각). UTC 자정에 이전 LA 월 유지, PST 08:00 UTC/PDT 07:00 UTC의 새 월, DST 시작·종료 및 다른 입력 타임존, 월 경계 동시 10개 중 정확히 1개 허용, 기존 시각·PK·상태·캐시·RLS 보존, 잘못된 기간/구버전 INSERT 차단, UTC 월초의 기존 900행을 이전 LA 월로 재집계하는 경우를 확인했다.
- **프론트엔드: 15개 테스트 통과, Next.js 프로덕션 빌드 성공.** 기존 UI 구조를 유지하고 제한 안내의 시간 기준만 수정했다.
- `git diff --check`와 문서의 로컬 링크 검사 통과. 임시 테스트 DB에만 SQL을 적용했다. 실제 Google API 호출·결제 연결·운영 DB 마이그레이션·운영 배포는 수행하지 않았다.
