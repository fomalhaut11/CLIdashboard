# -*- coding: utf-8 -*-
"""Stream Dashboard 配置: 路径 / stream 映射 / 核心白名单 / 快捷命令 / 数据集清单.

独立版: dashboard 自身与被监控的目标 repo 解耦.
被监控 repo 默认 F:\\zx\\multifactors_beta, 用环境变量 DASHBOARD_REPO_ROOT 覆盖.
"""
import os
import re

# 被监控的目标 repo (git/streams/约定守卫/数据/注册表都基于它). env 可覆盖.
REPO_ROOT = os.path.abspath(os.environ.get("DASHBOARD_REPO_ROOT", r"F:\zx\multifactors_beta"))
HOST = "127.0.0.1"
PORT = 5111
SHELL = ["powershell.exe", "-NoLogo"]

# 运行期状态文件
DASH_DIR = os.path.dirname(__file__)
PROC_LOG_DIR = os.path.join(DASH_DIR, "_proc_logs")
STREAM_META_FILE = os.path.join(DASH_DIR, "streams_meta.json")
REGISTRY_FILE = os.path.join(REPO_ROOT, "docs", "experiments", "registry.json")


def _data_root():
    env = os.environ.get("DATA_ROOT")
    if env:
        return env
    cfg = os.path.join(REPO_ROOT, "config", "main.yaml")
    try:
        with open(cfg, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*data_root:\s*['\"]?([^'\"#\n]+)", line)
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return r"F:\StockData"


DATA_ROOT = _data_root()

# stream 分支 -> 允许的专属文件夹 (应用型). 因子型 (factor-replicate) 不在此, 单独规则.
STREAM_FOLDER = {
    "stream/etf-timing": "streams/etf_timing",
    "stream/index-enhance": "streams/index_enhance",
    "stream/regime-style": "streams/regime_style",
}
FACTOR_STREAM = "stream/factor-replicate"

# 共享核心白名单: stream 分支改到这些前缀 = 越界 (应走 main)
CORE_PREFIXES = [
    "core/", "config/", "docs/", "data/",
    "factors/generators/", "factors/tester/", "factors/risk_model/",
    "pipeline/", "portfolio/optimizer/", "package_optimizer/",
    "tools/", "CLAUDE.md", "README.md", "AGENTS.md", ".gitignore",
]
# 共享单文件注册表: 改动应走 main (warn)
REGISTRY_PATHS = [
    "core/factors/meta/factor_registry.json",
    "config/derived_data.yaml",
]

# 终端快捷命令 (点击写入当前终端并回车). agent 启动/恢复按钮在 index.html 终端栏单列.
QUICK_COMMANDS = [
    {"label": "git status", "cmd": "git status -sb"},
    {"label": "git log(10)", "cmd": "git log --oneline -10"},
    {"label": "pull main", "cmd": "git merge --ff-only main"},
    {"label": "data 健康检查", "cmd": "python tools/data_management/scheduled_data_updater.py --health-check"},
]

# 作业型快捷命令 (作为受管进程启动, 输出落日志面板)
JOB_COMMANDS = [
    {"label": "data status", "cmd": "python manage.py data status"},
    {"label": "data check", "cmd": "python manage.py data check"},
    {"label": "健康检查", "cmd": "python tools/data_management/scheduled_data_updater.py --health-check"},
]

# 安全 git 操作白名单 (走 REST)
SAFE_GIT = {
    "fetch": ["fetch", "--all", "--prune"],
    "pull": ["pull", "--ff-only"],
    "status": ["status", "--porcelain=v1", "-b"],
    "diff": ["diff", "--stat"],
    "log": ["log", "--oneline", "-20"],
}

# 数据面板关注的数据集: (标签, 相对 DATA_ROOT 路径, 最大新鲜天数 None=不判新鲜)
KEY_DATASETS = [
    ("Price 日线", "Price.pkl", 4),
    ("StopPrice 停牌", "StopPrice.pkl", 4),
    ("ST 名单", "ST_stocks.pkl", 7),
    ("资产负债表", "fzb.pkl", None),
    ("利润表", "lrb.pkl", None),
    ("现金流量表", "xjlb.pkl", None),
    ("MarketState(已shift)", "auxiliary/MarketState.pkl", 4),
    ("交易日历", "auxiliary/TradingDates.pkl", 7),
    ("可交易域", "auxiliary/TradableUniverse.pkl", 7),
    ("无风险利率", "auxiliary/RiskFreeRate.pkl", 30),
]
# 目录计数项: (标签, 相对路径, 统计后缀)
DIR_COUNTS = [
    ("raw 因子", "factors/raw", ".pkl"),
    ("alpha191", "factors/alpha191", ".pkl"),
    ("orthogonal", "factors/orthogonal", ".pkl"),
]
