# Bot Ops (Shared Runtime & Automation Layer)

Shared runtime utilities, scheduling definitions, lightweight health checks, and Notion archiving for the daily Feishu reporting bots.

## Workflow

```text
Daily Scheduled Automations (Asia/Shanghai)
  │
  ├─ 08:30 CST (Daily)   ─▶ x-hotspot-morning
  │                           └─ X Hotspot Bot (48h AINews + Techmeme, single top-cited x.com link)
  │
  ├─ 09:00 CST (Mon–Fri) ─▶ cn-hk-premarket
  │                           └─ A-Share & HK Premarket Outlook (skips if > 10:00 via === SKIP_EXPIRED ===)
  │
  ├─ 09:30 CST (Daily)   ─▶ github-hn-morning
  │                           └─ GitHub Trending (Mon–Sat Daily / Sun Weekly) & Hacker News Top 8
  │
  ├─ 10:00 CST (Tue–Sat) ─▶ morning-catchup-daily-bots
  │                           └─ US Stock Close & 24h Crypto Daily Bot
  │
  ├─ 15:00 CST (Daily)   ─▶ ai-daily-afternoon (Sequential Execution)
  │                           ├─ Part A: AI Daily News Bot (Daily every day; no Sunday weekly review)
  │                           └─ Part B: AI Builder Bot
  │
  ├─ 16:15 CST (Mon–Fri) ─▶ cn-hk-close
  │                           └─ A-Share & HK Close Review
  │
  └─ +1 Hour After Run   ─▶ Lightweight Health Check (health_check_base.sh, Option B)
                              ├─ [OK]      Increment streak & clear resolved changelog items
                              ├─ [NO_NEWS] Normal terminal state; skip alarm
                              ├─ [MISSING] Notify & rely on Antigravity Sidecar wake-up catchup (no headless CLI)
                              └─ [FAIL]    Level 1 non-AI pending resend if drafts_fresh; else alert only
```

## Core Responsibilities

1. **Unified Fetching & Delivery (`bot_utils.py`)**: Proxy auto-healing (`127.0.0.1:1082`), RSS parsing, full-text extraction, 7-day cross-day URL deduplication (`sent_urls.json`), HTML sanitization, Feishu card pagination (`~20KB` chunking), and `send_x_linked_report`.
2. **Unified Shell Entrypoint (`report_base.sh`)**: Shared `claude_report.sh` wrapper importing `LaunchAgent` plist env vars, checking lock/run state, and invoking each bot's `*_report.py`.
3. **Notion Sync (`notion_archive.py`)**: Converts HTML/Feishu drafts to Notion blocks and archives daily reports into Notion DB `e072f4c04bbf467793879e7dce4e4373` (via proxy `1082` + direct fallback).
4. **Scheduled Task Definitions (`scheduled-tasks/`)**: Version-controlled `SKILL.md` prompts mirrored by Antigravity Sidecars (`~/.gemini/config/sidecars/`).
5. **Lightweight Health Monitoring (`health_check_base.sh`, `auto_repair_base.sh`, `ai_chain_health.sh`)**: Checks `run.log` / `run.jsonl` health, performs Level 1 pending-draft resend on transient send failures, and notifies Feishu if manual attention is needed without spawning headless CLI sessions (`ENABLE_CLAUDE_REPAIR=0`, `ENABLE_HEADLESS_CATCHUP=0`).
