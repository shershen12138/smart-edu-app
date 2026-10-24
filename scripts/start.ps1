param([switch]$Demo, [switch]$Worker)
$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$pythonPath = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Error '请先使用 Python 3.12 创建 .venv 并安装 requirements.lock.txt。'
    exit 1
}
& $pythonPath manage.py migrate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Demo) {
    Write-Warning '新版不再生成助教及旧演示数据。账号初始化请查看 README 中的 reset_local_accounts 命令。'
}
if ($Worker) {
    & $pythonPath manage.py run_judge
    exit $LASTEXITCODE
}
& $pythonPath manage.py runserver 127.0.0.1:8000
