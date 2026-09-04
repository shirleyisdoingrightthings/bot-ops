# scheduled-tasks — Claude 定时任务的备份

三个 bot 的**唯一写稿入口**是两个 Claude 定时任务（routine），它们的 prompt 存放在
`~/.claude/scheduled-tasks/<taskId>/SKILL.md`——那个目录**不属于任何 git 仓库**。
换电脑或重装 Claude 后这些 prompt 会一起消失，三个 bot 的脚本再完整也跑不出稿。
本目录就是它们的版本化副本，与 `bot_utils.py` 当年丢失后被纳入版本控制是同一个理由。

## 内容

| 路径 | taskId | 调度 | 作用 |
|---|---|---|---|
| `morning-catchup-daily-bots/SKILL.md` | `morning-catchup-daily-bots` | 每天 10:00（cron `0 10 * * *`） | 加密日报 + 美股日报：抓取 → Claude 写稿 → 推送 |
| `ai-daily-afternoon/SKILL.md` | `ai-daily-afternoon` | 每天 15:00（cron `0 15 * * *`） | AI 日报三块（产业日报 / X 热点 / AI Builder），共用同一个飞书 webhook |

> **2026-09-04 拆分**：AI 日报原本挂在 `morning-catchup-daily-bots` 里、每早 10:00 一起跑。
> 因为 AI Builder 的上游 feed 到北京时间 14:17 才生成，10:00 跑永远只能拿到前一天那份，
> 所以拆成独立的 `ai-daily-afternoon` 并改到 15:00。两个任务互不相干，
> 各自是对应 bot 的唯一写稿入口，改其中一个时不要去动另一个。

`manual-resend-daily-bots` 与 8 月那两个一次性核对任务已于 2026-09-03 删除：
前者写于 07-20，描述里还在说「Telegram」「三个 bot」，与现状脱节；后两个是
用完即弃的一次性核对。需要临时补发时，直接对当天那块跑
`FORCE_RUN=1 bash <bot>/claude_report.sh send` 即可，不必再养一个常驻任务。

## 恢复

在一台新机器上（已装好 Claude、已放好 `~/Desktop/bots/`）：

```bash
for t in morning-catchup-daily-bots ai-daily-afternoon; do
  mkdir -p ~/.claude/scheduled-tasks/$t
  cp ~/Desktop/bots/shared/scheduled-tasks/$t/SKILL.md ~/.claude/scheduled-tasks/$t/
done
```

`SKILL.md` 只有 prompt 正文与 frontmatter，**不含调度信息**。恢复后还要在 Claude 里
把两个任务分别设为每天 10:00 与 15:00 触发，否则它们只会以「手动」状态存在、不会自己跑。

调度信息实际存在 app 自己的注册表里：
`~/Library/Application Support/Claude/claude-code-sessions/<sessionId>/<id>/scheduled-tasks.json`。
除 `cronExpression` 外还有 `cwd`、`model`、`permissionMode` 等字段，**`permissionMode:
bypassPermissions` 尤其关键**——缺了它，无人值守的那次运行会卡在权限确认上、当天就发不出稿。
2026-09-04 误删 routine 后重建时踩过这个坑：用创建接口新建的条目不带这个字段，需要手工补。

另外这几件东西也不在任何仓库里，换机时要一并处理：
- `~/Library/LaunchAgents/com.shirley.*-bot.plist`（飞书 webhook 与代理端口的权威源，含密钥，**不要**提交到仓库）
- `~/Library/LaunchAgents/com.shirley.*-bot-health.plist`（加密与美股各自的 11:00 体检）
- `~/Library/LaunchAgents/com.shirley.ai-chain-health.plist`（AI 三块的 **16:00** 串行体检链，
  2026-09-04 随 AI 日报拆分建立；注意它**不叫** `-bot-health`，上面那个 glob 匹配不到它，别漏拷）
- 各 bot 的 `logs/`（含 `sent_urls.json` 跨天去重档案与 `archive/` 稿件存档，丢了不影响运行，只是去重与周回顾要重新攒）

## 同步纪律

这里的副本是**快照，不是软链**（软链会被写入操作替换成普通文件，静默失效，所以没这么做）。
在 Claude 里改完 routine 的 prompt 后，记得手动同步回来并提交：

```bash
for t in morning-catchup-daily-bots ai-daily-afternoon; do
  cp ~/.claude/scheduled-tasks/$t/SKILL.md ~/Desktop/bots/shared/scheduled-tasks/$t/
done
```

用下面这段随时检查有没有漂移（无输出即一致）：

```bash
for t in morning-catchup-daily-bots ai-daily-afternoon; do
  diff ~/.claude/scheduled-tasks/$t/SKILL.md \
       ~/Desktop/bots/shared/scheduled-tasks/$t/SKILL.md
done
```
