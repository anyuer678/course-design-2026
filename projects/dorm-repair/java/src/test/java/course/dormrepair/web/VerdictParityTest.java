package course.dormrepair.web;

import course.dormrepair.contract.WorkflowContract;
import course.dormrepair.domain.StateMachine;
import course.dormrepair.domain.TransitionRejectedException;
import course.dormrepair.domain.WorkOrder;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.io.InputStream;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 跨语言对拍：Python 模型算出的 1680 格判定，Java 必须逐格给出同样的结果。
 *
 * 这比"两边各自测自己的转换表"强，因为它钉的是**拒绝路径**：
 * NO_SUCH_TRANSITION / ROLE_NOT_ALLOWED / OWNER / ASSIGNEE / 各种 *_REQUIRED /
 * ACCEPTANCE_NOT_MATURE 该报哪一个、多个条件同时不满足时先报哪一个、宽限期到点算不算过期。
 * 这些细节在任何一边改坏，表就会分叉，而"看起来还在跑"的实现最难查的正是这种。
 *
 * 表的出处：contracts/verdict_table.json，由 `python tools/export_verdict_table.py --write` 生成。
 */
class VerdictParityTest {

    private record Actor(String role, String id) {
    }

    @Test
    void javaRecomputesEveryPythonVerdict() throws Exception {
        WorkflowContract contract = WorkflowContract.loadFromClasspath();
        StateMachine machine = new StateMachine(contract);

        JsonNode fixture;
        try (InputStream in = getClass().getClassLoader()
                .getResourceAsStream("contract/verdict_table.json")) {
            assertNotNull(in, "判定表没进 test classpath：检查 java/pom.xml 的 <testResource>");
            fixture = new ObjectMapper().readTree(in);
        }
        assertEquals(contract.schemaVersion(), fixture.path("workflow_schema_version").asInt(),
                "判定表是按另一个版本的契约生成的，先重生成再对拍");

        List<Actor> actors = new ArrayList<>();
        for (JsonNode a : fixture.path("actors")) {
            actors.add(new Actor(a.path("role").asText(), a.path("id").asText()));
        }
        List<Double> times = new ArrayList<>();
        fixture.path("times").forEach(n -> times.add(n.asDouble()));
        Map<String, String> full = new LinkedHashMap<>();
        fixture.path("inputs").path("full").fields()
                .forEachRemaining(e -> full.put(e.getKey(), e.getValue().asText()));

        Map<String, WorkOrder> canonical = canonical(machine);
        assertEquals(7, canonical.size(), "七个状态各一张代表工单");

        Map<String, String> mine = new TreeMap<>();
        for (String state : canonical.keySet()) {
            WorkOrder order = canonical.get(state);
            for (String action : contract.actions()) {
                for (Actor actor : actors) {
                    for (String label : List.of("full", "empty")) {
                        StateMachine.Inputs inputs = label.equals("full")
                                ? new StateMachine.Inputs(full.get("assignee"), full.get("note"),
                                full.get("reason"))
                                : new StateMachine.Inputs(null, null, null);
                        for (double now : times) {
                            String key = state + "|" + action + "|" + actor.role() + "|" + actor.id()
                                    + "|" + label + "|" + now;
                            mine.put(key, verdict(machine, order, actor, action, inputs, now));
                        }
                    }
                }
            }
        }

        assertEquals(fixture.path("count").asInt(), mine.size(),
                "格数就对不上：两边的穷举维度不同");
        List<String> diverging = new ArrayList<>();
        JsonNode verdicts = fixture.path("verdicts");
        for (Map.Entry<String, String> entry : mine.entrySet()) {
            String expected = verdicts.path(entry.getKey()).asText(null);
            if (expected == null) {
                diverging.add(entry.getKey() + " → 判定表里没有这一格");
            } else if (!expected.equals(entry.getValue())) {
                diverging.add(entry.getKey() + "：Python " + expected + " vs Java " + entry.getValue());
            }
        }
        for (String key : verdicts.fieldNames()) {
            if (!mine.containsKey(key)) {
                diverging.add(key + " → Java 侧没算这格");
            }
        }
        assertTrue(diverging.isEmpty(),
                diverging.size() + " 格判定分叉，前 8 条：\n  " + String.join("\n  ",
                        diverging.subList(0, Math.min(8, diverging.size()))));
    }

    private String verdict(StateMachine machine, WorkOrder order, Actor actor, String action,
                           StateMachine.Inputs inputs, double now) {
        try {
            return "OK:" + machine.apply(order, actor.role(), actor.id(), action, now, inputs, null)
                    .state();
        } catch (TransitionRejectedException e) {
            return "ERR:" + e.code();
        }
    }

    /**
     * 规范工单序列——必须与 `tools/export_verdict_table.py` 的 `canonical()` 逐字一致，
     * 包括每一步的时刻与输入。出处就在那边，所以这里的注释只写"抄自谁"。
     */
    private Map<String, WorkOrder> canonical(StateMachine machine) {
        WorkOrder d = machine.create("V1", "stu-1", "A01-101", "WATER_ELEC", "NORMAL",
                "水管漏水", "13800000000", 100.0);
        WorkOrder s = machine.apply(d, "STUDENT", "stu-1", "submit", 1000.0,
                StateMachine.Inputs.none(), null);
        WorkOrder a = machine.apply(s, "ADMIN", "adm-1", "assign", 2000.0,
                new StateMachine.Inputs("w-1", null, null), null);
        WorkOrder p = machine.apply(a, "WORKER", "w-1", "accept", 3000.0, StateMachine.Inputs.none(), null);
        WorkOrder r = machine.apply(p, "WORKER", "w-1", "resolve", 4000.0,
                new StateMachine.Inputs(null, "换了垫圈", null), null);
        WorkOrder c = machine.apply(r, "STUDENT", "stu-1", "confirm", 5000.0, StateMachine.Inputs.none(), null);
        WorkOrder x = machine.apply(s, "STUDENT", "stu-1", "cancel", 1500.0,
                new StateMachine.Inputs(null, null, "误报"), null);

        Map<String, WorkOrder> byState = new TreeMap<>();
        for (WorkOrder o : List.of(d, s, a, p, r, c, x)) {
            byState.put(o.state(), o);
        }
        return byState;
    }

    @Test
    void graceBoundaryVerdictIsTheSameOnBothSides() throws Exception {
        // 表里 ACCEPTANCE_NOT_MATURE 只能出现在 RESOLVED + force_close + now=5000 这两格
        // （empty 与 full 各一），608800 那两格必须是 OK:CLOSED。手算：4000 + 168*3600 = 608800。
        WorkflowContract contract = WorkflowContract.loadFromClasspath();
        StateMachine machine = new StateMachine(contract);
        WorkOrder resolved = canonical(machine).get("RESOLVED");
        assertEquals("RESOLVED", resolved.state());
        assertTrue(machine.check(resolved, "ADMIN", "adm-1", "force_close", 608800.0,
                StateMachine.Inputs.none(), null).to().equals("CLOSED"));
        assertEquals(608800.0, machine.acceptanceDue(resolved, null));
        TransitionRejectedException boom = org.junit.jupiter.api.Assertions.assertThrows(
                TransitionRejectedException.class,
                () -> machine.apply(resolved, "ADMIN", "adm-1", "force_close", 608799.99,
                        StateMachine.Inputs.none(), null));
        assertEquals("ACCEPTANCE_NOT_MATURE", boom.code());
    }
}
