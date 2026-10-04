"""linkbox/app.py —— 产品应用：短链（继承 B31 全部能力）+ 文本暂存（新增）。

继承而不是包装：LinkBoxApp 拥有 ShortUrlApp 的全部路由与处理器，
routes() 追加暂存与产品页路由。暂存内容的展示走 html.escape——
用户输入永远不当 HTML 渲染（B32 的 XSS 实验教出来的规矩）。
"""
from __future__ import annotations

import html
import json

from b31.app import JSON_TYPE, ShortUrlApp
from b31.codec import is_code_shape

from .stash import MAX_CONTENT, StashError, StashGone, StashStore

NO_STORE = ("Cache-Control", "no-store")


class LinkBoxApp(ShortUrlApp):
    def __init__(self, store, web_root, *, stash: StashStore, **kwargs):
        super().__init__(store, web_root, **kwargs)
        self.stash = stash

    def routes(self) -> list:
        return super().routes() + [
            (("POST", "/api/stash"), self.create_stash),
            (("GET", "/api/stash/*"), self.stash_api),
            (("DELETE", "/api/stash/*"), self.delete_stash),
            (("GET", "/s/*"), self.stash_page),
            (("HEAD", "/s/*"), self.stash_page),
        ]

    # ------------------------------------------------ 请求体解析（沿用 B31 的校验次序）
    def _json_body(self, request) -> tuple[dict | None, tuple | None]:
        if len(request.body) > MAX_CONTENT + 1024:
            return None, (413, [JSON_TYPE],
                          self._error(f"请求体 {len(request.body)} 字节，上限 "
                                      f"{MAX_CONTENT + 1024}"))
        content_type = request.header("content-type")
        if content_type is not None and \
                content_type.split(";")[0].strip() != "application/json":
            return None, (415, [JSON_TYPE],
                          self._error(f"只接受 application/json，收到 "
                                      f"{content_type!r}"))
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except UnicodeDecodeError:
            return None, (400, [JSON_TYPE], self._error("请求体不是 UTF-8"))
        except json.JSONDecodeError as exc:
            return None, (400, [JSON_TYPE],
                          self._error(f"JSON 语法错误：{exc.msg}"))
        if not isinstance(payload, dict):
            return None, (400, [JSON_TYPE], self._error("请求体必须是 JSON 对象"))
        return payload, None

    # ------------------------------------------------ 暂存：创建
    def create_stash(self, request):
        payload, err = self._json_body(request)
        if err:
            return err
        unknown = sorted(set(payload) - {"content", "ttl_hours"})
        if unknown:
            return 400, [JSON_TYPE], self._error(
                f"不认识的字段：{unknown}，只接受 content 与 ttl_hours")
        content = payload.get("content")
        if not isinstance(content, str):
            return 400, [JSON_TYPE], self._error("content 必须是字符串")
        ttl = payload.get("ttl_hours", 24.0)
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
            return 400, [JSON_TYPE], self._error("ttl_hours 必须是数字")
        try:
            rec = self.stash.create(content, ttl_hours=ttl, now=self.clock())
        except StashError as exc:
            return 400, [JSON_TYPE], self._error(str(exc))
        body = self._json({"code": rec.code, "url": f"/s/{rec.code}",
                           "expires_at": rec.expires_at,
                           "created_at": rec.created_at})
        return 201, [JSON_TYPE, ("Location", f"/s/{rec.code}"), NO_STORE], body

    # ------------------------------------------------ 暂存：API 查询 / 删除
    def stash_api(self, request):
        code, problem = self._code_from(request.path, "/api/stash/")
        if problem:
            return problem
        if not is_code_shape(code):
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        try:
            rec = self.stash.get(code, now=self.clock())
        except StashGone:
            return 410, [JSON_TYPE, NO_STORE], self._error("暂存已过期")
        if rec is None:
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        if request.method == "DELETE":
            self.stash.delete(code)
            return 204, [JSON_TYPE], b""
        body = self._json({"code": rec.code, "content": rec.content,
                           "created_at": rec.created_at,
                           "expires_at": rec.expires_at})
        return 200, [JSON_TYPE, NO_STORE], body

    def delete_stash(self, request):
        code, problem = self._code_from(request.path, "/api/stash/")
        if problem:
            return problem
        if not is_code_shape(code):
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        if self.stash.delete(code):
            return 204, [JSON_TYPE], b""
        return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")

    # ------------------------------------------------ 暂存：浏览页（/s/<code>）
    def stash_page(self, request):
        code, problem = self._code_from(request.path, "/s/")
        if problem:
            return problem
        if not is_code_shape(code):
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        try:
            rec = self.stash.get(code, now=self.clock())
        except StashGone:
            return 410, [("Content-Type", "text/html; charset=utf-8")], \
                self._page("暂存已过期", "这条暂存已到期被清除（内容不保留）。")
        if rec is None:
            return 404, [("Content-Type", "text/html; charset=utf-8")], \
                self._page("暂存不存在", f"没有找到 {code!r}。")
        body = self._page(f"暂存 {rec.code}", html.escape(rec.content),
                          note=f"创建于 {rec.created_at:.0f}，"
                               f"过期于 {rec.expires_at:.0f}（Unix 时间）")
        return 200, [("Content-Type", "text/html; charset=utf-8"), NO_STORE], body

    def _page(self, title: str, body_html: str, note: str = "") -> bytes:
        safe_title = html.escape(title)
        note_html = f'<p class="note">{html.escape(note)}</p>' if note else ""
        page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} · LinkBox</title>
<style>body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:2rem auto;max-width:46rem;padding:0 1rem;color:#16181d}}
pre{{white-space:pre-wrap;word-break:break-word;background:#0f1115;color:#e6e9ef;padding:1rem;border-radius:8px;font-size:15px}}
h1{{font-size:1.3rem}}.note{{color:#5f6773;font-size:.9rem}}a{{color:#1d4ed8}}</style></head>
<body><h1>{safe_title}</h1>{note_html}<pre>{body_html}</pre>
<p class="note"><a href="/">← LinkBox 首页</a></p></body></html>"""
        return page.encode("utf-8")
