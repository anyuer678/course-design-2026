package paint;

import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import paint.command.AddShapeCommand;
import paint.command.CommandHistory;
import paint.command.MoveShapeCommand;
import paint.command.RemoveShapeCommand;
import paint.io.DrawingFormat;
import paint.io.DrawingFormatException;
import paint.io.SafeStore;
import paint.model.Drawing;
import paint.model.EllipseShape;
import paint.model.LineShape;
import paint.model.RectShape;
import paint.model.Shape;
import paint.ui.PaintCanvas;
import paint.ui.Painter;
import paint.ui.ShapeFactory;
import paint.ui.Tool;

/**
 * B14 的测试：无框架、无依赖，一个 main 跑完所有检查并以退出码报告结果。
 * 用 <code>-Djava.awt.headless=true</code> 跑，全程不开窗口。
 *
 * <p>覆盖分两类：
 * <ul>
 *   <li>逻辑：模型不可变性、作用域化命中、撤销/重做与文档同步、文件解析防线、文件名限制；</li>
 *   <li>像素与交互：把画面画到离屏图上数颜色，用画布的语义入口驱动"拖一个矩形出来"，
 *       再加一个<b>快照影子模型</b>跑 300 步随机操作 —— 撤销栈最容易出的错就是和文档失同步。</li>
 * </ul>
 */
public final class PaintTests {

    private static int checks;
    private static final List<String> FAILURES = new ArrayList<>();
    private static String group = "";

    private PaintTests() {
    }

    public static void main(String[] args) throws Exception {
        System.out.println("Java 版本 " + Runtime.version().feature()
                + "  headless=" + java.awt.GraphicsEnvironment.isHeadless());
        run("模型", PaintTests::testModel);
        run("文档与命中", PaintTests::testDrawing);
        run("撤销/重做", PaintTests::testCommands);
        run("文件格式", PaintTests::testFileFormat);
        run("文件存取防线", PaintTests::testStore);
        run("离屏渲染像素", PaintTests::testRender);
        run("交互语义", PaintTests::testInteraction);
        run("随机操作 vs 快照模型", PaintTests::testFuzzAgainstSnapshots);

        System.out.println();
        if (FAILURES.isEmpty()) {
            System.out.println("全部通过：" + checks + " 项检查，0 失败");
            return;
        }
        System.out.println("失败 " + FAILURES.size() + " / " + checks + " 项：");
        FAILURES.forEach(line -> System.out.println("  ✗ " + line));
        System.exit(1);
    }

    // ------------------------------------------------ 小工具
    private interface Block {
        void run() throws Exception;
    }

    private static void run(String name, Block block) {
        group = name;
        System.out.print("· " + name + " … ");
        int before = FAILURES.size();
        try {
            block.run();
        } catch (Throwable unexpected) {
            FAILURES.add(name + "：抛出未预期异常 " + unexpected);
            unexpected.printStackTrace(System.out);
        }
        System.out.println(FAILURES.size() == before ? "ok" : "有问题");
    }

    private static void check(boolean ok, String what) {
        checks++;
        if (!ok) {
            FAILURES.add(group + "：" + what);
        }
    }

    private static void eq(Object actual, Object expected, String what) {
        check(java.util.Objects.equals(actual, expected),
                what + "：期望 " + expected + "，实际 " + actual);
    }

    private static void near(int actual, int expected, int tolerance, String what) {
        check(Math.abs(actual - expected) <= tolerance,
                what + "：期望 " + expected + "±" + tolerance + "，实际 " + actual);
    }

    private static void throwsSomething(Class<?> expected, String fragment, ThrowingBlock block, String what) {
        checks++;
        try {
            block.run();
            FAILURES.add(group + "：" + what + " 没有抛异常（期望 " + expected.getSimpleName() + "）");
        } catch (Throwable thrown) {
            if (!expected.isInstance(thrown)) {
                FAILURES.add(group + "：" + what + " 抛的是 " + thrown.getClass().getSimpleName()
                        + " 而不是 " + expected.getSimpleName() + "：" + thrown.getMessage());
            } else if (fragment != null && !String.valueOf(thrown.getMessage()).contains(fragment)) {
                FAILURES.add(group + "：" + what + " 消息里没找到「" + fragment + "」，实际："
                        + thrown.getMessage());
            }
        }
    }

    private interface ThrowingBlock {
        void run() throws Exception;
    }

    private static Drawing drawingOf(Shape... shapes) {
        Drawing drawing = new Drawing();
        List<Shape> list = new ArrayList<>(List.of(shapes));
        drawing.replaceAll(list);
        return drawing;
    }

    // ------------------------------------------------ 模型
    private static void testModel() {
        RectShape rect = new RectShape(80, 60, 20, 10, Color.RED);
        eq(rect.x(), 20, "反向拖拽时左上角取小值");
        eq(rect.y(), 10, "同上，y");
        eq(rect.width(), 60, "宽度取绝对值");
        eq(rect.height(), 50, "高度取绝对值");

        Shape moved = rect.translatedBy(5, -3);
        check(moved != rect, "translatedBy 必须返回新实例（形状不可变）");
        eq(rect.x(), 20, "平移不改变原对象");
        eq(((RectShape) moved).x(), 25, "新对象才带位移");

        LineShape line = new LineShape(10, 10, 10, 50, Color.BLUE);
        check(line.contains(10, 30), "线段正上中的点应命中");
        check(line.contains(11, 30), "2 像素宽 + 容差：旁边一点也算命中");
        check(!line.contains(30, 30), "远离线段的点不该命中");
        check(!line.contains(0, 0), "端点外侧远处不命中");
        check(new LineShape(30, 30, 30, 30, Color.BLACK).contains(31, 31), "退化成一个点的线段仍可在附近命中");

        RectShape box = new RectShape(10, 10, 40, 40, Color.BLACK);
        check(box.contains(25, 25), "空心矩形内部也应可选中（不然用户要点边线）");
        check(!box.contains(60, 60), "矩形外不命中");
        check(box.contains(41, 25), "右边界外一像素仍在容差内");

        EllipseShape circle = new EllipseShape(0, 0, 40, 40, Color.BLACK);
        check(circle.contains(20, 20), "椭圆中心命中");
        check(circle.contains(6, 6), "45° 方向上紧贴椭圆边框的点应命中");
        check(!circle.contains(1, 1), "外接框角落离椭圆边界还差 3 个像素，不该命中");
        check(!circle.contains(39, 1), "外接框角落（椭园外）不应命中");

        LineShape same1 = new LineShape(1, 2, 3, 4, Color.MAGENTA);
        LineShape same2 = new LineShape(1, 2, 3, 4, Color.MAGENTA);
        eq(same1, same2, "内容相同的形状应相等");
        eq(same1.hashCode(), same2.hashCode(), "相等对象的 hashCode 必须一致（放 HashSet 才发现）");
        check(!same1.equals(new LineShape(1, 2, 3, 4, Color.CYAN)), "颜色不同则不等");
        check(!same1.equals(new RectShape(1, 2, 3, 4, Color.MAGENTA)), "类型不同则不等");
        check(new java.util.HashSet<Shape>(List.of(same1, same2)).size() == 1,
                "HashSet 去重依赖 equals+hashCode 同时正确");

        throwsSomething(IllegalArgumentException.class, "颜色",
                () -> new RectShape(0, 0, 1, 1, null), "颜色为 null 要拒");
        eq(rect.serialize(), "rect 20 10 60 50 #FF0000", "序列化字段顺序与颜色写法");
    }

    // ------------------------------------------------ 文档
    private static void testDrawing() {
        Drawing drawing = new Drawing();
        check(drawing.isEmpty(), "新文档为空");
        eq(drawing.indexOfNearest(0, 0), -1, "空文档点哪里都是未命中");

        Shape bottom = new RectShape(0, 0, 20, 20, Color.RED);
        Shape top = new RectShape(0, 0, 20, 20, Color.BLUE);
        drawing.insert(0, bottom);
        drawing.insert(1, top);
        eq(drawing.indexOfNearest(5, 5), 1, "重叠时选中最上面那个（列表尾部）");
        drawing.removeAt(1);
        eq(drawing.indexOfNearest(5, 5), 0, "删掉上层后轮到下层");

        Drawing another = new Drawing();
        another.insert(0, bottom);
        another.insert(1, top);
        another.insert(2, new LineShape(100, 100, 130, 130, Color.GREEN));
        another.select(1);
        another.removeAt(0);
        eq(another.selection(), 0, "删掉选中项之下的形状时，选中索引整体前移");
        another.removeAt(0);
        eq(another.selection(), -1, "删掉当前选中项则取消选中");

        Drawing clamped = drawingOf(bottom);
        clamped.select(99);
        eq(clamped.selection(), -1, "越界选择按取消处理，不抛异常（点空白就是这个效果）");
        clamped.select(0);
        eq(clamped.selection(), 0, "合法选择生效");

        // 监听器：回调里取消订阅是最常见写法，不能在遍历时把自己迭代会
        Drawing live = new Drawing();
        final int[] fired = {0};
        Drawing.Listener oneShot = new Drawing.Listener() {
            @Override
            public void drawingChanged(Drawing changed) {
                fired[0]++;
                changed.removeListener(this);
            }
        };
        live.addListener(oneShot);
        live.insert(0, bottom);
        live.insert(0, top);
        eq(fired[0], 1, "回调里取消订阅：只通知一次且不抛异常");

        Drawing big = new Drawing();
        List<Shape> many = new ArrayList<>();
        for (int i = 0; i < Drawing.MAX_SHAPES + 1; i++) {
            many.add(new RectShape(i, i, i + 1, i + 1, Color.BLACK));
        }
        throwsSomething(IllegalStateException.class, "上限",
                () -> big.replaceAll(many), "形状数超上限要拒");
        eq(big.size(), 0, "被拒的替换不应改坏文档");

        Drawing bounds = drawingOf(new LineShape(-5, -5, 15, 15, Color.BLACK),
                new RectShape(50, 50, 60, 60, Color.BLACK));
        eq(bounds.rawBounds().x, -5, "内容范围含负坐标");
        eq(bounds.rawBounds().width, 65, "内容宽度");
        check(bounds.contentBounds().width > bounds.rawBounds().width,
                "contentBounds 额外留出线宽与容差");
        eq(new Drawing().contentBounds().width, 0, "空文档的范围是 0×0");
    }

    // ------------------------------------------------ 命令
    private static void testCommands() {
        Drawing drawing = new Drawing();
        CommandHistory history = new CommandHistory();
        check(!history.canUndo() && !history.canRedo(), "新历史两边都空");

        RectShape rect = new RectShape(0, 0, 10, 10, Color.RED);
        history.run(new AddShapeCommand(drawing, rect));
        eq(drawing.size(), 1, "添加生效");
        check(history.canUndo(), "有得撤销");
        eq(history.peekUndo(), "添加 rect", "描述文本");
        check(!history.canRedo(), "刚做完动作没有可重做");

        history.undo();
        eq(drawing.size(), 0, "撤销回到空文档");
        check(history.canRedo(), "撤销之后可重做");
        history.redo();
        eq(drawing.size(), 1, "重做恢复");
        eq(drawing.get(0), rect, "重做的是同一个形状");

        history.run(new MoveShapeCommand(drawing, 0, 5, 7));
        eq(((RectShape) drawing.get(0)).x(), 5, "移动改了位置");
        eq(((RectShape) drawing.get(0)).y(), 7, "移动改了位置 y");
        history.undo();
        eq(((RectShape) drawing.get(0)).x(), 0, "撤销移动回到原位（拿回旧实例）");
        history.redo();
        eq(((RectShape) drawing.get(0)).x(), 5, "重做移动再次生效");

        history.undo();
        history.undo();
        eq(drawing.size(), 0, "连续撤销回到最初始状态");
        eq(history.undoDepth(), 0, "撤销栈空了");
        check(!history.canUndo(), "canUndo 与栈深度一致");

        // 新命令清空 redo：不然后面的重做会把旧世界的操作贴到新世界上
        history.run(new AddShapeCommand(drawing, new LineShape(0, 0, 5, 5, Color.BLUE)));
        history.undo();
        check(history.canRedo(), "撤销后有可重做");
        history.run(new AddShapeCommand(drawing, new EllipseShape(0, 0, 8, 8, Color.GREEN)));
        check(!history.canRedo(), "执行新命令必须清空 redo 栈");

        // 深度上限
        CommandHistory tiny = new CommandHistory(3);
        Drawing many = new Drawing();
        for (int i = 0; i < 5; i++) {
            tiny.run(new AddShapeCommand(many, new RectShape(i, i, i + 1, i + 1, Color.BLACK)));
        }
        eq(tiny.undoDepth(), 3, "历史只留最近的 3 条");
        eq(tiny.droppedCount(), 2, "被丢掉的两条要能被统计到（UI 要如实告诉用户）");
        tiny.undo();
        tiny.undo();
        tiny.undo();
        eq(many.size(), 2, "只能撤销到保留的历史边界");
        eq(tiny.droppedCount(), 2, "计数不会因撤销而消失");
        check(many.get(0).equals(new RectShape(0, 0, 1, 1, Color.BLACK)),
                "剩下的是最早那两个形状：丢的确实是最老的");

        throwsSomething(IllegalArgumentException.class, "至少 1",
                () -> new CommandHistory(0), "历史深度为 0 要拒");

        // 删除命令的位置语义
        Drawing three = new Drawing();
        three.replaceAll(List.of(
                new RectShape(0, 0, 1, 1, Color.RED),
                new RectShape(0, 0, 2, 2, Color.GREEN),
                new RectShape(0, 0, 3, 3, Color.BLUE)));
        CommandHistory local = new CommandHistory();
        local.run(new RemoveShapeCommand(three, 1));
        eq(three.size(), 2, "删中间一个");
        eq(((RectShape) three.get(1)).width(), 3, "后面的补上来");
        local.undo();
        eq(three.size(), 3, "撤销放回原位");
        eq(((RectShape) three.get(1)).width(), 2, "放回的还是原来那个位置");

        // AddShapeCommand 撤销时的自检：文档被别处改过就该报错而不是删错东西
        Drawing guarded = new Drawing();
        CommandHistory guard = new CommandHistory();
        RectShape shape = new RectShape(0, 0, 4, 4, Color.RED);
        guard.run(new AddShapeCommand(guarded, shape));
        guarded.replaceAll(List.of(new RectShape(9, 9, 10, 10, Color.BLACK)));
        throwsSomething(RuntimeException.class, "找不到", guard::undo, "内容被整体换掉后撤销必须自检失败");

        // 空移动不做成命令（否则撤销一次没反应，用户以为坏了）
        MoveShapeCommand noOp = new MoveShapeCommand(drawingOf(new RectShape(0, 0, 1, 1, Color.RED)),
                0, 0, 0);
        check(noOp.isNoOp(), "dx=dy=0 的移动应被识别为无操作");
    }

    // ------------------------------------------------ 文件
    private static void testFileFormat() {
        Drawing drawing = new Drawing();
        drawing.replaceAll(List.of(
                new LineShape(-3, 4, 12, -8, new Color(0x10, 0x20, 0x30)),
                new RectShape(1, 2, 30, 40, Color.RED),
                new EllipseShape(5, 6, 70, 80, new Color(0, 0, 0))));
        String text = DrawingFormat.serialize(drawing);
        check(text.startsWith("pad 1\n"), "文件头");
        try {
            Drawing back = DrawingFormat.parse(text);
            eq(back.shapes(), drawing.shapes(), "写出再读回必须完全相等（含负坐标）");
        } catch (DrawingFormatException unexpected) {
            FAILURES.add("往返解析失败：" + unexpected.getMessage() + " " + unexpected.problems());
        }
        checks++;

        for (String bad : List.of(
                "",
                "pad 2\nrect 0 0 1 1 #FFFFFF\n",
                "rect 0 0 1 1 #FFFFFF\n",
                "pad 1\nsquare 0 0 1 1 #FFFFFF\n",
                "pad 1\nrect 0 0 1 #FFFFFF\n",
                "pad 1\nrect 0 0 1 1 white\n",
                "pad 1\nrect 0 0 1 1 #GGGGGG\n",
                "pad 1\nrect 0 0 1 1 #FFFFFF extra\n",
                "pad 1\nline a b c d #FFFFFF\n",
                "pad 1\nrect 0 0 -1 -1 #FFFFFF\n",
                "pad 1\nellipse 0 0 200000 1 #FFFFFF\n",
                "pad 1\nline 9999999 0 0 0 #FFFFFF\n",
                "pad x\n")) {
            checks++;
            try {
                DrawingFormat.parse(bad);
                FAILURES.add("group:坏文件被接受：" + bad.replace("\n", "\\n"));
            } catch (DrawingFormatException expected) {
                check(!expected.problems().isEmpty(), "坏文件要有具体问题描述：" + bad);
            }
        }

        // 一次报全 + 行号
        checks++;
        try {
            DrawingFormat.parse("pad 1\nrect 0 0 1 1 nope\n\n# 注释\nline 1 2 3\nellipse 0 0 1 1 #00FF00\n");
            FAILURES.add("多问题文件应该被拒");
        } catch (DrawingFormatException bad) {
            eq(bad.problems().size(), 2, "两处坏行都要报出来");
            check(bad.problems().get(0).contains("第 2 行"), "第一条带行号 2");
            check(bad.problems().get(1).contains("第 5 行"), "第二条带行号 5（空行与注释不占编号）");
        }

        try {
            eq(DrawingFormat.parse("pad 1\r\nrect 0 0 1 1 #FFFFFF\r\n").size(), 1, "CRLF 文件可读");
            eq(DrawingFormat.parse("pad 1\rrect 0 0 1 1 #FFFFFF\r").size(), 1, "裸 CR 文件可读");
            eq(DrawingFormat.parse("pad 1\n   \n  # 缩进注释\nrect 0 0 1 1 #FFFFFF").size(), 1,
                    "空白行与注释行忽略");
        } catch (DrawingFormatException unexpected) {
            FAILURES.add("合法变体被拒：" + unexpected.problems());
        }
        checks += 3;

        // 形状数上限
        StringBuilder huge = new StringBuilder("pad 1\n");
        for (int i = 0; i < Drawing.MAX_SHAPES + 5; i++) {
            huge.append("rect 0 0 1 1 #FFFFFF\n");
        }
        checks++;
        try {
            DrawingFormat.parse(huge.toString());
            FAILURES.add("超过形状数上限的文件被接受");
        } catch (DrawingFormatException expected) {
            check(expected.problems().stream().anyMatch(p -> p.contains("上限")), "要说明是上限问题");
        }
    }

    // ------------------------------------------------ 存取防线
    private static void testStore() throws Exception {
        Path root = Files.createTempDirectory("b14-store");
        SafeStore store = new SafeStore(root);
        store.save("测试.pad", "pad 1\n");
        check(Files.exists(root.resolve("测试.pad")), "中文文件名能写");
        eq(store.load("测试.pad"), "pad 1\n", "写进去的字节读回来一致");
        store.save("x.pad", "pad 1\nrect 0 0 1 1 #FFFFFF\n");
        eq(store.listDocuments(), List.of("x.pad", "测试.pad"), "列表按名称排序");
        check(!Files.exists(root.resolve("x.pad.tmp")), "原子写完不留临时文件");

        for (String bad : List.of("../escape.pad", "a/b.pad", "a\\b.pad", "/abs/path.pad",
                "C:\\windows\\x.pad", "..pad", "no-extension", "x.txt", "con.pad", "NUL.pad",
                "with space.pad", " 空格.pad", "点.PAD", "a".repeat(70) + ".pad",
                "\u0001x.pad", ".hidden.pad", "emoji😀.pad", "")) {
            throwsSomething(IOException.class, null, () -> store.resolve(bad), "拒绝文件名 " + bad);
        }
        // 中文名是允许的（上面那条被拒是因为大写 .PAD，不是因为中文）
        try {
            check(store.resolve("画图.pad").endsWith("画图.pad"), "中文文件名应当放行");
        } catch (IOException unexpected) {
            FAILURES.add("中文名被误拒：" + unexpected.getMessage());
        }
        checks++;
        throwsSomething(IOException.class, "必须以", () -> store.resolveExport("x.pad"),
                "导出文件名要提示必须以 .png 结尾");
        throwsSomething(IOException.class, "必须以", () -> store.resolve("x.exe"), "文档文件名要提示必须以 .pad 结尾");
        check(store.resolve("ok.pad").startsWith(root.toAbsolutePath()), "合法路径落在根目录内");

        throwsSomething(IOException.class, "过大",
                () -> store.save("big.pad", "x".repeat(DrawingFormat.MAX_FILE_BYTES + 10)),
                "写入超大文件要拒");
        Path outside = root.resolve("evil.pad");
        Files.writeString(outside, "pad 1\n");
        throwsSomething(IOException.class, "符号链接", () -> {
            Path link = root.resolve("link.pad");
            Files.deleteIfExists(link);
            Files.createSymbolicLink(link, outside);
            store.load("link.pad");
        }, "符号链接指向目录内的文件也拒绝（同一目录内不算越界，但仍是链接）");
    }

    // ------------------------------------------------ 渲染像素
    private static BufferedImage render(Drawing drawing, Shape preview, int w, int h) {
        BufferedImage image = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = image.createGraphics();
        try {
            Painter.render(drawing, preview, g, w, h);
        } finally {
            g.dispose();
        }
        return image;
    }

    private static int countColor(BufferedImage image, Color color, int x0, int y0, int x1, int y1) {
        int rgb = color.getRGB();
        int found = 0;
        for (int y = Math.max(0, y0); y < Math.min(image.getHeight(), y1); y++) {
            for (int x = Math.max(0, x0); x < Math.min(image.getWidth(), x1); x++) {
                if (image.getRGB(x, y) == rgb) {
                    found++;
                }
            }
        }
        return found;
    }

    private static void testRender() {
        BufferedImage blank = render(new Drawing(), null, 120, 90);
        eq(countColor(blank, Painter.BACKGROUND, 0, 0, 120, 90), 120 * 90, "空白画布全是背景色");

        Drawing drawing = drawingOf(new RectShape(10, 10, 40, 30, Color.RED));
        BufferedImage image = render(drawing, null, 120, 90);
        check(countColor(image, Color.RED, 5, 5, 60, 55) > 60, "红色矩形画出了轮廓像素");
        eq(countColor(image, Color.RED, 25, 25, 26, 26), 0, "空心矩形中间仍是背景色");
        eq(countColor(image, Color.RED, 60, 60, 120, 90), 0, "不该把颜色画到别处");

        BufferedImage withPreview = render(new Drawing(),
                new LineShape(5, 5, 60, 60, Color.BLUE), 120, 90);
        check(countColor(withPreview, Color.BLUE, 0, 0, 120, 90) > 30, "预览形状也会被画出来");

        Drawing selected = drawingOf(new EllipseShape(20, 20, 30, 30, Color.BLACK));
        selected.select(0);
        BufferedImage halo = render(selected, null, 120, 90);
        check(countColor(halo, Painter.SELECTION, 0, 0, 120, 90) > 20, "选中时画了选择框");
        selected.select(-1);
        eq(countColor(render(selected, null, 120, 90), Painter.SELECTION, 0, 0, 120, 90), 0,
                "取消选中后蓝框消失");

        // 撤销之后像素必须真的消失
        Drawing doc = new Drawing();
        CommandHistory history = new CommandHistory();
        history.run(new AddShapeCommand(doc, new RectShape(4, 4, 20, 20, Color.MAGENTA)));
        check(countColor(render(doc, null, 60, 60), Color.MAGENTA, 0, 0, 60, 60) > 20, "画完有像素");
        history.undo();
        eq(countColor(render(doc, null, 60, 60), Color.MAGENTA, 0, 0, 60, 60), 0, "撤销后像素消失");
    }

    // ------------------------------------------------ 交互
    private static void testInteraction() {
        Drawing drawing = new Drawing();
        CommandHistory history = new CommandHistory();
        PaintCanvas canvas = new PaintCanvas(drawing, history);
        canvas.setTool(Tool.RECT);
        canvas.setColor(Color.RED);

        canvas.pressAt(10, 10, false);
        canvas.dragTo(30, 25);
        check(canvas.preview() != null, "拖拽过程中有预览");
        eq(drawing.size(), 0, "拖拽过程中还没改文档（一次拖拽只产一条命令）");
        check(canvas.releaseAt(30, 25), "松手提交了命令");
        eq(drawing.size(), 1, "文档里多了一个形状");
        eq(((RectShape) drawing.get(0)).width(), 20, "宽度按按下点与松开点算");
        eq(((RectShape) drawing.get(0)).x(), 10, "左上角规范化");
        check(canvas.preview() == null, "松手后预览清空");
        eq(drawing.selection(), 0, "新加的形状成为选中项");

        canvas.pressAt(50, 50, false);
        check(!canvas.releaseAt(51, 51), "小于阈值的拖拽算误点，不产生形状");
        eq(drawing.size(), 1, "误点没有改文档");

        canvas.setTool(Tool.SELECT);
        canvas.pressAt(15, 15, false);
        eq(drawing.selection(), 0, "选择工具点中形状");
        canvas.dragTo(35, 45);
        canvas.releaseAt(35, 45);
        eq(((RectShape) drawing.get(0)).x(), 30, "拖动 20×30 后左上角跟着走");
        eq(((RectShape) drawing.get(0)).y(), 40, "y 同理");
        eq(history.undoDepth(), 2, "移动是一条独立命令");
        history.undo();
        eq(((RectShape) drawing.get(0)).x(), 10, "撤销移动回到原位");

        canvas.pressAt(15, 15, false);
        canvas.releaseAt(15, 15);
        eq(drawing.selection(), 0, "单击也能选中");
        check(canvas.pressKey(java.awt.event.KeyEvent.VK_DELETE, false, false), "Delete 删除选中项");
        eq(drawing.size(), 0, "删除生效");
        check(canvas.pressKey(java.awt.event.KeyEvent.VK_DELETE, false, false) == false,
                "没有选中时按 Delete 什么都不该发生");
        history.undo();
        eq(drawing.size(), 1, "删除可撤销");
        check(canvas.pressKey(java.awt.event.KeyEvent.VK_Z, true, false), "Ctrl+Z 走撤销");
        check(canvas.pressKey(java.awt.event.KeyEvent.VK_Z, true, true), "Ctrl+Shift+Z 走重做");
        check(canvas.pressKey(java.awt.event.KeyEvent.VK_Y, true, false), "Ctrl+Y 走重做");
        check(!canvas.pressKey(java.awt.event.KeyEvent.VK_A, true, false), "其它快捷键不处理");

        // 预览用不同工具产出不同形状：工厂是否真的生效
        canvas.setTool(Tool.ELLIPSE);
        canvas.pressAt(0, 0, false);
        canvas.dragTo(20, 20);
        check(canvas.preview() instanceof EllipseShape, "椭圆工具产出椭圆预览");
        canvas.setTool(Tool.LINE);
        canvas.pressAt(0, 0, false);
        canvas.dragTo(20, 20);
        check(canvas.preview() instanceof LineShape, "线工具产出线段预览");
        canvas.releaseAt(20, 20);
        check(canvas.pressKey(java.awt.event.KeyEvent.VK_ESCAPE, false, false), "Esc 有响应");
        eq(drawing.selection(), -1, "Esc 取消选中");

        throwsSomething(IllegalArgumentException.class, "不是绘制工具",
                () -> ShapeFactory.create(Tool.SELECT, 0, 0, 1, 1, Color.BLACK),
                "选择工具不能创建形状");
        throwsSomething(IllegalArgumentException.class, "null",
                () -> canvas.setTool(null), "工具为 null 要拒");
    }

    /** 快照栈必须和真实历史用同一个深度，否则两边"能撤销到多远"不一样，比较就失去意义。 */
    private static void trim(List<List<Shape>> snapshots) {
        while (snapshots.size() > FUZZ_HISTORY_DEPTH) {
            snapshots.remove(0);
        }
    }

    private static final int FUZZ_HISTORY_DEPTH = 20;

    // ------------------------------------------------ 随机操作 vs 快照模型
    /**
     * 影子模型用"整体快照栈"实现撤销，与命令式的实现完全不同一条路。
     * 两边跑同一串操作，形状列表必须每一步都相等——撤销栈与文档失同步是最难手工发现的 bug。
     */
    private static void testFuzzAgainstSnapshots() {
        Random rng = new Random(4242);
        for (int round = 0; round < 20; round++) {
            Drawing drawing = new Drawing();
            CommandHistory history = new CommandHistory(FUZZ_HISTORY_DEPTH);
            PaintCanvas canvas = new PaintCanvas(drawing, history);
            List<Shape> shadow = new ArrayList<>();
            List<List<Shape>> undoSnapshots = new ArrayList<>();
            List<List<Shape>> redoSnapshots = new ArrayList<>();

            for (int step = 0; step < 300; step++) {
                int action = rng.nextInt(6);
                if (action == 0) {                                   // 撤销
                    if (!undoSnapshots.isEmpty()) {
                        redoSnapshots.add(new ArrayList<>(shadow));
                        shadow.clear();
                        shadow.addAll(undoSnapshots.remove(undoSnapshots.size() - 1));
                        history.undo();
                    }
                } else if (action == 1 && !redoSnapshots.isEmpty()) {  // 重做
                    undoSnapshots.add(new ArrayList<>(shadow));
                    shadow.clear();
                    shadow.addAll(redoSnapshots.remove(redoSnapshots.size() - 1));
                    history.redo();
                } else if (action == 2 || action == 3) {              // 画一个
                    Tool tool = switch (rng.nextInt(3)) {
                        case 0 -> Tool.LINE;
                        case 1 -> Tool.RECT;
                        default -> Tool.ELLIPSE;
                    };
                    canvas.setTool(tool);
                    int x1 = rng.nextInt(200), y1 = rng.nextInt(200);
                    int x2 = x1 + rng.nextInt(40) - 20, y2 = y1 + rng.nextInt(40) - 20;
                    undoSnapshots.add(new ArrayList<>(shadow));
                    redoSnapshots.clear();
                    trim(undoSnapshots);
                    canvas.pressAt(x1, y1, false);
                    canvas.dragTo(x2, y2);
                    boolean committed = canvas.releaseAt(x2, y2);
                    if (committed) {
                        shadow.add(ShapeFactory.create(tool, x1, y1, x2, y2, canvas.color()));
                    } else {
                        undoSnapshots.remove(undoSnapshots.size() - 1);
                    }
                } else if (action == 4) {                             // 选中并拖动
                    canvas.setTool(Tool.SELECT);
                    int x = rng.nextInt(200), y = rng.nextInt(200);
                    canvas.pressAt(x, y, false);
                    int selected = drawing.selection();
                    int dx = rng.nextInt(20) - 10, dy = rng.nextInt(20) - 10;
                    boolean moved = canvas.releaseAt(x + dx, y + dy);
                    if (moved && selected >= 0 && selected < shadow.size()) {
                        undoSnapshots.add(new ArrayList<>(shadow));
                        redoSnapshots.clear();
                        trim(undoSnapshots);
                        shadow.set(selected, shadow.get(selected).translatedBy(dx, dy));
                    }
                } else {                                              // 删除选中
                    int selected = drawing.selection();
                    if (selected >= 0) {
                        undoSnapshots.add(new ArrayList<>(shadow));
                        redoSnapshots.clear();
                        trim(undoSnapshots);
                        check(canvas.pressKey(java.awt.event.KeyEvent.VK_DELETE, false, false),
                                "有选中项时 Delete 必须处理");
                        shadow.remove(selected);
                    }
                }
                if (!shadow.equals(drawing.shapes())) {
                    FAILURES.add("影子模型在第 " + round + " 轮第 " + step + " 步与文档失同步："
                            + " 期望 " + shadow + " 实际 " + drawing.shapes());
                    return;
                }
                checks++;
            }
            check(drawing.size() == shadow.size(), "每轮结束形状数一致");
        }
    }
}
