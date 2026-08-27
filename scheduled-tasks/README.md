# scheduled-tasks — Claude 定时任务的备份

三个 bot 的**唯一写稿入口**是 Claude 定时任务（routine），它的 prompt 存放在
`~/.claude/scheduled-tasks/<taskId>/SKILL.md`——那个目录**不属于任何 git 仓库**。
换电脑或重装 Claude 后这些 prompt 会一起消失，三个 bot 的脚本再完整也跑不出稿。
本目录就是它们的版本化副本，与 `bot_utils.py` 当年丢失后被纳入版本控制是同一个理由。

## 内容

| 路径 | taskId | 调度 | 作用 |
|---|---|---|---|
| `morning-catchup-daily-bots/SKILL.md` | `morning-catchup-daily-bots` | 每天 10:00（cron `0 10 * * *`） | 主力写稿入口：依次跑 AI 产业日报（周日改出周回顾）、Crypto 日报、美股日报，抓取 → Claude 写稿 → 推送 |

`manual-resend-daily-bots`（手动补发）与历史上的一次性任务尚未纳入备份，需要时再加。

## 恢复

在一台新机器上（已装好 Claude、已放好 `~/Desktop/bots/`）：

```bash
mkdir -p ~/.claude/scheduled-tasks/morning-catchup-daily-bots
cp ~/Desktop/bots/shared/scheduled-tasks/morning-catchup-daily-bots/SKILL.md \
   ~/.claude/scheduled-tasks/morning-catchup-daily-bots/
```

`SKILL.md` 只有 prompt 正文与 frontmatter，**不含调度信息**。恢复后还要在 Claude 里
把这个任务重新设为每天 10:00 触发，否则它只会以「手动」状态存在、不会自己跑。

另外这三件东西也不在任何仓库里，换机时要一并处理：
- `~/Library/LaunchAgents/com.shirley.*-bot.plist`（飞书 webhook 与代理端口的权威源，含密钥，**不要**提交到仓库）
- `~/Library/LaunchAgents/com.shirley.*-bot-health.plist`（11:00 体检的调度）
- 各 bot 的 `logs/`（含 `sent_urls.json` 跨天去重档案与 `archive/` 稿件存档，丢了不影响运行，只是去重与周回顾要重新攒）

## 同步纪律

这里的副本是**快照，不是软链**（软链会被写入操作替换成普通文件，静默失效，所以没这么做）。
在 Claude 里改完 routine 的 prompt 后，记得手动同步回来并提交：

```bash
cp ~/.claude/scheduled-tasks/morning-catchup-daily-bots/SKILL.md \
   ~/Desktop/bots/shared/scheduled-tasks/morning-catchup-daily-bots/
```

用下面这行随时检查有没有漂移（无输出即一致）：

```bash
diff ~/.claude/scheduled-tasks/morning-catchup-daily-bots/SKILL.md \
     ~/Desktop/bots/shared/scheduled-tasks/morning-catchup-daily-bots/SKILL.md
```
