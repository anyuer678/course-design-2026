package paint.model;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Rectangle;

/** 空心矩形：构造时就把坐标规范化成"左上角 + 非负宽高"，绘制与命中都不用再判方向。 */
public final class RectShape extends Shape {

    private final int x;
    private final int y;
    private final int width;
    private final int height;

    public RectShape(int x1, int y1, int x2, int y2, Color color) {
        super(color);
        Rectangle box = normalizedBox(x1, y1, x2, y2);
        this.x = box.x;
        this.y = box.y;
        this.width = box.width;
        this.height = box.height;
    }

    public RectShape(int x1, int y1, int x2, int y2, Color color, int strokeWidth) {
        super(color, strokeWidth);
        Rectangle box = normalizedBox(x1, y1, x2, y2);
        this.x = box.x;
        this.y = box.y;
        this.width = box.width;
        this.height = box.height;
    }

    public int x() {
        return x;
    }

    public int y() {
        return y;
    }

    public int width() {
        return width;
    }

    public int height() {
        return height;
    }

    @Override
    public String kind() {
        return "rect";
    }

    @Override
    public Rectangle bounds() {
        return new Rectangle(x, y, width, height);
    }

    @Override
    public Shape translatedBy(int dx, int dy) {
        return new RectShape(x + dx, y + dy, x + dx + width, y + dy + height,
                color(), strokeWidth());
    }

    @Override
    public boolean contains(int px, int py) {
        // 空心矩形点中间也算选中：让用户去瞄一条 2 像素宽的边是使用体验问题
        return inflated(bounds()).contains(px, py);
    }

    @Override
    public void draw(Graphics2D g) {
        g.setColor(color());
        g.setStroke(new BasicStroke(strokeWidth()));
        g.drawRect(x, y, width, height);
    }

    @Override
    public String serialize() {
        return "rect " + x + " " + y + " " + width + " " + height + " " + colorHex(color())
                + widthSuffix();
    }

    @Override
    protected boolean geometryEquals(Shape other) {
        RectShape rect = (RectShape) other;
        return x == rect.x && y == rect.y && width == rect.width && height == rect.height;
    }

    @Override
    protected String geometryKey() {
        return x + "," + y + "," + width + "," + height;
    }
}
