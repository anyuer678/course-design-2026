package paint.model;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Rectangle;

/**
 * 所有图形的抽象基类。
 *
 * <p><b>为什么渲染放在形状里</b>：这门课要看的正是"同一个 <code>draw(g)</code> 调用，
 * 线段画线、矩形画框、椭圆画弧"的多态分发。代价也真实存在——
 * 新增一种"操作"（比如描边宽度调整、序列化）要动每个子类；
 * 那种情况下 Visitor 或数据驱动渲染更合适。本项目只有一种渲染操作 + 一种序列化，
 * 所以选了教科书式的多态，并把成本写在这里而不是假装没有。
 *
 * <p><b>不可变</b>：形状没有任何 setter。"移动"是换一个新实例（{@link #translatedBy}），
 * 于是撤销/重做只需保存旧引用，不用担心共享对象被就地改掉。
 */
public abstract class Shape {

    /** 命中容差（像素）：点选比一个像素宽的线好点中，这是可用性问题不是精度问题。 */
    public static final int HIT_TOLERANCE = 4;

    private final Color color;

    protected Shape(Color color) {
        if (color == null) {
            throw new IllegalArgumentException("颜色不能为 null");
        }
        this.color = color;
    }

    public Color color() {
        return color;
    }

    /** 类型名，用于序列化与 UI 显示；也是 {@link #parse} 分派的依据。 */
    public abstract String kind();

    /** 外接矩形（含线宽与容差之外的几何范围）。 */
    public abstract Rectangle bounds();

    /** 平移出新形状。返回 this 时调用方应意识到没有移动（dx==dy==0）。 */
    public abstract Shape translatedBy(int dx, int dy);

    /** 命中判断：点在轮廓附近（线段）或区域内（矩形、椭圆）算选中。 */
    public abstract boolean contains(int x, int y);

    public abstract void draw(Graphics2D g);

    /** 序列化成文件里的一行。格式见 paint.io.DrawingFormat，读回必须得到 equals 的形状。 */
    public abstract String serialize();

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (other == null || getClass() != other.getClass()) {
            return false;
        }
        Shape shape = (Shape) other;
        return color.equals(shape.color) && geometryEquals(shape);
    }

    @Override
    public int hashCode() {
        return java.util.Objects.hash(getClass(), color, geometryKey());
    }

    protected abstract boolean geometryEquals(Shape other);

    /** 参与 equals/hashCode 的几何数据；子类返回一个不可变键对象。 */
    protected abstract Object geometryKey();

    @Override
    public String toString() {
        return kind() + ":" + serialize();
    }

    /** 夹到画布可用范围，避免坐标溢出成负宽高（矩形拖反方向时的常见事故）。 */
    protected static Rectangle normalizedBox(int x1, int y1, int x2, int y2) {
        int left = Math.min(x1, x2);
        int top = Math.min(y1, y2);
        return new Rectangle(left, top, Math.abs(x2 - x1), Math.abs(y2 - y1));
    }

    /** 命中测试用的"点是否在轮廓附近"：椭圆没有现成的距离公式，用区域近似。 */
    protected boolean nearOutline(int x, int y, Rectangle box, boolean ellipse) {
        Rectangle outer = new Rectangle(box.x - HIT_TOLERANCE, box.y - HIT_TOLERANCE,
                box.width + 2 * HIT_TOLERANCE, box.height + 2 * HIT_TOLERANCE);
        if (!outer.contains(x, y)) {
            return false;
        }
        Rectangle inner = new Rectangle(box.x + HIT_TOLERANCE, box.y + HIT_TOLERANCE,
                Math.max(0, box.width - 2 * HIT_TOLERANCE),
                Math.max(0, box.height - 2 * HIT_TOLERANCE));
        if (!inner.contains(x, y)) {
            return true;                    // 在带子里：肯定是轮廓附近
        }
        if (ellipse) {
            // 椭圆内部也算选中：点选一个空心椭圆中间却选不中，是使用体验上的坑
            double nx = (x + 0.5 - box.getCenterX()) / Math.max(1.0, box.getWidth() / 2.0);
            double ny = (y + 0.5 - box.getCenterY()) / Math.max(1.0, box.getHeight() / 2.0);
            return nx * nx + ny * ny <= 1.0;
        }
        return true;
    }
}
