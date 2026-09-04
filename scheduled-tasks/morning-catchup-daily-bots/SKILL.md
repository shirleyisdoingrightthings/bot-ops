---
name: morning-catchup-daily-bots
description: 每早 10:00 由 Claude 写稿并推送加密日报与美股日报两个飞书 bot
---

目标：加密日报与美股日报由本任务（Claude）每早亲自写稿并推送——抓取 → Claude 按各自 prompt 写稿 → 发送。本任务是这两块唯一的写稿入口。

⚠️ **2026-09-04 起本任务不再包含 AI 日报。** AI 日报的三块（产业日报 / X 热点 / AI Builder）已拆到单独的 `ai-daily-afternoon` 任务，每天 **15:00** 触发——原因是 AI Builder 的上游 feed 在北京时间 14:17 才生成，10:00 跑永远只能拿到前一天那份。**本任务不要去碰那三个 bot**，它们有自己的调度与体检链。

本任务负责的两个 bot 各自是独立机器人、独立 webhook：
  - 加密日报（`crypto daily bot`）
  - 美股日报（`us stock bot`）

⚠️ **告警不进日报群**：各 bot 的 health_check 把 WARN/FAIL 发到单独的监测机器人（plist 里的 `FEISHU_ALERT_WEBHOOK`）。本任务不负责告警。

**时间线**：本任务 10:00 触发（主力）→ 11:00 各 bot 的 launchd health_check 体检（`com.shirley.crypto-daily-bot-health` / `com.shirley.us-stock-bot-health`）；`[FAIL]` 派 auto_repair 自愈，当天无记录则派 `claude_catchup.sh` 无头补跑。注：主 plist（`com.shirley.*`，不带 -health）已不再承担调度，仅作为密钥/代理的环境变量配置源。

工作根目录是 `/Users/jialiwu/Desktop/bots`，共享层在 `/Users/jialiwu/Desktop/bots/shared/`。

⚠️ **fetch 的完整输出会落盘到各 bot 的 `logs/last_context.txt`**（marker + context 原样保存）。读 stdout 时若不慎截断或输出过大被省略，**直接读这个文件**，不要重跑 fetch——重跑会再打一轮外部 API，且零产计数会被重复累加。

## 第二部分：Crypto 日报（Claude 写 2 稿）

### 步骤 1 — 抓取
```
bash "/Users/jialiwu/Desktop/bots/crypto daily bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入汇报。
- `=== SKIP_PROXY ===`：代理不可用。**不要继续**，记「代理不可用未推送」，提示同上。
- `=== SKIP_NO_PRICES ===`：CoinGecko 核心价格全部抓取失败。**不要继续**，记「行情数据缺失未推送」，提示用户稍后可手动重跑。
- `=== FETCH_OK ===`：进入步骤 2。context 里一定有【今日核心行情/总市值/DeFi/赛道/热搜】区块；是否附带新闻条目，看下面这个标记。

**⚠️ 本 bot 的行情与新闻是不同频率的**：行情每天播，新闻每 3 天播一次。`FETCH_OK` 之后必有其中一个标记：
- `=== NEWS_INCLUDED ===`：本次含新闻，**写两稿**（消息①+②）。
- `=== NEWS_SKIPPED ===`：新闻未到 3 天周期，**只写消息①**。
  磁盘上的 `logs/report_news.txt` 是几天前的旧稿，**绝对不要重写或重发它**——
  `claude_report.sh send` 会自行识别本次不含新闻，只推送消息①。

同样：`=== SOURCE_ALERT ===` 块若有内容，原样记下，稍后在汇报里单列。

### 步骤 2 — 写稿
含新闻时写两稿，只出行情时**只写消息①**：

消息①（市场晨报）：
1. Read `/Users/jialiwu/Desktop/bots/crypto daily bot/prompt_analysis.md`。
2. 严格按其规则，结合 context 里的行情数据 + 新闻，写出《每日加密市场晨报》。
3. Write 到 `/Users/jialiwu/Desktop/bots/crypto daily bot/logs/report_analysis.txt`。

消息②（新闻播报）——**仅当 stdout 出现 `=== NEWS_INCLUDED ===` 时才写**：
4. Read `/Users/jialiwu/Desktop/bots/crypto daily bot/prompt_news.md`。
5. 严格按其规则，基于 context 里的新闻条目写出《加密市场新闻播报》，日期用 context 里的「今天日期」。开头的「⚡ 30秒速览」按 prompt_news.md 的速览规则写：固定 5 条、行首带星级、每条 ≤55 字且必须含具体数字或专有名词、与正文前 5 条一一对应。
6. Write 到 `/Users/jialiwu/Desktop/bots/crypto daily bot/logs/report_news.txt`。

两稿硬约束：消息①只用 `<b>` 加粗，不用 markdown `**`；消息②只用 `<b>` 和 `<a href>`；英文原标题不翻译。

### 步骤 3 — 发送
```
bash "/Users/jialiwu/Desktop/bots/crypto daily bot/claude_report.sh" send
```
它会按本次是否含新闻决定发一条还是两条（含部分发送保护），超长自动分块加页码。
非新闻日只发消息①，脚本内有旧稿新鲜度校验，不会误发几天前的新闻。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/Desktop/bots/crypto daily bot/logs/run.log"`：末行 `[OK] ... Claude写稿` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 第三部分：美股日报（Claude 写 2 稿）

本 bot 播报的是**最近一个已收盘的美股交易日**，不是"今天"。北京时间周日与周一没有新的收盘场次，脚本会自行跳过。

### 步骤 1 — 抓取
```
bash "/Users/jialiwu/Desktop/bots/us stock bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入汇报。
- `=== SKIP_NO_NEW_SESSION ===`：该收盘场次已播报过（周日/周一或美股假期）。**不要继续**，记「无新交易日，已跳过」——这是正常情况，不是故障。
- `=== SKIP_PROXY ===`：代理不可用。**不要继续**，记「代理不可用未推送」。
- `=== SKIP_NO_QUOTES ===`：行情抓取失败。**不要继续**，记「行情数据缺失未推送」。
- `=== FETCH_OK ===`：提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容。
  若 stdout 里出现「上次播报的收盘交易日：X」，且 X 与本次【收盘交易日】之间还夹着交易日，
  说明中间有场次被漏播（漏跑那几天造成），照常出稿，但在汇报里注明「X 至本次之间的收盘未播报」。它包含【收盘交易日】【指数收盘】【宏观指标】【板块表现】【个股涨跌前 8】区块 + 若干新闻条目。进入步骤 2。

同样：`=== SOURCE_ALERT ===` 块若有内容，原样记下，稍后在汇报里单列。

### 步骤 2 — 写两稿
消息①（收盘仪表盘）：
1. Read `/Users/jialiwu/Desktop/bots/us stock bot/prompt_market.md`。
2. 严格按其规则，结合 context 里的行情数据 + 新闻，写出《美股收盘》。
3. Write 到 `/Users/jialiwu/Desktop/bots/us stock bot/logs/report_market.txt`。

消息②（要闻播报）：
4. Read `/Users/jialiwu/Desktop/bots/us stock bot/prompt_news.md`。
5. 严格按其规则写出《美股要闻》。开头的「⚡ 30秒速览」按速览规则写：固定 5 条、行首带星级、每条 ≤55 字且必须含具体数字或专有名词、与正文前 5 条一一对应。
6. Write 到 `/Users/jialiwu/Desktop/bots/us stock bot/logs/report_news.txt`。

两稿硬约束：日期一律用 context 里的【收盘交易日】，不要用今天的日期；消息①只用 `<b>` 加粗，不用 markdown `**`；消息②只用 `<b>` 和 `<a href>`；英文原标题不翻译。
注意与 Crypto 日报的分工：本 bot 写股权角度（财报、股价、估值、并购），加密资产角度（买卖了多少 BTC）归 Crypto 日报，不要重复。

### 步骤 3 — 发送
```
bash "/Users/jialiwu/Desktop/bots/us stock bot/claude_report.sh" send
```
它会依次发送两稿（含部分发送保护），超长自动分块加页码。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/Desktop/bots/us stock bot/logs/run.log"`：末行 `[OK] ... Claude写稿` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。

━━━━━━━━━━━━━━━
## 汇报格式

用中文简要汇报，只报本任务负责的两个 bot：

```
加密日报：{状态}
美股日报：{状态}
```

状态取其一：
- 已推送成功（附 run.log 末行摘要）
- 已跳过（今天已推送）
- 未推送（行情数据缺失 / 代理不可用，注明哪种）
- 无新交易日，已跳过（仅美股，周日/周一或美股假期的正常情况）
- 仅行情，新闻未到周期（仅加密，新闻每 3 天一播的正常情况）
- 失败（附原因与日志末行）

⚠️ 加密的恐惧贪婪指数自 2026-09-04 起有备用源（主源 alternative.me，备用 CoinMarketCap）。若稿子里该值仍是「未知」，说明两个源都失败了，**要在汇报里点出来**。

若美股的「上次播报的收盘交易日」显示中间有场次被跳过，在状态行后单列一句说明。

若任一 bot 出现了 SOURCE_ALERT，在状态之后**单列一节「源健康」**，把告警行原样列出（哪个源、连续几天零产），并说明它们连续 3 天没有贡献任何进入正文的条目，可以从对应脚本的 `RSS_SOURCES` 里移除或更换，问用户要不要处理。没有告警就完全不提这一节。

注意：不修改任何脚本或 plist；同一块的 fetch/send 不要重复跑。任一 bot 因代理/数据问题未出，另一个照常处理，互不阻塞。