#!/bin/bash
# auto_repair_base.sh — 共享自愈逻辑（Crypto Daily Bot / AI Daily News Bot 共用）
#
# 2026-07-20 从 ~/Desktop/bot_ops/auto_repair_base.sh 迁入 ~/Desktop/bots/shared/ 并修复：
#   1. rerun() 原来裸跑 `python3 <script>` —— 缺必填的 --mode 参数、也不加载
#      plist 环境变量（无 token/代理），重跑必然失败。现改为走 claude_report.sh send。
#   2. 新增 drafts_fresh() 稿件新鲜度检查：稿件是 Claude 写的，重跑补不了稿；
#      当天稿件缺失/过期时直接跳过 L1/L2，转无头补跑，避免把旧稿重复发出去。
#   3. 新增最终兜底：L1/L2 都失败后调用 claude_catchup.sh 无头补跑，之后才转人工。
#
# 由各 Bot 的 auto_repair.sh 薄包装在 `source` 之前设置好以下变量：
#   DIR        Bot 根目录（含 logs/run.log、changelog.md、claude_report.sh）
#   BOT_NAME   Bot 名称（macOS 通知用）
#   SCRIPT     主脚本绝对路径（Level 2 提示词用）
#   ERROR      health_check 从 [FAIL] 行提取的失败原因
#   DRAFTS     当日稿件相对路径列表（空格分隔），用于新鲜度检查
#
# 两级自愈 + 最终兜底：
#   Level 1（瞬时错误：网络/超时/代理/限流）→ 等 30s 重跑 send
#   Level 2（持续错误，或 L1 重跑仍失败）   → 调用 Claude CLI 诊断修复 → 重跑 send
#   最终兜底                                → claude_catchup.sh 无头补跑（完整重走 fetch→写稿→send）
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

# 检查今日稿件是否可用：DRAFTS 中每个文件都存在、非空、且当天修改过。
# 稿件是 Claude 写的，重跑补不了稿；不新鲜时重跑 send 会把旧稿重复发出去，必须拦住。
drafts_fresh() {
    [ -n "${DRAFTS:-}" ] || return 1
    local f
    for f in $DRAFTS; do
        [ -s "$DIR/$f" ] || return 1
        [ "$(date -r "$DIR/$f" '+%Y-%m-%d')" = "$TODAY" ] || return 1
    done
    return 0
}

# 重跑发送环节；今天出现 [OK] 视为成功。
# 走 claude_report.sh 以复用 plist 环境变量加载（裸跑 python 拿不到 token/代理）；
# 只重跑 send：进入 L1/L2 前已由 drafts_fresh 确认当天稿件在手。
rerun() {
    log "重跑：bash claude_report.sh send"
    bash "$DIR/claude_report.sh" send >>"$REPAIR_LOG" 2>&1
    grep -q "$TODAY.*\[OK\]" "$RUN_LOG" 2>/dev/null
}

# 瞬时错误判定（网络/超时/代理/限流等可重试类）
is_transient() {
    echo "$ERROR" | grep -qiE \
      "time( |d )?out|timeout|connection|connect|network|网络|proxy|代理|temporar|rate.?limit|429|502|503|RequestException|SSLError|Max retries|ConnectionError|ReadTimeout|getaddrinfo|Remote end closed|unreachable|EOF occurred"
}

log "===== auto_repair 触发：${BOT_NAME} ====="
log "错误：$ERROR"
mark_changelog "/"          # 标记“修复中”

if ! drafts_fresh; then
    log "今日稿件缺失或过期（DRAFTS=${DRAFTS:-未配置}），重跑 send 无意义 → 跳过 L1/L2，直接转无头补跑"
else
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
        log "Level 2 已关闭（ENABLE_CLAUDE_REPAIR≠1）→ 跳过 AI 改码"
    elif [ -z "$CLAUDE_BIN" ]; then
        log "Level 2 已开启，但本机未安装 claude CLI（只有桌面 App，无法被脚本调用）"
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
fi

# ── 最终兜底：无头补跑（完整重走 fetch → 写稿 → send）──────────
if [ -f "$DIR/claude_catchup.sh" ]; then
    log "最终兜底：触发无头补跑（claude_catchup.sh）..."
    if bash "$DIR/claude_catchup.sh" >>"$REPAIR_LOG" 2>&1; then
        log "✅ 无头补跑成功"
        mark_changelog "x"
        notify "L1/L2 未修复，已由无头补跑完成今日推送"
        exit 0
    fi
    log "无头补跑仍失败"
fi

# ── 升级人工介入 ───────────────────────────────────────────────
log "❌ 自愈失败，需人工介入"
notify "自动修复失败，请人工介入：${SHORT}"
exit 1
