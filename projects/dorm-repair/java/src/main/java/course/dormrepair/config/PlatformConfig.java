package course.dormrepair.config;

import course.dormrepair.app.RepairService;
import course.dormrepair.contract.WorkflowContract;
import course.dormrepair.domain.StateMachine;
import course.dormrepair.domain.TimeSource;
import course.dormrepair.domain.WorkOrderRepository;
import course.dormrepair.infra.JdbcWorkOrderRepository;
import course.dormrepair.infra.Schema;
import course.dormrepair.infra.SystemTimeSource;
import jakarta.annotation.PostConstruct;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * 组合根：把契约、领域、仓储、时钟接起来。分层依赖方向在这里是**单向**的——
 * config 认识所有人，domain 谁也不认识（docs/08 第 4 节）。
 */
@Configuration
public class PlatformConfig {

    /** 启动就把契约读进来；schema_version 不对时宁可起不来，也不要"读到了但按默认值猜"。 */
    @Bean
    public WorkflowContract workflowContract() {
        return WorkflowContract.loadFromClasspath();
    }

    @Bean
    public StateMachine stateMachine(WorkflowContract contract) {
        return new StateMachine(contract);
    }

    @Bean
    public TimeSource timeSource() {
        return new SystemTimeSource();
    }

    @Bean
    public WorkOrderRepository workOrderRepository(JdbcTemplate jdbc, WorkflowContract contract) {
        return new JdbcWorkOrderRepository(jdbc, contract);
    }

    @Bean
    public RepairService repairService(StateMachine machine, WorkOrderRepository repository,
                                       TimeSource clock) {
        return new RepairService(machine, repository, clock);
    }

    /** 第二种接口形态（B19）。它只组合应用服务，不引入任何判定逻辑。 */
    @Bean
    public course.dormrepair.soap.SoapQueryService soapQueryService(RepairService service,
                                                                     WorkflowContract contract,
                                                                     TimeSource clock) {
        return new course.dormrepair.soap.SoapQueryService(service, contract, clock);
    }

    /**
     * DDL 由契约生成（见 Schema）。放在这里而不是 `schema.sql` 资源文件里，
     * 是因为资源文件是"又抄了一遍字段长度"——那正是 B18 要避免的事。
     */
    @Bean
    public SchemaInitializer schemaInitializer(JdbcTemplate jdbc, WorkflowContract contract) {
        return new SchemaInitializer(jdbc, contract);
    }

    public static class SchemaInitializer {
        private final JdbcTemplate jdbc;
        private final WorkflowContract contract;

        public SchemaInitializer(JdbcTemplate jdbc, WorkflowContract contract) {
            this.jdbc = jdbc;
            this.contract = contract;
        }

        @PostConstruct
        public void create() {
            for (String statement : Schema.ddl(contract).split(";")) {
                if (!statement.isBlank()) {
                    jdbc.execute(statement.trim());
                }
            }
        }
    }
}
