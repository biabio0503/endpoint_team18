# 데이콘 대회 크롤러

데이콘 공개 메인과 대회 탭에서 대회를 찾고, **진행·모집 중으로 확인된 대회에만** 상세 페이지를 열어 제목, 상금, 대회 시작일, 종료일, URL, 한 줄 소개(description), 대회 개요(overview)를 수집한다. 소개나 개요를 확인하지 못하면 null이며 기존 값이 있으면 보존한다. 개요는 원문이며 AI 요약이 아니다. 종료·마감·연습 대회의 상세 페이지는 요청하지 않는다. 메인에 노출된 데이커 대회는 그 상세 페이지만 추가로 읽는다. 데이커의 전체 목록은 별도로 탐색하지 않는다. 상세 화면에 표시된 대회 기간을 사용하고, 기간을 확정할 수 없으면 실행에 실패하며 기존 캐시는 그대로 둔다. 대회 상세 내용에 직접 비공개 API를 호출하지 않는다. 다만 웹페이지가 자체적으로 불러오는 리소스가 있을 수 있다.

추가 요청을 줄이기 위해 메인에 표시된 대회와 대회 탭 첫 화면만 살펴본다. 더보기는 누르지 않으므로 해당 화면 밖의 대회는 누락될 수 있다. 상세 페이지 요청은 3초 이상 간격을 둔다. 목록이나 상세 페이지 확인에 실패하면 기존 캐시를 수정하지 않는다.

## 설치 및 수동 수집

Windows PowerShell에서 저장소 루트 기준:

```powershell
python -m pip install -r crawling/dacon/requirements.txt
python -m playwright install chromium
python crawling/dacon/crawler.py
```

마지막 명령은 한번 수집한다. 실행 결과는 `added`, `changed`, `removed`, `competitions`를 담은 JSON으로 터미널에 출력하고, 현재 대회 목록을 `crawling/dacon/competitions.json`에 캐시한다. 변동이 없으면 캐시 파일을 다시 쓰지 않는다. 목록에 명시적으로 마감·종료·연습이 표시된 기존 대회만 삭제한다. 상태가 불명확하거나 페이지에서 사라진 것만으로 삭제하지 않기 때문에 해당 대회가 캐시에 일시적으로 남을 수 있다. DB 연결은 포함하지 않는다. 팀원이 `removed` ID를 이용해 별도 DB 삭제 로직을 만들 수 있다.

## JSON 출력 형식

터미널에는 변경 사항과 현재 목록을 함께 출력한다. 다음은 형식을 설명하기 위한 가상 예시다.

```json
{
  "added": ["daker:example"],
  "changed": [],
  "removed": [],
  "competitions": [
    {
      "id": "daker:example",
      "title": "AI 공모전",
      "prize": "1,000,000원",
      "start_date": "2026-11-01",
      "end_date": "2026-11-15",
      "url": "https://daker.ai/public/hackathons/example",
      "status": "모집중",
      "description": "AI를 활용한 서비스를 만드는 공모전입니다.",
      "overview": "대회 배경과 목적, 주제 등을 포함한 개요 원문입니다."
    }
  ]
}
```

| 필드 | 내용 |
| --- | --- |
| `added` | 새로 추가된 대회의 ID 목록 |
| `changed` | 기존 캐시와 정보가 달라진 대회의 ID 목록 |
| `removed` | 마감·종료·연습이 확인되어 캐시에서 삭제된 대회의 ID 목록 |
| `competitions` | 변경 사항을 반영한 현재 캐시 대회 목록 |
| `id` | 대회 식별자. 데이커 대회는 `daker:` 접두사를 사용 |
| `title`, `prize` | 대회명과 상금 문자열. 상금을 확인하지 못하면 `null` |
| `start_date`, `end_date` | 대회 시작일과 종료일 (`YYYY-MM-DD`) |
| `url`, `status` | 대회 URL과 상태 (`진행중` 또는 `모집중`) |
| `description` | 상세 페이지의 한 줄 소개. 없으면 `null` |
| `overview` | 상세 페이지의 대회 개요 원문. 없으면 `null` |

소개와 개요는 AI 요약이 아니라 페이지에 표시된 내용이다. 수집 시 일시적으로 읽지 못하면 기존에 저장된 소개와 개요를 유지한다. 처음 수집하면 새 대회 ID가 `added`에 들어가며, 정보가 같으면 `changed`에 들어가지 않는다.

`competitions.json`은 `{"competitions": [...]}` 형태로 현재 목록만 저장한다. 터미널 출력과 자동 실행의 `last_run.json`에는 `added`, `changed`, `removed`도 포함된다. 이 크롤러는 DB를 직접 변경하지 않으므로 DB 담당자가 `removed`를 별도로 반영해야 한다.

## 자동 실행

아래 명령은 **수집을 즉시 한 번 실행하고 성공하면** 다음 날부터 2026년 11월 15일까지 매일 09:10 KST에 Windows 작업 스케줄러를 등록한다. 이미 수동 수집했더라도 등록 과정에서 한 번 더 수집한다. PC가 한국 표준시로 설정되어 있어야 한다.

```powershell
powershell -ExecutionPolicy Bypass -File crawling/dacon/install_schedule.ps1 -Python "$env:LOCALAPPDATA\Python\bin\python.exe"
```

자동 실행은 PC가 켜져 있고 예약 작업을 실행할 수 있을 때 동작하며, 꺼짐·절전 중 놓친 실행은 보충하지 않는다. 예약 시 현재 목록은 `competitions.json`, 추가·변경·삭제 ID를 포함한 마지막 실행 결과는 `last_run.json`에 저장된다. `last_run.json`은 다음 성공 실행 때 덮어쓰므로 DB 담당자는 각 실행 결과를 처리해야 한다. 기존 `Team18-Dacon-Daily` 예약이 있으면 교체한다. 오류는 작업 스케줄러에서 확인한다.

```powershell
Get-ScheduledTask -TaskName Team18-Dacon-Daily | Get-ScheduledTaskInfo
Unregister-ScheduledTask -TaskName Team18-Dacon-Daily
python -m unittest discover -s crawling/dacon -p 'test_*.py' -v
```

예약 스크립트가 있어도 등록 명령을 실행하기 전까지 자동 실행되지는 않는다.
