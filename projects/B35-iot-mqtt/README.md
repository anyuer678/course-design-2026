# B35-iot-mqtt —— 手写极简 MQTT：传感器 → broker → SQLite → SVG 曲线（工业物联网技术）

**课程映射**：工业物联网技术（PLAN 批次 6/7 之间，安装决策点③）。

一句话：**物联网消息层的全链路，从字节到曲线，一行第三方库都不用**——
CONNECT/PUBLISH/SUBSCRIBE 的报文自己拼、broker 的订阅路由自己写、
断线重连自己扛、数据入库与曲线自己接；每一层都能指着字节说清楚"它为什么长这样"。

**决策点③的落实（零依赖）**：**不装 paho-mqtt、不装 mosquitto**，按 ROADMAP 的手写方案交付
（"手写协议"正是理解物联网消息层的最短路径）。本实现是 **MQTT 3.1.1 的子集**：
CONNECT/CONNACK、PUBLISH（仅 QoS0）、SUBSCRIBE/SUBACK、PINGREQ/PINGRESP、DISCONNECT；
主题通配符 `+`/`#` 完整实现（含"`$` 主题不被 `#`/`+` 匹配"的规范细节）。
**不做**：QoS1/QoS2 的握手与重发、retained message 存储（retain 位原样转发但不落库）、
Will 消息、用户名/密码、TLS、会话保持（每次连接都是干净会话）。
**边界声明**：本实现按规范子集自洽并通过自身对拍；**未与第三方实现互测**
（那需要装 mosquitto，属本决策外），README 不留"应该能互通"的口头承诺。

## 运行

```
run.bat                                          # 两步：23 项测试 → 六段演示（几秒钟）
python -m unittest discover -s tests             # 23 项（真 socket 端到端，约 24s）
python tests\test_mqtt.py                        # 同上（双入口同数）
python demo.py                                   # 六段；DB 与 SVG 产物在 build\
python tools\logdiff.py a.log b.log              # 两次 run.bat 日志的规范化比对
```

零依赖：纯标准库（socket/selectors/threading/sqlite3/json）。**零下载零安装**。

## 目录

| 路径 | 是什么 |
|---|---|
| `mqttlite/packets.py` | 字节级编解码：变长 Remaining Length、八种报文、通配符匹配、坏包分类（`MalformedPacket`/`IncompletePacket`） |
| `mqttlite/broker.py` | selectors 单线程事件循环：握手、订阅表、按过滤器路由、PING、**同 id 顶号**、坏包只断一条连接 |
| `mqttlite/client.py` | 客户端 + **ResilientClient**（PING 探活、断线重连、自动重订阅、safe_publish） |
| `mqttlite/sensors.py` | 模拟工业传感器：随机游走 + spike/freeze/dropout 三类异常（**带账本**） |
| `mqttlite/recorder.py` | 入库端：订阅 `sensors/+/data` → SQLite（幂等主键；实收/分布/异常/缺口四个对账口） |
| `mqttlite/svgplot.py` | 手写 SVG 折线图（异常红圈、多设备曲线、自包含） |
| `tests/test_mqtt.py` | 23 项测试（字节级手算表 / QoS0 语义 / 重连恢复 / 完整性账本 / SVG 结构） |
| `tools/logdiff.py` | 日志规范化比对（只规范两处【实测】数字与 unittest 计时） |

## 知识点 ↔ 实现 ↔ 怎么被验证

| 课程知识点 | 代码 | 验证方式 |
|---|---|---|
| 固定头与变长 Remaining Length | `encode/decode_remaining_length` | **手算边界表**：127→`7f`、128→`80 01`、16383→`ff 7f`、16384→`80 80 01`；超 4 字节拒收 |
| 报文字节级正确 | `encode_connect/publish/subscribe` | **逐字节十六进制对照**（CONNECT 16 字节、PUBLISH 9 字节、SUBSCRIBE 9 字节全部手算），demo 第 1 段并排打印 |
| QoS0 的"至多一次" | broker 不做 ack/离线队列 | 断线期间的发布**不补收**（专项用例）；"宕机中 safe_publish=False → 重启后只收到之后那条" |
| 通配符路由 | `topic_matches` | 12 条手算表（`a/+/c` ✓、`a/+` 不匹配三层、`a/#` 匹配 `a`、`#` 不匹配 `$SYS/x`…） |
| 订阅表与多订阅者 | `broker._subs` | 两个订阅者都收到（route 返回 2）；不相关主题 0 投递 |
| 坏包隔离 | `MalformedPacket` → 只断该连接 | 未知类型/先发 PUBLISH 未握手 → 该连接被关闭，**另一条好连接毫发无损**（断言） |
| 会话接管（同 id 顶号） | `broker._dispatch(CONNECT)` | 同 client id 第二次连接 → 旧连接被顶、`takeovers=1`、`client_count=1` |
| 断线重连与重订阅 | `ResilientClient` | 停 broker→同端口重启→自动重连（`reconnects=1`）+ 订阅表恢复 + 新消息到达；**PING 探活**是 QoS0 下的唯一"还活着吗" |
| 传感器异常与账本 | `SensorSimulator` | spike/freeze/dropout 三类**按账本注入**；库里异常计数与 seq 缺口逐数对上 |
| 链路完整性 | `Recorder` | 590 实发 == 590 实收 == 590 行；按设备分布对账；解析失败 0 |
| 曲线页 | `svgplot.line_chart` | SVG 结构断言（polyline 数=设备数、circle 数=异常数）；产物 11KB 可用浏览器打开 |

## 实测（2026-10-02，首次交付；数字均为本轮现算）

- 测试：**23 项全过、双入口同数**（约 24s）。
- 演示链路：3 设备 × 200 轮 → 实发 590 / 实收 590；按设备 {dev-01: 196, dev-02: 198, dev-03: 196}；
  异常账本 {spike: 25, freeze: 19} 与库一致；缺口账本 {4, 2, 4} 与库一致；解析失败 0。
- 吞吐【实测】：357 条/秒（含 JSON 解析与 SQLite 落库，本机 localhost）。
- 重连现场：宕机前发 True / 宕机中 False（丢的就是丢了，QoS0）/ 重启后 True；
  自动重连 1 次、订阅恢复、耗时【实测】17 ms（含 broker 启动）。
- 产物：`build/sensors.db`（53KB）、`build/dev01_temperature.svg`（11KB，17 个异常标记）。
- `run.bat` 连跑两次退出码 **0**、`build/` 之外无新增、`not recognized` 0；
  两次日志经 `tools/logdiff.py` 规范化后**逐字相同（各 67 行）**，规范项两侧对称（吞吐/重连耗时/单测计时各 1）。

## 坑（都留了钉子）

1. **入库端忘了订阅**：`Recorder` 第一版只挂 `on_message` 没调 `subscribe`——端到端测试
   立刻红在"实收 0 != 445"上。消息链路里"少挂一环"是静默断链的典型，测试要端到端才看得见。
2. **`ensure_connected` 必须用 PING 探活**：TCP 半关闭下，对端已死时 `sendall` 仍会"成功"，
   于是"宕机中发布"会假报 True。QoS0 没有 ack，**唯一的存活探针就是 PINGREQ/PINGRESP**。
3. **重连测试的"顺序"本身就是语义**：先发布后重连 ⇒ 消息在无人订阅时就丢了——
   测试第一版正是这么写红的，注释里写明"QoS0 不补历史"。
4. **漏关 socket 会污染日志比对**：ResourceWarning 里带随机 fd 与端口号，日志没法逐字比；
   `Client.connect()` 现在**先 close 旧连接**（重复 connect 不再把旧 socket 丢给 GC）。
5. **字典打印顺序随网络到达序漂移**：`by_device` 的插入序 = 消息到达序（不稳定）——
   demo 打印前一律 `sorted`，这是"输出可复现"的细节而不是洁癖。
6. **seq 是轮次号，不是发送数**：dropout 那几轮 seq 照样 +1，正好在库里留下缺口——
   "缺口数 == dropout 数"是完整性对账的第四项。

## 明确不做（本期范围外）

QoS1/QoS2（握手、重发、去重）、retained message 存储、Will、认证与 TLS、持久会话、
`$SYS` 系统主题、集群桥接；**未与第三方实现（mosquitto/paho）互测**——需要装包，属决策外。

## 练习建议（G2，自己动手）

1. 实现 QoS1 的 PUBACK：发送端缓存未确认消息并在重连后重发——先写"进程内掉线重发"的测试，
   再说清为什么 QoS1 也只是"至少一次"（重复投递要靠接收端去重，代码里的幂等主键正是为此）。
2. 给 broker 加 retained message：订阅时补发每个过滤器的最后一条保留消息，
   并让 `test_retain_flag_passthrough_no_store` 反过来变成"保留消息必须补发"。
3. 给 `ResilientClient` 加指数退避与抖动，用假时钟（注入 sleep 函数）测退避序列的可复现性。
4. 把 broker 换成 `asyncio` 再实现一遍，与 selectors 版跨实现跑同一批测试——
   体会"同一协议、两种并发模型"的等价性。
