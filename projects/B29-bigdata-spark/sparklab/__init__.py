"""B29-bigdata-spark —— 工业日志的 PySpark 清洗、聚合与 Spark SQL（工业大数据处理技术）

    session.py   统一会话入口（把 Windows 的三条坑挡在门外：PYSPARK_PYTHON 指向完整
                 解释器 / 仓库不被 metastore 弄脏 / shuffle 分区数对数据规模说话）
    genlog.py    合成工业日志：四类缺陷按已知数量注入 + 键倾斜开关（账本可对）
    clean.py     纯 Python 清洗（坏行四类分类，与 Spark 侧同一套正则与优先级）
    reference.py 纯 Python 参照聚合（Counter + sorted，最笨但最可信）
    jobs.py      Spark 版：DataFrame API 与 Spark SQL 双实现（清洗规则 rlike 复刻）
    skew.py      倾斜三件套：分区行数分布 / salting 两阶段聚合 / 结果对拍

环境：pyspark 4.2.0（用户级 pip 安装，~300MB，经用户批准）+ 本机 Zulu JDK。
"""
