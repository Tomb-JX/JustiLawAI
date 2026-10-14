<#
.SYNOPSIS
  JustiLawAI 单机一键启动（Windows）：准备 Python 环境 → 检测 Ollama → 启动服务 → 打开浏览器。
.DESCRIPTION
  首次运行会创建 justilaw-api\.venv 并安装依赖（约 1-3 分钟），之后秒开。
  没有 Python 3.10+ 时可自动安装 uv（Astral 官方的独立 Python 管理工具）并用它准备 Python，无需手动安装 Python。
  模型的下载与配置在网页里的「模型连接向导」完成，本脚本不拉取模型。
  兼容 Windows PowerShell 5.1（本文件须保存为 UTF-8 with BOM）。
.EXAMPLE
  双击 Start-JustiLaw.bat；或 powershell -ExecutionPolicy Bypass -File launcher\start.ps1 -Port 8000
#>
param([int]$Port = 8000, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 脚本既可在仓库的 launcher\ 下运行，也可在发布包根目录运行
$Root = if ((Split-Path $PSScriptRoot -Leaf) -eq 'launcher') { Split-Path $PSScriptRoot -Parent } else { $PSScriptRoot }
$Api = Join-Path $Root 'justilaw-api'
$Venv = Join-Path $Api '.venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$WebIndex = Join-Path $Root 'justilaw-web\dist\index.html'
$Mirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }
function Fail($msg) {
  Write-Host "`n[错误] $msg" -ForegroundColor Red
  Read-Host '按回车键退出'
  exit 1
}

# 本机地址不能走系统代理（开着代理时请求 127.0.0.1 会被转发而失败）
function Get-Json($url, $timeoutMs = 3000) {
  try {
    $req = [System.Net.WebRequest]::Create($url)
    $req.Proxy = $null
    $req.Timeout = $timeoutMs
    $resp = $req.GetResponse()
    $reader = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
    $text = $reader.ReadToEnd()
    $resp.Close()
    return $text | ConvertFrom-Json
  } catch { return $null }
}

# 端口上是不是"单机版 JustiLawAI"：鉴权关闭且托管了网页（开发用的后端只提供 API，不能当成已在运行）
function Test-JustiLawLocal($p) {
  $h = Get-Json "http://127.0.0.1:$p/api/v1/health"
  if (-not $h -or $h.data.service -ne 'justilaw-api' -or $h.data.auth_enabled) { return $false }
  try {
    $req = [System.Net.WebRequest]::Create("http://127.0.0.1:$p/")
    $req.Proxy = $null; $req.Timeout = 3000
    $resp = $req.GetResponse(); $type = $resp.ContentType; $resp.Close()
    return $type -like 'text/html*'
  } catch { return $false }
}

function Test-PortFree($p) {
  try {
    $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $p)
    $l.Start(); $l.Stop(); return $true
  } catch { return $false }
}

# 找一个 ≥3.10 的 Python；Windows 应用商店的 python.exe 占位程序会被版本检查排除
function Find-Python {
  foreach ($c in @(@('py', '-3'), @('python'), @('python3'))) {
    $exe = $c[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $args_ = @($c | Select-Object -Skip 1) + @('-c', 'import sys; print(int(sys.version_info >= (3, 10)))')
    try { $out = & $exe @args_ 2>$null } catch { continue }
    if ("$out".Trim() -eq '1') { return , $c }
  }
  return $null
}

Write-Host 'JustiLawAI 单机版' -ForegroundColor White
Write-Host "目录：$Root"

# ---------- 1. 已在运行则直接打开 ----------
if (Test-JustiLawLocal $Port) {
  Ok "服务已在运行：http://127.0.0.1:$Port"
  if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
  exit 0
}
if (-not (Test-PortFree $Port)) {
  $orig = $Port
  while (-not (Test-PortFree $Port)) { $Port++ }
  Warn "端口 $orig 被其他程序占用，改用 $Port"
}

if (-not (Test-Path $WebIndex)) {
  Fail "缺少网页文件 $WebIndex。请使用发布包（JustiLawAI-local.zip），或先在 justilaw-web 目录执行 pnpm install; pnpm build"
}

# ---------- 2. Python 环境 ----------
Step '准备 Python 环境'
$useUv = $false
if (-not (Test-Path $VenvPy)) {
  $py = Find-Python
  if ($py) {
    Ok "使用 Python：$($py -join ' ')"
    $pyArgs = @($py | Select-Object -Skip 1) + @('-m', 'venv', $Venv)
    & $py[0] @pyArgs
  } else {
    Warn '没有找到 Python 3.10 或更高版本。'
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
      $ans = Read-Host '是否自动安装 uv（Astral 官方工具，约 30 MB，用于下载独立的 Python）？[Y/n]'
      if ($ans -match '^[nN]') { Fail '请先安装 Python 3.10+（https://www.python.org/downloads/ ，安装时勾选 Add to PATH）后重新运行' }
      powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
      $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
      if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Fail 'uv 安装失败，请手动安装 Python 3.10+ 后重试' }
    }
    uv venv --python 3.12 $Venv
  }
  if (-not (Test-Path $VenvPy)) { Fail '创建 Python 虚拟环境失败' }
}
if (Get-Command uv -ErrorAction SilentlyContinue) { $useUv = $true }

# 依赖只在 requirements.txt 变化时重装
$req = Join-Path $Api 'requirements.txt'
$stamp = Join-Path $Venv '.requirements.sha256'
$hash = [BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.IO.File]::ReadAllBytes($req)))
if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $hash) {
  Step '安装依赖（首次运行约 1-3 分钟）'
  function Install($extra) {
    if ($useUv) { uv pip install --python $VenvPy -r $req @extra }
    else { & $VenvPy -m pip install --disable-pip-version-check -r $req @extra }
    return $LASTEXITCODE -eq 0
  }
  if (-not (Install @())) {
    Warn '默认源安装失败，改用国内镜像重试…'
    if (-not (Install @('-i', $Mirror))) { Fail '依赖安装失败，请检查网络后重试' }
  }
  Set-Content $stamp $hash
}
Ok 'Python 环境就绪'

# ---------- 3. Ollama ----------
Step '检测 Ollama'
$ollama = Get-Json 'http://127.0.0.1:11434/api/version'
if ($ollama) {
  Ok "Ollama 已运行（v$($ollama.version)）"
} else {
  $app = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
  if (Test-Path $app) {
    Warn 'Ollama 已安装但未运行，正在启动…'
    Start-Process $app
  } else {
    Warn '没有检测到 Ollama。将打开下载页：安装后网页里的向导会自动连接（服务照常启动）。'
    Start-Process 'https://ollama.com/download'
  }
}

# ---------- 4. 启动服务 ----------
Step "启动服务：http://127.0.0.1:$Port"
$env:PYTHONIOENCODING = 'utf-8'
$env:WEB_DIST_DIR = Split-Path $WebIndex -Parent
if (-not $NoBrowser) {
  # 后台等服务就绪后打开浏览器（Start-Job 在 5.1 下可用）
  Start-Job -ArgumentList $Port -ScriptBlock {
    param($p)
    for ($i = 0; $i -lt 60; $i++) {
      try {
        $r = [System.Net.WebRequest]::Create("http://127.0.0.1:$p/api/v1/health"); $r.Proxy = $null; $r.Timeout = 1000
        $r.GetResponse().Close(); Start-Process "http://127.0.0.1:$p"; return
      } catch { Start-Sleep -Milliseconds 500 }
    }
  } | Out-Null
}
Write-Host '    关闭此窗口即停止服务。数据保存在 justilaw-api\store。' -ForegroundColor DarkGray
Push-Location $Api
try { & $VenvPy -m uvicorn app.main:app --host 127.0.0.1 --port $Port }
finally { Pop-Location }
