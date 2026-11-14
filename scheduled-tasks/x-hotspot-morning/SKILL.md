---
name: x-hotspot-morning
description: 每天早 08:30 抓取过去 48 小时 Latent Space AINews（Twitter Recap）与 Techmeme 同期报道，提炼 1–4 个 X 圈真实技术/产品分歧并推送至飞书
---

目标：每天早上 08:30（独立于下午 `ai-daily-afternoon`，覆盖隔夜美国时间更新的 Latent Space `[AINews]` Twitter Recap），提炼「AI 圈昨天深夜到今天凌晨在吵什么」，给出「有人说 A、也有人说 B」的分歧拆解并推送到飞书（与 `AI Daily News Bot` 共用同一个飞书 webhook）。

**时间线**：每天 08:30 触发（主力）→ 09:30 由 `com.shirley.x-hotspot-bot-health` 执行轻量化健康检查（方案 B：不再拉起无头 CLI；若关机/休眠错过 08:30，开机唤醒后由 Antigravity Sidecar 自动补跑）。

**素材窗口与体例（48 小时窗口）**：
- 主素材来自 `latent.space/feed` 的最新一期 `[AINews]` 邮件复盘（`news.smol.ai` 已停服退居末位兜底），`DEFAULT_WINDOW_H = 48`（次早 08:30 稳定覆盖前一美股工作日夜间发表的新刊）；
- AINews 常见体例是「每天只挑一两个最大的事件往深里扒」，**话题数量控制在 1–4 条**：单话题日专注深扒 1 条，多话题日选最热的 2–4 条，切勿为了凑数硬拼边角料；
- `=== TECHMEME_BEGIN/END ===` 仅作主媒对照，判断话题是否只是小圈层热议；对照不上就整块不用，不硬塞新闻。

⚠️ **三条工具与排版铁律：**
1. **防截断**：执行 `fetch` 后，完整输出已自动落盘到 `/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/last_context.txt`。请直接使用 `read_file` 读取 `logs/last_context.txt`，严禁重复执行 `fetch`。
2. **防 `$` 变量吞字**：写稿落盘时，必须使用 `write_file`（`Overwrite: true`）写入 `/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/report_draft.txt`，严禁使用 `cat <<EOF` 或 `echo`。
3. **正文人物/机构行内加链接 + 末尾单条主原帖直链**：
   - 正文中所有提到且素材给出明确链接的**机构、评测方、研究者、开发者或 `@handle`**（如 `Artificial Analysis`、`@skalskip92`、`@simonw` 等），必须随文直接使用 `<a href="URL">名字/@handle</a>` 超链接（严禁只放文末而正文留空无链接）；
   - 每条话题末尾的 `原帖：` 行**仍只选被引用次数最多的那 1 条 `x.com/<user>/status/<id>` 原帖直链**，格式：`原帖：<a href="{x.com 直链}">@{handle}</a>（当天复盘被引用 {N} 次）`，不堆砌多条末尾原帖；
   - **禁止把「被引用 N 次」写成「点赞数 / 最高赞」**，那是 AINews 当天复盘里的引用中心度；
   - 正文仅使用 `<b>` 和 `<a href>` 标签，严禁使用 Markdown `**`。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 执行步骤

### 步骤 1 — 取材
```bash
bash "/Users/jialiwu/.gemini/bots/x-hotspot-bot/claude_report.sh" fetch
```
按 stdout 标记决定：
- `=== SKIP_ALREADY_RAN ===`：今天已推送过。记「已跳过」，停止执行。
- `=== SKIP_PROXY ===`：本地代理不可用（需检查 `127.0.0.1:1082`）。**不要继续**，记「代理不可用未推送」。
- `=== NO_TOPICS ===`：48 小时窗口内 Latent Space `[AINews]` 无未播新刊（如周末/停更，或最新一期已播过）。**不要继续写稿或推送**，直接记「未检测到上游 AINews 新刊，今日跳过推送」。
- `=== FETCH_OK ===`：使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/last_context.txt`，提取 `=== CONTEXT_BEGIN ===` 与 `=== CONTEXT_END ===` 之间内容，进入步骤 2。

若出现 `=== SOURCE_ALERT ===` 与 `=== SOURCE_ALERT_END ===`，原样记下并在汇报末尾单列一节「源健康」。

### 步骤 2 — 写稿
1. 使用 `read_file` 读取 `/Users/jialiwu/.gemini/bots/x-hotspot-bot/prompt.md`。
2. 严格按其全部规则与上述硬约束，基于 `last_context.txt` 写出完整《X 热点播报》。
3. 使用 `write_file`（`Overwrite: true`）将纯正文写入 `/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/report_draft.txt`。

### 步骤 3 — 发送
```bash
bash "/Users/jialiwu/.gemini/bots/x-hotspot-bot/claude_report.sh" send
```
脚本内部通过 `send_x_linked_report` 校验稿件必含真实 `x.com` status 链接并按段落自动分卡推送。

### 步骤 4 — 核对
`tail -1 "/Users/jialiwu/.gemini/bots/x-hotspot-bot/logs/run.log"`：
- 若出现 `[OK] ...` → 记「已推送成功」；
- 若出现 `[FAIL] 稿件里没有任何 x.com 原帖链接` → **回步骤 2 补齐从素材原样复制的 `x.com` status 链接**，然后重跑 `send`（禁止重跑 `fetch`）；
- 其他 `[FAIL]` / `[WARN]` → 记失败并附该行日志。
