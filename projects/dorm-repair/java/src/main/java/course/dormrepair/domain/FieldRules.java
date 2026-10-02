package course.dormrepair.domain;

import course.dormrepair.contract.WorkflowContract;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 字段校验（SRS 第 9 节，FR-03 / NFR-03）。
 *
 * 长度上限、错误码都从契约取；这个类里**只有正则**是代码，因为正则是"规则长什么样"，
 * 数字是"规则多严"——后者两边各写一遍一定会飘，前者写在 Java 里比对契约里的
 * `ROOM_PATTERN` 这个**名字**，名字对不上就当场失败（见 patternFor）。
 */
public final class FieldRules {

    private static final Pattern ROOM = Pattern.compile("^[A-Z]\\d{2}-\\d{3}$");
    private static final Pattern CONTACT = Pattern.compile("^1\\d{10}$");

    private final WorkflowContract contract;

    public FieldRules(WorkflowContract contract) {
        this.contract = contract;
    }

    public static String normalizeRoom(String raw) {
        return raw == null ? "" : raw.trim().toUpperCase();
    }

    /** 一次报全：返回所有问题，顺序稳定（按文档字段顺序）。 */
    public List<FieldError> validateOrder(String room, String category, String priority,
                                          String description, String contact) {
        List<FieldError> errors = new ArrayList<>();
        if (!ROOM.matcher(normalizeRoom(room)).matches()) {
            errors.add(new FieldError("room", code("room"), "宿舍编号要形如 A01-101"));
        }
        if (!contract.categories().contains(category)) {
            errors.add(new FieldError("category", code("category"),
                    "分类必须是 " + contract.categories()));
        }
        if (!contract.priorities().contains(priority)) {
            errors.add(new FieldError("priority", code("priority"),
                    "优先级必须是 " + contract.priorities()));
        }
        String text = description == null ? "" : description.trim();
        if (!withinLength("description", text)) {
            errors.add(new FieldError("description", code("description"), lengthReason("description")));
        }
        if (!CONTACT.matcher(contact == null ? "" : contact.trim()).matches()) {
            errors.add(new FieldError("contact", code("contact"), "联系方式要形如 11 位数字且以 1 开头"));
        }
        return errors;
    }

    /** 动作级输入（完工说明 / 理由 / 维修员工号）：出现即必须合法。 */
    public List<FieldError> requireText(String value, String fieldKey, String label) {
        String text = value == null ? "" : value.trim();
        if (text.isEmpty() || !withinLength(fieldKey, text)) {
            return List.of(new FieldError(fieldKey, code(fieldKey),
                    label + "必填，长度 " + lengthReason(fieldKey)));
        }
        return List.of();
    }

    private boolean withinLength(String fieldKey, String text) {
        WorkflowContract.Limit limit = limit(fieldKey);
        return limit.min() <= text.length() && text.length() <= limit.max();
    }

    private String lengthReason(String fieldKey) {
        WorkflowContract.Limit limit = limit(fieldKey);
        return limit.min() + ".." + limit.max();
    }

    private WorkflowContract.Limit limit(String fieldKey) {
        WorkflowContract.Limit limit = contract.fieldLimits().get(fieldKey);
        if (limit == null) {
            throw new IllegalStateException("契约的 field_limits 里没有 " + fieldKey
                    + "；说明 SRS 第 9 节的校验参数表缺行");
        }
        return limit;
    }

    private String code(String fieldKey) {
        String code = contract.fieldErrors().get(fieldKey);
        if (code == null) {
            throw new IllegalStateException("契约的 field_errors 里没有 " + fieldKey);
        }
        return code;
    }

    /** 契约里写了某个字段要过正则，但它给的名字我不认识 → 直接失败，不静默跳过。 */
    public void assertPatternsKnown() {
        contract.fieldLimits().forEach((field, limit) -> {
            switch (limit.pattern()) {
                case "NONE", "ROOM_PATTERN", "CONTACT_PATTERN" -> {
                }
                default -> throw new IllegalStateException("未知的格式代码 " + limit.pattern()
                        + "（字段 " + field + "）；契约与本实现的正则表已不同步");
            }
        });
    }
}
