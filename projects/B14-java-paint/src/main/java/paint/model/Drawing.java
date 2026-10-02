package paint.model;

import java.awt.Rectangle;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

/**
 * 文档：形状的有序列表 + 当前选中项 + 变更通知。
 *
 * <p><b>堆叠顺序</b>：列表尾部是"最上面"（最后画的盖在前面之上）。
 * 因此命中选择从尾部往前扫，第一个命中的就是视觉上该被点到的那个。
 *
 * <p><b>通知是观察者模式的使用处</b>：画布重绘、标题栏脏标记、撤销/重做按钮的可用状态，
 * 都订阅同一个信号，而不是互相调用。这里刻意只用一个 <em>drawingChanged</em>：
 * 本项目没有性能问题需要区分"内容变了"与"选中变了"，拆开只会让调用点翻倍。
 * 真要做增量重绘时再拆，拆的理由写在 README 里而不是靠猜。
 */
public final class Drawing {

    /** 观察者接口。命名用过去式回调，和 Swing 的 ActionListener 习惯一致。 */
    public interface Listener {
        void drawingChanged(Drawing drawing);
    }

    public static final int MAX_SHAPES = 5000;      // 与 io 层的解析上限同源，防止一把撑爆内存

    private final List<Shape> shapes = new ArrayList<>();
    private final List<Listener> listeners = new ArrayList<>();
    private int selection = -1;

    public int size() {
        return shapes.size();
    }

    public boolean isEmpty() {
        return shapes.isEmpty();
    }

    public Shape get(int index) {
        return shapes.get(index);
    }

    /** 只读快照：给渲染和序列化用，避免调用方拿着活列表改。 */
    public List<Shape> shapes() {
        return Collections.unmodifiableList(shapes);
    }

    public void addListener(Listener listener) {
        listeners.add(Objects.requireNonNull(listener, "listener"));
    }

    public void removeListener(Listener listener) {
        listeners.remove(listener);
    }

    private void fireChanged() {
        // 复制一份再遍历：回调里常常要读文档状态，甚至取消订阅，直接在活列表上迭代是并发修改的老坑
        for (Listener listener : new ArrayList<>(listeners)) {
            listener.drawingChanged(this);
        }
    }

    /** 插入到 index 处（index == size() 表示追加）。返回实际插入位置，命令层要记它才能撤销。 */
    public int insert(int index, Shape shape) {
        Objects.requireNonNull(shape, "shape");
        if (shapes.size() >= MAX_SHAPES) {
            throw new IllegalStateException("形状数量超过上限 " + MAX_SHAPES);
        }
        int at = Math.max(0, Math.min(index, shapes.size()));
        shapes.add(at, shape);
        selection = at;
        fireChanged();
        return at;
    }

    public Shape removeAt(int index) {
        Shape removed = shapes.remove(index);          // 越界由 ArrayList 抛出，调用方负责夹紧
        if (selection == index) {
            selection = -1;
        } else if (selection > index) {
            selection--;                               // 删掉下面的形状，上面的索引整体前移
        }
        fireChanged();
        return removed;
    }

    public Shape replaceAt(int index, Shape shape) {
        Shape previous = shapes.set(index, Objects.requireNonNull(shape, "shape"));
        fireChanged();
        return previous;
    }

    /** 载入/清空用的整体替换；不留下可撤销的中间状态，撤销由命令层负责。 */
    public void replaceAll(List<Shape> newShapes) {
        if (newShapes.size() > MAX_SHAPES) {
            throw new IllegalStateException("形状数量超过上限 " + MAX_SHAPES);
        }
        shapes.clear();
        shapes.addAll(newShapes);
        selection = -1;
        fireChanged();
    }

    public int selection() {
        return selection;
    }

    /** index 越界时不抛，而是清成"无选中"：UI 里点空白就是这个效果。 */
    public void select(int index) {
        selection = (index >= 0 && index < shapes.size()) ? index : -1;
        fireChanged();
    }

    /** 命中选择：从最上面往下找。返回 -1 表示点到了空白处。 */
    public int indexOfNearest(int x, int y) {
        for (int index = shapes.size() - 1; index >= 0; index--) {
            if (shapes.get(index).contains(x, y)) {
                return index;
            }
        }
        return -1;
    }

    /** 内容外接框（含线宽与容差）；导出图片与"适应窗口"都用它。空文档返回 0,0,0,0。 */
    public Rectangle contentBounds() {
        Rectangle box = null;
        for (Shape shape : shapes) {
            Rectangle bounds = shape.bounds();
            if (box == null) {
                box = new Rectangle(bounds);
            } else {
                box.add(bounds);
            }
        }
        if (box == null) {
            return new Rectangle(0, 0, 0, 0);
        }
        box.grow(Shape.STROKE_WIDTH + Shape.HIT_TOLERANCE, Shape.STROKE_WIDTH + Shape.HIT_TOLERANCE);
        return box;
    }

    /** 只取几何范围（不外扩），给"负坐标能不能存"这类边界检查用。 */
    public Rectangle rawBounds() {
        Rectangle box = null;
        for (Shape shape : shapes) {
            Rectangle bounds = shape.bounds();
            if (box == null) {
                box = new Rectangle(bounds);
            } else {
                box.add(bounds);
            }
        }
        return box == null ? new Rectangle(0, 0, 0, 0) : box;
    }
}
