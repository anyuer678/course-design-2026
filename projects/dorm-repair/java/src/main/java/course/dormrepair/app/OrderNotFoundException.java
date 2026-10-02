package course.dormrepair.app;

/** 工单不存在（或不在可见范围内——上层按 404 处理，不用"你无权看"泄露存在性）。 */
public class OrderNotFoundException extends RuntimeException {
    public OrderNotFoundException(String id) {
        super("工单不存在：" + id);
    }
}
