# bot-ops — 每日播报 Bot 的共享运行层

五个播报 bot 共用的工具与自愈逻辑。各 bot 仓库独立，通过本目录共享运行方式：
改这里，五个 bot 同时生效。

飞书群里只显示三个机器人：AI 产业日报、X 热点、AI Builder 三块推到同一个 webhook
（合称「AI 日报」），加密与美股各自独立。三块仍是三套脚本、三份去重档案、三个 run.log，
只是发送目标合并，任一块出问题不影响其余两块。

位置在 `~/Desktop/bots/shared/`，与各 bot 同级。各 bot 从脚本自身位置推导本目录，
所以整个 `bots` 文件夹可以随便搬（launchd plist 因格式限制仍需绝对路径）。

> 本目录原本不在任何 GitHub 仓库里，换电脑时 `bot_utils.py` 丢了、整套工作流跑不起来。
> 现已纳入版本控制，改动后记得 commit + push。

## 内容

| 文件 | 作用 |
|---|---|
| `bot_utils.py` | 共用工具函数，分五组：基础（`sanitize_html`、`fetch_rss`、`already_ran_today` 等）、取材（`fetch_article_text`）、跨天去重（`url_key` / `load_sent_urls` / `record_sent_urls`）、选题过滤（`is_ai_relevant` / `is_market_relevant`，只给泛源用）、推送与监控（`send_feishu`、`paginate_feishu`、`update_zero_streak`、`proxy_ok` 等）。逐个函数的说明见文件头 |
| `health_check_base.sh` | 体检的公共实现，各 bot 的 `health_check.sh` 是 30 行左右的薄封装。封装只声明差异点：`BOT_NAME` / `MAIN_PLIST` / `NO_NEWS_PATTERN` / `NO_NEWS_MSG`，可选 `STALE_KEY` / `ZERO_KEY` / `content_check()` |
| `auto_repair_base.sh` | 两级自愈：Level 1 瞬时错误等 30s 重跑；Level 2 调 Claude CLI 诊断后重跑；仍失败移交无头补跑 |
| `headless_catchup_base.sh` | 无头补跑：用本机 `claude` CLI 完整重走 fetch → 写稿 → send，等价于手动 Run Now |
| `alert.py` | 把一条运维告警发到飞书。用法 `alert.py <bot名> <FAIL\|WARN\|INFO> <正文>`，任何情况下都以 0 退出 |
| `scheduled-tasks/` | Claude 定时任务 prompt 的版本化副本（原件在 `~/.claude/scheduled-tasks/`，不属于任何仓库，换机即丢） |

## 各 bot 如何引用

- Python：`sys.path.insert(0, ~/Desktop/bots/shared)` 后 `from bot_utils import ...`
- Shell：`health_check.sh` / `auto_repair.sh` / `claude_catchup.sh` 三个入口都是薄封装，
  设好变量后 source 对应的 `*_base.sh`。逻辑一律写在共享层——往封装里塞逻辑，
  就是把复制粘贴的债重新背回来。

## 每日时间线

| 时间 | 环节 | 执行者 |
|---|---|---|
| 10:00 | 各 bot 依次抓取 → Claude 写稿 → 推送飞书 | Claude App 定时任务 `morning-catchup-daily-bots` |
| 11:00 | 体检：当天无 `[OK]` 则自愈 / 无头补跑 | launchd `com.shirley.*-bot-health` |

主 plist（`com.shirley.*-bot`）不再承担调度，只作为密钥与代理的环境变量配置源。

## 运维告警

WARN/FAIL 都发到单独的监测机器人，不进日报群——在各 bot 主 plist 里配
`FEISHU_ALERT_WEBHOOK` 即可（`health_check.sh` 只从主 plist 读 `FEISHU_*` 开头的键）。

缺跑扫描只写本地日志、不推送。当天缺跑由体检的 MISSING 分支负责通知，
历史缺跑不要再加回推送（原因见 `health_check_base.sh` 的 1.5 节注释）。

## 跨天去重与源淘汰

各 bot 的时间窗（AI 24h / Crypto 3 天 / 美股 48h / X 热点 48h）都拦不住"同一条新闻
连续多天入选"，因为脚本内的 `seen_urls` 只在单次运行内有效。由共享层统一处理：

- 去重：`send` 成功后从稿件抽 `<a href>` 记入各 bot 的 `logs/sent_urls.json`（留 7 天），
  下次 `fetch` 据此排除。归档在发送成功之后，发失败的那批不会被误标成"已播"。
- 源淘汰：`fetch` 统计每个源过滤后还剩几条，连续 3 天零产即输出 `=== SOURCE_ALERT ===`。
  连续天数由 `fetch` 单点写入 `logs/.zero_streak.json`，health_check 只读不写。

## 关于密钥

本目录不含任何密钥。所有 API key / Token 由各 bot 的 launchd plist 通过环境变量注入，
脚本只 `os.getenv(...)` 读取。

## 换机 / 排障

踩过的坑与处置办法在 [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md)：launchd 的日志路径
为什么不能放 Desktop、launchd 回收进程组、claude CLI 断链导致自愈静默失效。
换新机器或安全网没动静时先读那份。
