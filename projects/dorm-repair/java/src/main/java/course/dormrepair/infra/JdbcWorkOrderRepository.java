package course.dormrepair.infra;

import course.dormrepair.contract.WorkflowContract;
import course.dormrepair.domain.WorkOrder;
import course.dormrepair.domain.WorkOrderRepository;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * JdbcTemplate 实现的仓储（docs/08 的 infra.jdbc 层）。
 *
 * 三件事在这层被真实化，也是 B18 相对 B15/B16 内存模型的全部新增风险：
 * 1. **乐观锁**：`version` 不匹配就不写，返回 false 由上层报冲突——
 *    否则两个管理员同时派单，后写的那个会把前一个覆盖掉，而系统里两处都"派给了自己人"。
 * 2. **历史只追加**：新记录按 seq 续写，主键 (order_id, seq) 挡住重复写；不改旧行（BR-06）。
 * 3. **可见性在 SQL 里收口**：`visible()` 的 WHERE 直接来自契约的可见性代码，
 *    不是"捞全量再过滤"（BR-09、NFR-02）。
 */
public class JdbcWorkOrderRepository implements WorkOrderRepository {

    private final JdbcTemplate jdbc;
    private final WorkflowContract contract;

    public JdbcWorkOrderRepository(JdbcTemplate jdbc, WorkflowContract contract) {
        this.jdbc = jdbc;
        this.contract = contract;
    }

    @Override
    public String nextId() {
        Long n = jdbc.queryForObject("SELECT NEXT VALUE FOR order_seq", Long.class);
        if (n == null) {
            throw new IllegalStateException("序列 order_seq 没有取到值");
        }
        return String.format("R%03d", n);
    }

    @Override
    public boolean save(WorkOrder order, int expectedVersion) {
        Integer current = versionOfOrNull(order.id());
        if (current == null) {
            jdbc.update("""
                    INSERT INTO work_order (id, reporter, room, category, priority, description,
                        contact, state, assignee, resolved_by, created_at, submitted_at,
                        sla_due_at, resolved_at, version)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                    """, order.id(), order.reporter(), order.room(), order.category(), order.priority(),
                    order.description(), order.contact(), order.state(), order.assignee(),
                    order.resolvedBy(), order.createdAt(), order.submittedAt(), order.slaDueAt(),
                    order.resolvedAt());
            appendHistory(order, 0);
            return true;
        }
        if (current != expectedVersion) {
            return false;                                   // 有人先写了一步，让上层面对冲突而不是假装成功
        }
        int updated = jdbc.update("""
                UPDATE work_order SET reporter=?, room=?, category=?, priority=?, description=?,
                    contact=?, state=?, assignee=?, resolved_by=?, created_at=?, submitted_at=?,
                    sla_due_at=?, resolved_at=?, version=?
                WHERE id=? AND version=?
                """, order.reporter(), order.room(), order.category(), order.priority(),
                order.description(), order.contact(), order.state(), order.assignee(),
                order.resolvedBy(), order.createdAt(), order.submittedAt(), order.slaDueAt(),
                order.resolvedAt(), current + 1, order.id(), expectedVersion);
        if (updated != 1) {
            return false;                                   // 两条 UPDATE 落在同一个 version 上，只有一个是 1
        }
        appendHistory(order, historyCount(order.id()));
        return true;
    }

    @Override
    public int versionOf(String id) {
        Integer v = versionOfOrNull(id);
        if (v == null) {
            throw new IllegalStateException("工单 " + id + " 不存在，读不到版本号");
        }
        return v;
    }

    private Integer versionOfOrNull(String id) {
        List<Integer> found = jdbc.query("SELECT version FROM work_order WHERE id = ?",
                (rs, i) -> rs.getInt(1), id);
        return found.isEmpty() ? null : found.get(0);
    }

    @Override
    public Optional<WorkOrder> find(String id) {
        List<WorkOrder> rows = jdbc.query("SELECT * FROM work_order WHERE id = ?", this::map, id);
        if (rows.isEmpty()) {
            return Optional.empty();
        }
        WorkOrder base = rows.get(0);
        List<WorkOrder.Change> history = jdbc.query("""
                SELECT at, source_state, target_state, action, actor_role, actor_id, reason
                FROM work_order_change WHERE order_id = ? ORDER BY seq
                """, (rs, i) -> new WorkOrder.Change(rs.getDouble("at"), rs.getString("source_state"),
                rs.getString("target_state"), rs.getString("action"), rs.getString("actor_role"),
                rs.getString("actor_id"), rs.getString("reason")), id);
        return Optional.of(base.withHistory(history));
    }

    @Override
    public List<WorkOrder> visible(String actorRole, String actorId) {
        String mode = contract.visibility().get(actorRole);
        if (mode == null) {
            throw new IllegalArgumentException("契约里没有角色 " + actorRole);
        }
        String predicate = switch (mode) {
            case "ALL" -> "1=1";
            case "OWN" -> "reporter = ?";
            case "OWN_OR_POOL" -> "(state = 'SUBMITTED' OR assignee = ?)";
            case "OWN_OR_POOL_OR_RESOLVED" -> "(state = 'SUBMITTED' OR assignee = ? OR resolved_by = ?)";
            default -> throw new IllegalStateException("未知的可见性代码 " + mode);
        };
        List<Object> args = new ArrayList<>();
        if (!"ALL".equals(mode)) {
            args.add(actorId);
            if ("OWN_OR_POOL_OR_RESOLVED".equals(mode)) {
                args.add(actorId);
            }
        }
        return attachHistory(jdbc.query("SELECT * FROM work_order WHERE " + predicate + " ORDER BY id",
                this::map, args.toArray()));
    }

    @Override
    /** 筛选条件全部走**参数绑定**，不做字符串拼接——否则 `; DROP TABLE` 就进来了。 */
    public List<WorkOrder> visibleFiltered(String actorRole, String actorId, String state,
                                           String category, String room, String priority,
                                           boolean overdueOnly, Double now) {
        StringBuilder sql = new StringBuilder("SELECT * FROM work_order WHERE ");
        List<Object> args = new ArrayList<>();
        String mode = contract.visibility().get(actorRole);
        switch (mode == null ? "" : mode) {
            case "ALL" -> sql.append("1=1");
            case "OWN" -> {
                sql.append("reporter = ?");
                args.add(actorId);
            }
            case "OWN_OR_POOL" -> {
                sql.append("(state = 'SUBMITTED' OR assignee = ?)");
                args.add(actorId);
            }
            case "OWN_OR_POOL_OR_RESOLVED" -> {
                sql.append("(state = 'SUBMITTED' OR assignee = ? OR resolved_by = ?)");
                args.add(actorId);
                args.add(actorId);
            }
            default -> throw new IllegalStateException("未知的可见性代码 " + mode);
        }
        // 收口之后才允许继续收窄（顺序反了就是泄漏，见 UC-05 异常流 1a）
        if (state != null) {
            sql.append(" AND state = ?");
            args.add(state);
        }
        if (category != null) {
            sql.append(" AND category = ?");
            args.add(category);
        }
        if (room != null) {
            sql.append(" AND room = ?");
            args.add(room.trim().toUpperCase());
        }
        if (priority != null) {
            sql.append(" AND priority = ?");
            args.add(priority);
        }
        if (overdueOnly) {
            sql.append(" AND sla_due_at IS NOT NULL AND sla_due_at <= ? "
                    + "AND state NOT IN ('CLOSED','CANCELLED','RESOLVED')");
            args.add(now);
        }
        return attachHistory(jdbc.query(sql + " ORDER BY id", this::map, args.toArray()));
    }

    /**
     * 给列表批量补留痕：一条 `IN` 查询，不按行数打 N 次查询。
     *
     * 之前列表直接返回空 history，详情才有——同一个字段两种含义，
     * 前端会显示"这张单一步都没走过"，而它明明关了。修数据比写免责声明便宜。
     */
    private List<WorkOrder> attachHistory(List<WorkOrder> orders) {
        if (orders.isEmpty()) {
            return orders;
        }
        List<String> ids = orders.stream().map(WorkOrder::id).toList();
        String placeholders = String.join(",", java.util.Collections.nCopies(ids.size(), "?"));
        Map<String, List<WorkOrder.Change>> byId = new LinkedHashMap<>();
        jdbc.query("SELECT order_id, at, source_state, target_state, action, actor_role, actor_id, reason "
                        + "FROM work_order_change WHERE order_id IN (" + placeholders + ") "
                        + "ORDER BY order_id, seq",
                rs -> {
                    byId.computeIfAbsent(rs.getString("order_id"), k -> new ArrayList<>())
                            .add(new WorkOrder.Change(rs.getDouble("at"), rs.getString("source_state"),
                                    rs.getString("target_state"), rs.getString("action"),
                                    rs.getString("actor_role"), rs.getString("actor_id"),
                                    rs.getString("reason")));
                }, ids.toArray());
        return orders.stream()
                .map(o -> o.withHistory(byId.getOrDefault(o.id(), List.of())))
                .toList();
    }

    private WorkOrder map(java.sql.ResultSet rs, int rowNum) throws java.sql.SQLException {
        return new WorkOrder(rs.getString("id"), rs.getString("reporter"), rs.getString("room"),
                rs.getString("category"), rs.getString("priority"), rs.getString("description"),
                rs.getString("contact"), rs.getString("state"), rs.getString("assignee"),
                rs.getString("resolved_by"), rs.getDouble("created_at"),
                nullableDouble(rs, "submitted_at"), nullableDouble(rs, "sla_due_at"),
                nullableDouble(rs, "resolved_at"), List.of());
    }

    /**
     * `ResultSet.wasNull()` 只反映**上一次**读取，所以每列必须读完就立刻判空。
     * 早先写成"连着取三个 double 再各自看 wasNull"，结果第二、三列的 NULL
     * 会被前一列的读取结果掩盖——这种错不会报错，只会让 SLA 凭空少一截。
     */
    private static Double nullableDouble(java.sql.ResultSet rs, String column) throws java.sql.SQLException {
        double value = rs.getDouble(column);
        return rs.wasNull() ? null : value;
    }

    private int historyCount(String id) {
        Integer n = jdbc.queryForObject("SELECT COUNT(*) FROM work_order_change WHERE order_id = ?",
                Integer.class, id);
        return n == null ? 0 : n;
    }

    private void appendHistory(WorkOrder order, int fromIndex) {
        List<WorkOrder.Change> changes = order.history();
        for (int i = fromIndex; i < changes.size(); i++) {
            WorkOrder.Change c = changes.get(i);
            final int seq = i;
            jdbc.update("""
                    INSERT INTO work_order_change (order_id, seq, at, source_state, target_state,
                        action, actor_role, actor_id, reason, note)
                    VALUES (?,?,?,?,?,?,?,?,?,'')
                    """, order.id(), seq, c.at(), c.from(), c.to(), c.action(), c.actorRole(),
                    c.actorId(), c.reason());
        }
    }
}
