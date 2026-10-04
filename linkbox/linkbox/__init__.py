"""LinkBox —— 自托管工具站（产品矩阵 P2）。

产品与课程任务的关系（复用，不重写）：
    短链引擎来自课程任务 B31（projects/B31-shorturl/b31/），通信协议来自
    B11 的 netlab——本产品只做"产品层"：新增文本暂存功能、产品化界面、
    数据目录与启动方式。引擎里发现的问题修在引擎里（单源），不在这里复制。

数据文件（数据目录 data/，首次启动自动创建）：
    shorturl.sqlite  短链库（与课程任务 B31 同构，可直接沿用旧数据）
    stash.sqlite     文本暂存库（本产品新增，带过期时间）

M1 功能边界：短链（创建/跳转/统计/列表）+ 文本暂存（创建/查看/删除/过期）。
二维码、访问口令、剪贴板历史在 M2/M3。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 桥接课程任务引擎：短链核心（codec/urls/store）与 netlab 协议层都在 B31/B11
B31_DIR = Path(__file__).resolve().parents[1] / "projects" / "B31-shorturl"
B11_DIR = B31_DIR.parent / "B11-net-lab"
for _p in (B11_DIR, B31_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
