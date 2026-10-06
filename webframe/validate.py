"""webframe/validate.py —— JSON 体校验：schema 是一张"字段 -> (类型, 必填)"表。

设计取舍：
    - schema 就用 Python 类型本身：str/int/float/(int, float)/bool；
    - **bool 永远不许冒充 int/float**——bool 是 int 的子类，B31 的 INCR 与
      B23 的梯度检查都被这个坑咬过，这里在框架层一刀切掉；
    - 未知字段默认拒绝：静默忽略拼错的键 = "看起来成功了"，最难查（B31 原话）；
    - 错误一次性报全（不逐个挤牙膏）。
"""
from __future__ import annotations


class ValidationError(ValueError):
    """schema 不满足（框架映射 400）。"""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("；".join(problems))


def _type_name(t) -> str:
    if isinstance(t, tuple):
        return "/".join(_type_name(x) for x in t)
    return t.__name__


def _check_type(value, expected) -> bool:
    if isinstance(expected, tuple):
        return any(_check_type(value, t) for t in expected)
    if expected in (int, float) and isinstance(value, bool):
        return False                       # bool 冒充数字：一律不收
    if expected is float and isinstance(value, int) and not isinstance(value, bool):
        return True                        # int 可以当 float 用（JSON 只有 number）
    return isinstance(value, expected)


def validate(payload, schema: dict, *, allow_unknown: bool = False) -> dict:
    """payload 必须是 dict；按 schema 校验，违规一次性抛 ValidationError。"""
    problems: list[str] = []
    if not isinstance(payload, dict):
        raise ValidationError([f"请求体必须是 JSON 对象，收到 {type(payload).__name__}"])
    known = set(schema)
    if not allow_unknown:
        unknown = sorted(set(payload) - known)
        if unknown:
            problems.append(f"不认识的字段：{unknown}")
    for field, spec in schema.items():
        expected, required = spec
        if field not in payload:
            if required:
                problems.append(f"缺少必填字段 {field!r}")
            continue
        if not _check_type(payload[field], expected):
            problems.append(f"字段 {field!r} 须为 {_type_name(expected)}，"
                            f"收到 {type(payload[field]).__name__}")
    if problems:
        raise ValidationError(problems)
    return payload
