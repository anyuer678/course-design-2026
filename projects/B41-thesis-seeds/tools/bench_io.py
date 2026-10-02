"""tools/bench_io.py —— 候选① 的资源基准：写盘 + fsync 的真实代价（本机实测）

口径：同一目录写 60 次 1KB 小文件，取**中位数**每操作毫秒数，两种模式：
    plain：open/write/flush/close（数据进了内核就返回）
    fsync：再 os.fsync（承诺落盘——「提交即持久」的代价所在）
返回 {plain_ms, fsync_ms}；demo 打印【实测】行，logdiff 负责规范化这两行。
"""
from __future__ import annotations

import os
import pathlib
import statistics
import time


def write_bench(directory, reps: int = 60, payload: bytes = b"x" * 1024) -> dict:
    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    plain, with_fsync = [], []
    blob = payload * 8  # ~8KB，接近一条 B10 风格的日志记录
    for i in range(reps):
        target = directory / f"bench_{i}.tmp"
        t0 = time.perf_counter()
        with open(target, "wb") as handle:
            handle.write(blob)
            handle.flush()
        plain.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        with open(target, "wb") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        with_fsync.append((time.perf_counter() - t0) * 1000)
        os.remove(target)
    return {"plain_ms": statistics.median(plain),
            "fsync_ms": statistics.median(with_fsync)}


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory(prefix="b41-bench-") as tmp:
        result = write_bench(tmp)
    print(f"plain {result['plain_ms']:.3f} ms / fsync {result['fsync_ms']:.3f} ms")
