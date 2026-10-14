<#
.SYNOPSIS
  打包 JustiLawAI 单机版：release\JustiLawAI-local.zip（解压后双击 Start-JustiLaw.bat 即可使用）。
.DESCRIPTION
  包内：justilaw-api（不含 store / .venv / .env）、构建好的 justilaw-web\dist、launcher 启动脚本与使用说明。
  Python 依赖不打包，首次启动时由启动脚本自动安装（没有 Python 时可经 uv 自动准备）。
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File ops\package-local.ps1            # 构建前端并打包
  powershell -ExecutionPolicy Bypass -File ops\package-local.ps1 -SkipBuild # 复用已有 dist
#>
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Out = Join-Path $Root 'release'
$Stage = Join-Path $Out 'JustiLawAI'
$Zip = Join-Path $Out 'JustiLawAI-local.zip'
$Web = Join-Path $Root 'justilaw-web'

if (-not $SkipBuild) {
  Write-Host '==> 构建前端'
  pnpm --dir $Web install --frozen-lockfile
  if ($LASTEXITCODE -ne 0) { throw 'pnpm install 失败' }
  pnpm --dir $Web build
  if ($LASTEXITCODE -ne 0) { throw 'pnpm build 失败' }
}
if (-not (Test-Path (Join-Path $Web 'dist\index.html'))) { throw '缺少 justilaw-web\dist，请去掉 -SkipBuild 重新打包' }

Write-Host '==> 整理文件'
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force -Confirm:$false }
New-Item -ItemType Directory -Force $Stage | Out-Null

# robocopy 退出码 < 8 均为成功
robocopy (Join-Path $Root 'justilaw-api') (Join-Path $Stage 'justilaw-api') /E /NFL /NDL /NJH /NJS `
  /XD store .venv __pycache__ /XF .env *.pyc test-*.json | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 justilaw-api 失败（robocopy $LASTEXITCODE）" }
robocopy (Join-Path $Web 'dist') (Join-Path $Stage 'justilaw-web\dist') /E /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制前端失败（robocopy $LASTEXITCODE）" }

$Launcher = Join-Path $Root 'launcher'
New-Item -ItemType Directory -Force (Join-Path $Stage 'launcher') | Out-Null
Copy-Item (Join-Path $Launcher 'start.ps1'), (Join-Path $Launcher 'start.sh') (Join-Path $Stage 'launcher')
# 双击入口放在包根目录，使用说明作为 README
Copy-Item (Join-Path $Launcher 'Start-JustiLaw.bat'), (Join-Path $Launcher 'start.command') $Stage
Copy-Item (Join-Path $Launcher 'README.md') (Join-Path $Stage 'README.md')

Write-Host '==> 压缩'
if (Test-Path $Zip) { Remove-Item $Zip -Force -Confirm:$false }
Compress-Archive -Path $Stage -DestinationPath $Zip
$size = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
Write-Host "完成：$Zip（$size MB）" -ForegroundColor Green
