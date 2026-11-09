---
name: github-hn-morning
description: 每天早 09:30 自动抓取 GitHub Trending（周一至周六 Daily / 周日 Weekly）与 Hacker News Top 5，由 Flash 模型写稿并推送到飞书
---

目标：每天早上 09:30（在 10:00 美股 & 加密行情日报之前），由本任务自动抓取 GitHub Trending 榜单与 Hacker News 24h 热榜前五，统一使用 **Flash 模型** 写稿并推送至飞书。

- **模型固定为 Flash**：若当前会话默认模型是 Flash 则直接写稿；若当前会话默认是其他模型，可调用 `invoke_subagent(TypeName="self", Model="flash")` 交由 Flash 模型快速写稿落盘。
- **周一至周六（`=== FETCH_OK ===`）**：推送《GitHub Daily 今日飙升榜 + Hacker News 热榜 Top 5》（读 `prompt.md`）。不单列“持续霸榜”模块，但遇到前几天已经推送过的重复项目/热帖时，保留在榜单中简述 1～2 句并注明 `<b>（见 MM月DD日 推送）</b>`。
- **周日（`=== WEEKLY_OK ===`）**：推送《GitHub Weekly 本周趋势榜 + Hacker News 热榜 Top 5》（读 `prompt_weekly.md`）。包含「🔥 持续霸榜」模块。

**时间线**：每天 09:30 触发（主力）→ 10:30（或电脑开机唤醒时）由 `com.shirley.github-hn-bot-health` 检查当日是否已推送，若 09:30 因关机/休眠未跑，则自动调用 `claude_catchup.sh` 无头补跑。

⚠️ **两条工具执行铁律（防截断 & 防 `$` 吞字）：**
1. **防截断**：执行 `fetch` 后，完整输出已自动落盘到 `/Users/jialiwu/.gemini/bots/github-hn-bot/logs/last_context.txt`。若终端 stdout 显示不全或被截断，**直接使用 `read_file` 工具读取 `logs/last_context.txt`**，严禁重跑 `fetch`。
2. **防 `$` 变量吞字**：写稿落盘时，**必须使用 `write_file` 工具（设置 `Overwrite: true`）** 写入 `/Users/jialiwu/.gemini/bots/github-hn-bot/logs/report_draft.txt`，**严禁使用 `bash` 的 `cat <<EOF` 或 `echo` 写文件**。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 执行步骤

### 步骤 1 — 抓取
执行命令（若沙箱拦截本地代理 `127.0.0.1:12450`，请使用 `BypassSandbox: true`）：
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
   - 仅使用 `<b>` 和 `<a href="URL">` 标签，严禁使用 Markdown `**` 或代码块。
   - 状态标为 `🆕 首次上榜` 的项目/帖子完整展开；状态标为 `🔁 重复霸榜 / 重复在榜（首次见于 MM月DD日 推送）` 的项目/帖子用 1～2 句话简述并注明 `<b>（见 MM月DD日 推送）</b>`。
3. 使用 `write_file`（`Overwrite: true`）将纯正文写入 `/Users/jialiwu/.gemini/bots/github-hn-bot/logs/report_draft.txt`。

### 步骤 3 — 发送
```bash
bash "/Users/jialiwu/.gemini/bots/github-hn-bot/claude_report.sh" send
```

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/github-hn-bot/logs/run.log"`：末行 `[OK] ...` → 记「已推送成功」；`[FAIL]`/`[WARN]` → 记失败并附该行。
