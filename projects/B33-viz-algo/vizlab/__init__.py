"""B33-viz-algo —— 算法可视化：从 B2 导出操作记录，回放成可交互网页（可视化技术）

    tools/export_trace.cpp  用 B2 的只读 trace 观察口跑固定场景，导出 sort/bfs/dfs JSON
    vizlab/replay.py        独立回放/参照：逐步核对记录（对拍纪律的"可回放版"）
    vizlab/page.py          生成**自包含** HTML：内嵌数据 + 手写 JS 动画器
                            （播放/暂停/单步/上一步/速度；堆排序条形图 + 图遍历 SVG）

依赖方向：B33 → B2（只读 include B2 的头文件，不复制任何算法）。
决策声明：D3 / 树操作动画是 PLAN 的选做项，**不做**；页面零框架、零下载。
"""
