package board;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

import paint.io.DrawingFormat;
import paint.io.DrawingFormatException;
import paint.io.SafeStore;
import paint.model.Drawing;

/**
 * 备份仓库（产品层新增的能力，B14 明说的空白：保存/打开没有自动备份）。
 *
 * <p>结构：<code>data/backups/&lt;桶&gt;/&lt;epochMillis&gt;.pad</code>。
 * 桶 = 文档名干（autosave 桶放"未保存的工作"，文档桶放"已保存文档的历史版本"）。
 *
 * <p><b>零件库纪律：零重写</b>——原子写、文件名白名单、大小上限全部复用
 * {@link SafeStore}（每个桶一个 SafeStore 实例，白名单语义原样生效）；
 * 内容校验复用 {@link DrawingFormat#parse}（解析不了的版本一律拒收，
 * 恢复时解析失败一处都不改）。本类只做三件产品侧的事：
 * 选桶、时间戳命名、按 keep 轮换。
 */
public final class BackupStore {

    /** 桶名单独校验：桶名进路径，绝不能放行 ".." 或分隔符（与 SafeStore 同一张白名单的字符集）。 */
    private static final Pattern BUCKET = Pattern.compile("^[\\w\\u4E00-\\u9FA5-]{1,48}$");

    private final Path backupsRoot;
    private final int keep;
    private long lastStamp;                        // 同毫秒两次备份不能同名（同名=REPLACE 丢一份）

    public BackupStore(Path dataRoot, int keep) {
        this.backupsRoot = dataRoot.toAbsolutePath().normalize().resolve("backups");
        this.keep = Math.max(1, keep);
    }

    /** 桶目录（校验过才给路径；SafeStore 会自建目录）。 */
    public Path bucketDir(String bucket) throws IOException {
        if (bucket == null || !BUCKET.matcher(bucket).matches()) {
            throw new IOException("备份桶名不合法：" + bucket
                    + "（只允许字母/数字/下划线/连字符/中文，1..48 字符）");
        }
        return backupsRoot.resolve(bucket);
    }

    /** 写一份备份：内容先过解析（坏内容拒收），再经 SafeStore 原子写；返回桶内现有份数。 */
    public synchronized int write(String bucket, String content) throws IOException {
        validate(content);                          // 只收能完整解析的版本——备份不许带病落盘
        SafeStore store = new SafeStore(bucketDir(bucket));
        long stamp = System.currentTimeMillis();
        if (stamp <= lastStamp) {
            stamp = lastStamp + 1;                 // 保证同名不碰撞（同名 = REPLACE = 丢一份）
        }
        lastStamp = stamp;
        store.save(stamp + SafeStore.EXTENSION, content);
        rotate(store);
        return store.listDocuments().size();
    }

    /** 解析失败按坏内容处理（IOException）：守护把它计成 corrupt，CLI 报 error line。 */
    private static void validate(String content) throws IOException {
        validateAndParse(content);
    }

    private static Drawing validateAndParse(String content) throws IOException {
        try {
            return DrawingFormat.parse(content);
        } catch (DrawingFormatException badContent) {
            throw new IOException("内容解析不过，拒收：" + String.join("；", badContent.problems()));
        }
    }

    /** 轮换：只留最新 keep 份（listDocuments 升序，文件名是定宽毫秒时间戳，字典序=时间序）。 */
    private void rotate(SafeStore store) throws IOException {
        List<String> names = store.listDocuments();
        for (int i = 0; i < names.size() - keep; i++) {
            Files.delete(store.resolve(names.get(i)));
        }
    }

    /** 桶内全部备份名（旧 → 新）。 */
    public synchronized List<String> list(String bucket) throws IOException {
        return new ArrayList<>(new SafeStore(bucketDir(bucket)).listDocuments());
    }

    /** 最新一份备份的内容（桶空 → IOException）。 */
    public synchronized String latest(String bucket) throws IOException {
        List<String> names = list(bucket);
        if (names.isEmpty()) {
            throw new IOException("备份桶 " + bucket + " 是空的，没有可恢复的版本");
        }
        return new SafeStore(bucketDir(bucket)).load(names.get(names.size() - 1));
    }

    /** 恢复最新备份：解析 → replaceAll 进目标文档；返回恢复的形状数。 */
    public synchronized int restore(String bucket, Drawing target) throws IOException {
        Drawing revived = validateAndParse(latest(bucket));
        target.replaceAll(revived.shapes());
        return revived.size();
    }
}
