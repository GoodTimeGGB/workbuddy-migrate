﻿﻿#Requires -Version 5.1
# WorkBuddy 迁移工具 - 诊断脚本

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Write-Host "================================================"
Write-Host "  WorkBuddy 迁移工具 - 启动诊断"
Write-Host "================================================"
Write-Host ""
Write-Host "[当前目录] $scriptDir"
Write-Host "[用户名]   $env:USERNAME"
Write-Host ""

$py = $null

# 记录路径
$pathFile = Join-Path $scriptDir "python_path.txt"
if (Test-Path $pathFile) {
    $recorded = Get-Content $pathFile -Raw -Encoding utf8 -ErrorAction SilentlyContinue
    $recorded = $recorded.Trim()
    Write-Host "[记录路径] $recorded"
    if ($recorded -and (Test-Path $recorded)) {
        $py = $recorded
        Write-Host "           该路径有效"
    } else {
        Write-Host "           该路径已失效"
    }
} else {
    Write-Host "[记录路径] 无"
}
Write-Host ""

# WorkBuddy 自带
$wbPy = "C:\Users\$env:USERNAME\.workbuddy\binaries\python\versions\3.13.12\python.exe"
Write-Host "[WorkBuddy 自带 Python] $wbPy"
if (Test-Path $wbPy) {
    try {
        $ver = & $wbPy --version 2>&1
        Write-Host "           找到，版本: $ver"
        if (-not $py) { $py = $wbPy }
    } catch {
        Write-Host "           存在但无法运行: $_"
    }
} else {
    Write-Host "           未找到"
}
Write-Host ""

# 系统命令
foreach ($cmd in @("python", "py")) {
    Write-Host "[系统命令] $cmd"
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        try {
            $ver = & $cmd --version 2>&1
            Write-Host "           可用，版本: $ver"
            if (-not $py) { $py = $cmd }
        } catch {
            Write-Host "           存在但无法运行: $_"
        }
    } else {
        Write-Host "           不可用"
    }
}
Write-Host ""

if (-not $py) {
    Write-Host "[结论] 未找到任何可用 Python。"
    Write-Host "       请双击 start.bat，按提示一键安装。"
} else {
    Write-Host "[结论] 将使用: $py"
    Write-Host ""
    $serverPy = Join-Path $rootDir "server.py"
    Write-Host "[检查 server.py] $serverPy"
    if (Test-Path $serverPy) {
        try {
            Push-Location $rootDir
            & $py -c "import server; print('server.py 导入成功')" 2>&1
            Pop-Location
        } catch {
            Write-Host "server.py 导入失败: $_"
        }
    } else {
        Write-Host "server.py 不存在"
    }
}

Write-Host ""
Write-Host "如果仍无法启动，请把本窗口完整内容截图反馈。"
Read-Host "按 Enter 键退出"
