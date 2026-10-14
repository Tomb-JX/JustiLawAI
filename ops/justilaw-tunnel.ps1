<#
.SYNOPSIS
  JustiLawAI 模型隧道：把本机 Ollama 挂到服务器 docker0 上，供 justilaw-api 调用。
.DESCRIPTION
  不重复造轮子：断线重连 / 退避 / 残留会话清理全部复用 astrbot-ops 的
  services-tunnel-loop.ps1（它本来就带 -LocalPort/-RemotePort 参数化），
  本脚本只负责启动、状态、停止与计划任务安装。

    服务器 justilaw-api  ->  http://172.17.0.1:11434  ->（隧道）->  本机 Ollama 127.0.0.1:11434

  需要服务器 sshd GatewayPorts clientspecified（已配置，同 astrbot 链路）。
.EXAMPLE
  .\justilaw-tunnel.ps1            # 启动（已在运行则只显示状态）
.EXAMPLE
  .\justilaw-tunnel.ps1 -Status    # 查看隧道与模型状态
.EXAMPLE
  .\justilaw-tunnel.ps1 -Stop      # 关闭
.EXAMPLE
  .\justilaw-tunnel.ps1 -Install   # 登录 Windows 时自动启动；-Uninstall 取消
#>
param([switch]$Start, [switch]$Stop, [switch]$Status, [switch]$Install, [switch]$Uninstall)

# 复用 astrbot-ops 的公共配置（$ServerIp / $InstanceId / $Workbench / Invoke-Remote）
$OpsRoot    = "D:\02_Dev\Projects\脚本\astrbot-ops"
. (Join-Path $OpsRoot "config.ps1")

$StateDir   = Join-Path $env:LOCALAPPDATA "justilaw-ops"
$PidFile    = Join-Path $StateDir "model-tunnel.pid"
$LogFile    = Join-Path $StateDir "model-tunnel.log"
# loop 脚本把反向口统一绑到 172.17.0.1（docker0），与 astrbot 服务隧道同一约定
$LoopScript = Join-Path $OpsRoot "services-tunnel-loop.ps1"
$TaskName   = "JustiLaw 模型隧道"
$LocalPort  = 11434   # 本机 Ollama
$RemotePort = 11434   # 服务器 docker0 上的入口
New-Item -ItemType Directory -Path $StateDir -Force | Out-Null

function Get-TunnelProcess {
    if (Test-Path $PidFile) {
        $id = [int](Get-Content $PidFile -ErrorAction SilentlyContinue)
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        if ($p -and $p.CommandLine -like "*services-tunnel-loop.ps1*") { return $p }
    }
    # pid 文件可能过期，兜底按命令行找（只认带 11434 参数的那条，不误伤 astrbot 的两条）
    $real = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*services-tunnel-loop.ps1*" -and $_.CommandLine -match "11434" } |
        Select-Object -First 1
    if ($real) { $real.ProcessId | Set-Content $PidFile -ErrorAction SilentlyContinue; return $real }
    return $null
}

function Show-Status {
    $p = Get-TunnelProcess
    if ($p) { Write-Host "模型隧道守护进程运行中（PID $($p.ProcessId)），断线会自动重连" -ForegroundColor Green }
    else { Write-Host "模型隧道没有运行。运行 .\justilaw-tunnel.ps1 启动。" -ForegroundColor Yellow }

    # 本机 Ollama
    $tags = curl.exe -s --max-time 5 "http://127.0.0.1:$LocalPort/api/tags" 2>$null
    if ($tags) {
        $names = (@(($tags | ConvertFrom-Json).models) | ForEach-Object { $_.name }) -join ", "
        Write-Host "  本机 Ollama  127.0.0.1:$LocalPort  [$names]"
    } else { Write-Host "  本机 Ollama  不可达（ollama 是否在运行？）" -ForegroundColor Yellow }

    # 服务器侧反向口与后端
    $listen = Invoke-Remote "ss -tln | grep $RemotePort" 2>$null
    if ($listen) { Write-Host "  服务器侧     172.17.0.1:$RemotePort 正在监听" }
    else { Write-Host "  服务器侧     172.17.0.1:$RemotePort 没有监听" -ForegroundColor Yellow }
    $models = Invoke-Remote "curl -s --max-time 8 http://127.0.0.1:8100/api/v1/models" 2>$null
    if ($models -match 'qwen') { Write-Host "  justilaw-api 已发现模型（qwen3.5:9b）" }
    elseif ($models) { Write-Host "  justilaw-api 在线但模型列表为空（隧道未通）" -ForegroundColor Yellow }

    Write-Host "  最近日志（$LogFile）：" -ForegroundColor DarkGray
    Get-Content $LogFile -Tail 3 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
}

if ($Stop) {
    $p = Get-TunnelProcess
    if ($p) {
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.ProcessId)"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        $children | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Write-Host "模型隧道已关闭" -ForegroundColor Green
    } else { Write-Host "模型隧道本来就没有运行" }
    # 清孤儿 ssh：按本条隧道特有的转发串匹配，不会误伤 astrbot 的两条
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" |
        Where-Object { $_.CommandLine -match "172\.0?17\.0\.1:$RemotePort" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    return
}

if ($Install) {
    # 与 services.ps1 同款：VBS 隐藏启动（UTF-16，本脚本路径含中文）；登录 + 每 10 分钟自查
    $vbs = Join-Path $PSScriptRoot "justilaw-tunnel-hidden.vbs"
    if ($PSCommandPath -match '\s') { throw "脚本路径含空格，VBS 内联命令需要改回双引号方案：$PSCommandPath" }
    $inner = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath -Start"
    "Set sh = CreateObject(""WScript.Shell"")`r`nsh.Run ""$inner"", 0, False" |
        Set-Content -Path $vbs -Encoding Unicode
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B ""$vbs"""
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes 10) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit 0 -MultipleInstances IgnoreNew -StartWhenAvailable
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $logon,$repeat `
        -Settings $settings -Description "JustiLaw 模型隧道（-R 11434 → 本机 Ollama）：登录启动 + 每 10 分钟自查（VBS 隐藏启动）" `
        -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "已设置计划任务「$TaskName」：登录启动 + 每 10 分钟自查（已立即触发一次）" -ForegroundColor Green
    return
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "已取消登录时自动启动"
    return
}

if ($Status) { Show-Status; return }

if (Get-TunnelProcess) { Show-Status; return }

if (Test-Path $LogFile) {
    $recent = @(Get-Content $LogFile -Tail 500)
    try { Set-Content $LogFile -Value $recent -Encoding UTF8 } catch { }
}
$proc = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$LoopScript`"",
    "-ServerIp", $ServerIp, "-LogFile", "`"$LogFile`"",
    "-InstanceId", $InstanceId, "-LocalPort", $LocalPort, "-RemotePort", $RemotePort)
$proc.Id | Set-Content $PidFile
Start-Sleep -Seconds 5
Show-Status

