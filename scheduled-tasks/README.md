# scheduled-tasks — 自动化定时任务 `SKILL.md` 版本库

所有 bots 的**唯一写稿入口**是 Antigravity Scheduled Automations（sidecar 配置位于 `~/.gemini/config/sidecars/<taskId>/sidecar.json`），其执行指令直接指向本目录下的 `SKILL.md`。
将这些 `SKILL.md` 纳入 `bot-ops` Git 仓库进行版本控制，确保规则变更可追溯、跨设备可一键恢复。

## 调度总览（Asia/Shanghai）

| 路径 | Sidecar `taskId` | 调度 | 作用 |
|---|---|---|---|
| `x-hotspot-morning/SKILL.md` | `x-hotspot-morning` | 每天 08:30（`30 8 * * *`） | X 热点播报（48h AINews + Techmeme 窗口，单条最高引用原帖直链） |
| `cn-hk-stock-bot/SKILL.md` | `cn-hk-premarket` / `cn-hk-close` | 工作日 09:00 / 16:15 | A股 & 港股开盘前瞻（>10:00 自动跳过）与收盘复盘 |
| `github-hn-morning/SKILL.md` | `github-hn-morning` | 每天 09:30（`30 9 * * *`） | GitHub Trending（周一至周六日榜 / 周日周榜）+ Hacker News Top 8 |
| `morning-catchup-daily-bots/SKILL.md` | `morning-catchup-daily-bots` | 周二至周六 10:00（`0 10 * * 2-6`） | 美股收盘 & 24h 加密合盘日报（独立 crypto bot 已退役） |
| `ai-daily-afternoon/SKILL.md` | `ai-daily-afternoon` | 每天 15:00（`0 15 * * *`） | AI 产业日报（每日日报）→ AI Builder 日报（共用产业日报 Feishu webhook） |

> 注：各 bot 目录下的命令行包装脚本仍保留 `claude_report.sh` 文件名以兼容既有路径，内部统一 `source ../shared/report_base.sh`。需要临时手动补发当天已有草稿时，可直接执行：
> `FORCE_RUN=1 bash "<bot>/claude_report.sh" send`

## 本机依赖的非仓库配置（换机需同步）

1. **Antigravity Sidecars**：`~/.gemini/config/sidecars/<taskId>/sidecar.json`（调度 cron、Flash 模型路由 `--model=gemini-4-hydrogen-high` 与工作区权限）。
2. **`~/Library/LaunchAgents/com.shirley.*-bot.plist`**：权威环境变量源（含 Feishu webhook、FMP/TwelveData/CoinGecko/Notion API key、统一代理 `http://127.0.0.1:1082` 等密钥，**严禁**提交到任何 Git 仓库）。
3. **轻量化 `launchd` 健康检查（方案 B，无头 CLI 已停用）**：
   - `com.shirley.x-hotspot-bot-health.plist`（每日 09:30）
   - `com.shirley.github-hn-bot-health.plist`（每日 10:30）
   - `com.shirley.us-stock-bot-health.plist`（每日 11:00）
   - `com.shirley.ai-chain-health.plist`（每日 16:00，串行检查 `AI Daily News Bot` → `ai-builder-bot`）
   - `com.shirley.cn-hk-stock-bot-health.plist`（工作日 17:15）
   - 以上检查均配置 `ENABLE_CLAUDE_REPAIR=0`；错过调度时的开机唤醒补跑由 Antigravity Sidecar 自行负责，`launchd` 仅在草稿已存在且新鲜（`drafts_fresh`）时做 Level 1 非 AI 重发兜底，或发告警通知。
4. **各 bot `logs/` 状态文件**：`sent_urls.json` / `seen_history.json`（跨天去重）、`market_memory.json`（近 5 日盘面记忆）、`.zero_streak.json` 等。

## 一致性检查

确保每个 `~/.gemini/config/sidecars/<taskId>/sidecar.json` 引用的 `SKILL.md` 路径、调度时间与本仓库一致：

```bash
ls -1 ~/.gemini/config/sidecars/
```
