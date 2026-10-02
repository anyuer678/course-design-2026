package paint.ui;

import java.awt.Color;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.event.KeyEvent;
import java.awt.event.KeyListener;
import java.awt.event.MouseEvent;
import java.awt.event.MouseListener;
import java.awt.event.MouseMotionListener;
import javax.swing.JPanel;
import paint.command.AddShapeCommand;
import paint.command.CommandHistory;
import paint.command.MoveShapeCommand;
import paint.command.RemoveShapeCommand;
import paint.model.Drawing;
import paint.model.Point;
import paint.model.Shape;

/**
 * 画布：把鼠标键盘事件翻译成"命令"，自己不直接改文档。
 *
 * <p><b>三个语义入口</b>（{@link #pressAt}、{@link #dragTo}、{@link #releaseAt}、
 * {@link #pressKey}）才是真干活的地方，Swing 的监听器只是转调它们的薄适配器。
 * 这样测试能驱动与 GUI 完全相同的代码路径，又不用真的开一个窗口去"点"——
 * 手工点击能验证的事，不该用脆弱的方式自动化；反过来，能自动化的就别只靠手工。
 *
 * <p>一次拖拽 = 一条命令：拖过程中只画预览、不动文档，松手才提交。
 * 如果每次 mouseDragged 都产生一条命令，撤销一次只挪动几个像素，
 * 撤销三十次才回到起点——这是画图软件里最常见的设计事故。
 */
public final class PaintCanvas extends JPanel implements MouseListener, MouseMotionListener, KeyListener {

    private static final long serialVersionUID = 1L;

    /** 小于这个位移的"拖拽"当成误点：不产生形状，也不移动。 */
    public static final int MIN_DRAG = 3;
    /** 选择工具下超过这个距离才算真的移动。 */
    public static final int MOVE_TRIGGER = 3;

    private final Drawing drawing;
    private final CommandHistory history;

    private Tool tool = Tool.RECT;
    private Color color = Color.RED;
    private Point pressAt;
    private Shape preview;
    private int movingIndex = -1;

    public PaintCanvas(Drawing drawing, CommandHistory history) {
        this.drawing = drawing;
        this.history = history;
        setBackground(Painter.BACKGROUND);
        setFocusable(true);                       // 不设为可聚焦，键盘事件永远到不了这里
        addMouseListener(this);
        addMouseMotionListener(this);
        addKeyListener(this);
    }

    // ------------------------------------------------ 状态
    public Drawing drawing() {
        return drawing;
    }

    public CommandHistory history() {
        return history;
    }

    public Tool tool() {
        return tool;
    }

    public void setTool(Tool newTool) {
        if (newTool == null) {
            throw new IllegalArgumentException("工具不能为 null");
        }
        tool = newTool;
        preview = null;
        movingIndex = -1;
        repaint();
    }

    public Color color() {
        return color;
    }

    public void setColor(Color newColor) {
        color = newColor == null ? Color.BLACK : newColor;
    }

    public Shape preview() {
        return preview;
    }

    /** 渲染当前会显示的全部内容（含预览）。测试与 paintComponent 共用这一份。 */
    public void renderInto(Graphics2D g, int width, int height) {
        Painter.render(drawing, preview, g, width, height);
    }

    @Override
    protected void paintComponent(Graphics g) {
        super.paintComponent(g);
        Graphics2D scratch = (Graphics2D) g.create();   // create() 出来的副本必须 dispose，
        try {                                            // 否则每次重绘都泄一个图形上下文
            renderInto(scratch, getWidth(), getHeight());
        } finally {
            scratch.dispose();
        }
    }

    // ------------------------------------------------ 语义入口（真实逻辑在这）
    /** 按下：绘制工具开始拖预览；选择工具命中最上面的形状并准备移动。 */
    public void pressAt(int x, int y, boolean shiftDown) {
        requestFocusInWindow();                   // 点了画布才该收到 Delete/Ctrl+Z
        pressAt = new Point(x, y);
        if (tool.isDrawingTool()) {
            movingIndex = -1;
            preview = ShapeFactory.create(tool, x, y, x, y, color);
            repaint();
            return;
        }
        preview = null;
        movingIndex = drawing.indexOfNearest(x, y);
        drawing.select(movingIndex);              // select(-1) 就是取消选中
    }

    public void dragTo(int x, int y) {
        if (pressAt == null) {
            return;
        }
        if (tool.isDrawingTool() && preview != null) {
            preview = ShapeFactory.create(tool, pressAt.x(), pressAt.y(), x, y, color);
            repaint();
        }
    }

    /** 松手：够距离才提交命令。返回 true 表示本次操作产生了一条可撤销命令。 */
    public boolean releaseAt(int x, int y) {
        if (pressAt == null) {
            return false;
        }
        int dx = x - pressAt.x();
        int dy = y - pressAt.y();
        boolean committed = false;
        if (tool.isDrawingTool()) {
            if (Math.abs(dx) >= MIN_DRAG || Math.abs(dy) >= MIN_DRAG) {
                Shape shape = ShapeFactory.create(tool, pressAt.x(), pressAt.y(), x, y, color);
                history.run(new AddShapeCommand(drawing, shape));
                committed = true;
            }
            preview = null;
        } else if (movingIndex >= 0
                && (Math.abs(dx) >= MOVE_TRIGGER || Math.abs(dy) >= MOVE_TRIGGER)) {
            history.run(new MoveShapeCommand(drawing, movingIndex, dx, dy));
            committed = true;
        }
        pressAt = null;
        movingIndex = -1;
        repaint();
        return committed;
    }

    /** 键盘：返回是否被处理，方便测试与调用方判断。 */
    public boolean pressKey(int keyCode, boolean ctrlDown, boolean shiftDown) {
        if (!ctrlDown && (keyCode == KeyEvent.VK_DELETE || keyCode == KeyEvent.VK_BACK_SPACE)) {
            int selected = drawing.selection();
            if (selected < 0) {
                return false;                     // 没选中就按下删除：什么都不该发生
            }
            history.run(new RemoveShapeCommand(drawing, selected));
            return true;
        }
        if (ctrlDown && keyCode == KeyEvent.VK_Z) {
            if (shiftDown) {
                return history.redo() != null;
            }
            return history.undo() != null;
        }
        if (ctrlDown && keyCode == KeyEvent.VK_Y) {
            return history.redo() != null;
        }
        if (keyCode == KeyEvent.VK_ESCAPE) {
            preview = null;
            movingIndex = -1;
            pressAt = null;
            drawing.select(-1);
            repaint();
            return true;
        }
        return false;
    }

    // ------------------------------------------------ Swing 适配器
    @Override
    public void mousePressed(MouseEvent e) {
        pressAt(e.getX(), e.getY(), e.isShiftDown());
    }

    @Override
    public void mouseDragged(MouseEvent e) {
        dragTo(e.getX(), e.getY());
    }

    @Override
    public void mouseReleased(MouseEvent e) {
        releaseAt(e.getX(), e.getY());
    }

    @Override
    public void mouseClicked(MouseEvent e) {
        // 单击由 press/release 组合完成，这里不需要额外动作
    }

    @Override
    public void mouseEntered(MouseEvent e) {
    }

    @Override
    public void mouseExited(MouseEvent e) {
    }

    @Override
    public void mouseMoved(MouseEvent e) {
    }

    @Override
    public void keyPressed(KeyEvent e) {
        pressKey(e.getKeyCode(), e.isControlDown(), e.isShiftDown());
    }

    @Override
    public void keyReleased(KeyEvent e) {
    }

    @Override
    public void keyTyped(KeyEvent e) {
    }
}
