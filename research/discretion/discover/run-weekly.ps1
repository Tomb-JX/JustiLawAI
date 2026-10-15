# 发现层每周例行的计划任务入口（设计 docs/04-plan/search-discovery-design.md §9 M4）。
# 由 Windows 计划任务调用：切到本脚本所在仓库根目录，跑 weekly.py，输出写到数据目录 discover/logs/。
# API Key 从 Windows 用户级环境变量 QIANFAN_API_KEY 读取（search.api_key()），本脚本不含任何密钥。

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$dataDir = if ($env:JUSTILAW_DATA_DIR) { $env:JUSTILAW_DATA_DIR } else { "D:\02_Dev\Data\justilaw-research" }
$logDir = Join-Path $dataDir "discover\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("weekly-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

$env:PYTHONIOENCODING = "utf-8"
Set-Location $repo
python research/discretion/discover/weekly.py *>&1 | Tee-Object -FilePath $log
exit $LASTEXITCODE
