# bot-ops — 每日播报 Bot 的共享运行层

Crypto Daily Bot、AI Daily News Bot 与 US Stock Bot 共用的工具与自愈逻辑。三个 bot 仓库
（`crypto-daily-bot`、`AI-Daily-News-Bot`、`us-stock-bot`）各自独立，但通过本目录共享"形式和运行方式"：
改这里的代码，三个 bot 同时生效。

> ⚠️ 备份教训：本目录原本不在任何 GitHub 仓库里，换电脑时 `bot_utils.py` 丢失、
> 整套工作流跑不起来。现已单独纳入版本控制，**改动后请记得 commit + push**。

> 📍 当前位置：`~/Desktop/bots/shared/`，与三个 bot 同级。各 bot 用 `Path(__file__).resolve().parent.parent / "shared"`
> 从脚本自身位置推导本目录，因此整个 `bots` 文件夹搬到任何位置都不需要改代码（launchd plist 因格式限制仍需绝对路径）。


## ⚠️ launchd 的日志路径不能放在 Desktop 下

2026-08-30 排查发现三个 `com.shirley.*-bot-health` job 连续 11 天 `last exit code = 78 (EX_CONFIG)`，
`health_check.log` 最后一条停在 08-19——**整套体检 + auto_repair + claude_catchup 的安全网静默失效了 11 天**，
而唯一的告警渠道恰好也是它自己。

根因不在脚本：同一个 Label、同一份 plist，只把 `StandardOutPath` 换个位置就从 78 变成 0。
`~/Desktop/bots/*/logs/health_check.log` 被 TCC 打上了 `com.apple.macl`（按文件授权标记，
`~/Desktop`、`~/Documents`、`~/Downloads` 都受保护），launchd 打不开它，连 bash 都没 exec 就直接 EX_CONFIG。
被任何有 TCC 权限的 App 打开过一次就会复现。

处置与约定：
- 三个 health plist 的 `StandardOutPath`/`StandardErrorPath` 一律指向 `~/Library/Logs/bots/<job>.log`，
  各 bot 的 `logs/health_check.log` 留成指向该文件的软链，习惯与文档里的路径继续可用。
- **以后新增任何 LaunchAgent，输出重定向都不要写进 Desktop/Documents/Downloads。**
- plist 含 Token 故被 `.gitignore` 排除，这条约定只能记在这里；换机重建 plist 时务必照做。
- 排查手法：把 plist 复制一份、只改 `StandardOutPath` 到 `/tmp`、换个 Label 后 `launchctl bootstrap`，
  若 exit code 变 0 就说明问题出在输出文件而不是脚本。


## 内容

| 文件 | 作用 |
|---|---|
| `alert.py` | 把一条运维告警发到飞书，供各 bot 的 `health_check.sh` 调用。用法 `alert.py <bot名> <FAIL\|WARN\|INFO> <正文>`；webhook 取 `FEISHU_ALERT_WEBHOOK`，未设则回退 `FEISHU_WEBHOOK`。**任何情况下都以 0 退出**——告警发不出去不该让体检中断。 |
| `bot_utils.py` | 三个 bot 共用的工具函数，分五组：<br>**基础** `sanitize_html` / `with_retry` / `fetch_rss` / `parse_entry_date` / `already_ran_today`<br>**取材** `fetch_article_text`（best-effort 抓正文全文，零依赖）<br>**跨天去重** `url_key` / `load_sent_urls` / `record_sent_urls` / `extract_hrefs`<br>**选题过滤** `is_ai_relevant`（AI 相关性）/ `is_market_relevant`（美股相关性），均只给泛源用<br>**推送与监控** `html_to_lark_md`（HTML 稿件 → 飞书卡片 markdown）/ `paginate_feishu`（20KB 切分 + 页码 + 长度均衡）/ `send_feishu`（带签名直连推送）/ `update_zero_streak`（连续零产追踪）/ `resolve_proxy`（代理端口自愈）<br>**主脚本公共构件** `make_logger`（绑定路径的 write_log）/ `make_pending_saver` / `proxy_ok`（代理预检+自愈，返回生效代理）/ `emit_fetch_output`（fetch 的 stdout 一次性输出并落盘 `logs/last_context.txt`） |
| `auto_repair_base.sh` | 共享两级自愈逻辑：Level 1 瞬时错误等 30s 重跑；Level 2 调 Claude CLI 诊断修复后重跑；仍失败则移交无头补跑 |
| `headless_catchup_base.sh` | 共享无头补跑逻辑：用本机 `claude` CLI 无人值守完整重走 fetch → 写稿 → send，等价于手动 Run Now |
| `scheduled-tasks/` | Claude 定时任务 prompt 的版本化副本（原件在 `~/.claude/scheduled-tasks/`，不属于任何仓库，换机即丢）。恢复步骤与同步纪律见该目录 README |

## 三个 bot 如何引用本目录

- Python：脚本顶部 `sys.path.insert(0, ~/Desktop/bots/shared)` 后 `from bot_utils import ...`
- Shell：各 bot 的 `auto_repair.sh` / `claude_catchup.sh` 薄包装设好变量后
  `source ~/Desktop/bots/shared/auto_repair_base.sh`（或 `headless_catchup_base.sh`）

## 每日时间线

| 时间 | 环节 | 执行者 |
|---|---|---|
| 10:00 | 主力：三个 bot 依次抓取 → Claude 写稿 → 推送飞书 | Claude App 定时任务 `morning-catchup-daily-bots`（prompt 备份在 `scheduled-tasks/`） |
| 11:00 | 体检：当天无 `[OK]` 则自愈 / 无头补跑 | launchd `com.shirley.*-bot-health` |
| 随时 | 人工补发 | Claude App 手动任务 `manual-resend-daily-bots` |

各 bot 的主 plist（`com.shirley.*-bot`）**不再承担调度职责**，仅作为密钥与代理的
环境变量配置源供脚本读取。

> ⚠️ launchd 陷阱（2026-07-23 修复）：`health_check.sh` 原来用 `bash xxx.sh &`
> 起后台子进程再自己 exit，而 **launchd 在 job 主进程退出时会回收整个进程组**，
> 子进程当场被杀。结果是自愈与补跑"日志上写了触发、实际从未执行"。现已全部改为
> 前台调用。在本项目里加 launchd 触发的后台任务时务必注意这一点。

## 跨天去重与源淘汰

三个 bot 的时间窗（AI 24h / Crypto 3 天 / 美股 48h）都拦不住"同一条新闻连续多天入选"，
因为脚本内的 `seen_urls` 只在单次运行内有效。现由共享层统一处理：

- **去重**：`send` 成功后从稿件里抽 `<a href>` 记入各 bot 的 `logs/sent_urls.json`
  （保留 7 天），下次 `fetch` 据此排除。归档点在发送成功之后，发失败的那批不会被
  误标成"已播"。
- **源淘汰**：`fetch` 统计每个源"过滤后还剩几条"，连续 3 天零产即在 stdout 输出
  `=== SOURCE_ALERT ===` 块并写入 metrics，提示该源可以移除或更换。
  连续天数由 `fetch` 单点写入 `logs/.zero_streak.json`，health_check 只读不写。

## 关于密钥

本目录**不含任何密钥**。所有 API key / Token 由各 bot 的 launchd plist 通过环境变量注入，
脚本只 `os.getenv(...)` 读取。

## Level 2（Claude 自愈）开关

由各 bot 的 health plist 环境变量 `ENABLE_CLAUDE_REPAIR` 控制（`1`=开 / 缺省=关）。
依赖本机已安装并登录的 `claude` CLI；`auto_repair_base.sh` 会按多路径探测其绝对位置。
