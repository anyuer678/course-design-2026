package course.dormrepair.web;

import course.dormrepair.domain.StateMachine;
import course.dormrepair.domain.WorkOrder;

import java.util.List;

/**
 * 接口层给前端的唯一视图。
 *
 * `attemptable` 与 `requiredInputs` 由领域算好一起给（B16 的老约束：前端不许自己判断状态），
 * 所以 SRS 第 3 节改了以后，接口返回的动作列表自己就变了，前端一行不用改。
 */
public record OrderView(String id, String reporter, String room, String category, String priority,
                        String description, String contact, String state, String assignee,
                        String resolvedBy, double createdAt, Double submittedAt, Double slaDueAt,
                        Double resolvedAt, boolean overdue, boolean acceptanceStale,
                        List<String> attemptable, List<String> requiredInputs,
                        List<ChangeView> history) {

    public record ChangeView(double at, String from, String to, String action,
                             String actorRole, String actorId, String reason) {
    }

    public static OrderView of(WorkOrder order, StateMachine machine, String actorRole, double now) {
        List<String> actions = machine.attemptable(order, actorRole);
        return new OrderView(order.id(), order.reporter(), order.room(), order.category(),
                order.priority(), order.description(), order.contact(), order.state(),
                order.assignee(), order.resolvedBy(), order.createdAt(), order.submittedAt(),
                order.slaDueAt(), order.resolvedAt(),
                machine.isOverdue(order, now), machine.isAcceptanceStale(order, now, null),
                actions, actions.stream().flatMap(a -> machine.requiredInputs(a).stream()).distinct().sorted().toList(),
                order.history().stream()
                        .map(c -> new ChangeView(c.at(), c.from(), c.to(), c.action(), c.actorRole(),
                                c.actorId(), c.reason()))
                        .toList());
    }
}
