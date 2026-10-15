# 发现层每周例行的计划任务入口（设计 docs/04-plan/search-discovery-design.md §9 M4）。
# 由 Windows 计划任务调用：切到本脚本所在仓库根目录，跑 weekly.py，输出写到数据目录 discover/logs/。
# API Key 从 Windows 用户级环境变量 QIANFAN_API_KEY 读取（search.api_key()），本脚本不含任何密钥。

# 不用 Stop：Windows PowerShell 5.1 会把 Python 写到 stderr 的警告包成 NativeCommandError，Stop 时整个任务中断
# （2026-10-15 首次计划任务即因 urllib3 的 InsecureRequestWarning 失败）。成败以 python 的退出码为准。
$ErrorActionPreference = "Continue"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$dataDir = if ($env:JUSTILAW_DATA_DIR) { $env:JUSTILAW_DATA_DIR } else { "D:\02_Dev\Data\justilaw-research" }
$logDir = Join-Path $dataDir "discover\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("weekly-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

$env:PYTHONIOENCODING = "utf-8"
Set-Location $repo
# -u 不缓冲（日志实时落盘）；-W ignore 屏蔽警告；stderr 合并后逐行转成字符串，以 UTF-8 追加写日志
# （5.1 的 Tee-Object 只会写 UTF-16，所以不用它）
& python -u -W ignore research/discretion/discover/weekly.py 2>&1 | ForEach-Object {
    $line = "$_"
    Add-Content -Path $log -Value $line -Encoding UTF8
    $line
}
exit $LASTEXITCODE
