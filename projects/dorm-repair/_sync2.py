import pathlib

# --- 项目 README：知识点映射补 B19 三行，产物行的缺陷数改准
p = pathlib.Path("README.md")
s = p.read_text(encoding="utf-8")
s = s.replace("**WSDL 由契约生成、本轮真缺陷 4 条、明确不做**",
              "**WSDL 由契约生成、本轮真缺陷 5 条、明确不做**")
anchor = "| 跨工具链的编码与\"假绿灯\" |"
i = s.index(anchor)
j = s.index("\n", s.index("\n", i) + 1)          # 该表格行到下一行结束
rows = """| 服务契约与两种接口形态（REST vs SOAP 1.2） | `docs/10` + `java/…/soap/*` | 同一身份两侧**可见集合、按钮、错误码逐字相同**（`SoapInterfaceTest` 8 项）；注入一条 SOAP 自造规则立刻精确分叉 |
| 描述文件与契约同源（WSDL 不许手写） | `java/…/soap/Wsdl.java` | 测试比对 `StateType` 枚举与契约 `states` 集合；多一个少一个都红 |
| 消息格式的可解释性 | `Attemptable` / `Input` / `Change>Action` 元素名 | 撞名会让客户端按层级猜语义（本轮踩过）；测试按元素名读回，不用 indexOf |
| XML 的安全解析（XXE） | `SoapEnvelope.parseXml` | 两条反向测试：带 DOCTYPE 与带实体引用的信封都必须被拒；另配**正向**测试证明合法信封真能通过 |
""".rstrip("\n")
s = s[:j] + "\n" + rows + s[j:]
p.write_text(s, encoding="utf-8")

# --- docs/10：缺陷数与清单补齐第 5 条
d = pathlib.Path("docs/10-soa.md")
t = d.read_text(encoding="utf-8")
t = t.replace("## 6. 本轮真缺陷（4 处，全是我自己的）", "## 6. 本轮真缺陷（5 处，全是我自己的）")
t = t.replace("而红的原因是我的期望，不是实现。", """而红的原因是我的期望，不是实现。

⑤ **管道吃掉退出码**：`python checks/check_arch.py | tail -3; echo "exit=$?"` 报的是 `tail` 的码，
核对器明明列出 5 处问题却显示 `exit=0`。同一条坑在 B7/B10 记过，这次是我在新地方重犯——
**读退出码必须直连被检进程**（或显式取 `PIPESTATUS`）。""")
t = t.replace("**本轮真缺陷 4 条**", "**本轮真缺陷 5 条**")
d.write_text(t, encoding="utf-8")
print("synced")
