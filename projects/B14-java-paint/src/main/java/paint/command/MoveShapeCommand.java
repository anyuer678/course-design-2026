package paint.command;

import paint.model.Drawing;
import paint.model.Shape;

/**
 * 移动一个形状：把列表里的那个位置换成平移后的新实例。
 *
 * <p>形状不可变，所以"移动"不是改字段而是替换；撤销只要放回旧实例，
 * 不需要记录"反向位移"——反向位移在连续多次移动后容易和别人的记录错位。
 */
public final class MoveShapeCommand implements Command {

    private final Drawing drawing;
    private final int index;
    private final int dx;
    private final int dy;
    private Shape previous;

    public MoveShapeCommand(Drawing drawing, int index, int dx, int dy) {
        this.drawing = drawing;
        this.index = index;
        this.dx = dx;
        this.dy = dy;
    }

    public boolean isNoOp() {
        return dx == 0 && dy == 0;
    }

    @Override
    public void execute() {
        Shape current = drawing.get(index);
        if (previous == null) {
            previous = current;
        }
        drawing.replaceAt(index, current.translatedBy(dx, dy));
    }

    @Override
    public void undo() {
        if (previous == null) {
            throw new IllegalStateException("还没执行过移动，无法撤销");
        }
        drawing.replaceAt(index, previous);
    }

    @Override
    public String describe() {
        return "移动 " + (previous == null ? "" : previous.kind()) + " (" + dx + "," + dy + ")";
    }
}
