# bot_ops — 每日播报 Bot 的共享运行层

Crypto Daily Bot 与 AI Daily News Bot 共用的工具与自愈逻辑。两个 bot 仓库
（`crypto-daily-bot`、`AI-Daily-News-Bot`）各自独立，但通过本目录共享"形式和运行方式"：
改这里的代码，两个 bot 同时生效。

> ⚠️ 备份教训：本目录原本不在任何 GitHub 仓库里，换电脑时 `bot_utils.py` 丢失、
> 整套工作流跑不起来。现已单独纳入版本控制，**改动后请记得 commit + push**。

## 内容

| 文件 | 作用 |
|---|---|
| `shared/bot_utils.py` | 两个 bot 共用的 6 个工具函数：`sanitize_html` / `with_retry` / `fetch_rss` / `parse_entry_date` / `already_ran_today` / `fetch_article_text`（best-effort 抓正文全文，零依赖） |
| `auto_repair_base.sh` | 共享两级自愈逻辑：Level 1 瞬时错误等 30s 重跑；Level 2 调 Claude CLI 诊断修复后重跑 |

## 两个 bot 如何引用本目录

- Python：脚本顶部 `sys.path.insert(0, ~/Desktop/bot_ops/shared)` 后 `from bot_utils import ...`
- Shell：各 bot 的 `auto_repair.sh` 薄包装设好 `BOT_NAME/SCRIPT/ERROR/DIR` 后 `source ~/Desktop/bot_ops/auto_repair_base.sh`

## 关于密钥

本目录**不含任何密钥**。所有 API key / Token 由各 bot 的 launchd plist 通过环境变量注入，
脚本只 `os.getenv(...)` 读取。

## Level 2（Claude 自愈）开关

由各 bot 的 health plist 环境变量 `ENABLE_CLAUDE_REPAIR` 控制（`1`=开 / 缺省=关）。
依赖本机已安装并登录的 `claude` CLI；`auto_repair_base.sh` 会按多路径探测其绝对位置。
