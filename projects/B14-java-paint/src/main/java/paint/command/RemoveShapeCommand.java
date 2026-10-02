package paint.command;

import paint.model.Drawing;
import paint.model.Shape;

/** 删除一个形状。撤销 = 放回原来的位置。 */
public final class RemoveShapeCommand implements Command {

    private final Drawing drawing;
    private final int index;
    private Shape removed;

    public RemoveShapeCommand(Drawing drawing, int index) {
        this.drawing = drawing;
        this.index = index;
    }

    @Override
    public void execute() {
        removed = drawing.removeAt(index);
    }

    @Override
    public void undo() {
        if (removed == null) {
            throw new IllegalStateException("还没执行过删除，无法撤销");
        }
        drawing.insert(index, removed);
    }

    @Override
    public String describe() {
        return "删除 " + (removed == null ? "" : removed.kind());
    }
}
