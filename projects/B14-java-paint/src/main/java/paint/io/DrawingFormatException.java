package paint.io;

import java.util.Collections;
import java.util.List;

/** 文档文件的解析失败。一次性携带全部问题，而不是撞到第一个就丢一句"格式不对"。 */
public final class DrawingFormatException extends Exception {

    private static final long serialVersionUID = 1L;

    private final List<String> problems;

    public DrawingFormatException(String first, List<String> problems) {
        super(first);
        this.problems = Collections.unmodifiableList(problems);
    }

    public List<String> problems() {
        return problems;
    }
}
