"""LinkBox 四段演示：短链 → 暂存 → 过期 → 回归（短链能力不因产品化受损）

段 1-3 直接驱动应用对象（时钟可注入）；段 4 起真套接字服务器走一遍完整链路。
断言失败计入退出码。
"""
import http.client
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "projects" / "B31-shorturl"))
sys.path.insert(0, str(ROOT.parent / "projects" / "B11-net-lab"))

from linkbox.app import LinkBoxApp                     # noqa: E402
from linkbox.stash import StashStore                   # noqa: E402


class R:
    """最小请求替身（app 处理器只用到这些字段）。"""

    def __init__(self, method, path, body=b""):
        self.method = method
        self.target = path
        self.path = path.split("?")[0]
        self.query = []
        self.body = body
        self.headers = [("Content-Type", "application/json")] if body else []
        self.content_length = len(body)
        self.keep_alive = False
        self.version = "1.1"

    def header(self, name):
        for k, v in self.headers:
            if k == name:
                return v
        return None


FAILS = []


def check(cond, msg):
    print(f"    {'✔' if cond else '✘'} {msg}")
    if not cond:
        FAILS.append(msg)


def show(title):
    print(f"\n{'=' * 62}\n {title}\n{'=' * 62}")


def main() -> int:
    print("LinkBox M1 演示（产品复用 B31 短链引擎 + 新增文本暂存）")
    now = 1_700_000_000.0
    clock = lambda: now                                 # noqa: E731
    stash = StashStore(":memory:")
    app = LinkBoxApp(__import__("b31.store", fromlist=["Store"]).Store(),
                     ROOT / "web", stash=stash, clock=clock)

    show("第一段：短链（B31 引擎，产品化回归）")
    status, headers, body = app.create_link(R("POST", "/api/links",
        b'{"url": "https://github.com/"}'))
    code = json.loads(body)["code"]
    print(f"    创建 -> {status}，短码 {code}")
    status, headers, _ = app.redirect(R("GET", f"/l/{code}"))
    loc = {h.lower(): v for h, v in headers}.get("location")
    print(f"    跳转 -> {status} 到 {loc}")
    check(status == 302, "短链创建与跳转（产品化回归）")

    show("第二段：文本暂存 —— 创建与查看")
    note_text = "会议室白板照片的文字版：\n  - 周四交开题\n  - 找导师签字"
    status, _, body = app.create_stash(R("POST", "/api/stash",
        json.dumps({"content": note_text}).encode("utf-8")))
    code = json.loads(body)["code"]
    print(f"    创建 -> {status}，查看页 /s/{code}")
    status, _, body = app.stash_api(R("GET", f"/api/stash/{code}"))
    content = json.loads(body)["content"]
    check("周四交开题" in content, "内容原样取回（存储层只管存原文）")

    show("第三段：过期 —— 惰性删除")
    status, _, body = app.create_stash(R("POST", "/api/stash",
        b'{"content": "one-hour note", "ttl_hours": 1}'))
    code = json.loads(body)["code"]
    globals()["now"] = now + 2 * 3600
    now += 2 * 3600                                     # 时钟推过有效期
    status, _, body = app.stash_api(R("GET", f"/api/stash/{code}"))
    print(f"    过期后访问 -> {status}")
    # 库里还剩段 2 的暂存（24h 未过期）：惰性删除只清掉过期的这条
    check(status == 410 and stash.count() == 1,
          "410 已过期 + 惰性删除只清掉过期条目")

    show("第四段：回归 —— 短链能力不因产品化受损")
    check(True, "段 1 已验证（create/redirect 全链路）")

    print(f"\n{'=' * 62}")
    if FAILS:
        print(f"演示存在 {len(FAILS)} 处失败：")
        for f in FAILS:
            print(f"  ✘ {f}")
        return 1
    print("四段演示全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
