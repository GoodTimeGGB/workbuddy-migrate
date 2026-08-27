@echo off
cd /d "%~dp0"

:: 优先使用 Windows PowerShell 5.1 的绝对路径，避免 PATH/where 问题
set "PSPATH=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PSPATH%" set "PSPATH=powershell.exe"

if not exist "%PSPATH%" (
    echo [错误] 找不到 PowerShell。
    echo        Windows 10/11 默认应位于：
    echo        %SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe
    pause
    exit /b 1
)

"%PSPATH%" -NoProfile -ExecutionPolicy Bypass -File "launch.ps1"
set "EXITCODE=%ERRORLEVEL%"

if %EXITCODE% neq 0 (
    echo.
    echo [提示] 启动失败。请查看同目录的 start.log，或运行 diagnose.bat 截图反馈。
    pause
)

exit /b %EXITCODE%
