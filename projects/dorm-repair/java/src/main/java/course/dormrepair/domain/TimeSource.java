package course.dormrepair.domain;

/**
 * 时间来源（NFR-05）。领域不读系统钟——否则"验收宽限期 168 小时"这条规则
 * 就只能靠 `Thread.sleep(168 小时)` 来测，而那条测试永远不会进 CI。
 */
public interface TimeSource {

    /** epoch 秒，用 double 与 Python 侧 `spec` 的时钟口径保持一致，便于跨语言对拍。 */
    double now();
}
