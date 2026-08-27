# WorkBuddy 迁移工具

在两台电脑之间迁移 WorkBuddy 的任务和空间数据（公司电脑 ⇄ 家里笔记本）。

> **免责声明**：本工具为个人开发的第三方开源工具（MIT License），非 WorkBuddy 官方出品，与腾讯/WorkBuddy 团队无关联。请在导入前确认已做好数据备份；因使用本工具造成的任何数据问题由使用者自行承担。导出包内含你的对话与任务数据，请通过可信渠道传输并妥善保管。

工具把选中空间的**注册信息、会话、任务、文件内容**（可选含完整对话记录）打包成一个 zip 文件，
通过网盘 / 邮件 / U 盘传到另一台电脑后再导入。导入前有完整预览与自动备份，任何情况下不会删除目标电脑的已有数据。

## 环境要求

- Windows 10/11 + Python 3.8 及以上
- macOS 11+ + Python 3.8 及以上
- Linux + Python 3.8 及以上

工具仅用 Python 标准库，无需安装任何第三方包。

Python 下载地址：https://www.python.org/downloads/ （官网慢可用华为镜像 https://mirrors.huaweicloud.com/python/ ；Windows 安装时勾选 *Add python.exe to PATH*）

## 重要：必须这样启动

**不要直接双击 `web/index.html`！** 这个页面需要本地服务器提供数据接口。

### Windows

打开工具所在文件夹，**双击 `scripts/windows/start.bat`**。`start.bat` 会调用 `scripts/windows/launch.ps1` 启动本地服务并自动打开默认浏览器。使用期间请**保持黑窗口开启（可最小化）**，关闭窗口即退出工具。

> 首次打开页面会显示「正在扫描本机空间与文件大小」，空间较多或目录较大时需要十几秒到一分钟，页面会自动刷新，无需操作。

### macOS

打开工具所在文件夹，**双击 `scripts/macos/start.command`**。如果这是第一次运行，系统可能会提示“无法打开”，请在 Terminal 中执行一次：

```bash
chmod +x scripts/macos/start.command scripts/macos/start.sh
```

之后即可正常双击启动。Terminal 窗口会保持开启，关闭窗口即退出工具。

### Linux

在终端中进入工具所在目录，执行：

```bash
./scripts/linux/start.sh
# 或 macOS 终端
./scripts/macos/start.sh
```

### 没有 Python 怎么办？

#### Windows

`scripts/windows/launch.ps1` 会自动按以下顺序找 Python：
1. 之前一键安装的记录（`python_path.txt`）
2. WorkBuddy 自带的 Python
3. 系统 PATH 里的 `py` / `python`

如果都没有找到，会**弹窗询问你是否自动安装一个免安装版 Python**（约 12MB，无需管理员权限）。你只需要：
- 点「是」
- 选择一个安装目录（默认即可）
- 等待下载解压完成

安装完成后工具会自动继续启动，下次无需重复安装。

如果自动下载失败（网络问题），可以手动安装：
1. 打开 https://www.python.org/downloads/ （慢可换华为镜像 https://mirrors.huaweicloud.com/python/ ）
2. 下载 Windows installer (64-bit)
3. 安装时**务必勾选 Add python.exe to PATH**
4. 重新双击 `start.bat`，会自动检测到新装的 Python

#### macOS / Linux

`scripts/macos/start.sh`（macOS）或 `scripts/linux/start.sh`（Linux） 会按以下顺序找 Python 3.8+：
1. `python3`
2. `python`
3. `~/.workbuddy/binaries/python/versions/3.13.12/bin/python3`
4. Homebrew 常见路径（`/usr/local/bin/python3`、`/opt/homebrew/bin/python3`）

如果都没有找到，会提示安装方式：

```bash
# macOS（推荐用 Homebrew）
brew install python3

# Ubuntu/Debian
sudo apt update && sudo apt install python3

# Fedora/RHEL
sudo dnf install python3
```

安装后重新运行启动脚本即可。

### 启动异常排查

如果双击 `scripts/windows/start.bat` 后黑窗口一闪而过：
1. **先看 `start.log`**：`scripts/windows/launch.ps1` 会把启动过程写到同目录的 `start.log`，闪退后把该文件内容截图反馈。
2. **运行 `scripts/windows/diagnose.bat`**：它会调用 `scripts/windows/diagnose.ps1` 检测所有 Python 来源并输出结论，把窗口内容截图反馈。

常见原因：
- 电脑没有安装 Python，且 WorkBuddy 自带 Python 不在预期路径；
- 一键安装向导弹窗被你关闭/取消，或网络问题导致下载失败；
- 杀毒软件/防火墙拦截了本地 8765 端口；
- 同时打开了多个迁移工具窗口导致端口冲突（工具会自动换端口，黑窗口会显示实际地址）。

**注意**：不要直接双击 `scripts/windows/launch.ps1`、`scripts/windows/install_python.ps1`、`scripts/windows/diagnose.ps1`，也不要把它们的代码贴到 CMD 里运行。这些 `.ps1` 文件必须通过 `start.bat` / `scripts/windows/diagnose.bat` 调用。

## 使用步骤

### 旧电脑：导出

1. 双击 `scripts/windows/start.bat`（浏览器会自动打开工具页面）
2. 在「导出」页勾选要迁移的空间
3. 如需连完整对话记录一起迁移，勾选「包含完整对话记录」
4. **指定导出位置**：「导出保存到」默认是 `桌面\workbuddy-export\`，你可以：
   - 直接在输入框里修改路径；
   - 点击「浏览…」按钮，在弹出的系统文件夹对话框里选择（如 D 盘、网盘同步文件夹等）。
5. 点击「开始导出」，完成后页面显示文件位置
6. 把生成的 `workbuddy-export-日期.zip` 通过网盘 / 邮件发送

### 新电脑：导入

1. 把整个 `workbuddy-migrate` 文件夹拷到新电脑（U 盘或网盘均可），双击 `scripts/windows/start.bat`
2. 切到「导入」页，把 zip 文件拖入上传区
3. 核对预览：
   - 每个空间的源路径 → 本机写入路径（用户名不同会自动重写）
   - 与本机冲突的项目会标注「本机已存在」
   - 传输损坏的文件会标红，导入时自动跳过
4. 选择去重策略：
   | 策略 | 行为 |
   |---|---|
   | 智能合并（推荐） | 双方取并集，冲突保留较新版本，不删除本机内容 |
   | 跳过已存在 | 本机已有的完全不动，只补充没有的 |
   | 覆盖同名 | 同名项以导出包版本替换（不删本机多余文件，覆盖前自动备份） |
5. 点击「开始导入」并确认。完成后显示统计（成功数、跳过数、失败明细）
6. 启动 WorkBuddy，从空间列表打开导入的空间文件夹即可

## 数据安全说明

- **导入前自动备份**：数据库、将被改动的任务与文件会备份到 `~\.workbuddy\migrate-backup\时间戳\`
- **不删除**：三种策略均不会删除目标电脑上的任何已有数据
- **校验**：导出时每个空间生成 SHA256 清单，导入时逐一复算，损坏文件跳过并报告
- **原子写入**：文件先写临时名再改名，中断后可安全重跑
- **导入时需退出 WorkBuddy**：工具会检测并阻止在 WorkBuddy 运行时导入（导出不受限）

## 常见问题

**Q: 页面一直显示「正在扫描本机空间」**
正常的首次扫描——工具在统计每个空间的文件数和大小，空间多、目录大时需要几十秒。页面会自动刷新出结果，期间请保持黑窗口开启。

**Q: 页面提示「无法连接到本地服务器 (Failed to fetch)」**
启动工具的黑窗口被关闭了，或服务没启动成功。重新双击 `start.bat`，保持黑窗口开启（可最小化），再刷新页面。

**Q: 导入时提示 "检测到 WorkBuddy 正在运行"**
完全退出 WorkBuddy（包括系统托盘图标）后重试。

**Q: 提示 zip 损坏 / 条目数不符**
通常是传输不完整，重新下载/发送导出包再试。可对比页面显示的 SHA256 与源机器是否一致。

**Q: 两台电脑用户名不同，路径怎么办？**
工具会自动把源机器的 `<用户目录>\WorkBuddy` 前缀重写为本机路径，预览页可见重写结果。

**Q: 可以跨系统迁移吗？比如公司 Windows 导出、导入到家里 Mac？**
可以。导出包会记录源机器系统；导入时自动把路径前缀重写为本机系统的风格（如 `C:\Users\你\WorkBuddy\空间A` → `/Users/你/WorkBuddy/空间A`），对话记录归档文件夹也按本机规则生成。导入预览页会显示来源与本机的系统徽标及跨系统提示；个别文件名不符合本机系统规范时（极少见）会跳过并计入失败清单，不影响其余数据。

**Q: 导入后 WorkBuddy 里看不到空间？**
导入的是数据本身；在 WorkBuddy 的空间列表中打开对应文件夹（预览页显示的"本机路径"）即可。

## 目录结构

```
workbuddy-migrate/
├── scripts/
│   ├── windows/
│   │   ├── start.bat              # Windows 双击启动
│   │   ├── launch.ps1             # Windows 启动器（由 start.bat 调用）
│   │   ├── install_python.ps1     # Windows 一键安装 Python
│   │   ├── diagnose.bat           # Windows 诊断入口
│   │   └── diagnose.ps1           # Windows 诊断脚本
│   ├── macos/
│   │   ├── start.command          # macOS 双击启动
│   │   └── start.sh               # macOS 终端启动
│   └── linux/
│       └── start.sh               # Linux 终端启动
├── server.py                      # 服务入口（也可: python server.py [端口]）
├── paths.py                         # 路径发现与重写（兼容 Windows / macOS / Linux）
├── db.py                            # 数据库读写
├── archive.py                       # 打包/校验/安全解压
├── exporter.py                      # 导出逻辑
├── importer.py                      # 导入逻辑
├── jobs.py                          # 后台任务与进度
└── web/index.html                   # 界面
```
