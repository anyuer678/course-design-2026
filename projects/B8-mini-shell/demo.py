"""demo.py —— B8 六段演示：shell 行为全部实测（真起进程、真落文件、真数僵尸）。

 1) 命令执行与退出状态：true/false/exit 42 的实测退出码
 2) 内建命令 cd/pwd：为什么 cd 必须是内建（改的是 shell 自己的 cwd）
 3) 管道：三段管道现场 + "$? = 最后一段" 的口径
 4) 重定向：> / >> / < / 管道落盘（工作目录在 build/demo_tmp，演示完清理）
 5) 子进程回收：命令行跑完去 /proc 当面数僵尸（0 个才叫回收了）
 6) 错误路径：找不到命令 / 坏语法 / 坏重定向 → 报错 + 继续执行

固定脚本、不打印耗时，两遍运行应逐字相同。
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent
MSH = ROOT / "build" / "msh"
WORK = ROOT / "build" / "demo_tmp"
LINE = "=" * 78


def section(no: int, title: str) -> None:
    print(f"\n{LINE}\n  {no}) {title}\n{LINE}")


def show(label: str, value: object) -> None:
    print(f"  {label:<26}{value}")


def session(script: str):
    return subprocess.run([str(MSH)], input=script, text=True,
                          capture_output=True, cwd=str(WORK), timeout=15)


def children_of(pid: int) -> list[int]:
    out: list[int] = []
    task_dir = pathlib.Path(f"/proc/{pid}/task")
    if not task_dir.exists():
        return out
    for tid in task_dir.iterdir():
        f = tid / "children"
        if f.exists() and f.read_text().strip():
            out.extend(int(x) for x in f.read_text().split())
    return out


def zombie_children_of(pid: int) -> list[int]:
    z = []
    for c in children_of(pid):
        try:
            state = pathlib.Path(f"/proc/{c}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        if state == "Z":
            z.append(c)
    return z


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    print("B8-mini-shell 演示：fork/exec、管道、重定向、内建命令与子进程回收")

    # ------------------------------------------------------------------ 1
    section(1, "命令执行与退出状态")
    for script, label in (("true\n", "true"), ("false\n", "false"),
                          ("exit 42\n", "exit 42")):
        r = session(script)
        show(f"`{label.strip()}` 退出码", r.returncode)
    r = session("echo hello from msh\n")
    show("echo 输出", repr(r.stdout))

    # ------------------------------------------------------------------ 2
    section(2, "内建命令 cd/pwd：改的是 shell 自己的进程状态")
    r = session("pwd\ncd /tmp\npwd\n")
    lines = r.stdout.splitlines()
    show("pwd → cd /tmp → pwd", f"{lines[0]} → {lines[1]}")
    show("说明", "cd 若走 fork+exec，改的是子进程的 cwd，shell 自己不动——所以必须内建")

    # ------------------------------------------------------------------ 3
    section(3, "管道：N 个进程 + N-1 根管子")
    r = session("printf 'c\\nb\\na\\n' | sort | head -2\n")
    show("printf | sort | head -2", repr(r.stdout))
    show("管道 $? = 最后一段", session("true | false\n").returncode)
    show("反过来", session("false | true\n").returncode)

    # ------------------------------------------------------------------ 4
    section(4, "重定向：> 截断 / >> 追加 / < 读入 / 管道落盘")
    session("echo first > out.txt\n")
    show("echo first > out.txt 后", repr((WORK / "out.txt").read_text()))
    session("echo second >> out.txt\n")
    show("再 echo second >> 后", repr((WORK / "out.txt").read_text()))
    (WORK / "in.txt").write_text("z\ny\nx\n")
    show("sort < in.txt", repr(session("sort < in.txt\n").stdout))
    session("printf 'b\\na\\n' | sort > sorted.txt\n")
    show("printf | sort > sorted.txt", repr((WORK / "sorted.txt").read_text()))

    # ------------------------------------------------------------------ 5
    section(5, "子进程回收：0 僵尸（/proc 当面数）")
    proc = subprocess.Popen([str(MSH)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=str(WORK))
    try:
        # sleep 0.2 是同步点：先"确实见过子进程"，再等它被回收——
        # 否则快速命令可能在 shell fork 之前就轮询到空快照，把"没发生过"记成"回收了 0 个"。
        proc.stdin.write("true\ntrue\nsleep 0.2\n")
        proc.stdin.flush()
        deadline = time.time() + 5
        seen_child = False
        while time.time() < deadline:
            if children_of(proc.pid):
                seen_child = True
            if seen_child and not children_of(proc.pid) and not zombie_children_of(proc.pid):
                break
            time.sleep(0.05)
        show("3 条命令跑完后，僵尸子进程", f"{len(zombie_children_of(proc.pid))} 个")
        show("未回收的直接子进程", f"{len(children_of(proc.pid))} 个")
        proc.stdin.write("exit\n")
        proc.stdin.flush()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    # ------------------------------------------------------------------ 6
    section(6, "错误路径：报错、退出码、继续执行")
    r = session("no_such_command_xyz\necho still alive\n")
    show("找不到命令 → stderr", repr(r.stderr.splitlines()[0] if r.stderr else ""))
    show("随后 echo 仍执行", repr(r.stdout))
    r = session("| echo\n echo a |\n echo b >\necho done\n")
    show("3 条坏语法的 stderr 条数", r.stderr.count("语法错误"))
    show("最后仍输出", repr(r.stdout))

    shutil.rmtree(WORK)
    print("\n" + LINE)
    print("完成：6 段演示全部跑通（工作目录 build/demo_tmp 已清理）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
