<# : CMD-FALLBACK

@echo off

echo [提示] 请不要直接运行 launch.ps1，双击同目录的 start.bat 来启动工具。

pause

exit /b 1

#>

#Requires -Version 5.1

# WorkBuddy 迁移工具 - 启动器

# 检测/安装 Python，启动本地 HTTP 服务，并打开浏览器。



param(

    [int]$Port = 8765

)



# 冗余版本检测

if ($PSVersionTable.PSVersion.Major -lt 5) {

    Write-Host "错误：当前 PowerShell 版本过低，需要 5.1 或更高版本。" -ForegroundColor Red

    Write-Host "请双击 start.bat 启动工具。" -ForegroundColor Yellow

    Read-Host "按 Enter 键退出"

    exit 1

}



$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

$logFile = Join-Path $scriptDir "start.log"

function Write-Log($msg) {

    $line = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $msg

    Write-Host $line

    Add-Content -Path $logFile -Value $line -Encoding utf8 -ErrorAction SilentlyContinue

}



# 清空旧日志

"" | Set-Content -Path $logFile -Encoding utf8 -ErrorAction SilentlyContinue



Write-Log "WorkBuddy 迁移工具启动"

Write-Log "工作目录: $scriptDir"



# 1) 上次一键安装的记录

$py = $null

$pathFile = Join-Path $scriptDir "python_path.txt"

if (Test-Path $pathFile) {

    $recorded = Get-Content $pathFile -Raw -Encoding utf8 -ErrorAction SilentlyContinue

    $recorded = $recorded.Trim()

    Write-Log "发现 python_path.txt: $recorded"

    if ($recorded -and (Test-Path $recorded)) {

        $py = $recorded

        Write-Log "使用该记录路径"

    } else {

        Write-Log "记录路径已失效"

    }

}



# 2) WorkBuddy 自带的 Python

if (-not $py) {

    $wbPy = "C:\Users\$env:USERNAME\.workbuddy\binaries\python\versions\3.13.12\python.exe"

    Write-Log "尝试 WorkBuddy 自带 Python: $wbPy"

    if (Test-Path $wbPy) {

        try {

            & $wbPy -c "import sys; sys.exit(0)" | Out-Null

            $py = $wbPy

            Write-Log "WorkBuddy 自带 Python 可用"

        } catch {

            Write-Log "WorkBuddy 自带 Python 无法运行: $_"

        }

    } else {

        Write-Log "WorkBuddy 自带 Python 不存在"

    }

}



# 3) 系统 PATH 里的 Python

if (-not $py) {

    foreach ($cmd in @("python", "py")) {

        Write-Log "尝试系统命令: $cmd"

        if (Get-Command $cmd -ErrorAction SilentlyContinue) {

            try {

                & $cmd -c "import sys; sys.exit(0)" | Out-Null

                $py = $cmd

                Write-Log "系统命令 $cmd 可用"

                break

            } catch {

                Write-Log "系统命令 $cmd 无法运行: $_"

            }

        } else {

            Write-Log "系统命令 $cmd 不存在"

        }

    }

}



# 4) 一键安装向导

if (-not $py) {

    Write-Log "未找到 Python，调用一键安装向导"

    $installer = Join-Path $scriptDir "install_python.ps1"

    if (-not (Test-Path $installer)) {

        Write-Log "错误：找不到 install_python.ps1"

        Read-Host "按 Enter 键退出"

        exit 1

    }

    & powershell.exe -ExecutionPolicy Bypass -File "$installer"

    $installRet = $LASTEXITCODE

    Write-Log "install_python.ps1 返回: $installRet"

    if (Test-Path $pathFile) {

        $recorded = Get-Content $pathFile -Raw -Encoding utf8 -ErrorAction SilentlyContinue

        $recorded = $recorded.Trim()

        Write-Log "安装向导写入路径: $recorded"

        if ($recorded -and (Test-Path $recorded)) {

            $py = $recorded

        }

    }

}



if (-not $py) {

    Write-Log "错误：未能获取 Python"

    Write-Host ""

    Write-Host "未能获取 Python，迁移工具无法启动。"

    Write-Host ""

    Write-Host "方式一：自动安装（推荐）—— 重新双击 start.bat，按弹窗提示一键安装免安装版 Python（约 12MB，无需管理员权限）。"

    Write-Host ""

    Write-Host "方式二：手动安装 Python 3.8+："

    Write-Host "  1. 打开下载地址：https://www.python.org/downloads/"

    Write-Host "     （官网慢可用华为镜像：https://mirrors.huaweicloud.com/python/）"

    Write-Host "  2. 下载 Windows installer (64-bit)"

    Write-Host "  3. 安装时务必勾选 [Add python.exe to PATH]"

    Write-Host "  4. 安装完成后重新双击 start.bat，会自动检测到新装的 Python"

    Write-Host ""

    Write-Host "可能的原因："

    Write-Host "  - 一键安装向导被你关闭或取消"

    Write-Host "  - 安装向导下载失败（网络问题）"

    Write-Host "  - 你选择了无效的安装目录"

    Write-Host ""

    Read-Host "按 Enter 键退出"

    exit 1

}



Write-Log "使用 Python: $py"



# 查找可用端口

function Find-Port($basePort) {

    for ($p = $basePort; $p -lt $basePort + 20; $p++) {

        try {

            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)

            $listener.Start()

            $listener.Stop()

            return $p

        } catch {}

    }

    return $null

}



$port = Find-Port $Port

if (-not $port) {

    Write-Log "错误：无法找到可用端口"

    Read-Host "按 Enter 键退出"

    exit 1

}

$url = "http://127.0.0.1:$port"

Write-Log "本地服务地址: $url"



# 启动 server.py

$rootDir = Split-Path -Parent (Split-Path -Parent $scriptDir)
Write-Log "项目根目录: $rootDir"
$serverPy = Join-Path $rootDir "server.py"

Write-Log "启动本地服务..."



$psi = New-Object System.Diagnostics.ProcessStartInfo

$psi.FileName = $py

$psi.Arguments = '"' + $serverPy + '" ' + $port

$psi.WorkingDirectory = $rootDir

$psi.UseShellExecute = $false

$psi.CreateNoWindow = $true

$psi.RedirectStandardOutput = $true

$psi.RedirectStandardError = $true

$psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8

$psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8



$proc = [System.Diagnostics.Process]::Start($psi)



# 等待服务启动（用轻量 /api/ping 探活，不做目录扫描，秒级返回）

$started = $false

for ($i = 0; $i -lt 60; $i++) {

    Start-Sleep -Milliseconds 200

    try {

        $resp = Invoke-WebRequest -Uri "$url/api/ping" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop

        if ($resp.StatusCode -eq 200) {

            $started = $true

            break

        }

    } catch {}

}



if (-not $started) {

    Write-Log "错误：服务未能启动"

    if (-not $proc.HasExited) { $proc.Kill() }

    $err = $proc.StandardError.ReadToEnd()

    Write-Log "server.py 错误: $err"

    Write-Host ""

    Write-Host "服务未能启动，错误信息如下（如为空，请运行同目录 diagnose.bat 采集诊断信息）："

    Write-Host $err

    Write-Host ""

    Read-Host "按 Enter 键退出"

    exit 1

}



Write-Log "服务已启动"



# 打开浏览器

Start-Sleep -Milliseconds 500

try {

    Start-Process $url

    Write-Log "已打开浏览器: $url"

} catch {

    Write-Log "打开浏览器失败: $_"

    Write-Host "请手动在浏览器访问: $url"

}



Write-Log "工具运行中，关闭本窗口即退出"

Write-Host ""

Write-Host "========================================"

Write-Host "  WorkBuddy 迁移工具已启动"

Write-Host "  浏览器访问: $url"

Write-Host "  页面已自动在默认浏览器中打开"

Write-Host "  请勿关闭本命令行窗口（可最小化），"

Write-Host "  关闭本窗口 = 退出迁移工具"

Write-Host "========================================"

Write-Host ""



# 保持窗口开启，直到 server.py 退出

$proc.WaitForExit()

Write-Log "服务已退出"

Read-Host "按 Enter 键退出"

