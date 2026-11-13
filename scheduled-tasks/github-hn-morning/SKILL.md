---
name: github-hn-morning
description: 每天早 09:30 自动抓取 GitHub Trending（周一至周六 Daily / 周日 Weekly）与 Hacker News Top 8，由 Flash 模型写稿并推送到飞书
---

目标：每天早上 09:30（在 10:00 美股 & 加密行情日报之前），由本任务自动抓取 GitHub Trending 榜单与 Hacker News 24h 热榜 Top 8（融合 `Best` 高赞榜与 `Top` 实时热议榜），统一使用 **Flash 模型** 写稿并推送至飞书。

- **模型固定为 Flash**：若当前会话默认模型是 Flash 则直接写稿；若当前会话默认是其他模型，可调用 `invoke_subagent(TypeName="self", Model="flash")` 交由 Flash 模型快速写稿落盘。
- **周一至周六（`=== FETCH_OK ===`）**：推送《GitHub Daily 今日飙升榜 + Hacker News 热榜 Top 8》（读 `prompt.md`）。不单列“持续霸榜”模块，遇到前几天已经推送过的重复项目/热帖时，保留在榜单中精简 1 句话总结并注明 `<b>（见 MM月DD日 推送）</b>`。
- **周日（`=== WEEKLY_OK ===`）**：推送《GitHub Weekly 本周趋势榜 + Hacker News 热榜 Top 8》（读 `prompt_weekly.md`），含「🔥 持续霸榜」模块（全局唯一周趋势回顾）。

**时间线**：每天 09:30 触发（主力）→ 10:30 由 `com.shirley.github-hn-bot-health` 执行轻量化健康检查（方案 B：不再拉起无头 CLI，若草稿已存在且新鲜仅做 Level 1 重发；电脑关机/休眠错过调度时，开机后由 Antigravity Sidecar 唤醒补跑）。

⚠️ **三大执行与排版铁律：**
1. **防截断**：执行 `fetch` 后，完整输出已自动落盘到 `/Users/jialiwu/.gemini/bots/github-hn-bot/logs/last_context.txt`。若终端 stdout 显示不全或被截断，**直接使用 `read_file` 工具读取 `logs/last_context.txt`**，严禁重跑 `fetch`。
2. **防 `$` 变量吞字**：写稿落盘时，**必须使用 `write_file` 工具（设置 `Overwrite: true`）** 写入 `/Users/jialiwu/.gemini/bots/github-hn-bot/logs/report_draft.txt`，**严禁使用 `bash` 的 `cat <<EOF` 或 `echo` 写文件**。
3. **飞书排版美学与归属性**：
   - ① **大板块之间必有空行**：「⚡ 30秒速览」、「🚀 一、GitHub 今日飙升榜」、「🔥 二、Hacker News 热榜」三大板块之间**必须空一行隔开**；大标题下方紧贴第一条内容无空行；
   - ② **每个 Top 之间必有空行**：GitHub 各仓库（1 与 2、2 与 3...）以及 HN 各热帖之间**必须空一行隔开**，条理清晰；
   - ③ **单个 Top 内部绝无空行**：项目内部（标题、场景定位、适用建议、它是干嘛的、个人 Build 姿势）以及 HN 热帖内部（标题、Original、这帖在聊啥、评论区在吵啥）**必须紧凑提行，严禁多余空行**，绝不脱节。
   - ④ **标题加粗规范**：链接本身不嵌套在 `<b>...</b>` 内部，一律写成 `<b>1.</b> <a href="URL"><b>项目或标题</b></a>`（保证项目名加粗且兼容飞书渲染）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 执行步骤

### 步骤 1 — 抓取
执行命令（若沙箱拦截本地代理 `127.0.0.1:1082`，请使用 `BypassSandbox: true`）：
```bash
bash "/Users/jialiwu/.gemini/bots/github-hn-bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，进入汇报。
- `=== SKIP_PROXY ===`：代理不可用。**不要继续**，记「代理不可用未推送」。
- `=== NO_DATA ===`：未抓到有效数据。**不要继续**，记「数据缺失未推送」。
- `=== FETCH_OK ===`（周一至周六日榜）或 `=== WEEKLY_OK ===`（周日周榜）：
  使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/github-hn-bot/logs/last_context.txt`，提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容，进入步骤 2。

### 步骤 2 — 写稿（Flash 模型）
1. 若为 `=== FETCH_OK ===`，使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/github-hn-bot/prompt.md`；
   若为 `=== WEEKLY_OK ===`，使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/github-hn-bot/prompt_weekly.md`。
2. 严格按对应规范写稿：
   - 仅使用 `<b>` 和 `<a href="URL">` 标签（文字里的 `&` 直接写 `&`，不要手写 `&amp;`），严禁使用 Markdown `**` 或代码块。
   - 开头的「<b>⚡ 30秒速览</b>」为独立小标题，下方空一行后接 3 条无序列表内容（每行均以「- 」开头分行排列，严禁与标题粘在同一行）。
   - GitHub 项目单列场景定位与适用建议，采用「痛点+机制+对比」大白话叙述，启发升级为具象的「个人 Build 姿势」并敢于劝退（`🛠️ 适用建议` 已写明劝退的条目，`个人 Build 姿势` 不再重复贴 `[仅供吃瓜/科研劝退]` 标签）；HN 热榜提炼「这帖在聊啥」与「评论区在吵啥」。
   - 状态标为 `🆕 首次上榜` 的项目/帖子完整展开；状态标为 `🔁 重复霸榜 / 重复在榜（首次见于 MM月DD日 推送）` 的项目/帖子保留名次、用 1 句话精简说明并注明 `<b>（见 MM月DD日 推送）</b>`。
3. 使用 `write_file`（`Overwrite: true`）将纯正文写入 `/Users/jialiwu/.gemini/bots/github-hn-bot/logs/report_draft.txt`。

### 步骤 3 — 发送
```bash
bash "/Users/jialiwu/.gemini/bots/github-hn-bot/claude_report.sh" send
```

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/github-hn-bot/logs/run.log"`：末行 `[OK] ...` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。
