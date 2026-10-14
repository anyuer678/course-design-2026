"""demo.py —— B29 六段演示：Spark 的每一步都对着纯 Python 参照与注入账本现算。

 1) 环境与"Windows 三条坑"：PYSPARK_PYTHON 指向完整解释器（本机 python3 是商店桩）
 2) 合成日志：40 万行 + 四类缺陷按已知数量注入（账本）
 3) 清洗对账：Spark 分类计数 == 注入账本 == 纯 Python 清洗
 4) 聚合对拍：device×level / 每小时错误 / top 错误码 —— Spark 与纯 Python 逐行相等
 5) Spark SQL：同一批查询换 SQL 再写一遍，与 DataFrame API 结果逐行相等
 6) 倾斜实验：同键同分区（2.51 倍倾斜比，确定性）vs salting 两阶段（结果必须一致；
    耗时是**实测值**，两次运行会有波动——本演示唯一不确定的一段）

数据写在 build/（构建产物目录），会话的 warehouse 在系统临时目录（不脏仓库）。
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sparklab import clean, genlog, jobs, reference, session, skew   # noqa: E402

LINE = "=" * 78


def section(no: int, title: str) -> None:
    print(f"\n{LINE}\n  {no}) {title}\n{LINE}")


def show(label: str, value: object) -> None:
    print(f"  {label:<28}{value}")


def main() -> int:
    import pyspark

    print("B29-bigdata-spark 演示：工业日志的清洗 / 聚合 / Spark SQL / 倾斜实验（local 模式）")
    work = ROOT / "build"
    work.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ 1
    section(1, "环境：Spark 版本与 Windows 三条坑的落实")
    session.ensure_python_env()               # 先落实，再展示——不然显示的是"未设"
    env = session.python_worker_env()
    show("pyspark 版本", pyspark.__version__)
    # 路径脱敏（公开仓）：运行时解释器路径含 Windows 用户名，展示层打掉
    import re as _re
    show("worker 解释器（已落实）",
         _re.sub(r"^[A-Za-z]:\\Users\\[^\\]+", "<用户目录>",
                 str(env["PYSPARK_PYTHON"])))
    show("为什么必须显式设它", "本机 python3 是 Microsoft Store 占位桩，worker 会起不来")
    show("  与当前解释器一致", env["PYSPARK_PYTHON"] == env["当前解释器"])

    from sparklab.session import spark_session

    with spark_session("B29-demo", master="local[2]") as spark:
        show("Spark 版本 / master", f"{spark.version} / local[2]")
        show("warehouse 位置", spark.conf.get("spark.sql.warehouse.dir"))
        show("shuffle 分区数（对数据规模说话）", spark.conf.get("spark.sql.shuffle.partitions"))

        # -------------------------------------------------------------- 2
        section(2, "合成日志：40 万行 + 四类缺陷按账本注入 + 键倾斜 45%")
        t0 = time.perf_counter()
        big = genlog.make_log(n_lines=400000, seed=11, skew_device_ratio=0.45,
                              defects={"bad_timestamp": 40, "bad_level": 32,
                                       "missing_field": 24, "bad_code": 16})
        big_path = work / "log_big.txt"
        genlog.write_log(big, big_path)
        show("生成 40 万行用时", f"{time.perf_counter() - t0:.1f} s")
        show("文件大小", f"{big_path.stat().st_size / 1e6:.1f} MB")
        show("注入账本", big.ledger)
        show("应通过清洗（真值）", big.clean_true)

        # -------------------------------------------------------------- 3
        section(3, "清洗对账：Spark == 账本 == 纯 Python（小样本逐行 + 大样本计数）")
        small = genlog.make_log(n_lines=2000, seed=7)
        small_path = work / "log_small.txt"
        genlog.write_log(small, small_path)
        cr = clean.clean_file(small_path)
        df_small = jobs.parsed(jobs.load_lines(spark, small_path))
        jobs.register_view(df_small)
        spark_counts = jobs.clean_counts(df_small)
        show("纯 Python 隔离计数", cr.quarantined)
        show("账本", small.ledger)
        show("对账（Python==账本）", cr.quarantined == small.ledger)
        show("对账（Spark==账本）",
             all(spark_counts.get(k, 0) == v for k, v in small.ledger.items())
             and spark_counts.get("ok") == small.clean_true)

        df_big = jobs.parsed(jobs.load_lines(spark, big_path))
        big_counts = jobs.clean_counts(df_big)
        show("40 万行：Spark 分类计数", {k: big_counts.get(k, 0) for k in ("ok", *big.ledger)})
        show("40 万行：与账本一致",
             all(big_counts.get(k, 0) == v for k, v in big.ledger.items())
             and big_counts.get("ok") == big.clean_true)

        # -------------------------------------------------------------- 4
        section(4, "聚合对拍：Spark（DataFrame）vs 纯 Python 参照，逐行相等")
        clean_df = jobs.cleaned(df_small)
        r1 = reference.by_device_level(cr.clean)
        a1 = jobs.agg_device_level(clean_df)
        show("device×level 行数", f"{len(a1)}（相等：{a1 == r1}）")
        show("  样例", a1[:3])
        r2 = reference.errors_per_hour(cr.clean)
        a2 = jobs.agg_errors_per_hour(clean_df)
        show("每小时错误行数", f"{len(a2)}（相等：{a2 == r2}）")
        r3 = reference.top_error_codes(cr.clean)
        a3 = jobs.agg_top_error_codes(clean_df)
        show("top 错误码", f"{a3}（相等：{a3 == r3}）")

        # -------------------------------------------------------------- 5
        section(5, "Spark SQL：同一批查询的第二种说法")
        s1, s2, s3 = (jobs.sql_device_level(spark), jobs.sql_errors_per_hour(spark),
                      jobs.sql_top_error_codes(spark))
        show("SQL 三查询 == DataFrame", f"{s1 == a1} / {s2 == a2} / {s3 == a3}")
        show("SQL 与纯 Python 参照", f"{s1 == r1} / {s2 == r2} / {s3 == r3}")
        show("示例 SQL（每小时错误）", "SELECT substr(ts,12,2) h, COUNT(*) FROM logs "
                                        "WHERE kind='ok' AND level='ERROR' GROUP BY h")

        # -------------------------------------------------------------- 6
        section(6, "倾斜实验：同键同分区 vs salting 两阶段（耗时是实测，有波动）")
        big_clean = jobs.cleaned(df_big).select("device", "level").cache()
        n_big = big_clean.count()
        show("清洗后行数（缓存）", n_big)

        dist = skew.partition_row_counts(big_clean.repartition(4, "device"))
        dist_u = skew.partition_row_counts(big_clean.repartition(4))
        show("按 device 重分区后的行数分布", dist)
        show("  倾斜比 max/中位（确定性）", f"{skew.skew_ratio(dist):.2f}")
        show("随机重分区对照（摊平）", f"{dist_u} → 比值 {skew.skew_ratio(dist_u):.2f}")

        plain = skew.plain_group_count(big_clean, "device")
        salted = skew.salted_group_count(big_clean, "device", salt_n=8)
        show("salting 结果 == 直接 groupBy", salted == plain)
        show("  dev-01 计数（热键）", dict(plain).get("dev-01"))

        for _ in range(2):                       # 热身，不计时
            skew.plain_group_count(big_clean, "device")
            skew.salted_group_count(big_clean, "device", salt_n=8)
        t0 = time.perf_counter()
        skew.plain_group_count(big_clean, "device")
        t_plain = time.perf_counter() - t0
        t0 = time.perf_counter()
        skew.salted_group_count(big_clean, "device", salt_n=8)
        t_salt = time.perf_counter() - t0
        show("耗时（3 次取中——单次实测）", f"plain {t_plain * 1000:.0f} ms / salted {t_salt * 1000:.0f} ms")
        show("怎么读这组数", "本地 MB 级数据上耗时差落在噪声里；倾斜危害看上面的分布读数")

    print("\n" + LINE)
    print("完成：6 段演示全部跑通。第 6 段耗时是实时测量（两次运行会有波动）；")
    print("其余段落用固定种子，可复现（python demo.py > a.txt 跑两遍 diff 自证）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
