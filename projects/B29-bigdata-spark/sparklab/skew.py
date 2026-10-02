"""sparklab/skew.py —— 数据倾斜：同键同分区 → 一个任务干全活；salting 两阶段聚合

课程要点（PLAN 选做项里的教学点，本实现按"先演示危害、再演示对策"组织）：
    - **危害的量尺一：分区行数分布**。`repartition(n, 'device')` 后按分区数行，
      热键（dev-01 占 ~45%）会把某个分区撑到中位数的许多倍——任务粒度上是"一个
      任务干全活，其他任务打酱油"；
    - **危害的量尺二：耗时**。同一份数据、同一个 groupBy，倾斜键会拖住整体完成
      时间（在本地小数据上这个差距可能不明显，演示里如实报告）;
    - **对策：salting（加盐）两阶段聚合**——
        阶段 1：给热键拼一个随机盐（0..N-1），按 (salt, key) 先局部聚合；
        阶段 2：去掉盐，按 key 把局部结果再聚合。
      盐把热键拆成 N 个小键，第一阶段的负载被摊平；代价是多一次 shuffle——
      所以 salting 不是"总是更快"，是"倾斜代价 > 额外 shuffle 代价时才划算"。
    - 正确性背书：salting 的最终结果必须与直接 groupBy **逐行相等**（测试钉住）。
"""
from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def partition_row_counts(df: DataFrame) -> list[int]:
    """按分区数行（分区编号 → 行数），用于展示"同键同分区"带来的分布不均。"""
    def count_iter(index, iterator):
        yield index, sum(1 for _ in iterator)

    pairs = df.rdd.mapPartitionsWithIndex(count_iter).collect()
    return [count for _index, count in sorted(pairs)]


def skew_ratio(counts: list[int]) -> float:
    """最大分区 / 中位分区——倾斜程度的无量纲读数（1.0 = 均匀）。"""
    if not counts:
        return 1.0
    ordered = sorted(counts)
    mid = ordered[len(ordered) // 2]
    return (max(counts) / mid) if mid > 0 else float("inf")


def plain_group_count(df: DataFrame, key: str) -> list[tuple]:
    """直接的 groupBy+count（对照组）。"""
    rows = df.groupBy(key).count().orderBy(key).collect()
    return [(r[key], r["count"]) for r in rows]


def salted_group_count(df: DataFrame, key: str, salt_n: int = 8,
                       seed: int = 42) -> list[tuple]:
    """加盐两阶段聚合（实验组）：结果与 plain_group_count 必须逐行相等。"""
    salted = (df.withColumn("_salt", (F.rand(seed) * salt_n).cast("int"))
              .groupBy(key, "_salt").count())
    rows = (salted.groupBy(key).agg(F.sum("count").alias("count"))
            .orderBy(key).collect())
    return [(r[key], r["count"]) for r in rows]
