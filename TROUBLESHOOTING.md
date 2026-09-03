# 排障与换机备忘

这几条的载体（launchd plist）被 `.gitignore` 排除，只能记在这里。
共同点是故障发生时安全网本身也一起失效了，不会有任何告警，只能靠这份文档。

## launchd 的日志路径不能放在 Desktop 下

2026-08-30 排查发现三个 health job 连续 11 天 `exit 78 (EX_CONFIG)`，整套体检 +
自愈 + 补跑的安全网静默失效，而唯一的告警渠道恰好也是它自己。

根因不在脚本：`~/Desktop/bots/*/logs/health_check.log` 被 TCC 打上 `com.apple.macl`
（`~/Desktop`、`~/Documents`、`~/Downloads` 都受保护），launchd 打不开它，
连 bash 都没 exec 就 EX_CONFIG。

约定：新增任何 LaunchAgent，输出重定向一律指向 `~/Library/Logs/bots/<job>.log`，
不要写进 Desktop / Documents / Downloads。排查手法是复制一份 plist、只把
`StandardOutPath` 改到 `/tmp`、换个 Label 后 bootstrap，exit code 变 0 就是这个问题。

## launchd 会回收整个进程组

`health_check.sh` 原来用 `bash xxx.sh &` 起后台子进程再自己 exit，而 launchd 在 job
主进程退出时会回收整个进程组，子进程当场被杀——结果是自愈与补跑"日志上写了触发、
实际从未执行"。现已全部改为前台调用（2026-07-23 修复）。

## claude CLI 断链会让 Level 2 自愈静默失效

Level 2 自愈由各 bot health plist 的 `ENABLE_CLAUDE_REPAIR` 控制（`1`=开），
依赖本机已安装并登录的 `claude` CLI。

`~/.local/bin/claude` 曾是指向版本目录的软链，Claude 升级后旧目录被清理，软链断掉
但没人发现——探测循环用 `[ -x ]` 判定，断链过不了，于是四个 bot 的自愈与补跑全失效。

重装走 npm，不要用 claude.ai 的安装脚本（实测 npm 831 KB/s，官方二进制约 90 KB/s）：

```bash
npm install -g @anthropic-ai/claude-code
ln -sfn /opt/homebrew/bin/claude ~/.local/bin/claude   # 指向 npm 的 bin，升级不会再断
```

排查必须验到无头调用这一层，只看 `--version` 会误判：

```bash
claude -p "回复:OK" --dangerously-skip-permissions
```

`--version` 能过、无头调用却报 OAuth 过期是常见组合——CLI 装好了但会话过期，
在终端跑一次 `claude` 走 `/login` 即可。

另：凭证存在 keychain 里，取用需要 `USER` / `LOGNAME`。用 `env -i` 起干净环境会剥掉
这两个，claude 就报 OAuth 过期，看着像凭证坏了其实是环境缺变量。launchd 会自动提供
这两个变量（已实测），health plist 不需要额外配置；但谁要在脚本里用 `env -i` 调 claude
就会踩到。
