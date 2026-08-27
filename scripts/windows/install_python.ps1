﻿﻿#Requires -Version 5.1
# WorkBuddy 迁移工具 - Python 一键安装脚本
# 当系统没有 Python 时，自动下载 embeddable 版 Python 到用户指定目录。
param(
    [string]$DefaultDir = (Join-Path $PSScriptRoot "python")
)

Add-Type -AssemblyName System.Windows.Forms

$title = "WorkBuddy 迁移工具"
$log = Join-Path $PSScriptRoot "install.log"
function Write-Log($msg) {
    $line = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8 -ErrorAction SilentlyContinue
}
Write-Log "install_python.ps1 启动"

# 再检查一遍，避免误触发
$hasPy = $false
foreach ($cmd in @("python", "py")) {
    Write-Log "探测命令: $cmd"
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        try {
            & $cmd -c "import sys; sys.exit(0)" | Out-Null
            $hasPy = $true
            Write-Log "找到可用命令: $cmd"
            break
        } catch {
            Write-Log "命令 $cmd 存在但无法运行: $_"
        }
    } else {
        Write-Log "命令 $cmd 不存在"
    }
}
if ($hasPy) {
    Write-Log "已有 Python，无需安装，退出"
    exit 0
}

Write-Log "未找到 Python，准备弹窗询问"

# 询问用户
$msg = "未检测到 Python。`n`nWorkBuddy 迁移工具需要 Python 3.8+ 才能运行。`n`n是否自动下载并安装一个免安装版 Python？`n（约 12MB，无需管理员权限）"
$ans = [System.Windows.Forms.MessageBox]::Show($msg, $title, "YesNo", "Question")
Write-Log "用户选择: $ans"
if ($ans -ne [System.Windows.Forms.DialogResult]::Yes) {
    exit 1
}

# 选择安装目录
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = "选择 Python 安装位置（推荐保持默认）"
$dialog.SelectedPath = $DefaultDir
$dialog.ShowNewFolderButton = $true
if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    Write-Log "用户取消选择目录"
    exit 1
}
$target = $dialog.SelectedPath
Write-Log "用户选择安装目录: $target"

# 创建目录
New-Item -ItemType Directory -Force -Path $target | Out-Null

# 下载 embeddable Python
$version = "3.13.12"
$urls = @(
    "https://www.python.org/ftp/python/$version/python-$version-embed-amd64.zip",
    "https://mirrors.huaweicloud.com/python/$version/python-$version-embed-amd64.zip"
)
$zip = Join-Path $target "python-embed.zip"
$ok = $false
foreach ($url in $urls) {
    Write-Log "尝试下载: $url"
    try {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($url, $zip)
        $ok = $true
        Write-Log "下载成功: $url"
        break
    } catch {
        Write-Log "下载失败 ${url}: $_"
    }
}
if (-not $ok) {
    [System.Windows.Forms.MessageBox]::Show(
        "自动下载失败，请检查网络后重试。`n`n也可以手动安装 Python 3.8+：`n1. 打开 https://www.python.org/downloads/（慢可换华为镜像 https://mirrors.huaweicloud.com/python/）`n2. 下载 Windows installer (64-bit)`n3. 安装时勾选 Add python.exe to PATH`n4. 重新双击 start.bat 即可自动检测",
        "下载失败", "OK", "Error") | Out-Null
    if (Test-Path $zip) { Remove-Item $zip -Force }
    exit 1
}

# 解压
Write-Log "开始解压到: $target"
try {
    Expand-Archive -Path $zip -DestinationPath $target -Force
    Remove-Item $zip -Force
    Write-Log "解压完成"
} catch {
    Write-Log "解压失败: $_"
    [System.Windows.Forms.MessageBox]::Show("解压失败：$_", "错误", "OK", "Error") | Out-Null
    exit 1
}

# 验证
$py = Join-Path $target "python.exe"
if (-not (Test-Path $py)) {
    Write-Log "验证失败: 未找到 $py"
    [System.Windows.Forms.MessageBox]::Show("解压后未找到 python.exe", "错误", "OK", "Error") | Out-Null
    exit 1
}
try {
    $ver = & $py --version 2>&1
    Write-Log "验证成功: $ver"
} catch {
    Write-Log "验证失败: python.exe 无法运行: $_"
    [System.Windows.Forms.MessageBox]::Show("python.exe 无法运行：$_", "错误", "OK", "Error") | Out-Null
    exit 1
}

# 记录路径，供 start.bat 下次直接使用
$pathFile = Join-Path $PSScriptRoot "python_path.txt"
$py | Set-Content -Path $pathFile -Encoding utf8 -NoNewline
Write-Log "已记录 Python 路径到 $pathFile"

[System.Windows.Forms.MessageBox]::Show("Python 已就绪：$target`n版本：$ver", "安装完成", "OK", "Information") | Out-Null
exit 0
