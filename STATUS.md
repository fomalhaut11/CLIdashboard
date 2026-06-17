# Stream Dashboard — 项目状态 (handoff)

> 最后更新: 2026-06-17 ｜ 维护者: fomalhaut
> 本文件是跨会话交接用的"当前真相"。开工前先读这里，再读 README.md。

## 0. 一句话

多 stream worktree 的统一管理控制台 (本地 Web, localhost:5111)：把多个并行开发子任务的
coding agent (Claude / Codex) 的**对话入口、进度、所在分支**集中到一个浏览器页面。
核心诉求不是 git，而是"对所有在跑的 agent 有统一入口 + 直观看到各分支任务进度"。

## 1. 代码 / git 归属 (容易搞混, 务必看清)

存在**两份**副本：

| 副本 | 路径 | git 仓 / 分支 | 角色 |
|---|---|---|---|
| **真身 (在跑 + 在改)** | `F:\zx\stream-dashboard` | 独立仓 **CLIdashboard** (github fomalhaut11/CLIdashboard) 的 `main` | 唯一应该改的地方 |
| 旧镜像 | `F:\zx\multifactors_beta\tools\stream_dashboard` | multifactors_beta 的 `main` | 停在 v1.4, 已过时, **不是**运行版; 待删/合并 |

- 桌面快捷方式 "Stream Dashboard" 已指向真身的 `start.bat`。
- 真身与被监控的 multifactors_beta **解耦**: 被监控仓由 `config.py` 的
  `REPO_ROOT`(env `DASHBOARD_REPO_ROOT`, 默认 `F:\zx\multifactors_beta`) 决定。
- **隐患**: 旧镜像和真身已分叉。要么删掉旧镜像, 要么明确"只读快照"。尚未处理。

## 2. 当前未提交的改动 (2026-06-17 本次会话)

真身仓 `main` 上有 3 个文件改了**但未 commit**: `app.py` / `static/app.js` / `static/style.css`。
内容是下面三块, 验证通过后应 commit 成一个 v1.7。

### (A) 修复: Web 终端跑 Claude TUI 冻结 + 残留 + 尺寸错
排除了"第三方调用封禁"(token 还在计费=API 正常; 原生终端也正常)。真因是
`winpty -> WebSocket -> xterm.js` 这条管道扛不住 Claude 全屏 TUI:
- **冻结 (主症)**: 旧实现读线程直接阻塞式 `ws.send`, 浏览器收得慢就反压堵死 PTY ->
  卡死里面的 claude (耗时计数器停住、不出答案)。
  -> 改为**每个浏览器连接一条独立发送队列 + 发送线程** (`_PtyClient`), 读线程只入队永不阻塞;
  积压合并成一次 send, 超 4MB 丢最旧帧。
- **残留 + 尺寸 (次症)**: 旧实现重连时把 PTY 原始字节历史 (`ent["buf"]`) 重放给浏览器,
  全屏 TUI 的历史字节带"按旧尺寸的绝对光标定位", 重放到新尺寸=错位残留。
  -> 改为**不再重放原始历史**; 连上后抖动一次窗口尺寸 (先 -1 行再回正, 两次 SIGWINCH),
  逼 TUI 按真实尺寸**重绘当前屏**。前端 onopen 先 `fit.fit()` 再发尺寸, 起 claude 前再确认一次。
- 顺带: PTY spawn 注入 `TERM=xterm-256color` / `COLORTERM=truecolor`, 默认尺寸 40x140。

### (B) 新增: 会话 fork 可视化管理 (对接 Claude 原生 `--fork-session`)
不自己造 fork 引擎, 用原生: `claude --resume <id> --fork-session` (机器上已验证存在)。
- 会话弹窗里 Claude 会话按 **fork 家族**分组: 后端给每个会话读出"首条消息 uuid"(`first_uuid`),
  同源(原始+各 fork)共享同一首条 uuid -> 前端按它聚类, 标"根/分支"。
- 每条 Claude 会话多一个「分叉」按钮 -> 起 `--fork-session` 新分支 (复制分叉前上下文, 原对话不动)。
- **未验证点**: fork 是否真的保留首条 uuid 没能实测 (本机 `claude -p --resume` 解析不到这些会话)。
  若实际分叉后家族没聚拢, 说明 claude 重写了 uuid, 需换聚类键 (改 `renderClaudeSessions` 的 `first_uuid`)。

## 3. 已知限制 / 下一步候选

- **并行 A/B fork 受限**: 当前一个 worktree 只挂一条 PTY (按 cwd keyed)。同目录连开两个 claude 会打架。
  要真正 A、B 并行, 得在**不同 worktree** 各分叉一次; 或做"多 PTY per worktree"改造 (较大)。
- **fork return path**: 把分支结论并回父对话, 原生和社区都没解决 (feature req #32631/#19286/#16276), 是潜在原创点。
- **原生窗口逃生口** (可选): 给会话/Agent 列表加"在原生 wt 窗口打开"按钮 (`wt.exe` 本机可用),
  TUI 体验最稳; dashboard 仍按 cwd+sessionId 追踪, 不靠拥有终端。暂未做。
- **两份副本合并/删除** (见 §1)。
- 重启 dashboard 进程会杀掉它名下所有 PTY (winpty 子进程随父死); transcript 不丢, 可 `claude -r` 复活。
  注意: Windows 上 `Stop-Process` 只杀单进程不杀树, 杀 dashboard 前留意是否有计算子进程。

## 4. 运行 / 重启 / 验证

```
# 启动 (或重启后)
双击桌面 "Stream Dashboard"  ->  浏览器开 http://127.0.0.1:5111

# 手动重启 (改了 app.py 必须重启, Flask 无热重载; 改 app.js 浏览器 Ctrl+F5 即可)
# 1) 杀旧: 找 5111 监听 PID -> Stop-Process
# 2) 起新: cd F:\zx\stream-dashboard ; python app.py

# 验证服务
curl http://127.0.0.1:5111/api/pty/list          # 常驻终端 (含 cwd)
curl "http://127.0.0.1:5111/api/sessions?path=F:\zx\multifactors_beta"   # 看 first_uuid 是否带上
```

## 5. 关键文件

```
F:\zx\stream-dashboard\
  app.py              后端 (Flask + flask-sock + winpty); PTY/会话归属/fork 后端在这里
  config.py           REPO_ROOT / stream 映射 / 核心白名单 / 快捷命令 / 数据集清单
  templates/index.html  页面骨架 (5 标签 + 终端栏 + 会话/diff 模态)
  static/app.js       前端逻辑 (connect/PTY、会话恢复、fork 家族渲染)
  static/style.css    样式 (含 .forkfam fork 家族样式)
  start.bat           幂等启动 (查 5111, 在跑则只开浏览器)
  README.md           功能说明 ｜ STATUS.md  本文件
```
