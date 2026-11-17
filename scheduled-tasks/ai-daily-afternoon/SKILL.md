---
name: ai-daily-afternoon
description: 每天 09:00 按 1. AI 产业日报 → 2. X 热点播报 → 3. AI Builder 日报 顺序三合一串行抓取、去重、写稿并推送至飞书（识别 Automation 选定模型并允许自主 Orchestrate）
---

目标：每天早上 **09:00**，由本任务在**同一个主控会话内**严格按 **`1. AI 产业日报 → 2. X 热点播报 → 3. AI Builder 日报`** 的先后顺序串行完成抓取、写稿、飞书推送与 Notion 归档。紧随其后的 `4. GitHub Trending & Hacker News` 将在 **09:30** 独立运行并读取本任务产出的当日去重账本。

- **模型识别与自主 Orchestrate 原则**：主会话直接识别并运行在用户在 Automations 界面为本任务选定的最新模型上（不硬编码模型版本）。主 Agent 拥有**自主 Orchestrate 权**：可根据当天内容复杂度自行决定由当前主模型直接完成，或通过 `invoke_subagent(TypeName="self", Model="flash" / "flash_lite")` 将常规整理、初稿起草等适合轻量化的环节委派给快速响应/轻量化子代理协同处理（若委派子代理写稿，主 Agent 须在 `send` 前完成核心事实、超链接不重不漏与排版把关）。

> **⚠️ 为什么严格按 `1. AI 产业日报 → 2. X 热点播报 → 3. AI Builder 日报` 串行执行？**
> 1. **第 1 棒《AI 产业日报》**：先把过去 24h 主流科技媒体报道的客观行业大事、发布、融资、政策播完，并在 `send` 成功后自动写入共享账本 `/Users/jialiwu/.gemini/bots/shared/logs/daily_topic_ledger.json`。
> 2. **第 2 棒《X 热点播报》**：完整拉取上游 Latent Space `[AINews]` 的 `AI Twitter Recap`（65,000 字符完整预算，不腰斩中间技术细节），并自动读取第 1 棒已播账本。定稿时**严格过滤掉单次顺带提及的噪音、吹水与次优先级内容**，只挑讨论中心度最高、存在真正正反方技术分歧的 1–4 个焦点议题；若某事件第 1 棒已报过客观背景，本篇只写社区正反交锋与实测质疑，并在 `send` 后将其主原帖与话题追加写入共享账本。
> 3. **第 3 棒《AI Builder 日报》**：通过 `twscrape` 直连拉取自建 X List（自动对 X Article 补调 `tweet_details` 拉取完整长文正文，并对独立技术博客外链调用 `fetch_article_text` 拉取正文摘要），同时在代码层自动过滤掉第 2 棒《X 热点播报》已用过的 `x.com` 推文。写稿时针对每位 Builder 的具体项目/长文独立成篇深写（每条 3–5 句详实拆解，严禁把两个不同人物/项目硬拼成一条），且遵守超链接“不重不漏”原则。

**时间线**：每天 09:00 触发（主力）→ 16:00 由 `com.shirley.ai-chain-health` 串行检查运行状态（方案 B：仅核查状态与 `drafts_fresh` 本地重发兜底，不拉起无头 CLI）。

工作根目录是 `/Users/jialiwu/.gemini/bots`，共享层在 `/Users/jialiwu/.gemini/bots/shared/`。

⚠️ **两条工具执行铁律（防截断 & 防 `$` 吞字）：**
1. **防截断**：执行 `fetch` 后，完整输出已自动落盘到各 bot 的 `logs/last_context.txt`。请直接使用 `read_file` 读取 `logs/last_context.txt`，严禁重复执行 `fetch`。
2. **防 `$` 变量吞字**：写稿落盘时，必须使用 `write_file`（`Overwrite: true`）写入各 bot 的 `logs/report_draft.txt`，严禁使用 `cat <<EOF` 或 `echo`。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 第一部分（第 1 棒）：AI 产业日报（写 1 稿）

**每日统一出《AI 产业日报》（包括周日，亦按当日客观新闻出日报，不再出周回顾）。**

### 步骤 1 — 抓取
执行命令（若遇沙盒配置报错或拦截网络/本地代理 `127.0.0.1:1082`，请使用 `BypassSandbox: true`）：
```bash
bash "/Users/jialiwu/.gemini/bots/AI Daily News Bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入第二部分（X 热点播报）。
- `=== SKIP_PROXY ===`：本地代理不可用。**不要继续**，记「代理不可用未推送」，进入第二部分。
- `=== NO_NEWS ===`：24 小时无有效新闻。**不要继续**，记「无有效新闻」，进入第二部分。
- `=== FETCH_OK ===`：使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/last_context.txt`，提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容，进入步骤 2。

另外：`=== SOURCE_ALERT ===` 与 `=== SOURCE_ALERT_END ===` 之间若有内容，原样记下并在汇报最后单列一节「源健康」。

### 步骤 2 — 写当日日报（`FETCH_OK` 时）
1. 使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/AI Daily News Bot/prompt.md`。
2. 严格按其全部规则写出完整《AI 产业日报》：
   - 仅使用 `<b>` 和 `<a href>` 标签，严禁使用 Markdown `**`；
   - 标题使用 `<b>📋 AI 产业日报 · [今天日期]</b>` 与 `<b>⚡ 30秒速览</b>`；
   - 「⚡ 30秒速览」下方空一行后接 5 条以「- 」开头的无序列表（无 ⭐、每条 ≤55 字且含具体数字/专名、与正文前 5 条一一对应）；
   - 正文严格按 5星至3星倒序，**最多入选 12 条**（按 5分 > 4分 > 3分 截断），英文原标题不翻译，每条严格按 `标题 (<a href="..."><b>...</b></a>) → [星级] [标签] → 📄 The Details：` 顺序排版，`📄 The Details：` 后紧接单段高密度连贯叙事（禁止 bullet，禁止叙事段落内部使用冒号）。
3. 使用 `write_file`（`Overwrite: true`）将纯正文写入 `/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/report_draft.txt`。

### 步骤 3 — 发送（自动写入当日跨 Bot 账本）
执行命令（若遇沙盒配置报错或拦截飞书/Notion 网络请求，请使用 `BypassSandbox: true`）：
```bash
bash "/Users/jialiwu/.gemini/bots/AI Daily News Bot/claude_report.sh" send
```

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/run.log"`：末行 `[OK] ...` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 第二部分（第 2 棒）：X 热点播报（写 1 稿）

本块抓取过去 48 小时 Latent Space `[AINews]` 完整 `AI Twitter Recap` 与 Techmeme 同期报道，提炼 X 圈真正高优先级的正反方技术/产品分歧。**排在第 1 棒《AI 产业日报》之后运行，自动读取当日账本去重。**

### 步骤 1 — 取材
执行命令（若遇沙盒配置报错或拦截网络/本地代理 `127.0.0.1:1082`，请使用 `BypassSandbox: true`）：
```bash
bash "/Users/jialiwu/.gemini/bots/x-hotspot-bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入第三部分（AI Builder）。
- `=== SKIP_PROXY ===`：本地代理不可用。**不要继续**，记「代理不可用未推送」，进入第三部分。
- `=== NO_TOPICS ===`：48 小时窗口内 Latent Space `[AINews]` 无未播新刊。**不要继续写稿或推送**，直接记「未检测到上游 AINews 新刊，今日跳过推送」，进入第三部分。
- `=== FETCH_OK ===`：使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/last_context.txt`，进入步骤 2。

### 步骤 2 — 筛优去噪与写稿
1. 使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/x-hotspot-bot/prompt.md`。
2. 严格按其全部规则写出完整《X 热点播报》：
   - **完整读取与强力去噪**：通读 `last_context.txt` 中完整抓取的 Latent Space `AI Twitter Recap`，**严格筛选讨论中心度最高（被引用次数多、存在真正正反交锋或第三方实测争议）的 1–4 个焦点话题**，果断剔除单次提及的边角料、营销吹水与次优先级噪音；
   - **承接第 1 棒去重**：对照顶部 `TODAY_LEDGER`，若某事已在第 1 棒《AI 产业日报》播过且无社区正反争论则直接跳过；若有激烈争议则直接切入正反方观点与实测数据，不重复复述新闻背景；
   - **行内链与文末单条主原帖**：正文中提到的具体争议方/评测方/研究者若素材有对应链接且不同于底部主原帖，随文挂 `<a href="URL">`；每条话题末尾 `原帖：` 行**只选被引用次数最多的那 1 条 `x.com/<user>/status/<id>` 原帖直链**（格式：`原帖：<a href="{x.com 直链}">@{handle}</a>（当天复盘被引用 {N} 次）`，切勿写成点赞数）。
3. 使用 `write_file`（`Overwrite: true`）将纯正文写入 `/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/report_draft.txt`。

### 步骤 3 — 发送（自动追加写入当日跨 Bot 账本）
执行命令（若遇沙盒配置报错或拦截飞书/Notion 网络请求，请使用 `BypassSandbox: true`）：
```bash
bash "/Users/jialiwu/.gemini/bots/x-hotspot-bot/claude_report.sh" send
```

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/run.log"`：末行 `[OK] ...` → 记「已推送成功」；其余记失败并附该行。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 第三部分（第 3 棒）：AI Builder 日报（写 1 稿）

本块播的是 **自建 X List 上一线 AI builder 本人最近说了什么**（含自动补拉的 X Article 完整长文与外链技术博客正文）。**排在第 1 棒《AI 产业日报》和第 2 棒《X 热点播报》之后运行，自动过滤前序已播原推并避开重复事件。**

### 步骤 1 — 取材
执行命令（若遇沙盒配置报错或拦截网络/本地代理 `127.0.0.1:1082`，请使用 `BypassSandbox: true`）：
```bash
bash "/Users/jialiwu/.gemini/bots/ai-builder-bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入汇报。
- `=== SKIP_PROXY ===`：本地代理不可用。**不要继续**，记「代理不可用未推送」。
- `=== FEED_ERROR ===`：X List 拉取失败或 Cookie 失效。**不要继续**，记「素材源不可用未推送」并附错误。
- `=== NO_TWEETS ===`：X List 过去 24h 窗口内没有新推文。**不要继续**，记「无可用素材」。
- `=== FETCH_OK ===`：使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/ai-builder-bot/logs/last_context.txt`，进入步骤 2。

### 步骤 2 — 写稿（独立深写 + 超链接不重不漏）
1. 使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/ai-builder-bot/prompt.md`。
2. 严格按其全部规则写出完整《AI Builder 日报》：
   - **一人一事独立深写（严禁异事拼盘）**：精选 5–6 条高含金量话题，每条只聚焦 **1 位 Builder 的 1 个具体项目/长文/技术判断**，写足 3–5 句（单条 180–320 字，全篇 1500–2500 字），充分利用 `[X Article 全文摘录]` 与 `[外链正文摘录]` 把具体工程痛点、技术机制、架构设计与核心数字写透；绝不把两个不同人物/项目硬凑成一条！
   - **超链接“不重不漏”铁律**：
     1. 底部 `原推：<a href="...">@handle</a>（N 赞）` 已经挂了主推文链接的作者本人，**正文中首次出现只写 `身份 + 姓名（@handle）` 纯文本，绝不重复挂与底部 `原推：` 相同的链接**；
     2. 正文行内 `<a href>` **只挂不同于底部主原推 URL 的增量链接**（如独立技术博客/论文/仓库外链、同一作者的第 2 条补充推文、或交锋中的第三方推文；且若正文中挂了同一作者的补充推文，底部 `原推：` 只放主推文 1 条，确保上下绝不重复）；
     3. 严禁单独挂 `x.com/i/article/...` 冗余链接。
   - **前序去重**：对照顶部 `TODAY_LEDGER`，若某件官宣/融资大事已在第 1 棒或第 2 棒播过且推文无额外一手技术拆解，直接跳过。
   - 开头第一行如实写明推文实际时间区间；文末注脚格式为 `<b>素材</b>：X List（{builder 数} 位 · {推文数} 条）· 覆盖 {时间区间}`。
3. 使用 `write_file`（`Overwrite: true`）将纯正文写入 `/Users/jialiwu/.gemini/bots/ai-builder-bot/logs/report_draft.txt`。

### 步骤 3 — 发送
执行命令（若遇沙盒配置报错或拦截飞书/Notion 网络请求，请使用 `BypassSandbox: true`）：
```bash
bash "/Users/jialiwu/.gemini/bots/ai-builder-bot/claude_report.sh" send
```

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/ai-builder-bot/logs/run.log"`：末行 `[OK] ...` → 记「已推送成功」；其余记失败并附该行。

━━━━━━━━━━━━━━━
## 汇报格式

用中文简要汇报本任务串行执行的三块：

```text
AI 早间 09:00 三合一流水线（产业日报 → X 热点 → AI Builder）
  · 1. AI 产业日报：{状态}
  · 2. X 热点播报：{状态}
  · 3. AI Builder：{状态}
```

状态取其一：
- 已推送成功（附 run.log 末行摘要）
- 已跳过（今天已推送 / 未检测到上游 AINews 新刊）
- 未推送（无有效新闻 / 代理不可用 / 素材源不可用，注明哪种）
- 无可用素材（窗口内没抓到推文）
- 失败（附原因与日志末行）

若任一块出现 `SOURCE_ALERT`，在状态后单列一节「源健康」原样列出；没有则不提。
注意：不修改任何脚本或 plist；同一块的 fetch/send 不要重复跑；任一块失败不阻塞下一块。
