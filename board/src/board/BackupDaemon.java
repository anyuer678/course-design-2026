package board;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import javax.swing.SwingUtilities;

import paint.io.SafeStore;
import paint.ui.PaintFrame;

/**
 * 画板服务（产品层）：目录守护 + 探活口 + 可选窗口。
 *
 * <p><b>两种形态，一个入口</b>：
 * <ul>
 *   <li>默认 = <b>守护</b>：盯着数据目录里的 .pad 文件，谁变了就把新版本备份进
 *       backups/&lt;文档名&gt;/（用户在任意 B14 窗口里点保存，守护这边自动接住）；
 *       同时开一个<b>探活口</b>——连上就回一行状态（在线=TCP 连得上，与门户同一口径）；
 *   <li>{@code --window} = 守护之上再开 B14 的真窗口（复用 {@link PaintFrame}，
 *       不重写一行业务），并给窗口的文档挂 {@link AutoBackup}——<b>没保存的工作</b>
 *       也有节流备份，这是 B14 明说没有的能力。</li>
 * </ul>
 *
 * <p><b>被门户管理（如实声明）</b>：{@code --parent-pid} 是父进程看门狗——Studio
 * 停止 = 终止启动器（Python），本进程每秒确认父进程还活着，没了就自觉退出，
 * 不留孤儿进程、不留半开的探活口。独立运行（不传该参数）时没有此行为。
 *
 * <p>数据目录沿用 B14 的约定：{@code -Dpaint.data=目录}（默认 ./data）。
 */
public final class BackupDaemon implements AutoCloseable {

    private final Path dataRoot;
    private final BackupStore store;
    private final long intervalMillis;
    private final ServerSocket server;
    private final AtomicInteger backups = new AtomicInteger();
    private final AtomicInteger corrupt = new AtomicInteger();
    private volatile boolean running = true;

    public BackupDaemon(Path dataRoot, long intervalMillis, int keep, int port) throws IOException {
        this.dataRoot = dataRoot.toAbsolutePath().normalize();
        this.store = new BackupStore(this.dataRoot, keep);
        this.intervalMillis = Math.max(50, intervalMillis);
        this.server = new ServerSocket();
        server.bind(new InetSocketAddress("127.0.0.1", port));
    }

    public int port() {
        return server.getLocalPort();
    }

    // ---------------------------------------------------------------- 探活口

    private Thread startAcceptor() {
        Thread acceptor = new Thread(this::acceptLoop, "board-liveness");
        acceptor.setDaemon(true);
        acceptor.start();
        return acceptor;
    }

    private void acceptLoop() {
        while (running) {
            try {
                Socket client = server.accept();
                handleProbe(client);
            } catch (IOException acceptFailed) {
                if (running) {
                    System.out.println("[liveness] " + acceptFailed.getMessage());
                    System.out.flush();
                }
            }
        }
    }

    private void handleProbe(Socket client) {
        try (client) {
            // 每次探活现算账：docs/backups/corrupt 都是活数，不是启动时拍死的老值
            int docCount = new SafeStore(dataRoot).listDocuments().size();
            String reply = "BOARD " + server.getLocalPort() + " OK docs=" + docCount
                    + " backups=" + backups.get() + " corrupt=" + corrupt.get() + "\n";
            try {
                client.getOutputStream().write(reply.getBytes(StandardCharsets.UTF_8));
                client.getOutputStream().flush();
            } catch (IOException peerGone) {
                // 探活方连上就走也是合法语义：不撒谎、不报错
            }
        } catch (IOException handled) {
            // accept 的套接字处理失败不影响服务
        }
    }

    // ---------------------------------------------------------------- 目录守护

    private void pollLoop() {
        SafeStore docs = new SafeStore(dataRoot);
        Map<String, long[]> seen = new HashMap<>();      // name -> {mtimeMillis, size}
        while (running) {
            try {
                List<String> names = docs.listDocuments();
                for (String name : names) {
                    Path path = docs.resolve(name);
                    long mtime = Files.getLastModifiedTime(path).toMillis();
                    long size = Files.size(path);
                    long[] prev = seen.get(name);
                    if (prev != null && prev[0] == mtime && prev[1] == size) {
                        continue;
                    }
                    seen.put(name, new long[]{mtime, size});
                    backUpOne(docs, name);
                }
            } catch (IOException pollProblem) {
                throw new UncheckedIOException(pollProblem);
            }
            sleepQuietly(intervalMillis);
        }
    }

    /** 首次见到也算变更：守护启动即给现有文档兜一份（备份的承诺不挑时机）。 */
    private void backUpOne(SafeStore docs, String name) {
        try {
            String content = docs.load(name);
            String stem = name.substring(0, name.length() - SafeStore.EXTENSION.length());
            int count = store.write(stem, content);
            backups.incrementAndGet();
            System.out.println("[backup] " + name + " -> backups/" + stem + "（" + count + " 份）");
        } catch (IOException badContent) {
            corrupt.incrementAndGet();
            System.out.println("[corrupt] 跳过 " + name + "：" + badContent.getMessage());
        }
        System.out.flush();
    }

    private static void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }

    // ---------------------------------------------------------------- 看门狗

    private void startWatchdog(long parentPid) {
        Thread watchdog = new Thread(() -> {
            while (true) {
                boolean parentAlive = ProcessHandle.of(parentPid)
                        .map(ProcessHandle::isAlive)
                        .orElse(false);
                if (!parentAlive) {
                    System.out.println("[watchdog] 父进程 " + parentPid + " 已不在，自觉退出");
                    System.out.flush();
                    System.exit(0);
                }
                sleepQuietly(1000);
            }
        }, "board-watchdog");
        watchdog.setDaemon(true);
        watchdog.start();
    }

    @Override
    public void close() {
        running = false;
        try {
            server.close();
        } catch (IOException ignored) {
            // 关一个已关的套接字不是错误
        }
    }

    // ---------------------------------------------------------------- 入口

    public static void main(String[] args) throws Exception {
        int port = 8023;
        long interval = 2000;
        int keep = 20;
        long parentPid = -1;
        boolean window = false;
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--port" -> port = Integer.parseInt(args[++i]);
                case "--interval" -> interval = Long.parseLong(args[++i]);
                case "--keep" -> keep = Integer.parseInt(args[++i]);
                case "--parent-pid" -> parentPid = Long.parseLong(args[++i]);
                case "--window" -> window = true;
                case "--help", "-h" -> {
                    System.out.println("用法: java board.BackupDaemon [--port 8023] [--interval 2000]"
                            + " [--keep 20] [--window] [--parent-pid pid]");
                    System.out.println("  默认   目录守护 + 探活口（数据目录里的 .pad 变更 → 自动备份）");
                    System.out.println("  --window  再开 B14 真窗口，并给未保存的工作挂节流自动备份");
                    System.out.println("  数据目录: -Dpaint.data=目录 （默认 ./data）");
                    return;
                }
                default -> {
                    System.err.println("不认识的参数：" + args[i] + "（--help 看用法）");
                    System.exit(2);
                }
            }
        }
        String configured = System.getProperty("paint.data");
        Path dataRoot = Paths.get(configured == null ? "data" : configured);
        if (window && java.awt.GraphicsEnvironment.isHeadless()) {
            System.err.println("当前环境无显示器（headless），--window 开不了窗口；"
                    + "守护模式照常可用（去掉 --window 再跑）");
            System.exit(2);
        }
        BackupDaemon daemon = new BackupDaemon(dataRoot, interval, keep, port);
        if (parentPid >= 0) {
            daemon.startWatchdog(parentPid);
        }
        System.out.println("BOARD LISTENING " + daemon.port());
        System.out.println("数据目录 " + dataRoot.toAbsolutePath() + "；备份桶 keep=" + keep
                + "；轮询 " + interval + "ms");
        System.out.flush();
        daemon.startAcceptor();
        if (window) {
            SafeStore docs = new SafeStore(dataRoot);
            BackupStore store = new BackupStore(dataRoot, keep);
            SwingUtilities.invokeLater(() -> {
                PaintFrame frame = new PaintFrame(docs);
                // AutoBackup 挂在窗口的真实文档上：未保存的工作也有节流备份（EDT 序列化）
                new AutoBackup(frame.drawing(), store, "autosave", 3000);
                frame.setVisible(true);
            });
        }
        daemon.pollLoop();                               // 主线程就是守护循环
    }
}
