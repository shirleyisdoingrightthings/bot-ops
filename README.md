# Bot Ops (Shared Runtime & Automation Layer)

Shared runtime utilities, scheduling definitions, health checks, and self-healing workflows for the daily Feishu reporting bots.

## Workflow

```text
Daily Scheduled Automations
  │
  ├─ 10:00 CST (Tue–Sat) ─▶ morning-catchup-daily-bots
  │                           └─ US Stock & 24h Crypto Daily Bot
  │
  ├─ 15:00 CST (Daily)   ─▶ ai-daily-afternoon (Sequential Execution)
  │                           ├─ Part A: AI Daily News Bot (or Sunday Weekly Review via Pro model)
  │                           ├─ Part B: X Hotspot Bot (skips if no new AINews issue)
  │                           └─ Part C: AI Builder Bot
  │
  └─ +1 Hour After Run   ─▶ Health Check & Self-Healing (health_check_base.sh)
                              ├─ [OK]      Increment streak & clear resolved changelog items
                              ├─ [NO_NEWS] Normal terminal state; skip catchup
                              ├─ [MISSING] Trigger headless_catchup_base.sh (fetch → draft → send)
                              └─ [FAIL]    Trigger auto_repair_base.sh (retry → diagnose → catchup)
```

## Core Responsibilities

1. **Unified Fetching & Delivery (`bot_utils.py`)**: Provides proxy auto-healing, RSS parsing, full-text extraction, 7-day cross-day URL deduplication (`sent_urls.json`), HTML sanitization, and Feishu card pagination.
2. **Scheduled Task Definitions (`scheduled-tasks/`)**: Version-controlled instructions for the morning (`10:00`) and afternoon (`15:00`) automated agent runs.
3. **Automated Health Check & Recovery (`*_base.sh`)**: Monitors daily execution logs and automatically triggers headless catchup or self-repair when a scheduled run is missed or fails.
