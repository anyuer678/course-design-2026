package course.dormrepair.domain;

import course.dormrepair.contract.WorkflowContract;

import java.util.ArrayList;
import java.util.List;

/**
 * 契约驱动的状态机：报修流程里唯一的判定处（ADR-02）。
 *
 * 三条设计约束与前几轮同源：
 * * 转换表来自契约，本类**没有任何一张手抄的状态表**；
 * * 时间一律由调用方注入（NFR-05），本类不读系统钟，所以测试不用 sleep；
 * * 被拒的转换不改原对象、不留痕（BR-02、NFR-03）。
 */
public final class StateMachine {

    /** 动作级输入：谁接单(assignee)、修了什么(note)、为什么(reason)。 */
    public record Inputs(String assignee, String note, String reason) {
        public static Inputs none() {
            return new Inputs(null, null, null);
        }
    }

    private final WorkflowContract contract;
    private final FieldRules rules;

    public StateMachine(WorkflowContract contract) {
        this.contract = contract;
        this.rules = new FieldRules(contract);
        this.rules.assertPatternsKnown();
    }

    public WorkflowContract contract() {
        return contract;
    }

    public FieldRules rules() {
        return rules;
    }

    /** FR-01：建草稿。校验不过就一张单都不产生（NFR-03）。 */
    public WorkOrder create(String id, String reporter, String room, String category,
                            String priority, String description, String contact, double createdAt) {
        List<FieldError> errors = rules.validateOrder(room, category, priority, description, contact);
        if (!errors.isEmpty()) {
            throw new InvalidFieldsException(errors);
        }
        return WorkOrder.draft(id, reporter.trim(), FieldRules.normalizeRoom(room), category, priority,
                description.trim(), contact.trim(), createdAt);
    }

    /** 当前角色在这个状态下**能尝试**的动作。只看状态与角色，不含前置条件——界面据此画按钮，
     *  服务端仍然会拒（NFR-02），所以"点了才被拒"是有意的取舍，见 docs/06 的 V4。 */
    public List<String> attemptable(WorkOrder order, String actorRole) {
        return contract.attemptable(order.state(), actorRole);
    }

    public List<String> requiredInputs(String action) {
        return contract.requiredInputs(action);
    }

    /** 只回答"这次转换行不行"，不改动任何东西。 */
    public WorkflowContract.Transition check(WorkOrder order, String actorRole, String actorId,
                                             String action, double now, Inputs inputs,
                                             Integer graceHours) {
        List<WorkflowContract.Transition> byState = contract.transitions().stream()
                .filter(t -> t.action().equals(action) && t.from().equals(order.state()))
                .toList();
        if (byState.isEmpty()) {
            throw new TransitionRejectedException("NO_SUCH_TRANSITION",
                    order.state() + " 下没有 " + action + " 这个动作");
        }
        List<WorkflowContract.Transition> matched = byState.stream()
                .filter(t -> t.roles().contains(actorRole)).toList();
        if (matched.isEmpty()) {
            throw new TransitionRejectedException("ROLE_NOT_ALLOWED",
                    actorRole + " 不能在 " + order.state() + " 发起 " + action
                            + "（允许的角色：" + byState.stream()
                            .flatMap(t -> t.roles().stream()).distinct().sorted().toList() + "）");
        }
        // 同一动作在不同状态下可能有多行（cancel 就是三条），逐行试前置条件，取第一个通过的
        TransitionRejectedException last = null;
        for (WorkflowContract.Transition candidate : matched) {
            TransitionRejectedException problem = preconditionProblem(candidate, order, actorId,
                    inputs, graceHours, now);
            if (problem == null) {
                return candidate;
            }
            last = problem;
        }
        throw last;
    }

    /** 执行转换，返回新工单。 */
    public WorkOrder apply(WorkOrder order, String actorRole, String actorId, String action,
                           double now, Inputs inputs, Integer graceHours) {
        WorkflowContract.Transition tr = check(order, actorRole, actorId, action, now, inputs, graceHours);
        WorkOrder.Builder next = order.toBuilder()
                .state(tr.to())
                .append(new WorkOrder.Change(now, tr.from(), tr.to(), tr.action(),
                        actorRole, actorId, inputs.reason() == null ? "" : inputs.reason().trim()));

        if (action.equals("assign") || action.equals("reassign")) {
            next.assignee(inputs.assignee() == null ? "" : inputs.assignee().trim());
        } else if (action.equals("return_pool") || action.equals("decline") || action.equals("escalate")
                || contract.isTerminal(tr.to())) {
            // 数据字典：待派单与终态都不挂"当前维修员"。谁修过的记在 resolved_by（BR-11），
            // 所以这里清空不会把审计信息弄丢。
            next.assignee("");
        }
        if (tr.to().equals("RESOLVED")) {
            // 每次进入 RESOLVED 都重写：处理人 + 宽限期起算点（BR-10、BR-11、SRS 第 12.1 节）
            next.resolvedBy(actorId).resolvedAt(now);
        }
        if (tr.to().equals("SUBMITTED") && order.submittedAt() == null) {
            // BR-08：只有首次进入才起算，改派与退回不重置——否则来回推诿能把时限洗成无限
            Integer hours = contract.slaHours().get(order.priority());
            if (hours == null) {
                throw new IllegalStateException("契约的 sla_hours 里没有优先级 " + order.priority());
            }
            next.submittedAt(now).slaDueAt(now + hours * 3600L);
        }
        return next.build();
    }

    // ------------------------------------------------------------ 前置条件（SRS 第 4 节图例）

    private TransitionRejectedException preconditionProblem(WorkflowContract.Transition tr,
                                                            WorkOrder order, String actorId,
                                                            Inputs inputs, Integer graceHours,
                                                            double now) {
        for (String code : tr.requires()) {
            switch (code) {
                case "none" -> {
                }
                case "owner" -> {
                    if (!order.reporter().equals(actorId)) {
                        return new TransitionRejectedException("OWNER",
                                "只能操作自己提的工单（BR-09）");
                    }
                }
                case "assignee" -> {
                    if (!order.assignee().equals(actorId)) {
                        return new TransitionRejectedException("ASSIGNEE",
                                "只有当前维修员能推进这一单（BR-04）");
                    }
                }
                case "assignee_required" -> {
                    TransitionRejectedException problem = require("assignee", inputs.assignee(),
                            "维修员工号");
                    if (problem != null) {
                        return problem;
                    }
                }
                case "resolution_note" -> {
                    TransitionRejectedException problem = require("resolution_note", inputs.note(),
                            "完工说明");
                    if (problem != null) {
                        return problem;
                    }
                }
                case "reason" -> {
                    TransitionRejectedException problem = require("reason", inputs.reason(), "理由");
                    if (problem != null) {
                        return problem;
                    }
                }
                case "acceptance_timeout" -> {
                    Double due = acceptanceDue(order, graceHours);
                    if (due == null || now < due) {
                        return new TransitionRejectedException("ACCEPTANCE_NOT_MATURE",
                                "该单停留 RESOLVED 未满宽限期（到期时刻 " + due + "，现在 " + now + "）——BR-10");
                    }
                }
                case "valid_fields" -> {
                    List<FieldError> errors = rules.validateOrder(order.room(), order.category(),
                            order.priority(), order.description(), order.contact());
                    if (!errors.isEmpty()) {
                        return new TransitionRejectedException("INVALID_FIELDS",
                                "字段校验未通过：" + errors.stream().map(FieldError::code).toList());
                    }
                }
                default -> throw new IllegalStateException("契约里有本实现不认识的前置条件代码：" + code
                        + "（转换 " + tr.id() + "）；说明契约版本与代码不同步");
            }
        }
        return null;
    }

    private TransitionRejectedException require(String fieldKey, String value, String label) {
        List<FieldError> errors = rules.requireText(value, fieldKey, label);
        if (errors.isEmpty()) {
            return null;
        }
        FieldError first = errors.get(0);
        return new TransitionRejectedException(first.code(), first.reason());
    }

    // ------------------------------------------------------------ 查询（SRS 第 6、8 节）

    public boolean visibleTo(WorkOrder order, String actorRole, String actorId) {
        String mode = contract.visibility().get(actorRole);
        if (mode == null) {
            throw new IllegalStateException("契约的可见性矩阵没有角色 " + actorRole);
        }
        return switch (mode) {
            case "ALL" -> true;
            case "OWN" -> order.reporter().equals(actorId);
            case "OWN_OR_POOL" -> order.state().equals("SUBMITTED") || order.assignee().equals(actorId);
            // AQ-12：命中 resolved_by 只给"看得见"，不给"点得动"
            case "OWN_OR_POOL_OR_RESOLVED" -> order.state().equals("SUBMITTED")
                    || order.assignee().equals(actorId)
                    || order.resolvedBy().equals(actorId);
            default -> throw new IllegalStateException("未知的可见性代码 " + mode);
        };
    }

    /** SRS 第 8 节：已完工待验收与终态都不算逾期。 */
    public boolean isOverdue(WorkOrder order, double now) {
        if (order.slaDueAt() == null || contract.isTerminal(order.state())) {
            return false;
        }
        if (order.state().equals("RESOLVED")) {
            return false;
        }
        return now >= order.slaDueAt();
    }

    public Double acceptanceDue(WorkOrder order, Integer graceHoursOverride) {
        if (order.resolvedAt() == null) {
            return null;
        }
        int hours = graceHoursOverride == null ? contract.acceptanceGraceHours() : graceHoursOverride;
        return order.resolvedAt() + hours * 3600L;
    }

    public boolean isAcceptanceStale(WorkOrder order, double now, Integer graceHoursOverride) {
        Double due = acceptanceDue(order, graceHoursOverride);
        return due != null && now >= due;
    }

    /** 供上层做"一次报全"以外的场景：把契约里的转换按文档顺序摊平，方便打印与调试。 */
    public List<String> describeTransitions() {
        List<String> out = new ArrayList<>();
        for (WorkflowContract.Transition t : contract.transitions()) {
            out.add(t.id() + " " + t.action() + " " + t.from() + "->" + t.to()
                    + " " + t.roles() + " [" + String.join(",", t.requires()) + "]");
        }
        return out;
    }
}
