import pathlib

p = pathlib.Path("README.md")
lines = p.read_text(encoding="utf-8").split("\n")

# 1) 产物表：在 docs/09 行前插入 docs/10 行
row = ("| `docs/10-soa.md` | B19：为什么选 SOAP 不选 gRPC（**本机依赖实测**）、双接口覆盖范围、"
       "**状态字面量白名单**、WSDL 由契约生成、本轮真缺陷 4 条、明确不做 | "
       "`check_arch.py::check_java_state_literals`（双向）+ Java 对拍 |")
i = next(n for n, l in enumerate(lines) if l.startswith("| `docs/09-platform.md` |"))
lines.insert(i, row)

# 2) 已知局限前插入 B19 的坑
block = """### B19 追加的坑（双接口与加固）

30. **照抄来的 XML 加固配置在这台机器上根本无效**：`disallow-doctype-declaration` 是 Xerces 专有的特性名，
    JDK 自带解析器不认。我的"失败关闭"逻辑于是让每次解析都报 INTERNAL，
    结果是 **XXE 防护一次都没真正生效过**，只是把所有请求都拒了、看起来很像很安全。
    修法与教训：**安全/加固配置必须配一条正向测试**（给一个合法请求，断言它真的通过）——
    否则"拒绝一切"和"防护到位"这两种状态在测试里长得一模一样。
31. Java 里我把内嵌 record 命名成 `Element`，**遮住了 `org.w3c.dom.Element`**；
    按钮元素又写成 `<Action>`，与留痕里的 `<Action>` 撞名。报文格式里的歧义一旦发布就永久留着，
    改成 `Item` / `Attemptable` 都是编译期或读回时才暴露，不是设计期想出来的。
32. 我朝 SOAP 发了个 `<Assign>` 想做错误码对拍，拿到 `CLIENT` 其实是**正确行为**
    （第二种接口只覆盖查询），我却把它写成"码值分叉"。范围没想清楚时，测试会比实现先错。
33. 测试与实现**各写了一遍解析**（我的测试版忘了剥反引号）→ 测试红、实现绿。
    抽出 `state_literal_allow_list()` 让两边共用同一个函数才修好：**重复的解析迟早漂移**。
34. 又踩一次管道退出码：`python checks/check_arch.py | tail -3; echo exit=$?` 读的是 `tail` 的码，
    明明报了 5 处问题却显示 `exit=0`。B7/B10 记过这条，这次是我在新地方重犯。

""".split("\n")
j = next(n for n, l in enumerate(lines) if l.startswith("## 已知局限"))
lines[j:j] = block

# 3) 下一轮接手什么：B19 段改成已完成
start = next(n for n, l in enumerate(lines) if l.startswith("* **B19（SOA"))
stop = next(n for n, l in enumerate(lines) if l.startswith("* **B20（"))
lines[start:stop] = [
    "* **B19（已完成，2026-10-01）**：查询用例 UC-05 多了一种接口形态——手写 SOAP 1.2 端点 + 由契约生成的 WSDL，",
    "  **零下载**（本机没有 Spring WS / gRPC 缓存，这是实测出来的选型理由，见 `docs/10` 第 1 节）。",
    "  判定没有第二份：同一身份的可见集合、按钮、错误码两边逐字相同（`SoapInterfaceTest` 8 项）；",
    "  谁能自己判断状态由 `docs/10` 的**状态字面量白名单**双向核对（3 个文件，扫描前先剥注释）。",
    "  写操作**故意没有**放进 SOAP，理由写在 `docs/10` 第 2 节。",
]
p.write_text("\n".join(lines), encoding="utf-8")
print("README synced")
