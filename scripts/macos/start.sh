#!/usr/bin/env bash
# WorkBuddy 迁移工具启动脚本（macOS / Linux）
# 用法：./scripts/macos/start.sh  或  ./scripts/linux/start.sh
# macOS 双击：请使用 scripts/macos/start.command

# 切换到项目根目录（本脚本位于 scripts/<platform>/）
cd "$(dirname "$0")/../.." || exit 1

# 探测 Python 3.8+
PYTHON=""
for cmd in python3 python "$HOME/.workbuddy/binaries/python/versions/3.13.12/bin/python3" \
           /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ver=$("$cmd" --version 2>&1 | awk '{print $2}')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 8 ]; then
            PYTHON=$cmd
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "未找到 Python 3.8+。"
    echo ""
    echo "macOS / Linux 建议安装方式："
    echo "  1. macOS 安装 Homebrew：https://brew.sh"
    echo "  2. 执行：brew install python3   （或 Linux: sudo apt install python3）"
    echo "  3. 重新运行本脚本"
    echo ""
    echo "或访问 https://www.python.org/downloads/ 下载安装。"
    echo ""
    read -rsp "按回车键退出..."
    exit 1
fi

echo "使用 Python: $PYTHON ($($PYTHON --version 2>&1))"

PORT=8765
URL="http://127.0.0.1:$PORT"

# 启动服务（工作目录为项目根目录）
"$PYTHON" server.py "$PORT" &
PID=$!

# 等待服务就绪
for i in $(seq 1 30); do
    if curl -s "$URL" >/dev/null 2>&1; then
        break
    fi
    sleep 0.3
done

# 打开浏览器
if command -v open >/dev/null 2>&1; then
    open "$URL"
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL"
fi

wait $PID
