"""webframe/template.py —— 模板片段：${name} 占位 + 默认转义 + Raw 显式放行。

为什么这么小：PRODUCTS.md §四.1 说"模板片段"，不是模板引擎——产品页的
业务判定全在服务端、页面由服务端拼装（B31/B32 的口径），缺的是一个
**不会忘转义**的拼装器。规则：
    - ${name} 替换为 esc(value)；想原样输出 HTML 就包 Raw()；
    - 缺键/传了没用的键都报错：模板拼错名字不该静默留一个 ${name} 在页面上。
"""
from __future__ import annotations

import html
import re

_PLACEHOLDER = re.compile(r"\$\{([a-z_][a-z0-9_]*)\}")


class Raw(str):
    """标记"我已经自己保证安全"的片段（比如现算的 SVG）。"""


def esc(value) -> str:
    """HTML 转义（含引号属性位）。"""
    return html.escape(str(value), quote=True)


def render(template: str, /, **values) -> str:
    """${name} 占位替换。值默认 esc()，Raw 包裹的原样输出；缺键/拼错键即抛错。"""
    used: set[str] = set()

    def sub(match: re.Match) -> str:
        name = match.group(1)
        used.add(name)
        if name not in values:
            raise KeyError(name)
        value = values[name]
        return value if isinstance(value, Raw) else esc(value)

    out = _PLACEHOLDER.sub(sub, template)
    unused = sorted(set(values) - used)
    if unused:
        raise KeyError(f"传了但模板没用到的值：{unused}")
    return out
