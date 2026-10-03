"""tests/test_msh.py —— B8 自测：脚本驱动 mini-shell，逐条验证行为契约。

纪律（和本仓库其它项目一致）：
  1. 期望值来自手算或独立参照：输出与真实工具（sort/tr/head/cat）对拍，
     退出码对照 128+信号 的约定，僵尸检查去 /proc 里**当面数**；
  2. 每个用例都跑在临时目录里（`mkdtemp`，断言不在仓库内），用完即删；
  3. 双入口同数：`python3 -m unittest discover -s tests` 与 `python3 tests/test_msh.py`。

这几个用例盯着本实现的三条"设计坑"（写实现时踩过/有意防住的）：
  - 命令行必须**逐字节 read**（stdio 预读会把 cat 的 stdin 吞掉）→ test_stdin_inheritance；
  - 父进程要关掉管道两端的多余 fd（不然读端等不到 EOF）→ 管道用例能跑完就说明关对了；
  - 每个子进程都要 waitpid（不止最后一个）→ test_zombie_reaping 数僵尸。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MSH = ROOT / "build" / "msh"
REPO = ROOT.parent.parent


def make_tmp(name: str) -> pathlib.Path:
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"b8-{name}-"))
    if str(base.resolve()).lower().startswith(str(REPO.resolve()).lower()):
        raise RuntimeError(f"临时目录意外落在仓库里：{base}")
    return base


def run_script(script: str, cwd: pathlib.Path, timeout: float = 15.0):
    return subprocess.run(
        [str(MSH)], input=script, text=True, capture_output=True,
        cwd=str(cwd), timeout=timeout,
    )


def children_of(pid: int) -> list[int]:
    """读 /proc 列出 pid 的全部直接子进程（Linux/WSL 口径）。"""
    out: list[int] = []
    task_dir = pathlib.Path(f"/proc/{pid}/task")
    if not task_dir.exists():
        return out
    for tid in task_dir.iterdir():
        children_file = tid / "children"
        if children_file.exists():
            text = children_file.read_text().strip()
            if text:
                out.extend(int(x) for x in text.split())
    return out


def zombie_children_of(pid: int) -> list[int]:
    zombies = []
    for child in children_of(pid):
        try:
            stat = pathlib.Path(f"/proc/{child}/stat").read_text()
        except OSError:
            continue
        # stat 的第二个字段（括号内是 comm，可能含空格）之后才是 state
        state = stat.rsplit(")", 1)[1].split()[0]
        if state == "Z":
            zombies.append(child)
    return zombies


class TestMsh(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MSH.exists(), msg=f"先跑 run.sh 编译：缺 {MSH}")
        self.tmp = make_tmp("case")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    # ---------------------------------------------------------------- 基础执行

    def test_echo_and_exit_status(self):
        r = run_script("echo hello world\n", self.tmp)
        self.assertEqual(r.stdout, "hello world\n")
        self.assertEqual(r.returncode, 0)

        self.assertEqual(run_script("true\n", self.tmp).returncode, 0)
        self.assertEqual(run_script("false\n", self.tmp).returncode, 1)

    def test_exit_builtin(self):
        self.assertEqual(run_script("exit 7\n", self.tmp).returncode, 7)
        self.assertEqual(run_script("false\nexit\n", self.tmp).returncode, 1)
        self.assertEqual(run_script("exit\n", self.tmp).returncode, 0)

    def test_quotes(self):
        self.assertEqual(run_script('echo "a  b"\n', self.tmp).stdout, "a  b\n")
        self.assertEqual(run_script("echo 'x  y'\n", self.tmp).stdout, "x  y\n")
        self.assertEqual(run_script('echo a"b c"d\n', self.tmp).stdout, "ab cd\n")
        self.assertEqual(run_script('echo "a\\"b"\n', self.tmp).stdout, 'a"b\n')

    def test_unclosed_quote_is_reported_and_shell_survives(self):
        r = run_script('echo "oops\necho fine\n', self.tmp)
        self.assertIn("引号", r.stderr)
        self.assertEqual(r.stdout, "fine\n")
        self.assertEqual(r.returncode, 0)

    def test_comments_and_blank_lines(self):
        r = run_script("\n   \n# 注释整行跳过\necho ok\n", self.tmp)
        self.assertEqual(r.stdout, "ok\n")
        self.assertEqual(r.returncode, 0)

    def test_prompt_absent_when_not_tty(self):
        r = run_script("echo hi\n", self.tmp)
        self.assertNotIn("msh>", r.stdout)

    # ---------------------------------------------------------------- 管道

    def test_pipe_two_stages(self):
        r = run_script("echo hello | tr a-z A-Z\n", self.tmp)
        self.assertEqual(r.stdout, "HELLO\n")

    def test_pipe_three_stages(self):
        r = run_script("printf 'c\\nb\\na\\n' | sort | head -2\n", self.tmp)
        self.assertEqual(r.stdout, "a\nb\n")

    def test_pipeline_status_is_last_stage(self):
        self.assertEqual(run_script("false | true\n", self.tmp).returncode, 0)
        self.assertEqual(run_script("true | false\n", self.tmp).returncode, 1)

    # ---------------------------------------------------------------- 重定向

    def test_input_redirect(self):
        (self.tmp / "in.txt").write_text("b\na\n")
        r = run_script("sort < in.txt\n", self.tmp)
        self.assertEqual(r.stdout, "a\nb\n")

    def test_output_truncate_and_append(self):
        run_script("echo one > f.txt\n", self.tmp)
        self.assertEqual((self.tmp / "f.txt").read_text(), "one\n")
        run_script("echo two > f.txt\n", self.tmp)
        self.assertEqual((self.tmp / "f.txt").read_text(), "two\n")
        run_script("echo three >> f.txt\n", self.tmp)
        self.assertEqual((self.tmp / "f.txt").read_text(), "two\nthree\n")

    def test_attached_redirect_no_spaces(self):
        run_script("echo hi>f2.txt\n", self.tmp)
        self.assertEqual((self.tmp / "f2.txt").read_text(), "hi\n")

    def test_pipeline_with_redirect(self):
        r = run_script("printf 'b\\na\\n' | sort > sorted.txt\n", self.tmp)
        self.assertEqual(r.returncode, 0)
        self.assertEqual((self.tmp / "sorted.txt").read_text(), "a\nb\n")

    def test_redirect_to_bad_path_reports_and_continues(self):
        r = run_script("echo hi > /no/such/dir/out.txt\necho alive\n", self.tmp)
        self.assertIn("/no/such/dir/out.txt", r.stderr)
        self.assertEqual(r.stdout, "alive\n")
        self.assertEqual(r.returncode, 0)

    # ---------------------------------------------------------------- 内建命令

    def test_cd_persists_across_lines(self):
        r = run_script("cd /tmp\npwd\ncd /\npwd\n", self.tmp)
        self.assertEqual(r.stdout, "/tmp\n/\n")

    def test_cd_failure_keeps_cwd_and_sets_status(self):
        r = run_script("cd /no/such/dir\npwd\n", self.tmp)
        self.assertIn("cd", r.stderr)
        self.assertEqual(r.stdout.rstrip("\n"), str(self.tmp))   # 目录没变
        self.assertEqual(run_script("cd /no/such/dir\n", self.tmp).returncode, 1)

    def test_builtin_in_pipeline_treated_as_external(self):
        # 内建只在"单命令"时由 shell 本体执行；进管道就当外部命令（找不到 → 子进程 127）。
        # 但管道的 $? 口径 = **最后一段**（cat 成功）→ 整体 0；证据在 stderr 上。
        r = run_script("cd /tmp | cat\n", self.tmp)
        self.assertIn("cd", r.stderr)
        self.assertIn("No such file", r.stderr)
        self.assertEqual(r.returncode, 0)

    # ---------------------------------------------------------------- 错误路径

    def test_command_not_found_continues(self):
        r = run_script("definitely_not_a_command_xyz\necho after\n", self.tmp)
        self.assertIn("definitely_not_a_command_xyz", r.stderr)
        self.assertEqual(r.stdout, "after\n")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(run_script("definitely_not_a_command_xyz\n", self.tmp).returncode, 127)

    def test_syntax_errors_do_not_kill_shell(self):
        script = "| echo\n echo hi |\n echo hi >\n echo hi <\necho alive\n"
        r = run_script(script, self.tmp)
        self.assertGreaterEqual(r.stderr.count("语法错误"), 4)
        self.assertEqual(r.stdout, "alive\n")
        self.assertEqual(r.returncode, 0)

    def test_signal_death_maps_to_128_plus_signal(self):
        r = run_script("sh -c 'kill -TERM $$'\n", self.tmp)
        self.assertEqual(r.returncode, 143)          # 128 + SIGTERM(15)

    def test_stderr_passthrough(self):
        r = run_script("sh -c 'echo err >&2'\n", self.tmp)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.stderr, "err\n")

    # ---------------------------------------------------------------- 进程回收与 stdin

    def test_stdin_inheritance_for_cat(self):
        # 这条盯着"命令行要用逐字节 read"：若用 fgets，stdio 会把 hello/world 预读走
        r = run_script("cat\nhello\nworld\n", self.tmp)
        self.assertIn("hello", r.stdout)
        self.assertIn("world", r.stdout)

    def test_zombie_reaping(self):
        proc = subprocess.Popen([str(MSH)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, cwd=str(self.tmp))
        try:
            # 同步点用**文件**而不是"轮询到空快照"：echo 落盘意味着前面所有命令
            # （含 sleep 0.3 这个看得见的子进程）都已经处理完，且它是最后一条——
            # 之后不会再有新 fork，"空"才是稳定结论。
            # 原版对三条瞬时命令直接轮询空快照就 break：shell 还没 fork 之前
            # 就会把"没发生过"记成"回收完毕"（2026-10-03 实测到的竞态）。
            sync = self.tmp / "sync.txt"
            proc.stdin.write("true\nfalse\nsleep 0.3\necho done > sync.txt\n")
            proc.stdin.flush()
            deadline = time.time() + 5.0
            while time.time() < deadline and not sync.exists():
                time.sleep(0.05)
            self.assertTrue(sync.exists(), "同步文件未出现——结论不可信")
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if not children_of(proc.pid) and not zombie_children_of(proc.pid):
                    break
                time.sleep(0.05)
            self.assertEqual(zombie_children_of(proc.pid), [])
            self.assertEqual(children_of(proc.pid), [])   # 全部回收，一个不留
            proc.stdin.write("false\nexit\n")
            proc.stdin.flush()
            # exit 无参数 = 取最后一条命令的状态——退出前最后一条是 false，所以是 1
            self.assertEqual(proc.wait(timeout=5), 1)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_sequence_of_commands_share_state(self):
        r = run_script("cd /tmp\ntrue\necho here\npwd\nexit 5\n", self.tmp)
        self.assertEqual(r.stdout, "here\n/tmp\n")
        self.assertEqual(r.returncode, 5)


if __name__ == "__main__":
    unittest.main()
