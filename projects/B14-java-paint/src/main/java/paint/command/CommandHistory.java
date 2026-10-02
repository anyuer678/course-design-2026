package paint.command;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;

/**
 * 撤销/重做栈。
 *
 * <p>三条规矩，每条都有对应的测试：
 * <ol>
 *   <li>执行新命令必须清空 redo 栈——否则"撤销撤销…再做一个新操作"之后
 *       重做会把一个基于旧世界的操作贴到新世界上，文档就花了。</li>
 *   <li>超过深度上限时丢最老的（并告诉调用方"最早的历史已丢失"）：
 *       不丢就会无界增长，一直画一直撤销不动就把堆撑满。</li>
 *   <li>状态变化必须通知观察者——按钮的可用状态是"问出来的"，
 *       而不是在每个操作点手动 setEnabled(true)，那样一定会漏。</li>
 * </ol>
 */
public final class CommandHistory {

    /** 观察者：撤销/重做能力变了就叫一声，UI 据此刷新按钮与标题。 */
    public interface Listener {
        void historyChanged(CommandHistory history);
    }

    public static final int DEFAULT_DEPTH = 100;

    private final Deque<Command> undoStack = new ArrayDeque<>();
    private final Deque<Command> redoStack = new ArrayDeque<>();
    private final List<Listener> listeners = new ArrayList<>();
    private final int depth;
    private int dropped;

    public CommandHistory() {
        this(DEFAULT_DEPTH);
    }

    public CommandHistory(int depth) {
        if (depth < 1) {
            throw new IllegalArgumentException("历史深度至少 1，收到 " + depth);
        }
        this.depth = depth;
    }

    public void addListener(Listener listener) {
        listeners.add(listener);
    }

    /** 执行并入栈。命令自己抛的异常原样传出去，此时它没有被记入历史，文档也没改到一半。 */
    public void run(Command command) {
        command.execute();
        undoStack.push(command);
        redoStack.clear();
        while (undoStack.size() > depth) {
            undoStack.removeLast();         // 丢最老的一条：还能撤销的范围变小，但不会内存泄漏
            dropped++;
        }
        fireChanged();
    }

    public boolean canUndo() {
        return !undoStack.isEmpty();
    }

    public boolean canRedo() {
        return !redoStack.isEmpty();
    }

    /** @return 被撤销的命令描述，用于状态栏；没有可撤销时返回 null */
    public String undo() {
        if (undoStack.isEmpty()) {
            return null;
        }
        Command command = undoStack.pop();
        command.undo();
        redoStack.push(command);
        fireChanged();
        return command.describe();
    }

    public String redo() {
        if (redoStack.isEmpty()) {
            return null;
        }
        Command command = redoStack.pop();
        command.execute();
        undoStack.push(command);
        fireChanged();
        return command.describe();
    }

    public int undoDepth() {
        return undoStack.size();
    }

    public int redoDepth() {
        return redoStack.size();
    }

    /** 因为深度上限被丢掉的历史条数：UI 要能诚实说"最早的编辑已无法撤销"。 */
    public int droppedCount() {
        return dropped;
    }

    public String peekUndo() {
        return undoStack.isEmpty() ? null : undoStack.peek().describe();
    }

    public String peekRedo() {
        return redoStack.isEmpty() ? null : redoStack.peek().describe();
    }

    public void clear() {
        undoStack.clear();
        redoStack.clear();
        dropped = 0;
        fireChanged();
    }

    private void fireChanged() {
        for (Listener listener : new ArrayList<>(listeners)) {
            listener.historyChanged(this);
        }
    }
}
