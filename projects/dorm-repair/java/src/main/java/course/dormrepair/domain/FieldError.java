package course.dormrepair.domain;

import java.util.List;

/** 字段级错误：一次报全（FR-03、NFR-03）。B13 编译器与 B14 文件校验都验证过这条交互价值。 */
public record FieldError(String field, String code, String reason) {
}
