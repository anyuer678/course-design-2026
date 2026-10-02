"""B35-iot-mqtt —— 手写极简 MQTT：传感器 → broker → SQLite → SVG 曲线（工业物联网技术）

    packets.py    MQTT 3.1.1 子集字节级编解码（变长 Remaining Length / 通配符匹配 / 坏包分类）
    broker.py     selectors 单线程事件循环：CONNECT/CONNACK、订阅表、按通配符路由、PING、
                  同 id 顶号、坏包只断一条连接
    client.py     客户端 + ResilientClient（断线重连、自动重订阅、safe_publish）
    sensors.py    模拟工业传感器：随机游走 + spike/freeze/dropout 三类异常（带账本）
    recorder.py   订阅端入库 SQLite（幂等主键、实收/分布/异常/缺口四个对账口）
    svgplot.py    手写 SVG 折线图（异常点标红圈）

零依赖（纯标准库），决策点③的落实方案——不装 paho-mqtt / mosquitto。
"""
