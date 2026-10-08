package paint.model;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import java.util.Objects;

/** 线段：两个端点，命中按"点到线段的距离"。 */
public final class LineShape extends Shape {

    private final Point from;
    private final Point to;

    public LineShape(Point from, Point to, Color color) {
        super(color);
        this.from = Objects.requireNonNull(from, "from");
        this.to = Objects.requireNonNull(to, "to");
    }

    public LineShape(int x1, int y1, int x2, int y2, Color color) {
        this(new Point(x1, y1), new Point(x2, y2), color);
    }

    public LineShape(int x1, int y1, int x2, int y2, Color color, int strokeWidth) {
        this(new Point(x1, y1), new Point(x2, y2), color, strokeWidth);
    }

    public LineShape(Point from, Point to, Color color, int strokeWidth) {
        super(color, strokeWidth);
        this.from = Objects.requireNonNull(from, "from");
        this.to = Objects.requireNonNull(to, "to");
    }

    public Point from() {
        return from;
    }

    public Point to() {
        return to;
    }

    @Override
    public String kind() {
        return "line";
    }

    @Override
    public Rectangle bounds() {
        return normalizedBox(from.x(), from.y(), to.x(), to.y());
    }

    @Override
    public Shape translatedBy(int dx, int dy) {
        return new LineShape(from.x() + dx, from.y() + dy, to.x() + dx, to.y() + dy,
                color(), strokeWidth());
    }

    @Override
    public boolean contains(int x, int y) {
        long tolerance = HIT_TOLERANCE;
        // 平方比较，不开方：整数距离既没有精度问题，也不会引入 NaN
        return new Point(x, y).squaredDistanceToSegment(from, to) <= tolerance * tolerance;
    }

    @Override
    public void draw(Graphics2D g) {
        g.setColor(color());
        g.setStroke(new BasicStroke(strokeWidth(), BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
        g.drawLine(from.x(), from.y(), to.x(), to.y());
    }

    @Override
    public String serialize() {
        return "line " + from.x() + " " + from.y() + " " + to.x() + " " + to.y()
                + " " + colorHex(color()) + widthSuffix();
    }

    @Override
    protected boolean geometryEquals(Shape other) {
        LineShape line = (LineShape) other;
        return from.equals(line.from) && to.equals(line.to);
    }

    @Override
    protected String geometryKey() {
        return from.x() + "," + from.y() + "," + to.x() + "," + to.y();
    }
}
