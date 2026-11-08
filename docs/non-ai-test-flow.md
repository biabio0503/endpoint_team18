# 비AI 전체 기능 테스트 흐름

현재 구현 기준의 수동 검수 안내서다. 모든 입력과 첨부 파일은 가상 데이터다. 체크박스는 실행 기록용이며, 작성 자체가 테스트 통과를 의미하지 않는다. AI 분석·추천·로드맵 생성은 미구현이므로 기능 검수 대상에서 제외한다. 분석 준비 안내와 빈 결과 화면은 UI 상태만 확인한다. 실제 학교 자료와 실제 외부 사이트 수집도 구현되어 있지 않다.

## 준비

1. Node.js 20.9 이상, Python 3을 준비한다. 저장소 루트에서 아래 명령을 실행한다. 기존 기본 DB를 사용하는 명령이므로 기존 계획과 섞지 않으려면 아래 별도 저장소 설정을 사용한다.

   ```sh
   python3 -m venv apps/api/.venv
   apps/api/.venv/bin/pip install -r apps/api/requirements.txt
   mkdir -p /tmp/roadmap-manual-test
   ROADMAP_DB_PATH=/tmp/roadmap-manual-test/roadmap.sqlite3 apps/api/.venv/bin/python apps/api/app/scripts/seed_dev.py
   ```

2. 터미널 1에서 API와 문서 워커를 실행한다.

   ```sh
   ROADMAP_DB_PATH=/tmp/roadmap-manual-test/roadmap.sqlite3 ROADMAP_FILE_STORAGE_PATH=/tmp/roadmap-manual-test/files ROADMAP_INSECURE_LOCAL_COOKIE=1 apps/api/.venv/bin/python apps/api/app/main.py
   ```

3. 터미널 2에서 웹을 실행한다.

   ```sh
   cd apps/web
   npm ci
   npm run dev
   ```

4. `http://localhost:3000`에 접속한다. 두 서버가 이미 해당 포트를 사용 중이면 중복 실행하지 말고 설정과 DB 경로를 확인한다. 기본 DB와 격리된 테스트 DB를 쓰더라도 기존 브라우저 쿠키가 남아 있으면 세션이 맞지 않을 수 있으므로 새 시크릿 창을 사용한다. 테스트 자료는 `/tmp/roadmap-manual-test`에 남는다. 초기화가 필요한 경우 서버를 종료하고 해당 테스트 디렉터리와 테스트 브라우저 쿠키를 정리한 뒤 다시 준비한다. 일반 브라우저의 쿠키를 삭제하면 기존 계획 접근이 끊길 수 있다.

## 업로드 파일

아래 파일은 [test-files](test-files/)에 있다. 파일 선택 창에서 저장소의 `docs/test-files`로 이동해 선택한다. 일부 파일은 의도적으로 비정상이다.

| 파일 | 용도와 예상 결과 |
|---|---|
| `project-ready.txt` | UTF-8 문서, 읽기 완료. 캠퍼스 일정 관리 서비스 역할과 활동 확인 |
| `project-ready.docx` | 본문이 있는 DOCX, 읽기 완료 |
| `project-ready.pdf` | 일반 텍스트 PDF, 읽기 완료. 외부 fixture의 영문 예시 문서 |
| `project-partial.docx` | 본문과 머리글이 있는 DOCX, 일부만 읽힘. 머리글 제외 안내 및 확인 필요 |
| `image-only.docx` | 이미지만 있는 DOCX, OCR 필요. 이미지에는 시험용 무늬만 있음 |
| `blank.pdf`, `empty-content.txt` | 형식은 유효하나 읽을 본문이 없어 읽기 실패 |
| `invalid-format.pdf` | PDF 확장자의 텍스트 파일. 업로드 시 형식 오류로 거부 |

기본 제한은 파일당 10 MiB, 계획당 10개, PDF 100페이지다. 설정값을 변경했다면 화면의 제한을 기준으로 확인한다. 문서 처리는 비동기이며 상태가 갱신될 때까지 기다린다.

## 1. 시작과 기본 정보

- [ ] 새 시크릿 창에서 **이어서 작성**을 누르면 이어 쓸 계획이 없다는 안내가 나온다.
- [ ] **새 계획 시작**을 누르면 기본 정보 화면이 열린다. 목표를 비운 채 저장하면 필수 입력 안내가 나온다.
- [ ] 목표에 `데이터 분석을 준비합니다`, 희망 직무에 `데이터 분석가`를 입력한다. 학교 `가상대학교 (개발용 예시)`, 학과 `컴퓨터공학과 (가상 예시)`, 과목 목록 `가상 교육과정 A (개발용)`, 학년 2학년을 선택한다. 학교·학과를 바꾸면 하위 선택이 초기화되는지도 확인하고 다시 선택한다.
- [ ] 선택 입력에서 취득학점 `0`, GPA `0`, 만점 `4.50`을 입력해 **저장**한다. 저장 성공 표시와 새로고침 후 값 복원을 확인한다. GPA 만점을 지우거나 GPA를 만점보다 크게 입력해 저장하면 오류가 표시되는지 확인하고 올바른 값으로 복구한다. 미입력 값과 0은 구분된다.
- [ ] **저장 후 다음: 프로젝트 문서**로 이동한다. 저장하지 않은 수정은 이동 시 사라질 수 있으므로 보존이 필요한 변경은 먼저 저장한다.

## 2. 문서 등록과 처리

- [ ] 문서가 없을 때 다음 버튼이 비활성화되어 있다. `invalid-format.pdf`를 선택하면 거부되고 목록에 추가되지 않는다. 오류가 표시되면 **최신 상태 불러오기**로 복구한다.
- [ ] `image-only.docx`, `blank.pdf`, `empty-content.txt`를 차례로 등록하고 각각 OCR 필요, 읽기 실패, 읽기 실패로 표시되는지 확인한다. 유효 문서가 없으므로 다음 버튼은 여전히 비활성화된다. **읽힌 내용**에서 본문 없음과 제한 안내를 확인한다. OCR 필요 문서는 다시 읽기 버튼이 없다.
- [ ] `project-partial.docx`를 등록해 일부만 읽힘 상태를 기다린다. **읽힌 범위 확인**에서 본문과 머리글 제외 안내, **읽힌 위치**를 확인한다. 확인 전에는 다음으로 갈 수 없고 **읽힌 범위를 확인했어요**를 누르면 범위 확인됨으로 바뀌고 다음 버튼이 활성화된다.
- [ ] 부분 문서의 **다시 읽기**를 누르면 추출 버전이 증가하고 다시 확인이 필요하다. 아직 다른 유효 문서가 없으면 다음 버튼이 다시 비활성화된다. 새 버전의 범위를 확인한다.
- [ ] `project-ready.txt`, `project-ready.docx`, `project-ready.pdf`를 각각 등록하고 읽기 완료 및 **읽힌 내용**을 확인한다. TXT의 역할·수행 내용과 DOCX 본문, PDF의 영문 텍스트가 보인다. 읽기 완료 문서의 **다시 읽기** 후 버전 증가와 완료 상태를 확인한다.
- [ ] 문서 하나를 **삭제**하고 확인 대화상자를 승인하면 목록에서 사라진다. 취소 시에는 남는다. 새로고침해도 나머지 문서와 상태가 유지된다. 한 개 이상의 읽기 완료 또는 확인된 부분 문서를 남겨 **다음: 이수 과목**으로 이동한다.
- [ ] 추가 경계 검수: 총 10개까지 등록하면 파일 선택이 비활성화된다. 10 MiB 초과 파일은 거부된다. 크기 제한 테스트 파일은 저장소에 넣지 않았으므로 필요할 때 별도로 생성한다. 파일을 삭제하면 다시 등록할 수 있다.

## 3. 이수 과목

- [ ] 목록 A에서 과목명/코드 검색, 학년·전공 구분 필터, **선택한 과목만 보기**, 이전/다음 페이지를 확인한다. 검색 결과가 없어도 기존 선택은 유지된다.
- [ ] 선택하지 않은 상태에서 **이수 선택 확인 완료**를 눌러 0개 확인이 가능함을 확인한다. `프로그래밍 기초 (DEV101)`와 `자료구조 (DEV201)`를 선택하면 즉시 저장되고 선택 현황과 학점 합계가 갱신되며 확인 상태가 해제된다. 다시 확인을 누른다.
- [ ] **목록에 없는 이수 과목이 있어요**를 체크하고 필터를 바꿔도 체크가 유지되는지 확인한다. 다시 **이수 선택 확인 완료**를 누르면 `일부 누락 · 부분 확인`이 저장된다. 체크를 바꾸고 저장하기 전에는 다음 버튼이 비활성화된다.
- [ ] 새로고침 후 선택·부분 확인이 복원되는지 확인한다. 기본 정보로 돌아가 과목 목록을 B로 바꿔 저장한 뒤 이수 과목으로 돌아오면 확인이 해제되고 목록 밖의 기존 선택이 표시된다. 이름이 같은 `데이터베이스`라도 코드가 다른 과목은 별개다. 필요한 경우 목록 밖 선택을 해제하고 현재 목록을 다시 확인한다.
- [ ] 별도 새 계획에서 학교·학과·목록을 선택하지 않고 유효 문서를 등록한 뒤 과목 화면으로 이동한다. 목록 사용 불가 안내와 **수강 제안 없이 계속**을 확인한다. 이 상태는 0개 확인과 다르다.
- [ ] 목록이 있는 계획에서는 확인을 마친 뒤 **다음: 분석 내용 확인**으로 이동한다.

## 4. 복원, 충돌, 세션 분리

- [ ] 시작 화면으로 돌아가 **이어서 작성**을 누르고 저장한 기본 정보, 문서, 과목 선택이 복원되는지 확인한다. 새 계획을 만들면 이어 쓰기 대상이 새 계획으로 바뀔 수 있으므로 복원할 계획을 먼저 확인한다.
- [ ] 같은 브라우저 세션에서 기본 정보 화면을 두 탭으로 연다. 첫 탭에서 희망 직무를 수정·저장한 후, 오래된 두 번째 탭에서 다른 값으로 저장한다. 충돌 안내가 나와야 한다. **최신 내용 불러오기**와 변경 폐기 확인을 통해 첫 탭의 값을 복원한다. 과목 화면에서도 두 탭의 오래된 선택으로 저장하면 최신 상태를 불러오라는 안내가 나오는지 확인한다.
- [ ] 다른 독립 시크릿 세션에서 기존 계획이 이어서 작성되지 않는지 확인한다. 서로 다른 세션의 직접 API 접근 차단은 아래 자동 통합 테스트로 검증한다.

## 5. 준비 중 화면

- [ ] 분석 내용 확인 화면에 준비 중 안내와 비활성화된 **로드맵 생성** 버튼이 보인다.
- [ ] **결과 화면 살펴보기**에서 준비 상태, 직무 역량 비교, 실행 로드맵, 수강 후보, 공모전·대외활동 5개 탭을 각각 선택한다. 모두 결과 없음이 표시된다. 방향키·Home·End로 탭 이동 및 **입력 수정** 링크도 확인한다. 실제 결과 생성은 테스트할 수 없다.

## 6. 내부 외부 자료 fixture 검수

화면이나 공개 API가 아닌 내부 CLI다. 다음 명령은 위 테스트 DB를 사용하며 실제 네트워크나 채용 사이트를 조회하지 않는다. 기존 테스트 결과가 있으면 고유한 `--job-key`를 사용한다.

```sh
ROADMAP_DB_PATH=/tmp/roadmap-manual-test/roadmap.sqlite3 apps/api/.venv/bin/python apps/api/app/scripts/external_collect.py init-fixtures
ROADMAP_DB_PATH=/tmp/roadmap-manual-test/roadmap.sqlite3 apps/api/.venv/bin/python apps/api/app/scripts/external_collect.py enqueue fixture-jobs --fixture-set v1 --job-key manual-v1
ROADMAP_DB_PATH=/tmp/roadmap-manual-test/roadmap.sqlite3 apps/api/.venv/bin/python apps/api/app/scripts/external_collect.py work --drain
ROADMAP_DB_PATH=/tmp/roadmap-manual-test/roadmap.sqlite3 apps/api/.venv/bin/python apps/api/app/scripts/external_collect.py inspect fixture-jobs
```

- [ ] 등록 시 반환된 작업 ID를 `status <작업 ID>`로 조회하면 성공과 가상 채용 자료 1건을 확인할 수 있다. 위와 같은 환경변수를 각 명령에 붙인다.
- [ ] `fixture-jobs`의 `empty`, `partial`, `failure`, `v2`를 서로 다른 작업 키로 등록하고 처리해 각각 0건 성공, 부분, 실패, 변경된 자료를 확인한다. 실패 작업의 `work`는 종료 코드 1일 수 있다. `retry <작업 ID>` 후 다시 `work`하면 실패 fixture는 다시 실패한다.
- [ ] `fixture-activities`와 `fixture-pdf`도 각각 등록·처리·조회한다. 활동은 2건, PDF는 본문 확보 후 필드 미분류로 부분 처리된다. 전체 명령과 의미는 [README](../README.md#외부-자료-수집-내부-fixture-검증)를 참고한다.

## 7. 자동 회귀 검증

저장소 루트에서 실행한다. 통합 테스트는 임시 DB를 사용한다. 브라우저 E2E는 Node.js 22 이상과 Chromium 계열 브라우저 및 별도 실행 서버가 필요하므로 [README의 통합 검증](../README.md#통합-검증)에 나온 격리 포트 설정을 그대로 따른다. 웹 빌드와 개발 서버는 같은 `.next`를 쓰므로 빌드 전에 웹 개발 서버를 종료한다.

```sh
apps/api/.venv/bin/python -m unittest discover -s apps/api/tests/integration -p 'test_*.py' -v
npm run build --prefix apps/web
npm run check --prefix apps/web
node --check apps/web/tests/e2e/p5-flow.mjs
```

브라우저 E2E 실행 명령은 `node apps/web/tests/e2e/p5-flow.mjs`이며, 구문 검사만으로 실제 브라우저 흐름이 실행된 것은 아니다. 수동 검수에서는 각 항목의 실행 일시·환경·결과와 오류 메시지를 별도로 기록한다.
