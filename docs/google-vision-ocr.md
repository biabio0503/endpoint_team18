# Google Cloud Vision 문서 OCR

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

`document_ocr_units`의 한 행이 잠재적인 유료 호출 1단위다. SQLite `BEGIN IMMEDIATE`, PostgreSQL transaction advisory lock `18180734`와 고유 키로 모든 사용자·프로세스가 UTC 월별 예산을 공유한다. Gemini `ai_guard.py`와 사용량 테이블·lock은 별개다. 전체 문서를 한꺼번에 예약하지 않고 필요한 페이지마다 예약한다. 남은 예산이 일부뿐이면 그 부분까지 처리하고 나머지는 미완료로 남긴다. 재시도 가능 안내는 참고용이며 실제 호출 직전 원자적 예약이 최종 판단한다.

예약 커밋 **후에만** 외부 호출한다. SDK `retry=None`, 요청 timeout 25초이며 애플리케이션 자동 재호출도 없다. 인증 거부, 429, API 오류, 타임아웃, 예약 직후 프로세스 중단까지 모두 사용량을 돌려주지 않는다. 실제로 호출되지 않았을 수도 있는 예약을 보수적으로 사용량에 남긴다. 월이 바뀐 뒤 이전 월 예약으로 새 호출을 시작하지 않는다.

고유 키는 `(document_id, unit_key)`다. PDF는 페이지 번호+전처리 버전, DOCX는 이미지 해시+전처리 버전을 사용한다. 최초 예약의 extraction_revision도 남긴다. 원본은 같은 문서 ID에서 교체되지 않으므로 **revision이 달라져도** 완료 결과를 재사용하고, 미확정/실패 단위를 자동 재호출하지 않는다. 예약/실패 행을 지우거나 키 버전을 바꾸면 이 보호가 깨진다. 운영자가 임의 초기화하지 않는다. 별도 재업로드는 다른 문서이며 월 총량 제한은 그대로 적용된다.

문서 삭제 후 원본·추출 이력을 기존 cleanup으로 삭제하고 OCR `result_json`도 지운다. 사용량 행은 텍스트 없이 남긴다. 삭제 중 도착한 응답은 결과 텍스트를 복원하지 않는다.

**이 앱의 900단위 제한은 Google Cloud 프로젝트 전체의 무과금을 보장하지 않는다.** 다른 서비스·클라이언트·별도 DB를 쓰는 앱 인스턴스의 호출, 재업로드, Google의 실제 청구 집계와 시점은 별개다. 무료량·가격은 바뀔 수 있으므로 활성화 시 공식 가격표를 다시 확인한다. 절대로 과금이 허용되지 않으면 provider를 `none`으로 유지한다. Cloud Billing 예산 알림은 지출의 자동 차단 기능이 아니다.

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

- SQLite: `apps/api/migrations/009_document_ocr_units.sql`. 기존처럼 시작 시 순서대로 적용하며 기존 행을 삭제하지 않는다.
- PostgreSQL: `supabase/migrations/20261110091129_document_ocr_units.sql`. Supabase CLI로 생성한 추가 마이그레이션이다. 기존 문서 테이블 뒤에 적용한다. 기존 migration 이력 불일치는 [문서 이관 안내](phase3-document-migration.md)를 먼저 확인한다.
- 테이블은 RLS 활성화, PUBLIC/anon/authenticated 접근 차단, 서버 DB 연결만 사용한다. 원문 인식 결과가 들어가므로 공개 정책을 추가하지 않는다.
- 운영 적용 전 백업/복원 가능성, 스키마·기존 이력·역할, DB를 공유하는 모든 인스턴스의 설정을 확인한다. **이 작업은 운영 SQL을 적용하지 않았다.** 앱 코드 배포 전에 해당 SQL을 검토·승인하여 적용한다. 롤백은 provider를 끄고 ledger를 보존한다. ledger DROP/초기화는 월 예산과 중복 방지를 잃게 한다.

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
  .venv/bin/python -m pytest tests/unit/test_document_ocr.py tests/integration/test_documents_postgres.py -q
```

PostgreSQL 테스트는 TLS를 지원하는 로컬 일회용 PostgreSQL이 필요하다. 기존 통합 테스트는 이 **정확한 이름의 로컬 DB** public 스키마를 초기화한다. Supabase/운영 DSN을 절대 사용하지 않는다. OCR 단위 테스트는 같은 DB 안에 랜덤 별도 스키마를 만들고 정리한다. 독립 연결의 동시 예약과 독립 Python 프로세스의 월 한도 공유를 검증한다.

## 남은 한계

- 실제 Google 인증·인식 품질·청구 및 실제 Render/Supabase 배포는 검증하지 않았다. Mock은 한글/영어/기술명/숫자 전달의 보존을 검증하며 OCR 인식률을 증명하지 않는다.
- 정상 텍스트 레이어가 있는 PDF 페이지 안의 이미지 글자와 벡터 윤곽선으로만 그린 글자는 OCR 대상에서 제외한다. 잘못된 기존 텍스트 레이어, 같은 페이지 내 텍스트+스캔 영역, 복잡한 다단 배치는 완전성을 보장하지 않는다.
- DOCX 머리글/바닥글/각주/차트/SmartArt/OLE/일부 텍스트 상자, 외부 링크 이미지, 지원하지 않는 벡터·다중 프레임 이미지는 limitations에 기록한다. DOCX의 이미지 내 글자와 인접 본문 간 시각적 순서는 복원하지 않는다.
- 2,000px 축소로 작은 글자 인식률이 떨어질 수 있다. PDF 파서/렌더러의 모든 악성 입력에 대한 별도 OS 프로세스 격리나 CPU 시간 강제 종료는 구현하지 않았다. 기존 10MB·100페이지와 추가 이미지 제한을 적용한다.
- 외부 호출은 정확히 한 번 완료를 보장할 수 없다. 완료가 불확실하면 비용 보호를 위해 해당 영역이 미완료로 남는다. 오류가 난 동일 단위를 강제로 다시 호출하는 관리 UI/API는 제공하지 않는다.

## 변경 파일 목록

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
