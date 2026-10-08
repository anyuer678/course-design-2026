"""board 画板自测：B14 引擎自检 + 备份仓库 + 节流自动备份 + 守护探活 + CLI + 启动器契约。

对拍口径（零件库纪律的测试面）：
    - B14 PaintTests（7106 项检查）在产品编译产物上现跑现过——引擎没被产品层碰坏；
    - 绘图/存取/PNG 全走 B14 真件（PaintCanvas 交互语义、SafeStore 白名单、
      DrawingFormat 往返），产品侧只补备份与守护；
    - 钉值出处：B14 README 钉了自检 7106 项（拓展轮 2026-10-07 画笔/线宽/微调
      +52）；PNG 魔数 \\x89PNG；探活回行的 docs/backups/corrupt 是现算活账。
"""
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BOARD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOARD))

from compile_support import ensure_classes

PAD_DOC = "pad 1\nrect 0 0 100 80 #ff0000\nellipse 40 20 120 90 #00ff00\n"
PNG_MAGIC = b"\x89PNG"
# B14 run.bat 的 JAVA_FLAGS：Windows 上不指定 stdout 编码，中文输出会变 GBK 乱码
JAVA_FLAGS = ["-Djava.awt.headless=true", "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8"]


def run_cli(data_dir: Path, script_lines: list[str], *, keep: int = 20,
            timeout: float = 120) -> tuple[int, list[dict], str]:
    """跑一条 CLI 脚本：返回 (退出码, JSON 行列表, stderr)。"""
    classes, _ = ensure_classes()
    script = data_dir.parent / "script.txt"
    script.write_text("\n".join(script_lines) + "\n", encoding="utf-8")
    proc = subprocess.run(
        ["java", *JAVA_FLAGS, f"-Dpaint.data={data_dir}",
         "-cp", str(classes), "board.Cli", "--script", str(script), "--keep", str(keep)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False)
    records = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            records.append(json.loads(line))
    return proc.returncode, records, proc.stderr


class EngineTest(unittest.TestCase):
    """引擎完好性：产品编译产物上现跑 B14 的 7106 项自检。"""

    def test_b14_selfcheck_on_product_build(self):
        classes, test_classes = ensure_classes()
        proc = subprocess.run(
            ["java", *JAVA_FLAGS, "-cp", f"{classes};{test_classes}", "paint.PaintTests"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        # 钉值出处：B14 README——"7106 项检查"（拓展轮 +52）。格式："全部通过：7106 项检查，0 失败"
        summary = [ln for ln in proc.stdout.splitlines() if "全部通过" in ln]
        self.assertTrue(summary, "自检汇总行没找到")
        self.assertIn("7106", summary[-1])
        self.assertIn("0 失败", summary[-1])


class CliTest(unittest.TestCase):
    """无头驱动口：绘图/存取/导出/备份全链路（每个用例独立数据目录）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.data = self.tmp / "data"

    def test_draw_save_open_roundtrip(self):
        """画三个形状 → 存 → 清空 → 打开：形状种类逐项一致（DrawingFormat 往返）。"""
        rc, records, err = run_cli(self.data, [
            "tool rect", "color #ff0000", "draw 10 10 80 60",
            "tool ellipse", "color #00ff00", "draw 120 30 200 100",
            "tool line", "color #0000ff", "draw 20 150 200 190",
            "stats", "save 往返.pad", "new", "stats", "open 往返.pad", "stats",
        ])
        self.assertEqual(rc, 0, err)
        stats = [r for r in records if r.get("op") == "stats"]
        self.assertEqual(stats[0]["shapes"], 3)
        self.assertEqual(stats[0]["kinds"], "rect,ellipse,line")
        self.assertEqual(stats[0]["undo"], 3)
        self.assertEqual(stats[1]["shapes"], 0)           # new 真的清空
        self.assertEqual(stats[2]["kinds"], stats[0]["kinds"])   # 往返一致
        self.assertTrue((self.data / "往返.pad").exists())

    def test_backup_now_and_restore(self):
        """备份 → 改 → 恢复：恢复的就是备份那一刻的文档（形状逐项对上）。"""
        rc, records, err = run_cli(self.data, [
            "tool rect", "color #ff0000", "draw 10 10 80 60",
            "tool line", "color #0000ff", "draw 0 0 40 40",
            "backup-now",                                  # 2 形状的版本
            "tool ellipse", "color #00ff00", "draw 200 200 260 260",   # 改：+1
            "stats", "backup-restore", "stats", "backup-list",
        ])
        self.assertEqual(rc, 0, err)
        stats = [r for r in records if r.get("op") == "stats"]
        self.assertEqual(stats[0]["shapes"], 3)
        restore = next(r for r in records if r.get("op") == "backup-restore")
        self.assertEqual(restore["shapes"], 2)            # 回到备份那一刻
        self.assertEqual(stats[1]["shapes"], 2)
        self.assertEqual(stats[1]["kinds"], "rect,line")
        listing = next(r for r in records if r.get("op") == "backup-list")
        self.assertEqual(listing["count"], 1)

    def test_backup_rotation(self):
        """轮换：keep=3 连写 5 份 → 桶里只剩最新 3 份（时间戳字典序=时间序）。"""
        script = []
        for i in range(5):
            script += ["tool rect", "color #ff0000", f"draw {i * 10} 0 {i * 10 + 30} 30",
                       "backup-now"]
        rc, records, err = run_cli(self.data, script + ["backup-list"], keep=3)
        self.assertEqual(rc, 0, err)
        kept = [r for r in records if r.get("op") == "backup-now"]
        self.assertEqual([r["kept"] for r in kept], [1, 2, 3, 3, 3])   # 轮换的账
        listing = records[-1]
        self.assertEqual(listing["count"], 3)

    def test_auto_backup_after_quiet(self):
        """节流自动备份：auto-on(300ms) 挂在改动之前 → 改 → 等 1s → 桶里自动多一份
        （全程没点过 backup-now）。"""
        rc, records, err = run_cli(self.data, [
            "auto-on 300",                                 # 先挂监听，改动才有事件可听
            "tool rect", "color #ff0000", "draw 10 10 80 60",
            "sleep 1000", "backup-list", "auto-off",
        ])
        self.assertEqual(rc, 0, err)
        listing = next(r for r in records if r.get("op") == "backup-list")
        self.assertGreaterEqual(listing["count"], 1)      # 自动备份真的自己写了
        self.assertEqual(listing["bucket"], "autosave")

    def test_export_png(self):
        """PNG 导出（离屏渲染走 SafeStore 导出白名单）：魔数与字节数如实。"""
        rc, records, err = run_cli(self.data, [
            "tool rect", "color #ff0000", "draw 10 10 200 120", "export 冒烟.png",
        ])
        self.assertEqual(rc, 0, err)
        record = records[-1]
        self.assertEqual(record["op"], "export")
        self.assertGreater(record["bytes"], 0)
        png = self.data / "冒烟.png"
        self.assertTrue(png.exists())
        self.assertEqual(png.read_bytes()[:4], PNG_MAGIC)

    def test_pencil_nudge_width_roundtrip(self):
        """拓展轮（10-07）：画笔一笔=一个形状、nudge 微调生效、线宽 w 尾缀进文档往返。"""
        rc, records, err = run_cli(self.data, [
            "tool pencil", "width 4", "color #ff8800",
            "scribble 10 10 20 30 40 10",
            "tool rect", "width 8",
            "draw 0 0 50 50",
            "nudge 5 0",
            "save 拓展.pad", "stats",
        ])
        self.assertEqual(rc, 0, err)
        scribble = next(r for r in records if r.get("op") == "scribble")
        self.assertTrue(scribble["committed"])
        self.assertEqual(scribble["points"], 3)           # 一次拖拽 = 一条命令、三个采样点
        nudge = next(r for r in records if r.get("op") == "nudge")
        self.assertTrue(nudge["moved"])
        text = (self.data / "拓展.pad").read_text(encoding="utf-8")
        self.assertIn("pencil #FF8800 3 10 10 20 30 40 10 w4", text)
        self.assertIn("rect 5 0 50 50 #FF8800 w8", text)  # 微调后的位置 + 线宽尾缀
        rc2, records2, _ = run_cli(self.data, ["new", "open 拓展.pad", "stats"])
        self.assertEqual(rc2, 0)
        stats = [r for r in records2 if r.get("op") == "stats"]
        self.assertEqual(stats[0]["kinds"], "pencil,rect")

    def test_bad_script_first_error_stops(self):
        """首错即停：未知操作/非法文件名都带行号报错、退出码 2、之前的操作结果仍在。"""
        rc, records, err = run_cli(self.data, [
            "tool rect", "draw 0 0 30 30", "frobnicate 1 2", "stats",
        ])
        self.assertEqual(rc, 2)
        self.assertIn("error line 3 (frobnicate)", err)
        self.assertEqual(len(records), 2)                 # 前两个操作的 JSON 仍在
        rc, _, err = run_cli(self.data, ["save ../逃逸.pad"])
        self.assertEqual(rc, 2)
        self.assertIn("error line 1 (save)", err)         # SafeStore 白名单挡住路径逃逸


class DaemonTest(unittest.TestCase):
    """守护形态：探活口活账 + 启动即兜底 + 变更备份 + 坏文档如实计数。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.data = self.tmp / "data"
        self.data.mkdir()

    def start_daemon(self, *extra: str) -> tuple[subprocess.Popen, int]:
        classes, _ = ensure_classes()
        proc = subprocess.Popen(
            ["java", *JAVA_FLAGS, f"-Dpaint.data={self.data}",
             "-cp", str(classes), "board.BackupDaemon", "--port", "0",
             "--interval", "100", *extra],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        self.addCleanup(self.kill_daemon, proc)
        boot = proc.stdout.readline().strip()
        self.assertTrue(boot.startswith("BOARD LISTENING "), boot)
        return proc, int(boot.split()[-1])

    @staticmethod
    def kill_daemon(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def probe(self, port: int) -> str:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
            return sock.recv(4096).decode("utf-8").strip()

    def probe_until(self, port: int, want: str, timeout: float = 5.0) -> str:
        deadline = time.time() + timeout
        reply = ""
        while time.time() < deadline:
            reply = self.probe(port)
            if want in reply:
                return reply
            time.sleep(0.1)
        self.fail(f"5s 内没等到 {want!r}，最后一次：{reply}")

    def test_liveness_startup_backup_and_change(self):
        """启动即给现有文档兜一份；新保存的文档在轮询间隔内被接住；探活回报活账。"""
        (self.data / "预热.pad").write_text(PAD_DOC, encoding="utf-8")
        _, port = self.start_daemon()
        reply = self.probe_until(port, "backups=1")
        self.assertIn("docs=1", reply)
        (self.data / "新文档.pad").write_text("pad 1\nline 0 0 50 50 #0000ff\n",
                                              encoding="utf-8")
        reply = self.probe_until(port, "docs=2 backups=2")
        bucket = self.data / "backups" / "新文档"
        self.assertTrue(bucket.is_dir() and any(bucket.iterdir()))

    def test_corrupt_doc_counted_not_fatal(self):
        """坏文档：corrupt 如实 +1，守护与好文档的备份都不受影响。"""
        (self.data / "坏文档.pad").write_text("这不是 pad 文件\n", encoding="utf-8")
        (self.data / "好文档.pad").write_text(PAD_DOC, encoding="utf-8")
        _, port = self.start_daemon()
        reply = self.probe_until(port, "corrupt=1")
        self.assertIn("docs=2", reply)
        self.assertIn("backups=1", reply)                 # 只有能解析的那份入了备份
        self.assertFalse((self.data / "backups" / "坏文档").exists())

    def test_parent_watchdog(self):
        """看门狗：--parent-pid 指向不存在的进程 → 守护一秒级自觉退出（退出码 0）。"""
        proc, _ = self.start_daemon("--parent-pid", "99999999")
        rc = proc.wait(timeout=6)
        self.assertEqual(rc, 0)


class LauncherTest(unittest.TestCase):
    """Studio 集成契约：launch.py = 编译 + 拉守护 + 看门狗；启动器被杀 → java 随之退。"""

    def test_launch_and_watchdog_contract(self):
        ensure_classes()                              # 预热编译，别让首跑探活超时
        launcher = subprocess.Popen(
            [sys.executable, str(BOARD / "launch.py"), "--port", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        try:
            boot = launcher.stdout.readline().strip()
            self.assertTrue(boot.startswith("BOARD LISTENING "), boot)
            port = int(boot.split()[-1])
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                pass                                  # 探活口真的活着
        finally:
            launcher.terminate()                      # Studio stop = 终止启动器
            try:
                launcher.wait(timeout=5)
            except subprocess.TimeoutExpired:
                launcher.kill()
        # 看门狗：java 子进程一秒级自觉退出，探活口关闭（不留孤儿）
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                time.sleep(0.2)
            except OSError:
                break                                 # 连不上了 = 进程收干净了
        else:
            self.fail("启动器死后 8s，java 子进程还占着探活口（孤儿进程）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
