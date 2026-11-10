---
name: ai-daily-afternoon
description: 每天 15:00 由 Claude 写稿并推送 AI 日报三块（产业日报 / X 热点 / AI Builder）
---

目标：AI 日报的三块内容由本任务（Claude）每天下午亲自写稿并推送——抓取 → Claude 按各自 prompt 写稿 → 发送。本任务是这三块唯一的写稿入口。

⚠️ **本任务只管 AI 日报这一个机器人。** 加密日报与美股日报是另外两个独立机器人、独立 webhook、独立调度（仍是每早 10:00 的 `morning-catchup-daily-bots` 任务），**与本任务无关，不要去碰它们**。

三块内容全部发到同一个飞书 webhook，群里显示为「AI 产业日报」这一个机器人：
  1. AI 产业日报（媒体报道了什么）
  2. X 热点播报（圈子在吵什么）
  3. AI Builder 日报（这十几个人本人说了什么）

三块仍是三套独立的脚本、独立的去重档案、独立的 run.log，只是发送目标合并成了同一个 webhook。所以下面按块处理，任一块出问题不影响其余两块。**必须按 A → B → C 的顺序做**：先写完产业日报和 X 热点，写 AI Builder 时才能主动避开重复。

**时间线（2026-09-04 改）**：本任务 15:00 触发（主力）→ 16:00 由 `com.shirley.ai-chain-health` 这一个 launchd job 按固定顺序串行体检三块（产业日报 → X 热点 → AI Builder，每块 25 分钟超时），检测到当天无运行记录就调用对应 bot 的 `claude_catchup.sh` 做无头补跑。改到下午的直接原因是 AI Builder 的上游 feed 在北京时间 14:17 才生成。

工作根目录是 `/Users/jialiwu/.gemini/bots`，共享层在 `/Users/jialiwu/.gemini/bots/shared/`。

⚠️ **两条工具执行铁律（防截断 & 防 `$` 吞字）：**
1. **防截断**：执行 `fetch` 后，完整输出已自动落盘到各 bot 的 `logs/last_context.txt`（marker + context 原样保存）。若终端 stdout 截断或输出过大被省略，**直接使用 `read_file` 工具读取 `logs/last_context.txt`**，严禁重跑 `fetch`（重跑会再打一轮外部 API，且零产计数会被重复累加）。
2. **防 `$` 变量吞字**：写稿落盘时，**必须使用 `write_file` 工具（设置 `Overwrite: true`）** 写入各 bot 的 `logs/report_draft.txt`，**严禁使用 `bash` 的 `cat <<EOF` 或 `echo` 写文件**（否则正文中的 `$100M` 等美元数字会被 shell 当作变量展开吞掉）。

## 第一部分之 A：AI 产业日报（Claude 写 1 稿）

**⚠️ 本 bot 周日不出日报，改出《AI 产业周回顾》。** 是否周日由脚本自己判断（机器时区就是北京时间），你不需要算星期几，只看 stdout 给的标记：`=== FETCH_OK ===` = 当日日报，`=== WEEKLY_OK ===` = 本周回顾。两者只差「读哪份 prompt」，发送与核对完全一致。

### 步骤 1 — 抓取
```
bash "/Users/jialiwu/.gemini/bots/AI Daily News Bot/claude_report.sh" fetch
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
1. Read `/Users/jialiwu/.gemini/bots/AI Daily News Bot/prompt.md`。
2. 严格按其全部规则，基于步骤 1 数据写出完整《AI 产业日报》。
3. 硬约束：只用 `<b>` 和 `<a href>` 标签；英文原标题不翻译；日期用 context 里的「今天日期」。开头的「⚡ 30秒速览」为独立小标题，下方空一行后接 5 条无序列表内容（每行均以「- 」开头分行排列，严禁与标题粘在同一行，严禁写成单段连续文本），彻底去掉所有星星（无 ⭐）、每条 ≤55 字且必须含具体数字或专有名词、与正文前 5 条一一对应。正文条目必须严格按照最高优先级向最低优先级倒序排列（5星至3星），The Details 严禁使用 bullet points，必须采用单个连贯完整的高密度叙事段落，格式与《美股要闻》保持 100% 镜像一致。
4. Write 纯正文（无解释、无 markdown 代码块包裹）到：
   `/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/report_draft.txt`

### 步骤 2B — 写本周回顾（`WEEKLY_OK` 时，自动调用 `Pro` 模型写稿）
⚠️ **模型动态路由（方案 A）：** 平时周一至周六的日常任务由主 Agent（`Flash` 模型）直接完成；唯独周日触发 `=== WEEKLY_OK ===` 时，由于需要跨 6 天、约 1.5 万字存档做线索合并与重新评分，**必须调用 `invoke_subagent`（设置 `TypeName: "self"`, `Model: "pro"`）指派 `Pro` 子模型专门撰写《AI 产业周回顾》**，写完直接落盘到 `/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/report_draft.txt`：
1. 让 `Pro` 子模型 Read `/Users/jialiwu/.gemini/bots/AI Daily News Bot/prompt_weekly.md`（**不要用 prompt.md**）及 `/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/last_context.txt`。
2. 严格按其全部规则，基于存档 + 新增素材写出完整《AI 产业周回顾》。核心是跨天合并同一线索、按一周尺度重新评分（只留 >= 4 分）、按主题分组，**不是把几天日报拼起来**。
3. 硬约束：只用 `<b>` 和 `<a href>` 标签；**链接一律从存档里原样复制，绝不凭记忆生成 URL**；只写存档与新增素材里出现过的事实，不补充你自己知道的背景；日期区间按 prompt_weekly.md 的规则从 context 的覆盖区间推出。「⚡ 本周 5 件事」与「📈 本周数字」严格采用「- 」列表符并与标题空行隔开，正文组别与新闻条目均以空行断开独立占行。
4. 使用 `write_file`（`Overwrite: true`）将纯正文写入同一个文件：
   `/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/report_draft.txt`

### 步骤 3 — 发送
```
bash "/Users/jialiwu/.gemini/bots/AI Daily News Bot/claude_report.sh" send
```
稿件超过 4096 字时脚本会自动按段落切分并加 (n/N) 页码，无需你处理。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/run.log"`：末行 `[OK] ... Claude写稿` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。周回顾成功时这行会写成 `Claude写稿 → 周回顾N天存档 + 新增M条 → ...`，汇报时注明这天出的是周回顾。

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

**⚠️ 素材源已于 2026-09-04 更换。** 原站 news.smol.ai 整站返回 402
（Vercel 的 DEPLOYMENT_DISABLED，账单停用），`sources.py` 里已把
`latent.space/feed` 设为首选、原站退到末位兜底。AINews 已并入 Latent Space，
同一批 `[AINews]` 期刊在那边照常更新，正文结构与原站一致。
兜底路径按标题里的 `[ainews]` 过滤（latent.space 的 feed 混有播客与专栏文）。
若某天 stdout 里重新出现 news.smol.ai 的 402 提示，属正常（说明原站仍未恢复）。

### 步骤 1 — 取材
```
bash "/Users/jialiwu/.gemini/bots/x-hotspot-bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入汇报。
- `=== SKIP_PROXY ===`：本地代理不可用。**不要继续**，记「代理不可用未推送」。
- `=== NO_TOPICS ===`：30h 窗口内上游 Latent Space `[AINews]` 无未播新刊（如周末/周一停更，或最新一期已播过）。**不要继续写稿或推送**，直接记「未检测到上游 AINews 新刊，今日跳过推送」，进入下一部分。
- `=== FETCH_OK ===`：提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容，进入步骤 2。

context 里有两个区块：`=== AINEWS_BEGIN/END ===` 是主素材（Twitter Recap 正文 + **原帖排行**），
`=== TECHMEME_BEGIN/END ===` 是同期主流科技媒体报道（30h 窗口），只用来判断话题是不是只在小圈层里热；
对不上就整块不用，别硬塞进稿子。

**⚠️ 信号说明：**
`=== SOURCE_ALERT ===` ~ `=== SOURCE_ALERT_END ===` 之间若有内容，说明某个 provider
连续 3 天零产。**原样记下这几行**，稍后在汇报里单列，不影响出稿流程。

### 步骤 2 — 写稿
1. Read `/Users/jialiwu/.gemini/bots/x-hotspot-bot/prompt.md`。
2. 严格按其全部规则，基于步骤 1 的素材写出完整《X 热点播报》。
3. **硬约束（前两条违反会被 send 直接拒发，或让稿子失去意义）：**
   - **每条话题只选被引用次数最多的那 1 条 `x.com/<user>/status/<id>` 原帖直链贴出**（格式：`原帖：<a href="{x.com 直链}">@{handle}</a>（当天复盘被引用 {N} 次）`），**不要堆砌多条原帖链接**，且必须从素材的「原帖排行」里原样复制，绝不凭记忆生成 status id。send 会检查，全篇一条都没有直接 `[FAIL]`。
   - **不许把「被引 N 次」写成「点赞数」或「最高赞」**。那是该帖在当天 AINews 复盘里被引用的次数，是讨论中心度的代理指标，不是互动量。要提就照实说「当天复盘被引用 N 次」。
   - **分歧必须保留**：素材里有 `Supportive / Neutral / Critical` 三档，只写叫好的一侧等于骗人。重要话题都要给出「有人说 A、也有人说 B」（正文中点出代表人物的 `@handle` 即可，末尾只挂被引最高的那 1 条原帖直链）。
   - 只用 `<b>` 和 `<a href>` 标签；英文人名、账号 handle、模型名不翻译。
4. Write 纯正文（无解释、无 markdown 代码块包裹）到：
   `/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/report_draft.txt`

### 步骤 3 — 发送
```
bash "/Users/jialiwu/.gemini/bots/x-hotspot-bot/claude_report.sh" send
```
超长会自动按段落切分并加 (n/N) 页码，无需你处理。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/run.log"`：末行 `[OK] ... Claude写稿` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。
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
bash "/Users/jialiwu/.gemini/bots/ai-builder-bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入第二部分。
- `=== SKIP_PROXY ===`：本地代理不可用。**不要继续**，记「代理不可用未推送」。
- `=== FEED_ERROR ===`：上游 feed 拉不到。**不要继续**，记「素材源不可用未推送」并附错误。
- `=== NO_TWEETS ===`：feed 里没有新推文（多半上游 CI 未更新）。**不要继续**，记「无可用素材」。
- `=== FETCH_OK ===`：提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容，进入步骤 2。

**⚠️ 关于 feed 的时间（2026-09-04 起本任务由 10:00 改到 15:00，这段跟着改了）：**
素材来自 zarazhangrui/follow-builders 仓库的公共 feed，上游 GitHub Actions 在
**北京时间 14:17** 生成当天那份。本任务 15:00 跑，**正常情况下拿到的就是当天的 feed**，
滞后约 45 分钟——这正是把本任务从 10:00 挪到 15:00 的原因（此前 10:00 跑永远只能拿到
前一天 14:17 的那份，播的是前天下午到昨天下午的推文）。
但**仍然不要默认它就是「今天」**：上游 CI 偶尔延迟或失败，那时 raw 上还是昨天那份。
context 顶部给了「feed 生成时间」和「推文实际时间区间」，**稿子开头必须按 context 里的
实际区间写明这批推文发生在哪一天**，不要凭「现在是 15 点所以一定是今天」想当然。

若出现 `=== FEED_STALE ===` ~ `=== FEED_STALE_END ===` 块，说明滞后超过 36 小时，
上游 CI 多半真的断了。**照常出稿**，但汇报时注明滞后几小时。

### 步骤 2 — 写稿
1. Read `/Users/jialiwu/.gemini/bots/ai-builder-bot/prompt.md`。
2. 严格按其全部规则，基于步骤 1 的素材写出完整《AI Builder 日报》。
3. **硬约束（前两条违反会被 send 拒发或让稿子失去意义）：**
   - **每条话题至少带一条 `x.com/<user>/status/<id>` 原推直链**，且**必须从素材的
     `[原推]` 字段原样复制，绝不凭记忆生成 status id**。send 会检查，全篇一条都没有直接 `[FAIL]`。
   - **开头第一行写明这批推文的实际日期**（见上面的时间差说明）。
   - 赞/转/回是 X 上的**真实互动量**，可以照实写。⚠️ 别和 X 热点那块的「被引用 N 次」
     搞混——那个是复盘引用次数，本块没有那个概念。
   - 只用 `<b>` 和 `<a href>` 标签；英文人名、handle、公司名、模型名不翻译。
4. Write 纯正文（无解释、无 markdown 代码块包裹）到：
   `/Users/jialiwu/.gemini/bots/ai-builder-bot/logs/report_draft.txt`

### 步骤 3 — 发送
```
bash "/Users/jialiwu/.gemini/bots/ai-builder-bot/claude_report.sh" send
```
超长会自动按段落切分并加 (n/N) 页码，无需你处理。发送目标与 AI 产业日报是同一个
webhook，群里显示为同一个机器人。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/ai-builder-bot/logs/run.log"`：末行 `[OK] ... Claude写稿` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。
若末行是 `[FAIL] 稿件里没有任何 x.com 原推链接`，说明步骤 2 的硬约束没做到——**回步骤 2 重写并补上原推直链**，不要跳过，也不要重跑 fetch。

━━━━━━━━━━━━━━━
## 汇报格式

用中文简要汇报，只报本任务负责的三块：

```
AI 日报（一个机器人，三块内容）
  · 产业日报：{状态}
  · X 热点：{状态}
  · AI Builder：{状态}
```

状态取其一：
- 已推送成功（附 run.log 末行摘要；产业日报若当天出的是《AI 产业周回顾》，写成「已推送成功（本周回顾）」）
- 已跳过（今天已推送）
- 未推送（无有效新闻 / 代理不可用 / 素材源不可用，注明哪种）
- 无可用素材（X 热点或 AI Builder 窗口内没抓到东西）
- 已推送成功（素材滞后 N 天/小时）
- 失败（附原因与日志末行）

⚠️ AI Builder 现在应当拿到**当天**的 feed（上游 14:17 生成、我们 15:00 取，滞后约 45 分钟）。若 context 显示拿到的仍是前一天那份，说明上游 CI 延迟或失败，**要在汇报里点出来**——这和改点之前「慢一天是常态」已经不同了。出现 `=== FEED_STALE ===` 时另外注明滞后小时数。

若产业日报报了 ARCHIVE_GAP，在状态行后单列一句说明。

若任一块出现了 SOURCE_ALERT，在状态之后**单列一节「源健康」**，把告警行原样列出（哪个源 / provider、连续几天零产），并说明它们连续 3 天没有贡献任何进入正文的条目，可以从对应脚本的 `RSS_SOURCES`（X 热点是 `sources.py` 的 provider）里移除或更换，问用户要不要处理。没有告警就完全不提这一节。

注意：不修改任何脚本或 plist；同一块的 fetch/send 不要重复跑。任一块因代理/数据问题未出，其余照常处理，互不阻塞。