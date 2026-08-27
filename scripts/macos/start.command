#!/usr/bin/env bash
# macOS 双击启动入口（会自动打开 Terminal）
cd "$(dirname "$0")" || exit 1
exec ./start.sh
