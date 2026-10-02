package course.dormrepair.domain;

import java.util.ArrayList;
import java.util.List;

/**
 * 工单聚合。与 Python 侧 `spec/workorder.py` 的 `Order` 逐字段对应（SRS 第 12 节数据字典）。
 *
 * 不可变：转换成功返回**新对象**，被拒时原对象一字未动（BR-02、NFR-03）。
 * 这不是洁癖——B15 的穷举走查能断言"非法转换后历史条数不变"，靠的就是没有原地修改这回事。
 */
public record WorkOrder(String id,
                        String reporter,
                        String room,
                        String category,
                        String priority,
                        String description,
                        String contact,
                        String state,
                        String assignee,
                        String resolvedBy,
                        double createdAt,
                        Double submittedAt,
                        Double slaDueAt,
                        Double resolvedAt,
                        List<Change> history) {

    /** 一条留痕。字段与 Python 的 `Change` 一致：at/from/to/action/actor/reason。 */
    public record Change(double at, String from, String to, String action,
                         String actorRole, String actorId, String reason) {
    }

    public WorkOrder {
        history = List.copyOf(history);
    }

    public static WorkOrder draft(String id, String reporter, String room, String category,
                                  String priority, String description, String contact,
                                  double createdAt) {
        return new WorkOrder(id, reporter, room, category, priority, description, contact,
                "DRAFT", "", "", createdAt, null, null, null, List.of());
    }

    public Builder toBuilder() {
        return new Builder(this);
    }

    /** 仓储把历史单独读回来时用（record 手写 15 个参数太容易错位）。 */
    public WorkOrder withHistory(List<Change> newHistory) {
        return new WorkOrder(id, reporter, room, category, priority, description, contact,
                state, assignee, resolvedBy, createdAt, submittedAt, slaDueAt, resolvedAt, newHistory);
    }

    public boolean isTerminal(List<String> terminalStates) {
        return terminalStates.contains(state);
    }

    /** 记录式对象在 Java 里要手写一遍"改几个字段返回新对象"，这里集中一次写清楚。 */
    public static final class Builder {
        private final WorkOrder from;
        private String state;
        private String assignee;
        private String resolvedBy;
        private Double submittedAt;
        private Double slaDueAt;
        private Double resolvedAt;
        private List<Change> history;

        private Builder(WorkOrder from) {
            this.from = from;
            this.state = from.state;
            this.assignee = from.assignee;
            this.resolvedBy = from.resolvedBy;
            this.submittedAt = from.submittedAt;
            this.slaDueAt = from.slaDueAt;
            this.resolvedAt = from.resolvedAt;
            this.history = new ArrayList<>(from.history);
        }

        public Builder state(String next) {
            this.state = next;
            return this;
        }

        public Builder assignee(String who) {
            this.assignee = who == null ? "" : who;
            return this;
        }

        public Builder resolvedBy(String who) {
            this.resolvedBy = who == null ? "" : who;
            return this;
        }

        public Builder submittedAt(Double at) {
            this.submittedAt = at;
            return this;
        }

        public Builder slaDueAt(Double at) {
            this.slaDueAt = at;
            return this;
        }

        public Builder resolvedAt(Double at) {
            this.resolvedAt = at;
            return this;
        }

        public Builder append(Change change) {
            this.history.add(change);
            return this;
        }

        public WorkOrder build() {
            return new WorkOrder(from.id, from.reporter, from.room, from.category, from.priority,
                    from.description, from.contact, state, assignee, resolvedBy, from.createdAt,
                    submittedAt, slaDueAt, resolvedAt, history);
        }
    }
}
