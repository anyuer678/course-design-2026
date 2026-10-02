package course.dormrepair.domain;

/** 一次转换被拒。`code` 是给上层与测试用的稳定标识，`reason` 给人看。与 Python 的 TransitionError 同构。 */
public class TransitionRejectedException extends RuntimeException {
    private final String code;

    public TransitionRejectedException(String code, String reason) {
        super(code + ": " + reason);
        this.code = code;
    }

    public String code() {
        return code;
    }
}
