package course.dormrepair.infra;

import course.dormrepair.contract.WorkflowContract;

/**
 * 表结构由**契约**生成，不手抄。
 *
 * 理由与 ADR-02 同源：字段长度如果同时存在于 SRS 第 9 节、Python 常量和 DDL 里，
 * 那就是三处说法。这里只留两处（文档 + 契约），DDL 从契约拼出来，
 * 改文档 → 重生成契约 → DDL 自己跟着变；忘了重生成，`SchemaTest` 会红。
 */
public final class Schema {

    private Schema() {
    }

    public static String ddl(WorkflowContract contract) {
        int room = varchar("room", contract);
        int description = varchar("description", contract);
        int contact = varchar("contact", contract);
        int reason = varchar("reason", contract);
        int note = varchar("resolution_note", contract);
        int assignee = varchar("assignee", contract);
        return """
                CREATE SEQUENCE IF NOT EXISTS order_seq START WITH 1;
                CREATE TABLE IF NOT EXISTS work_order (
                  id            VARCHAR(32)  PRIMARY KEY,
                  reporter      VARCHAR(64)  NOT NULL,
                  room          VARCHAR(%d)  NOT NULL,
                  category      VARCHAR(16)  NOT NULL,
                  priority      VARCHAR(8)   NOT NULL,
                  description   VARCHAR(%d)  NOT NULL,
                  contact       VARCHAR(%d)  NOT NULL,
                  state         VARCHAR(16)  NOT NULL,
                  assignee      VARCHAR(%d)  NOT NULL DEFAULT '',
                  resolved_by   VARCHAR(%d)  NOT NULL DEFAULT '',
                  created_at    DOUBLE       NOT NULL,
                  submitted_at  DOUBLE       NULL,
                  sla_due_at    DOUBLE       NULL,
                  resolved_at   DOUBLE       NULL,
                  version       INT          NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS work_order_change (
                  order_id     VARCHAR(32) NOT NULL,
                  seq          INT         NOT NULL,
                  at           DOUBLE      NOT NULL,
                  source_state VARCHAR(16) NOT NULL,
                  target_state VARCHAR(16) NOT NULL,
                  action       VARCHAR(32) NOT NULL,
                  actor_role   VARCHAR(16) NOT NULL,
                  actor_id     VARCHAR(64) NOT NULL,
                  reason       VARCHAR(%d) NOT NULL DEFAULT '',
                  note         VARCHAR(%d) NOT NULL DEFAULT '',
                  PRIMARY KEY (order_id, seq),
                  CONSTRAINT fk_change_order FOREIGN KEY (order_id) REFERENCES work_order(id)
                );
                CREATE INDEX IF NOT EXISTS ix_wo_state ON work_order (state);
                CREATE INDEX IF NOT EXISTS ix_wo_assignee ON work_order (assignee);
                CREATE INDEX IF NOT EXISTS ix_wo_resolved ON work_order (resolved_by);
                CREATE INDEX IF NOT EXISTS ix_wo_reporter ON work_order (reporter);
                """.formatted(room, description, contact, assignee, assignee, reason, note);
    }

    /**
     * 完工说明的上限是 500、理由是 200——这两条如果抄错，数据库会**静默截断**还是报错
     * 取决于方言，太危险。所以取值只认契约，缺字段就直接失败。
     */
    private static int varchar(String field, WorkflowContract contract) {
        WorkflowContract.Limit limit = contract.fieldLimits().get(field);
        if (limit == null) {
            throw new IllegalStateException("契约的 field_limits 缺少 " + field + "，无法生成 DDL");
        }
        return limit.max();
    }
}
