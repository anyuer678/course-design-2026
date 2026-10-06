"""simlab/record.py —— 统一运行记录格式 simlab-run/v1：一份记录 = 一次真实引擎运行。

格式契约（播放器/对比器的公共接口，改这里必须 bump 版本号）：
    {
      "format": "simlab-run/v1",
      "experiment": "b12-dijkstra",     # 实验类型（对应 engines 注册名）
      "title": "...",                   # 人读的标题
      "engine": "B12 algo.graph.dijkstra（原项目 import，未重写）",
      "params": {...},                  # 引擎输入（原样）
      "frames": [                       # 时间线：内容全部来自引擎真实产出
        {"t": 0, "caption": "...", "state": {...}, "highlights": [...]}, ...
      ],
      "metrics": {...},                 # 结果指标（与引擎直接调用对拍）
      "notes": "...",                   # 可选
      "seed": 7,                        # 可选（随机实验才需要）
      "created_at": 1696...             # 可选（build 自动补；确定性对比时剔除）
    }

校验纪律：错误一次性报全；save 用 allow_nan=False——Infinity/NaN 这种
"看起来是 JSON 其实不是"的东西在落盘那一刻就炸，而不是等播放器解码。
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

FORMAT = "simlab-run/v1"


class RecordError(ValueError):
    """记录不满足 simlab-run/v1（problems 一次性列全）。"""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("；".join(problems))


def build(experiment: str, title: str, engine: str, params: dict,
          frames: list, metrics: dict, *, notes: str = "",
          seed: int | None = None) -> dict:
    """组装一条记录并校验；created_at 由这里补（引擎保持纯函数，便于确定性对比）。"""
    record = {
        "format": FORMAT,
        "experiment": experiment,
        "title": title,
        "engine": engine,
        "params": params,
        "frames": frames,
        "metrics": metrics,
        "notes": notes,
    }
    if seed is not None:
        record["seed"] = seed
    record["created_at"] = time.time()
    validate(record)
    return record


def validate(record) -> dict:
    """校验 simlab-run/v1；通过则原样返回，失败抛 RecordError（problems 报全）。"""
    problems: list[str] = []
    if not isinstance(record, dict):
        raise RecordError([f"记录必须是 JSON 对象，收到 {type(record).__name__}"])
    if record.get("format") != FORMAT:
        problems.append(f"format 必须是 {FORMAT!r}，收到 {record.get('format')!r}")
    for field in ("experiment", "engine", "params", "frames", "metrics"):
        if field not in record:
            problems.append(f"缺少必填字段 {field!r}")
    if problems:
        raise RecordError(problems)
    for field in ("experiment", "engine"):
        if not isinstance(record[field], str) or not record[field]:
            problems.append(f"{field} 必须是非空字符串")
    if not isinstance(record["title"], str) or not record["title"]:
        problems.append("title 必须是非空字符串")
    if not isinstance(record["params"], dict):
        problems.append("params 必须是对象")
    if not isinstance(record["metrics"], dict):
        problems.append("metrics 必须是对象")
    _validate_frames(record.get("frames"), problems)
    if problems:
        raise RecordError(problems)
    return record


def _validate_frames(frames, problems: list[str]) -> None:
    if not isinstance(frames, list) or not frames:
        problems.append("frames 必须是非空数组")
        return
    for i, frame in enumerate(frames):
        if not isinstance(frame, dict):
            problems.append(f"frames[{i}] 必须是对象")
            continue
        if frame.get("t") != i:
            problems.append(f"frames[{i}].t 必须等于下标 {i}，收到 {frame.get('t')!r}")
        caption = frame.get("caption")
        if not isinstance(caption, str) or not caption:
            problems.append(f"frames[{i}].caption 必须是非空字符串")
        if "state" not in frame or not isinstance(frame["state"], dict):
            problems.append(f"frames[{i}].state 必须是对象")
        highlights = frame.get("highlights", [])
        if not isinstance(highlights, list):
            problems.append(f"frames[{i}].highlights 必须是数组（可缺省）")


def save(record: dict, path: str | Path) -> Path:
    """校验后落盘。allow_nan=False：非有限浮点在写盘那一刻就报错。"""
    validate(record)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def load(path: str | Path) -> dict:
    """读盘并校验。"""
    path = Path(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecordError([f"{path} 不是合法 JSON：{exc.msg}"]) from None
    return validate(record)


def finite(obj):
    """把 inf/-inf 转成 None（JSON 没有无穷大；引擎的 dist 快照里全是它）。"""
    if isinstance(obj, float) and math.isinf(obj):
        return None
    if isinstance(obj, list):
        return [finite(x) for x in obj]
    if isinstance(obj, tuple):
        return [finite(x) for x in obj]
    if isinstance(obj, dict):
        return {k: finite(v) for k, v in obj.items()}
    return obj
