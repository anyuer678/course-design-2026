"""tools/walkthrough_pack.py —— 走查期望值生成器（B16 backlog ①，ROADMAP §5.3）。

为什么要有它：`docs/07-walkthrough.md` 的「期望」列是 B16 手写的。规则一改，
手写的期望就会**悄悄过期**——B18 把验收宽限期落成 168 小时，而第 13 步的期望
一直停在"任何时刻都能关"；第 8 步的"对 R006 退回公共池"还会把第 9-11 步的
接单链直接切断（SUBMITTED 下没有 accept）。这两处都是本工具第一次重放才暴露的。
所以：把「期望」变成**现算的**，过期就红，红在步号上。

口径（写在这里，代码只是翻译）：

* **规范序列**：docs/07 的 20 步按顺序在**真原型**上重放一遍（`prototype.server`
  进程内起在 0 端口，走真 HTTP 调用）。步骤 1-16 与 20 有现算值；步骤 17-19
  （断服务/键盘/窄屏）无法脚本化，表里明写"只能人工"并给源码位置供对照。
* **固定输入**：每步的输入固定成 `INPUTS` 常量（谁、什么身份、填什么），否则
  期望值不唯一。第 3 步故意失败的建单会**占掉编号 R007**（原型计数器在校验前
  自增），因此第 4/6 步建的单是 `R008`/`R009`——按表操作时不要中途重启；
  重启或跳过第 3 步，编号整体前移（注记写明）。
* **时间口径**：模型钟从 1000 秒起算（NFR-05：原型不读真实时钟），界面按本地
  时间把它显示成 1970 年——不是 bug。表中凡时间都写成**两个量之差**或模型钟
  原值，不依赖本地时区。
* **输出**：`docs/16-walkthrough-pack.md`，与 docs/07 **逐号对应**的填空对照表；
  「你的实际／一致？」两列留空，你自己填——结论请回填 docs/07 的『你的结果』列
  （那里有 `checks/check_qa.py` 保护，不会被代填；本表是生成物，重生成会覆盖）。
* **校验**（`--check`；run.bat 第 3 步与 `tests/test_walkthrough_pack.py` 都跑）：
  1. `docs/16` 与现算一致（生成物过期即红）；
  2. `docs/07` 每步的关键断言仍与现算一致（`CLAIMS` 逐条核对，说法过期即红）。
  故意**不做**的：解析期望列里的自由散文（只写窄断言，写宽了会误报——B30 的
  "过强断言"教训）；把常驻检查挂进 `tools/pipeline.py`（层数被门禁表锁死，
  加层要动 gate.json / docs/12 / 台账一串——挂 run.bat 第 3 步 + 单测收益一样）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checks import check_docs                                  # noqa: E402
from checks.check_qa import WALK_HEADER                        # noqa: E402
from prototype.server import PrototypeServer                   # noqa: E402  （先把 B11 的 netlab 挂进 sys.path）
from netlab.client import Connection                           # noqa: E402

OUT = ROOT / "docs" / "16-walkthrough-pack.md"
WALK = ROOT / "docs" / "07-walkthrough.md"


# ------------------------------------------------------------------ 步骤模型

@dataclass
class Step:
    no: int
    inputs: str                                    # 本表口径：照做，右列才成立
    expect: list = field(default_factory=list)     # 现算期望（每项一句）
    facts: dict = field(default_factory=dict)      # 机器值（CLAIMS 用）
    notes: list = field(default_factory=list)      # 逐步注记


INPUTS = {
    1: "身份保持默认 `STUDENT/stu-1`，直接看列表。",
    2: "角色切 `维修员`，人选 `w-1`。",
    3: ("角色切 `学生`、人选 `stu-2`；宿舍号填 `101`，分类与紧急程度留在占位项"
        "（'请选择…'），描述与联系方式留空，点『提交报修』。"),
    4: ("同 `stu-2`；宿舍号填 `a01-101`、分类选 `NETWORK`、紧急程度选 `NORMAL`，"
        "描述填「网口不通，插上没反应」，联系方式填 `13900002222`，点『存为草稿』。"),
    5: "在同身份下打开刚建的草稿（`R008`），点『提交报修』。",
    6: ("同 `stu-2`；宿舍号 `a01-101`、分类 `NETWORK`、紧急程度 `NORMAL`，"
        "描述填「又一张，同房同分类」，联系方式 `13900002222`，点『提交报修』。"),
    7: ("角色切 `管理员/adm-1`；打开第 6 步新建的单（`R009`），点『派单』——"
        "先不填工号点确认（看被拒），再填 `w-1` 点确认。"),
    8: ("同 `ADMIN`；打开 `R009`（第 7 步刚派给 w-1），点『退回公共池』——"
        "先不填理由点确认（看被拒），再填「派错了宿舍」点确认。"),
    9: "角色切 `维修员/w-2`；打开 `R006`，点『接单』。之后切到 `w-1` 找 `R006`。",
    10: ("同 `w-2`；打开 `R006` 点『标记完工』——先留空点确认（看被拒），"
         "再填「更换模块，测通」点确认。"),
    11: ("角色切 `学生/stu-2`；打开 `R006` 点『验收不通过』——先留空理由（看被拒），"
         "再填「还是不通」；切回 `w-2` 点『标记完工』填「再查一遍，换了水晶头」；"
         "切回 `stu-2` 点『验收通过』。"),
    12: "角色切 `学生/stu-1`；试打开 `R003`（别人的单）：先看列表，再直接开详情。",
    13: "角色切 `管理员/adm-1`；打开 `R001` 点『强制关闭』。",
    14: "同 `ADMIN`；打开 `R005`（已关闭）。",
    15: ("角色切 `学生/stu-2`；筛选：状态 `SUBMITTED` + 分类 `NETWORK`；"
         "再把状态改成 `CLOSED` 看一眼；再改成 `CANCELLED`；最后切 `stu-1` 用同一筛选对照。"),
    16: "角色切 `管理员/adm-1`；只勾『只看逾期』。",
    17: "关掉服务进程，再在页面点任意按钮（比如『筛选』或某行的『打开』）。",
    18: "只用 Tab / Enter / Esc：跳转链接 → 下拉 → 按钮 → 打开详情 → Esc 关闭。",
    19: "把窗口拖窄（< 46rem ≈ 736px），或按手机宽度看。",
    20: "看中文与时间显示；展开紧急程度下拉看文案。",
}


# ------------------------------------------------------------------ 重放（现算期望）

def _q(role: str, actor: str) -> str:
    return f"role={role}&actor={actor}"


def _ids(data: dict) -> list:
    return [o["id"] for o in data.get("orders", [])]


def replay() -> list:
    """按规范序列在真原型上走一遍，返回 20 个 Step（现算期望 + 机器值）。"""
    steps = [Step(no=n, inputs=INPUTS[n]) for n in range(1, 21)]
    server = PrototypeServer(port=0)
    port = server.start()
    try:
        with Connection(port=port) as conn:
            def get(path):
                r = conn.request("GET", path)
                return r.status, (json.loads(r.text()) if r.text() else {})

            def post(path, body):
                r = conn.request("POST", path, body=json.dumps(body).encode("utf-8"),
                                 headers=[("Content-Type", "application/json")])
                return r.status, (json.loads(r.text()) if r.text() else {})

            # ---- 1：stu-1 列表
            _, d = get(f"/api/orders?{_q('STUDENT', 'stu-1')}")
            s = steps[0]
            s.expect = [f"列表 **{d['count']} 张**：{'、'.join(_ids(d))}"
                        f"（`OWN` 可见性：只含 stu-1 自己的单）",
                        "无错误态、无空态、没有被标记逾期的行"]
            s.facts = {"count": d["count"], "ids": _ids(d)}
            s.notes = ["排序规则：逾期优先，其次按编号（界面里的行序）。"]

            # ---- 2：w-1 列表
            _, d = get(f"/api/orders?{_q('WORKER', 'w-1')}")
            s = steps[1]
            s.expect = [f"列表 **{d['count']} 张**，`R003`（逾期）排最前：{'、'.join(_ids(d))}",
                        "一张草稿都不出现（`R004` 对维修员不可见）"]
            s.facts = {"count": d["count"], "ids": _ids(d)}
            s.notes = ["`w-1` 可见 = 公共池 + 派给他的 + 他完工过的（`OWN_OR_POOL_OR_RESOLVED`，AQ-12）。"]

            # ---- 3：stu-2 故意失败建单
            _, d = post(f"/api/orders?{_q('STUDENT', 'stu-2')}",
                        {"room": "101", "category": "", "priority": "",
                         "description": "", "contact": "", "action": "submit"})
            codes = [f["code"] for f in d.get("fields", [])]
            s = steps[2]
            s.expect = [f"**400 `INVALID_FIELDS`，{len(codes)} 处一次报全**：{'、'.join(codes)}",
                        f"汇总行写「有 {len(codes)} 处需要修改」；焦点落在第一个出错字段（宿舍号）",
                        "列表不新增单据（校验失败不留半张单）"]
            s.facts = {"count": len(codes), "codes": codes}
            s.notes = ["docs/07 第 3 步原文用占位符 N——就是这里的 5，不写死就不会过期。"]

            # ---- 4：stu-2 建草稿
            _, d = post(f"/api/orders?{_q('STUDENT', 'stu-2')}",
                        {"room": "a01-101", "category": "NETWORK", "priority": "NORMAL",
                         "description": "网口不通，插上没反应", "contact": "13900002222",
                         "action": "draft"})
            first_id = d.get("id")
            s = steps[3]
            s.expect = [f"**201 建单**：编号 `{first_id}`、状态 `DRAFT`；"
                        f"宿舍号显示为 **`{d.get('room')}`**（小写已归一化）"]
            s.facts = {"id": first_id, "state": d.get("state"), "room": d.get("room")}
            s.notes = ["第 3 步的失败尝试已占掉 `R007`（原型计数器在建单校验前自增），"
                       "所以这张是 `R008`；跳步或重启，编号会整体前移。",
                       "提交前这张单的『时限』列显示'未提交'。"]

            # ---- 5：提交草稿
            _, d = post(f"/api/orders/{first_id}/act?{_q('STUDENT', 'stu-2')}",
                        {"action": "submit"})
            delta = d.get("sla_due_at") - d.get("submitted_at")
            s = steps[4]
            s.expect = [f"状态 `SUBMITTED`；**时限到期 - 提交时刻 = {int(delta)} 秒**"
                        f"（`NORMAL` = 24 小时，来自模型的 SLA 表）",
                        f"到期晚于现在（模型钟 {int(d['sla_due_at'])} > {int(d['submitted_at'])}）"]
            s.facts = {"delta": delta, "state": d.get("state")}
            s.notes = ["模型钟从 1000 秒起算，界面按本地时间把它显示成 1970 年——不是 bug"
                       "（NFR-05：原型不读真实时钟，两次打开看到的是同一份数据）。"]

            # ---- 6：stu-2 再提一张（同房同分类）
            _, d = post(f"/api/orders?{_q('STUDENT', 'stu-2')}",
                        {"room": "a01-101", "category": "NETWORK", "priority": "NORMAL",
                         "description": "又一张，同房同分类", "contact": "13900002222",
                         "action": "submit"})
            second_id = d.get("id")
            s = steps[5]
            s.expect = [f"**201 建单**：编号 `{second_id}`、状态 `SUBMITTED`",
                        "原型**不拦截也不提示**重复——请判断'静默放行'是否够用"]
            s.facts = {"id": second_id, "duplicate": "R002"}
            s.notes = ["模型里 `spec.find_duplicate` 已能判定重复单（同房同分类、未终态；此处指向 `R002`），"
                       "但原型没接线提示——这就是第 6 步要你下判断的对象。"]

            # ---- 7：ADMIN 派单 R009
            _, d = post(f"/api/orders/{second_id}/act?{_q('ADMIN', 'adm-1')}",
                        {"action": "assign"})
            refused = d.get("code")
            _, d = post(f"/api/orders/{second_id}/act?{_q('ADMIN', 'adm-1')}",
                        {"action": "assign", "assignee": "w-1"})
            _, admin_list = get(f"/api/orders?{_q('ADMIN', 'adm-1')}")
            s = steps[6]
            s.expect = [f"不填工号 → **400 `{refused}`**，状态不变；"
                        f"填 `w-1` → `ASSIGNED`（assignee=w-1）",
                        f"列表首行仍是 `{admin_list['orders'][0]['id']}`（逾期优先排序不受影响）"]
            s.facts = {"refused": refused, "state": d.get("state"), "id": second_id,
                       "first_row": admin_list["orders"][0]["id"]}
            s.notes = ["`R006` 从这里到第 11 步都保持种子里'已派给 w-2'的状态——第 9-11 步的接单链要用它。"]

            # ---- 8：ADMIN 退回公共池（target 是第 7 步刚派出去的 R009）
            _, d = post(f"/api/orders/{second_id}/act?{_q('ADMIN', 'adm-1')}",
                        {"action": "return_pool"})
            refused = d.get("code")
            _, d = post(f"/api/orders/{second_id}/act?{_q('ADMIN', 'adm-1')}",
                        {"action": "return_pool", "reason": "派错了宿舍"})
            s = steps[7]
            s.expect = [f"不填理由 → **400 `{refused}`**；"
                        f"填理由 → `{d.get('state')}`，assignee 清空（回公共池）"]
            s.facts = {"refused": refused, "state": d.get("state"), "id": second_id}
            s.notes = ["对象是第 7 步刚派出的那张（`R009`）——`R006` 要留给第 9-11 步的接单链。"
                       "若按旧文案对 `R006` 退回，第 9 步的'接单'会落在 `SUBMITTED` 上无处可点"
                       "（这个断链是本工具第一版重放抓出来的，docs/07 第 8 步已随之修正）。"]

            # ---- 9：w-2 接单 R006；w-1 视角
            _, d = post(f"/api/orders/R006/act?{_q('WORKER', 'w-2')}", {"action": "accept"})
            _, hard = post(f"/api/orders/R006/act?{_q('WORKER', 'w-1')}", {"action": "accept"})
            detail_status, detail = get(f"/api/orders/R006?{_q('WORKER', 'w-1')}")
            s = steps[8]
            s.expect = [f"`w-2` 接单 → `{d.get('state')}`",
                        f"`w-1` 视角：`R006` **根本看不见**（列表没有它；直接开详情 HTTP {detail_status}"
                        f"「{detail.get('error')}」）",
                        f"此时硬发 accept → **400 `{hard.get('code')}`**"
                        f"（接单成功前硬发则是 `ASSIGNEE`——两种时机都记在这里）"]
            s.facts = {"state": d.get("state"), "detail_status": detail_status,
                       "hard_code": hard.get("code")}
            s.notes = ["'按钮不出现'的准确含义是**整单不可见**——旧文案容易读成按钮只是藏起来了。"
                       "前端不给按钮只是便利，越权照样被服务端拒（NFR-02）。"]

            # ---- 10：w-2 完工 R006
            _, d = post(f"/api/orders/R006/act?{_q('WORKER', 'w-2')}", {"action": "resolve"})
            refused = d.get("code")
            _, d = post(f"/api/orders/R006/act?{_q('WORKER', 'w-2')}",
                        {"action": "resolve", "note": "更换模块，测通"})
            s = steps[9]
            s.expect = [f"留空说明 → **400 `{refused}`**，状态仍 `IN_PROGRESS`；"
                        f"填说明 → `{d.get('state')}`",
                        "（验收宽限期从进入 `RESOLVED` 这一刻起算，见第 13 步）"]
            s.facts = {"refused": refused, "state": d.get("state")}

            # ---- 11：stu-2 退回 → 再完工 → 验收通过
            _, d = post(f"/api/orders/R006/act?{_q('STUDENT', 'stu-2')}",
                        {"action": "reject_check"})
            refused = d.get("code")
            _, d = post(f"/api/orders/R006/act?{_q('STUDENT', 'stu-2')}",
                        {"action": "reject_check", "reason": "还是不通"})
            back_state, back_assignee = d.get("state"), d.get("assignee")
            post(f"/api/orders/R006/act?{_q('WORKER', 'w-2')}",
                 {"action": "resolve", "note": "再查一遍，换了水晶头"})
            _, d = post(f"/api/orders/R006/act?{_q('STUDENT', 'stu-2')}", {"action": "confirm"})
            history = d.get("history", [])
            s = steps[10]
            s.expect = [f"退回：留空理由 → **400 `{refused}`**；填理由 → 回 `{back_state}`，"
                        f"**assignee 仍是 `{back_assignee}`**（同一个维修员）",
                        f"再完工 → `RESOLVED`；验收通过 → `{d.get('state')}`",
                        f"处理过程共 **{len(history)} 条**，每条含动作、角色/人、理由"]
            s.facts = {"refused": refused, "final": d.get("state"),
                       "history_len": len(history), "assignee_kept": back_assignee}
            s.notes = ["最后三条：`reject_check`（stu-2）→ `resolve`（w-2）→ `confirm`（stu-2）；"
                       "'含角色与标识'在界面上就是每条后面的 `by 角色/人`。"]
            for i, h in enumerate(history):
                assert h["role"] and h["actor"], f"第 {i + 1} 条处理记录缺角色或人"

            # ---- 12：stu-1 打开 R003
            status, d = get(f"/api/orders/R003?{_q('STUDENT', 'stu-1')}")
            _, mine = get(f"/api/orders?{_q('STUDENT', 'stu-1')}")
            s = steps[11]
            s.expect = [f"列表里没有 `R003`（当前可见：{'、'.join(_ids(mine))}）",
                        f"直接开详情 → **HTTP {status}「{d.get('error')}」**（不是 500、不是空白页）"]
            s.facts = {"status": status, "error": d.get("error")}
            s.notes = ["404 文案从服务端来（`看不到这张单：R003`），不透露它存在。"]

            # ---- 13：ADMIN 强制关闭 R001
            _, d = post(f"/api/orders/R001/act?{_q('ADMIN', 'adm-1')}",
                        {"action": "force_close"})
            m = re.search(r"到期时刻 ([\d.]+)，现在 ([\d.]+)", d.get("error", ""))
            due, now = (m.group(1), m.group(2)) if m else ("?", "?")
            s = steps[12]
            s.expect = [f"**400 `{d.get('code')}`**：宽限期未满（到期 {due} > 现在 {now}，模型钟）",
                        "口径：AQ-03 已裁决为 **168 小时 + 仅管理员**（`spec.ACCEPTANCE_GRACE_HOURS`）；"
                        "原型无法推进时钟，界面上看不到'成功关闭'",
                        "请判断 168 小时这个时长是否可接受——这正是要留的走查结论"]
            s.facts = {"code": d.get("code")}
            s.notes = ["成功路径（关闭后 assignee 清空、留一条 ADMIN 记录）由 "
                       "`test_acceptance_grace_is_configurable_and_blocks_force_close` 覆盖。",
                       "旧文案'现在任何时刻都能关'是 AQ-03 裁决前的口径，已随本工具首跑修正。"]

            # ---- 14：R005 终态
            _, d = get(f"/api/orders/R005?{_q('ADMIN', 'adm-1')}")
            s = steps[13]
            s.expect = [f"状态 `{d.get('state')}`；`attemptable` 为空——**任何身份都没有按钮**",
                        "界面明写「这张单已经是终态，任何人都不能再对它操作（BR-02）」"]
            s.facts = {"state": d.get("state"), "attemptable": d.get("attemptable")}

            # ---- 15：筛选
            _, d = get(f"/api/orders?{_q('STUDENT', 'stu-2')}&state=SUBMITTED&category=NETWORK")
            _, closed_d = get(f"/api/orders?{_q('STUDENT', 'stu-2')}&state=CLOSED&category=NETWORK")
            _, empty_d = get(f"/api/orders?{_q('STUDENT', 'stu-2')}&state=CANCELLED&category=NETWORK")
            _, other = get(f"/api/orders?{_q('STUDENT', 'stu-1')}&state=SUBMITTED&category=NETWORK")
            s = steps[14]
            s.expect = [f"筛选后 **{d['count']} 张**：{'、'.join(_ids(d))}"
                        f"（= 可见性 ∩ 筛选条件，可见性先收口）",
                        f"状态改 `CLOSED` → **{closed_d['count']} 张**：{'、'.join(_ids(closed_d))}"
                        f"（刚验收通过的那张，顺带确认第 11 步的终态）",
                        f"状态改 `CANCELLED` → **{empty_d['count']} 张**，显示空状态（不是残留上一次表格）",
                        f"对照 `stu-1` 同筛选 → {other['count']} 张（他人的单先被可见性挡掉）"]
            s.facts = {"count": d["count"], "ids": _ids(d),
                       "closed_count": closed_d["count"], "closed_ids": _ids(closed_d),
                       "empty_count": empty_d["count"], "stu1_count": other["count"]}
            s.notes = ["若中途重启过（回到种子），`SUBMITTED+NETWORK` 对 `stu-2` 直接是 0 张——"
                       "空状态那半句仍成立；'2 张'是本表口径（不重启）。"]

            # ---- 16：只看逾期
            _, d = get(f"/api/orders?{_q('ADMIN', 'adm-1')}&overdue=1")
            _, r003 = get(f"/api/orders/R003?{_q('ADMIN', 'adm-1')}")
            s = steps[15]
            s.expect = [f"只列出 **{d['count']} 张**：{'、'.join(_ids(d))}"
                        f"（`R001` RESOLVED 与 `R005` CLOSED 不算逾期）",
                        "`R003` 行徽章是**逾期样式**（琥珀色）——徽章文字是状态名，"
                        f"'已逾期'三个字在详情页『是否逾期』一栏"
                        f"（当前值：{'已逾期' if r003.get('overdue') else '未逾期'}）"]
            s.facts = {"count": d["count"], "ids": _ids(d), "overdue": r003.get("overdue")}

            # ---- 17-19：无法脚本化
            s = steps[16]
            s.expect = ["只能人工：出现错误态文案「加载失败：…这不是'没有工单'，是请求没成功。」，"
                        "不静默退化成空列表"]
            s.facts = {"manual": True}
            s.notes = ["文案出处：`prototype/web/app.js` 的 `loadOrders()`（本工具不驱动浏览器，只标注位置）。"]

            s = steps[17]
            s.expect = ["只能人工：Tab 依次可达（跳转链接、下拉、按钮、表单）；"
                        "打开详情后焦点落在标题；Esc 关闭详情"]
            s.facts = {"manual": True}
            s.notes = ["相关实现：`index.html` 的 skip 链接、`app.js` 的 `\"detail-h\".focus()` 与 keydown 的 Esc 处理；"
                       "存在性有自动测试，手感只能人工。"]

            s = steps[18]
            s.expect = ["只能人工：不横向溢出；『时限』列在窄屏隐藏"
                        "（`style.css` 里 46rem 及以下的媒体查询隐藏第 6 列的规则已存在，但'看着不挤'只有眼睛能判）"]
            s.facts = {"manual": True}

            # ---- 20：元数据文案
            _, meta = get("/api/meta")
            labels = {p: f"{p}（{h} 小时内响应）" for p, h in meta.get("priorities", {}).items()}
            s = steps[19]
            s.expect = ["紧急程度下拉文案来自模型："
                        + "、".join(f"`{labels[p]}`" for p in ("LOW", "NORMAL", "HIGH", "URGENT")),
                        "中文无乱码、时间为本地格式（这两项只能人工）"]
            s.facts = {"labels": labels}
            s.notes = ["标签由 `/api/meta` 现算——SLA 表改了，下拉文案与本行都会变。"]
    finally:
        server.stop()
    return steps


# ------------------------------------------------------------------ docs/07 关键断言

def rows_from(text: str) -> tuple:
    """解析走查清单表（复用 check_docs 的表格解析，不写第二份）。"""
    found, problems = check_docs.tables_in(text)
    if problems:
        return [], list(problems)
    try:
        rows = check_docs.one(found, WALK_HEADER, "走查清单表")
    except check_docs.Problem as exc:
        return [], [str(exc)]
    return rows, []


def _row_text(rows: list, step: int) -> str:
    for row in rows:
        if row[0].strip() == str(step):
            return " ".join(row[1:3])          # 做什么 + 期望
    return ""


def _num(fact_key: str, label: str):
    def check(match, facts, text):
        want = facts.get(fact_key)
        if int(match.group(1)) != want:
            more = f"（{'、'.join(facts['ids'])}）" if "ids" in facts else ""
            return [f"{label}写着 {match.group(1)}，现算 {want}{more}"]
        return []
    return check


def _eq(fact_key: str, label: str):
    def check(match, facts, text):
        want = facts.get(fact_key)
        if match.group(1) != want:
            return [f"{label}写着 {match.group(1)}，现算 {want}"]
        return []
    return check


def _only(ok_absent: str, why: str):
    def check(match, facts, text):
        if ok_absent in text:
            return [f"还残留「{ok_absent}」——{why}"]
        return []
    return check


#: 每条 = (步号, 必须命中的句式, 命中后的校验)。句式命不中就是"说法被改没了"，
#: 也要红——宁可你来看一眼，也不让某一步悄悄脱管。
CLAIMS = [
    (1, r"显示\s*(\d+)\s*张单", _num("count", "第 1 步列表张数")),
    (1, r"无报错", lambda m, f, t: []),
    (2, r"变成\s*(\d+)\s*张", _num("count", "第 2 步列表张数")),
    (2, r"草稿", lambda m, f, t: []),
    (3, r"有 N 处需要修改", lambda m, f, t: []),          # 占位符不写死数字，不会过期
    (3, r"焦点", lambda m, f, t: []),
    (4, r"A01-101", lambda m, f, t: []),
    (4, r"DRAFT", lambda m, f, t: []),
    (5, r"从提交那一刻起算", lambda m, f, t: []),
    (6, r"重复", lambda m, f, t: []),
    (6, r"find_duplicate", lambda m, f, t: []),
    (7, r"`(R\d{3})`", _eq("id", "第 7 步派单对象")),
    (7, r"不填工号", lambda m, f, t: []),
    (8, r"`(R\d{3})`", _eq("id", "第 8 步退回对象")),
    (8, r"退回公共池", _only("R006", "R006 要留给第 9-11 步的接单链，第 8 步不能再指回它")),
    (8, r"退回公共池", lambda m, f, t: []),
    (9, r"R006", lambda m, f, t: []),
    (9, r"404", lambda m, f, t: []),
    (9, r"NO_SUCH_TRANSITION", lambda m, f, t: []),
    (10, r"NOTE_REQUIRED", lambda m, f, t: []),
    (10, r"RESOLVED", lambda m, f, t: []),
    (11, r"IN_PROGRESS", lambda m, f, t: []),
    (11, r"CLOSED", lambda m, f, t: []),
    (11, r"同一个维修员", lambda m, f, t: []),
    (12, r"看不到这张单", lambda m, f, t: []),
    (13, r"`(ACCEPTANCE_NOT_MATURE)`", _eq("code", "第 13 步错误码")),
    (13, r"168", lambda m, f, t: []),
    (13, r"裁决", _only("任何时刻", "AQ-03 裁决前的旧口径「任何时刻都能关」不能再出现在第 13 步")),
    (14, r"终态", lambda m, f, t: []),
    (14, r"无任何按钮|都没有按钮", lambda m, f, t: []),
    (15, r"交集", lambda m, f, t: []),
    (15, r"空状态", lambda m, f, t: []),
    (15, r"CANCELLED", lambda m, f, t: []),
    (16, r"R003", lambda m, f, t: []),
    (16, r"逾期样式", lambda m, f, t: []),
    (16, r"已逾期", lambda m, f, t: []),
    (17, r"错误态", lambda m, f, t: []),
    (18, r"Tab", lambda m, f, t: []),
    (18, r"Esc", lambda m, f, t: []),
    (19, r"溢出", lambda m, f, t: []),
    (20, r"URGENT（(\d+) 小时内响应）", lambda m, f, t: [] if f["labels"]["URGENT"] == m.group(0)
     else [f"写着 {m.group(0)}，现算是 {f['labels']['URGENT']}"]),
]


def claims_problems(rows: list, steps: list) -> list:
    """docs/07 每步的关键断言 vs 现算值。窄断言，按步号报红。"""
    if len(rows) != 20:
        return [f"走查清单应有 20 步，解析到 {len(rows)} 行——docs/07 与 docs/16 靠步号对应，先修它"]
    facts = {s.no: s.facts for s in steps}
    out = []
    for step, pattern, verify in CLAIMS:
        text = _row_text(rows, step)
        match = re.search(pattern, text)
        if not match:
            out.append(f"第 {step} 步：docs/07 里找不到「{pattern}」——说法被改没了或行序变了，"
                       f"对照 tools/walkthrough_pack.py 的 CLAIMS 看一眼")
            continue
        out.extend(f"第 {step} 步：{p}" for p in verify(match, facts[step], text))
    return out


# ------------------------------------------------------------------ 渲染

def _cell(text: str) -> str:
    assert "|" not in text and "\n" not in text, f"单元格不能含 | 或换行：{text!r}"
    return text


def render(steps: list) -> str:
    lines = [
        "# 16 · 走查期望值对照表（B16 backlog ①）",
        "",
        "> **生成物，勿手改**：由 `python tools/walkthrough_pack.py --write` 从 `spec/` 与",
        "> `prototype/` 的种子数据**现算**。与 `docs/07-walkthrough.md` **逐号对应**（20 步）。",
        "> 本表过期、或 docs/07 的关键断言与本表分叉，`run.bat` 第 3 步与",
        "> `tests/test_walkthrough_pack.py` 都会红。",
        "",
        "## 怎么用",
        "",
        "1. 起原型：`python -m prototype.server --port 8010`（数据在内存，退出即清空）；",
        "2. 打开 `docs/07-walkthrough.md` 从第 1 步走到第 20 步：每步先按本表「本表口径」列操作，"
        "再看「现算期望」列；",
        "3. 结论填回 **docs/07 的『你的结果』列**（`checks/check_qa.py` 保护它不被代填）；"
        "本表右边两列供你草记，重新生成会覆盖。",
        "",
        "口径要点：",
        "",
        "- 全程**不要重启服务**、不要跳步；第 3 步故意失败的尝试会占掉编号 `R007`"
        "（原型计数器在建单校验前自增），所以第 4/6 步的新单是 `R008`/`R009`；",
        "- 模型钟从 1000 秒起算，界面会按本地时间显示成 1970 年——不是 bug"
        "（NFR-05）；凡时间都写成'两个量之差'或模型钟原值；",
        "- 第 17-19 步无法脚本化（断服务/键盘/窄屏），只给源码位置与观感问题，不下数值断言。",
        "",
        "## 对照表",
        "",
        "| # | 本表口径（照做） | 现算期望（spec + 种子） | 你的实际 | 一致？ |",
        "|---|---|---|---|---|",
    ]
    for s in steps:
        lines.append(f"| {s.no} | {_cell(s.inputs)} | {_cell('；'.join(s.expect))} | | |")
    lines += ["", "## 逐步注记", ""]
    for s in steps:
        for note in s.notes:
            lines.append(f"- **第 {s.no} 步**：{note}")
    lines += [
        "",
        "## 你的结论去哪儿",
        "",
        "按 `docs/07-walkthrough.md` 末尾『记下来的问题去哪儿』的三条路走（需求没定 → `docs/05`；"
        "界面没体现 → `docs/06` 与原型；模型/表格变了 → `docs/02` → `spec/` → 重生成）。",
        "**不要在代码里直接改**：任何一处改完，不一致都会以红灯的形式找到你。",
        "",
        "重生成：`python tools/walkthrough_pack.py --write`（改过 spec、种子、或原型后）。",
        "",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ 校验与入口

def freshness_problems(rendered: str | None = None, disk: str | None = None) -> list:
    """docs/16 与现算渲染是否一致。可注入文本（测试用）。"""
    if disk is None:
        if not OUT.is_file():
            return [f"{OUT.name} 不存在——跑 python tools/walkthrough_pack.py --write"]
        disk = OUT.read_text(encoding="utf-8")
    if rendered is None:
        rendered = render(replay())
    if rendered != disk:
        return [f"{OUT.name} 与现算不一致（生成物过期，或有人手改了它）："
                f"跑 python tools/walkthrough_pack.py --write"]
    return []


def check() -> list:
    steps = replay()
    problems = freshness_problems(render(steps))
    rows, bad = rows_from(WALK.read_text(encoding="utf-8"))
    problems.extend(bad)
    if not bad:
        problems.extend(claims_problems(rows, steps))
    return problems


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="走查期望值生成器（对照表见 docs/16）")
    ap.add_argument("--check", action="store_true", help="校验 docs/16 是否过期、docs/07 关键断言是否分叉")
    ap.add_argument("--write", action="store_true", help="重新生成 docs/16")
    args = ap.parse_args(argv[1:])
    if args.write:
        steps = replay()
        OUT.write_text(render(steps), encoding="utf-8")
        total = sum(len(s.expect) for s in steps)
        print(f"已写出 {OUT.name}：{len(steps)} 步、{total} 条现算期望；"
              f"对照表与 docs/07 逐号对应（改过 spec/种子/原型后请重跑）")
        return 0
    if args.check:
        problems = check()
        if problems:
            print(f"走查期望表核对发现 {len(problems)} 处问题：")
            for p in problems:
                print("  -", p)
            return 1
        steps = replay()
        manual = sum(1 for s in steps if s.facts.get("manual"))
        print(f"走查期望表现算通过：docs/16 与现算一致；docs/07 的 20 步关键断言全部对上"
              f"（其中 {len(CLAIMS)} 条窄断言、{manual} 步只能人工已标注）。")
        return 0
    print(render(replay()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
