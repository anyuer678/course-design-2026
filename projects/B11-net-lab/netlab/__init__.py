"""netlab —— B11 计算机网络实验包。

    http1.py   HTTP/1.1 请求/响应的严格子集解析与构造
    server.py  select 多路复用 + keep-alive 的单线程事件循环服务器
    client.py  裸 socket 客户端（测试与演示用它，才能真打到自己的解析器）
    udp.py     数据报格式、真回环 UDP 链路、种子化仿真坏信道
    gbn.py     Go-Back-N 滑动窗口：超时整窗重传，按序无重复交付
    websocket.py RFC 6455 WebSocket 服务器侧（升级握手、帧编解码、会话回调）

用法一律写 `from netlab.http1 import parse_request` 这样的具体模块，
这里不做二次导出：包级 API 会悄悄变成没人维护的兼容层。
"""
