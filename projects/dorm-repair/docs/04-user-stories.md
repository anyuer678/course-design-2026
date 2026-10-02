# 04 · 用户故事与验收标准

> B15 产物。故事按"谁要什么、为什么"分粒度，验收标准写成 Given/When/Then（表格里压缩成一句：
> **给定** 条件 **当** 动作 **则** 结果）。
>
> `验证` 列只允许三种写法，检查器会核实：
> * `T:tests/….py::方法` —— 本轮已有可执行测试，**方法必须真的存在**（检查器会去源码里找）；
> * `待验证（Bxx）` —— 本轮没有可运行系统，写清由哪一轮接手；
> * `人工确认（Bxx）` —— 只能靠人看（界面观感、编码显示），不假装自动化过。

### US-01 · 学生把坏了的东西报上去

- 需求：FR-01, FR-02, FR-03
- 用例：UC-01
- 价值：现在的口头报修会漏、会记错宿舍号；填一次就要拿到一个可追踪的单子

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-01 | 给定五个字段都合规，当学生建单，则得到一张 `DRAFT` 工单且宿舍编号已规范化为大写 | `T:tests/test_workorder_spec.py::test_create_order_normalizes_fields` |
| AC-02 | 给定最小样例数据，当建单，则不产生任何字段错误 | `T:tests/test_workorder_spec.py::test_valid_order_accepts_minimal_fixture` |
| AC-03 | 给定描述为空白且宿舍编号写成 `101`，当提交，则一次列出全部问题而不是只报第一个 | `T:tests/test_workorder_spec.py::test_validation_reports_all_problems_at_once` |
| AC-04 | 给定字段不合规，当提交失败，则工单仍是 `DRAFT` 且历史没有新增 | `T:tests/test_workorder_spec.py::test_validation_failure_leaves_state_unchanged` |
| AC-05 | 给定表单要在浏览器里可用，当 B16 做界面，则错误提示按字段就地显示 | `T:tests/test_prototype.py::test_frontend_maps_field_errors_to_each_field` |

### US-02 · 学生先存草稿，想清楚再提交

- 需求：FR-02
- 用例：UC-01
- 价值：描述和联系方式常常要回宿舍查，强制一次填完会逼人乱填

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-06 | 给定一张草稿，当学生反复修改而不提交，则状态一直是 `DRAFT` 且没有 `submitted_at` | `T:tests/test_workorder_spec.py::test_sla_starts_at_first_submission` |

### US-03 · 别再让同一间宿舍同一处坏被重复报

- 需求：FR-04
- 用例：UC-01
- 价值：重复单会让维修员白跑，也让管理员误判数量

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-07 | 给定同宿舍同分类已有一张未完成的单，当再次提交，则检出该单并提示 | `T:tests/test_workorder_spec.py::test_duplicate_open_order_detected` |
| AC-08 | 给定同宿舍但不同分类，当提交，则不误报重复 | `T:tests/test_workorder_spec.py::test_duplicate_open_order_detected` |

### US-04 · 管理员把待派单分给具体的人

- 需求：FR-05
- 用例：UC-02
- 价值：现在没人负责的单子等于没人修

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-09 | 给定 `SUBMITTED` 且带来维修员工号，当管理员派单，则进入 `ASSIGNED` 且 assignee 为该工号 | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| AC-10 | 给定派单请求没有工号，当派单，则拒绝并说明需要指定维修员 | `T:tests/test_workorder_spec.py::test_assignee_required_blocks_assign` |
| AC-11 | 给定发起者是学生或维修员，当派单，则拒绝（权限矩阵只给 ADMIN） | `T:tests/test_workorder_spec.py::test_permission_matrix_matches_srs` |

### US-05 · 管理员派错了能纠，不用重开一张单

- 需求：FR-06
- 用例：UC-02
- 价值：重开会打断 SLA 起算与统计口径

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-12 | 给定 `ASSIGNED`，当管理员改派，则状态不变、assignee 变、历史追加一条 | `T:tests/test_workorder_spec.py::test_reassign_keeps_state_and_appends_history` |
| AC-13 | 给定 `ASSIGNED`，当管理员退回公共池但不写理由，则拒绝 | `T:tests/test_workorder_spec.py::test_cancel_and_return_pool_need_reason` |
| AC-14 | 给定退回成功，当查看工单，则 assignee 已清空且 `submitted_at` 未被重置 | `T:tests/test_workorder_spec.py::test_assignee_cleared_when_leaving_assigned` |

### US-06 · 维修员接单，也能拒掉不该自己干的单

- 需求：FR-07
- 用例：UC-03
- 价值：口头交接无法证明谁接了；拒单要有出路，否则只能拖着

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-15 | 给定 `ASSIGNED` 且 assignee 是本人，当接单，则进入 `IN_PROGRESS` | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| AC-16 | 给定 `ASSIGNED` 但 assignee 是别人，当接单，则拒绝（BR-04） | `T:tests/test_workorder_spec.py::test_owner_and_assignee_are_checked_in_model_not_caller` |
| AC-17 | 给定 `ASSIGNED`，当本人拒单，则回到 `SUBMITTED` 且 assignee 清空 | `T:tests/test_workorder_spec.py::test_assignee_cleared_when_leaving_assigned` |

### US-07 · 维修员记完工，写清修了什么

- 需求：FR-08
- 用例：UC-03
- 价值：没有完工说明，学生无从判断是否真的修好

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-18 | 给定 `IN_PROGRESS` 且完工说明非空，当标记完工，则进入 `RESOLVED` | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| AC-19 | 给定 `IN_PROGRESS`，当完工说明是空白，则拒绝且状态不变 | `T:tests/test_workorder_spec.py::test_illegal_transition_leaves_order_unchanged` |

### US-08 · 学生验收，不满意就退回原来那个人

- 需求：FR-09
- 用例：UC-04
- 价值：修没修好只有报修人最清楚；退回必须回到同一维修员，否则球又掉在地上

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-20 | 给定 `RESOLVED` 且本人是报修人，当验收通过，则进入 `CLOSED` | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| AC-21 | 给定 `RESOLVED`，当报修人退回并写理由，则回到 `IN_PROGRESS` 且 assignee 不变 | `T:tests/test_workorder_spec.py::test_reject_check_keeps_assignee` |
| AC-22 | 给定 `RESOLVED`，当别的学生来验收，则拒绝（BR-09） | `T:tests/test_workorder_spec.py::test_owner_and_assignee_are_checked_in_model_not_caller` |

### US-09 · 管理员能关掉一直没人验收的单

- 需求：FR-10, BR-10
- 用例：UC-04
- 价值：学生毕业后单悬挂着，队列会越积越长

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-23 | 给定 `RESOLVED` 且已满验收宽限期，当管理员强制关闭，则进入 `CLOSED`，不需要理由也不需要本人 | `T:tests/test_workorder_spec.py::test_permission_matrix_matches_srs` |
| AC-24 | 给定 `RESOLVED` 停留未满 168 小时，当管理员强制关闭，则拒绝；宽限时长改成 1 小时后同一时刻允许——阈值是参数，不是散在实现里的魔法数 | `T:tests/test_workorder_spec.py::test_acceptance_grace_is_configurable_and_blocks_force_close` |

### US-10 · 不想修了能取消

- 需求：FR-11
- 用例：UC-06
- 价值：误报和"自己捅的漏已经修好了"很常见，没有取消入口就会留下垃圾单

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-25 | 给定 `DRAFT` 或 `SUBMITTED`，当报修本人取消，则进入 `CANCELLED` | `T:tests/test_workorder_spec.py::test_transition_table_matches_srs` |
| AC-26 | 给定 `ASSIGNED`，当管理员取消而不写理由，则拒绝 | `T:tests/test_workorder_spec.py::test_cancel_and_return_pool_need_reason` |
| AC-27 | 给定 `ASSIGNED`，当学生想自己取消，则拒绝（AQ-09 的收紧） | `T:tests/test_workorder_spec.py::test_permission_matrix_matches_srs` |
| AC-28 | 给定 `CLOSED` 或 `CANCELLED`，当任何人做任何动作，则一律拒绝 | `T:tests/test_workorder_spec.py::test_terminal_states_have_no_exits` |

### US-11 · 三个人看到三种列表

- 需求：FR-12, FR-13, FR-14, BR-11
- 用例：UC-05
- 价值：学生只关心自己的，维修员只关心能领的和自己手里的，管理员要能筛总量

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-29 | 给定样例数据 12 单，当学生查询，则恰好看到自己提的单（含自己的草稿） | `T:tests/test_workorder_spec.py::test_visibility_matrix_matches_srs` |
| AC-30 | 给定样例数据，当维修员查询，则看到公共池与派给自己的单，且一张草稿都看不到 | `T:tests/test_workorder_spec.py::test_visibility_matrix_matches_srs` |
| AC-31 | 给定样例数据，当管理员按分类或宿舍号筛选，则结果恰好等于逐条独立判断的集合 | `T:tests/test_workorder_spec.py::test_filters_narrow_the_fixture_set` |
| AC-32 | 给定管理员只看逾期，当以某时刻判定，则排除 `RESOLVED` 与两个终态 | `T:tests/test_workorder_spec.py::test_overdue_excludes_resolved_and_terminal` |
| AC-40 | 给定一张由某维修员完工并已关闭的历史单，当他查询，则这张单**可见但不可操作**（`resolved_by` 命中，`attemptable()` 仍为空） | `T:tests/test_workorder_spec.py::test_resolved_history_is_visible_but_inert` |

### US-12 · 每一步都留痕，事后能追责

- 需求：FR-15
- 用例：UC-01, UC-04
- 价值：没有留痕，"谁什么时候把单派错了"就永远吵不清楚

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-33 | 给定任意成功转换，当查看历史，则条数加一且旧条目未被改动 | `T:tests/test_workorder_spec.py::test_history_is_append_only` |
| AC-34 | 给定任意被拒绝的转换，当查看工单，则状态与历史都没变 | `T:tests/test_workorder_spec.py::test_illegal_transition_leaves_order_unchanged` |
| AC-35 | 给定历史条目，当检查内容，则含时刻、起止状态、动作、发起角色与标识 | `T:tests/test_workorder_spec.py::test_exhaustive_walk_keeps_invariants` |

### US-13 · 时限与留痕必须能被机器核对（横切故事）

- 需求：FR-15, FR-02
- 用例：UC-05
- 价值：SLA 和留痕一旦只能靠人肉看，就会在实现时被"顺手简化"，而没人发现
- 说明：这不是新流程，而是 US-01、US-05、US-12 共同的**核对要求**，所以单独占一个故事编号，
  免得它的验收标准被塞进别的故事里冒充别的故事的完成定义

| AC ID | 验收标准（Given/When/Then） | 验证 |
|---|---|---|
| AC-36 | 给定优先级 `NORMAL` 且首次提交于 t=1000.0，当计算 SLA，则到期时刻为 87400.0（1000 + 24×3600，手算） | `T:tests/test_workorder_spec.py::test_sla_hours_match_srs_table` |
| AC-37 | 给定一张单被改派或退回过，当查看 `submitted_at`，则仍是首次进入待派单的时刻（BR-08） | `T:tests/test_workorder_spec.py::test_sla_starts_at_first_submission` |
| AC-38 | 给定模型源码，当检查时间来源，则其中不存在任何自行读取时钟的调用（NFR-05） | `T:tests/test_workorder_spec.py::test_time_is_injected_not_read` |
| AC-39 | 给定界面需要走查，当 B16 做交互设计，则列表、筛选与错误态按本文件的故事复核 | `T:tests/test_prototype.py::test_walkthrough_checklist_covers_every_story`（清单覆盖 13 个故事已由机器核对；每一行的**结果**仍为"未验证"，由你实跑填写） |
