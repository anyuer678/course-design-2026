"""sparklab/jobs.py —— Spark 版清洗与聚合：DataFrame API 与 Spark SQL 双实现

课程要点：
    - **清洗规则必须是同一套正则、同一个优先级**：本模块用 rlike + CASE WHEN
      复刻 `clean.classify_line` 的判定顺序——对拍只有在"两份实现读同一把尺子"
    时才公平；
    - DataFrame API 与 Spark SQL 是同一台引擎的两种说法：注册一个临时视图后，
      同一批聚合用 SQL 再写一遍，两边结果必须逐行相等（"换个写法不换答案"）；
    - 空值语义要当心：字段数不足的行 `split` 之后取下标会得到 null，
      所以"字段数"必须**最先判**（Python 侧同序，否则两边归类会漂）。
"""
from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from sparklab.clean import CODE_PATTERN, LEVELS, TS_PATTERN

BAD_ORDER = ("missing_field", "bad_timestamp", "bad_level", "bad_code")


def load_lines(spark: SparkSession, path) -> DataFrame:
    return spark.read.text(str(path))


def parsed(df: DataFrame) -> DataFrame:
    """value → ts/device/level/code/msg + kind（分类优先级与 clean.py 一致）。"""
    fields = F.split(F.col("value"), r"\|")
    ts = fields.getItem(0)
    device = fields.getItem(1)
    level = fields.getItem(2)
    code_field = fields.getItem(3)
    msg_field = fields.getItem(4)
    # 与 clean.parse_ok_line 同一契约：code 只留三位数；msg 剥 "msg=" 前缀
    msg = F.when(msg_field.startswith("msg="), F.substring(msg_field, 5, 10000)).otherwise(msg_field)
    kind = (F.when(F.size(fields) != 5, "missing_field")
            .when(ts.isNull() | ~ts.rlike(TS_PATTERN), "bad_timestamp")
            .when(level.isNull() | ~level.isin(*LEVELS), "bad_level")
            .when(code_field.isNull() | ~code_field.rlike(CODE_PATTERN), "bad_code")
            .otherwise("ok"))
    return df.select(
        ts.alias("ts"), device.alias("device"), level.alias("level"),
        F.substring(code_field, 6, 3).alias("code"), msg.alias("msg"),
        kind.alias("kind"),
    )


def clean_counts(df: DataFrame) -> dict:
    """{'ok': n, 'missing_field': n, ...}——与账本对账用的口径。"""
    rows = df.groupBy("kind").count().collect()
    return {r["kind"]: r["count"] for r in rows}


def cleaned(df: DataFrame) -> DataFrame:
    return df.filter(F.col("kind") == "ok")


def agg_device_level(df: DataFrame) -> list[tuple]:
    rows = (df.groupBy("device", "level").count()
            .orderBy("device", "level").collect())
    return [(r["device"], r["level"], r["count"]) for r in rows]


def agg_errors_per_hour(df: DataFrame) -> list[tuple]:
    rows = (df.filter(F.col("level") == "ERROR")
            .withColumn("hour", F.substring("ts", 12, 2))
            .groupBy("hour").count().orderBy("hour").collect())
    return [(r["hour"], r["count"]) for r in rows]


def agg_top_error_codes(df: DataFrame, k: int = 3) -> list[tuple]:
    rows = (df.filter(F.col("level") == "ERROR")
            .groupBy("code").count()
            .orderBy(F.desc("count"), F.asc("code"))
            .limit(k).collect())
    return [(r["code"], r["count"]) for r in rows]


# ---------------------------------------------------------------- Spark SQL 版（同一视图，另一种说法）

def register_view(df: DataFrame, name: str = "logs") -> None:
    df.createOrReplaceTempView(name)


def sql_device_level(spark: SparkSession) -> list[tuple]:
    rows = spark.sql(
        "SELECT device, level, COUNT(*) AS cnt FROM logs WHERE kind = 'ok' "
        "GROUP BY device, level ORDER BY device, level").collect()
    return [(r["device"], r["level"], r["cnt"]) for r in rows]


def sql_errors_per_hour(spark: SparkSession) -> list[tuple]:
    rows = spark.sql(
        "SELECT substr(ts, 12, 2) AS hour, COUNT(*) AS cnt FROM logs "
        "WHERE kind = 'ok' AND level = 'ERROR' GROUP BY hour ORDER BY hour").collect()
    return [(r["hour"], r["cnt"]) for r in rows]


def sql_top_error_codes(spark: SparkSession, k: int = 3) -> list[tuple]:
    rows = spark.sql(
        f"SELECT code, COUNT(*) AS cnt FROM logs "
        f"WHERE kind = 'ok' AND level = 'ERROR' "
        f"GROUP BY code ORDER BY cnt DESC, code ASC LIMIT {k}").collect()
    return [(r["code"], r["cnt"]) for r in rows]
