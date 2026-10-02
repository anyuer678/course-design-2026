"""sparklab/session.py —— Spark 会话的统一入口（把 Windows 的坑一次挡在门外）

本机实测的三条坑（2026-10-02，全部写死在代码里而不是留给运气）：
  1. **`PYSPARK_PYTHON` 必须指向完整解释器路径**：不设时 Spark 用 `python3` 拉起
     worker，而本机 `python3` 是 **Microsoft Store 的占位桩**
     （`C:\\Users\\...\\WindowsApps\\python3`）——worker 起不来，JVM 等回连超时，
     报"Python worker failed to connect back"（A/B 对照：设了就过，不设必挂）；
  2. **仓库不能被 Spark 弄脏**：metastore/warehouse 默认落在进程 cwd——这里改用
     `in-memory` catalog（免 Derby）+ 系统临时目录里的 warehouse，并断言临时目录
     一定不在仓库内（事故后纪律）；
  3. `spark.sql.shuffle.partitions` 默认 200：教学数据只有 MB 级，缩到 4 个，
     不然一个 count 要起 200 个小任务（这是"配置要对数据规模说话"的第一课）。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
from contextlib import contextmanager

REPO = pathlib.Path(__file__).resolve().parents[3]      # sparklab/ -> B29/ -> projects/ -> 课设/


def _make_warehouse() -> pathlib.Path:
    wh = pathlib.Path(tempfile.mkdtemp(prefix="b29-warehouse-"))
    if str(wh.resolve()).lower().startswith(str(REPO.resolve()).lower()):
        raise RuntimeError(f"warehouse 意外落在仓库里：{wh}")
    return wh


def ensure_python_env() -> None:
    """把 worker 解释器指到**当前进程自己**（setdefault：不覆盖用户显式设置）。

    必须在 import/创建 SparkSession **之前**调用——顺序反了不生效。"""
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)


@contextmanager
def spark_session(app_name: str = "B29", master: str = "local[2]",
                  shuffle_partitions: int = 4):
    """生成一个配置好的本地 SparkSession；退出时 stop 并清掉 warehouse。"""
    ensure_python_env()                       # 坑 1：先设环境变量，再建会话

    from pyspark.sql import SparkSession

    warehouse = _make_warehouse()
    spark = (SparkSession.builder
             .master(master)
             .appName(app_name)
             .config("spark.ui.enabled", "false")
             .config("spark.ui.showConsoleProgress", "false")   # 进度条按调度时机刷屏，两次日志就没法逐字比
             .config("spark.sql.catalogImplementation", "in-memory")
             .config("spark.sql.warehouse.dir", str(warehouse))
             .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
             .config("spark.driver.host", "127.0.0.1")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    try:
        yield spark
    finally:
        spark.stop()
        shutil.rmtree(warehouse, ignore_errors=True)


def python_worker_env() -> dict:
    """返回当前生效的 worker 解释器环境（测试与演示用来展示"设没设"的差别）。"""
    return {
        "PYSPARK_PYTHON": os.environ.get("PYSPARK_PYTHON", "（未设）"),
        "PYSPARK_DRIVER_PYTHON": os.environ.get("PYSPARK_DRIVER_PYTHON", "（未设）"),
        "当前解释器": sys.executable,
    }
