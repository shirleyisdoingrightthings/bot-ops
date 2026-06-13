#!/bin/bash
# auto_repair_base.sh — 共享自愈逻辑（Crypto Daily Bot / AI Daily News Bot 共用）
#
# ⚠️ 本文件由 Claude 依据 health_check.sh / auto_repair.sh 的调用契约与
#    README.md / AGENTS.md 中描述的两级自愈流程重建（原件未进 GitHub 备份）。
#    若日后找到原始版本可直接覆盖。
#
# 由各 Bot 的 auto_repair.sh 薄包装在 `source` 之前设置好以下变量：
#   DIR        Bot 根目录（含 logs/run.log、changelog.md）
#   BOT_NAME   Bot 名称（macOS 通知用）
#   SCRIPT     主脚本绝对路径（重跑用）
#   ERROR      health_check 从 [FAIL] 行提取的失败原因
#
# 两级自愈：
#   Level 1（瞬时错误：网络/超时/代理/限流）→ 等 30s 直接重跑
#   Level 2（持续错误，或 L1 重跑仍失败）   → 调用 Claude CLI 诊断修复 → 重跑
# 结果：成功 → changelog 该条标记 [x]（待验证，连续 3 次 OK 后由 health_check 删除）
#       失败 → macOS 通知，人工介入

set -o pipefail

# 主脚本解释器：新机用系统 python3（无 Homebrew/python3.11）。
# 可用环境变量 BOT_PYTHON 覆盖。
PYTHON="${BOT_PYTHON:-/usr/bin/python3}"

# Level 2 总开关：0=关（只发通知喊人工）  1=开（让 Claude CLI 无人值守改代码并重跑）。
# 默认关；由 health plist 的 EnvironmentVariables 设 ENABLE_CLAUDE_REPAIR=1 打开。
ENABLE_CLAUDE_REPAIR="${ENABLE_CLAUDE_REPAIR:-0}"

# 解析 claude CLI 绝对路径（launchd 的 PATH 极简，不能依赖裸 `claude`）。
# 可用环境变量 CLAUDE_BIN 指定；否则在常见安装位置里探测。
if [ -z "${CLAUDE_BIN:-}" ]; then
    for _c in "$HOME/.local/bin/claude" "$HOME/.claude/local/claude" \
              /opt/homebrew/bin/claude /usr/local/bin/claude \
              "$(command -v claude 2>/dev/null)"; do
        if [ -n "$_c" ] && [ -x "$_c" ]; then CLAUDE_BIN="$_c"; break; fi
    done
fi
CLAUDE_BIN="${CLAUDE_BIN:-}"

LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"
REPAIR_LOG="$LOG_DIR/auto_repair.log"
RUN_LOG="$LOG_DIR/run.log"
CHANGELOG="$DIR/changelog.md"
TODAY="$(date '+%Y-%m-%d')"
SHORT="$(echo "$ERROR" | cut -c1-120)"

log()    { echo "$(date '+%Y-%m-%d %H:%M:%S')  $*" | tee -a "$REPAIR_LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"🛠️ ${BOT_NAME}\"" 2>/dev/null; }

# 把 changelog 中“含本次错误摘要”的 [ ]/[/] 条目改成指定标记（/=修复中, x=待验证）
mark_changelog() {
    [ -f "$CHANGELOG" ] || return 0
    "$PYTHON" - "$CHANGELOG" "$SHORT" "$1" <<'PY'
import sys, re
path, short, mark = sys.argv[1], sys.argv[2], sys.argv[3]
key = short[:40]
lines = open(path, encoding="utf-8").read().splitlines()
out, done = [], False
for ln in lines:
    if not done and key and key in ln and re.match(r"^- \[[ /]\]", ln):
        ln = re.sub(r"^- \[[ /]\]", f"- [{mark}]", ln, count=1)
        done = True
    out.append(ln)
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
}

# 重跑主脚本；今天出现 [OK] 视为成功
rerun() {
    log "重跑：$PYTHON \"$SCRIPT\""
    FORCE_RUN=1 "$PYTHON" "$SCRIPT" >>"$REPAIR_LOG" 2>&1
    if grep -q "$TODAY.*\[OK\]" "$RUN_LOG" 2>/dev/null; then
        return 0
    fi
    return 1
}

# 瞬时错误判定（网络/超时/代理/限流等可重试类）
is_transient() {
    echo "$ERROR" | grep -qiE \
      "time( |d )?out|timeout|connection|connect|network|网络|proxy|代理|temporar|rate.?limit|429|502|503|RequestException|SSLError|Max retries|ConnectionError|ReadTimeout|getaddrinfo|Remote end closed|unreachable|EOF occurred"
}

log "===== auto_repair 触发：${BOT_NAME} ====="
log "错误：$ERROR"
mark_changelog "/"          # 标记“修复中”

# ── Level 1：瞬时错误，等 30s 重跑 ──────────────────────────────
if is_transient; then
    log "判定为瞬时错误 → Level 1：等待 30s 后重跑"
    sleep 30
    if rerun; then
        log "✅ Level 1 重跑成功"
        mark_changelog "x"
        notify "瞬时故障已自愈（Level 1 重跑成功）"
        exit 0
    fi
    log "Level 1 重跑仍失败 → 升级 Level 2"
else
    log "判定为持续错误 → 直接进入 Level 2"
fi

# ── Level 2：调用 Claude CLI 诊断修复 ───────────────────────────
if [ "$ENABLE_CLAUDE_REPAIR" != "1" ]; then
    log "Level 2 已关闭（ENABLE_CLAUDE_REPAIR≠1）→ 跳过 AI 改码，转人工"
elif [ -z "$CLAUDE_BIN" ]; then
    log "Level 2 已开启，但本机未安装 claude CLI（只有桌面 App，无法被脚本调用）→ 转人工"
else
    log "Level 2：调用 Claude CLI 诊断修复（$CLAUDE_BIN）..."
    PROMPT="你是 ${BOT_NAME} 的自动修复代理。主脚本 ${SCRIPT} 今天运行失败。
失败原因（来自 logs/run.log 的 [FAIL] 行）：
${ERROR}

请严格遵循本目录 AGENTS.md 的「Auto-Repair 代理行为规范」：
1. 只做最小范围修复，不触碰任何修改禁区；
2. 不确定根因时选择 CANNOT_FIX，而不是盲目改动。
修复完成后只输出一行：FIX: <一行说明>  或  CANNOT_FIX: <原因>。"

    CLAUDE_OUT="$(cd "$DIR" && "$CLAUDE_BIN" -p "$PROMPT" --dangerously-skip-permissions 2>>"$REPAIR_LOG")"
    log "Claude 输出：$CLAUDE_OUT"

    if echo "$CLAUDE_OUT" | grep -q "^FIX:"; then
        log "Claude 报告已修复，重跑验证..."
        if rerun; then
            log "✅ Level 2 修复并重跑成功"
            mark_changelog "x"
            notify "已由 Claude 自动修复并恢复运行"
            exit 0
        fi
        log "修复后重跑仍失败"
    else
        log "Claude 未能修复（CANNOT_FIX 或无 FIX 标记）"
    fi
fi

# ── 升级人工介入 ───────────────────────────────────────────────
log "❌ 自愈失败，需人工介入"
notify "自动修复失败，请人工介入：${SHORT}"
exit 1
