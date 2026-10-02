"""algo —— B12 算法分析与设计实验场。

    divide.py     分治：归并排序顺便数逆序对
    dp.py         动态规划：0/1 背包（填表 + 方案还原 + 一维滚动）
    greedy.py     贪心：区间调度；另有三种"看起来对"的贪心反例
    backtrack.py  回溯：N 皇后（集合剪枝版 + 位运算版 + 全排列参照）
    graph.py      图：Dijkstra，参照实现 Bellman-Ford 与 Floyd
    bench.py      规模计时：重复取中位数、log-log 斜率、机器信息

模块之间不互相依赖，也不重复 B2 的数据结构库：需要堆时用标准库 heapq，
理由写在 README 里——B2 已经owns了 C++ 的结构库，这里再造一份只会分裂知识。
"""
