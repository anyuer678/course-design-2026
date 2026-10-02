package course.dormrepair.soap;

import course.dormrepair.app.OrderConflictException;
import course.dormrepair.app.OrderNotFoundException;
import course.dormrepair.app.RepairService;
import course.dormrepair.contract.WorkflowContract;
import course.dormrepair.domain.InvalidFieldsException;
import course.dormrepair.domain.StateMachine;
import course.dormrepair.domain.TimeSource;
import course.dormrepair.domain.TransitionRejectedException;
import course.dormrepair.domain.WorkOrder;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * UC-05（查询工单）的 SOAP 形态。
 *
 * 这层的纪律只有一条：**不判定业务**。可见集合、按钮、逾期标志全部来自 `RepairService`
 * 与 `StateMachine`（它们只认契约），所以同一身份走 REST 和走 SOAP 必然拿到同一批工单。
 * 一旦这里出现 `state.equals("SUBMITTED")` 之类的判断，`check_arch.py` 的状态字面量白名单就会红灯。
 */
public class SoapQueryService {

    private final RepairService service;
    private final WorkflowContract contract;
    private final TimeSource clock;

    public SoapQueryService(RepairService service, WorkflowContract contract, TimeSource clock) {
        this.service = service;
        this.contract = contract;
        this.clock = clock;
    }

    /** 处理一条请求，返回可直接写进 SOAP Body 的 XML。业务错误以 Fault 形式返回同样的错误码。 */
    public String handle(byte[] payload) {
        SoapEnvelope.Request request;
        try {
            request = SoapEnvelope.parse(payload);
        } catch (SoapFaultException e) {
            return SoapEnvelope.fault(e.code(), e.getMessage(), true);
        }
        try {
            return switch (request.operation()) {
                case "ListOrders" -> listOrders(request);
                case "GetOrder" -> getOrder(request);
                default -> SoapEnvelope.fault("CLIENT",
                        "本服务只有 ListOrders / GetOrder，收到 " + request.operation(), true);
            };
        } catch (TransitionRejectedException e) {
            return SoapEnvelope.fault(e.code(), e.getMessage(), !e.code().equals("ROLE_NOT_ALLOWED"));
        } catch (InvalidFieldsException e) {
            return SoapEnvelope.fault("INVALID_FIELDS", e.getMessage(), true);
        } catch (OrderNotFoundException e) {
            return SoapEnvelope.fault("NOT_FOUND", e.getMessage(), true);
        } catch (OrderConflictException e) {
            return SoapEnvelope.fault("CONCURRENT_UPDATE", e.getMessage(), false);
        } catch (IllegalArgumentException e) {
            return SoapEnvelope.fault("BAD_IDENTITY", e.getMessage(), true);
        }
    }

    private String listOrders(SoapEnvelope.Request request) {
        String role = identity(request);
        String actor = request.required("Actor");
        boolean overdue = Boolean.parseBoolean(request.text("Overdue", "false"));
        List<WorkOrder> orders = service.list(role, actor,
                emptyToNull(request.required("State")), emptyToNull(request.required("Category")),
                emptyToNull(request.required("Room")), emptyToNull(request.required("Priority")),
                overdue);
        List<SoapEnvelope.Item> body = new ArrayList<>();
        for (WorkOrder order : orders) {
            body.add(toElement(order, role));
        }
        body.add(0, SoapEnvelope.Item.of("Count", String.valueOf(orders.size())));
        return SoapEnvelope.response("ListOrders", body);
    }

    private String getOrder(SoapEnvelope.Request request) {
        String role = identity(request);
        String actor = request.required("Actor");
        WorkOrder order = service.one(role, actor, request.required("Id"));
        return SoapEnvelope.response("GetOrder", List.of(toElement(order, role)));
    }

    private String identity(SoapEnvelope.Request request) {
        String role = request.required("Role");
        if (!contract.roles().contains(role)) {
            throw new IllegalArgumentException("未知角色 " + role + "；合法值 " + contract.roles());
        }
        if (request.required("Actor").isBlank()) {
            throw new IllegalArgumentException("Actor 不能为空：可见性与归属判定都靠它");
        }
        return role;
    }

    /** 字段名与 REST 视图一一对应，这样两边的差异只可能是"包装"，不可能是"内容"。 */
    private SoapEnvelope.Item toElement(WorkOrder order, String role) {
        StateMachine machine = service.machine();
        List<String> actions = machine.attemptable(order, role);
        List<SoapEnvelope.Item> children = new ArrayList<>();
        children.add(SoapEnvelope.Item.of("Id", order.id()));
        children.add(SoapEnvelope.Item.of("State", order.state()));
        children.add(SoapEnvelope.Item.of("Reporter", order.reporter()));
        children.add(SoapEnvelope.Item.of("Room", order.room()));
        children.add(SoapEnvelope.Item.of("Category", order.category()));
        children.add(SoapEnvelope.Item.of("Priority", order.priority()));
        children.add(SoapEnvelope.Item.of("Assignee", order.assignee()));
        children.add(SoapEnvelope.Item.of("ResolvedBy", order.resolvedBy()));
        children.add(SoapEnvelope.Item.of("Overdue",
                String.valueOf(machine.isOverdue(order, clock.now()))));
        children.add(SoapEnvelope.Item.of("AcceptanceStale",
                String.valueOf(machine.isAcceptanceStale(order, clock.now(), null))));
        // 按钮用 Attemptable / Input 这两个专属元素名：曾经写成 <Action>，
        // 于是和历史留痕里的 <Change><Action> 撞名，客户端（和测试）只能靠"它在第几层"猜。
        for (String action : actions) {
            children.add(SoapEnvelope.Item.of("Attemptable", action));
        }
        for (String input : actions.stream().flatMap(a -> machine.requiredInputs(a).stream())
                .distinct().sorted().toList()) {
            children.add(SoapEnvelope.Item.of("Input", input));
        }
        List<SoapEnvelope.Item> changes = new ArrayList<>();
        for (WorkOrder.Change c : order.history()) {
            changes.add(SoapEnvelope.Item.of("Change", List.of(
                    SoapEnvelope.Item.of("At", String.valueOf(c.at())),
                    SoapEnvelope.Item.of("From", c.from()),
                    SoapEnvelope.Item.of("To", c.to()),
                    SoapEnvelope.Item.of("Action", c.action()),
                    SoapEnvelope.Item.of("Actor", c.actorId()))));
        }
        children.add(SoapEnvelope.Item.of("History", changes));
        return SoapEnvelope.Item.of("Order", children);
    }

    private static String emptyToNull(String value) {
        return value == null || value.isBlank() ? null : value;
    }

    /** 供 WSDL 生成用：操作 → 需要的元素名。这张小表只讲"消息形状"，不讲业务规则。 */
    public Map<String, List<String>> operationShapes() {
        return Map.of(
                "ListOrders", List.of("Role", "Actor", "State", "Category", "Room", "Priority", "Overdue"),
                "GetOrder", List.of("Role", "Actor", "Id"));
    }

    public String wsdl() {
        return Wsdl.of(contract, operationShapes());
    }
}
