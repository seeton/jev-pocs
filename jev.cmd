@echo off
setlocal
rem Do not pass PowerShell 7 module paths to Windows PowerShell 5.1.
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\jev.ps1" %*
exit /b %errorlevel%
