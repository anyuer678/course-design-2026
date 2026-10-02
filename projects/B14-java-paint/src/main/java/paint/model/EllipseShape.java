package paint.model;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Rectangle;

/** 空心椭圆：与矩形共用"外接框"表示，差别只在命中与绘制。 */
public final class EllipseShape extends Shape {

    private final int x;
    private final int y;
    private final int width;
    private final int height;

    public EllipseShape(int x1, int y1, int x2, int y2, Color color) {
        super(color);
        Rectangle box = normalizedBox(x1, y1, x2, y2);
        this.x = box.x;
        this.y = box.y;
        this.width = box.width;
        this.height = box.height;
    }

    @Override
    public String kind() {
        return "ellipse";
    }

    @Override
    public Rectangle bounds() {
        return new Rectangle(x, y, width, height);
    }

    @Override
    public Shape translatedBy(int dx, int dy) {
        return new EllipseShape(x + dx, y + dy, x + dx + width, y + dy + height, color());
    }

    @Override
    public boolean contains(int px, int py) {
        if (!inflated(bounds()).contains(px, py)) {
            return false;
        }
        // 容差换算到"半径比"上：形状越小，同样的像素容差占的比例越大
        double slack = (2.0 * HIT_TOLERANCE) / Math.max(1.0, Math.min(width, height) / 2.0);
        return insideEllipse(bounds(), px, py, slack);
    }

    @Override
    public void draw(Graphics2D g) {
        g.setColor(color());
        g.setStroke(new BasicStroke(STROKE_WIDTH));
        g.drawOval(x, y, width, height);
    }

    @Override
    public String serialize() {
        return "ellipse " + x + " " + y + " " + width + " " + height + " " + colorHex(color());
    }

    @Override
    protected boolean geometryEquals(Shape other) {
        EllipseShape ellipse = (EllipseShape) other;
        return x == ellipse.x && y == ellipse.y && width == ellipse.width && height == ellipse.height;
    }

    @Override
    protected String geometryKey() {
        return x + "," + y + "," + width + "," + height;
    }
}
