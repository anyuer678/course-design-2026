package board;

import java.awt.Color;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.Locale;

import javax.imageio.ImageIO;

import paint.command.CommandHistory;
import paint.io.DrawingFormat;
import paint.io.SafeStore;
import paint.model.Drawing;
import paint.model.Shape;
import paint.ui.PaintCanvas;
import paint.ui.Tool;

/**
 * 无头驱动口（产品层）：一条脚本跑完"画 → 存 → 备份 → 恢复 → 导出"，全程不开窗口。
 *
 * <p>给两类人用：<b>自动化测试</b>（Python 测试驱动本类，断言 JSON 行与磁盘产物）和
 * <b>脚本化演示</b>（远程/CI 环境证明引擎与备份链路活着）。所有绘图走
 * {@link PaintCanvas} 的真实交互语义（pressAt/dragTo/releaseAt——阈值、规范化、
 * 撤销栈全继承 B14），文件全走 {@link SafeStore}/{@link DrawingFormat}——
 * <b>引擎零重写</b>，本类只是把零件摆上操作台。
 *
 * <p>输出协议：每个操作成功回一行 JSON 对象（机器可断言）；出错打到 stderr
 * （error line &lt;行号&gt;: 人话）并整体退出码 2——脚本语境下首错即停，不带着错状态往下跑。
 *
 * <p>脚本语法（每行一个操作，# 开头是注释，空行忽略）：
 * <pre>
 *   tool &lt;line|rect|ellipse&gt;        换工具
 *   color &lt;#RRGGBB&gt;                 换颜色
 *   draw &lt;x1&gt; &lt;y1&gt; &lt;x2&gt; &lt;y2&gt;        按下-拖动-松手（小于阈值的误点如实报 committed=false）
 *   undo | redo | new
 *   save &lt;名.pad&gt; | open &lt;名.pad&gt;
 *   export &lt;名.png&gt;                 离屏渲染 480x360 → PNG（走 SafeStore 的导出白名单）
 *   stats                           形状数/种类/撤销深度
 *   backup-now | backup-list | backup-restore     备份桶 autosave
 *   auto-on &lt;quietMs&gt; | auto-off    挂/摘节流自动备份（auto-off 与收尾都会 flush）
 *   sleep &lt;ms&gt;
 * </pre>
 */
public final class Cli {

    private static final int EXPORT_WIDTH = 480;
    private static final int EXPORT_HEIGHT = 360;

    private final Drawing drawing = new Drawing();
    private final CommandHistory history = new CommandHistory();
    private final PaintCanvas canvas = new PaintCanvas(drawing, history);
    private final SafeStore docs;
    private final BackupStore store;
    private AutoBackup auto;

    private Cli(Path dataRoot, int keep) {
        this.docs = new SafeStore(dataRoot);
        this.store = new BackupStore(dataRoot, keep);
    }

    public static void main(String[] args) throws Exception {
        Path dataRoot = Paths.get(System.getProperty("paint.data", "data"));
        int keep = 20;
        String scriptPath = null;
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--script" -> scriptPath = args[++i];
                case "--keep" -> keep = Integer.parseInt(args[++i]);
                case "--help", "-h" -> {
                    System.out.println("用法: java board.Cli --script <文件|-> [--keep 20]");
                    System.out.println("  数据目录: -Dpaint.data=目录 （默认 ./data）；脚本语法见类注释");
                    return;
                }
                default -> {
                    System.err.println("不认识的参数：" + args[i] + "（--help 看用法）");
                    System.exit(2);
                }
            }
        }
        if (scriptPath == null) {
            System.err.println("缺 --script（error-free 退出码 0 只属于真跑了脚本的情况）");
            System.exit(2);
        }
        String text = scriptPath.equals("-")
                ? new String(System.in.readAllBytes(), StandardCharsets.UTF_8)
                : Files.readString(Paths.get(scriptPath), StandardCharsets.UTF_8);
        if (!text.isEmpty() && text.charAt(0) == '\uFEFF') {
            text = text.substring(1);                    // Windows 编辑器爱送 UTF-8 BOM：不能让它把第一个操作污染成 "?tool"
        }
        Cli cli = new Cli(dataRoot, keep);
        int exitCode = cli.run(text);
        System.out.flush();
        System.exit(exitCode);
    }

    private int run(String text) {
        int lineNumber = 0;
        try {
            for (String rawLine : text.split("\r\n|\r|\n", -1)) {
                lineNumber++;
                String line = rawLine.strip();
                if (line.isEmpty() || line.startsWith("#")) {
                    continue;
                }
                execute(lineNumber, line.split("\\s+"));
            }
        } catch (ExitFailure failure) {
            System.err.println(failure.getMessage());
            return 2;
        } finally {
            if (auto != null) {
                auto.close();                            // 收尾兜底：未落盘的 pending flush 掉
            }
        }
        return 0;
    }

    /** 首错即停：用一个小异常把"行号 + 人话"带出去（不吞错、不带病继续跑）。 */
    private void execute(int lineNumber, String[] tokens) {
        try {
            dispatch(tokens);
        } catch (Exception problem) {                    // 受检/运行时统一带行号（sleep 的中断、open 的坏文档都算）
            throw new ExitFailure("error line " + lineNumber + " (" + tokens[0] + "): "
                    + problem.getMessage());
        }
    }

    private void dispatch(String[] tokens) throws Exception {
        String op = tokens[0];
        switch (op) {
            case "tool" -> {
                canvas.setTool(Tool.valueOf(tokens[1].toUpperCase(Locale.ROOT)));
                emit("{\"op\":\"tool\",\"tool\":\"" + tokens[1].toLowerCase(Locale.ROOT) + "\"}");
            }
            case "color" -> {
                canvas.setColor(Color.decode(tokens[1]));   // 不是 #RRGGBB → 异常 → error line
                emit("{\"op\":\"color\",\"color\":\"" + tokens[1] + "\"}");
            }
            case "draw" -> {
                requireTokens(tokens, 5);
                canvas.pressAt(intAt(tokens, 1), intAt(tokens, 2), false);
                canvas.dragTo(intAt(tokens, 3), intAt(tokens, 4));
                boolean committed = canvas.releaseAt(intAt(tokens, 3), intAt(tokens, 4));
                emit("{\"op\":\"draw\",\"committed\":" + committed
                        + ",\"shapes\":" + drawing.size() + "}");
            }
            case "undo" -> emit("{\"op\":\"undo\",\"described\":\""
                    + jsonEscape(history.undo()) + "\",\"shapes\":" + drawing.size() + "}");
            case "redo" -> emit("{\"op\":\"redo\",\"described\":\""
                    + jsonEscape(history.redo()) + "\",\"shapes\":" + drawing.size() + "}");
            case "new" -> {
                drawing.replaceAll(List.of());
                history.clear();
                emit("{\"op\":\"new\",\"shapes\":0}");
            }
            case "save" -> {
                requireTokens(tokens, 2);
                String content = DrawingFormat.serialize(drawing);
                docs.save(tokens[1], content);
                emit("{\"op\":\"save\",\"name\":\"" + jsonEscape(tokens[1])
                        + "\",\"bytes\":" + content.getBytes(StandardCharsets.UTF_8).length + "}");
            }
            case "open" -> {
                requireTokens(tokens, 2);
                Drawing revived = DrawingFormat.parse(docs.load(tokens[1]));
                drawing.replaceAll(revived.shapes());
                history.clear();                        // 与 B14 的口径一致：整体换文档，撤销栈不留旧账
                emit("{\"op\":\"open\",\"name\":\"" + jsonEscape(tokens[1])
                        + "\",\"shapes\":" + drawing.size() + "}");
            }
            case "export" -> {
                requireTokens(tokens, 2);
                int bytes = exportPng(tokens[1]);
                emit("{\"op\":\"export\",\"name\":\"" + jsonEscape(tokens[1])
                        + "\",\"bytes\":" + bytes + "}");
            }
            case "stats" -> emit("{\"op\":\"stats\",\"shapes\":" + drawing.size()
                    + ",\"kinds\":\"" + kinds() + "\",\"undo\":" + history.undoDepth()
                    + ",\"redo\":" + history.redoDepth() + "}");
            case "backup-now" -> {
                int count = store.write("autosave", DrawingFormat.serialize(drawing));
                emit("{\"op\":\"backup-now\",\"bucket\":\"autosave\",\"kept\":" + count
                        + ",\"shapes\":" + drawing.size() + "}");
            }
            case "backup-list" -> {
                List<String> items = store.list("autosave");
                StringBuilder names = new StringBuilder();
                for (String item : items) {
                    names.append(names.isEmpty() ? "" : ",").append(item);
                }
                emit("{\"op\":\"backup-list\",\"bucket\":\"autosave\",\"count\":" + items.size()
                        + ",\"items\":\"" + names + "\"}");
            }
            case "backup-restore" -> {
                int shapes = store.restore("autosave", drawing);
                history.clear();                        // 恢复也是整体换内容，旧撤销账不留
                emit("{\"op\":\"backup-restore\",\"bucket\":\"autosave\",\"shapes\":" + shapes + "}");
            }
            case "auto-on" -> {
                requireTokens(tokens, 2);
                if (auto != null) {
                    auto.close();
                }
                auto = new AutoBackup(drawing, store, "autosave", longAt(tokens, 1));
                emit("{\"op\":\"auto-on\",\"bucket\":\"autosave\",\"quiet_ms\":" + longAt(tokens, 1) + "}");
            }
            case "auto-off" -> {
                if (auto != null) {
                    auto.close();
                    auto = null;
                }
                emit("{\"op\":\"auto-off\"}");
            }
            case "sleep" -> {
                requireTokens(tokens, 2);
                Thread.sleep(longAt(tokens, 1));
                emit("{\"op\":\"sleep\",\"ms\":" + longAt(tokens, 1) + "}");
            }
            default -> throw new IOException("不认识的操作：" + op + "（脚本语法见 board.Cli 类注释）");
        }
    }

    private int exportPng(String name) throws IOException {
        Path target = docs.resolveExport(name);         // 白名单/落点/保留名守卫原样复用
        BufferedImage image = new BufferedImage(EXPORT_WIDTH, EXPORT_HEIGHT,
                BufferedImage.TYPE_INT_RGB);
        var graphics = image.createGraphics();
        try {
            canvas.renderInto(graphics, EXPORT_WIDTH, EXPORT_HEIGHT);
        } finally {
            graphics.dispose();                          // create() 出来的上下文必须关（B14 的坑 4）
        }
        ImageIO.write(image, "png", target.toFile());
        return (int) Files.size(target);
    }

    private String kinds() {
        StringBuilder out = new StringBuilder();
        for (Shape shape : drawing.shapes()) {
            out.append(out.isEmpty() ? "" : ",").append(shape.kind());
        }
        return out.toString();
    }

    private static void requireTokens(String[] tokens, int needed) {
        if (tokens.length < needed) {
            throw new IllegalArgumentException(tokens[0] + " 需要 " + (needed - 1) + " 个参数");
        }
    }

    private static int intAt(String[] tokens, int index) {
        return Integer.parseInt(tokens[index]);
    }

    private static long longAt(String[] tokens, int index) {
        return Long.parseLong(tokens[index]);
    }

    private static String jsonEscape(String text) {
        StringBuilder out = new StringBuilder();
        for (char ch : text.toCharArray()) {
            if (ch == '"' || ch == '\\') {
                out.append('\\').append(ch);
            } else if (ch < 0x20) {
                out.append(String.format("\\u%04x", (int) ch));
            } else {
                out.append(ch);
            }
        }
        return out.toString();
    }

    private static void emit(String json) {
        System.out.println(json);
    }

    private static final class ExitFailure extends RuntimeException {
        ExitFailure(String message) {
            super(message);
        }
    }
}
