"""planner/grid.py —— 栅格地图：格子、障碍与邻域

课程要点（无人系统/移动机器人）：
    - 栅格地图是"最便宜的配置空间"：把连续世界离散成格子，规划问题就有了有限状态；
      **邻域模型决定运动学**——4 邻域是只能走直角的世界，8 邻域允许对角（代价 √2，
      不是 1——"对角走一步"实际距离是 √2，代价模型写错会让启发式和结果一起失真）；
    - 障碍用**种子生成**：每张随机地图都能复现，测试与演示引用同一张图（对拍纪律）；
    - 起终点落在障碍上是**调用方的错误**，当场抛错而不是"帮忙挪一格"（隐式修正会
      掩盖上游数据问题）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# 4 邻域：右、下、左、上（固定顺序 → 展开顺序确定，对拍才稳定）
NEIGHBORS4 = ((1, 0), (0, 1), (-1, 0), (0, -1))
SQRT2 = 2 ** 0.5
# 8 邻域：先四正后四斜（顺序是确定性的一部分）
NEIGHBORS8 = ((1, 0), (0, 1), (-1, 0), (0, -1),
              (1, 1), (1, -1), (-1, 1), (-1, -1))


@dataclass
class Grid:
    width: int
    height: int
    obstacles: set = field(default_factory=set)
    allow_diagonal: bool = False

    def __post_init__(self):
        if self.width < 1 or self.height < 1:
            raise ValueError("栅格尺寸必须为正")

    # ---------------------------------------------------------------- 查询
    def inside(self, cell) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def free(self, cell) -> bool:
        return self.inside(cell) and cell not in self.obstacles

    def neighbors(self, cell):
        """返回 [(邻居, 步价)]。斜步价 √2；越界/障碍的邻居直接不出现在表里。"""
        moves = NEIGHBORS8 if self.allow_diagonal else NEIGHBORS4
        out = []
        for dx, dy in moves:
            nxt = (cell[0] + dx, cell[1] + dy)
            if not self.free(nxt):
                continue
            if dx and dy:
                # 更符合直觉的防"穿角"：两条正交边都通才允许斜着穿
                if not (self.free((cell[0] + dx, cell[1])) and self.free((cell[0], cell[1] + dy))):
                    continue
                out.append((nxt, SQRT2))
            else:
                out.append((nxt, 1.0))
        return out

    def require_free(self, *cells) -> None:
        for cell in cells:
            if not self.free(cell):
                raise ValueError(f"格子不可用（越界或障碍）：{cell}")


def random_grid(width: int = 40, height: int = 30, density: float = 0.25,
                seed: int = 1, allow_diagonal: bool = False,
                start=(0, 0), goal=None) -> Grid:
    """种子化随机障碍图；保证 start/goal 及其不在障碍上（挪开而不是重掷——确定性优先）。"""
    rng = random.Random(seed)
    goal = goal if goal is not None else (width - 1, height - 1)
    obstacles = set()
    for x in range(width):
        for y in range(height):
            if (x, y) in (start, goal):
                continue
            if rng.random() < density:
                obstacles.add((x, y))
    grid = Grid(width=width, height=height, obstacles=obstacles,
                allow_diagonal=allow_diagonal)
    grid.require_free(start, goal)
    return grid


def corridor(length: int = 3) -> Grid:
    """手算基准：1×N 直走廊（4 邻域）。"""
    return Grid(width=length, height=1)


def walled_scene() -> tuple[Grid, tuple, tuple]:
    """手算基准：5×5；目标 (2,4) 三面被围（左 (1,4)、右 (3,4)、上 (2,3) 皆墙），
    再加两格装饰墙——4 邻域下目标不可达（第一版只围了上面三格，
    目标仍能从侧下方进入，被"应当不可达"的测试当场抓出）。"""
    wall = {(1, 3), (2, 3), (3, 3), (1, 4), (3, 4)}
    grid = Grid(width=5, height=5, obstacles=set(wall))
    return grid, (0, 0), (2, 4)
