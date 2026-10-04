"""压测工具：对运行中的 CourseLab 发并发请求，报吞吐与 p50/p95（零依赖，标准库）。

用法：
    python tools/bench.py --url http://127.0.0.1:7900 --n 200 --c 8
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import urllib.request

PATHS = ["/api/courses", "/api/courses/B11-net-lab", "/health"]


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="CourseLab 压测（标准库并发请求）")
    ap.add_argument("--url", default="http://127.0.0.1:7900")
    ap.add_argument("--n", type=int, default=200, help="总请求数")
    ap.add_argument("--c", type=int, default=8, help="并发线程数")
    args = ap.parse_args(argv[1:])

    lat = []
    lock = threading.Lock()
    errors = [0]

    def worker(offset: int) -> None:
        for i in range(offset, args.n, args.c):
            path = PATHS[i % len(PATHS)]
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(args.url + path, timeout=10) as r:
                    r.read()
            except OSError:
                with lock:
                    errors[0] += 1
            dt = (time.perf_counter() - t0) * 1000
            with lock:
                lat.append(dt)

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.c)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.perf_counter() - t0

    lat.sort()

    def pct(p: float) -> float:
        return lat[min(len(lat) - 1, int(len(lat) * p))]

    print(f"压测：{args.n} 请求 / {args.c} 并发 / 用时 {total:.2f}s")
    print(f"  吞吐 {args.n / total:.1f} req/s | p50 {pct(0.5):.1f}ms | "
          f"p95 {pct(0.95):.1f}ms | max {lat[-1]:.1f}ms | 失败 {errors[0]}")
    return 0 if errors[0] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
