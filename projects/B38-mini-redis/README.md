# B38-mini-redis —— 手写 Redis 子集：RESP2 + 单线程事件循环 + 双策略过期（软件工程案例分析与实践）

**课程映射**：软件工程案例分析与实践（PLAN 批次 8）。

一句话：**先读案例再动手**——`docs/case-study.md` 先写清楚 Redis 的设计要点
（为什么单线程、RESP 长什么样、过期为什么两条腿走路、RDB/AOF 取舍、内存编码），
再把它落成一个可跑、可测、可对拍的**教学子集**：字符串类型 + 8 条命令，
惰性删除 + 主动采样过期，selectors 单线程事件循环，简化快照；
没有真 Redis 可对比（本机与 WSL 均无、不装），对拍换成
**独立第二解析器交叉读 + 语义表逐条 + 协议 fuzz** 三条腿。

**范围声明**：`GET/SET/DEL/EXPIRE/TTL/INCR/PING/SAVE` 八条命令、字符串一种类型。
**明确不是完整 Redis**：无事务/订阅/复制/集群/多库，快照是自定格式（非 RDB 兼容），
主动过期只由命令计数触发（真实 Redis 另有时间触发）——完整偏离表见
`docs/case-study.md` §6。零第三方依赖、零下载。

## 运行

```
run.bat                                   # 两步：36 项测试 → demo（六段；不落任何产物文件）
python -m unittest discover -s tests      # 36 项（双入口同数）
python tests/test_redis.py                # 直跑同 36 项
python demo.py                            # 六段演示（唯一实时测量是末段吞吐【实测】行）
python tools/logdiff.py a.log b.log       # 两次日志规范化比对（规则两类，会打印计数）
```

## 目录

| 路径 | 是什么 |
|---|---|
| `redislite/resp.py` | RESP2 流式帧解码：粘包/拆包、内联×数组混合、协议错误分类（请求/回复两条通道） |
| `redislite/store.py` | 字符串键空间：语义表命令 + 惰性删除 + 主动采样（时钟可注入，边界可测） |
| `redislite/server.py` | selectors 单线程事件循环：多客户端、管线、坏包只断一条连接、CLOSE_AFTER_REPLY |
| `redislite/dbsnap.py` | 简化快照：版本魔数 + SHA256 + 原子写（临时文件 + os.replace） |
| `redislite/client.py` | 极简客户端（与服务器共用解码器；CLIENT_CLOSE 语义归一） |
| `tools/reference_resp.py` | **独立第二实现**（游标+递归风格）：交叉读的参照，不 import 主实现 |
| `tests/test_redis.py` | 36 项（解析/语义/过期/交叉对拍/改坏必红/fuzz/快照） |
| `docs/case-study.md` | **先写的**案例分析：设计要点 + 语义表 + 偏离表 + 对拍策略 |
| `demo.py` · `run.bat` · `tools/logdiff.py` | 演示与交付三件套（本仓库通例） |

## 知识点 ↔ 实现 ↔ 怎么被验证

| 课程知识点 | 代码 | 验证方式 |
|---|---|---|
| 单线程串行化=原子性 | `server.py` selectors 循环 | 两客户端交替 `INCR` 得 1、2（无锁也不会丢更新）；同循环里坏包只伤自己 |
| 流式解析（粘包/拆包） | `FrameDecoder` 累积缓冲 | 同一字节流按 1..9 随机块长喂入 ×20，帧序列与整体喂入逐条相等 |
| 内联与数组混合 | `_cut_command` 双通道 | 同一条流里 `PING\r\n`、`*2\r\n$3\r\nGET...`、带引号内联并存；`*0`/空行跳过 |
| 二进制安全 | 显式长度定界 | 值含 `\r\n\0` 全程往返无损（请求与回复方向都测） |
| 协议错误分类 | `ProtocolError` 文本 | 六类错误文本逐字断言，且与第二解析器**消息一致** |
| 过期：惰性 + 主动 | `_check_expired` / `active_expire_cycle` | 假时钟：deadline 当刻即过期、TTL 向下取整、负 EXPIRE 即删、TTL -1/-2；主动周期在"从未 GET"的键上也清内存（20/轮 ×4 轮、>25% 命中再来） |
| 严格整数（string2ll 口径） | `store.parse_int64` | `01/1.0/+1/-0/空串` 全拒、int64 溢出两种错误文本分别是"not an integer"与"would overflow" |
| 键空间语义 | `dispatch` | SET 清 TTL、INCR 保留 TTL、DEL 只数存在的键、EXPIRE 覆盖旧时间 |
| 快照工程要点 | `dbsnap.py` | 原子写（无 .tmp 残留）、改一字节 → SnapshotError、坏文件拒启（服务器构造即抛） |
| 对拍（没有真 Redis） | `tools/reference_resp.py` | 请求/回复两方向跨语料逐条相等；**改坏每一个采样字节，两器要么都收要么都拒**（不允许分歧） |
| fuzz | 测试 + demo | 解析器 400 条随机流只有定义好的错误；服务器 3 构造坏包（错误帧→断开）+ 25 随机弹不崩、新连接可用 |

## 实测（2026-10-02，首次交付；数字均为本轮现算）

- **36 项测试双入口同数**（`discover` 与直跑均 36 OK，`-W error::ResourceWarning` 下也干净）；
  `run.bat` **两次退出码 0**、**无任何新增文件**（demo 全部写系统临时目录，仓库零产物）、
  两次日志经 `tools/logdiff.py` 规范化后**逐字相同**（各 67 行；规范项 = 单测计时 1 + 吞吐 1）。
- demo 关键读数：惰性过期后 `GET → nil` 且 lazy 计数 +1；100 个到期键从未被访问，
  一次主动周期删 80、剩余 20 由下一周期清完（active=100、lazy=0）；
  交叉读 4 条命令与回复流全部逐条相等；构造坏帧 6/6 拒绝；服务器 fuzz 后
  `protocol_errors=3` 且新连接 PING 正常；快照 114 字节、重启后值与 TTL=60 原样。
- 吞吐【实测】：2000 次 `INCR` 往返 151.1 ms（≈ 1.3 万次往返/秒，本机回环、纯 Python 单线程）。

## 坑（都留了钉子）

1. **"时好时坏"的冒烟：客户端把 int 参数编成了 RESP 整数帧**。`c.cmd("EXPIRE","k",10)`
   的 `10` 被编码成 `:10\r\n`——**请求数组的元素必须是 bulk**，服务器（正确地）回
   `expected '$', got ':'` 并断开。探针恰好用字符串 `"10"` 全过、脚本用 int `10` 全挂，
   排查被"随机失败"的假象带偏了好几轮（改解析器、比字节流、二分命令序列……）。
   教训：**先验证自己发出去的字节**（`encode_command` 的产物打印一次就破案）；
   修复=对 int/float 做 str 化，测试钉住 `encode_command("EXPIRE","k",10)` 不含 `:`。
2. **协议错误断开前必须把错误帧发完**（真实 Redis 的 CLOSE_AFTER_REPLY 模式）：
   第一版 `_flush` 后立刻 `close`，Windows 上客户端只收到 RST（10054）**看不到错误文本**；
   改成"输出缓冲清空后再关"（`close_after_flush`），错误帧稳定送达。
3. **Windows 的 RST ≠ 优雅 EOF**：服务器关连接时客户端可能收到 `ConnectionResetError`，
   与"读到 EOF"是同一语义的两种表象——客户端必须归一为 `ConnectionClosed`，
   否则测试没法写"错误帧之后连接已断"。
4. **构造失败不能泄漏监听套接字**：坏快照拒启时 `__init__` 里已 bind 的 socket 要关
   （`-W error::ResourceWarning` 下跑测试当场抓到）。
5. **单线程服务器里"任何未捕获异常=全体瘫痪"**：调试初期 `CommandError.message`
   属性名不存在，直接把整个服务循环炸掉（所有连接一起死）。事件循环里的异常处理
   本身就是可靠性设计——这条在本项目里由"坏包只断一条连接"的测试钉住。

## 明确不做（本期范围外）

事务（MULTI/EXEC）、订阅发布、复制与集群、多数据库（SELECT）、
字符串以外的数据类型、真实 RDB 二进制兼容、AOF、时间触发的主动过期周期（留作练习）。
**一切"像 Redis"之处均为教学对齐，不宣称兼容**。

## 练习建议（G2，自己动手）

1. 给主动过期加"时间触发"通道（与命令计数并行：`select` 每次循环检查上次周期距今超过
   T 秒就触发），用假时钟写测试——顺便说清"为什么真实 Redis 需要它"（空闲时也清内存）。
2. 实现 `SETEX` 与 `SETNX`：先改 `docs/case-study.md` 的语义表，再改 `dispatch`，
   最后补测试——体会"文档先行"的顺序。
3. 给快照加一个"版本升级"场景：改 `MAGIC` 尾部版本号，让加载器对旧版本给出**可操作**的
   错误信息（而不是一句"魔数不符"）；再想想向前兼容该怎么做。
4. 用 selectors 实现 per-connection 空闲超时（30 秒无请求断开），说明它与
   Redis `timeout` 配置的差别（后者还涉及主从/发布订阅的连接豁免）。
