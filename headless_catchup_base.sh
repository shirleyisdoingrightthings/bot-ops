#!/bin/bash
# headless_catchup_base.sh — 共享无头补跑逻辑（Crypto Daily Bot / AI Daily News Bot 共用）
#
# 作用：当天没有成功出稿时，用本机 claude CLI 无人值守地完整补跑一次
#       （fetch → 写稿 → send），等价于在 Claude App 里手动点 Run Now。
# 触发方：
#   - health_check.sh 的 MISSING 分支（08:30 routine 当天根本没跑）
#   - auto_repair_base.sh 的最终失败分支（Level 1/2 自愈无效）
#
# 由各 Bot 的 claude_catchup.sh 薄包装在 `source` 之前设置好以下变量：
#   DIR         Bot 根目录（含 logs/run.log、claude_report.sh）
#   BOT_NAME    Bot 名称（macOS 通知用）
#   PLIST       ~/Library/LaunchAgents 主 plist 路径（加载代理/密钥）
#   WRITE_SPEC  写稿要求单行说明（prompt 文件 → 产物路径）
#
# 防重复保护：
#   - run.log 今天已有 [OK] → 直接退出，绝不重复推送
#   - 同一天只实际补跑一次（logs/.catchup_ran 戳记），避免多触发方叠加烧 token

set -uo pipefail

LOG_DIR="$DIR/logs"; mkdir -p "$LOG_DIR"
CATCHUP_LOG="$LOG_DIR/headless_catchup.log"
RUN_LOG="$LOG_DIR/run.log"
TODAY="$(date '+%Y-%m-%d')"

log()    { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" | tee -a "$CATCHUP_LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"🤖 ${BOT_NAME}\"" 2>/dev/null; }
ok_today() { grep -q "$TODAY.*\[OK\]" "$RUN_LOG" 2>/dev/null; }

# ── 今天已成功 → 不补跑（防重复推送）─────────────────────────────
if ok_today; then
    log "今天已有 [OK]，无需补跑"
    exit 0
fi

# ── 同一天只补跑一次 ─────────────────────────────────────────────
STAMP="$LOG_DIR/.catchup_ran"
if [ -f "$STAMP" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$TODAY" ]; then
    log "今天已触发过补跑，跳过（防重复）"
    exit 1
fi
echo "$TODAY" > "$STAMP"

# ── 加载代理/密钥（claude CLI 需走代理访问 API）──────────────────
# fetch/send 环节的环境变量由 claude_report.sh 自行加载，这里只为 CLI 本身。
if [ -f "$PLIST" ]; then
    while IFS= read -r line; do export "$line"; done < <(
        /usr/libexec/PlistBuddy -c "Print :EnvironmentVariables" "$PLIST" \
        | sed -n 's/^[[:space:]]*\([A-Za-z_][A-Za-z0-9_]*\) = \(.*\)$/\1=\2/p')
fi

# ── 解析 claude CLI 绝对路径（launchd 的 PATH 极简）──────────────
if [ -z "${CLAUDE_BIN:-}" ]; then
    for _c in "$HOME/.local/bin/claude" "$HOME/.claude/local/claude" \
              /opt/homebrew/bin/claude /usr/local/bin/claude \
              "$(command -v claude 2>/dev/null)"; do
        if [ -n "$_c" ] && [ -x "$_c" ]; then CLAUDE_BIN="$_c"; break; fi
    done
fi
if [ -z "${CLAUDE_BIN:-}" ]; then
    log "未找到 claude CLI，无法补跑"
    notify "无头补跑失败：未找到 claude CLI"
    exit 1
fi

# ── 无头补跑 ─────────────────────────────────────────────────────
log "===== 无头补跑触发：${BOT_NAME}（$CLAUDE_BIN）====="
PROMPT="你是 ${BOT_NAME} 的无头补跑代理。今天 08:30 的 Claude routine 未能成功出稿，请在本目录完成一次完整补跑：
1. bash claude_report.sh fetch 获取当日素材；
2. ${WRITE_SPEC}；
3. bash claude_report.sh send 推送；
4. 确认 logs/run.log 出现今天（${TODAY}）的 [OK] 行。
严格遵循本目录 AGENTS.md / CLAUDE.md 的全部规范与修改禁区，不要修改任何代码。完成后只输出一行：DONE 或 FAILED: <原因>。"

(cd "$DIR" && "$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions >>"$CATCHUP_LOG" 2>&1)

if ok_today; then
    log "✅ 无头补跑成功"
    notify "今日稿件已由无头补跑送达"
    exit 0
fi
log "❌ 无头补跑后仍无今天 [OK]，需人工介入"
notify "无头补跑失败，请人工处理"
exit 1
