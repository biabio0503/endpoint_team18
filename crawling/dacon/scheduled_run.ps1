param([Parameter(Mandatory=$true)][string]$Python)
$folder = Split-Path -Parent $MyInvocation.MyCommand.Path
$temporary = Join-Path $folder 'last_run.json.tmp'
$output = Join-Path $folder 'last_run.json'
& $Python (Join-Path $folder 'crawler.py') --scheduled | Out-File -FilePath $temporary -Encoding utf8
if ($LASTEXITCODE -eq 0) { Move-Item -LiteralPath $temporary -Destination $output -Force }
else { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue; exit $LASTEXITCODE }
