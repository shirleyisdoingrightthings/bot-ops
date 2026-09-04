#!/bin/bash
# ai_chain_health.sh — AI 三块内容的串行体检 / 补跑调度
#
# 为什么要有这个文件：
# 产业日报、X 热点、AI Builder 共用同一个飞书 webhook（群里显示为同一个机器人），
# 所以它们的补跑必须串行且顺序固定：产业日报 → X 热点 → AI Builder。
# 顺序不是审美问题——x-hotspot 和 ai-builder 的 prompt.md 都要求「先写完前一块，
# 主动避开已经播过的题」，顺序反了就会撞题；群里的阅读顺序也会乱。
#
# 2026-09-04 之前的状况：五个 health_check 各挂一个 plist，全部 11:00 同时触发。
# launchd 不保证同时刻 job 的启动顺序，三块并发跑各自的无头补跑，谁先跑完谁先发。
# 当天实际发出的顺序是 AI Builder(11:18) → 产业日报(11:35)，正好反了。
# 并发还有第二个坏处：三个 claude CLI 同时开工会互相挤，9/01 和 9/02 的补跑
# 都倒在 "You've hit your session limit" 上，整块失败。串行一并解决这两件事。
#
# crypto / us-stock 是独立机器人、独立 webhook，不进这条链，仍各自 11:00 触发。

set -u

BOTS_DIR="/Users/jialiwu/Desktop/bots"

# ⚠️ 顺序即语义，不要调换。
CHAIN=(
    "AI Daily News Bot"
    "x-hotspot-bot"
    "ai-builder-bot"
)

# 单块上限。实测一次无头补跑 6~17 分钟，给到 25 分钟；超时就杀掉进入下一块——
# 否则一块卡死会把后面两块全饿死，那还不如并发。
BLOCK_TIMEOUT=${BLOCK_TIMEOUT:-1500}

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "$(ts)  ===== AI 三块串行体检开始 ====="
for name in "${CHAIN[@]}"; do
    script="$BOTS_DIR/$name/health_check.sh"
    if [ ! -f "$script" ]; then
        echo "$(ts)  ❌ 找不到 $script，跳过这一块"
        continue
    fi

    echo "$(ts)  --- $name 开始 ---"
    bash "$script" &
    pid=$!

    waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$waited" -ge "$BLOCK_TIMEOUT" ]; then
            echo "$(ts)  ⏱ $name 超过 ${BLOCK_TIMEOUT}s 未结束，终止后继续下一块"
            kill -TERM "$pid" 2>/dev/null
            sleep 5
            kill -KILL "$pid" 2>/dev/null
            break
        fi
        sleep 5
        waited=$((waited + 5))
    done

    wait "$pid" 2>/dev/null
    rc=$?
    # health_check 的退出码是「状态」不是「错误」：0=健康、1=触发了无头补跑、
    # 2=触发了 auto_repair。任何一块的结果都不能中断整条链。
    echo "$(ts)  --- $name 结束（exit=$rc）---"
done
echo "$(ts)  ===== AI 三块串行体检结束 ====="
