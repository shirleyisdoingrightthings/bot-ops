#!/bin/bash
# report_base.sh — 各 Bot `claude_report.sh` 的共享实现
#
# 由各 bot 的 `claude_report.sh` 在设好以下变量后 `source` 调用：
#   DIR         Bot 根目录
#   PLIST       ~/Library/LaunchAgents 中权威 plist 路径（仅含环境变量与密钥）
#   SCRIPT      Python 主脚本文件名（位于 $DIR 下，如 daily_report.py）
#   USAGE_MSG   可选，参数错误时的提示文案
#   EXTRA_ARGS  可选数组，附加传给主脚本的参数（如 (--session premarket)）
#
# 密钥单一来源：运行前通过 PlistBuddy 从 $PLIST 动态注入环境变量，脚本本身零密钥。

set -uo pipefail
cd "${DIR:?必须先设置 DIR}" || exit 1

MODE="${1:-}"
if [ "$MODE" != "fetch" ] && [ "$MODE" != "send" ]; then
    echo "ERROR: 用法 ${USAGE_MSG:-claude_report.sh fetch|send}" >&2
    exit 2
fi

PY="${BOT_PYTHON:-/usr/bin/python3}"
if [ ! -f "${PLIST:?必须先设置 PLIST}" ]; then
    echo "ERROR: 找不到 $PLIST，无法加载环境变量" >&2
    exit 1
fi

while IFS= read -r line; do
    export "$line"
done < <(/usr/libexec/PlistBuddy -c "Print :EnvironmentVariables" "$PLIST" \
    | sed -n 's/^[[:space:]]*\([A-Za-z_][A-Za-z0-9_]*\) = \(.*\)$/\1=\2/p')

exec "$PY" "${SCRIPT:?必须先设置 SCRIPT}" --mode "$MODE" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
