package course.dormrepair.domain;

import java.util.List;

/** 建单字段校验未通过。`errors` 是**全部**问题，不是第一个（FR-03）。 */
public class InvalidFieldsException extends RuntimeException {
    private final List<FieldError> errors;

    public InvalidFieldsException(List<FieldError> errors) {
        super("字段校验未通过：" + errors.stream()
                .map(e -> e.field() + "(" + e.code() + ")").toList());
        this.errors = List.copyOf(errors);
    }

    public List<FieldError> errors() {
        return errors;
    }
}
