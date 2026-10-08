package paint.model;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * 画笔（自由手绘）：一次拖拽采样出的一串折线点，整体算一个形状。
 *
 * <p><b>为什么整条笔迹是一个形状而不是每段一条线</b>：一笔 = 一次撤销单位，
 * 这是画图软件的通用语义。拆成 N 条 LineShape 会让"撤销一次只缩回一小段"，
 * 文档里还会塞进几千个形状。
 *
 * <p><b>不可变</b>：拖拽过程中每采一个点就换一个新实例（{@link #extendedTo}），
 * 与 {@code Shape} 家族的"移动 = 换新实例"是同一条纪律——预览引用被任何
 * 命令/重绘路径持有都不会看到半途被改的状态。
 *
 * <p>序列化格式：<code>pencil #RRGGBB[ wN] 点数 x1 y1 … xM yM</code>——
 * 点数显式写出，解析器才能校验字段数；不带 w 尾缀时按默认线宽读回。
 */
public final class PencilShape extends Shape {

    /** 单条笔迹的采样点上限：防一个超长拖拽把文件与内存撑爆。 */
    public static final int MAX_POINTS = 10_000;
    /** 少于 2 个点不成笔迹（单击是误点，画布层负责拦截）。 */
    public static final int MIN_POINTS = 2;

    private final List<Point> points;

    /** 用完整点列构造（画布首拖与解析器都用）；笔迹至少要两个采样点。 */
    public PencilShape(List<Point> points, Color color, int strokeWidth) {
        super(color, strokeWidth);
        Objects.requireNonNull(points, "points");
        if (points.size() < MIN_POINTS) {
            throw new IllegalArgumentException("笔迹至少要 " + MIN_POINTS + " 个点");
        }
        if (points.size() > MAX_POINTS) {
            throw new IllegalArgumentException("笔迹点数超过上限 " + MAX_POINTS);
        }
        this.points = List.copyOf(points);
    }

    /** 追加一个采样点：返回新实例（同点重复采样返回 this，避免拖住不动时疯狂分配）。 */
    public PencilShape extendedTo(int x, int y) {
        Point last = points.get(points.size() - 1);
        if (last.x() == x && last.y() == y) {
            return this;
        }
        if (points.size() >= MAX_POINTS) {
            return this;                    // 到上限就停在原笔迹：不再生长也不抛（拖拽路径不适合抛）
        }
        List<Point> grown = new ArrayList<>(points);
        grown.add(new Point(x, y));
        return new PencilShape(grown, color(), strokeWidth());
    }

    public List<Point> points() {
        return points;
    }

    public int pointCount() {
        return points.size();
    }

    @Override
    public String kind() {
        return "pencil";
    }

    @Override
    public Rectangle bounds() {
        Point first = points.get(0);
        int minX = first.x(), maxX = first.x(), minY = first.y(), maxY = first.y();
        for (Point point : points) {
            minX = Math.min(minX, point.x());
            maxX = Math.max(maxX, point.x());
            minY = Math.min(minY, point.y());
            maxY = Math.max(maxY, point.y());
        }
        return new Rectangle(minX, minY, maxX - minX, maxY - minY);
    }

    @Override
    public Shape translatedBy(int dx, int dy) {
        List<Point> moved = new ArrayList<>(points.size());
        for (Point point : points) {
            moved.add(new Point(point.x() + dx, point.y() + dy));
        }
        return new PencilShape(moved, color(), strokeWidth());
    }

    @Override
    public boolean contains(int x, int y) {
        // 点到任意一段的距离在容差内即命中：折线的"轮廓附近"就是逐段判
        long tolerance = HIT_TOLERANCE;
        for (int i = 0; i < points.size() - 1; i++) {
            if (new Point(x, y).squaredDistanceToSegment(points.get(i), points.get(i + 1))
                    <= tolerance * tolerance) {
                return true;
            }
        }
        return false;
    }

    @Override
    public void draw(Graphics2D g) {
        g.setColor(color());
        g.setStroke(new BasicStroke(strokeWidth(), BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
        int[] xs = new int[points.size()];
        int[] ys = new int[points.size()];
        for (int i = 0; i < points.size(); i++) {
            xs[i] = points.get(i).x();
            ys[i] = points.get(i).y();
        }
        g.drawPolyline(xs, ys, points.size());
    }

    @Override
    public String serialize() {
        StringBuilder out = new StringBuilder("pencil ").append(colorHex(color()))
                .append(' ').append(points.size());
        for (Point point : points) {
            out.append(' ').append(point.x()).append(' ').append(point.y());
        }
        return out + widthSuffix();
    }

    @Override
    protected boolean geometryEquals(Shape other) {
        return points.equals(((PencilShape) other).points);
    }

    @Override
    protected String geometryKey() {
        // 只参与 hashCode；点数大时字符串拼接是一次性成本，正确性优先
        return points.toString();
    }
}
