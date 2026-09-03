---
name: morning-catchup-daily-bots
description: 每早 10:00 由 Claude 亲自写稿并推送三个飞书播报 bot（AI 日报含产业/X 热点/Builder 三块）
---

目标：三份本地日报由本任务（Claude）每早亲自写稿并推送——抓取 → Claude 按各自 prompt 写稿 → 发送。本任务是唯一的写稿入口。

⚠️ **2026-09-03 起改为「群里三个机器人」**：
- **AI 日报**（三块，全部发到同一个飞书 webhook，群里显示为「AI 产业日报」这一个机器人）
  1. AI 产业日报（媒体报道了什么）
  2. X 热点播报（圈子在吵什么）
  3. AI Builder 日报（这十几个人本人说了什么）
- **加密日报**（独立 webhook，不变）
- **美股日报**（独立 webhook，不变）

三块 AI 内容仍然是三套独立的脚本、独立的去重档案、独立的 run.log，只是**发送目标合并成了同一个 webhook**。所以下面仍按块处理，任一块出问题不影响其余两块。

⚠️ **告警不再进日报群**：各 bot 的 health_check 现在把 WARN/FAIL 发到单独的监测机器人（plist 里的 `FEISHU_ALERT_WEBHOOK`）。本任务不负责告警，看到日报群里没有 WARN 是正常的。

本任务每天 10:00 触发。若当天本任务没跑成（电脑睡眠 / App 未开等），11:00 的 launchd health_check 会检测到当天无运行记录，并自动调用各 bot 的 claude_catchup.sh 做无头补跑（用 claude CLI 完整重走 fetch → 写稿 → send）。时间线：
10:00 本任务（主力） → 11:00 health_check（体检；[FAIL] 派 auto_repair 自愈，无记录则派 claude_catchup 无头补跑）。
注：各 bot 的主 plist（com.shirley.*）已不再承担调度，仅作为密钥/代理的环境变量配置源。

工作根目录是 `/Users/jialiwu/Desktop/bots`，共享层位于 `/Users/jialiwu/Desktop/bots/shared/`（bot_utils.py / auto_repair_base.sh / headless_catchup_base.sh）。

⚠️ **fetch 的完整输出会落盘到各 bot 的 `logs/last_context.txt`**（marker + context 原样保存）。
读 stdout 时若不慎截断（`head`/`tail`）或输出过大被省略，**直接读这个文件**，
不要重跑 fetch——重跑会再打一轮外部 API，且 RSS 零产计数会被重复累加。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 第一部分之 A：AI 产业日报（Claude 写 1 稿）

**⚠️ 本 bot 周日不出日报，改出《AI 产业周回顾》。** 是否周日由脚本自己判断（机器时区就是北京时间），你不需要算星期几，只看 stdout 给的标记：`=== FETCH_OK ===` = 当日日报，`=== WEEKLY_OK ===` = 本周回顾。两者只差「读哪份 prompt」，发送与核对完全一致。

### 步骤 1 — 抓取
```
bash "/Users/jialiwu/Desktop/bots/AI Daily News Bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入第二部分。
- `=== SKIP_PROXY ===`：本地代理不可用。**不要继续**，记「代理不可用未推送」，提示用户开代理后可手动重跑该 bot 的 `claude_report.sh fetch` 全流程。
- `=== NO_NEWS ===`：24 小时无有效新闻。**不要继续**，记「无有效新闻」。
- `=== FETCH_OK ===`：**当日日报**。提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容作为新闻数据，进入步骤 2A。
- `=== WEEKLY_OK ===`：**本周回顾**（周日）。素材有两段，都要带上：`=== ARCHIVE_BEGIN ===` ~ `=== ARCHIVE_END ===` 之间是本周每天已推送的日报全文（主素材），`=== CONTEXT_BEGIN ===` ~ `=== CONTEXT_END ===` 之间是最近 24 小时的新增原始素材（可能为空）。进入步骤 2B。

周回顾还可能带 `=== ARCHIVE_GAP ===` ~ `=== ARCHIVE_GAP_END ===` 块，列出本周哪几天没有存档
（那几天根本没出稿，多半是没开电脑）。**照常写回顾**，但在最后汇报时注明「本周回顾覆盖不全，缺 X 天」，
并且不要在稿子里假装那几天的事件也已涵盖。

另外：`=== SOURCE_ALERT ===` 与 `=== SOURCE_ALERT_END ===` 之间若有内容，说明有 RSS 源连续 3 天以上零产。**原样记下这几行**，稍后在汇报里单列，不影响出稿流程。

### 步骤 2A — 写当日日报（`FETCH_OK` 时）
1. Read `/Users/jialiwu/Desktop/bots/AI Daily News Bot/prompt.md`。
2. 严格按其全部规则，基于步骤 1 数据写出完整《AI 产业日报》。
3. 硬约束：只用 `<b>` 和 `<a href>` 标签；英文原标题不翻译；日期用 context 里的「今天日期」。开头的「⚡ 30秒速览」按 prompt.md 的速览规则写：固定 5 条、行首带星级、每条 ≤55 字且必须含具体数字或专有名词、与正文前 5 条一一对应。
4. Write 纯正文（无解释、无 markdown 代码块包裹）到：
   `/Users/jialiwu/Desktop/bots/AI Daily News Bot/logs/report_draft.txt`

### 步骤 2B — 写本周回顾（`WEEKLY_OK` 时）
1. Read `/Users/jialiwu/Desktop/bots/AI Daily News Bot/prompt_weekly.md`（**不要用 prompt.md**）。
2. 严格按其全部规则，基于存档 + 新增素材写出完整《AI 产业周回顾》。核心是跨天合并同一线索、按一周尺度重新评分（只留 >= 4 分）、按主题分组，**不是把几天日报拼起来**。
3. 硬约束：只用 `<b>` 和 `<a href>` 标签；**链接一律从存档里原样复制，绝不凭记忆生成 URL**；只写存档与新增素材里出现过的事实，不补充你自己知道的背景；日期区间按 prompt_weekly.md 的规则从 context 的覆盖区间推出。
4. Write 纯正文到同一个文件：
   `/Users/jialiwu/Desktop/bots/AI Daily News Bot/logs/report_draft.txt`

### 步骤 3 — 发送
```
bash "/Users/jialiwu/Desktop/bots/AI Daily News Bot/claude_report.sh" send
```
稿件超过 4096 字时脚本会自动按段落切分并加 (n/N) 页码，无需你处理。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/Desktop/bots/AI Daily News Bot/logs/run.log"`：末行 `[OK] ... Claude写稿` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。周回顾成功时这行会写成 `Claude写稿 → 周回顾N天存档 + 新增M条 → ...`，汇报时注明这天出的是周回顾。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 第一部分之 B：X 热点播报（Claude 写 1 稿）

本块播的是 **X（Twitter）上 AI 圈在吵什么**，是 AI 三块里的第二块：
A 播「媒体报道了什么」，本块播「圈子在吵什么」，C 播「当事人本人怎么讲」。
**同一件事 A 给结论、本块给现场和分歧、C 给本人原话**，三边撞题不算重复，
但本块的正文必须落在原帖与分歧上，不要写成 A 的缩写版。
排在 A 之后处理就是这个原因：先写完产业日报再写它，能主动避开重复。

⚠️ **别指望它给出「今天的热点清单」。** 2026-09-03 核对过 AINews 最近 6 期：它的
Twitter Recap 是**每天只挑一件最大的事往深里扒**的体例（9/1 那期 13 个 h2 全是
Fable 5.1 的不同侧面），不是当天话题的巡览。所以这一块**结构上就只能覆盖一到两个
话题**，这是正常的，不是抓取出了问题。「今天有哪些事」由 A（AI 产业日报）负责，
本块的价值在于把那一件事的分歧扒到「有人说 A、也有人说 B」这个颗粒度。
写稿时不要为了显得全面而硬凑话题数。

### 步骤 1 — 取材
```
bash "/Users/jialiwu/Desktop/bots/x-hotspot-bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入汇报。
- `=== SKIP_PROXY ===`：本地代理不可用。**不要继续**，记「代理不可用未推送」。
- `=== NO_TOPICS ===`：窗口内没抓到可用素材。**不要继续**，记「无可用素材」。
- `=== FETCH_OK ===`：提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容，进入步骤 2。

context 里有两个区块：`=== AINEWS_BEGIN/END ===` 是主素材（Twitter Recap 正文 + **原帖排行**），
`=== TECHMEME_BEGIN/END ===` 是同期主流科技媒体报道，只用来判断话题是不是只在小圈层里热；
对不上就整块不用，别硬塞进稿子。

**⚠️ 两个必须原样传达给读者的信号：**
1. context 顶部若出现「**⚠️ 窗口内没有新一期，以下是最新的一期，距今 N 天**」，
   说明 AINews 停更或延迟。**照常写稿**，但开头第一行必须写明这批讨论发生在哪一天，
   **绝对不能写成「今天」**，汇报时也要注明素材滞后几天。
2. `=== SOURCE_ALERT ===` ~ `=== SOURCE_ALERT_END ===` 之间若有内容，说明某个 provider
   连续 3 天零产。**原样记下这几行**，稍后在汇报里单列，不影响出稿流程。

### 步骤 2 — 写稿
1. Read `/Users/jialiwu/Desktop/bots/x-hotspot-bot/prompt.md`。
2. 严格按其全部规则，基于步骤 1 的素材写出完整《X 热点播报》。
3. **硬约束（前两条违反会被 send 直接拒发，或让稿子失去意义）：**
   - **每条话题至少带一条 `x.com/<user>/status/<id>` 原帖直链**，且**必须从素材的「原帖排行」里原样复制，绝不凭记忆生成 status id**。send 会检查，全篇一条都没有直接 `[FAIL]`。
   - **不许把「被引 N 次」写成「点赞数」或「最高赞」**。那是该帖在当天 AINews 复盘里被引用的次数，是讨论中心度的代理指标，不是互动量。要提就照实说「当天复盘里被引用 N 次」。
   - **分歧必须保留**：素材里有 `Supportive / Neutral / Critical` 三档，只写叫好的一侧等于骗人。重要话题都要给出「有人说 A、也有人说 B」。
   - 只用 `<b>` 和 `<a href>` 标签；英文人名、账号 handle、模型名不翻译。
4. Write 纯正文（无解释、无 markdown 代码块包裹）到：
   `/Users/jialiwu/Desktop/bots/x-hotspot-bot/logs/report_draft.txt`

### 步骤 3 — 发送
```
bash "/Users/jialiwu/Desktop/bots/x-hotspot-bot/claude_report.sh" send
```
超长会自动按段落切分并加 (n/N) 页码，无需你处理。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/Desktop/bots/x-hotspot-bot/logs/run.log"`：末行 `[OK] ... Claude写稿` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。
若末行是 `[FAIL] 稿件里没有任何 x.com 原帖链接`，说明步骤 2 的硬约束没做到——**回步骤 2 重写并补上原帖直链**，不要跳过，也不要重跑 fetch。这是本 bot 唯一允许在同一轮里重写的情形。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 第一部分之 C：AI Builder 日报（Claude 写 1 稿）

本块播的是 **X 上十几位 AI builder（研究员 / 创始人 / 产品 / 工程）本人发了什么**，
和前两块的分工是死的：产业日报播「媒体报道了什么」，X 热点播「圈子在吵什么」，
本块播「当事人自己怎么讲」。同一件事三块都碰得到不算重复，但本块正文必须落在
「某个具体的人说了什么」上，不要写成产业日报的缩写版。放在 AI 三块最后处理，
就是为了先写完前两块再写它，好主动避开重复。

### 步骤 1 — 取材
```
bash "/Users/jialiwu/Desktop/bots/ai-builder-bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入第二部分。
- `=== SKIP_PROXY ===`：本地代理不可用。**不要继续**，记「代理不可用未推送」。
- `=== FEED_ERROR ===`：上游 feed 拉不到。**不要继续**，记「素材源不可用未推送」并附错误。
- `=== NO_TWEETS ===`：feed 里没有新推文（多半上游 CI 未更新）。**不要继续**，记「无可用素材」。
- `=== FETCH_OK ===`：提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容，进入步骤 2。

**⚠️ 一个每天都要处理的时间差：**
素材来自 zarazhangrui/follow-builders 仓库的公共 feed，上游 GitHub Actions 是
**北京时间 14:17** 生成当天那份，而本任务 10:00 就跑了，所以**我们拿到的基本都是
前一天生成的 feed**，覆盖的是前天下午到昨天下午。context 顶部给了「feed 生成时间」
和「推文实际时间区间」，**稿子开头必须写明这批推文发生在哪一天，绝对不能写成「今天」**。
这是正常状态，不是故障，不用在汇报里当问题报。

若出现 `=== FEED_STALE ===` ~ `=== FEED_STALE_END ===` 块，说明滞后超过 36 小时，
上游 CI 多半真的断了。**照常出稿**，但汇报时注明滞后几小时。

### 步骤 2 — 写稿
1. Read `/Users/jialiwu/Desktop/bots/ai-builder-bot/prompt.md`。
2. 严格按其全部规则，基于步骤 1 的素材写出完整《AI Builder 日报》。
3. **硬约束（前两条违反会被 send 拒发或让稿子失去意义）：**
   - **每条话题至少带一条 `x.com/<user>/status/<id>` 原推直链**，且**必须从素材的
     `[原推]` 字段原样复制，绝不凭记忆生成 status id**。send 会检查，全篇一条都没有直接 `[FAIL]`。
   - **开头第一行写明这批推文的实际日期**（见上面的时间差说明）。
   - 赞/转/回是 X 上的**真实互动量**，可以照实写。⚠️ 别和 X 热点那块的「被引用 N 次」
     搞混——那个是复盘引用次数，本块没有那个概念。
   - 只用 `<b>` 和 `<a href>` 标签；英文人名、handle、公司名、模型名不翻译。
4. Write 纯正文（无解释、无 markdown 代码块包裹）到：
   `/Users/jialiwu/Desktop/bots/ai-builder-bot/logs/report_draft.txt`

### 步骤 3 — 发送
```
bash "/Users/jialiwu/Desktop/bots/ai-builder-bot/claude_report.sh" send
```
超长会自动按段落切分并加 (n/N) 页码，无需你处理。发送目标与 AI 产业日报是同一个
webhook，群里显示为同一个机器人。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/Desktop/bots/ai-builder-bot/logs/run.log"`：末行 `[OK] ... Claude写稿` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。
若末行是 `[FAIL] 稿件里没有任何 x.com 原推链接`，说明步骤 2 的硬约束没做到——**回步骤 2 重写并补上原推直链**，不要跳过，也不要重跑 fetch。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 汇报格式

用中文简要汇报。**按三个机器人分组**，AI 日报下面列三块：

```
AI 日报（一个机器人，三块内容）
  · 产业日报：{状态}
  · X 热点：{状态}
  · AI Builder：{状态}
加密日报：{状态}
美股日报：{状态}
```

状态取其一：
- 已推送成功（附 run.log 末行摘要；产业日报若当天出的是《AI 产业周回顾》，写成「已推送成功（本周回顾）」）
- 已跳过（今天已推送）
- 未推送（无有效新闻 / 行情数据缺失 / 代理不可用 / 素材源不可用，注明哪种）
- 无新交易日，已跳过（仅美股，周日/周一或美股假期的正常情况）
- 仅行情，新闻未到周期（仅加密，新闻每 3 天一播的正常情况）
- 无可用素材（X 热点或 AI Builder 窗口内没抓到东西）
- 已推送成功（素材滞后 N 天/小时）（X 热点遇 AINews 停更、AI Builder 遇上游 CI 断更时）
- 失败（附原因与日志末行）

⚠️ AI Builder 那块「feed 比我们早一天」是常态（上游 14:17 生成、我们 10:00 取），
**不要当成异常报**；只有出现 `=== FEED_STALE ===` 才在状态行后注明滞后小时数。

若某个 bot 报了 ARCHIVE_GAP 或「上次播报的收盘交易日」显示有场次被跳过，在状态行后单列一句说明。

若任一块出现了 SOURCE_ALERT，在状态之后**单列一节「源健康」**，把告警行原样列出（哪个源 / provider、连续几天零产），并说明：它们连续 3 天没有贡献任何进入正文的条目，可以从对应脚本的 `RSS_SOURCES`（X 热点是 `sources.py` 的 provider）里移除或更换，问用户要不要处理。没有告警就完全不提这一节。

注意：不修改任何脚本或 plist；同一块的 fetch/send 不要重复跑。任一块因代理/数据问题未出，其余照常处理，互不阻塞。
