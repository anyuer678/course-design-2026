"""B38-mini-redis —— 手写 Redis 子集：RESP2 + 单线程事件循环 + 双策略过期（软件工程案例分析）

    resp.py      RESP2 流式帧解码（粘包/拆包、内联×数组混合、协议错误分类）
    store.py     字符串键空间：语义表命令 + 惰性删除 + 主动采样（时钟可注入）
    server.py    selectors 单线程事件循环：多客户端、管线、坏包只断一条连接
    dbsnap.py    简化快照：版本魔数 + 校验和 + 原子写
    client.py    极简客户端（与服务器共用解码器；第二实现在 tools/reference_resp.py）

设计要点、实现子集与偏离表见 docs/case-study.md。**明确不是完整 Redis**：
只有字符串类型与 8 条命令，无事务/订阅/复制/集群。
"""
from redislite.client import Client, ConnectionClosed
from redislite.dbsnap import SnapshotError, load_snapshot, save_snapshot
from redislite.resp import ProtocolError, RespError
from redislite.server import Server
from redislite.store import CommandError, Store

__all__ = ["Client", "CommandError", "ConnectionClosed", "ProtocolError",
           "RespError", "Server", "SnapshotError", "Store",
           "load_snapshot", "save_snapshot"]
