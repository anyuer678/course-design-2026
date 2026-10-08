package paint.ui;

import java.awt.Color;
import paint.model.EllipseShape;
import paint.model.LineShape;
import paint.model.PencilShape;
import paint.model.RectShape;
import paint.model.Shape;

/**
 * 按工具产出形状（工厂）。
 *
 * <p>用处很具体：画布的鼠标代码只说"给我两点之间的形状"，不需要知道有几种图形类。
 * 新增一种图形时改动集中在"加一个 Shape 子类 + 这里加一个分支 + 枚举加一项"，
 * 而不是去画布的事件处理里加 if。
 *
 * <p>反面也要说清：这里只有一个创建点、几个类型，用 if-else 也完全够；
 * 抽成工厂是因为"创建逻辑要脱离 Swing 单测"，不是为了模式本身。
 * 画笔（PENCIL）是唯一例外：它是"生长式"的（首拖两点起步、随后逐点追加），
 * 不由两点工厂直接产出——画布对它走 {@link PencilShape} 的专用路径。
 */
public final class ShapeFactory {

    private ShapeFactory() {
    }

    public static Shape create(Tool tool, int x1, int y1, int x2, int y2, Color color) {
        return create(tool, x1, y1, x2, y2, color, Shape.STROKE_WIDTH);
    }

    public static Shape create(Tool tool, int x1, int y1, int x2, int y2,
                               Color color, int strokeWidth) {
        if (!tool.isDrawingTool()) {
            throw new IllegalArgumentException(tool + " 不是绘制工具");
        }
        return switch (tool) {
            case LINE -> new LineShape(x1, y1, x2, y2, color, strokeWidth);
            case RECT -> new RectShape(x1, y1, x2, y2, color, strokeWidth);
            case ELLIPSE -> new EllipseShape(x1, y1, x2, y2, color, strokeWidth);
            case PENCIL, SELECT -> throw new IllegalArgumentException(
                    tool + " 不由两点工厂产出（PENCIL 走画布的生长路径）");
        };
    }
}
