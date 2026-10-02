package paint;

import java.nio.file.Path;
import java.nio.file.Paths;
import javax.swing.SwingUtilities;
import paint.io.SafeStore;
import paint.ui.PaintFrame;

/**
 * 程序入口。
 *
 * <p>文档目录默认是"当前工作目录下的 data/"，可以用 <code>-Dpaint.data=...</code> 换掉——
 * 测试与离屏演示就是靠这个开关指向临时目录的，不需要为了测试在生产代码里留后门。
 *
 * <p><code>--demo</code> 走一条完全不开窗口的路径：用命令层画几个形状、撤销一次、
 * 再渲染到离屏图上统计像素并导出 PNG。它的用途是"在没有显示器的环境里也能证明
 * 绘制与撤销确实改变了画面"；真窗口的观感仍然要人点一遍（README 里写明了哪部分没被自动验证）。
 */
public final class App {

    private App() {
    }

    public static void main(String[] args) throws Exception {
        if (args.length > 0 && (args[0].equals("--help") || args[0].equals("-h"))) {
            System.out.println("用法: java paint.App [--demo]");
            System.out.println("  无参数   打开画图窗口（需要显示器）");
            System.out.println("  --demo   不开窗口：命令层画几个形状 + 撤销 + 离屏导出 PNG");
            System.out.println("  文档目录: -Dpaint.data=目录  （默认 ./data）");
            return;
        }
        String configured = System.getProperty("paint.data");
        Path root = Paths.get(configured == null ? "data" : configured);
        SafeStore store = new SafeStore(root);
        if (args.length > 0 && args[0].equals("--demo")) {
            demo();
            return;
        }
        try {
            javax.swing.UIManager.setLookAndFeel(javax.swing.UIManager.getSystemLookAndFeelClassName());
        } catch (Exception lookAndFeelProblem) {
            // 换肤失败不影响功能，用默认观感继续
        }
        SwingUtilities.invokeLater(() -> new PaintFrame(store).setVisible(true));
    }

    private static void demo() throws Exception {
        var drawing = new paint.model.Drawing();
        var history = new paint.command.CommandHistory();
        var canvas = new paint.ui.PaintCanvas(drawing, history);
        canvas.setColor(java.awt.Color.RED);
        canvas.pressAt(40, 40, false);
        canvas.dragTo(220, 150);
        canvas.releaseAt(220, 150);
        canvas.setTool(paint.ui.Tool.ELLIPSE);
        canvas.setColor(java.awt.Color.BLUE);
        canvas.pressAt(260, 60, false);
        canvas.dragTo(400, 190);
        canvas.releaseAt(400, 190);
        canvas.setTool(paint.ui.Tool.LINE);
        canvas.setColor(java.awt.Color.GREEN);
        canvas.pressAt(60, 300, false);
        canvas.dragTo(380, 340);
        canvas.releaseAt(380, 340);
        System.out.println("画完 3 个形状：" + shapesOf(drawing));

        history.undo();
        System.out.println("撤销一次（去掉线段）：" + shapesOf(drawing));
        history.redo();
        System.out.println("重做回来：" + shapesOf(drawing));

        var image = new java.awt.image.BufferedImage(480, 380,
                java.awt.image.BufferedImage.TYPE_INT_RGB);
        var g = image.createGraphics();
        try {
            canvas.renderInto(g, image.getWidth(), image.getHeight());
        } finally {
            g.dispose();
        }
        int red = count(image, java.awt.Color.RED);
        int blue = count(image, java.awt.Color.BLUE);
        int green = count(image, java.awt.Color.GREEN);
        System.out.println("离屏像素统计：红 " + red + "、蓝 " + blue + "、绿 " + green
                + "（三个都应为正，说明三条绘制路径都真的落到画面上）");
        java.nio.file.Path png = java.nio.file.Files.createTempFile("b14-demo", ".png");
        javax.imageio.ImageIO.write(image, "png", png.toFile());
        System.out.println("PNG 写到临时目录：" + png + "（" + java.nio.file.Files.size(png)
                + " 字节），故意不放进项目目录，免得每次演示都留垃圾文件");
    }

    private static String shapesOf(paint.model.Drawing drawing) {
        StringBuilder out = new StringBuilder();
        for (paint.model.Shape shape : drawing.shapes()) {
            out.append(out.isEmpty() ? "" : ", ").append(shape.kind());
        }
        return "[" + out + "]";
    }

    private static int count(java.awt.image.BufferedImage image, java.awt.Color color) {
        int rgb = color.getRGB();
        int found = 0;
        for (int y = 0; y < image.getHeight(); y++) {
            for (int x = 0; x < image.getWidth(); x++) {
                if (image.getRGB(x, y) == rgb) {
                    found++;
                }
            }
        }
        return found;
    }
}
