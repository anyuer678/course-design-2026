package paint.ui;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.Rectangle;
import paint.model.Drawing;
import paint.model.Shape;

/**
 * 渲染：文档 + 一个"正在拖出来的预览形状" → 画面。
 *
 * <p>写成静态纯函数是有原因的：这样测试可以把它画到一张离屏 {@link java.awt.image.BufferedImage}
 * 上数像素，不需要真的开一个窗口。"必须开窗口才能验证画对了"是最难自动化的状态。
 *
 * <p>不启用抗锯齿（除了预览的描边），因为测试要判断"这个区域里有没有这个颜色"：
 * 抗锯齿会把边缘像素混色，断言变得依赖渲染管线。这里选"可断言"而不是"更好看"，
 * 并且把选择写下来。
 */
public final class Painter {

    public static final Color BACKGROUND = Color.WHITE;
    public static final Color SELECTION = new Color(0, 120, 215);

    private Painter() {
    }

    public static void render(Drawing drawing, Shape preview, Graphics2D g, int width, int height) {
        g.setColor(BACKGROUND);
        g.fillRect(0, 0, Math.max(width, 1), Math.max(height, 1));
        for (Shape shape : drawing.shapes()) {
            shape.draw(g);
        }
        if (preview != null) {
            preview.draw(g);                  // 预览与最终形状走同一段绘制代码，所见即所得
        }
        int selected = drawing.selection();
        if (selected >= 0 && selected < drawing.size()) {
            drawSelection(g, drawing.get(selected).bounds());
        }
    }

    private static void drawSelection(Graphics2D g, Rectangle box) {
        Rectangle halo = new Rectangle(box.x - 3, box.y - 3, box.width + 6, box.height + 6);
        g.setColor(SELECTION);
        g.setStroke(new BasicStroke(1f, BasicStroke.CAP_BUTT, BasicStroke.JOIN_MITER,
                1f, new float[]{4f, 3f}, 0f));
        g.draw(halo);
        for (int[] corner : new int[][]{{halo.x, halo.y},
                {halo.x + halo.width, halo.y},
                {halo.x, halo.y + halo.height},
                {halo.x + halo.width, halo.y + halo.height}}) {
            g.fillRect(corner[0] - 2, corner[1] - 2, 5, 5);
        }
    }
}
