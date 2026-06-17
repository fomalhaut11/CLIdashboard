# -*- coding: utf-8 -*-
"""
Stream Dashboard v1.6 - 多 stream worktree 一体化管理控制台

标签页: Streams(git状态+约定守卫+diff+终端+会话恢复[claude/codex]) / 实验注册表(type/进度) / 进程 / 数据 / 后台Agent(分支+最近活动)
会话归属: claude/codex 均按 git 解析 cwd->worktree 根 (git_toplevel), 含子目录会话.
后台Agent: 每个在跑 agent 显示所在分支 + 从其 transcript 末尾抓的"最近在干啥".
终端: PTY 后端常驻(按 worktree 一份), 切走/关页只 detach 不杀, 重连回放; 多个 CLI 可同时存活.
仅监听 127.0.0.1. 终端/进程是真实 shell, 切勿绑定 0.0.0.0.
启动: python tools/stream_dashboard/app.py  ->  http://127.0.0.1:5111
"""
import collections
import json
import os
import re
import subprocess
import threading
import time

from flask import Flask, jsonify, render_template, request
from flask_sock import Sock

import winpty

import config as C

app = Flask(__name__)
sock = Sock(app)

os.makedirs(C.PROC_LOG_DIR, exist_ok=True)

# ---------------- git 辅助 ----------------

def run_git(cwd, args, timeout=60):
    try:
        p = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "[timeout]"
    except Exception as e:  # noqa: BLE001
        return 1, "[error] %s" % e


def list_worktrees():
    rc, out = run_git(C.REPO_ROOT, ["worktree", "list", "--porcelain"])
    if rc != 0:
        return []
    trees, cur = [], {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if cur:
                trees.append(cur)
            cur = {"path": line[9:].strip()}
        elif line.startswith("branch "):
            cur["branch"] = line[7:].strip().replace("refs/heads/", "")
        elif line.startswith("detached"):
            cur["branch"] = "(detached)"
    if cur:
        trees.append(cur)
    return trees


# ---------------- 约定守卫 ----------------

def classify_path(branch, f):
    """返回 (level, kind, msg). level: ok|warn|violation."""
    f = f.replace("\\", "/")
    if branch == "main" or branch == "(detached)":
        return ("ok", "main", "")
    for rp in C.REGISTRY_PATHS:
        if f == rp:
            return ("warn", "registry", "注册表改动应走 main")
    allowed = C.STREAM_FOLDER.get(branch)
    if allowed and f.startswith(allowed + "/"):
        return ("ok", "own", "")
    # 别的 stream 文件夹
    for b, folder in C.STREAM_FOLDER.items():
        if b != branch and f.startswith(folder + "/"):
            return ("violation", "wrong_stream", "属于 %s" % b)
    # 因子型 stream: 因子文件 OK
    if branch == C.FACTOR_STREAM:
        if f.startswith("factors/repository/") or f.startswith("tests/"):
            return ("ok", "factor", "")
    # 共享核心
    for pre in C.CORE_PREFIXES:
        if f.startswith(pre):
            return ("violation", "core", "共享核心, 应走 main")
    return ("warn", "unclassified", "未归类, 建议放 stream 文件夹")


def guard_report(path, branch):
    """该 worktree 相对 main 的改动 (已提交+工作区) 的约定检查."""
    files = set()
    rc, out = run_git(path, ["diff", "--name-only", "main...HEAD"])
    if rc == 0:
        files.update(l.strip() for l in out.splitlines() if l.strip())
    rc, out = run_git(path, ["status", "--porcelain=v1"])
    if rc == 0:
        for line in out.splitlines():
            if len(line) > 3:
                files.add(line[3:].strip().strip('"'))
    items = []
    for f in sorted(files):
        level, kind, msg = classify_path(branch, f)
        if level != "ok":
            items.append({"file": f, "level": level, "kind": kind, "msg": msg})
    return items


# ---------------- stream meta (状态板) ----------------

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ---------------- worktree 状态采集 ----------------

def worktree_info(wt):
    path, branch = wt["path"], wt.get("branch", "?")
    info = {"path": path, "name": os.path.basename(path.rstrip("\\/")), "branch": branch,
            "staged": 0, "unstaged": 0, "untracked": 0, "ahead": 0, "behind": 0,
            "commits": [], "guard": [], "ok": os.path.isdir(path)}
    if not info["ok"]:
        return info
    rc, out = run_git(path, ["status", "--porcelain=v1"])
    if rc == 0:
        for line in out.splitlines():
            if not line:
                continue
            if line.startswith("??"):
                info["untracked"] += 1
            else:
                if line[0] != " ":
                    info["staged"] += 1
                if line[1] != " ":
                    info["unstaged"] += 1
    base = "origin/main" if branch == "main" else "main"
    rc, out = run_git(path, ["rev-list", "--left-right", "--count", "%s...HEAD" % base])
    if rc == 0 and out.strip():
        try:
            behind, ahead = out.split()
            info["behind"], info["ahead"] = int(behind), int(ahead)
        except ValueError:
            pass
    rc, out = run_git(path, ["log", "--oneline", "-5"])
    if rc == 0:
        info["commits"] = [l for l in out.splitlines() if l.strip()]
    info["guard"] = guard_report(path, branch)
    return info


# ---------------- 路由: 页面 ----------------

@app.route("/")
def index():
    return render_template("index.html", quick=C.QUICK_COMMANDS, jobs=C.JOB_COMMANDS)


@app.route("/api/streams")
def api_streams():
    meta = load_json(C.STREAM_META_FILE, {})
    out = []
    for wt in list_worktrees():
        info = worktree_info(wt)
        info["meta"] = meta.get(info["branch"], {"status": "ACTIVE", "note": ""})
        out.append(info)
    active = sum(1 for x in out if x["branch"] != "main" and x["meta"]["status"] == "ACTIVE")
    return jsonify({"streams": out, "wip_active": active})


# ---------------- 路由: git 安全操作 + diff + 分文件提交 ----------------

@app.route("/api/git", methods=["POST"])
def api_git():
    b = request.get_json(force=True)
    path, action = b.get("path"), b.get("action")
    if action not in C.SAFE_GIT:
        return jsonify({"rc": 1, "out": "不允许: %s" % action}), 400
    if not path or not os.path.isdir(path):
        return jsonify({"rc": 1, "out": "无效路径"}), 400
    rc, out = run_git(path, C.SAFE_GIT[action])
    return jsonify({"rc": rc, "out": out})


@app.route("/api/changed")
def api_changed():
    path = request.args.get("path")
    if not path or not os.path.isdir(path):
        return jsonify([])
    rc, out = run_git(path, ["status", "--porcelain=v1"])
    files = []
    if rc == 0:
        for line in out.splitlines():
            if len(line) < 3:
                continue
            x, y = line[0], line[1]
            f = line[3:].strip().strip('"')
            files.append({"file": f, "x": x, "y": y,
                          "staged": x not in (" ", "?"), "untracked": line.startswith("??")})
    return jsonify(files)


@app.route("/api/filediff")
def api_filediff():
    path, f = request.args.get("path"), request.args.get("file")
    staged = request.args.get("staged") == "1"
    if not path or not f:
        return jsonify({"diff": ""})
    args = ["diff"] + (["--cached"] if staged else []) + ["--", f]
    rc, out = run_git(path, args)
    if not out.strip() and not staged:
        # 未跟踪文件: 用 no-index 对比 /dev/null
        rc, out = run_git(path, ["diff", "--no-index", "--", os.devnull, f])
    return jsonify({"diff": out})


@app.route("/api/stage", methods=["POST"])
def api_stage():
    b = request.get_json(force=True)
    path, files, unstage = b.get("path"), b.get("files", []), b.get("unstage", False)
    if not path or not files:
        return jsonify({"rc": 1, "out": "缺参数"}), 400
    args = (["restore", "--staged"] if unstage else ["add", "--"]) + files
    rc, out = run_git(path, args)
    return jsonify({"rc": rc, "out": out})


@app.route("/api/commit", methods=["POST"])
def api_commit():
    b = request.get_json(force=True)
    path, files, msg = b.get("path"), b.get("files", []), (b.get("message") or "").strip()
    if not path or not msg:
        return jsonify({"rc": 1, "out": "缺路径或提交信息"}), 400
    if files:
        rc, out = run_git(path, ["add", "--"] + files)
        if rc != 0:
            return jsonify({"rc": rc, "out": out})
    rc, out = run_git(path, ["commit", "-m", msg])
    return jsonify({"rc": rc, "out": out})


@app.route("/api/worktree", methods=["POST"])
def api_worktree_add():
    b = request.get_json(force=True)
    name, branch = (b.get("name") or "").strip(), (b.get("branch") or "").strip()
    if not name or not branch:
        return jsonify({"rc": 1, "out": "name/branch 必填"}), 400
    target = os.path.abspath(os.path.join(C.REPO_ROOT, "..", name))
    rc, out = run_git(C.REPO_ROOT, ["worktree", "add", target, "-b", branch])
    return jsonify({"rc": rc, "out": out})


# ---------------- 路由: stream 状态板 ----------------

@app.route("/api/stream_meta", methods=["POST"])
def api_stream_meta():
    b = request.get_json(force=True)
    branch = b.get("branch")
    if not branch:
        return jsonify({"rc": 1}), 400
    meta = load_json(C.STREAM_META_FILE, {})
    meta[branch] = {"status": b.get("status", "ACTIVE"), "note": b.get("note", "")}
    save_json(C.STREAM_META_FILE, meta)
    return jsonify({"rc": 0})


# ---------------- 路由: 实验注册表 ----------------

@app.route("/api/registry", methods=["GET"])
def api_registry_get():
    return jsonify(load_json(C.REGISTRY_FILE, []))


@app.route("/api/registry", methods=["POST"])
def api_registry_post():
    b = request.get_json(force=True)
    op = b.get("op", "add")
    data = load_json(C.REGISTRY_FILE, [])
    if op == "add":
        e = b.get("entry", {})
        nid = max([x.get("id", 0) for x in data], default=0) + 1
        e["id"] = nid
        data.append(e)
    elif op == "update":
        eid, fields = b.get("id"), b.get("fields", {})
        for x in data:
            if x.get("id") == eid:
                x.update(fields)
    elif op == "delete":
        data = [x for x in data if x.get("id") != b.get("id")]
    save_json(C.REGISTRY_FILE, data)
    return jsonify({"rc": 0, "count": len(data)})


# ---------------- 路由: 进程管理 ----------------

PROCS = {}          # id -> {proc, label, cmd, path, started, log}
PROC_SEQ = {"n": 0}
PROC_LOCK = threading.Lock()


@app.route("/api/proc/start", methods=["POST"])
def api_proc_start():
    b = request.get_json(force=True)
    path, cmd, label = b.get("path") or C.REPO_ROOT, b.get("cmd"), b.get("label") or b.get("cmd")
    if not cmd:
        return jsonify({"rc": 1, "out": "缺命令"}), 400
    with PROC_LOCK:
        PROC_SEQ["n"] += 1
        pid = PROC_SEQ["n"]
    logpath = os.path.join(C.PROC_LOG_DIR, "proc_%d.log" % pid)
    logf = open(logpath, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=path, shell=True, stdout=logf,
                            stderr=subprocess.STDOUT, text=True)
    PROCS[pid] = {"proc": proc, "label": label, "cmd": cmd, "path": path,
                  "started": time.strftime("%H:%M:%S"), "log": logpath, "logf": logf}
    return jsonify({"rc": 0, "id": pid})


@app.route("/api/proc/list")
def api_proc_list():
    out = []
    for pid, p in sorted(PROCS.items()):
        rc = p["proc"].poll()
        out.append({"id": pid, "label": p["label"], "cmd": p["cmd"], "path": p["path"],
                    "started": p["started"],
                    "status": "running" if rc is None else "exited",
                    "rc": rc})
    return jsonify(out)


@app.route("/api/proc/log")
def api_proc_log():
    pid = int(request.args.get("id", 0))
    p = PROCS.get(pid)
    if not p:
        return jsonify({"text": "(无此进程)"})
    try:
        with open(p["log"], encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        text = ""
    return jsonify({"text": text[-20000:]})


@app.route("/api/proc/stop", methods=["POST"])
def api_proc_stop():
    pid = int(request.get_json(force=True).get("id", 0))
    p = PROCS.get(pid)
    if p and p["proc"].poll() is None:
        p["proc"].terminate()
    return jsonify({"rc": 0})


@app.route("/api/proc/clear", methods=["POST"])
def api_proc_clear():
    for pid in [k for k, v in PROCS.items() if v["proc"].poll() is not None]:
        try:
            PROCS[pid]["logf"].close()
        except Exception:  # noqa: BLE001
            pass
        del PROCS[pid]
    return jsonify({"rc": 0})


# ---------------- 路由: 数据管理可视化 ----------------

@app.route("/api/data/overview")
def api_data_overview():
    root = C.DATA_ROOT
    now = time.time()
    datasets = []
    for label, rel, max_age in C.KEY_DATASETS:
        fp = os.path.join(root, rel.replace("/", os.sep))
        if os.path.exists(fp):
            st = os.stat(fp)
            age_d = (now - st.st_mtime) / 86400.0
            stale = (max_age is not None and age_d > max_age)
            datasets.append({"label": label, "rel": rel, "exists": True,
                             "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                             "age_days": round(age_d, 1), "size_mb": round(st.st_size / 1e6, 1),
                             "stale": stale, "max_age": max_age})
        else:
            datasets.append({"label": label, "rel": rel, "exists": False})
    counts = []
    for label, rel, suf in C.DIR_COUNTS:
        d = os.path.join(root, rel.replace("/", os.sep))
        n = 0
        if os.path.isdir(d):
            n = sum(1 for x in os.listdir(d) if x.endswith(suf))
        counts.append({"label": label, "rel": rel, "count": n})
    # store_v2 激活版本 (junction 目标)
    sv = os.path.join(root, "factors", "store_v2")
    version = ""
    try:
        if os.path.exists(sv):
            tgt = os.path.realpath(sv)
            version = os.path.basename(tgt.rstrip("\\/"))
    except OSError:
        pass
    return jsonify({"data_root": root, "datasets": datasets, "counts": counts,
                    "store_v2_version": version})


# ---------------- 会话恢复 (claude 持久化 transcript) ----------------

USER_HOME = os.path.expanduser("~")
CLAUDE_PROJECTS_DIR = os.path.join(USER_HOME, ".claude", "projects")

# session id 必须长这样才允许拼进 shell 命令 / onclick (防注入, 源头校验)
_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")
# 跳过"模型选择"类 token (codex 首条常是 gpt-5.5 / opus 等, 非真实 prompt)
_MODEL_TOK = re.compile(r"^(gpt|o\d|claude|opus|sonnet|haiku|codex|gemini)[\w.\-]*$", re.I)


def _safe_id(sid):
    """只放行形如 UUID/hex 的 id, 否则返回空串 (调用方据此跳过)."""
    return sid if (sid and _ID_RE.match(sid)) else ""


def claude_project_dir(path):
    """worktree 路径 -> claude transcript 目录 (~/.claude/projects/<编码路径>).

    claude 把工作目录里非字母数字的字符都替换成 '-' 作为项目目录名,
    例: F:\\zx\\multifactors_beta -> F--zx-multifactors-beta.
    盘符大小写可能不一致, 故先精确命中, 不中再做大小写不敏感解析.
    """
    enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))
    cand = os.path.join(CLAUDE_PROJECTS_DIR, enc)
    if os.path.isdir(cand):
        return cand
    encl = enc.casefold()
    try:
        for d in os.listdir(CLAUDE_PROJECTS_DIR):
            if d.casefold() == encl:
                return os.path.join(CLAUDE_PROJECTS_DIR, d)
    except OSError:
        pass
    return cand


def _session_meta(fp, info):
    """读 jsonl 头部取会话名(summary)+首条用户消息预览, 只扫前 80 行保持轻量."""
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 80:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(r, dict):
                    continue
                if not info.get("cwd") and r.get("cwd"):
                    info["cwd"] = r["cwd"]
                # 首条消息 uuid: fork 复制分叉前前缀, 故同源(原始+各 fork)会话共享同一首条 uuid
                if not info.get("first_uuid") and r.get("uuid"):
                    info["first_uuid"] = r["uuid"]
                t = r.get("type")
                if t == "summary" and not info["name"]:
                    info["name"] = (r.get("summary") or "")[:60]
                if not info["preview"] and t == "user":
                    m = r.get("message") or {}
                    c = m.get("content")
                    txt = ""
                    if isinstance(c, str):
                        txt = c
                    elif isinstance(c, list):
                        for b in c:
                            if isinstance(b, dict) and b.get("type") == "text":
                                txt = b.get("text", "")
                                break
                    txt = (txt or "").strip()
                    # 跳过工具结果 / caveat / slash 命令噪声, 取第一条真人提问
                    if txt and txt[0] not in "<[" and not txt.startswith("Caveat"):
                        info["preview"] = txt.replace("\n", " ")[:90]
                if info["name"] and info["preview"]:
                    break
    except OSError:
        pass


def _tail_activity(fp, n_bytes=131072):
    """读 transcript 末尾, 取最近一条真人提问 + 最近一条 assistant 文本 (看 agent 在干啥)."""
    last_user = last_asst = ""
    try:
        size = os.path.getsize(fp)
        with open(fp, "rb") as f:
            if size > n_bytes:
                f.seek(size - n_bytes)
                f.readline()  # 丢弃可能不完整的首行
            chunk = f.read().decode("utf-8", "replace")
    except OSError:
        return {"last_user": "", "last_asst": ""}
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        m = r.get("message") or {}
        c = m.get("content")
        txt = ""
        if isinstance(c, str):
            txt = c
        elif isinstance(c, list):
            txt = " ".join(b.get("text", "") for b in c
                           if isinstance(b, dict) and b.get("type") == "text")
        txt = (txt or "").strip().replace("\n", " ")
        if not txt:
            continue
        if r.get("type") == "user":
            if txt[0] not in "<[" and not txt.startswith("Caveat"):
                last_user = txt[:140]
        elif r.get("type") == "assistant":
            last_asst = txt[:180]
    return {"last_user": last_user, "last_asst": last_asst}


@app.route("/api/sessions")
def api_sessions():
    """列出某 worktree 已保存的 claude 会话 (按 git 解析 cwd 归属, 含子目录会话)."""
    path = request.args.get("path")
    if not path or not os.path.isdir(path):
        return jsonify({"dir": "", "sessions": []})
    target = git_toplevel(path)
    # 候选 transcript 目录: 编码名精确匹配 + 以"编码名-"开头的(子目录启动的会话), 大小写不敏感
    enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path)).casefold()
    cand_dirs = []
    if os.path.isdir(CLAUDE_PROJECTS_DIR):
        for d in os.listdir(CLAUDE_PROJECTS_DIR):
            dl = d.casefold()
            if dl == enc or dl.startswith(enc + "-"):
                cand_dirs.append(os.path.join(CLAUDE_PROJECTS_DIR, d))
    out = []
    for pdir in cand_dirs:
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if not fn.endswith(".jsonl"):
                continue
            sid = _safe_id(fn[:-6])
            if not sid:
                continue
            fp = os.path.join(pdir, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            info = {"id": sid, "ts": st.st_mtime,
                    "mtime": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime)),
                    "size_kb": round(st.st_size / 1024), "name": "", "preview": "",
                    "cwd": "", "first_uuid": ""}
            _session_meta(fp, info)
            # git 解析该会话 cwd 确认归属; cwd 读不到则信任目录名编码(已落在候选集)
            if info.get("cwd") and git_toplevel(info["cwd"]) != target:
                continue
            out.append(info)
    out.sort(key=lambda x: x["ts"], reverse=True)
    return jsonify({"dir": ";".join(cand_dirs), "sessions": out})


@app.route("/api/agents")
def api_agents():
    """claude 原生后台 agent 列表 (claude agents --json, 不挂终端的后台会话)."""
    try:
        p = subprocess.run("claude agents --json", cwd=C.REPO_ROOT, shell=True,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=20)
        body = (p.stdout or "").strip()
        data = json.loads(body) if body.startswith("[") else []
        for a in (data if isinstance(data, list) else []):
            if not isinstance(a, dict):
                continue
            cwd = a.get("cwd")
            if not cwd:
                continue
            a["branch"] = git_branch(cwd)           # 在哪个分支
            top = git_toplevel(cwd)
            a["worktree"] = os.path.basename(top.rstrip("/")) if top else ""
            sid = a.get("sessionId")
            if sid:                                  # 用 sessionId 定位它自己的 transcript, 读末尾=在干啥
                tp = os.path.join(claude_project_dir(cwd), str(sid) + ".jsonl")
                if os.path.isfile(tp):
                    a.update(_tail_activity(tp))
        return jsonify({"ok": True, "agents": data, "raw": "" if data else body[:400]})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e), "agents": []})


# ---------------- 会话恢复 (codex rollout) ----------------

CODEX_SESSIONS_DIR = os.path.join(USER_HOME, ".codex", "sessions")


def _norm_path(p):
    """统一路径用于比较: 大小写折叠 + 统一斜杠. codex 存反斜杠, git 给正斜杠.
    空串直接返回空 (否则 abspath('') 会变成 dashboard 自身 cwd, 造成误归属)."""
    if not p:
        return ""
    try:
        return os.path.normcase(os.path.abspath(p)).replace("\\", "/")
    except Exception:  # noqa: BLE001
        return (p or "").replace("\\", "/").lower()


_TOPLEVEL_CACHE = {}


def git_toplevel(path):
    """把任意 cwd 解析到它所属 git worktree 根 (规范化路径), 带缓存.

    用 git rev-parse 而非字符串前缀匹配: 子目录会正确归到 worktree 根,
    且不受盘符大小写 / claude 目录名 '_'->'-' 编码歧义影响.
    cwd 不存在或非 git 仓时, 回退为该路径自身的规范化值 (不会误配到别处).
    """
    key = _norm_path(path)
    if not key:
        return ""
    if key in _TOPLEVEL_CACHE:
        return _TOPLEVEL_CACHE[key]
    top = ""
    if os.path.isdir(path):
        rc, out = run_git(path, ["rev-parse", "--show-toplevel"])
        if rc == 0 and out.strip():
            top = _norm_path(out.strip().splitlines()[0].strip())
    if not top:
        top = key  # 兜底: cwd 已删/非 git -> 用原 cwd 规范化, 不会误归到别的 worktree
    _TOPLEVEL_CACHE[key] = top
    return top


def git_branch(path):
    """cwd -> 当前分支名 (HEAD). 不缓存(分支会变); 解析不了返回空."""
    if not path or not os.path.isdir(path):
        return ""
    rc, out = run_git(path, ["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip().splitlines()[0].strip() if rc == 0 and out.strip() else ""


def _codex_session_brief(fp):
    """读 codex rollout 头部, 取 session_meta(id/cwd) + 首条真人 prompt 预览."""
    sid = cwd = ""
    preview = ""
    try:
        with open(fp, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 60:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(r, dict):
                    continue
                t = r.get("type")
                pl = r.get("payload")
                if not isinstance(pl, dict):
                    pl = {}
                if t == "session_meta":
                    sid = pl.get("id", "")
                    cwd = pl.get("cwd", "")
                elif t == "event_msg" and pl.get("type") == "user_message" and not preview:
                    msg = (pl.get("message") or "").strip()
                    # 跳过注入(# / <)与"模型选择"token(gpt-5.5/opus...), 短问候保留
                    if msg and msg[0] not in "#<" and not (_MODEL_TOK.match(msg) and " " not in msg):
                        preview = msg.replace("\n", " ")[:90]
                if sid and preview:
                    break
    except OSError:
        return None
    sid = _safe_id(sid)
    return {"id": sid, "cwd": cwd, "preview": preview} if sid else None


@app.route("/api/codex_sessions")
def api_codex_sessions():
    """列出某 worktree 的 codex 会话 (rollout 文件按 cwd 过滤)."""
    path = request.args.get("path")
    if not path or not os.path.isdir(path):
        return jsonify({"dir": CODEX_SESSIONS_DIR, "sessions": []})
    target = git_toplevel(path)
    out = []
    if os.path.isdir(CODEX_SESSIONS_DIR):
        for root, _dirs, files in os.walk(CODEX_SESSIONS_DIR):
            for fn in files:
                if not (fn.startswith("rollout-") and fn.endswith(".jsonl")):
                    continue
                fp = os.path.join(root, fn)
                br = _codex_session_brief(fp)
                if not br or not br["cwd"]:
                    continue
                # git 解析 rollout 里的 cwd -> worktree 根, 再比对 (子目录/大小写/编码歧义都正确)
                if git_toplevel(br["cwd"]) != target:
                    continue
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                out.append({"id": br["id"], "preview": br["preview"], "name": "",
                            "mtime": time.strftime("%m-%d %H:%M", time.localtime(st.st_mtime)),
                            "ts": st.st_mtime, "size_kb": round(st.st_size / 1024)})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return jsonify({"dir": CODEX_SESSIONS_DIR, "sessions": out})


# ---------------- 交互终端 (PTY) — 后端常驻, 按 worktree 一份, 断开只 detach 不杀 ----------------
# 多个 CLI 可同时存活: 切走/关页只是 detach, PTY 继续跑; 重连回放最近输出. 显式关闭才 terminate.

PTYS = {}                 # key(规范化 cwd) -> {"proc","buf","clients","cwd"}
PTY_LOCK = threading.Lock()
PTY_BUF_MAX = 200000      # 每个终端保留最近 ~200KB 输出, 供重连回放
PTY_CLIENT_MAX_BYTES = 4000000   # 单客户端积压上限 ~4MB; 超了丢最旧帧 (防慢客户端拖垮 PTY)


class _PtyClient:
    """单个浏览器连接的发送侧: 自带队列 + 独立发送线程.

    关键: 读线程只往队列里 feed (永不阻塞); 发送线程负责 ws.send.
    这样某个浏览器收得慢/卡住, 也不会反压堵死 PTY 读线程 -> 不会卡死里面的 claude.
    (旧实现是读线程直接 ws.send, 阻塞式; 高频整屏重绘时浏览器收不赢就把 claude 冻住.)
    积压时把待发帧合并成一次 send 降压; 超上限丢最旧帧 (TUI 会整屏重绘自愈)."""

    def __init__(self, ws):
        self.ws = ws
        self.q = collections.deque()
        self.nbytes = 0
        self.cv = threading.Condition()
        self.alive = True
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def feed(self, data):
        if not data:
            return
        with self.cv:
            self.q.append(data)
            self.nbytes += len(data)
            while self.nbytes > PTY_CLIENT_MAX_BYTES and len(self.q) > 1:
                self.nbytes -= len(self.q.popleft())
            self.cv.notify()

    def close(self):
        with self.cv:
            self.alive = False
            self.cv.notify()

    def _run(self):
        while True:
            with self.cv:
                while self.alive and not self.q:
                    self.cv.wait()
                if not self.q and not self.alive:
                    return
                chunk = "".join(self.q)   # 合并待发帧 -> 一次 send
                self.q.clear()
                self.nbytes = 0
            try:
                self.ws.send(chunk)
            except Exception:  # noqa: BLE001
                self.alive = False
                return


def _pty_reader(key):
    ent = PTYS.get(key)
    if not ent:
        return
    proc = ent["proc"]
    try:
        while True:
            try:
                if not proc.isalive():
                    break
            except Exception:  # noqa: BLE001
                break
            data = proc.read(65536)
            if not data:
                continue
            ent["buf"] = (ent["buf"] + data)[-PTY_BUF_MAX:]
            for c in list(ent["clients"]):
                c.feed(data)            # 非阻塞: 入各客户端队列, 慢客户端不影响读取
    except (EOFError, Exception):  # noqa: BLE001
        pass
    finally:
        for c in list(ent["clients"]):
            c.feed("\r\n\x1b[31m[终端进程已退出]\x1b[0m\r\n")
            c.close()
        with PTY_LOCK:
            PTYS.pop(key, None)


def _get_or_spawn_pty(cwd):
    key = _norm_path(cwd)
    with PTY_LOCK:
        ent = PTYS.get(key)
        if ent:
            try:
                if ent["proc"].isalive():
                    return key, ent
            except Exception:  # noqa: BLE001
                pass
            PTYS.pop(key, None)   # 死掉的清掉重开
        env = dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")
        proc = winpty.PtyProcess.spawn(C.SHELL, cwd=cwd, env=env, dimensions=(40, 140))
        ent = {"proc": proc, "buf": "", "clients": set(), "cwd": cwd}
        PTYS[key] = ent
    threading.Thread(target=_pty_reader, args=(key,), daemon=True).start()
    return key, ent


@app.route("/api/pty/list")
def api_pty_list():
    """当前常驻终端列表 (跨切换存活)."""
    out = []
    with PTY_LOCK:
        items = list(PTYS.items())
    for key, ent in items:
        try:
            alive = ent["proc"].isalive()
        except Exception:  # noqa: BLE001
            alive = False
        out.append({"key": key, "cwd": ent["cwd"],
                    "name": os.path.basename(ent["cwd"].rstrip("\\/")) or ent["cwd"],
                    "alive": alive, "clients": len(ent["clients"])})
    return jsonify(out)


@app.route("/api/pty/kill", methods=["POST"])
def api_pty_kill():
    """显式关闭某终端 (真正 terminate)."""
    key = (request.get_json(force=True) or {}).get("key")
    with PTY_LOCK:
        ent = PTYS.get(key)
    if ent:
        try:
            ent["proc"].terminate(force=True)
        except Exception:  # noqa: BLE001
            pass
    return jsonify({"rc": 0})


@sock.route("/pty")
def pty(ws):
    cwd = request.args.get("cwd") or C.REPO_ROOT
    if not os.path.isdir(cwd):
        cwd = C.REPO_ROOT
    key, ent = _get_or_spawn_pty(cwd)
    client = _PtyClient(ws)
    ent["clients"].add(client)
    # 注意: 不回放原始字节历史 (ent["buf"]). 全屏 TUI(claude/codex) 的历史字节
    # 带的是"按旧尺寸"的绝对光标定位, 重放到新尺寸终端会画出错位的"残留对话".
    # 改为靠下面首个 resize 抖动一次, 强制 TUI 自己按新尺寸重绘当前屏 (干净 + 尺寸正确).
    first_resize = [True]
    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break
            try:
                obj = json.loads(msg)
            except (ValueError, TypeError):
                continue
            if "i" in obj:
                try:
                    ent["proc"].write(obj["i"])
                except Exception:  # noqa: BLE001
                    break
            elif "r" in obj:
                try:
                    cols, rows = int(obj["r"][0]), int(obj["r"][1])
                    if rows > 0 and cols > 0:
                        if first_resize[0]:
                            first_resize[0] = False
                            # 抖动一次 (先 -1 行再回正) -> 两次 SIGWINCH, 逼 Ink/TUI 重绘,
                            # 清掉本视图 detach 期间残留、并按真实尺寸排版
                            ent["proc"].setwinsize(max(1, rows - 1), cols)
                            time.sleep(0.03)
                        ent["proc"].setwinsize(rows, cols)
                        ent["size"] = (rows, cols)
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        client.close()
        ent["clients"].discard(client)   # 仅 detach, 不杀 PTY


if __name__ == "__main__":
    print("Stream Dashboard v1.6 -> http://%s:%d  (repo: %s)" % (C.HOST, C.PORT, C.REPO_ROOT))
    app.run(host=C.HOST, port=C.PORT, threaded=True, debug=False)
