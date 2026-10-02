package paint.ui;

import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.util.List;
import javax.imageio.ImageIO;
import javax.swing.BorderFactory;
import javax.swing.ButtonGroup;
import javax.swing.JButton;
import javax.swing.JColorChooser;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JToggleButton;
import javax.swing.SwingUtilities;
import javax.swing.WindowConstants;
import paint.command.CommandHistory;
import paint.io.DrawingFormat;
import paint.io.DrawingFormatException;
import paint.io.SafeStore;
import paint.model.Drawing;

/**
 * 主窗口：把工具栏、画布、撤销栈和文件动作接在一起。
 *
 * <p>这个类刻意几乎不含业务逻辑：编辑都走 {@link PaintCanvas} 的语义入口，
 * 持久化都走 {@link SafeStore}。所以"没有显示器也能测"不是空话——模型和交互都测得到，
 * 只有"按钮摆得顺手不顺手、窗口能不能开"这一类必须人工点一遍，README 里列明了。
 */
public final class PaintFrame extends JFrame {

    private static final long serialVersionUID = 1L;

    private final Drawing drawing = new Drawing();
    private final CommandHistory history = new CommandHistory();
    private final PaintCanvas canvas = new PaintCanvas(drawing, history);
    private final SafeStore store;
    private final JButton undoButton = new JButton("撤销");
    private final JButton redoButton = new JButton("重做");
    private final JLabel status = new JLabel(" 就绪");
    private final JButton colorButton = new JButton();

    /** 变更计数：只有"和上次保存时的计数不同"才算脏，比"形状数量变了"准得多——移动一个形状数量不变。 */
    private int changeCount;
    private int savedChangeCount;
    private String lastFileName;

    public PaintFrame(SafeStore store) {
        super("Java 画图");
        this.store = store;
        setDefaultCloseOperation(WindowConstants.DO_NOTHING_ON_CLOSE);
        setLayout(new BorderLayout());
        add(buildToolbar(), BorderLayout.NORTH);
        add(canvas, BorderLayout.CENTER);
        add(status, BorderLayout.SOUTH);
        setSize(900, 620);
        setLocationByPlatform(true);

        drawing.addListener(changed -> onDrawingChanged());
        history.addListener(changed -> refreshHistoryButtons());
        addWindowListener(new java.awt.event.WindowAdapter() {
            @Override
            public void windowClosing(java.awt.event.WindowEvent event) {
                confirmAndClose();
            }
        });
        refreshHistoryButtons();
        refreshStatus();
    }

    public Drawing drawing() {
        return drawing;
    }

    public PaintCanvas canvas() {
        return canvas;
    }

    // ------------------------------------------------ 工具栏
    private JPanel buildToolbar() {
        JPanel bar = new JPanel();
        bar.setBorder(BorderFactory.createEmptyBorder(4, 6, 4, 6));
        ButtonGroup tools = new ButtonGroup();
        for (Tool tool : Tool.values()) {
            JToggleButton button = new JToggleButton(tool.label());
            button.setSelected(tool == canvas.tool());
            button.addActionListener(e -> canvas.setTool(tool));
            tools.add(button);
            bar.add(button);
        }
        bar.add(new JLabel("   颜色 "));
        colorButton.setBackground(canvas.color());
        colorButton.addActionListener(e -> pickColor());
        bar.add(colorButton);
        bar.add(undoButton);
        bar.add(redoButton);
        undoButton.addActionListener(e -> show(history.undo()));
        redoButton.addActionListener(e -> show(history.redo()));
        JButton newButton = new JButton("新建");
        newButton.addActionListener(e -> doNew());
        JButton saveButton = new JButton("保存");
        saveButton.addActionListener(e -> doSave());
        JButton openButton = new JButton("打开");
        openButton.addActionListener(e -> doOpen());
        JButton exportButton = new JButton("导出 PNG");
        exportButton.addActionListener(e -> doExport());
        bar.add(newButton);
        bar.add(saveButton);
        bar.add(openButton);
        bar.add(exportButton);
        return bar;
    }

    private void pickColor() {
        Color picked = JColorChooser.showDialog(this, "选择画笔颜色", canvas.color());
        if (picked != null) {
            canvas.setColor(picked);
            colorButton.setBackground(picked);
        }
    }

    // ------------------------------------------------ 文件与文档动作
    private boolean isDirty() {
        return changeCount != savedChangeCount;
    }

    private void doNew() {
        if (!confirmDiscardIfDirty()) {
            return;
        }
        // "新建"刻意不可撤销：撤销它需要保存整个旧文档的快照，代价与收益不成比例。
        // 这个取舍本身就是课程要点，写在这里而不是藏起来。
        drawing.replaceAll(List.of());
        history.clear();
        savedChangeCount = changeCount;
        lastFileName = null;
        show("已新建空白文档（历史已清空，无法撤销回来）");
    }

    private void doSave() {
        String name = askText("保存到文档目录的文件名", lastFileName == null ? "未命名.pad" : lastFileName);
        if (name == null) {
            return;
        }
        try {
            store.save(name, DrawingFormat.serialize(drawing));
            lastFileName = name;
            savedChangeCount = changeCount;
            show("已保存 " + name + "（" + drawing.size() + " 个形状）");
        } catch (IOException | RuntimeException failure) {
            error("保存失败", failure);
        }
    }

    private void doOpen() {
        String name;
        try {
            List<String> existing = store.listDocuments();
            if (existing.isEmpty()) {
                name = askText("文档目录里还没有文件，输入要打开的文件名", "未命名.pad");
            } else {
                name = (String) JOptionPane.showInputDialog(this, "选择要打开的文档", "打开",
                        JOptionPane.PLAIN_MESSAGE, null, existing.toArray(), existing.get(0));
            }
        } catch (IOException failure) {
            error("读取目录失败", failure);
            return;
        }
        if (name == null) {
            return;
        }
        if (!confirmDiscardIfDirty()) {
            return;
        }
        try {
            Drawing loaded = DrawingFormat.parse(store.load(name));
            drawing.replaceAll(loaded.shapes());
            history.clear();
            lastFileName = name;
            savedChangeCount = changeCount;
            show("已打开 " + name + "（" + drawing.size() + " 个形状）");
        } catch (DrawingFormatException bad) {
            error("文件读不懂，文档一处也没改", bad);
        } catch (IOException failure) {
            error("读取失败", failure);
        }
    }

    private void doExport() {
        String name = askText("导出 PNG 的文件名（写在文档目录里）", "画图.png");
        if (name == null) {
            return;
        }
        try {
            BufferedImage image = new BufferedImage(Math.max(1, canvas.getWidth()),
                    Math.max(1, canvas.getHeight()), BufferedImage.TYPE_INT_RGB);
            Graphics2D g = image.createGraphics();
            try {
                canvas.renderInto(g, image.getWidth(), image.getHeight());
            } finally {
                g.dispose();
            }
            java.nio.file.Path target = store.resolveExport(name);
            ImageIO.write(image, "png", target.toFile());
            show("已导出 " + target.getFileName() + "（" + image.getWidth() + "×"
                    + image.getHeight() + "）");
        } catch (IOException | RuntimeException failure) {
            error("导出失败", failure);
        }
    }

    // ------------------------------------------------ 状态
    private void onDrawingChanged() {
        changeCount++;
        canvas.repaint();
        refreshStatus();
    }

    private void refreshHistoryButtons() {
        undoButton.setEnabled(history.canUndo());
        redoButton.setEnabled(history.canRedo());
        undoButton.setToolTipText(history.canUndo() ? "撤销：" + history.peekUndo() : "没有可撤销的操作");
        redoButton.setToolTipText(history.canRedo() ? "重做：" + history.peekRedo() : "没有可重做的操作");
    }

    private void refreshStatus() {
        setTitle("Java 画图" + (isDirty() ? " *" : "") + " — " + store.root().getFileName());
        StringBuilder text = new StringBuilder(" 形状 ").append(drawing.size())
                .append("  选中 ").append(drawing.selection() < 0 ? "无" : "#" + drawing.selection())
                .append("  历史 撤销 ").append(history.undoDepth())
                .append("/重做 ").append(history.redoDepth());
        if (history.droppedCount() > 0) {
            text.append("  （最早 ").append(history.droppedCount()).append(" 步已超出历史深度，无法撤销）");
        }
        if (isDirty()) {
            text.append("  ● 未保存");
        }
        status.setText(text.toString());
    }

    private String askText(String question, String initial) {
        return (String) JOptionPane.showInputDialog(this, question, "输入",
                JOptionPane.QUESTION_MESSAGE, null, null, initial);
    }

    private boolean confirmDiscardIfDirty() {
        if (!isDirty()) {
            return true;
        }
        int choice = JOptionPane.showConfirmDialog(this, "当前文档有未保存的修改，确定丢弃吗？",
                "未保存", JOptionPane.YES_NO_OPTION, JOptionPane.WARNING_MESSAGE);
        return choice == JOptionPane.YES_OPTION;
    }

    private void confirmAndClose() {
        if (confirmDiscardIfDirty()) {
            dispose();
        }
    }

    private void error(String headline, Throwable failure) {
        String detail = failure.getMessage() == null ? failure.toString() : failure.getMessage();
        if (failure instanceof DrawingFormatException bad) {
            detail = String.join("\n", bad.problems());
        }
        show(headline + "：" + detail.split("\n")[0]);
        JOptionPane.showMessageDialog(this, headline + "\n" + detail, "出问题",
                JOptionPane.ERROR_MESSAGE);
    }

    private void show(String message) {
        if (message == null) {
            status.setText(" 没有可撤销的操作");
            refreshHistoryButtons();
            return;
        }
        status.setText(" " + message);
        refreshStatus();
    }

    /** 供入口使用：确保在事件派发线程上跑。 */
    public static void onEdt(Runnable task) {
        if (SwingUtilities.isEventDispatchThread()) {
            task.run();
        } else {
            SwingUtilities.invokeLater(task);
        }
    }
}
