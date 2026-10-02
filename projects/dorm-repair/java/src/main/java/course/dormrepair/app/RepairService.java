package course.dormrepair.app;

import course.dormrepair.domain.InvalidFieldsException;
import course.dormrepair.domain.StateMachine;
import course.dormrepair.domain.TimeSource;
import course.dormrepair.domain.TransitionRejectedException;
import course.dormrepair.domain.WorkOrder;
import course.dormrepair.domain.WorkOrderRepository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 应用服务：一次动作 = 一个事务边界（docs/08 的第 3 节）。
 *
 * 事务里做的恰好是四步：读单 → 交给领域判定 → 写回（带 version）→ 追加留痕。
 * 少一步会出现"状态改了但留痕没写"，多一步（比如在事务里再判定一次）就是第二个判定源。
 */
public class RepairService {

    private final StateMachine machine;
    private final WorkOrderRepository repository;
    private final TimeSource clock;

    public RepairService(StateMachine machine, WorkOrderRepository repository, TimeSource clock) {
        this.machine = machine;
        this.repository = repository;
        this.clock = clock;
    }

    public StateMachine machine() {
        return machine;
    }

    /** FR-01 + NFR-03：校验不过一张单都不产生。 */
    @Transactional
    public WorkOrder create(String reporter, String room, String category, String priority,
                            String description, String contact) {
        String id = repository.nextId();
        WorkOrder draft = machine.create(id, reporter, room, category, priority, description,
                contact, clock.now());
        if (!repository.save(draft, -1)) {
            throw new OrderConflictException(id);
        }
        return repository.find(id).orElseThrow(() -> new OrderNotFoundException(id));
    }

    /** 一次状态动作。`graceHours` 只给测试与配置用（AC-24 要证明阈值能被换掉）。 */
    @Transactional
    public WorkOrder act(String id, String actorRole, String actorId, String action,
                         StateMachine.Inputs inputs, Integer graceHours) {
        WorkOrder current = repository.find(id).orElseThrow(() -> new OrderNotFoundException(id));
        int version = repository.versionOf(id);
        WorkOrder next = machine.apply(current, actorRole, actorId, action, clock.now(), inputs,
                graceHours);
        if (!repository.save(next, version)) {
            throw new OrderConflictException(id);
        }
        return repository.find(id).orElseThrow(() -> new OrderNotFoundException(id));
    }

    public List<WorkOrder> list(String actorRole, String actorId) {
        return repository.visible(actorRole, actorId);
    }

    /**
     * 单条读取。**必须**走 `find` 而不是从列表里挑——列表查询为了省一次 join 不读留痕表，
     * 用列表读详情就会得到一份"状态对、历史空"的视图（B18 实测踩过，见 RepairApiTest）。
     * 可见性仍然先收口：不在范围内一律按不存在处理，不透露"这张单存在但你不能看"。
     */
    public WorkOrder one(String actorRole, String actorId, String id) {
        WorkOrder order = repository.find(id).orElseThrow(() -> new OrderNotFoundException(id));
        if (!machine.visibleTo(order, actorRole, actorId)) {
            throw new OrderNotFoundException(id);
        }
        return order;
    }

    public List<WorkOrder> list(String actorRole, String actorId, String state, String category,
                                String room, String priority, boolean overdueOnly) {
        return repository.visibleFiltered(actorRole, actorId, state, category, room, priority,
                overdueOnly, clock.now());
    }

    /** 越权与非法转换由领域抛码；这里只负责把错误透出去，不重新解释规则。 */
    public static String codeOf(RuntimeException e) {
        if (e instanceof TransitionRejectedException t) {
            return t.code();
        }
        if (e instanceof InvalidFieldsException) {
            return "INVALID_FIELDS";
        }
        return "INTERNAL";
    }
}
