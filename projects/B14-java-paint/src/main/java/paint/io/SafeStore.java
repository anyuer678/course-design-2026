package paint.io;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 可信的本地文件存取：文档只能落在程序自己的 data 目录里。
 *
 * <p>四道防线，每道都对应一个真实事故类型：
 * <ol>
 *   <li><b>文件名白名单</b>：只允许"字母数字下划线连字符中文 + .pad"，长度 ≤ 64。
 *       带 <code>..</code>、路径分隔符、绝对路径、Windows 保留名（CON、NUL）一律拒绝。</li>
 *   <li><b>落点复核</b>：解析成绝对路径后必须仍在 data 目录内——白名单挡住大部分，
 *       这一步防的是软链接/目录联结和以后改代码时漏掉校验。</li>
 *   <li><b>读之前先比大小</b>：不检查大小的 readFile 会让一个 5 GB 的文件直接把堆吃光。</li>
 *   <li><b>原子写</b>：写临时文件再 ATOMIC_MOVE。崩溃/断电不会留下"半个文档"，
 *       旧版本要么完整保留要么完整被替换。</li>
 * </ol>
 *
 * <p>不用 {@code ObjectInputStream}：见 {@link DrawingFormat} 的说明。
 */
public final class SafeStore {

    public static final String EXTENSION = ".pad";
    public static final int MAX_NAME_CHARS = 64;

    /** 允许中文，但不允许点、斜杠、反斜杠、冒号、控制字符：整个文件名里只有扩展名那一个点。 */
    private static final Pattern PAD_NAME = Pattern.compile("^[\\w\\u4E00-\\u9FA5-]{1,48}\\.pad$");
    private static final Pattern PNG_NAME = Pattern.compile("^[\\w\\u4E00-\\u9FA5-]{1,48}\\.png$");
    private static final List<String> RESERVED = List.of(
            "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4",
            "lpt1", "lpt2", "lpt3", "lpt4");

    private final Path root;

    public SafeStore(Path root) {
        this.root = root.toAbsolutePath().normalize();
    }

    public Path root() {
        return root;
    }

    /** 校验文件名并给出安全路径。文件名不合格时抛 IOException，消息里说清哪条规则拦的。 */
    public Path resolve(String name) throws IOException {
        if (name == null || name.isBlank()) {
            throw new IOException("文件名不能为空");
        }
        if (name.length() > MAX_NAME_CHARS) {
            throw new IOException("文件名过长（" + name.length() + " > " + MAX_NAME_CHARS + "）");
        }
        String trimmed = name.trim();
        if (!NAME.matcher(trimmed).matches()) {
            throw new IOException("文件名不合法：" + name + "。只允许字母、数字、下划线、连字符、中文，"
                    + "并且必须以内置扩展名 " + EXTENSION + " 结尾");
        }
        String stem = trimmed.substring(0, trimmed.length() - EXTENSION.length()).toLowerCase();
        if (RESERVED.contains(stem)) {
            throw new IOException("文件名 " + trimmed + " 是 Windows 保留名，换一个是吧");
        }
        Path candidate = root.resolve(trimmed).normalize();
        if (!candidate.startsWith(root)) {
            throw new IOException("路径越出文档目录：" + name);
        }
        Files.createDirectories(root);
        if (Files.exists(candidate, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                && Files.isSymbolicLink(candidate)) {
            throw new IOException("拒绝读写符号链接：" + trimmed);
        }
        return candidate;
    }

    public void save(String name, String content) throws IOException {
        byte[] bytes = content.getBytes(StandardCharsets.UTF_8);
        if (bytes.length > DrawingFormat.MAX_FILE_BYTES) {
            throw new IOException("文档过大（" + bytes.length + " 字节），拒绝写入");
        }
        Path target = resolve(name);
        Path temp = target.resolveSibling(target.getFileName() + ".tmp");
        Files.write(temp, bytes);
        try {
            Files.move(temp, target, StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING);
        } catch (AtomicMoveUnsupportedFileException | UnsupportedOperationException
                 | AtomicMoveNotSupportedException unsupported) {
            // 某些网络盘/临时目录不支持原子移动：退化成"先写后换"，仍不留半个文件在 target 上
            Files.move(temp, target, StandardCopyOption.REPLACE_EXISTING);
        }
    }

    public String load(String name) throws IOException {
        Path target = resolve(name);
        if (!Files.isRegularFile(target)) {
            throw new IOException("文件不存在：" + name);
        }
        long size = Files.size(target);
        if (size > DrawingFormat.MAX_FILE_BYTES) {
            throw new IOException("文件过大（" + size + " 字节），拒绝读取");
        }
        return Files.readString(target, StandardCharsets.UTF_8);
    }

    public List<String> listDocuments() throws IOException {
        Files.createDirectories(root);
        List<String> names = new ArrayList<>();
        try (var stream = Files.list(root)) {
            stream.filter(Files::isRegularFile)
                    .map(path -> path.getFileName().toString())
                    .filter(fileName -> fileName.endsWith(EXTENSION))
                    .sorted()
                    .forEach(names::add);
        }
        return names;
    }

    /** 编译期防御：万一某平台抛的是没列出来的异常类型，也不至于变成"写坏了没提示"。 */
    private static final class AtomicMoveUnsupportedFileException extends IOException {
        private static final long serialVersionUID = 1L;
    }
}
