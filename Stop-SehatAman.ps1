$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$recordPath = Join-Path $taskRoot '.local\server-process.json'
if (-not (Test-Path -LiteralPath $recordPath)) { Write-Output 'No background SehatAman process record exists.'; exit 0 }
$record = Get-Content -Raw -LiteralPath $recordPath | ConvertFrom-Json
if ([System.IO.Path]::GetFullPath($record.project) -ne $taskRoot) { throw 'The process record belongs to a different project.' }
$taskProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int]$record.pid)
if (-not $taskProcess) { Write-Output 'The recorded process has already stopped.'; exit 0 }
$entryPath = Join-Path $taskRoot 'manage.py'
if ($taskProcess.Name -ne 'python.exe' -or -not $taskProcess.CommandLine.Contains($entryPath) -or -not $taskProcess.CommandLine.Contains('serve')) { throw 'Refusing to stop a process that is not this project server.' }
Stop-Process -Id $taskProcess.ProcessId
Write-Output 'Stopped the task-owned SehatAman background server. Persisted data is retained.'
