package course.dormrepair.contract;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * SRS 的机器可读契约（docs/02 第 1/3/4/5/6/8/9/12 节 → contracts/workflow.json）。
 *
 * 这个类存在的唯一理由：Java 侧不许再抄一遍状态转换表。ADR-02 说判定源只有一份，
 * 那么 B18 的实现就只能**读**契约，不能"照着文档再敲一遍"——敲错的那一行不会报错，
 * 只会在某天变成"界面允许、后端拒绝"。
 *
 * schema_version 必须等于 2：v2 才有 acceptance_grace_hours 与 field_effects。
 * 版本不对就直接拒绝启动，而不是"字段缺失就当默认值"。
 */
public record WorkflowContract(int schemaVersion,
                               List<String> roles,
                               List<String> states,
                               List<String> actions,
                               List<String> terminalStates,
                               List<String> categories,
                               List<String> priorities,
                               Set<String> preconditions,
                               List<Transition> transitions,
                               Map<String, Set<String>> permissions,
                               Map<String, String> visibility,
                               Map<String, Integer> slaHours,
                               int acceptanceGraceHours,
                               List<FieldEffect> fieldEffects,
                               Map<String, Limit> fieldLimits,
                               Map<String, String> fieldErrors) {

    /**
     * roles / requires 用 **List 而不是 Set**：JSON 里的顺序就是文档表格的顺序，
     * Python 侧也是按 `tuple(sorted(...))` 逐个判前置条件。两边都必须按同一个顺序报第一个错，
     * 否则"两个条件同时不满足"时各报一个码，对拍表就会假性分叉。
     */
    public record Transition(String id, String action, String from, String to,
                             List<String> roles, List<String> requires) {
    }

    public record FieldEffect(String field, String when, String test) {
    }

    /** SRS 第 9 节的校验参数：长度上下限 + 要不要过正则。Java 侧不许自带一套数字。 */
    public record Limit(int min, int max, String pattern) {
    }

    public static final int SUPPORTED_SCHEMA_VERSION = 2;
    public static final String RESOURCE = "contract/workflow.json";

    public static WorkflowContract loadFromClasspath() {
        return parse(WorkflowContract.class.getClassLoader().getResourceAsStream(RESOURCE), RESOURCE);
    }

    public static WorkflowContract parse(InputStream in, String origin) {
        if (in == null) {
            throw new IllegalStateException("契约资源不存在：" + origin
                    + "（构建时应从 ../contracts/workflow.json 复制进来；见 java/pom.xml 的 <resource>）");
        }
        JsonNode root;
        try (InputStream stream = in) {
            root = new ObjectMapper().readTree(stream);
        } catch (IOException e) {
            throw new UncheckedIOException("契约解析失败：" + origin, e);
        }
        int version = root.path("schema_version").asInt(-1);
        if (version != SUPPORTED_SCHEMA_VERSION) {
            throw new IllegalStateException("契约 schema_version=" + version + "，本实现只认 v"
                    + SUPPORTED_SCHEMA_VERSION + "；拒绝用猜默认值的方式启动");
        }
        List<Transition> transitions = new ArrayList<>();
        for (JsonNode t : root.path("transitions")) {
            transitions.add(new Transition(t.path("id").asText(), t.path("action").asText(),
                    t.path("from").asText(), t.path("to").asText(),
                    stringList(t.path("roles")), stringList(t.path("requires"))));
        }
        Map<String, Set<String>> permissions = new LinkedHashMap<>();
        root.path("permissions").fields().forEachRemaining(e -> permissions.put(e.getKey(), stringSet(e.getValue())));
        Map<String, String> visibility = new LinkedHashMap<>();
        root.path("visibility").fields().forEachRemaining(e -> visibility.put(e.getKey(), e.getValue().asText()));
        Map<String, Integer> sla = new LinkedHashMap<>();
        root.path("sla_hours").fields().forEachRemaining(e -> sla.put(e.getKey(), e.getValue().asInt()));
        Map<String, String> fieldErrors = new LinkedHashMap<>();
        root.path("field_errors").fields().forEachRemaining(e -> fieldErrors.put(e.getKey(), e.getValue().asText()));
        List<FieldEffect> effects = new ArrayList<>();
        for (JsonNode row : root.path("field_effects")) {
            effects.add(new FieldEffect(row.path("field").asText(), row.path("when").asText(),
                    row.path("test").asText()));
        }
        Map<String, Limit> limits = new LinkedHashMap<>();
        root.path("field_limits").fields().forEachRemaining(e -> limits.put(e.getKey(),
                new Limit(e.getValue().path("min").asInt(), e.getValue().path("max").asInt(),
                        e.getValue().path("pattern").asText())));
        return new WorkflowContract(version, stringList(root.path("roles")), stringList(root.path("states")),
                stringList(root.path("actions")), stringList(root.path("terminal_states")),
                stringList(root.path("categories")), stringList(root.path("priorities")),
                stringSet(root.path("preconditions")), List.copyOf(transitions),
                Map.copyOf(permissions), Map.copyOf(visibility), Map.copyOf(sla),
                root.path("acceptance_grace_hours").asInt(), List.copyOf(effects),
                Map.copyOf(limits), Map.copyOf(fieldErrors));
    }

    /** 契约里最容易出事的一行：转换必须唯一确定 (action, from, role)。 */
    public Transition find(String action, String from, String role) {
        List<Transition> hits = transitions.stream()
                .filter(t -> t.action().equals(action) && t.from().equals(from) && t.roles().contains(role))
                .toList();
        if (hits.isEmpty()) {
            return null;
        }
        if (hits.size() > 1) {
            throw new IllegalStateException("契约有歧义：" + action + " 从 " + from + " 出发对角色 "
                    + role + " 命中 " + hits.size() + " 条（"
                    + hits.stream().map(Transition::id).toList() + "）");
        }
        return hits.get(0);
    }

    public boolean isTerminal(String state) {
        return terminalStates.contains(state);
    }

    /** 某个状态下某角色**可以点**的动作（只看状态与角色，不看前置条件）。与 Python 的 attemptable() 同语义。 */
    public List<String> attemptable(String state, String role) {
        return actions.stream().filter(a -> find(a, state, role) != null).toList();
    }

    /** 这个动作需要用户额外填什么。与 Python 的 required_inputs() 同语义。 */
    public List<String> requiredInputs(String action) {
        Set<String> need = new LinkedHashSet<>();
        for (Transition t : transitions) {
            if (!t.action().equals(action)) {
                continue;
            }
            if (t.requires().contains("assignee_required")) {
                need.add("assignee");
            }
            if (t.requires().contains("resolution_note")) {
                need.add("note");
            }
            if (t.requires().contains("reason")) {
                need.add("reason");
            }
        }
        return new ArrayList<>(need).stream().sorted().toList();
    }

    private static List<String> stringList(JsonNode array) {
        List<String> out = new ArrayList<>();
        array.forEach(n -> out.add(n.asText()));
        return List.copyOf(out);
    }

    private static Set<String> stringSet(JsonNode array) {
        Set<String> out = new LinkedHashSet<>();
        array.forEach(n -> out.add(n.asText()));
        return Set.copyOf(out);
    }
}
