package course.dormrepair.contract;

import course.dormrepair.domain.StateMachine;
import course.dormrepair.domain.WorkOrder;
import org.junit.jupiter.api.Test;

import java.io.InputStream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 契约能不能读出来、状态机能不能走一条完整链路。
 *
 * 期望值出处：contracts/workflow.json（15 条转换、宽限 168 小时）与
 * docs/02-srs.md 第 8 节的手算样例（resolved_at=4000 + 168×3600 = 608800）。
 */
class ContractSmokeTest {

    static WorkflowContract contract() {
        try (InputStream in = WorkflowContract.class.getClassLoader()
                .getResourceAsStream(WorkflowContract.RESOURCE)) {
            assertNotNull(in, "契约没被打进 classpath：检查 java/pom.xml 的 <resource> 是否指向 ../contracts");
            return WorkflowContract.parse(in, WorkflowContract.RESOURCE);
        } catch (java.io.IOException e) {
            throw new java.io.UncheckedIOException(e);
        }
    }

    @Test
    void contractLoadsTheSingleSourceTables() {
        WorkflowContract c = contract();
        assertEquals(2, c.schemaVersion());
        assertEquals(15, c.transitions().size());
        assertEquals(168, c.acceptanceGraceHours());
        assertEquals(12, c.actions().size(), "SRS 第 1 节的动作枚举是 12 个");
        assertEquals("OWN_OR_POOL_OR_RESOLVED", c.visibility().get("WORKER"));
        assertEquals(6, c.fieldLimits().size());
        // 契约的键必须是标识符，不是半截中文（B18 现场修过一次）
        assertTrue(c.fieldErrors().containsKey("room"), c.fieldErrors().keySet().toString());
        assertFalse(c.fieldErrors().keySet().stream().anyMatch(k -> k.contains("`") || k.contains(" ")),
                "field_errors 的键混进了 markdown 残留：" + c.fieldErrors().keySet());
    }

    @Test
    void canonicalHappyPathReachesClosedAndKeepsTheHandler() {
        StateMachine sm = new StateMachine(contract());
        WorkOrder draft = sm.create("R1", "stu-1", "a01-101", "WATER_ELEC", "NORMAL",
                "水管漏水", "13800000000", 100.0);
        assertEquals("A01-101", draft.room(), "编号在建单时就归一，不能等到查询两边各转一次");

        WorkOrder submitted = sm.apply(draft, "STUDENT", "stu-1", "submit", 1000.0,
                StateMachine.Inputs.none(), null);
        assertEquals(87400.0, submitted.slaDueAt());        // 1000 + 24×3600（SRS 第 8 节算式）
        assertEquals(1000.0, submitted.submittedAt());

        WorkOrder assigned = sm.apply(submitted, "ADMIN", "adm-1", "assign", 2000.0,
                new StateMachine.Inputs("w-1", null, null), null);
        WorkOrder inProgress = sm.apply(assigned, "WORKER", "w-1", "accept", 3000.0,
                StateMachine.Inputs.none(), null);
        WorkOrder resolved = sm.apply(inProgress, "WORKER", "w-1", "resolve", 4000.0,
                new StateMachine.Inputs(null, "换了垫圈", null), null);
        assertEquals(4000.0, resolved.resolvedAt());
        assertEquals("w-1", resolved.resolvedBy());

        // 改派不重置时限（BR-08）
        WorkOrder reassigned = sm.apply(resolved.toBuilder().state("SUBMITTED").submittedAt(1000.0).build(),
                "ADMIN", "adm-1", "assign", 9000.0, new StateMachine.Inputs("w-2", null, null), null);
        assertEquals(87400.0, reassigned.slaDueAt());

        WorkOrder closed = sm.apply(resolved, "STUDENT", "stu-1", "confirm", 9000.0,
                StateMachine.Inputs.none(), null);
        assertEquals("CLOSED", closed.state());
        assertEquals("", closed.assignee(), "终态不挂当前负责人");
        assertEquals("w-1", closed.resolvedBy(), "但处理人必须留着（BR-11）");
        assertEquals(5, closed.history().size());
    }

    @Test
    void rejectedTransitionChangesNothing() {
        StateMachine sm = new StateMachine(contract());
        WorkOrder draft = sm.create("R2", "stu-1", "A01-101", "WATER_ELEC", "NORMAL",
                "漏水", "13800000000", 100.0);
        var boom = assertThrows(course.dormrepair.domain.TransitionRejectedException.class,
                () -> sm.apply(draft, "WORKER", "w-1", "submit", 1000.0, StateMachine.Inputs.none(), null));
        assertEquals("ROLE_NOT_ALLOWED", boom.code());
        assertEquals("DRAFT", draft.state());
        assertTrue(draft.history().isEmpty(), "被拒的转换不许留痕（BR-06 的另一面）");
    }

    @Test
    void forceCloseNeedsTheGracePeriodAndIsConfigurable() {
        StateMachine sm = new StateMachine(contract());
        WorkOrder order = resolvedOrder(sm);
        assertEquals(608800.0, sm.acceptanceDue(order, null), "4000 + 168*3600");
        assertThrows(course.dormrepair.domain.TransitionRejectedException.class,
                () -> sm.apply(order, "ADMIN", "adm-1", "force_close", 608799.9,
                        StateMachine.Inputs.none(), null));
        WorkOrder closed = sm.apply(order, "ADMIN", "adm-1", "force_close", 608800.0,
                StateMachine.Inputs.none(), null);
        assertEquals("CLOSED", closed.state());
        // 阈值是参数：1 小时宽限时，同一个 now=8000 从被拒变成允许
        assertThrows(course.dormrepair.domain.TransitionRejectedException.class,
                () -> sm.apply(order, "ADMIN", "adm-1", "force_close", 8000.0,
                        StateMachine.Inputs.none(), null));
        assertEquals("CLOSED", sm.apply(order, "ADMIN", "adm-1", "force_close", 8000.0,
                StateMachine.Inputs.none(), 1).state());
    }

    @Test
    void resolvedHistoryIsVisibleButInert() {
        StateMachine sm = new StateMachine(contract());
        WorkOrder closed = sm.apply(resolvedOrder(sm), "ADMIN", "adm-1", "force_close", 608800.0,
                StateMachine.Inputs.none(), null);
        assertTrue(sm.visibleTo(closed, "WORKER", "w-1"), "修过的人查得到自己的历史");
        assertFalse(sm.visibleTo(closed, "WORKER", "w-2"), "别人的历史不进我的列表");
        assertEquals(java.util.List.of(), sm.attemptable(closed, "WORKER"), "看得见不等于点得动");
    }

    @Test
    void staleFlagAndDecisionShareOneBoundary() {
        /**
         * `isAcceptanceStale` 是界面"可强制关闭"提示的来源（B16 的四态），
         * 而 `force_close` 的许可是判定源算的。两者必须同口径，否则会出现
         * "界面说可以、后端拒绝"之外更糟的一种：界面说不行、后端其实允许。
         *
         * 这条测试是变异探针逼出来的：我把边界从 `>=` 改成 `>`，
         * 当时 21 项测试全绿——说明这个谓词没有任何人在管（判定路径有对拍表管，视图标志没有）。
         */
        StateMachine sm = new StateMachine(contract());
        WorkOrder order = resolvedOrder(sm);
        double due = sm.acceptanceDue(order, null);          // 4000 + 168*3600 = 608800.0
        assertEquals(608800.0, due);
        assertFalse(sm.isAcceptanceStale(order, due - 0.01, null), "差一点就还没到");
        assertTrue(sm.isAcceptanceStale(order, due, null), "达到即算，与 is_overdue 同一口径");
        assertTrue(sm.isAcceptanceStale(order, due + 1, null));
        // 阈值是参数：取一个落在两条线之间的时刻 now=8000
        //   168h → 到期 608800 → 不算超时；1h → 到期 4000+3600=7600 → 已超时
        assertFalse(sm.isAcceptanceStale(order, 8000.0, null), "默认 168 小时下 8000 还没到");
        assertTrue(sm.isAcceptanceStale(order, 8000.0, 1), "换成 1 小时，同一时刻就算超时");
        // 没进过 RESOLVED 的单：宽限期不适用，而不是"立刻可关"
        WorkOrder draft = sm.create("R9", "stu-1", "A01-101", "WATER_ELEC", "NORMAL",
                "漏水", "13800000000", 100.0);
        assertFalse(sm.isAcceptanceStale(draft, 1e12, null));
    }

    private WorkOrder resolvedOrder(StateMachine sm) {
        WorkOrder draft = sm.create("R3", "stu-1", "A01-101", "WATER_ELEC", "NORMAL",
                "漏水", "13800000000", 100.0);
        WorkOrder submitted = sm.apply(draft, "STUDENT", "stu-1", "submit", 1000.0,
                StateMachine.Inputs.none(), null);
        WorkOrder assigned = sm.apply(submitted, "ADMIN", "adm-1", "assign", 2000.0,
                new StateMachine.Inputs("w-1", null, null), null);
        WorkOrder inProgress = sm.apply(assigned, "WORKER", "w-1", "accept", 3000.0,
                StateMachine.Inputs.none(), null);
        return sm.apply(inProgress, "WORKER", "w-1", "resolve", 4000.0,
                new StateMachine.Inputs(null, "换垫圈", null), null);
    }
}
