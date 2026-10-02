package course.dormrepair.infra;

import course.dormrepair.contract.WorkflowContract;
import course.dormrepair.domain.StateMachine;
import course.dormrepair.domain.WorkOrder;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;


import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 仓储的三个真实风险：并发覆盖、重启丢失、越权可见。
 * 这三件事在 B15/B16 的内存模型里**不存在**，所以不能靠"模型测过了"推定。
 */
class RepositoryTest {

    private final WorkflowContract contract = WorkflowContract.loadFromClasspath();
    private final StateMachine machine = new StateMachine(contract);

    private JdbcTemplate fresh(String url) {
        // H2 的内存库在"最后一条连接关闭"时就销毁，而 DriverManagerDataSource 每条语句都开新连接：
        // 于是第一条 CREATE TABLE 执行完，库已经没了，第二条就会报 Table WORK_ORDER not found。
        // 这不是 H2 的坑，是"连接池语义 vs 一次性连接"的语义差——测试里必须显式钉住库的生命周期。
        String normalized = url.contains(":mem:") && !url.contains("DB_CLOSE_DELAY")
                ? url + ";DB_CLOSE_DELAY=-1"
                : url;
        DriverManagerDataSource ds = new DriverManagerDataSource();
        ds.setDriverClassName("org.h2.Driver");
        ds.setUrl(normalized);
        ds.setUsername("sa");
        ds.setPassword("");
        JdbcTemplate jdbc = new JdbcTemplate(ds);
        for (String statement : Schema.ddl(contract).split(";")) {
            if (!statement.isBlank()) {
                jdbc.execute(statement.trim());
            }
        }
        return jdbc;
    }

    private WorkOrder submitted(JdbcTemplate jdbc, String id) {
        JdbcWorkOrderRepository repo = new JdbcWorkOrderRepository(jdbc, contract);
        WorkOrder draft = machine.create(id, "stu-1", "A01-101", "WATER_ELEC", "NORMAL",
                "水管漏水", "13800000000", 100.0);
        WorkOrder order = machine.apply(draft, "STUDENT", "stu-1", "submit", 1000.0,
                StateMachine.Inputs.none(), null);
        assertTrue(repo.save(order, -1));
        return order;
    }

    @Test
    void roundTripKeepsEveryFieldIncludingHistory() {
        JdbcTemplate jdbc = fresh("jdbc:h2:mem:rt-" + System.nanoTime());
        JdbcWorkOrderRepository repo = new JdbcWorkOrderRepository(jdbc, contract);
        WorkOrder order = submitted(jdbc, "RT01");
        WorkOrder assigned = machine.apply(order, "ADMIN", "adm-1", "assign", 2000.0,
                new StateMachine.Inputs("w-1", null, null), null);
        assertTrue(repo.save(assigned, repo.versionOf("RT01")));

        Optional<WorkOrder> back = repo.find("RT01");
        assertTrue(back.isPresent());
        assertEquals("ASSIGNED", back.get().state());
        assertEquals("w-1", back.get().assignee());
        assertEquals(1000.0, back.get().submittedAt());
        assertEquals(87400.0, back.get().slaDueAt());
        assertEquals(2, back.get().history().size(), "留痕必须一条不少地回来（BR-06）");
        assertEquals(List.of("submit", "assign"),
                back.get().history().stream().map(WorkOrder.Change::action).toList());
    }

    @Test
    void staleVersionIsRefusedAndDoesNotOverwrite() {
        JdbcTemplate jdbc = fresh("jdbc:h2:mem:ver-" + System.nanoTime());
        JdbcWorkOrderRepository repo = new JdbcWorkOrderRepository(jdbc, contract);
        WorkOrder order = submitted(jdbc, "VR01");
        int read = repo.versionOf("VR01");

        WorkOrder toW1 = machine.apply(order, "ADMIN", "adm-1", "assign", 2000.0,
                new StateMachine.Inputs("w-1", null, null), null);
        WorkOrder toW2 = machine.apply(order, "ADMIN", "adm-1", "assign", 2100.0,
                new StateMachine.Inputs("w-2", null, null), null);

        assertTrue(repo.save(toW1, read), "第一个写者按读到的版本写，应当成功");
        assertFalse(repo.save(toW2, read), "第二个写者拿的是同一个旧版本，必须写不进去");
        assertEquals("w-1", repo.find("VR01").orElseThrow().assignee(),
                "冲突的代价是失败，不是把前一个人的结果覆盖掉");
        assertEquals(read + 1, repo.versionOf("VR01"));
    }

    @Test
    void concurrentAssignLetsExactlyOneWinnerThrough() throws Exception {
        // 真起两个线程，都从同一版本读到 SUBMITTED，再都尝试派给不同的人。
        // 乐观锁的意义只有在这种时候才看得见：内存模型里根本不会出现这个交错。
        JdbcTemplate jdbc = fresh("jdbc:h2:mem:cc-" + System.nanoTime());
        JdbcWorkOrderRepository repo = new JdbcWorkOrderRepository(jdbc, contract);
        WorkOrder order = submitted(jdbc, "CC01");
        int read = repo.versionOf("CC01");

        AtomicInteger ok = new AtomicInteger();
        CountDownLatch go = new CountDownLatch(1);
        List<Thread> threads = List.of(
                new Thread(() -> tryAssign(repo, order, read, "w-1", ok, go)),
                new Thread(() -> tryAssign(repo, order, read, "w-2", ok, go)));
        threads.forEach(Thread::start);
        go.countDown();                                    // 两个线程卡在同一发令时刻，交错才可能真的出现
        for (Thread t : threads) {
            t.join(5000);
        }
        assertEquals(1, ok.get(), "两个并发派单只允许一个成功");
        WorkOrder stored = repo.find("CC01").orElseThrow();
        assertTrue(List.of("w-1", "w-2").contains(stored.assignee()), stored.assignee());
        assertEquals(read + 1, repo.versionOf("CC01"), "只有一笔写入推进了版本号");
        assertEquals(1L, jdbc.queryForObject("SELECT COUNT(*) FROM work_order_change WHERE order_id='CC01'",
                        Long.class).longValue() - 1,
                "留痕也只该多一条：败者的那一步不能留下痕迹");
    }

    private void tryAssign(JdbcWorkOrderRepository repo, WorkOrder order, int version,
                           String worker, AtomicInteger ok, CountDownLatch go) {
        try {
            go.await();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        WorkOrder next = machine.apply(order, "ADMIN", "adm-1", "assign", 2000.0,
                new StateMachine.Inputs(worker, null, null), null);
        if (repo.save(next, version)) {
            ok.incrementAndGet();
        }
    }

    @Test
    void dataSurvivesProcessRestart() throws Exception {
        Path dir = Files.createTempDirectory("b18-restart");
        String file = dir.resolve("repair").toString().replace('\\', '/');
        String url = "jdbc:h2:file:" + file + ";DB_CLOSE_ON_EXIT=FALSE";

        JdbcTemplate first = fresh(url);
        submitted(first, "RS01");
        JdbcWorkOrderRepository repo1 = new JdbcWorkOrderRepository(first, contract);
        WorkOrder assigned = machine.apply(repo1.find("RS01").orElseThrow(), "ADMIN", "adm-1",
                "assign", 2000.0, new StateMachine.Inputs("w-1", null, null), null);
        assertTrue(repo1.save(assigned, repo1.versionOf("RS01")));
        java.sql.Connection probe = first.getDataSource().getConnection();
        probe.close();                                     // 关掉这条连接；文件库的数据在磁盘上，不靠连接活着

        // 换一套连接对象，等于进程重启：数据必须还在，历史不能断
        JdbcTemplate second = fresh(url);
        JdbcWorkOrderRepository repo2 = new JdbcWorkOrderRepository(second, contract);
        WorkOrder back = repo2.find("RS01").orElseThrow(() -> new AssertionError("重启后工单不见了"));
        assertEquals("ASSIGNED", back.state());
        assertEquals("w-1", back.assignee());
        assertEquals(2, back.history().size());
        assertEquals(87400.0, back.slaDueAt(), "SLA 起算点不能因为重启而丢失");
    }

    @Test
    void draftsOfOthersNeverReachTheWorkerQuery() {
        JdbcTemplate jdbc = fresh("jdbc:h2:mem:vis-" + System.nanoTime());
        JdbcWorkOrderRepository repo = new JdbcWorkOrderRepository(jdbc, contract);
        // stu-1 的草稿：直接落库，不走转换，模拟"存了没提交"
        WorkOrder otherDraft = machine.create("VS01", "stu-1", "A01-101", "WATER_ELEC", "NORMAL",
                "没写完", "13800000000", 100.0);
        assertTrue(repo.save(otherDraft, -1));
        WorkOrder mine = machine.create("VS02", "stu-2", "A01-102", "NETWORK", "LOW",
                "网口没信号", "13900002222", 110.0);
        assertTrue(repo.save(mine, -1));

        assertEquals(List.of(), repo.visible("WORKER", "w-1").stream()
                .filter(o -> o.state().equals("DRAFT")).map(WorkOrder::id).toList(),
                "草稿不进公共池（SRS 第 6 节、AQ-07）");
        assertEquals(List.of("VS01"), repo.visible("STUDENT", "stu-1").stream()
                .map(WorkOrder::id).toList());
        assertEquals(List.of("VS01", "VS02"), repo.visible("ADMIN", "adm-1").stream()
                .map(WorkOrder::id).toList());
        // 先收口再筛选：管理员按 room 筛不会把别人的草稿带出来
        assertEquals(List.of(), new JdbcWorkOrderRepository(jdbc, contract)
                .visibleFiltered("STUDENT", "stu-2", "DRAFT", null, "A01-101", null, false, 0.0));
    }

    @Test
    void workerSeesOwnResolvedHistoryButNotOthers() {
        JdbcTemplate jdbc = fresh("jdbc:h2:mem:hist-" + System.nanoTime());
        JdbcWorkOrderRepository repo = new JdbcWorkOrderRepository(jdbc, contract);
        WorkOrder order = submitted(jdbc, "HS01");
        WorkOrder assigned = machine.apply(order, "ADMIN", "adm-1", "assign", 2000.0,
                new StateMachine.Inputs("w-1", null, null), null);
        WorkOrder inProgress = machine.apply(assigned, "WORKER", "w-1", "accept", 2500.0,
                StateMachine.Inputs.none(), null);
        WorkOrder resolved = machine.apply(inProgress, "WORKER", "w-1", "resolve", 3000.0,
                new StateMachine.Inputs(null, "换了垫圈", null), null);
        WorkOrder closed = machine.apply(resolved, "STUDENT", "stu-1", "confirm", 4000.0,
                StateMachine.Inputs.none(), null);
        assertTrue(repo.save(closed, repo.versionOf("HS01")));

        assertEquals(List.of("HS01"), repo.visible("WORKER", "w-1").stream()
                .map(WorkOrder::id).toList(), "AQ-12：修过的人查得到自己的历史");
        assertEquals(List.of(), repo.visible("WORKER", "w-2").stream()
                .map(WorkOrder::id).toList(), "别人的历史不进我的列表");
        assertEquals("", closed.assignee());
        assertEquals("w-1", repo.find("HS01").orElseThrow().resolvedBy());
    }

    @Test
    void ddlLengthsComeFromTheContractNotFromTyping() {
        String ddl = Schema.ddl(contract);
        assertEquals(500, contract.fieldLimits().get("description").max());
        assertEquals(200, contract.fieldLimits().get("reason").max());
        assertTrue(ddl.contains("description   VARCHAR(500)"), ddl);
        assertTrue(ddl.contains("reason       VARCHAR(200)"), ddl);

        // 契约里少一行 field_limits，DDL 就必须拒绝生成，而不是"那段用默认长度"
        WorkflowContract missing = new WorkflowContract(contract.schemaVersion(), contract.roles(),
                contract.states(), contract.actions(), contract.terminalStates(), contract.categories(),
                contract.priorities(), contract.preconditions(), contract.transitions(),
                contract.permissions(), contract.visibility(), contract.slaHours(),
                contract.acceptanceGraceHours(), contract.fieldEffects(),
                java.util.Map.of("room", new WorkflowContract.Limit(8, 8, "ROOM_PATTERN")),
                contract.fieldErrors());
        IllegalStateException boom = assertThrows(IllegalStateException.class, () -> Schema.ddl(missing));
        assertTrue(boom.getMessage().contains("description"), boom.getMessage());
    }
}
