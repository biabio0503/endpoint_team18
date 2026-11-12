param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$folder = Split-Path -Parent $MyInvocation.MyCommand.Path
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Korea Standard Time')
if ([TimeZoneInfo]::Local.Id -ne $zone.Id) { throw 'Windows 시간대를 한국 표준시로 설정해야 예약을 등록할 수 있습니다.' }
$now = [TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow, $zone)
if ($now.Date -gt [datetime]'2026-11-15') { throw '예약 종료일이 지났습니다.' }
# A successful manual collection is required before registering automatic runs.
& $Python (Join-Path $folder 'crawler.py')
if ($LASTEXITCODE -ne 0) { throw '최초 수집 실패: 예약 작업을 등록하지 않았습니다.' }
$start = $now.Date.AddDays(1).AddHours(9).AddMinutes(10)
if ($start.Date -gt [datetime]'2026-11-15') { Write-Host '예약할 날짜가 남아 있지 않습니다.'; exit 0 }
$trigger = New-ScheduledTaskTrigger -Daily -At $start
$trigger.StartBoundary = $start.ToString('yyyy-MM-ddTHH:mm:ss')
$trigger.EndBoundary = '2026-11-15T23:59:59'
$resolvedPython = (Get-Command $Python -ErrorAction Stop).Source
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + (Join-Path $folder 'scheduled_run.ps1') + '" -Python "' + $resolvedPython + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $folder
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'Team18-Dacon-Daily' -Action $action -Trigger $trigger -Settings $settings -Description 'Dacon public listings, 09:10 KST through 2026-11-15' -Force | Out-Null
Write-Host '예약 등록 완료: 매일 09:10 KST, 2026-11-15까지.'
