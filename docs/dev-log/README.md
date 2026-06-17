# 对话开发记录 (dev-log)

这里留存开发本 dashboard 的 Claude 对话 transcript, 方便将来在本目录重拾上下文。

> 原始 `*.jsonl` 已 gitignore (单个 4MB+, 含完整对话内容), 只在本地存在, 不推 GitHub。
> 可移植的交接文档是仓库根的 `STATUS.md`。

## 已留存

| 文件 | 会话 | 内容 |
|---|---|---|
| `27b1d829-dashboard-dev-2026-06-17.jsonl` | 27b1d829 | 2026-06-17: Web 终端冻结/残留/尺寸修复 + fork 可视化 (见 STATUS.md §2) |

## 怎么重拾这段对话

**方式一 (推荐, 接回原对话):** 该 transcript 已同时拷到 claude 项目目录
`~/.claude/projects/F--zx-stream-dashboard/`, 所以从本仓库目录可直接接回:

```
cd F:\zx\stream-dashboard
claude -r 27b1d829-55be-481c-8562-5cfa2895b979
# 或 claude -r 打开选择器
```

**方式二 (只看记录):** 直接读本目录的 `.jsonl` (机器格式), 或读 `STATUS.md` (人读版交接)。

## 注意

- 拷贝是**某时刻的快照**。原对话还在写时, 快照不含其后续。会话结束后重新拷一次最新:

  ```
  copy "C:\Users\ZhangXi\.claude\projects\F--zx-multifactors-beta\27b1d829-55be-481c-8562-5cfa2895b979.jsonl" ^
       "F:\zx\stream-dashboard\docs\dev-log\27b1d829-dashboard-dev-2026-06-17.jsonl"
  ```

- **今后开发本 dashboard, 直接在 `F:\zx\stream-dashboard` 目录下起 claude** (而不是在 multifactors_beta 里),
  这样 transcript 会**原生**落到本项目目录, 自然可 `claude -c/-r` 接回, 无需手动拷贝。
  本次是历史遗留: 整个 dashboard 是在 multifactors_beta 的会话里开发的。
