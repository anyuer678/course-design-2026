# 快照与成员变更：先定死的两个子问题（B41 候选③）

这份文档**先于实现**写出（2026-10-02）。B30 目前是"能逐事件查不变式"的 Raft 模拟器，
但 README 的红线写着"没有快照、没有成员变更"。本轮的验收（B41 候选③）是三个具体的问题：
① 快照后重启：状态机与快照+日志重放逐条一致；② 成员变更期间选举/复制不变式每事件 0 失败；
③ 「快照边界上的 §5.4.2」用构造场景证明仍不被违反。

论文级工作量的两个子问题都有"看起来对、实际上漏"的经典落点，所以照 B13×② 的做法：
**先把约定写死，实现只做翻译**。实现完成后本文不再改；若实现与本文不符，以本文为准、改实现。

## 一、快照（日志压缩 + InstallSnapshot）

### 1.1 快照记录与日志索引

节点新增字段（都属于**持久状态**，重启保留）：

```
snapshot: {
    last_index / last_term:  快照覆盖到的最后一条已应用条目
    sm:                      状态机在 last_index 处的**副本**
    members:                 该处的成员配置（新节点靠快照学会配置）
}
digests: dict[int, bytes]    诊断账本（见 1.4；不进恢复语义，重启原样带走）
```

日志改为"快照 + 相对段"：`log` 只装 **index > snapshot.last_index** 的条目。

```
first_log_index() = snapshot.last_index + 1
last_log_index()  = snapshot.last_index + len(log)
entry_term(i):  i == 0 → 0；i <= snapshot.last_index → snapshot.last_term
                （i < snapshot.last_index 只可能出现在防御路径里）
                i >  snapshot.last_index → log[i - snapshot.last_index - 1]["term"]
entry_cmd(i) 同理。
```

一切"`len(log)`"与"`log[x-1]`"的旧写法全部改成上述抽象——这是重构的主体。

### 1.2 压缩（日志压缩即快照）

在 `_apply` 应用完一条后检查：`last_applied - snapshot.last_index >= SNAPSHOT_THRESHOLD(=8)`
就压缩一次：快照 =（last_applied、该条目的 term、**dict 副本** of sm、当前 members、`digest_at(last_applied)`），
然后把日志替换成 index > last_applied 的段。压缩是确定性的（无随机源），同一 seed 轨迹逐次一致。

**只压缩已提交的条目**是硬纪律：压缩点取 last_applied（≤ commit），因此快照永远只含已提交内容——
「快照边界上的 §5.4.2」就是靠这一条成立的（未提交的 ghost 永远进不了任何人的快照）。

### 1.3 InstallSnapshot（RPC 语义定死）

Leader 对 follower j 的发送决策：`next_index[j] < first_log_index()` → 发快照，否则发 AppendEntries。
快照消息：`{kind:"install_snapshot", src, dst, term, last_index, last_term, sm(副本), members(排序列表), digest(hex), commit_index}`。

Follower 收到时：

1. `term < mine` → 回 `{success: False, term: mine}`，不碰状态。
2. `term > mine` → 采纳任期、转 follower；重置选举计时、记 leader。
3. `last_index <= last_applied`（陈旧/不落后）→ 回 `{success: True, match: last_applied}`，
   **不改任何状态**——已应用进度只许前进。
4. 否则采纳：快照字段整体替换、`sm = dict(msg.sm)`、`log = []`（简化：论文允许保留匹配后缀，
   本模拟全弃，靠 leader 续传；偏差在此登记）、`commit_index = max(commit, last_index)`、
   `last_applied = last_index`、`digests[last_index] = msg.digest`（中间的缺口索引不补，
   比较协议天然允许缺口，见 1.4）。回 `{success: True, match: last_index}`。
5. 之后的 AppendEntries 从 `next_index = match+1` 继续，prev 检查用 `entry_term` 抽象。

**回放校验（验收①）**：`verify_node_replay(node)` = 取快照 sm 副本，按序重放
`log` 中 index ≤ last_applied 的条目，结果必须等于 `node.sm`；再验 `digests[last_applied]`
若存在则与重放链末端一致。故意改坏一条日志条目使校验器变红——**负面对照钉住它**。

### 1.4 已应用前缀比较：哈希链诊断账本（替代旧的 applied_prefix）

旧检查拿 `log[:last_applied]` 的 (term, cmd) 元组逐条比——压缩之后条目没了。
新口径：`digests[i] = sha256(digests[i-1] ‖ term ‖ cmd)`（`digests[0] = sha256("raft30/genesis")`，
所有节点从同一个值起步），每次应用把 (i, digest) 记进账本；采纳快照时把 (last_index, 快照 digest) 记进去。
于是**任何节点在索引 i 处的 digest 恒等于"条目 1..i 的折叠"**（无论它是否亲历过那段历史）。

比较协议：两节点取 `m = min(applied)`，在双方账本都有的、≤ m 的最大索引 i 处比 digest；
相等 →（模哈希碰撞）前缀 1..i 逐条相同。哈希链保证**任何更早的分叉都会改变 i 处的值**，
所以比一个点就够。缺口（采纳快照跳过的索引）自动跳过，取下一个公共点。

账本不进快照、不参与恢复语义、重启原样带走——它是**检查器专用**的诊断设施（每条 32 字节），
真实系统没有它，靠快照边界与领导者权威；这一条在 README 局限里写明。

## 二、成员变更（单步）

### 2.1 配置进日志、生效于提交

- 配置变更就是一条普通日志条目：`cmd = ("config", 成员 id 的升序元组)`，走同一条复制与提交路径。
- **节点成员 = 最新的配置来源**：先看日志里最后一条 config 条目（即使未提交也用于决策——
  论文口径"使用日志中最新的配置"）；日志里没有就看快照里的 members；再没有就 `base_members`（初始集）。
  `effective_members(node)` / `committed_members(node)`（只看到 commit 位）两个查询函数定死这套口径。
- 应用（提交后）到这条 config 时：`node.members` 更新、sim 记入 `config_history(index, term, 配置)`（去重）。
- **自移除**：leader 应用了不含自己的配置 → 立刻退位为 follower（它的作用已经结束了）。

### 2.2 一次一个 + 多数派口径

- `change_membership(add=X | remove=X)` 由当前 leader 发起；**如果 leader 日志里已有一条
  index > commit_index 的 config 条目则拒绝**（一次一个，论文的单步变更安全前提）。
- 选举/投票/提交的多数派一律按 `effective_members` 计算：
  `majority = len(members)//2 + 1`；票只数成员的；提交取"成员中第 majority 大的 last/match index"。
- **发送集 = committed_members ∪ effective_members**（并集）：这是可达性工程，不是安全口径——
  安全永远只用 effective/committed 的多数派。并集让两种情况变好：新增节点在配置提交前就开始追赶；
  被移除节点在配置提交前仍收到条目（于是它能"学会自己已被移除"而安静下来）。
  纯论文口径（只发 latest）会让被移除节点永远学不到、持续搅动选举——这条偏差与理由都登记在案。

### 2.3 新节点与被移除节点

- `add_server()`：新节点**空日志、空成员集**（不知道任何配置）→ 不竞选（`id 不在 effective_members`
  即不发起选举），等 leader 的 AppendEntries/InstallSnapshot 教会它。leader 侧 next_index 从
  `last_log_index()+1` 开始退避，最终走到快照或全量日志——复用现有退避路径。
- 被移除节点：应用了不含自己的配置后，`id 不在 effective_members` → `sim_tick` 不再为它发起选举。
- **disruption 如实登记**：在它学会之前（或一直收不到消息时），被移除节点可能自认仍是成员并
  搅动选举（论文 §4.2.3 的问题；工业修复是 Pre-Vote/CheckQuorum，本模拟不做）。
  安全不变式不受影响（安全靠多数派交叠，不靠"被移除者安静"）；测试**不假设**变更期间一定有稳定 leader。

### 2.4 配置安全不变式（检查器）

`check_config_overlap()`：对 `config_history` 里任意两份**已提交**配置 C1、C2，断言
**不存在互不相交的多数派**（即任意两个多数派总有共同成员），且**相邻两份配置恰好
差一个成员**（一次一个）。实现上用组合枚举（集群规模 ≤ 7，代价可忽略）。
反向：构造"差两个成员"的两份配置，检查器必须红（负面对照）。

## 三、验收对应表（三个问题 → 怎么证明）

| 验收问题 | 实现落点 | 测试怎么钉 |
|---|---|---|
| ① 快照后重启：状态机与快照+日志重放逐条一致 | 1.1/1.3 的快照字段与 `verify_node_replay` | 压缩后再重启再重放；改坏一条日志 → 校验器必红 |
| ② 成员变更期间不变式每事件 0 失败 | 2.1–2.4 全部 | 扩展随机事件流（提交/分区/重启/成员/快照）逐事件查 4 条不变式；3→5→3 保服务场景 |
| ③ 快照边界上的 §5.4.2 | 1.2 "只压缩已提交" | 构造：旧 leader 隔离收 ghost、新 leader 提交 real 并**压缩跨过 ghost 索引**、愈合 → ghost 全员无、real 全员一致、旧 leader 走 InstallSnapshot 追平（计数器证明） |

## 四、明确不做的（本轮边界，不含糊）

- Joint Consensus（联合共识）：不做，只做单步变更 + 一次一个的简化方案（测试与文档都按它写）。
- Pre-Vote / CheckQuorum：不做（disruption 按其未修复的形态登记）。
- 多进程真集群、磁盘持久化、消息乱序/重复的完整处理：维持 B30 原范围。
- 快照的增量/分块传输：InstallSnapshot 一次性整发（教学规模状态机）。
- 日志后缀保留优化（论文允许在快照安装时保留匹配后缀）：简化成全弃 + 续传（已登记）。
