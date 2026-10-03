# B11-net-lab —— 计算机网络：HTTP 子集 + IO 多路复用 + UDP 可靠传输

课程设计里"计算机网络"这一门的动手部分。三件事放在一起做，因为它们本来就是同一条链路上的三层说法：

1. **应用层**：一个够用的 HTTP/1.1 子集（解析请求、路由、生成响应），但每个边界都按 RFC 讲得清道理；
2. **传输层之上**：用 `select` 在**一条线程**里同时服务多条连接，keep-alive、半包、超时、资源回收全部可见可测；
3. **传输层**：UDP 什么都没有，所以自己写 Go-Back-N——序号、校验和、累计确认、超时整窗重传、可复现丢包实验。

压轴验收是**与标准库对拍**：同一份请求字节交给 `http.server` 的解析器和本项目的解析器，
结论必须一致（或分歧被写成断言钉住）；同一份响应字节交给 `http.client` 和本项目的解析器，
状态码、头部、体必须逐字节一致。

## 运行

```
run.bat                              # 自测（74 + 16 项）+ 全流程演示
python tests\test_netlab.py          # 只跑主测试
python tests\test_against_stdlib.py   # 只跑与标准库的对拍
python demo.py                        # 只看演示（只绑 127.0.0.1，跑完全部关闭）
```

`run.bat` 用 CRLF + `chcp 65001` + `set PYTHONUTF8=1`；`echo` 文案里不出现未转义的 `>`，
否则 cmd 会把它当重定向，既不报错也不改退出码，只在目录里凭空留一个垃圾文件。

## 目录

```
netlab/http1.py            HTTP/1.1 子集：请求解析、响应构造、响应解析（含硬边界）
netlab/server.py           select 事件循环 + keep-alive 的单线程服务器 + 内存键值应用
netlab/client.py           裸 socket 客户端（半包、畸形字节、连接复用都要能手工构造）
netlab/udp.py              数据报格式（kind/seq/len/crc32）、真回环链路、种子化坏信道
netlab/gbn.py              Go-Back-N 发送窗 / 按序交付 / 仿真与真套接字两种驱动
tests/test_netlab.py       解析边界、服务器行为、多路复用与资源回收、UDP 与 GBN
tests/test_against_stdlib.py  与 http.server / http.client 的解析器对拍 + 分歧表断言
demo.py                    五段演示：请求旅程 → CRUD → 复用与拒绝 → UDP → GBN 实验
```

## 课程知识点 · 代码模块映射

| 知识点 | 在哪实现 | 用哪个测试/实验验证 | 取舍 |
|---|---|---|---|
| 报文格式与协议字段 | `http1.parse_request`、`udp.encode/decode` | `TestRequestParsing`、`TestDatagramFormat` | 只实现子集，但字段非法必须拒，不"宽容" |
| 可靠传输：序号/确认/重传 | `gbn.Sender/Receiver` | `TestGbnOverSimChannel` 全场景逐字节一致 | GBN 整窗重传，不上 SR（选做练习） |
| 滑动窗口与序号回绕 | `gbn.seq_diff`、`window ≤ space/2` 检查 | `TestSeqArithmetic`、`test_sequence_numbers_wrap_around`（space=8 绕 3 圈） | 内部用不回绕计数，上线才取模，避免边界歧义 |
| 超时与 RTT | `Sender.timeout` 挂在 base 上 | `test_out_of_order_is_dropped_not_buffered` | 固定超时，不做 RTT 自适应（练习 2） |
| 校验和与差错控制 | `zlib.crc32` | `test_one_bit_flip_is_caught`（40 个位置逐一翻位） | 校验失败当"没收到"，不区分坏包/丢包 |
| 信道损伤的统计特性 | `udp.SimChannel`（丢包/损坏/重复/乱序/抖动） | `TestSimChannel`（同 seed 轨迹一致） | 虚拟时钟，与机器快慢无关，实验可复现 |
| TCP 字节流：粘包/半包 | `server.Conn.inbuf` + `parse_request` 返回消耗字节数 | `test_half_packet_then_rest`、`test_pipelined_requests_take_their_own_bytes` | 增量解析，不做"读满再解" |
| 长连接与并发 | `_keep_alive`、`Server._tick` | `TestKeepAliveAndPipelining`、`TestMultiplexing`（`peak_open`） | 单线程 select，不做线程池 |
| IO 多路复用 | `select.select(readable, writable, …)` | `test_many_concurrent_connections_single_thread` | 非阻塞 + 发送缓冲，处理部分写 |
| 拥塞/准入控制 | `max_conn` 拒绝 + `idle_timeout` 回收 | `test_over_connection_limit_gets_503`、`TestResourceRelease` | 只做上限与超时，没有队列 |
| 应用层语义（方法/状态码） | `STATUS`、`_dispatch` | `test_method_not_allowed_and_unknown_method`、对拍分歧表 | 未实现的方法一律 405/501，不含糊 |

## 一条请求的旅程（demo 第 1、3 段能看到全部中间产物）

```
客户端字节  PUT /kv/repair HTTP/1.1\r\nHost: …\r\nContent-Length: 12\r\n\r\n水管漏水
   ↓ select 报告可读，recv 进 Conn.inbuf（可能只到一半，也可能到了三个请求）
解析        找 CRLFCRLF → 逐行校验（裸 LF？超长？obs-fold？CL 冲突？）
   ↓        → 目标解码（百分号、`..`、scheme）→ 头部表 → keep-alive 判定
路由        (方法, 路径模式) → handler，返回 (状态码, 头部, 体)
构造        build_response：状态行 + Content-Length/Date/Server/Connection + 体
   ↓        进 Conn.outbuf；非阻塞 send 可能只写出去一部分，剩下的下一轮继续
收尾        还要读下一个请求？不需要了 → 写 FIN（半关闭）→ 等对端 EOF 才回收 socket
```

## 支持的 HTTP 子集

* 方法：`GET`、`HEAD`、`POST`、`PUT`、`DELETE`（其他一律 405，`OPTIONS` 501）
* 版本：`HTTP/1.0`、`HTTP/1.1`；其他 505
* 目标：只接受 origin-form（`/path?query`），绝对 URI 与 `*` 给 501
* 头部：`Host`、`Connection`（close / keep-alive）、`Content-Length`、`Expect`（417 拒）
* 体：只认 `Content-Length`；`Transfer-Encoding: chunked` 直接 501，**不忽略**
* 硬上限：请求目标 2048、单行 8 KiB、头部总数 100、头部总量 32 KiB、请求体 1 MiB、
  单连接缓冲 32 KiB + 1 MiB；超限分别 414 / 431 / 413
* 状态码：本项目自己会发出 200 201 204 400 404 405 408 413 414 417 431 500 501 503 505；
  reason 表只收录真用得到的码，表外的码必须显式给 reason（不静默给个"未知"）。
  **2026-09-30 为 B31 短链补了 301 302 303 304 307 409 415 429**：`Server._reply` 不给应用传 reason 的机会，
  表里少一条 302 的后果是事件循环线程抛 `ValueError`——客户端只表现为"等不到响应"，和当年漏 503 是同一类故障。
  补齐后 B11 全部测试重跑通过（见下面"测试策略"）
* 应用：内存键值表 + `/sum`、`/echo`、`/stats`（`/stats` 是"并发与失败都记在账上"的抓手）

## 踩过的坑（每一条都是先跑出错误、再修、再钉成测试）

1. **`%xx` 解码全废**：`bytes` 下标取出来是 `int`，却拿字符串集合去判十六进制，
   于是 `%20`、`%E4%BF%AE` 全被当非法转义。合法请求被自己的解析器拒了。
2. **裸 LF 被当成"数据还没到"**：找不到 `CRLFCRLF` 就返回"需要更多数据"，
   而 `GET / HTTP/1.1\n\n` 永远等不到——客户端挂到超时才知道自己写错了。现在缓冲里
   一旦出现裸 LF 就立刻 400。
3. **头部值含非 ASCII 抛 `UnicodeDecodeError`**：不是 `HttpError`，一路冒到服务端
   变成 500。协议层的非法输入必须是 400，`decode` 之前先按字节校验可见 ASCII。
4. **小写方法被悄悄折成 `GET`**：RFC 9110 说方法名大小写敏感。`get` 和 `GET` 在
   我们和标准库里必须被当成同一个结论——都不当 GET 执行（标准库 501，我们 405）。
5. **`Connection: close` 只写进响应头，没真的关**：客户端读完响应继续等，直到超时。
   承诺写在头部里就得在行为上兑现，`_handle` 里必须把连接置成收尾状态。
6. **HEAD 的 `Content-Length` 被写成 0**：拼响应前就把体清空了，长度算的是空体。
   HEAD 的长度描述的是"允许带体的话有多大"，必须按真实体计算、只省略体。
7. **超出连接上限时"发完 503 立刻 close"，503 被 RST 冲掉**：Windows 上只要接收缓冲
   还有没读走的字节，`close()` 就是中止关闭，把刚发出去的响应一起作废。同一个坑在
   413/431 这些提前拒绝的路径上也会踩。统一改成：**发完承诺的响应 → `shutdown(SHUT_WR)`
   写 FIN → 继续把对方字节读干净 → 收到 EOF 才回收**，赖着不走的由空闲超时兜底。
8. **`STATUS` 表漏了 503**：构造响应时抛 `ValueError`，事件循环线程当场死掉，
   而线程里的异常被咽了——表现是"连上去没有任何响应"，看起来像超时或死锁。
   现在 `Server.stop()` 会把循环线程的异常抛回主线程。
9. **`select` 返回的对象当 dict 键用**：`fd in self.conns` 判的是整数键，永远 False，
   可读事件全被丢掉。必须 `self.conns.get(fd.fileno())`。
10. **仿真信道"只看队头"**：用队列时，一个晚到的头包会堵住后面所有包，
    `jitter`/`reorder` 形同虚设——测出来的 GBN 根本没见过乱序。改成按到期时间取堆顶，
    并加了一条"必须真能倒过来交付"的测试钉住它。
11. **仿真信道两只插头接在同一方向**：A 端发到队列 0、又从队列 0 读，双方都只读自己
    发出去的那条线——真套接字能跑通、仿真一个包都收不到，发送方无限重传。
12. **回绕序号不能直接比大小**：`space=8` 时 1 和 7 的真实距离是 -1（7 是 1 的前一个），
    直接 `a > b` 会说 7 更大。窗口也必须 `≤ space/2`，否则新旧序号分不开。
    实现上 base/nextseq 用不回绕的逻辑计数，上线时才取模。
13. **对拍夹具自己会造假日志**：覆写 `send_error` 时没像标准库那样置
    `close_connection`，stdlib 接着把残留字节当第二个请求解析，第二个错误把真正要记的
    结论盖掉了——"标准库竟然 400" 其实是我们夹具的错。
14. **用"进程里 socket 对象数"判断 fd 泄漏会假报警**：客户端关闭是异步被 `select`
    发现的，测到的数量取决于时序。改成看服务端自己的账：停服后连接表必须空、
    `open_now` 必须归零、被拒/被超时的连接必须让客户端读到 EOF。

## 与标准库的分歧（Python 3.12.3 实测，已写成断言钉住）

同样这些字节，`http.server.BaseHTTPRequestHandler` 与本项目：

| 输入 | 我们 | 标准库 | 为什么我们更严 |
|---|---|---|---|
| `Transfer-Encoding: chunked` | 501 | **200**（收下但不读体） | 不实现就得拒；忽略它是请求走私的入口 |
| 两个不一致的 `Content-Length` | 400 | **200** | 前后端理解不一致时，谁先读到什么是不确定的 |
| 裸 LF 换行 | 400 | **200**（`readline` 认 `\n`） | 同一字节流被切成两种请求 |
| 9000 字节的请求目标 | 414 | **200** | 缓冲区与日志都被一条超长行拖走 |
| `/a/../b`、`/a/%2e%2e/b` | 400 | **200**（不检查） | 现在不接文件系统，接了就来不及了 |
| `Expect: 100-continue` | 417 | **200**（不理会） | 不实现就明说，不要装作支持 |
| 小写方法 `get` | 405 | 501 | 结论一致：都不当 GET 执行 |
| 200 条头部 | 431 | 431 | 与标准库同判 |
| 方法名里有空格 `G T` | 400 | 400 | 与标准库同判 |

前六行是"我们拒、标准库收"的方向性差异，测试 `TestDocumentedDivergences` 会同时断言两边；
哪天前面的库改了默认，测试先叫，README 再改。

## 测试策略（75 + 16 = 91 项，另有 62 个 subTest）

（2026-09-30 补 3xx/409/415/429 时新增一条"重定向状态码可构造"的回归，故由 90 变 91。）

* **解析层**：合法/半包/畸形/越界逐条断，包括 40 个不同位置的单bit翻体能被 crc 抓到。
* **服务器行为**：CRUD、204 不带长度、HEAD 与 GET 长度一致、UTF-8 键名、405/501/404、
  查询串 `+`/`%20`/缺值、pipelining 一次读进三个请求、半包后补包。
* **失败与回收**：413 在没读完体时就拒、431/414/400/501/505、垃圾字节不崩服务、
  空闲超时先给 408 再写 FIN、被拒连接不会因滴字节续命、150 条短连接后 `open_now` 归零、
  `max_conn` 满时新连接收到 503 而不是被掐。
* **UDP/GBN**：干净/丢包/损坏/重复/乱序/全叠加 × 3 seed 全部逐字节一致；
  序号空间 8 绕 3 圈；`drop=1.0` 时在期限内明确"没完成"而不是死循环；
  同 seed 两次轨迹（时隙与发送数）完全一致；窗口 1/2/4/8 的时隙单调改善；
  真 127.0.0.1 UDP 上 30000 字节一次不差（30 个包，0.3s）。
* **对拍**：`http.client` 驱动我们的服务器（keep-alive、HEAD、413、必需头部）；
  同一份响应字节交给两个解析器，结论（状态码 + 排序后的头部 + 体 + 是否刚好吃完）必须相同；
  截断一个字节时两边都判"没读完"。

## 已知局限（说清楚，不含糊）

* **单线程**：handler 里做一件慢事，所有人一起等。没有线程池、没有异步框架。
* **不是通用 Web 服务器**：无 TLS、无 chunked/gzip/Range/条件请求/重定向/代理语义，
  不实现 `OPTIONS`、`CONNECT`、`PATCH`；`Expect: 100-continue` 直接 417。
* **边界值是写死的常量**（2048 / 8 KiB / 100 / 32 KiB / 1 MiB），不能按虚拟主机配置。
* **准入控制只有上限 + 超时**：没有队列、没有连接速率限制，被拒的连接仍占一个名额
  直到对方关闭或空闲超时；真实对抗 slowloris 需要更细的准入策略。
* **keep-alive 没有单连接请求数上限**，靠 `idle_timeout` 回收。
* **GBN 不做拥塞控制**，超时是固定值（没有 RTT 估计），丢一个包重传整窗，
  丢包 40% 时有效载荷比只有 8.5%——这是 GBN 的固有学费，不是实现缺陷。
* **仿真信道 ≠ 真实网络**：真实丢包是相关的、突发的、与排队延迟耦合的；
  这里的模型是按概率独立抽签 + 虚拟时隙，目的是**可复现**，不是**逼真**。
* **真 UDP 只在 127.0.0.1 验证过**：没有跨主机、没有防火墙/NAT 场景，
  也没有用抓包工具对照过重传计数（本机未授权抓包，属课设范围外）。
* **测试依赖本机可用端口**：只绑回环、端口交给系统分配；并发测试用 8~10 条连接，
  不会打满文件描述符，但在极受限的容器里可能偏慢。

## 练习建议（G2，自己动手）

1. 把 `Expect: 100-continue` 真正实现（先回 100 再读体），说明"忽略 chunked"为什么
   会导致请求走私，并补一条两侧理解不一致的测试。
2. 把固定超时换成 SRTT/RTTVAR（Jacobson/Karels）估计，用同一 seed 比较重传次数与时隙。
3. 实现 SR（选择重传）：加 NACK/缓存 + 单个定时器，同一批丢包轨迹下比较有效载荷比。
4. 给服务器加线程池版本，测 `peak_open` 与响应延迟，说明为什么单线程版里
   `sleep` 一个 handler 会拖垮所有客户端。
5. 用 `GET /stats` 设计一个失败实验：让客户端在收到响应前断开，解释服务端
   `open_now` 为什么会先涨后落，并说明"退出码为 0 不代表没留垃圾"这条验收规则
   在本项目哪一处救了你。
