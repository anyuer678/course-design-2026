"""simlab/engines —— 引擎注册表：实验名 -> 适配器（run(params) -> 记录骨架）。

适配器契约：
    - run(params: dict) 返回 build() 之前的记录骨架（无 created_at），
      引擎保持纯函数——同参数两次运行产出逐字节一致（确定性，B34 的纪律）；
    - PARAM_SCHEMA：参数表单描述（类型/默认值/说明），default 是可跑通的示例
      ——播放器据此生成参数表单（轮三之三：参数可调实时重算）；
    - 参数错误 raise ValueError（尽量让原项目的守卫先说话，适配层只补 JSON 形状检查）。
"""
from __future__ import annotations

from . import b12_dijkstra, b12_knapsack, b34_astar

ENGINES = {
    "b12-dijkstra": b12_dijkstra,
    "b12-knapsack": b12_knapsack,
    "b34-astar": b34_astar,
}


def run_experiment(name: str, params: dict) -> dict:
    if name not in ENGINES:
        raise ValueError(f"未知实验 {name!r}，可用：{sorted(ENGINES)}")
    return ENGINES[name].run(params)


def param_schema(name: str) -> dict:
    if name not in ENGINES:
        raise ValueError(f"未知实验 {name!r}，可用：{sorted(ENGINES)}")
    return ENGINES[name].PARAM_SCHEMA
