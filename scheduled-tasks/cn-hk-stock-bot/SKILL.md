---
name: cn-hk-stock-bot
description: 周一至周五早 09:00（开盘前瞻）与下午 16:15（收盘复盘）自动抓取 A股 & 港股行情、均线乖离率、行业 ETF 与 7x24 电报，分别推送至 A股 与 港股 飞书机器人
---

目标：基于 `ZhuLinsen/daily_stock_analysis` 的决策仪表盘与均线乖离率趋势诊断理念，在周一至周五两个关键时点分别向飞书群里的「A股机器人」和「港股机器人」推送报告：
1. **早 09:00（`premarket` 开盘前瞻）**：赶在 09:15 A股集合竞价与 09:30 A/H股开盘前，汇总隔夜美股/中概股 ADR 涨跌映射、昨日收盘技术锚点与早间 7x24 财经电报，输出《🇨🇳 A股开盘前瞻》与《🇭🇰 港股开盘前瞻》。
2. **下午 16:15（`close` 收盘复盘）**：在 15:00 A股收盘、16:00 港股收盘后，汇总全天指数、两市成交额、MA5/MA20 均线乖离率、12 大行业 ETF 轮动、核心龙头异动与当日电报催化，输出《🇨🇳 A股收盘复盘》与《🇭🇰 港股收盘复盘》。

⚠️ **三大执行与排版铁律：**
1. **防截断**：执行 `fetch` 后，完整输出已自动落盘到 `/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/logs/last_context.txt`。请直接使用 `read_file` 读取 `logs/last_context.txt`，严禁重复执行 `fetch`。
2. **防 `$` 吞字**：写稿落盘时，必须使用 `write_file`（`Overwrite: true`）分别写入 `logs/report_cn.txt`（A股）和 `logs/report_hk.txt`（港股），严禁使用 `cat <<EOF`。
3. **飞书排版美学与归属感**：
   - ① **顶部指标卡紧凑化**：核心指数、市场宽度、趋势与乖离率、两市量能/外围与流动性映射之间**仅单换行（提行），严禁留空行**；
   - ② **大标题上方空行、下方紧贴**：三大块标题（🔥领涨、❄️领跌、🔭核心叙事、🎯决策仪表盘）**上方必须空一行**与上一节内容彻底拉开距离，**下方严禁留空行**，必须紧贴其管辖的第一项内容；
   - ③ **各板块/叙事条目间隔**：板块1与板块2、板块2与板块3之间空一行；叙事1与叙事2之间空一行；仪表盘各项紧凑换行。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 执行步骤

### 步骤 1 — 抓取
根据当前运行场次（09:00 传 `premarket`，16:15 传 `close`）执行：
```bash
bash "/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/claude_report.sh" fetch premarket
# 或 16:15 收盘场次：
bash "/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/claude_report.sh" fetch close
```
然后使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/logs/last_context.txt`。

### 步骤 2 — 写两稿（A股 + 港股）
1. 若为 `premarket`（09:00 开盘前瞻），使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/prompt_premarket.md`；
   若为 `close`（16:15 收盘复盘），使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/prompt_close.md`。
2. 严格按对应规范写出两份纯正文（仅使用 `<b>` 加粗标签，严禁使用 Markdown `**`）：
   - 使用 `write_file`（`Overwrite: true`）将 A 股报告写入 `/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/logs/report_cn.txt`
   - 使用 `write_file`（`Overwrite: true`）将 港股报告写入 `/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/logs/report_hk.txt`

### 步骤 3 — 分别发送至 A股 与 港股 飞书机器人
```bash
bash "/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/claude_report.sh" send
```
该命令会自动将 `report_cn.txt` 推送至 `FEISHU_WEBHOOK_CN`（A股 Bot），将 `report_hk.txt` 推送至 `FEISHU_WEBHOOK_HK`（港股 Bot）。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/logs/run.log"` 确认出现 `[OK]`。
