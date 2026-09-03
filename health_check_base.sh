#!/bin/bash
# health_check_base.sh — 各 bot 体检脚本的公共实现
#
# 由各 bot 的 health_check.sh 薄封装 source，与 auto_repair_base.sh /
# headless_catchup_base.sh 同一套路。
#
# ── 为什么要抽出来（2026-09-03）───────────────────────────────────────
# 抽之前 5 个 bot 各有一份 221 行的 health_check.sh，两两只差 18~27 行，
# 也就是约 1100 行里有 1000 行是复制粘贴。代价已经付过三次：
#   · 「缺跑告警不再重推历史日期」这一处修改，要在 4 个文件里各改一遍；
#   · x-hotspot 的终态标记写成了「无有效新闻」，而它的脚本实际写的是
#     「没抓到可用素材」——对不上，于是正常终态被判成缺跑，白派无头补跑；
#   · x-hotspot 的第 5 节读 rss_stale_sources，而它实际写的是 stale_sources，
#     导致它的零产告警从上线起就从未触发过。
# 三个都是"复制过来忘了改"。抽成公共层后，这类差异必须在封装里显式声明，
# 漏了会直接报错而不是静默失效。
#
# ── 封装需要提供的变量 ───────────────────────────────────────────────
# 必填：
#   BOT_NAME          告警标题里的 bot 名，例：AI Daily News Bot
#   MAIN_PLIST        主 plist 绝对路径（只从中取 FEISHU_* 键）
#   NO_NEWS_PATTERN   终态 WARN 的 grep 模式，必须与脚本 write_log 的实际措辞一致
#   NO_NEWS_MSG       终态 WARN 的通知正文
# 选填：
#   STALE_KEY         run.jsonl 里"连续零产源"的键名；留空则跳过第 5 节
#   ZERO_KEY          run.jsonl 里"今日零产源"的键名；留空则跳过
#   content_check()   第 4 节的内容质量校验，各 bot 查各自的指标；未定义则跳过
#
# 封装里 source 本文件之前必须先设好 DIR（bot 目录绝对路径）。

set -uo pipefail

: "${DIR:?封装必须先设 DIR}"
: "${BOT_NAME:?封装必须先设 BOT_NAME}"
: "${MAIN_PLIST:?封装必须先设 MAIN_PLIST}"
: "${NO_NEWS_PATTERN:?封装必须先设 NO_NEWS_PATTERN（须与脚本 write_log 的实际措辞一致）}"
: "${NO_NEWS_MSG:?封装必须先设 NO_NEWS_MSG}"
STALE_KEY="${STALE_KEY:-}"
ZERO_KEY="${ZERO_KEY:-}"

LOG="$DIR/logs/run.log"
JSONL="$DIR/logs/run.jsonl"
CHANGELOG="$DIR/changelog.md"
OK_COUNT_FILE="$DIR/logs/.ok_streak"
TODAY=$(date '+%Y-%m-%d')
HOUR=$(date '+%H'); HOUR=${HOUR#0}; HOUR=${HOUR:-0}
ALERT_PY="$DIR/../shared/alert.py"

# 无头补跑的时间窗。RunAtLoad 打开后，本脚本会在每次开机/登录时也跑一遍，
# 没有这个窗口就会出现两种误触发：
#   · 早上 8 点开机 → 10:00 的 routine 还没到点，却被判成"今天没跑"而抢先补跑
#   · 深夜 23 点开机 → 补出一份当天已经没人看的稿子，白烧 token
# 窗口外只通知、不补跑。10:00 的 routine + 11:00 的定时体检都落在窗口内。
CATCHUP_FROM=${CATCHUP_FROM:-11}
CATCHUP_UNTIL=${CATCHUP_UNTIL:-20}
# 缺跑回看天数：只用来"告诉你哪几天彻底没跑"，不触发任何补救动作，也不推送告警
MISSED_LOOKBACK=${MISSED_LOOKBACK:-7}

# ── 0. 告警通道：桌面通知 + 飞书 ─────────────────────────────────────
# 桌面通知只在人坐在电脑前时有效。2026-08-30 查出三个 health job 因 EX_CONFIG
# 连续 11 天没跑成，而唯一的告警渠道恰好也是最看不见的那个——故障本身把报警器
# 一起带走了。飞书是已经在手的送达渠道，这里让每条告警同时走两边。
#
# 只从主 plist 取 FEISHU_* ——那里还放着 PATH 等键，整份 export 会覆盖体检
# 自己的 PATH，进而影响 claude_catchup 找 claude 可执行文件。
# 运维消息分流到监测群靠主 plist 里的 FEISHU_ALERT_WEBHOOK（见 alert.py）。
if [ -f "$MAIN_PLIST" ]; then
    while IFS= read -r kv; do export "$kv"; done < <(
        /usr/libexec/PlistBuddy -c "Print :EnvironmentVariables" "$MAIN_PLIST" 2>/dev/null \
        | sed -n 's/^[[:space:]]*\(FEISHU[A-Z_]*\) = \(.*\)$/\1=\2/p')
fi

# notify <FAIL|WARN|INFO> <正文>
notify() {
    local level="$1" msg="$2" icon
    case "$level" in
        FAIL) icon="🔴" ;;
        WARN) icon="⚠️" ;;
        *)    icon="ℹ️" ;;
    esac
    osascript -e "display notification \"$msg\" with title \"$icon $BOT_NAME\"" 2>/dev/null
    # 告警发不出去是小事，让体检因此中断是大事，故整条容错
    [ -f "$ALERT_PY" ] && /usr/bin/python3 "$ALERT_PY" "$BOT_NAME" "$level" "$msg" 2>&1 \
        | grep -v NotOpenSSLWarning | grep -v "warnings.warn" || true
    return 0
}

# 从今天最后一条 jsonl 记录里取一个字段，取不到返回默认值。供 content_check 用。
# 用法：jsonl_field <键名> [默认值]
jsonl_field() {
    local key="$1" default="${2:-}"
    [ -f "$JSONL" ] || { echo "$default"; return 0; }
    grep "$TODAY" "$JSONL" | tail -1 | /usr/bin/python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    v = d.get('$key')
    print(v if v is not None else '''$default''')
except Exception:
    print('''$default''')
" 2>/dev/null
}

# ── 1. 检查 run.log 是否存在 ─────────────────────────────────────────
if [ ! -f "$LOG" ]; then
    notify FAIL "run.log 不存在，脚本可能从未运行"
    exit 1
fi

# ── 1.5 缺跑扫描：最近 N 天里哪几天 run.log 一行记录都没有 ────────────
# 「一行都没有」= 那天机器没开 / 进程压根没起来，与「跑了但跳过」（WARN 有记录）
# 是两回事。这类静默缺失过去无人知晓：2026-08-28、08-29 两天全丢，直到 08-30
# 写周回顾时才从存档少了两份发现。这里只做告知，不做补救——过期的日报没有补的意义。
#
# ⚠️ 2026-09-03：这一段**只写本地日志，不再推送告警**。原来它每天把整个 7 天窗口
# 里的缺跑日期推一遍，同一批旧日期（08-28、08-29）会连推 7 天才滚出窗口，读起来
# 像「今天又出问题了」，而当天其实跑得好好的。当天缺跑不需要靠这里发现——下面
# 第 2/3 节的 MISSING 分支本来就会在补跑窗口内发一条「今天主脚本未运行」。
# 所以这里保留扫描（排查时看 health_check.log 仍能知道哪几天丢了），去掉推送。
# 不要因为「历史缺跑没人告诉我」把 notify 加回来——要加也只加当天那一天。
MISSED=""
for i in $(seq 1 "$MISSED_LOOKBACK"); do
    D=$(date -v-"${i}"d '+%Y-%m-%d' 2>/dev/null) || break
    grep -q "^$D" "$LOG" || MISSED="$D${MISSED:+, }$MISSED"
done
if [ -n "$MISSED" ]; then
    echo "[health_check] 缺跑（仅本地记录，不推送）：最近 $MISSED_LOOKBACK 天内这些日期无任何运行记录 — $MISSED"
fi

# ── 2. 判断今天的运行状态（基于日期，而不是 tail -1）────────────────
get_today_status() {
    if grep -q "$TODAY.*\[OK\]" "$LOG"; then
        echo "OK"
    elif grep -q "$TODAY.*\[FAIL\]" "$LOG"; then
        echo "FAIL"
    elif grep -q "$TODAY.*\[WARN\].*$NO_NEWS_PATTERN" "$LOG"; then
        # 终态 WARN：当天确实没有值得播的东西，不是故障。
        # 补跑也只会再抓一次同样的空结果，白烧 token 还弹"需人工介入"。
        # 注意：代理不可用 / 行情数据缺失这两类 WARN 不在此列——它们是暂时性的，
        # 到体检时刻可能已恢复，仍按 MISSING 处理以触发补跑。
        # ⚠️ NO_NEWS_PATTERN 必须与脚本 write_log 里的实际措辞一致，对不上就会
        # 把正常终态误判成缺跑、白派一次补跑（x-hotspot 踩过这个坑）。
        echo "NO_NEWS"
    else
        echo "MISSING"
    fi
}

STATUS=$(get_today_status)

# 若今天无记录，等待 60s 再判一次（应对补跑竞态：脚本可能仍在运行中）
if [ "$STATUS" = "MISSING" ]; then
    echo "[health_check] 今天暂无运行记录，等待 60s 后重判（可能为补跑中）..."
    sleep 60
    STATUS=$(get_today_status)
fi

# ── 3. 根据状态分支处理 ───────────────────────────────────────────────
if [ "$STATUS" = "FAIL" ]; then
    ERR_LINE=$(grep "$TODAY.*\[FAIL\]" "$LOG" | tail -1)
    ERR=$(echo "$ERR_LINE" | sed 's/.*\[FAIL\]  //')
    SHORT=$(echo "$ERR" | cut -c1-120)
    TS=$(echo "$ERR_LINE" | cut -c1-16)

    if [ ! -f "$CHANGELOG" ]; then
        {
            echo "# Changelog — $BOT_NAME"
            echo ""
            echo "> 格式：[ ] 待处理 · [/] 修复中 · [x] 待验证（连续3次OK后自动删除）"
            echo ""
        } > "$CHANGELOG"
    fi
    if ! tail -10 "$CHANGELOG" | grep -qF "$SHORT"; then
        echo "- [ ] \`$TS\` $SHORT" >> "$CHANGELOG"
    fi

    echo "0" > "$OK_COUNT_FILE"
    echo "[health_check] FAIL 检测到，触发 auto_repair..."
    echo "[health_check] FAIL — $ERR_LINE"
    # 前台执行：launchd 在 job 主进程退出时会回收整个进程组，
    # 用 `&` 起的后台子进程会被立即杀掉（2026-07-23 修复）
    bash "$DIR/auto_repair.sh" "$ERR"
    exit 2

elif [ "$STATUS" = "MISSING" ]; then
    # 等待 60s 后仍无记录：10:00 routine 今天未运行（机器睡眠 / App 未开等）
    # → 触发无头补跑（自动版 Run Now），由 claude CLI 完整重走 fetch → 写稿 → send
    if [ "$HOUR" -lt "$CATCHUP_FROM" ] || [ "$HOUR" -ge "$CATCHUP_UNTIL" ]; then
        # 窗口外（多半是 RunAtLoad 在清早或深夜触发的这一次）：不补跑，只留一行记录。
        # 清早不补是因为 10:00 的 routine 还没轮到；深夜不补是因为稿子已经没人看。
        echo "[health_check] 今天（$TODAY）无运行记录，但当前 ${HOUR} 点不在补跑窗口 ${CATCHUP_FROM}-${CATCHUP_UNTIL} 点内，跳过补跑"
        exit 0
    fi
    notify WARN "今天主脚本未运行，已触发无头补跑"
    echo "[health_check] WARN: 今天（$TODAY）无任何运行记录，触发无头补跑..."
    # 前台执行，理由同 auto_repair 分支（launchd 进程组回收）
    bash "$DIR/claude_catchup.sh"
    exit 1
fi

if [ "$STATUS" = "NO_NEWS" ]; then
    # 正常终态：不补跑、不自愈、不计入 OK streak
    notify INFO "$NO_NEWS_MSG"
    echo "[health_check] NO_NEWS: 今天（$TODAY）$NO_NEWS_MSG，属正常终态，不触发补跑"
    exit 0
fi

# ── 4. 今天 OK：内容质量校验（各 bot 查各自的指标）───────────────────
if declare -F content_check >/dev/null; then
    content_check
fi

# ── 5. 分源监控：读取 fetch 阶段算好的"连续零产"结论 ──────────────
# 连续天数由各 *_report.py 的 fetch 单点维护（logs/.zero_streak.json），
# 这里只读不写——两处各加一次会让天数翻倍。
# 单一素材源的 bot（如 ai-builder）没有零产概念，封装里不设 STALE_KEY 即跳过。
if [ -n "$STALE_KEY" ] && [ -f "$JSONL" ]; then
    STALE=$(grep "$TODAY" "$JSONL" | tail -1 | /usr/bin/python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    st = d.get('$STALE_KEY', {}) or {}
    print(', '.join(f'{k}({v}天)' for k, v in sorted(st.items())))
except Exception: print('')
" 2>/dev/null)
    if [ -n "$STALE" ]; then
        notify WARN "素材源连续零产，建议移除：$STALE"
        echo "[health_check] WARN: 源连续零产，建议移除或更换: $STALE"
    fi
fi

if [ -n "$ZERO_KEY" ] && [ -f "$JSONL" ]; then
    ZERO_TODAY=$(grep "$TODAY" "$JSONL" | tail -1 | /usr/bin/python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    print(','.join(d.get('$ZERO_KEY', []) or []))
except Exception: print('')
" 2>/dev/null)
    if [ -n "$ZERO_TODAY" ]; then
        echo "[health_check] INFO: 今日零产源（未达连续 3 天，暂不告警）: $ZERO_TODAY"
    fi
fi

# ── 6. 更新 OK streak，核销 changelog ────────────────────────────────
STREAK=0
if [ -f "$OK_COUNT_FILE" ]; then
    STREAK=$(cat "$OK_COUNT_FILE")
fi
STREAK=$((STREAK + 1))
echo "$STREAK" > "$OK_COUNT_FILE"

OK_LINE=$(grep "$TODAY.*\[OK\]" "$LOG" | tail -1)
echo "[health_check] OK (streak=$STREAK) — $OK_LINE"

if [ "$STREAK" -ge 3 ] && [ -f "$CHANGELOG" ]; then
    BEFORE=$(wc -l < "$CHANGELOG")
    grep -v "^\- \[x\]" "$CHANGELOG" > "$CHANGELOG.tmp" && mv "$CHANGELOG.tmp" "$CHANGELOG"
    AFTER=$(wc -l < "$CHANGELOG")
    REMOVED=$((BEFORE - AFTER))
    if [ "$REMOVED" -gt 0 ]; then
        echo "[health_check] 已核销 $REMOVED 条已修复条目"
        echo "0" > "$OK_COUNT_FILE"
    fi
fi

exit 0
