# 독립 AI 실험

`gemini/`는 Gemini 호출, `local/`은 로컬 GPU 모델 추론·학습과 OCR, `intake.py`는 문서 추출, `workflow.py`는 입력·검토·결과 이력을 담당합니다. 웹과는 연결하지 않았습니다. Gemini 선택 시 입력 문서는 Google에 전송됩니다. 키와 개인정보는 Git에 올리지 마세요. 기본 OCR에 필요한 두 모델 가중치만 Git에서 추적할 수 있습니다.

## 준비

Node.js 20.9 이상과 Python이 필요합니다. 문서 처리 의존성은 `python -m pip install -r apps/api/requirements.txt`로 설치합니다. Gemini 키는 `ai/.env`에 넣습니다. 테스트 저장소는 Git 폴더 밖에 만드세요.

## 파일 입력과 결과 확인

입력 JSON은 `sample-input.json`의 학생 필드를 사용하되 `documents` 대신 `document_paths` 배열에 TXT/PDF/DOCX 경로를 넣습니다. 상대 경로는 입력 JSON 위치 기준입니다. OCR을 사용할 때 PNG/JPEG, 스캔 PDF 및 DOCX 내 PNG/JPEG 이미지도 지원합니다.

```powershell
python ai/workflow.py create C:/roadmap-test/input.json --storage C:/roadmap-test/store
# OCR 인식 모델 선택: local은 직접 추가 학습한 모델(기본값), open-source는 원본 Qota-OCR입니다.
ai/.venv/Scripts/python.exe ai/workflow.py create C:/roadmap-test/input.json --storage C:/roadmap-test/store --ocr --ocr-model local
# 원본 오픈소스 모델로 바꾸려면 위 명령의 --ocr-model local을 --ocr-model open-source로 변경합니다.
# 출력된 요청 ID를 사용합니다. 부분 추출일 때 읽힌 내용을 확인한 뒤 문서 ID를 지정하세요.
python ai/intake.py export 요청ID --storage C:/roadmap-test/store --confirm 문서ID
# 공급자 선택: --provider gemini 또는 --provider local
python ai/workflow.py analyze 요청ID --storage C:/roadmap-test/store --provider gemini
python ai/workflow.py status 요청ID --storage C:/roadmap-test/store
```

추출 실패·OCR 필요 문서가 있으면 분석을 중단합니다. 결과를 보고 다음 형태의 UTF-8 JSON 파일에 확인·수정한 경험과 질문 답변을 작성하세요.

```json
{"confirmed_experiences":[{"project":"프로젝트명","description":"확인한 역할"}],"answers":[{"question":"추가 질문","answer":"답변"}]}
```

```powershell
python ai/workflow.py review 요청ID C:/roadmap-test/review.json --storage C:/roadmap-test/store
python ai/workflow.py analyze 요청ID --storage C:/roadmap-test/store --provider gemini
python ai/workflow.py status 요청ID --storage C:/roadmap-test/store
```

확인 내용을 저장하면 이전 결과는 오래된 결과가 됩니다. 재분석하면 확인 내용이 입력에 포함됩니다. 입력이나 확인 내용이 분석 중 바뀌면 결과를 저장하지 않습니다. 이 저장소는 인증·다중 사용자 권한이 없는 개인용 실험입니다.

## 로컬 AI 및 학습

Qwen3-0.6B를 RTX 5070에서 자체 제작 가상 72건으로 LoRA 추가 학습했습니다. 6개 직무의 기간·과목 상태만 조합한 데이터라 독립 사례가 72개인 것은 아닙니다. 모델은 실험용이며 실제 추천에 사용할 수 없습니다. 모델과 가상환경은 Git에서 제외됩니다.

### 로컬 모델별 학습 기록

| 모델 | 학습에 사용한 데이터 | 학습한 작업 | 현재 용도 |
| --- | --- | --- | --- |
| 로컬 로드맵 생성 | 직접 만든 가상 학생·프로젝트 사례 72건 | 목표·과목·문서 입력에 대한 경험, 질문, 주차별 계획 JSON 생성 | 실험용. 출력 형식과 근거 오류가 있어 실사용 불가 |
| 로컬 OCR 글자 인식 | 한국산업인력공단 NCS 능력단위명으로 만든 가상 한글 이미지 300건 | 이미지의 한 줄 글자를 텍스트로 읽기 | `--ocr-model local` 선택 시 사용. 실제 문서 정확도 미검증 |

**로컬 로드맵 생성 학습:** `local/make_demo_data.py`가 데이터 분석가·웹 개발자 등 가상 직무 6개에 준비기간 4·6·8·12주와 과목 이수 상태 3종을 조합한다. 각 입력에는 가상 프로젝트 문서가 있고, 정답에는 원문 인용·질문·계획이 들어 있다. 실제 한국 채용 공고나 학생 개인정보는 이 데이터에 포함되지 않는다. `local/train.py`는 Qwen3-0.6B의 전체 가중치가 아닌 `q_proj`와 `v_proj`에 LoRA를 적용하여 RTX 5070에서 3회 학습했다. 별도로 만든 가상 입력 3건 중 모든 기계적 검증을 통과한 것은 1건이다. 이 작은 시험은 추천 품질을 입증하지 못한다.

**로컬 OCR 학습:** NCS 원본에서 능력단위명을 중복 제거하고, 모델이 인식할 수 있는 문자로 이루어진 5~18자 문구를 선택했다. 무작위 시드 42로 문구를 학습 300개·검증 40개·시험 40개로 나눴다. 학습 이미지는 맑은 고딕과 굵은 맑은 고딕, 검증·시험 이미지는 학습에 쓰지 않은 바탕 글꼴로 만들었다. `local/train_ocr.py`는 Qota-OCR의 글자 인식 출력층만 CTC 손실로 2회 학습하고 검증 문자 오류율이 가장 낮은 가중치를 저장했다. 결과는 아래 OCR 절과 `local/ocr-evaluation.json`을 참고한다.


### 모델과 데이터 출처

- [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B): 공개 다국어 언어 모델, Apache-2.0. 로컬 진로 분석 실험의 기본 가중치다. 사용자가 처음부터 만든 모델은 아니며 추가 학습 실험이다.
- `local/make_demo_data.py`가 만든 가상 72건: 6개 직무에 기간·과목 상태를 조합한 자체 제작 실험용 데이터다. 실제 학생 정보나 실제 직무 기준이 아니며, 내용의 다양성이 제한된다.
- [Henry010/job-counseling](https://huggingface.co/datasets/Henry010/job-counseling): 데이터 카드에는 MIT라고 적혀 있지만 확인한 첫 파일은 JSON 구문 오류가 있어 학습에 사용하지 않았다. 실제 출처와 이용조건도 추가 검증이 필요하다.
- 기존 프로젝트의 `docs/test-files`: TXT/PDF/DOCX 텍스트 추출 검증용 가상 문서. 로드맵 모델 학습에는 사용하지 않았다.
- 학습에는 [PEFT](https://github.com/huggingface/peft)(Apache-2.0) LoRA, PyTorch, Transformers, Datasets를 사용한다. 기존 문서 파서는 pypdf/python-docx를 사용한다. 각 패키지의 배포 라이선스는 해당 프로젝트에서 확인한다.

### 문서 추출과 OCR

일반 텍스트 PDF/DOCX/TXT는 기존 `apps/api/app/providers/document_parser.py`가 담당한다. `--ocr`은 `ai/local/ocr.py`에서 이미지 PNG/JPEG, 스캔 PDF, DOCX 내부 PNG/JPEG를 로컬에서 읽는다. 글자 위치 검출은 두 선택지 모두 공개 사전학습 모델을 사용한다. 글자 인식은 `--ocr-model local`(기본값)이 추가 학습 가중치, `--ocr-model open-source`가 원본 Qota-OCR이다. 둘 다 로컬에서 실행되며 인터넷을 사용하지 않는다. `--ocr-model`은 `--ocr`과 함께 사용한다. PDF는 최대 20페이지, DOCX는 이미지 20개, 한 이미지 최대 2,000만 픽셀을 처리한다. OCR 결과는 오류·중복 가능성이 있으므로 항상 `partial`이며 CLI에서 읽힌 범위를 확인하고 각 문서 ID를 `--confirm`해야 분석에 포함된다. 혼합 PDF는 기존 텍스트와 OCR이 중복될 수 있다. DOCX 이미지 위치는 원래 페이지가 아닌 이미지 순번이다. 손글씨·표·회전·배치 정확도는 검증하지 않았다. 파일은 서버로 전송하지 않고 로컬에서 OCR한다.

가상 한글 PNG, 스캔 PDF, 이미지가 포함된 DOCX에서 텍스트 추출과 부분 확인을 시험했다. DOCX OCR 결과의 줄바꿈과 Gemini 인용의 공백 차이로 두 번 거절된 문제를 수정한 후 한 번의 가상 DOCX 시험에서 추천 결과를 받았다. 공백만 다른 경우 실제 원문으로 복원하고 글자가 다른 인용은 거절한다. 이는 소규모 시험으로, 손글씨·실제 문서·추출된 경험과 근거의 의미상 일치까지 검증한 것은 아니다.

이 PC에는 모델을 설치했다. 다른 PC에서는 CUDA PyTorch와 호환 torchvision을 설치한 뒤 다음을 실행한다. GPU가 없으면 CPU로 실행하며 느릴 수 있다.

```powershell
python -m pip install -r ai/requirements-ocr.txt
python ai/download_ocr_models.py
# NCS 원본을 ai/local/data/ncs.csv로 다운로드한 뒤 Windows GPU에서 1차·2차 추가 학습
python ai/local/train_ocr.py
python ai/local/train_ocr.py --base ai/models/ocr-trained --output ai/models/ocr-v2 --train-count 1200 --eval-count 100 --epochs 3 --augment
```

- [Qota-OCR](https://huggingface.co/atonlee/Qota-OCR): Apache-2.0 한국어·다국어 글자 인식 모델. 한 줄 인식만 하므로 아래 검출 모델과 함께 사용한다. 모델 카드에 AI Hub 기반 학습 데이터의 출처가 기재돼 있다.
- [PP-OCRv6 small detector](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_safetensors): Apache-2.0 텍스트 영역 검출 모델. 기본 OCR에서 사용하는 검출 모델은 Git에서 추적할 수 있다. 원본 Qota-OCR은 선택 사항이며 별도로 내려받는다.
- PyTorch, Transformers, Pillow, OpenCV 및 pypdfium2를 사용한다. PyPDFium2는 Apache-2.0/BSD-3-Clause 라이선스 조건을 확인한다. 기존 문서 파서는 pypdf와 python-docx를 사용한다.

#### OCR 추가 학습과 평가

`local/train_ocr.py`는 한국산업인력공단 NCS 능력단위명으로 생성한 가상 한 줄 이미지 300건에서 Qota-OCR의 CTC 출력층을 RTX 5070으로 2회 학습했다. 나머지 가중치와 글자 위치 검출 모델은 학습하지 않았다. 입력 문구를 학습·검증·시험으로 분리하고 학습에 쓰지 않은 바탕 글꼴과 문구 40건으로 원본과 비교했다. 원본의 문자 오류율 3.05%, 완전 일치 70%에 비해 학습 모델은 각각 1.53%, 85%였다. 결과는 `local/ocr-evaluation.json`에 기록되어 있다. 이 시험은 인쇄체 합성 한 줄만 다루며 실제 스캔·손글씨·표·전체 페이지 성능을 의미하지 않는다. 실제 문서를 사용하기 전 추가 검증이 필요하다. 기본 OCR 모델 가중치는 Git에서 추적할 수 있으며, Windows 글꼴은 해당 PC에 설치된 글꼴을 사용한다.

이후 1차 모델에 NCS 문구 1,200건과 날짜·구두점 등을 조합해 두 번째 모델 `ai/models/ocr-v2`를 3회 추가 학습했다. 별도 합성 한 줄 100건에서 1차 모델은 87/100, 2차 모델은 97/100을 완전 일치했다. 이어 문구 2,400건으로 세 번째 모델도 시험했지만 실제 개발 문서 점수는 2차보다 개선되지 않아 선택하지 않았다. 현재 `--ocr-model local`은 2차 모델과 페이지 방향 자동 판별을 사용한다. 방향 판별과 두 번째 모델의 결합은 기계적 실험이며 실제 문서 전반에서 성능 향상을 보장하지 않는다. 기본 OCR 모델은 Git에 포함할 수 있다. 파일이 없는 경우 위 1차·2차 학습 명령을 순서대로 실행한다.

#### 실제 공공 문서 비교 (2026-11-08)

[ONTHEIT/KDoc-OCRBench-V2](https://huggingface.co/datasets/ONTHEIT/KDoc-OCRBench-V2)의 실제 한국어 공공 문서 중 공지·안내서·보고서 각 1쪽을 선택했다. 각 문서의 검증된 문구 8개씩 총 24개가 OCR 결과에 나타나는지 확인했다. Unicode 정규화와 공백 제거 후 정확한 부분 문자열로 비교했으며, 공식 벤치마크의 허용 오차나 표·읽기 순서 점수는 적용하지 않았다.

| 문서 유형 | 원본 Qota-OCR | 직접 추가 학습한 인식기 |
| --- | --- | --- |
| 포항시 소식지 | 3/8 | 3/8 |
| 국토교통부 규제안내서 | 3/8 | 3/8 |
| 국립산림과학원 보고서 | 8/8 | 8/8 |
| 합계 | **14/24** | **14/24** |

이 수치는 문자 정확도(CER)가 아니라 일부 문구의 정확한 포함 여부다. 문서 3쪽은 무작위 대표 표본이 아니며 페이지 텍스트의 전체 품질, 손글씨, 실제 스캔 여부를 평가하지 않는다. 두 모델이 실문서 전반에서 동등하다고 결론 낼 수 없다. `local/evaluate_real_ocr.py`는 카테고리별 조건에 맞는 첫 문서를 고르고, `local/ocr-real-evaluation.json`에는 문서별 출처·라이선스·출처표시와 결과를 보관한다. 원본 문서와 벤치마크 데이터는 `local/data/`에 다운로드되며 Git에 포함하지 않는다. 문서별 제공기관의 이용 조건을 따른다.

**추가 학습 후 독립 시험:** 위 첫 3쪽과 별도로 분류별 세 번째 문서 3쪽을 고정해 같은 방식으로 검사했다. 1차 모델은 13/24, 2차 모델과 자동 회전 결합은 14/24였다. 90% 목표에는 미달이다. 중간에 확인한 두 번째 문서 3쪽은 회전 처리 개발에 사용했으므로 독립 시험에서 제외했다. `local/ocr-final-baseline.json`과 `local/ocr-final-v2.json`에 개별 결과가 있다. 문서가 매우 적고 표·읽기 순서는 따로 평가하지 않았으므로 보편적인 실사용 정확도라고 해석하면 안 된다.

```powershell
ai/.venv/Scripts/python.exe ai/local/evaluate_real_ocr.py
```

시험용 데이터는 `python ai/local/make_demo_data.py`로 생성할 수 있습니다. 한 행은 목표·기간·문서와 그에 대한 올바른 경험 근거, 질문, 주차별 계획의 쌍입니다. 실제 학습 데이터는 잘못된 근거나 허구의 경험을 제거하고, 실제 인물의 개인정보를 포함하지 않도록 검수하세요. 학습에 쓰지 않는 별도 검증 사례로 근거 일치와 추천 품질을 확인해야 합니다.

이 PC의 시험 환경은 `ai/.venv`이며 기본 모델은 `ai/models/qwen3-0.6b`, 최근 시험 학습 결과는 `ai/models/career-experiment`입니다. CUDA 지원 PyTorch, transformers, accelerate, datasets, peft가 필요합니다. 모델이 지정된 JSON 형식을 지키지 않으면 검증이 실패합니다.

```powershell
$env:LOCAL_MODEL_PATH = 'ai/models/career-experiment'
$env:AI_PYTHON = (Resolve-Path 'ai/.venv/Scripts/python.exe').Path
python ai/workflow.py analyze 요청ID --storage C:/roadmap-test/store --provider local
```

학습에는 추가로 datasets가 필요합니다. JSONL은 한 줄마다 `{"messages":[{"role":"user","content":"입력"},{"role":"assistant","content":"정답 JSON"}]}` 형식입니다. 검수된 데이터와 기본 모델은 별도로 준비해야 합니다. RTX 5070 CUDA를 사용하며 모델 크기에 따라 12GB VRAM이 부족할 수 있습니다.

```powershell
ai/.venv/Scripts/python.exe ai/local/train.py --model ai/models/qwen3-0.6b --data ai/local/demo.jsonl --output ai/models/career-experiment --epochs 3
```

## 2026-11-07 실험 평가

학습 예제와 별도로 만든 가상 입력 3건을 `local/evaluate.py`로 검사했다. 기존 6건 시험 모델은 유효 JSON 0/3, 새 72건 LoRA 모델은 유효 JSON 2/3, 필수 구조 2/3, 원문 인용 일치 1/3, 준비기간 범위 2/3이었다. 전체 조건을 통과한 사례는 1/3이다. 이 평가는 작은 가상 세트의 기계적 검사이며 추천의 사실성·적절성을 평가하지 않는다. 출력이 원문에 존재해도 해당 설명을 뒷받침하는지 자동 검증하지 못한다. 결과 파일은 `local/eval-baseline.json`, `local/eval-career.json`이다. 이 시험은 로드맵 모델에 대한 것이며 OCR의 별도 평가는 위 OCR 절에 기록했다.

가상 입력 단독 호출은 `node --env-file=ai/.env ai/generate.mjs ai/sample-input.json`, 테스트는 `node --test ai/gemini/roadmap.test.mjs`입니다. 원문 인용의 존재를 검사하지만 AI 설명의 사실성을 보장하지 않습니다.

#### 대학 학과 데이터 추가 OCR 실험 (2026-11-08)

[공공데이터포털 전국대학별학과정보표준데이터](https://www.data.go.kr/data/15107737/standard.do)의 웹 미리보기 499행(24개 학교, 370개 고유 학과명)을 사용했다. 자료는 OCR 정답 이미지가 아닌 학교명·학과명 목록이며 전국 전체가 아니다. [교육데이터 활용·지원 서비스](https://data.edmgr.kr/dataView.do?id=www-data-go-kr-data-standard-15107737)는 라이선스를 CC0로 안내한다. 데이터 출처는 한국대학교육협의회·공공데이터포털이다. 실제 자료 배포 시 원본 포털의 최신 이용 조건을 확인한다.

`local/extract_university_data.py`는 로컬에 저장한 원본 HTML의 표에서 학교명과 학과명을 추출한다. `local/train_ocr_university.py`는 중복 문구를 제거하고 표현 가능한 글자만 남긴 뒤 시드 42로 서로 다른 문구 270/60/60개를 학습/검증/시험으로 나누었다. 맑은 고딕으로 합성한 한 줄 이미지를 사용해 기존 `ocr-v2`의 CTC 출력층만 RTX 5070에서 3회 학습하고 검증 문자 오류율이 가장 낮은 회차를 선택했다. 검증과 시험에는 학습에 쓰지 않은 바탕 글꼴을 사용한다. 같은 학교의 학과명은 서로 다른 분할에 포함될 수 있다.

학습하지 않은 합성 문구 60개에서 기존 모델과 추가 학습 모델 모두 완전 일치 60/60, 문자 오류율 0%였다. 이 쉬운 합성 시험에서 개선은 확인되지 않았다. 기존 실제 공공 문서 3쪽의 24개 문구 포함 시험에서도 기존 모델과 새 모델이 각각 14/24로 같았다. 이는 문자 정확도가 아니며 실제 문서 전반의 성능을 대표하지 않는다. 따라서 새 모델은 기본값으로 채택하지 않았고, 검출기와 회전 처리도 바뀌지 않았다. 실험 모델 가중치는 정리했으며, 시험 결과는 `local/ocr-university-evaluation.json`과 `local/ocr-university-real-evaluation.json`에 기록했다. 학습 스크립트로 실험 모델을 다시 만들 수 있다. 원본 데이터는 Git에 포함되지 않는다.

Windows에서 저장소 루트 기준 재현 방법(가상환경 및 `models/ocr-v2` 필요):

```powershell
Invoke-WebRequest 'https://www.data.go.kr/data/15107737/standard.do' -OutFile ai/local/data/university_source.html
ai/.venv/Scripts/python.exe ai/local/extract_university_data.py
ai/.venv/Scripts/python.exe ai/local/train_ocr_university.py --epochs 3 --augment
ai/.venv/Scripts/python.exe ai/local/evaluate_real_ocr.py --candidate ai/models/ocr-university --split final --orientation auto --output ai/local/ocr-university-real-evaluation.json
```

포털 표의 내용이나 구조가 바뀌면 데이터 해시, 행 수와 결과도 달라질 수 있다. 전체 문서 OCR 개선을 입증하려면 다양한 실제 성적표·이력서의 허가된 정답 이미지와 별도 시험 문서가 필요하다.


추가로 기존 모델의 영역 여백을 0, 2, 4, 8픽셀로 검증 문서 3쪽에 적용했을 때 각각 18/24, 18/24, 18/24, 17/24였으므로 기본 여백 0을 유지했다. 합성 시험 기록은 `local/ocr-university-evaluation.json`이다.

### OCR 자동 열 정렬 실험 (2026-11-12)

`LocalOCR`은 검출한 텍스트 상자의 좌우 배치가 반복되면 기존 열 정렬을, 그렇지 않으면 행 정렬을 적용한다. 세 쌍 이상의 상자가 같은 높이에서 페이지 중앙을 사이에 두고 충분히 떨어져 있는지 검사하는 규칙이다. `layout='rows'` 또는 `layout='columns'`를 지정하면 자동 선택을 끌 수 있다. 가중치 학습이나 문자 인식기 변경은 없으며, 텍스트 순서를 변경하는 방식이다. 표·복잡한 문서에서 읽기 순서가 틀리거나 팀 작업이 본인 작업으로 잘못 해석될 수 있으므로 OCR 결과의 사용자 확인은 계속 필요하다.

`ocr_test` 브랜치의 합성 학생 프로젝트 12개·36장과 그 기존 OCR 출력을 이용해 공백 제외 CER을 비교했다. 기존 저장 출력은 1,012/7,317 = 13.83%, 자동 정렬 재실행은 652/7,317 = 8.91%였다. 제공된 기존 사실 채점기의 역할 보존은 40/56에서 54/56으로 바뀌었고 잘못 연결됨은 두 경우 모두 0건이었다. 새 기준에서 미확정 2건이 남았다. 이는 알려진 36장으로 규칙을 고르고 같은 자료로 측정한 개발 결과라 독립 시험이나 실제 학생 문서의 일반적인 정확도가 아니다. 실행 환경도 기존 CPU와 현재 GPU가 달라 새 결과의 개선은 정렬 변경 외 환경 영향까지 완전히 분리한 통제 실험이 아니다.

별도 KDoc 공개 문서 3쪽에서 원래 보관된 점수와 동일한 정확 부분문자열 검사 결과는 14/24에서 17/24였다. 이 문서들도 이전 OCR 개발 과정에서 확인한 적이 있으며, 표·전체 문자 정확도를 평가하지 않는다. 정렬이 인식 문자나 역할의 정확성을 보장하지 않는다. 페이지별 오류·역할 수는 `local/ocr-layout-evaluation.json`에 기록했다. 공개 문서의 개별 결과는 `local/ocr-layout-public-evaluation.json`에 있다. 실험 원본은 건드리지 않았다.

재실행하려면 `ocr_test` 브랜치에 있는 `data/evaluation/ocr-v2-student-projects-20261110`을 별도 경로에 준비한 뒤, 저장소 루트에서 이전 결과를 덮어쓰지 않는 새 출력 파일을 지정한다.

```powershell
python ai/local/evaluate_layout.py --dataset <평가_데이터_폴더> --output <새_결과_JSON>
python ai/local/test_ocr_layout.py
```
