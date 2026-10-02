package paint.io;

import java.awt.Color;
import java.util.ArrayList;
import java.util.List;
import paint.model.Drawing;
import paint.model.EllipseShape;
import paint.model.LineShape;
import paint.model.RectShape;
import paint.model.Shape;

/**
 * 文档的文本格式（版本 1）与解析。
 *
 * <pre>
 *   pad 1
 *   line x1 y1 x2 y2 #RRGGBB
 *   rect x y w h #RRGGBB
 *   ellipse x y w h #RRGGBB
 *   # 以 # 开头的行是注释，空行忽略
 * </pre>
 *
 * <p><b>为什么用文本而不是 {@code ObjectInputStream}</b>：反序列化不可信字节等于把
 * "构造任意对象"的权力交给文件，这是 Java 里最经典的远程代码执行入口。
 * 文本 + 白名单式的逐字段校验，最坏情况只是解析失败。
 *
 * <p>解析策略是<b>先收全问题再报告</b>：一个 200 行的手改文件里错三处时，
 * 只报第一处会让人改一次跑一次。坐标一律夹紧到 ±{@value #COORD_LIMIT}，
 * 宽高非负且 ≤ {@value #SIZE_LIMIT}，颜色必须是 6 位十六进制。
 */
public final class DrawingFormat {

    public static final String MAGIC = "pad";
    public static final int VERSION = 1;
    public static final int COORD_LIMIT = 100_000;
    public static final int SIZE_LIMIT = 100_000;
    public static final int MAX_FILE_BYTES = 4 * 1024 * 1024;
    public static final int MAX_LINES = 20_000;

    private DrawingFormat() {
    }

    // ------------------------------------------------ 写
    public static String serialize(Drawing drawing) {
        StringBuilder out = new StringBuilder();
        out.append(MAGIC).append(' ').append(VERSION).append('\n');
        out.append("# 由 B14-java-paint 生成；手改请先看 README 的格式说明\n");
        for (Shape shape : drawing.shapes()) {
            out.append(shape.serialize()).append('\n');
        }
        return out.toString();
    }

    // ------------------------------------------------ 读
    public static Drawing parse(String text) throws DrawingFormatException {
        List<String> problems = new ArrayList<>();
        Drawing drawing = new Drawing();
        List<Shape> shapes = new ArrayList<>();
        String[] lines = text.split("\r\n|\r|\n", -1);
        if (text.length() > MAX_FILE_BYTES) {
            throw new DrawingFormatException("文件过大（" + text.length() + " 字符）", List.of());
        }
        if (lines.length > MAX_LINES) {
            throw new DrawingFormatException("行数超过上限 " + MAX_LINES, List.of());
        }
        int nonEmpty = 0;
        for (int index = 0; index < lines.length; index++) {
            String line = lines[index].trim();
            int lineNo = index + 1;
            if (line.isEmpty() || line.startsWith("#")) {
                continue;
            }
            nonEmpty++;
            if (nonEmpty == 1) {
                String[] head = line.split("\\s+");
                if (head.length != 2 || !MAGIC.equals(head[0])) {
                    problems.add("第 " + lineNo + " 行：文件必须以 \"" + MAGIC + " " + VERSION
                            + "\" 开头，实际是 " + line);
                    continue;
                }
                if (!parseVersion(head[1], problems, lineNo)) {
                    continue;
                }
                continue;
            }
            if (shapes.size() >= Drawing.MAX_SHAPES) {
                problems.add("第 " + lineNo + " 行：形状数量超过上限 " + Drawing.MAX_SHAPES + "，后面的行被忽略");
                break;
            }
            Shape shape = parseShape(line, lineNo, problems);
            if (shape != null) {
                shapes.add(shape);
            }
        }
        if (nonEmpty == 0) {
            problems.add("第 1 行：空文件，缺少 \"" + MAGIC + " " + VERSION + "\" 头部");
        }
        if (!problems.isEmpty()) {
            throw new DrawingFormatException(problems.get(0), problems);
        }
        drawing.replaceAll(shapes);
        return drawing;
    }

    private static boolean parseVersion(String text, List<String> problems, int lineNo) {
        int version;
        try {
            version = Integer.parseInt(text);
        } catch (NumberFormatException bad) {
            problems.add("第 " + lineNo + " 行：版本号不是整数：" + text);
            return false;
        }
        if (version != VERSION) {
            problems.add("第 " + lineNo + " 行：不支持的版本 " + version + "（本程序读写版本 "
                    + VERSION + "）");
            return false;
        }
        return true;
    }

    private static Shape parseShape(String line, int lineNo, List<String> problems) {
        String[] parts = line.split("\\s+");
        String kind = parts[0];
        int expected = switch (kind) {
            case "line" -> 6;
            case "rect", "ellipse" -> 6;
            default -> -1;
        };
        if (expected == -1) {
            problems.add("第 " + lineNo + " 行：不认识的类型 " + kind);
            return null;
        }
        if (parts.length != expected) {
            problems.add("第 " + lineNo + " 行：需要 " + expected + " 个字段，实际 " + parts.length);
            return null;
        }
        List<Integer> numbers = new ArrayList<>();
        for (int i = 1; i <= 4; i++) {
            Integer value = parseInt(parts[i]);
            if (value == null) {
                problems.add("第 " + lineNo + " 行：第 " + i + " 个字段不是整数：" + parts[i]);
                return null;
            }
            numbers.add(value);
        }
        Color color = parseColor(parts[5]);
        if (color == null) {
            problems.add("第 " + lineNo + " 行：颜色必须是 #RRGGBB，实际是 " + parts[5]);
            return null;
        }
        int x1 = numbers.get(0), y1 = numbers.get(1), x2 = numbers.get(2), y2 = numbers.get(3);
        if (!inRange(x1) || !inRange(y1) || !inRange(x2) || !inRange(y2)) {
            problems.add("第 " + lineNo + " 行：坐标超出 ±" + COORD_LIMIT);
            return null;
        }
        return switch (kind) {
            case "line" -> new LineShape(x1, y1, x2, y2, color);
            default -> {
                // rect/ellipse 的第 3、4 个字段是宽高，必须非负；
                // 手改文件里写成 "x1 y1 x2 y2" 是常见误用，宁可报错也不猜
                if (x2 < 0 || y2 < 0) {
                    problems.add("第 " + lineNo + " 行：宽高不能为负");
                    yield null;
                }
                if (x2 > SIZE_LIMIT || y2 > SIZE_LIMIT) {
                    problems.add("第 " + lineNo + " 行：宽高超出 " + SIZE_LIMIT);
                    yield null;
                }
                yield "rect".equals(kind)
                        ? new RectShape(x1, y1, x1 + x2, y1 + y2, color)
                        : new EllipseShape(x1, y1, x1 + x2, y1 + y2, color);
            }
        };
    }

    private static boolean inRange(int value) {
        return value >= -COORD_LIMIT && value <= COORD_LIMIT;
    }

    private static Integer parseInt(String text) {
        try {
            return Integer.valueOf(text);
        } catch (NumberFormatException bad) {
            return null;
        }
    }

    /** 只认 #RRGGBB：不接受颜色名、不接受 8 位带 alpha 的写法，避免同一个颜色有多种存法。 */
    static Color parseColor(String text) {
        if (text.length() != 7 || text.charAt(0) != '#') {
            return null;
        }
        int rgb = 0;
        for (int i = 1; i < 7; i++) {
            int digit = Character.digit(text.charAt(i), 16);
            if (digit < 0) {
                return null;
            }
            rgb = rgb * 16 + digit;
        }
        return new Color(rgb);
    }
}
