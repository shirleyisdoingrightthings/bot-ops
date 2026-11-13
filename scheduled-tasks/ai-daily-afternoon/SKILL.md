---
name: ai-daily-afternoon
description: 每天 15:00 写稿并推送 AI 产业日报与 AI Builder 日报（统一 Flash 模型；X 热点已拆至每天早 08:30 独立运行）
---

目标：AI 下午两块内容由本任务（Flash 模型）每天 15:00 串行完成抓取、写稿与飞书推送：
1. **A：AI 产业日报**（媒体报道了什么 —— **每日统一出《AI 产业日报》，已永久取消周日周回顾**）
2. **B：AI Builder 日报**（一线研究员 / 创始人 / 工程师本人发了什么与长文）

> **⚠️ 分工与独立调度说明：**
> - 《X 热点播报》已移至每天早 **08:30** 的 `x-hotspot-morning` 任务独立运行（48h 窗口），**本任务不要再去跑 `x-hotspot-bot`**。
> - 《美股收盘 & 加密行情日报》在 `morning-catchup-daily-bots`（周二至周六 10:00）、《A股 & 港股》在 `cn-hk-*`、《GitHub & HN》在 `github-hn-morning`（09:30），**均与本任务无关**。
> - 本任务两块内容发往同一个飞书 webhook（「AI 产业日报」机器人），但拥有各自独立的脚本、去重档案与 `run.log`。**必须先写 A（产业日报）再写 B（AI Builder）**，写 AI Builder 时主动避开重复。

**时间线**：每天 15:00 触发（主力）→ 16:00 由 `com.shirley.ai-chain-health` 串行检查 `AI Daily News Bot` 与 `ai-builder-bot` 两块运行状态（方案 B：仅核查状态与 `drafts_fresh` 本地重发兜底，不拉起无头 CLI；开机唤醒补跑由 Antigravity Sidecar 自行负责）。

工作根目录是 `/Users/jialiwu/.gemini/bots`，共享层在 `/Users/jialiwu/.gemini/bots/shared/`。

⚠️ **两条工具执行铁律（防截断 & 防 `$` 吞字）：**
1. **防截断**：执行 `fetch` 后，完整输出已自动落盘到各 bot 的 `logs/last_context.txt`。请直接使用 `read_file` 读取 `logs/last_context.txt`，严禁重复执行 `fetch`（重跑会重复消耗请求且累加零产计数）。
2. **防 `$` 变量吞字**：写稿落盘时，必须使用 `write_file`（`Overwrite: true`）写入各 bot 的 `logs/report_draft.txt`，严禁使用 `cat <<EOF` 或 `echo`。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 第一部分之 A：AI 产业日报（Flash 写 1 稿）

**每日统一出《AI 产业日报》（包括周日，亦按当日客观新闻出日报，不再出周回顾）。** 全局唯一周趋势回顾已收敛至周日 `github-hn-morning`。

### 步骤 1 — 抓取
```bash
bash "/Users/jialiwu/.gemini/bots/AI Daily News Bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入第二部分（AI Builder）。
- `=== SKIP_PROXY ===`：本地代理不可用（需检查 `127.0.0.1:1082`）。**不要继续**，记「代理不可用未推送」，直接进入第二部分。
- `=== NO_NEWS ===`：24 小时无有效新闻。**不要继续**，记「无有效新闻」，进入第二部分。
- `=== FETCH_OK ===`：使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/last_context.txt`，提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容，进入步骤 2。

另外：`=== SOURCE_ALERT ===` 与 `=== SOURCE_ALERT_END ===` 之间若有内容，说明某 RSS 源连续 3 天以上零产，**原样记下**并在汇报最后单列一节「源健康」。

### 步骤 2 — 写当日日报（`FETCH_OK` 时）
1. 使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/AI Daily News Bot/prompt.md`。
2. 严格按其全部规则写出完整《AI 产业日报》：
   - 仅使用 `<b>` 和 `<a href>` 标签，严禁使用 Markdown `**`；
   - 标题使用 `<b>📋 AI 产业日报 · [今天日期]</b>` 与 `<b>⚡ 30秒速览</b>`；
   - 「⚡ 30秒速览」下方空一行后接 5 条以「- 」开头的无序列表（无 ⭐、每条 ≤55 字且含具体数字/专名、与正文前 5 条一一对应）；
   - 正文严格按 5星至3星倒序，**最多入选 12 条**（按 5分 > 4分 > 3分 截断），英文原标题不翻译，`📄 The Details：` 后紧接单段高密度连贯叙事（禁止 bullet，禁止叙事段落内部使用冒号）；
   - 必须使用 context 里的「今天日期」。
3. 使用 `write_file`（`Overwrite: true`）将纯正文写入 `/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/report_draft.txt`。

### 步骤 3 — 发送
```bash
bash "/Users/jialiwu/.gemini/bots/AI Daily News Bot/claude_report.sh" send
```
超长时脚本会自动按段落分卡并加 `(n/N)` 页码，无需人工切分。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/AI Daily News Bot/logs/run.log"`：末行 `[OK] ...` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 第二部分之 B：AI Builder 日报（Flash 写 1 稿）

本块播的是 **X 上一线 AI builder 本人最近说了什么与技术长文**，与产业日报「媒体报道了什么」严格分工。排在 A 之后写，主动避开重复或补充一线本人视角。

### 步骤 1 — 取材
```bash
bash "/Users/jialiwu/.gemini/bots/ai-builder-bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入汇报。
- `=== SKIP_PROXY ===`：本地代理不可用。**不要继续**，记「代理不可用未推送」。
- `=== FEED_ERROR ===`：上游 feed 拉不到。**不要继续**，记「素材源不可用未推送」并附错误。
- `=== NO_TWEETS ===`：feed 里没有新推文。**不要继续**，记「无可用素材」。
- `=== FETCH_OK ===`：使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/ai-builder-bot/logs/last_context.txt`，提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容，进入步骤 2。

**⚠️ 关于 feed 与推文时间区间：**
- 上游 `follow-builders` CI 在北京时间 **14:17** 生成，我们 15:00 取正常滞后约 45 分钟；若某天延迟仍可能是前一天数据。
- **稿子开头必须按 context 里的「推文实际时间区间」如实写明日期**，若出现 `=== FEED_STALE ===` 滞后超过 36 小时需在汇报中标注。

### 步骤 2 — 写稿
1. 使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/ai-builder-bot/prompt.md`。
2. 严格按其全部规则写出完整《AI Builder 日报》：
   - 每条话题至少带一条从素材 `[原推]` 字段原样复制的 `x.com/<user>/status/<id>` 直链；若引用 builder 个人技术长文，附 `长文：<a href="{博客直链}">{作者/博客}：《{标题}》</a>`（注意 `send` 仍要求全文至少包含 1 条 `x.com` 原推链接）；
   - 赞/转/回是 X 上真实互动量，可照实写；
   - 开头第一行写明这批推文的实际日期；文末数据注脚标明覆盖条数（含博客长文数时写 `+ {N} 篇长文`）；
   - 只用 `<b>` 和 `<a href>` 标签；英文人名、handle、公司名、模型名不翻译。
3. 使用 `write_file`（`Overwrite: true`）将纯正文写入 `/Users/jialiwu/.gemini/bots/ai-builder-bot/logs/report_draft.txt`。

### 步骤 3 — 发送
```bash
bash "/Users/jialiwu/.gemini/bots/ai-builder-bot/claude_report.sh" send
```

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/ai-builder-bot/logs/run.log"`：末行 `[OK] ...` → 记「已推送成功」；
若末行是 `[FAIL] 稿件里没有任何 x.com 原推链接` → **回步骤 2 补齐原推直链后重跑 `send`**（禁止重跑 `fetch`）；其余 `[FAIL]`/`[WARN]` 记失败并附该行。

━━━━━━━━━━━━━━━
## 汇报格式

用中文简要汇报本任务负责的两块：

```text
AI 下午场日报（产业日报 + AI Builder）
  · 产业日报：{状态}
  · AI Builder：{状态}
```

状态取其一：
- 已推送成功（附 run.log 末行摘要）
- 已跳过（今天已推送）
- 未推送（无有效新闻 / 代理不可用 / 素材源不可用，注明哪种）
- 无可用素材（AI Builder 窗口内没抓到推文）
- 已推送成功（素材滞后 N 天/小时）
- 失败（附原因与日志末行）

若任一块出现 `SOURCE_ALERT`，在状态后单列一节「源健康」原样列出；没有则不提。
注意：不修改任何脚本或 plist；同一块的 fetch/send 不要重复跑；任一块失败不阻塞另一块。
