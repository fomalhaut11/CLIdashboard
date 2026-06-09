# Stream Dashboard v1.5

多 stream worktree 一体化管理控制台:本地 Web,把 4 条平行开发 stream 的
**git 动态、约定守卫、diff/提交、实验注册表、进程、数据、会话恢复(Claude+Codex)、后台Agent** 整合在一个浏览器页面。

核心用途:对所有在跑的 coding agent(claude/codex)有一个**统一入口 + 进度总览**——长会话不必再靠记忆,
一眼看清每个 agent **在哪个分支、最近在干什么**;实验注册表按 type(research/dev/replication)+ 下一步管各线进度。

> 注:服务是常驻进程,关闭浏览器**不会**停掉它——重新打开 http://127.0.0.1:5111 即可。
> 同理 Claude Code 会话持续写盘 (`~/.claude/projects/<编码路径>/<id>.jsonl`),CLI 窗口关了对话不丢,见下方「会话恢复」。

## 安装 & 启动

```
pip install -r requirements.txt
start.bat                REM 或直接:  python app.py
```

浏览器打开 http://127.0.0.1:5111(start.bat 会自动开)。`start.bat` 幂等:已在运行则只开浏览器;
关闭它弹出的控制台窗口即停止 dashboard。

## 配置:被监控的 repo

dashboard 自身与被监控的目标 repo 解耦。默认监控 `F:\zx\multifactors_beta`;要监控别的 repo,
设环境变量 `DASHBOARD_REPO_ROOT` 指向那个 repo 根目录即可——其 git/worktree/streams/约定守卫/数据/
`docs/experiments/registry.json` 都基于它。

注:`config.py` 里的 `STREAM_FOLDER`(stream→文件夹)/`CORE_PREFIXES`(共享核心白名单)/`KEY_DATASETS`
(数据集清单)仍按 multifactors_beta 的约定硬编码,换到别的项目时按需改 `config.py`。

## 标签页

### Streams
- 每个 git worktree 一张卡(每 6 秒自动刷新):分支、脏文件数、相对 main 领先/落后、最近提交。
- **约定守卫**:按 `CLAUDE.md` 的路径约定,自动标出该 stream 分支的越界改动——
  改到共享核心(红/应走 main)、跑进别的 stream 文件夹(红)、动注册表(黄/走 main)、未归类(黄)。
- **stream 状态板**:每条标 ACTIVE/PARKED/BLOCKED;顶部 WIP 计数,活跃 >2 高亮提醒。
- **改动/diff**:点「改动」开模态,逐文件看彩色 diff、勾选文件暂存/取消暂存/提交。
- **嵌入式终端**:点「终端」在该 worktree 起真实 PowerShell。终端栏分 Claude / Codex 两组启动按钮:
  - Claude:`+新`=`claude`、`继续`=`claude -c`(接该目录最近)、`选择`=`claude -r`(选择器)。
  - Codex:`+新`=`codex`、`继续`=`codex resume --last`、`选择`=`codex resume`(自动按当前目录过滤)。
- **会话恢复(Claude + Codex)**:点「会话」开模态,分两区列出该 worktree 已保存的会话
  (名称/预览/时间/大小)。点「恢复」=切到终端自动 `claude -r <id>` 或 `codex resume <id>` 接回——
  窗口/浏览器崩了也不用手写 handoff。claude transcript 在 `~/.claude/projects/<编码路径>/`;
  codex rollout 在 `~/.codex/sessions/年/月/日/rollout-*.jsonl`(按文件内 `cwd` 归属到 worktree)。
- 安全 git 按钮:fetch / pull / log。右上角「+ worktree」新建。

### 进程
把命令作为**受管后台进程**启动(回测、训练、health-check),输出流式落日志面板。
作业按钮 / 自定义命令(在当前选中 worktree 运行)/ 进程列表(状态·退出码·停止)/ 实时日志 / 清理已结束。
与「终端」区别:终端是交互式,进程面板适合长跑作业 + 留存输出。

### 数据
数据层可视化(读 `config/main.yaml` 的 data_root):store_v2 激活版本、raw/alpha191/orthogonal 因子计数、
关键数据集(Price/财务三表/MarketState/交易日历…)的最后更新时间、大小、新鲜/过期判定。

### 后台Agent(统一入口 + 进度)
读 `claude agents --json`,列出当前所有在跑的 claude 会话(跨 worktree),每条显示:
- 状态(busy·idle)、**所在分支**(git 解析 cwd→worktree→HEAD)、worktree 名、pid、cwd;
- **最近在干什么**:从该会话自己的 transcript 末尾抓「最近一条真人提问 ▶」+「最近一条 assistant 回复 ↳」——长会话不用翻窗口回忆;
- 「在终端接入」=切到终端并 `claude -r <id>` 接入。
- 8 秒自动刷新。**作用:一页看清同时工作的多个 agent 在哪条分支、进度到哪。**

### 实验注册表(进度台账)
跨 stream 实验/任务总表(`docs/experiments/registry.json`):**类型(research/dev/replication)**/ stream /
假设或目标 / kill 准则 / **下一步** / 结论(RUNNING·PASS·HONEST-FAIL)/ FactorStore 版本 / 链接。
支持按 stream 和类型过滤,新增,一键改结论,`→` 一键更新下一步,删除。
**作用:一个台账管所有研究/开发线的进度,避免重试已否决方向,也避免忘记某线下一步该干啥。**

## 安全

- 只监听 `127.0.0.1`。终端和进程都是真实 shell,**不要**改成 `0.0.0.0` 对外暴露。
- git REST 操作白名单(fetch/pull/status/diff/log + 受控的 stage/commit)。

## 文件

```
app.py                后端 (Flask + flask-sock + winpty)
config.py             目标repo路径/stream映射/核心白名单/快捷命令/数据集清单
templates/index.html  页面骨架 (标签页 + diff/会话 模态)
static/style.css      样式
static/app.js         前端逻辑
streams_meta.json     stream 状态板数据 (ACTIVE/PARKED/BLOCKED)
requirements.txt      依赖
start.bat             幂等启动脚本 (Windows)
_proc_logs/           受管进程日志 (gitignored, 运行时生成)
```

实验注册表数据存于**被监控 repo** 的 `docs/experiments/registry.json`(路径由 `DASHBOARD_REPO_ROOT` 决定)。
依赖:flask, flask-sock, pywinpty。xterm.js 走 CDN,无需 npm 构建。
