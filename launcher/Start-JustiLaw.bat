@echo off
rem JustiLawAI one-click launcher (Windows). Double-click to start; close the window to stop.
chcp 65001 >nul
rem Started from a PowerShell 7 terminal, the inherited PSModulePath breaks Windows PowerShell 5.1 built-in cmdlets
set "PSModulePath="
set "PS1=%~dp0start.ps1"
if not exist "%PS1%" set "PS1=%~dp0launcher\start.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
