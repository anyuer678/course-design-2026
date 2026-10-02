package course.dormrepair.app;

/** 乐观锁冲突：同一张单在"读—判定—写"之间被别人改过。上层翻成 409，让客户端重读再试。 */
public class OrderConflictException extends RuntimeException {
    public OrderConflictException(String id) {
        super("工单 " + id + " 刚被别人改过，本次写入已放弃（没有覆盖对方的结果）");
    }
}
