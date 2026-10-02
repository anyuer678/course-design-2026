package paint.command;

import paint.model.Drawing;
import paint.model.Shape;

/** 添加一个形状。撤销 = 删掉它。 */
public final class AddShapeCommand implements Command {

    private final Drawing drawing;
    private final int requestedIndex;
    private final Shape shape;
    private int actualIndex = -1;

    public AddShapeCommand(Drawing drawing, int index, Shape shape) {
        this.drawing = drawing;
        this.requestedIndex = index;
        this.shape = shape;
    }

    /** 追加到最上层。 */
    public AddShapeCommand(Drawing drawing, Shape shape) {
        this(drawing, Integer.MAX_VALUE, shape);
    }

    @Override
    public void execute() {
        actualIndex = drawing.insert(requestedIndex, shape);
    }

    @Override
    public void undo() {
        if (actualIndex < 0 || actualIndex >= drawing.size() || !drawing.get(actualIndex).equals(shape)) {
            throw new IllegalStateException("撤销添加时找不到当初插入的那个形状");
        }
        drawing.removeAt(actualIndex);
    }

    @Override
    public String describe() {
        return "添加 " + shape.kind();
    }
}
