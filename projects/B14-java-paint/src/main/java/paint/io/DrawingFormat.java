package paint.io;

import java.awt.Color;
import java.util.ArrayList;
import java.util.List;
import paint.model.Drawing;
import paint.model.EllipseShape;
import paint.model.LineShape;
import paint.model.PencilShape;
import paint.model.Point;
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
        // 画笔是变长格式：颜色 + 点数 + 2×点数 个坐标（+ 可选线宽尾缀）；其余固定 6 字段
        boolean pencil = "pencil".equals(kind);
        boolean known = pencil || "line".equals(kind)
                || "rect".equals(kind) || "ellipse".equals(kind);
        if (!known) {
            problems.add("第 " + lineNo + " 行：不认识的类型 " + kind);
            return null;
        }
        // 线宽尾缀（wN，可选）：非画笔在末尾第 7 字段；画笔在最后一个字段。
        int width = Shape.STROKE_WIDTH;
        if (parts.length >= (pencil ? 5 : 7)) {
            String tail = parts[parts.length - 1];
            if (tail.length() >= 2 && tail.charAt(0) == 'w') {
                width = Shape.parseWidthSuffix(tail);
                if (width < 0) {
                    problems.add("第 " + lineNo + " 行：线宽尾缀要写成 w1..w"
                            + Shape.MAX_WIDTH + "，实际是 " + tail);
                    return null;
                }
                String[] trimmed = new String[parts.length - 1];
                System.arraycopy(parts, 0, trimmed, 0, parts.length - 1);
                parts = trimmed;
            } else if (!pencil && parts.length != 6) {
                problems.add("第 " + lineNo + " 行：需要 6 个字段，实际 " + parts.length);
                return null;
            }
        }
        if (pencil) {
            if (parts.length < 5) {
                problems.add("第 " + lineNo + " 行：pencil 至少要 颜色+点数+2 个坐标，实际 "
                        + parts.length + " 个字段");
                return null;
            }
            return parsePencil(parts, width, lineNo, problems);
        }
        if (parts.length != 6) {
            problems.add("第 " + lineNo + " 行：需要 6 个字段，实际 " + parts.length);
            return null;
        }
        Integer[] numbers = new Integer[4];
        for (int i = 1; i <= 4; i++) {
            numbers[i - 1] = parseInt(parts[i]);
            if (numbers[i - 1] == null) {
                problems.add("第 " + lineNo + " 行：第 " + i + " 个字段不是整数：" + parts[i]);
                return null;
            }
        }
        Color color = parseColor(parts[5]);
        if (color == null) {
            problems.add("第 " + lineNo + " 行：颜色必须是 #RRGGBB，实际是 " + parts[5]);
            return null;
        }
        int x1 = numbers[0], y1 = numbers[1], x2 = numbers[2], y2 = numbers[3];
        if (!inRange(x1) || !inRange(y1) || !inRange(x2) || !inRange(y2)) {
            problems.add("第 " + lineNo + " 行：坐标超出 ±" + COORD_LIMIT);
            return null;
        }
        return switch (kind) {
            case "line" -> new LineShape(x1, y1, x2, y2, color, width);
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
                        ? new RectShape(x1, y1, x1 + x2, y1 + y2, color, width)
                        : new EllipseShape(x1, y1, x1 + x2, y1 + y2, color, width);
            }
        };
    }

    /** pencil 行：parts = [pencil, #RRGGBB, 点数, x1, y1, …]，width 已从尾缀解析。 */
    private static Shape parsePencil(String[] parts, int width, int lineNo,
                                     List<String> problems) {
        Color color = parseColor(parts[1]);
        if (color == null) {
            problems.add("第 " + lineNo + " 行：颜色必须是 #RRGGBB，实际是 " + parts[1]);
            return null;
        }
        Integer count = parseInt(parts[2]);
        if (count == null || count < PencilShape.MIN_POINTS
                || count > PencilShape.MAX_POINTS) {
            problems.add("第 " + lineNo + " 行：点数须在 " + PencilShape.MIN_POINTS
                    + ".." + PencilShape.MAX_POINTS + "，实际是 " + parts[2]);
            return null;
        }
        if (parts.length != 3 + 2 * count) {
            problems.add("第 " + lineNo + " 行：点数说 " + count + "，实际给了 "
                    + (parts.length - 3) + " 个坐标字段");
            return null;
        }
        List<Point> points = new ArrayList<>(count);
        for (int i = 0; i < count; i++) {
            Integer x = parseInt(parts[3 + 2 * i]);
            Integer y = parseInt(parts[4 + 2 * i]);
            if (x == null || y == null) {
                problems.add("第 " + lineNo + " 行：第 " + (i + 1) + " 个点不是整数坐标");
                return null;
            }
            if (!inRange(x) || !inRange(y)) {
                problems.add("第 " + lineNo + " 行：坐标超出 ±" + COORD_LIMIT);
                return null;
            }
            points.add(new Point(x, y));
        }
        try {
            return new PencilShape(points, color, width);
        } catch (IllegalArgumentException bad) {
            problems.add("第 " + lineNo + " 行：" + bad.getMessage());
            return null;
        }
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
