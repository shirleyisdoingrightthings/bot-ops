#!/usr/bin/python3
"""alert.py — 把一条运维告警发到飞书，供各 bot 的 health_check.sh 调用。

起因：体检的唯一告警渠道一直是 osascript 桌面通知，而它只在人坐在电脑前时有效。
2026-08-30 查出三个 health job 因 EX_CONFIG 连续 11 天没跑成，恰恰是"告警本身也
没能发出来"——最该被看见的故障，反而是最看不见的。飞书是已经在手的送达渠道，
不依赖你在不在电脑前。

用法：
    alert.py <bot 名> <级别 FAIL|WARN|INFO> <正文>

密钥来源（由调用方 export 进环境）：
    FEISHU_ALERT_WEBHOOK / FEISHU_ALERT_SECRET   —— 想把运维消息分流到单独的群就设这个
    FEISHU_WEBHOOK       / FEISHU_SECRET         —— 没设分流时回退到 bot 自己的群

⚠️ 本脚本任何情况下都以 0 退出：告警发不出去是小事，让体检脚本因此中断是大事。
"""

import os
import sys
import pathlib
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def main() -> int:
    bot   = sys.argv[1] if len(sys.argv) > 1 else "bot"
    level = (sys.argv[2] if len(sys.argv) > 2 else "WARN").upper()
    msg   = sys.argv[3] if len(sys.argv) > 3 else ""

    # ⚠️ webhook 与 secret 必须成对取，不能各自独立回退。
    # 2026-09-03 修：原来是 ALERT_WEBHOOK or WEBHOOK / ALERT_SECRET or SECRET 两条
    # 独立回退，于是「设了分流地址、没设分流密钥」时，会拿 bot 自己那个群的签名密钥
    # 去签监测群的请求——签名对不上，告警静默丢失，而这恰恰是最需要送达的消息。
    # x-hotspot-bot 的主 plist 里就有 FEISHU_SECRET，正好会踩中。
    if os.getenv("FEISHU_ALERT_WEBHOOK"):
        webhook = os.getenv("FEISHU_ALERT_WEBHOOK", "")
        secret  = os.getenv("FEISHU_ALERT_SECRET", "")      # 监测群没开签名就留空
    else:
        webhook = os.getenv("FEISHU_WEBHOOK", "")
        secret  = os.getenv("FEISHU_SECRET", "")
    if not webhook:
        print("[alert] 环境里没有 FEISHU_WEBHOOK，跳过飞书告警", file=sys.stderr)
        return 0

    try:
        from bot_utils import send_feishu, sanitize_html
    except Exception as e:
        print(f"[alert] 无法导入 bot_utils（{e}），跳过飞书告警", file=sys.stderr)
        return 0

    icon = {"FAIL": "🔴", "WARN": "⚠️"}.get(level, "ℹ️")
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 正文来自 health_check 的字符串拼接，可能含 < > &，过一遍转义免得被当成标签
    text = (f"<b>{icon} {sanitize_html(bot)} · {level}</b>\n"
            f"{sanitize_html(msg)}\n"
            f"{ts}")

    try:
        send_feishu(text, webhook, secret or None)
        print(f"[alert] 已发飞书：{level} — {msg}", file=sys.stderr)
    except Exception as e:
        print(f"[alert] 飞书告警发送失败（不影响体检）：{e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
