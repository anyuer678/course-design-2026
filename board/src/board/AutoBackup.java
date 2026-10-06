package board;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

import paint.io.DrawingFormat;
import paint.model.Drawing;

/**
 * 节流自动备份：挂在一个 {@link Drawing} 上，"改完安静 quietMillis 后"把当前文档
 * 写进备份桶。补的是 B14 明说的空白——崩溃前没保存的工作，现在总有一份。
 *
 * <p>线程模型（如实声明）：
 * <ul>
 *   <li><b>序列化在回调线程做</b>（GUI 是 EDT，测试是驱动线程）：谁持有文档状态
 *       谁序列化，避免跨线程读到改一半的形状列表——Drawing 不是线程安全的，这是自觉；</li>
 *   <li><b>落盘在单一守护线程做</b>：距上次修改满 quietMillis 才写，安静期内多次
 *       修改自然合并成一份（只写最新快照）；失败计数不打断线程（错误数如实可查，
 *       与 SensorHub 节拍线程同一纪律）；</li>
 *   <li>{@link #flush()} 同步写掉 pending（停机前兜底）；{@link #close()} = 停线程 + flush。</li>
 * </ul>
 */
public final class AutoBackup implements Drawing.Listener, AutoCloseable {

    private final BackupStore store;
    private final String bucket;
    private final long quietMillis;
    private final Object wake = new Object();
    private final AtomicReference<String> pending = new AtomicReference<>();
    private final AtomicBoolean dirty = new AtomicBoolean();
    private final AtomicLong lastChange = new AtomicLong();
    private final AtomicInteger written = new AtomicInteger();
    private final AtomicInteger errors = new AtomicInteger();
    private volatile boolean closed;
    private final Thread worker;
    private final Drawing drawing;

    public AutoBackup(Drawing drawing, BackupStore store, String bucket, long quietMillis) {
        if (quietMillis < 0) {
            throw new IllegalArgumentException("quietMillis 不能为负");
        }
        this.drawing = drawing;
        this.store = store;
        this.bucket = bucket;
        this.quietMillis = quietMillis;
        this.worker = new Thread(this::loop, "board-autobackup");
        this.worker.setDaemon(true);
        this.worker.start();
        drawing.addListener(this);
    }

    /** 回调线程（EDT/驱动线程）：立刻序列化快照并记时刻，落盘交给守护线程节流。 */
    @Override
    public void drawingChanged(Drawing changed) {
        if (closed || changed != drawing) {
            return;
        }
        pending.set(DrawingFormat.serialize(changed));
        dirty.set(true);
        lastChange.set(System.currentTimeMillis());
        synchronized (wake) {
            wake.notifyAll();
        }
    }

    private void loop() {
        while (!closed) {
            try {
                if (!dirty.get() || pending.get() == null) {
                    idle(200);
                    continue;
                }
                long elapsed = System.currentTimeMillis() - lastChange.get();
                if (elapsed < quietMillis) {
                    // 还没安静够：睡到理论安静点附近再看（最多 200ms 醒一次防错过 close）
                    idle(Math.max(20, Math.min(quietMillis - elapsed, 200)));
                    continue;
                }
                String content = pending.getAndSet(null);
                if (content == null) {
                    dirty.set(false);
                    continue;
                }
                try {
                    store.write(bucket, content);
                    written.incrementAndGet();
                    dirty.set(false);
                } catch (IOException writeProblem) {
                    errors.incrementAndGet();           // 落盘失败不许带走线程（错误数如实可查）
                }
            } catch (RuntimeException loopProblem) {
                errors.incrementAndGet();               // 任何一轮异常都不许带走节拍
            }
        }
    }

    private void idle(long millis) {
        if (millis <= 0) {
            return;
        }
        synchronized (wake) {
            try {
                wake.wait(millis);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
        }
    }

    /** 同步把 pending 落盘（没有 pending 就什么都不写）。返回是否写了。 */
    public synchronized boolean flush() throws IOException {
        String content = pending.getAndSet(null);
        if (content == null) {
            return false;
        }
        store.write(bucket, content);
        written.incrementAndGet();
        dirty.set(false);
        return true;
    }

    public int writtenCount() {
        return written.get();
    }

    public int errorCount() {
        return errors.get();
    }

    public String bucket() {
        return bucket;
    }

    /** 停线程并尽力 flush（flush 失败计入 errors，不抛——停机路径不许被卡住）。 */
    @Override
    public synchronized void close() {
        if (closed) {
            return;
        }
        closed = true;
        synchronized (wake) {
            wake.notifyAll();
        }
        try {
            worker.join(2000);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
        try {
            flush();
        } catch (IOException flushProblem) {
            errors.incrementAndGet();
        }
    }
}
