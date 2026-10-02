"""B34-path-planner —— 栅格路径规划：A* / Dijkstra / BFS 同框架对拍（无人系统）

    planner/grid.py        栅格地图：障碍（种子可复现）、4/8 邻域与移动代价
    planner/heuristics.py  曼哈顿 / 欧氏 / 对角(octile) / 零启发式（h=0 即 Dijkstra）
    planner/search.py      统一 best-first 框架：A*、Dijkstra、BFS；扩展数/代价/路径
    planner/viz.py         自包含 HTML：**搜索展开动画**（SVG）+ 路径高亮，数据内嵌

复用声明：优先队列用标准库 `heapq`（本仓库规矩：Python 侧不再手造第二套堆——
B12 同款决策）；不做 RRT*/DWA/PID（PLAN 选做项）。
"""
