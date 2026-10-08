# SensorHub —— 物联网监测（P6）：传感器 → MQTT → SQLite → 曲线 → 告警

**定位**：把 B35 手写 MQTT 的"真件"编排成一条常驻生产线——3 台模拟传感器各自
用真套接字连上真 broker 发布读数，入库端订阅落 SQLite，产品侧对入库读数做
**阈值告警**并给出监测台（总账 + 对账表 + SVG 曲线 + 告警台账）。

## 零件库说明（如实区分）

**MQTT 全链路零重写**，全部直接 import B35 mqttlite 的真实实现：

| 零件 | 来源 | 在产品里的角色 |
|---|---|---|
| Broker | mqttlite.broker（selectors 真套接字） | 本进程内的消息中枢（端口自动分配） |
| SensorSimulator | mqttlite.sensors | 每台设备一个：随机游走 + spike/freeze/dropout（带账本） |
| Recorder | mqttlite.recorder | 订阅 `sensors/+/data` → SQLite（幂等主键 + 四个对账口） |
| line_chart | mqttlite.svgplot | 曲线页的自包含 SVG（异常点标红圈） |

**产品侧只补两件 B35 没有的**：

1. **阈值告警台账**：对入库读数逐行评估 `temp_max`（默认 85.0）/ `vib_max`
   （默认 4.0），严格大于才算；落 `alerts` 表（主键 `device+seq+rule` 幂等，
   重复评估不重复计数，重启后台账仍在）。台账与 readings 可**双向对账**：
   每条告警必对应一条越限读数，反之亦然——设备自报的 anomaly 标记与产品侧
   规则是两套独立口径（测试专门钉住"自报正常、实际越限照样被抓"）。
2. **编排与观察面**：节拍线程、`inject` 管理口注入（走 `broker.route()` 的
   真实订阅表，确定性送样本）、`status` 总账（设备账本 vs 入库实收）。

## 线程模型（如实声明）

服务模式下 mqttlite 的 socket 与 sqlite 连接全部在 **hub 线程**里建立并只被它
使用；HTTP 处理器的读写经队列汇入 hub 线程（SQLite 连接跟人走，跨线程用就是
ProgrammingError——测试里真抓到过一次，见下）。测试/脚本可用手动模式
（`interval=None`）在调用线程里确定性推拍。

## 运行

```
run.bat                                   # 双入口测试（25 项）
python server.py --port 8022              # 监测台服务（Studio 门户可一键启停）
python server.py --port 8022 --interval 0.2   # 加快节拍看曲线动起来
```

页面：**总账**（入库行数/broker 客户端/拍数/告警数）→ **阈值编辑器**（S1：
改完立即生效并落盘 rules.json，重启仍在）→ **对账表**（每台设备
发出/尖峰/卡值/断数 vs 实收入库/seq 缺口）→ **曲线**（temp 叠加设备自报异常点）
→ **告警台账**（最新在前；S2 确认按钮，已确认持久标记）。
API：`/api/status`、`/api/series`、`/api/chart`、`/api/alerts`、
`POST /api/rules`、`POST /api/alerts/ack`、`POST /api/tick`、`POST /api/inject`。

## 测试策略（25 项 = 13 引擎 + 11 服务 + 1 真套接字）

**全链路对账钉值**（seed=2026 + 计划 0.2/0.2/0.2 + 8 拍的确定性流，探针实测）：
发出 21 == 实收 21 == 入库行数；自报异常 spike 3 / freeze 7 == 设备账本；
gaps {0,1,1}（dev-01 的断数落在 seq 1——首条成功之前，gap 区间量不到，
两条账各自都对，这是 B35 对账口径的诚实呈现）；告警 temp_max 14（spike 后
温度居高不下）、vib_max 0。**告警语义**：注入 120 越限即告警、压线 85.0 不算、
重复评估幂等、重启后台账仍在且重评估不加账。**确定性**：同种子两次运行剔除
ts 逐条一致。**守卫**：注入口设备名白名单（topic 注入面）、未启动先拒。
**服务**：status/series/chart/alerts/rules/ack/tick/inject 全覆盖（压线 400、bool 冒充
数字 400、非法设备名 400、幽灵设备 404）、SVG 现算含异常红圈、真套接字全链路
（HTTP 线程经队列汇入 hub 线程）。

**S1/S2（2026-10-07，+6）**：S1 阈值页面化——set_rule 立即生效（新口径下不再
告警）+ rules.json 原子落盘重启仍在 + 校验收口（未知规则/越界/NaN/inf/bool/
字符串全 400，上下限含等号）+ `POST /api/rules` 后 status 同步；S2 告警确认——
ack 幂等（重复/不存在 False→404）、acked_at 落库、unacked 汇总、重启仍在、
无 acked_at 列的老库 ALTER TABLE 自动迁移照常读写。

## 已知边界（如实声明）

- 轮六（二）收官：**Studio 门户第六个 managed 产品**（真启停钉住，端口 8022）；
- QoS0"至多一次"：断数就是丢了（B35 语义），产品不补历史，缺口如实进账；
- 告警评估是全表扫描（教学规模无压力），阈值变更后会按新规则重评历史（幂等）；
- 告警的 `raised_at` 是评估时刻墙钟——两次运行台账条数一致但时刻不同（非确定字段）；
- 服务端启动把 `interval=None` 视为 1.0：HTTP 服务必须跑节拍线程（手动模式
  的内联执行只属于单线程的测试/脚本）；
- Studio 停止 = TerminateProcess：SQLite 每拍落盘崩溃安全，broker/客户端是
  守护线程随进程收走（重启续用同一库文件，读数与告警台账都在）；
- 观感归用户验收。
