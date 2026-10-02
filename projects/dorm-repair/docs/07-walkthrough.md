# 07 · 浏览器走查清单（B16）

> PLAN 第 6 节要求：**Web/UI 必须实际启动并交互验证正常路径、错误输入和回归；无法运行时标"未验证"**。
> 本机不允许我自动化驱动浏览器（试过被策略拦下，拦得对），所以下面每一行的**结果列都是空的**——
> 那是留给你填的，我不会替你打勾。
>
> **B21 加了第 4 列"自动证据"**：要么是真实存在的测试（`T:文件::方法`，
> `checks/check_qa.py` 会去源码里核实它在不在），要么明写 `只能人工`。
> 它的作用不是让你少走查，而是把注意力分到机器测不到的地方——
> 本轮统计：**20 步 = 纯自动 11 + 有自动证据但仍要看观感 7 + 只能人工 2**。
>
> 我已经自动验过的部分（`tests/test_prototype.py`，73 项测试里的一段）：
> 可见集合等于可见性矩阵、草稿对维修员不可见、逾期排最前、字段错误一次报全且不建单、
> 越权动作被服务端拒且不改动工单、终态无动作、缺必填入参被稳定 code 拒绝、
> 静态文件的目录包含、前端无 `innerHTML` 用法、`node --check` 通过、label/role/aria 关联完整。
> **这些不需要你在浏览器里重做**；你要判断的是它们"看起来对不对、用起来顺不顺"。
>
> **B16 backlog ① 追加**：配套的**现算期望值对照表**在 `docs/16-walkthrough-pack.md`——
> 20 步的期望全部由 `tools/walkthrough_pack.py` 从 spec 与种子数据现算（第 6/7/8/9/13/15/16
> 步的期望文案在生成器首跑时按现行规则校正过，原因见 docs/16 的逐步注记）。

## 启动

```
run.bat                 走到第 4 步会自动不起服务；要看界面就单独起：
python -m prototype.server --port 8010
```

浏览器打开 `http://127.0.0.1:8010/`。数据是内存的，重启回到种子状态（6 张单）。
身份是模拟的：学生 `stu-1` / `stu-2`、维修员 `w-1` / `w-2`、管理员 `adm-1`。

## 清单

每行填 `通过 / 有问题（写清哪一步） / 没测`。

| # | 做什么 | 期望（回链） | 自动证据 | 你的结果 |
|---|---|---|---|---|
| 1 | 首次打开页面 | 顶部明确写"不是登录"；列表默认以 `STUDENT/stu-1` 显示 3 张单，无报错 | T:tests/test_prototype.py::test_index_is_served_with_a11y_contracts、T:tests/test_prototype.py::test_list_matches_the_visibility_matrix、只能人工：顶部那句是否醒目 | 未验证 |
| 2 | 角色切到"维修员"，人选 `w-1` | 列表变成 3 张（`R003` 公共池 + `R001`/`R002`）；**一张草稿都不出现**；说明文案不误导（US-06、US-11、第 6 节） | T:tests/test_prototype.py::test_list_matches_the_visibility_matrix、T:tests/test_prototype.py::test_workers_never_see_drafts、只能人工：说明文案会不会误导 | 未验证 |
| 3 | 角色切"学生"，人选 `stu-2`，描述留空、宿舍号填 `101`、分类不选，点"提交报修" | **每个出错字段下方各出现一条中文说明**，汇总写"有 N 处需要修改"，焦点落在第一个出错字段；列表不新增单据（US-01、AC-03、AC-05） | T:tests/test_prototype.py::test_frontend_maps_field_errors_to_each_field、T:tests/test_prototype.py::test_create_lists_every_field_problem_and_creates_nothing、只能人工：焦点是否真落在第一个出错字段 | 未验证 |
| 4 | 宿舍号填 `a01-101`（小写）、其余填对，点"存为草稿" | 建单成功且列表里宿舍号显示为大写 `A01-101`；状态 `DRAFT`（US-01、US-02） | T:tests/test_workorder_spec.py::test_create_order_normalizes_fields | 未验证 |
| 5 | 打开这张草稿，点"提交报修" | 状态转 `SUBMITTED`，"时限到期"从提交那一刻起算（不是建单时刻）（US-01、US-13、AC-36、AC-37、BR-08） | T:tests/test_workorder_spec.py::test_sla_starts_at_first_submission、T:tests/test_prototype.py::test_full_chain_through_the_api | 未验证 |
| 6 | 同宿舍同分类再提一张 | 允许提交但原型不提示重复（模型里 `spec.find_duplicate` 已能判定重复单、原型未接线提示）——请判断"静默放行"是否够用（US-03） | T:tests/test_workorder_spec.py::test_duplicate_open_order_detected、只能人工：提示够不够用 | 未验证 |
| 7 | 角色切"管理员"，给第 6 步新建的单（`R009`）派单给 `w-1` | 不填工号时被拒并说明原因；填了之后状态 `ASSIGNED`，列表按逾期优先排序仍正常（US-04、AC-10） | T:tests/test_workorder_spec.py::test_assignee_required_blocks_assign、T:tests/test_prototype.py::test_missing_required_input_is_rejected_with_a_stable_code | 未验证 |
| 8 | 角色切"管理员"，对第 7 步刚派给 `w-1` 的单（`R009`）点"退回公共池"但不填理由 | 被拒（`REASON_REQUIRED`）且工单没变化；补上理由后再操作成功（`SUBMITTED`，回公共池）（US-05、AC-13） | T:tests/test_workorder_spec.py::test_cancel_and_return_pool_need_reason | 未验证 |
| 9 | 角色切"维修员" `w-2`，对 `R006` 点"接单" | 状态 `IN_PROGRESS`；换 `w-1` 时**这张单根本看不见**（列表里没有、直接开详情 404）——硬发请求也被拒（按 `docs/16` 的规范顺序是 `NO_SUCH_TRANSITION`）（US-06、AC-15、AC-16） | T:tests/test_prototype.py::test_server_refuses_actions_the_role_cannot_take、T:tests/test_workorder_spec.py::test_worker_cannot_see_others_assigned_orders | 未验证 |
| 10 | `w-2` 对 `R006` 点"标记完工"，完工说明留空 | 被拒（`NOTE_REQUIRED`），状态仍是 `IN_PROGRESS`；填了之后进入 `RESOLVED`（US-07、AC-18、AC-19） | T:tests/test_prototype.py::test_missing_required_input_is_rejected_with_a_stable_code、T:tests/test_workorder_spec.py::test_transition_table_matches_srs | 未验证 |
| 11 | 用报修人 `stu-2` 验收 `R006`：先"验收不通过"再"验收通过" | 退回后仍是同一个维修员负责、状态回 `IN_PROGRESS`；再完工后验收通过转 `CLOSED`；两步都要在"处理过程"里各留一条，含角色与标识（US-08、US-12、AC-20、AC-21、AC-33） | T:tests/test_workorder_spec.py::test_reject_check_keeps_assignee、T:tests/test_workorder_spec.py::test_history_entries_carry_the_five_fields | 未验证 |
| 12 | 用**另一个学生** `stu-1` 打开 `R003`（别人的单） | 列表里看不到、详情返回"看不到这张单"，不是 500 也不是空白页（US-11、第 6 节、AC-29） | T:tests/test_prototype.py::test_students_cannot_open_others_orders、T:tests/test_prototype.py::test_unknown_order_is_404_not_500 | 未验证 |
| 13 | 管理员对 `R001` 点"强制关闭" | 被拒：`ACCEPTANCE_NOT_MATURE`——**AQ-03 已裁决**为 168 小时宽限期（`spec.ACCEPTANCE_GRACE_HOURS`），R001 远未到期；"关闭后 `assignee` 清空、留一条 `ADMIN` 记录"的成功路径由 `test_acceptance_grace_is_configurable_and_blocks_force_close` 覆盖（原型无法推进时钟）。请判断这个宽限期时长是否可接受（US-09、AC-23） | T:tests/test_workorder_spec.py::test_acceptance_grace_is_configurable_and_blocks_force_close、只能人工：这样是否可接受 | 未验证 |
| 14 | 打开已关闭的 `R005` | 明确显示"终态，任何人都不能再操作"，无任何按钮（US-10、AC-28、BR-02） | T:tests/test_workorder_spec.py::test_no_action_is_allowed_from_a_terminal_state | 未验证 |
| 15 | 用筛选：状态选 `SUBMITTED` + 分类选 `NETWORK`，身份 `STUDENT/stu-2` | 结果恰好是交集（确切张数与单号见 `docs/16` 第 15 步的现算值）；再试一个必空的组合（如状态改成 `CANCELLED`）看**空状态**而不是残留上一次表格或报错（US-11、AC-31、AC-32） | T:tests/test_prototype.py::test_filters_narrow_without_escaping_visibility、T:tests/test_prototype.py::test_blank_state_marker_survives_a_re_render | 未验证 |
| 16 | 只勾"只看逾期"（管理员） | 只有 `R003` 出现，且它的状态徽章是**逾期样式**（琥珀色；徽章文字是状态名，"已逾期"三个字在详情页"是否逾期"一栏）；`RESOLVED` 与终态不出现在逾期里（AC-32、第 8 节、AQ-02） | T:tests/test_prototype.py::test_overdue_orders_sort_first、T:tests/test_workorder_spec.py::test_overdue_excludes_resolved_and_terminal | 未验证 |
| 17 | 关掉服务进程再用页面点任意按钮 | 出现**错误态**文案且明确"这不是没有工单"，不是静默变成空列表（AC-39 相关、V3 约定） | T:tests/test_prototype.py::test_error_and_empty_states_exist_in_markup、只能人工：断服务后的真实表现 | 未验证 |
| 18 | 键盘走查：只用 Tab / Enter / Esc | 顶部跳转链接可用；下拉、按钮、表单均可 Tab 到；打开详情焦点到标题；Esc 关闭详情（V1/V5） | 只能人工：本机策略不允许自动化驱动浏览器 | 未验证 |
| 19 | 手机宽度（或窗口拖窄） | 表格隐藏"时限到期"列但不横向溢出；详情面板仍完整可读（V5） | 只能人工：窄屏是否溢出只有眼睛能判 | 未验证 |
| 20 | 中文与时间显示 | 无乱码；时间是本地格式；紧急程度选项里显示"URGENT（2 小时内响应）"这类来自模型的文案（NFR-04、第 8 节） | T:tests/test_prototype.py::test_meta_comes_from_the_model_not_a_copy、只能人工：乱码与时间格式要眼看 | 未验证 |

## 走查时请特别判断这三处（我的默认值可能不对）

1. **AQ-02（SLA 时长与口径）**：界面把时限直接印在选项和徽章上。如果真实时限口径不是
   "从提交起算、按优先级定额"，这些提示就要跟着改——**改了要动 `docs/02-srs.md` 第 8 节的表**，
   然后 `python checks/check_docs.py --write`，模型和界面会自己跟上。
2. **AQ-03（验收悬挂多久算超时、谁有权强制关闭）**：已裁决为 168 小时宽限期 + 仅管理员
   （第 13 步会看到"未满宽限期"的拒绝）；界面上没有"已悬挂 X 小时"的提示，也没有二次
   确认。要不要加，请你走查第 13 步时决定。
3. **动作确认的强度**：现在所有动作都走"展开表单 → 确认执行"，但像"强制关闭""取消已派单"
   这类不可逆操作，是否还需要再确认一次，属产品判断（我不替你们定）。

## 记下来的问题去哪儿

走查发现的问题按这个顺序落文档，**不要直接改代码**：

1. 是需求没定 → 写进 `05-open-questions.md`，新增或更新 AQ 条目；
2. 是需求定了但界面没体现 → 改 `06-wireframes.md` 与原型；
3. 是模型/表格变了 → 改 `02-srs.md` 的规范表 → 改 `spec/workorder.py` →
   跑 `python checks/check_docs.py --write` → 跑 `python -m unittest discover -s tests`。

第 3 条那一路径是故意设的：**任何一处改完，不一致都会以红灯的形式找到你**，
而不是等到 B18 实现时才发现界面、文档、代码讲的是三个故事。
