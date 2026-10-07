# CacheKV —— 自托管键值缓存（P3）

**定位**：给自己（和其他产品）用的键值缓存——TTL 过期、快照持久化、统计页。
**零件库纪律**：KV 引擎与快照持久化**直接 import B38 mini-redis 的真实实现**
（`redislite.store.Store`：SET/GET/DEL/EXPIRE/TTL/INCR + 惰性/主动过期双策略 +
clock 可注入；`redislite.dbsnap`：临时文件 + fsync + os.replace 原子写）。
CacheKV 产品层只加了三样：统计账本、HTTP API（webframe）、快照调度。

## 运行

```
run.bat                                   # 双入口测试（19 项）
python server.py --port 8021              # 启动缓存服务（统计页在根路径）
```

快照在 `data/snapshot.bin`：启动载入、每 60 秒**脏了才写**（B10 的
"没改动别写盘"经验）、停止时强制刷一次。`data/` 已进 .gitignore。

## HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| PUT | /api/kv/<key>?ttl=秒 | 写入（体即值；ttl 可选；ttl 非法 400）→ 201 |
| GET | /api/kv/<key> | 读取（不存在/已过期 → 404） |
| DELETE | /api/kv/<key> | 删除（204 / 404） |
| GET | /api/keys | 存活键列表 |
| GET | /api/overview | 仪表盘聚合口（轮九）：存活键明细（大小/剩余 TTL，按 TTL 升序）+ 统计 + 快照状态 |
| POST | /api/demo | 一键注入演示数据（轮九）：12 键混合 TTL + 制造命中/未命中账；幂等 |
| GET | /api/stats | 命中/未命中/命中率/键数/快照次数（3 秒自刷新统计页） |
| POST | /api/save | 手动快照 |

## 测试策略（19 项）

引擎语义对拍（**与直接调用 B38 Store 逐条一致**：读写/TTL/惰性过期，共同时钟推进）、
INCR、统计账本（hit+miss == 总读取）、主动过期周期、
快照重启往返（值 + TTL 都保住）、快照线程（**未脏不落盘**，真线程 50ms 轮）、
HTTP 全套（PUT/GET/DELETE/404/TTL 过期 404/坏 ttl 400/stats 对账/keys/save）、
**真套接字真重启**（写两键 → 停机自动刷快照 → 重新 build → 数据与 TTL 都在）。

## 已知边界（如实声明）

- 引擎复用踩过一个坑：产品层的计数 dict 不能叫 `self.stats`——B38 Store
  内部有自己的 stats 账（expired_lazy 等），覆盖它会让惰性过期当场 KeyError
  （探针定位，注释与测试双钉住）；
- 快照为全量写（B38 原子写保证崩溃安全）；数据量大后可考虑 AOF 增量（B38 有复制经验）；
- 单进程单实例；无淘汰策略（LRU 等进后续轮次）；值上限 1 MiB（沿 B38）。
