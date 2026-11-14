---
name: morning-catchup-daily-bots
description: 每周二至周六早 10:00 写稿并推送《美股收盘 & 加密行情日报》飞书 bot
---

目标：美股收盘日报（已内嵌 24h 加密核心币价与情绪指标）由本任务在每周二至周六早 10:00（对应美股周一至周五收盘）亲自写稿并推送——抓取 → 按各自 prompt 写稿 → 发送。本任务是该机器人的唯一写稿入口。

⚠️ **重要变更说明：**
1. **2026-11 起独立 Crypto 日报已退役并合并：** 加密货币不再抓取新闻，仅保留核心币价（BTC / ETH / SOL / BNB / XRP / HYPE）、全球加密市值、BTC 市占率与恐惧贪婪指数，并已直接内嵌到 `us stock bot` 的消息①（收盘仪表盘）中。**独立 `crypto daily bot` 已下线归档，切勿再去运行。**
2. **其他时段调度不在此任务：** `x-hotspot-morning` 在早 08:30、`cn-hk-*` 在工作日 09:00/16:15、`github-hn-morning` 在早 09:30、`ai-daily-afternoon` 在下午 15:00 运行，**本任务只跑 `us stock bot`**。

**时间线**：每周二至周六 10:00 触发（主力）→ 11:00 `com.shirley.us-stock-bot-health` 执行轻量化健康检查（方案 B：不再拉起无头 CLI；仅当本地草稿已生成且新鲜 `drafts_fresh` 时执行 Level 1 非 AI 重发；关机/休眠错过 10:00 时由 Antigravity Sidecar 开机唤醒补跑）。

工作根目录是 `/Users/jialiwu/.gemini/bots`，共享层在 `/Users/jialiwu/.gemini/bots/shared/`。

⚠️ **两条工具执行铁律（防截断 & 防 `$` 吞字）：**
1. **防截断**：执行 `fetch` 后，完整输出已自动落盘到 `/Users/jialiwu/.gemini/bots/us stock bot/logs/last_context.txt`。若终端 stdout 显示不全或被截断，**直接使用 `read_file` 工具读取 `logs/last_context.txt`**，严禁重跑 `fetch`（重跑会重复消耗外部 API 并累加零产计数）。
2. **防 `$` 变量吞字**：写稿落盘时，**必须使用 `write_file` 工具（设置 `Overwrite: true`）** 写入 `logs/report_market.txt` 和 `logs/report_news.txt`，**严禁使用 `bash` 的 `cat <<EOF` 或 `echo` 写文件**（否则正文中的 `$100B`、`$NVDA` 等美元符号会被 shell 当作变量展开吞掉）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 美股收盘 & 加密行情日报（写 2 稿）

本 bot 播报的是**最近一个已收盘的美股交易日**（附带 24h 加密核心行情），不是"今天"。北京时间周日与周一没有新的收盘场次（美股假期同理），脚本会自行跳过。

### 步骤 1 — 抓取
执行命令（若沙箱拦截本地代理 `127.0.0.1:1082`，请使用 `BypassSandbox: true`）：
```bash
bash "/Users/jialiwu/.gemini/bots/us stock bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入汇报。
- `=== SKIP_NO_NEW_SESSION ===`：该收盘场次已播报过（周末或美股假期）。**不要继续**，记「无新交易日，已跳过」——这是正常情况，不是故障。
- `=== SKIP_PROXY ===`：代理不可用。**不要继续**，记「代理不可用未推送」。
- `=== SKIP_NO_QUOTES ===`：行情抓取失败。**不要继续**，记「行情数据缺失未推送」。
- `=== FETCH_OK ===`：使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/us stock bot/logs/last_context.txt`，提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容。
  若出现「上次播报的收盘交易日：X」，且 X 与本次【收盘交易日】之间还夹着交易日，说明中间有场次被漏播，照常出稿，但在汇报里注明「X 至本次之间的收盘未播报」。
  context 包含【收盘交易日】【指数收盘】【宏观指标】【加密核心行情（24h）】【板块表现】【个股涨跌前 8】区块 + 若干新闻条目。进入步骤 2。

同样：`=== SOURCE_ALERT ===` 块若有内容，原样记下，稍后在汇报里单列。

### 步骤 2 — 写两稿
消息①（美股收盘 & 加密行情仪表盘）：
1. 使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/us stock bot/prompt_market.md`。
2. 严格按其规则，结合 context 里的美股行情、24h 加密核心行情与新闻，写出《美股收盘 & 加密行情复盘》：
   - `10年期美债` 按收益率 + bp 涨跌展示（如 `5.14% (+3.4bp)`），不要写相对百分比；
   - 普跌日领涨板块自动标注为 `🔥 领涨/抗跌 Top 3 板块`；
   - 板块或个股无新闻对应时明确写 `未见明确催化`（补一句技术/资金面说明 ≤ 20 字）；
   - 各核心指标、板块细项与决策仪表盘字段必须按规范分行/空行，严禁挤在同一行。
3. 使用 `write_file`（`Overwrite: true`）写入 `/Users/jialiwu/.gemini/bots/us stock bot/logs/report_market.txt`。

消息②（美股要闻播报）：
4. 使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/us stock bot/prompt_news.md`。
5. 严格按其规则写出《美股要闻》：
   - 标题用 `<b>📋 美股要闻 · [收盘交易日]</b>` 与 `<b>⚡ 30秒速览</b>`；
   - 「⚡ 30秒速览」下方空一行后接 5 条以「- 」开头的无序列表（彻底去掉 ⭐、每条 ≤55 字且含具体数字/专名、与正文前 5 条一一对应）；
   - 正文严格按 5星至3星倒序，**最多入选 12 条**（按 5分 > 4分 > 3分 截断），每条严格按 `标题 (<a href="..."><b>...</b></a>) → [星级] [标签] → 📄 The Details：` 顺序排版，`📄 The Details：` 后必须采用单个连贯高密度叙事段落（严禁 bullet，严禁叙事段落内部使用冒号），格式与《AI 产业日报》保持 100% 镜像一致。
6. 使用 `write_file`（`Overwrite: true`）写入 `/Users/jialiwu/.gemini/bots/us stock bot/logs/report_news.txt`。

两稿硬约束：日期一律用 context 里的【收盘交易日】，不要用今天的日期；消息①只用 `<b>` 加粗，不用 markdown `**`；消息②只用 `<b>` 和 `<a href>`；英文原标题不翻译。

### 步骤 3 — 发送
```bash
bash "/Users/jialiwu/.gemini/bots/us stock bot/claude_report.sh" send
```
它会依次发送两稿（含部分发送保护），超长自动分块加页码。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/us stock bot/logs/run.log"`：末行 `[OK] ...` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。

━━━━━━━━━━━━━━━
## 汇报格式

用中文简要汇报：

```text
美股收盘 & 加密行情日报：{状态}
```

状态取其一：
- 已推送成功（附 run.log 末行摘要）
- 已跳过（今天已推送）
- 未推送（行情数据缺失 / 代理不可用，注明哪种）
- 无新交易日，已跳过（周末或美股假期的正常情况）
- 失败（附原因与日志末行）

⚠️ 加密的恐惧贪婪指数有双源兜底（主源 alternative.me，备用 CoinMarketCap）。若稿子里该值仍是「未知」，说明两个源都失败了，**要在汇报里点出来**。

若「上次播报的收盘交易日」显示中间有场次被跳过，在状态行后单列一句说明。

若出现了 `SOURCE_ALERT`，在状态之后**单列一节「源健康」**，把告警行原样列出（哪个源、连续几天零产），问用户要不要处理。没有告警就完全不提这一节。
