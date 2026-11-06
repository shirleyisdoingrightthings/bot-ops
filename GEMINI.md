# Bots 工作区全局记忆与执行规范

1. **仓库结构（均同步至 `git@github.com:shirleyisdoingrightthings/`）**：
   - `us stock bot`（`us-stock-bot.git`）：美股收盘 & 24h 加密行情合盘日报（每周二至周六 10:00 运行；独立 `crypto daily bot` 已退役停跑）。
   - `AI Daily News Bot`（`AI-Daily-News-Bot.git`）：周一至周六出日报（`FETCH_OK`），周日出周回顾（`WEEKLY_OK`）。
   - `x-hotspot-bot`（`x-hotspot-bot.git`）：X 热点分歧播报，每条话题末尾**仅保留被引用次数最多的 1 条 `x.com` 原帖直链**。
   - `ai-builder-bot`（`ai-builder-bot.git`）：AI Builder 日报，已过滤 8 个噪音号并接入 `feed-blogs.json`、AINews 白名单 `EXTRA_BUILDERS` 及 5 个顶级 Builder 个人博客 RSS。
   - `shared`（`bot-ops.git`）：共享工具 `bot_utils.py`、无头补跑框架及 `scheduled-tasks/` 定义。
2. **模型动态路由（方案 A）**：
   - 平时定时任务使用 **Flash** 模型；
   - 周日 `AI Daily News Bot` 返回 `=== WEEKLY_OK ===` 时，调用 `invoke_subagent(TypeName="self", Model="pro")` 指派 **Pro** 模型撰写《AI 产业周回顾》。
3. **两条工具铁律**：
   - `fetch` 后一律用 `read_file` 读取 `logs/last_context.txt`，严禁重复跑 `fetch`；
   - 写稿一律用 `write_file`（`Overwrite: true`），严禁使用 `cat <<EOF` 以防 `$` 金额被 shell 展开吞掉。
