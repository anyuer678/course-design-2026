package course.dormrepair.web;

import course.dormrepair.app.OrderConflictException;
import course.dormrepair.app.OrderNotFoundException;
import course.dormrepair.app.RepairService;
import course.dormrepair.contract.WorkflowContract;
import course.dormrepair.domain.InvalidFieldsException;
import course.dormrepair.domain.StateMachine;
import course.dormrepair.domain.TimeSource;
import course.dormrepair.domain.TransitionRejectedException;
import course.dormrepair.domain.WorkOrder;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * REST 接口层。身份仍然走查询参数（`role` / `actor`），**这不是认证**——
 * 真实认证是 B21/B22 的事，写在 docs/09 的"明确不做"里。
 * 之所以能这么临时：授权判定全部在领域层，把参数换成真令牌不需要动任何一条规则。
 */
@RestController
@RequestMapping("/api")
public class RepairController {

    public record NewOrder(String room, String category, String priority, String description,
                           String contact) {
    }

    public record ActionInput(String assignee, String note, String reason) {
    }

    private final RepairService service;
    private final WorkflowContract contract;
    private final TimeSource clock;

    public RepairController(RepairService service, WorkflowContract contract, TimeSource clock) {
        this.service = service;
        this.contract = contract;
        this.clock = clock;
    }

    @GetMapping("/orders")
    public Map<String, Object> list(@RequestParam String role, @RequestParam String actor,
                                    @RequestParam(required = false) String state,
                                    @RequestParam(required = false) String category,
                                    @RequestParam(required = false) String room,
                                    @RequestParam(required = false) String priority,
                                    @RequestParam(defaultValue = "false") boolean overdue) {
        identity(role, actor);
        double now = clock.now();
        StateMachine machine = service.machine();
        List<OrderView> orders = service.list(role, actor, state, category, room, priority, overdue)
                .stream().map(o -> OrderView.of(o, machine, role, now)).toList();
        return Map.of("orders", orders, "actor", Map.of("role", role, "id", actor));
    }

    @GetMapping("/orders/{id}")
    public OrderView get(@PathVariable String id, @RequestParam String role,
                         @RequestParam String actor) {
        identity(role, actor);
        // 详情走 one()：它读留痕表。以前复用列表，列表不 join 历史，
        // 于是"状态明明对、history 却是空的"——这种视图会骗过只看状态的测试。
        WorkOrder order = service.one(role, actor, id);
        return OrderView.of(order, service.machine(), role, clock.now());
    }

    @PostMapping("/orders")
    public ResponseEntity<OrderView> create(@RequestParam String role, @RequestParam String actor,
                                            @RequestBody NewOrder body) {
        identity(role, actor);
        if (!role.equals("STUDENT")) {
            throw new TransitionRejectedException("ROLE_NOT_ALLOWED", "只有学生能报修（FR-01）");
        }
        WorkOrder created = service.create(actor, body.room(), body.category(), body.priority(),
                body.description(), body.contact());
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(OrderView.of(created, service.machine(), role, clock.now()));
    }

    @PostMapping("/orders/{id}/actions/{action}")
    public OrderView act(@PathVariable String id, @PathVariable String action,
                         @RequestParam String role, @RequestParam String actor,
                         @RequestBody(required = false) ActionInput body,
                         @RequestParam(required = false) Integer graceHours) {
        identity(role, actor);
        if (!contract.actions().contains(action)) {
            throw new TransitionRejectedException("NO_SUCH_TRANSITION",
                    "契约里没有动作 " + action + "（合法动作：" + contract.actions() + "）");
        }
        ActionInput safe = body == null ? new ActionInput(null, null, null) : body;
        WorkOrder next = service.act(id, role, actor, action,
                new StateMachine.Inputs(safe.assignee(), safe.note(), safe.reason()), graceHours);
        return OrderView.of(next, service.machine(), role, clock.now());
    }

    private void identity(String role, String actor) {
        if (!contract.roles().contains(role)) {
            throw new IllegalArgumentException("未知角色 " + role + "；合法值 " + contract.roles());
        }
        if (actor == null || actor.isBlank()) {
            throw new IllegalArgumentException("actor 不能为空：可见性与归属判定都靠它");
        }
    }

    // ------------------------------------------------------------ 错误→状态码（一处映射，供前端分派）

    @ExceptionHandler(InvalidFieldsException.class)
    public ResponseEntity<Map<String, Object>> onFields(InvalidFieldsException e) {
        return ResponseEntity.badRequest().body(Map.of(
                "error", "INVALID_FIELDS",
                "fields", e.errors().stream().map(f -> Map.of(
                        "field", f.field(), "code", f.code(), "reason", f.reason())).toList()));
    }

    @ExceptionHandler(TransitionRejectedException.class)
    public ResponseEntity<Map<String, Object>> onRejected(TransitionRejectedException e) {
        HttpStatus status = switch (e.code()) {
            case "ROLE_NOT_ALLOWED" -> HttpStatus.FORBIDDEN;
            case "NO_SUCH_TRANSITION" -> HttpStatus.BAD_REQUEST;
            default -> HttpStatus.CONFLICT;
        };
        return ResponseEntity.status(status).body(Map.of(
                "error", e.code(), "reason", e.getMessage()));
    }

    @ExceptionHandler(OrderNotFoundException.class)
    public ResponseEntity<Map<String, String>> onNotFound(OrderNotFoundException e) {
        // 越权读取与不存在返回同一个码：不额外透露"这张单存在但你不能看"
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("error", "NOT_FOUND",
                "reason", e.getMessage()));
    }

    @ExceptionHandler(OrderConflictException.class)
    public ResponseEntity<Map<String, String>> onConflict(OrderConflictException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of(
                "error", "CONCURRENT_UPDATE", "reason", e.getMessage()));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> onBadArgs(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", "BAD_IDENTITY",
                "reason", e.getMessage()));
    }
}
