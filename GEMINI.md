# Bots 工作区全局记忆与执行规范

1. **仓库结构（均同步至 `git@github.com:shirleyisdoingrightthings/`）**：
   - `x-hotspot-bot`（`x-hotspot-bot.git`）：X 热点分歧播报（**每日早 08:30** 独立运行，48h 窗口；每条话题末尾**仅保留被引用次数最多的 1 条 `x.com` 原帖直链**）。
   - `cn-hk-stock-bot`：A股 & 港股智能决策日报（周一至周五 09:00 `premarket` 开盘前瞻，**超过 10:00 自动跳过**；16:15 `close` 收盘复盘）。
   - `github-hn-bot`：GitHub Trending（周一至周六 Daily / 周日 Weekly 全局唯一周趋势回顾）+ Hacker News Top 8 大白话早报（每日 09:30）。
   - `us stock bot`（`us-stock-bot.git`）：美股收盘 & 24h 加密行情合盘日报（每周二至周六 10:00；独立 `crypto daily bot` 已退役停跑）。
   - `AI Daily News Bot`（`AI-Daily-News-Bot.git`）：每日 15:00 统一出《AI 产业日报》（`FETCH_OK`；已永久取消周日周回顾）。
   - `ai-builder-bot`（`ai-builder-bot.git`）：每日 15:00 紧随产业日报运行；已过滤 8 个噪音号并接入 `feed-blogs.json`、AINews 白名单 `EXTRA_BUILDERS` 及 5 个顶级 Builder 个人博客 RSS。
   - `shared`（`bot-ops.git`）：共享工具 `bot_utils.py`、统一脚本入口 `report_base.sh`、Notion 归档 `notion_archive.py`、轻量化健康检查与 Level 1 重发保护（`*_base.sh`）及 `scheduled-tasks/` 定义。
2. **模型调度与健康检查（方案 B）**：
   - 日常定时任务统一由 Antigravity Scheduled Automations 驱动并使用 **Flash** 模型。
   - 取消 `launchd` 拉起无头 CLI（`ENABLE_HEADLESS_CATCHUP=0`、`ENABLE_CLAUDE_REPAIR=0`）；开机唤醒补跑由 Antigravity Sidecar 自行负责，`launchd` 健康检查仅执行轻量状态核验与本地新鲜草稿（`drafts_fresh`）的 Level 1 非 AI 重发。
3. **两条工具铁律**：
   - `fetch` 后一律用 `read_file` 读取 `logs/last_context.txt`，严禁重复跑 `fetch`；
   - 写稿一律用 `write_file`（`Overwrite: true`），严禁使用 `cat <<EOF` 以防 `$` 金额被 shell 展开吞掉。
