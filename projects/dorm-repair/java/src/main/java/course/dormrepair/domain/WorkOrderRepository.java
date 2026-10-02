package course.dormrepair.domain;

import java.util.List;
import java.util.Optional;

/**
 * 领域层的出口（docs/08 的"端口"）。领域不认识 SQL、不认识 HTTP，
 * 所以 B20 换存储、B19 拆服务时，判定逻辑不用动。
 */
public interface WorkOrderRepository {

    /**
     * 工单号由存储层原子分配（H2 序列），不在应用里"读最大值 +1"——
     * 那种写法在两个并发建单时会发出同一个号，B31 的短链计数器就是靠这个混过关的。
     */
    String nextId();

    /** 乐观锁写入：id 不存在则插入，存在则必须 version 匹配才更新；不匹配返回 false 让上层决定重试还是报冲突。 */
    boolean save(WorkOrder order, int expectedVersion);

    int versionOf(String id);

    Optional<WorkOrder> find(String id);

    /**
     * 可见性必须在**取数这一步**收口（BR-09、NFR-02）：
     * 先把全部工单捞进内存再过滤，就是 B16 那条"别人的草稿通过筛选结果泄漏"的翻版，
     * 而且这一回带上了真实数据库，泄漏的是持久化的数据。
     */
    List<WorkOrder> visible(String actorRole, String actorId);

    /**
     * 带筛选的可见集合。放在端口上而不是让上层去 `instanceof` 具体实现——
     * 一旦应用层开始"看穿"仓储类型，app→infra 就出现了一条文档没允许的依赖边，
     * 而这正是 ADR-02 要在 Java 侧同样守住的东西（B18 自查时抓到过一次）。
     */
    List<WorkOrder> visibleFiltered(String actorRole, String actorId, String state, String category,
                                    String room, String priority, boolean overdueOnly, Double now);
}
