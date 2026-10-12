"""linkbox/app.py —— 产品应用：短链（继承 B31 全部能力）+ 文本暂存 + 文件暂存。

继承而不是包装：LinkBoxApp 拥有 ShortUrlApp 的全部路由与处理器，
routes() 追加暂存与产品页路由。暂存内容的展示走 html.escape——
用户输入永远不当 HTML 渲染（B32 的 XSS 实验教出来的规矩）。

M2 起的暂存增强：
    - 可选访问口令：API 侧 401（缺/错都不放行），页面侧 200 + 口令表单；
      判定次序固定 404 -> 410 -> 401，存在性与过期状态不因口令隐藏；
    - 二维码：/s/<码>/qr.svg 独立路由 + 内容页内联一份，编码的都是
      查看页绝对 URL（Host 头拼装，同 B31 短链"只给人看"的口径）。
      注意路由顺序：/s/*/qr.svg 必须排在 /s/* 之前（fnmatch 首中分发）。

轮八新增文件暂存（/f/ 命名空间，与 /s/ 同语义不同载荷）：
    - 上传 POST /api/files?name=&ttl_hours=&passcode=，请求体是**原始字节**
      （浏览器 fetch 直接把 File 对象当 body 发，不需要 multipart）；
    - 下载 GET /f/<码> = 直接下发字节 + attachment 头（扫码即下载）；
      设了口令的先出表单页（POST 提交，口令不进 URL）；
    - 二维码 /f/<码>/qr.svg 同 /s/ 口径，只编码查看（下载）页绝对 URL。
"""
from __future__ import annotations

import html
import json
import threading
import urllib.parse
from pathlib import Path

from b31.app import HTML_TYPE, JSON_TYPE, STATIC_TYPES, TEXT_TYPE, ShortUrlApp
from b31.codec import is_code_shape

from .files import (MAX_FILE_BYTES, FileError, FileGone,     # noqa: E402
                    content_disposition, content_disposition_inline,
                    preview_content_type)
from .qr import qr_svg
from .stash import MAX_CONTENT, StashError, StashGone, StashStore

NO_STORE = ("Cache-Control", "no-store")
SVG_TYPE = ("Content-Type", "image/svg+xml")
DOWNLOAD_TYPE = ("Content-Type", "application/octet-stream")
QR_SUFFIX = "/qr.svg"
DELETE_SUFFIX = "/delete"              # L3：查看页删除表单的提交地址后缀
VIEW_SUFFIX = "/view"                  # 升级动作②：文件内联预览（/f/<码>/view）


class LinkBoxApp(ShortUrlApp):
    def __init__(self, store, web_root, *, stash: StashStore, files=None, **kwargs):
        super().__init__(store, web_root, **kwargs)
        self.stash = stash
        self.files = files
        # 口令失败限流账（2026-10-07 审查收口）：code -> (失败次数, 窗口起点)
        self._pass_fails: dict[str, tuple[int, float]] = {}
        self._pass_lk = threading.Lock()

    PASS_MAX_FAILS = 5                    # 窗口内允许的口令失败次数
    PASS_WINDOW = 600.0                   # 失败计数窗口（秒）
    PASS_FAILS_CAP = 10000                # 失败表键数上限（防随机 code 刷内存）

    def routes(self) -> list:
        return super().routes() + [
            # L3 短链删除：DELETE /api/links/<码>（B31 原路由只读，删除走产品层）。
            # GET /api/links/* 只注册了 GET/HEAD，DELETE 首中本条。
            (("DELETE", "/api/links/*"), self.delete_link),
            (("POST", "/api/stash"), self.create_stash),
            (("GET", "/api/stash/*"), self.stash_api),
            (("DELETE", "/api/stash/*"), self.delete_stash),
            (("GET", f"/s/*{QR_SUFFIX}"), self.stash_qr),
            # L3 暂存删除表单：必须在 POST /s/* 之前注册（fnmatch 首中分发）
            (("POST", f"/s/*{DELETE_SUFFIX}"), self.stash_delete_page),
            (("GET", "/s/*"), self.stash_page),
            (("HEAD", "/s/*"), self.stash_page),
            (("POST", "/s/*"), self.stash_page_post),   # M3：口令表单，口令不进 URL
            (("POST", "/api/files"), self.create_file),
            (("GET", "/api/files/*"), self.file_api),
            (("DELETE", "/api/files/*"), self.file_api),
            (("GET", f"/f/*{QR_SUFFIX}"), self.file_qr),
            # 升级动作②（2026-10-12）：内联预览——必须在 /f/* 之前注册（fnmatch 首中）
            (("GET", f"/f/*{VIEW_SUFFIX}"), self.file_view),
            (("GET", "/f/*"), self.file_download),
            (("HEAD", "/f/*"), self.file_download),
            (("POST", "/f/*"), self.file_download_post),
            # 访问趋势统计（2026-10-12）：流水由引擎层 Store 记账（visit/log_click），
            # 本路由只做参数校验与组装。注意必须排在 /api/stash/* 之前——
            # fnmatch 首中分发，/api/stats/clicks 不与 /api/stash/* 冲突但保持习惯一致。
            (("GET", "/api/stats/clicks"), self.clicks_api),
            # 共享资产：sync_assets 把 webkit/kb.css 落到 web/assets/，
            # 而 B31 的静态白名单只有根级三个名字——没有这条路由，
            # 产品页的 <link assets/kb.css> 永远 404（整页裸样式，2026-10-07 实测）。
            (("GET", "/assets/*"), self.assets_static),
        ]

    def assets_static(self, request):
        name = request.path[len("/assets/"):].lstrip("/")
        if not name:
            return 404, [TEXT_TYPE], "资源不存在".encode("utf-8")
        data = self.read_static("assets/" + name)
        if data is None or Path(name).suffix not in STATIC_TYPES:
            return 404, [TEXT_TYPE], "资源不存在".encode("utf-8")
        return 200, [("Content-Type", STATIC_TYPES[Path(name).suffix]), NO_STORE], data

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
        unknown = sorted(set(payload) - {"content", "ttl_hours", "passcode"})
        if unknown:
            return 400, [JSON_TYPE], self._error(
                f"不认识的字段：{unknown}，只接受 content、ttl_hours 与 passcode")
        content = payload.get("content")
        if not isinstance(content, str):
            return 400, [JSON_TYPE], self._error("content 必须是字符串")
        ttl = payload.get("ttl_hours", 24.0)
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
            return 400, [JSON_TYPE], self._error("ttl_hours 必须是数字")
        passcode = payload.get("passcode")
        if passcode is not None and not isinstance(passcode, str):
            return 400, [JSON_TYPE], self._error("passcode 必须是字符串")
        try:
            rec = self.stash.create(content, ttl_hours=ttl, now=self.clock(),
                                    passcode=passcode)
        except StashError as exc:
            return 400, [JSON_TYPE], self._error(str(exc))
        body = self._json({"code": rec.code, "url": f"/s/{rec.code}",
                           "expires_at": rec.expires_at,
                           "created_at": rec.created_at,
                           "protected": rec.has_passcode})
        return 201, [JSON_TYPE, ("Location", f"/s/{rec.code}"), NO_STORE], body

    # ------------------------------------------------ 暂存：API 查询 / 删除
    def _passcode_of(self, request) -> str | None:
        """查询串里的 passcode（netlab 已做百分号解码与 + 归空格）。"""
        return dict(request.query).get("passcode")

    def _verify_passcode(self, store, code: str, candidate: str | None):
        """口令校验 + 按 code 失败限流（2026-10-07 审查收口：此前失败无计数，
        叠加旧版 code 可枚举，弱口令可在线爆破）。返回 True=通过 / False=不对 /
        "locked"=限流中。锁定期内不做 PBKDF2 计算——拒绝也要拒绝得便宜。"""
        now = self.clock()
        with self._pass_lk:
            fails, first = self._pass_fails.get(code, (0, 0.0))
            if fails and now - first >= self.PASS_WINDOW:
                self._pass_fails.pop(code, None)
                fails = 0
            if fails >= self.PASS_MAX_FAILS:
                return "locked"
            if len(self._pass_fails) > self.PASS_FAILS_CAP:
                for key in [k for k, (_, t0) in self._pass_fails.items()
                            if now - t0 >= self.PASS_WINDOW]:
                    self._pass_fails.pop(key, None)
        ok = store.verify_passcode(code, candidate)
        with self._pass_lk:
            if ok:
                self._pass_fails.pop(code, None)
            else:
                fails, first = self._pass_fails.get(code, (0, now))
                self._pass_fails[code] = (fails + 1, first if fails else now)
        return ok

    def stash_api(self, request):
        code, problem = self._code_from(request.path, "/api/stash/")
        if problem:     # M1 曾直接 return problem（裸字符串会砸了分发层的解包）——潜伏 bug，M2 顺手修掉
            return 400, [JSON_TYPE], self._error(problem)
        if not is_code_shape(code):
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        try:
            rec = self.stash.get(code, now=self.clock())
        except StashGone:
            return 410, [JSON_TYPE, NO_STORE], self._error("暂存已过期")
        if rec is None:
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        if rec.has_passcode:
            verdict = self._verify_passcode(self.stash, code,
                                            self._passcode_of(request))
            if verdict == "locked":
                return 429, [("Retry-After", "60"), JSON_TYPE, NO_STORE], \
                    self._error("口令尝试过于频繁：请稍后再来")
            if not verdict:
                return 401, [JSON_TYPE, NO_STORE], \
                    self._error("这条暂存设有访问口令：请在查询串带 ?passcode=…")
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
            return 400, [JSON_TYPE], self._error(problem)
        if not is_code_shape(code):
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        # M1 语义保持：过期行删除等价清理，照样 204（内容已不可读，无泄漏）
        try:
            rec = self.stash.get(code, now=self.clock())
        except StashGone:
            self.stash.delete(code)
            return 204, [JSON_TYPE], b""
        if rec is None:
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        if rec.has_passcode:
            verdict = self._verify_passcode(self.stash, code,
                                            self._passcode_of(request))
            if verdict == "locked":
                return 429, [("Retry-After", "60"), JSON_TYPE, NO_STORE], \
                    self._error("口令尝试过于频繁：请稍后再来")
            if not verdict:
                return 401, [JSON_TYPE, NO_STORE], \
                    self._error("这条暂存设有访问口令：请在查询串带 ?passcode=…")
        self.stash.delete(code)
        return 204, [JSON_TYPE], b""

    # ------------------------------------------------ L3：短链删除 / 暂存查看页删除
    def overview(self, request: Request):
        """2026-10-11 ECharts 化：在 B31 overview（stats+top5）上增量补
        inventory（暂存/文件在存数），旧键原样保留。"""
        status, headers, body = super().overview(request)
        if status != 200:
            return status, headers, body
        import json as _json
        payload = _json.loads(body.decode("utf-8"))
        payload["inventory"] = {"stashes": self.stash.count(),
                                "files": self.files.count() if self.files else 0}
        return status, headers, self._json(payload)

    def delete_link(self, request):
        """DELETE /api/links/<码>：删除短链（管理能力，B31 引擎新增 Store.delete）。
        404 不存在 / 204 已删；删掉后再访问 /l/<码> 自然 404。"""
        code, problem = self._code_from(request.path, "/api/links/")
        if problem is not None:
            return 400, [JSON_TYPE], self._error(problem)
        if not self.store.delete(code):
            return 404, [JSON_TYPE], self._error(f"短码 {code} 不存在")
        return 204, [JSON_TYPE], b""

    # ------------------------------------------------ 访问趋势统计（GET /api/stats/clicks）
    def clicks_api(self, request):
        """近 N 天逐日访问曲线 + 对象排行。days/kind 都做白名单校验——
        流水表的治理在引擎层（保留窗口 + 行数上限），这里只管别让脏参数进 SQL。"""
        values = dict(request.query)
        raw_days = values.get("days", "14")
        try:
            days = int(raw_days)
        except ValueError:
            return 400, [JSON_TYPE], self._error(f"days 要写成整数，收到 {raw_days!r}")
        kind = values.get("kind")
        if kind == "":
            kind = None
        if kind is not None and kind not in ("link", "stash", "file"):
            return 400, [JSON_TYPE], \
                self._error(f"kind 只接受 link/stash/file，收到 {kind!r}")
        try:
            series = self.store.click_series(days, kind)
            top = self.store.click_top(days, limit=8, kind=kind)
            total = self.store.clicks_total(days, kind)
        except ValueError as exc:
            return 400, [JSON_TYPE], self._error(str(exc))
        # 未指定 kind 时附带三条分线数据（前端趋势图一次拉齐，不用发三个请求）
        by_kind = None if kind is not None else {
            k: self.store.click_series(days, k) for k in ("link", "stash", "file")}
        body = self._json({"days": max(1, min(days, 90)), "kind": kind,
                           "total": total, "series": series,
                           "series_by_kind": by_kind, "top": top})
        return 200, [JSON_TYPE, NO_STORE], body

    def _form_fields(self, request) -> tuple[dict | None, tuple | None]:
        """口令/删除表单共用的表单体解析（与 stash_page_post 同口径）。"""
        ctype = request.header("content-type")
        if ctype is not None and \
                ctype.split(";")[0].strip() != "application/x-www-form-urlencoded":
            return None, (415, [TEXT_TYPE],
                          "表单要用 application/x-www-form-urlencoded 提交\n".encode("utf-8"))
        try:
            fields = urllib.parse.parse_qs(request.body.decode("utf-8"),
                                           keep_blank_values=True)
        except UnicodeDecodeError:
            return None, (400, [TEXT_TYPE], "表单体不是 UTF-8\n".encode("utf-8"))
        return fields, None

    def stash_delete_page(self, request):
        """查看页删除表单的提交端：404 -> 410（顺手清残留）-> 口令门 -> 删除。
        口令走请求体（与 M3 口令表单同口径，不进 URL/浏览器历史）。"""
        stem = request.path[:-len(DELETE_SUFFIX)] if \
            request.path.endswith(DELETE_SUFFIX) else request.path
        code, problem = self._code_from(stem, "/s/")
        if problem:
            return 400, [TEXT_TYPE], problem.encode("utf-8")
        fields, err = self._form_fields(request)
        if err:
            return err
        candidate = (fields.get("passcode") or [None])[0]
        try:
            rec = self.stash.get(code, now=self.clock())
        except StashGone:
            self.stash.delete(code)      # 过期行删除等价清理（与 delete_stash 同口径）
            return 200, [HTML_TYPE, NO_STORE], \
                self._page("已删除", "这条暂存已过期，现在顺手清掉了残留记录。")
        if rec is None:
            return 404, [HTML_TYPE], \
                self._page("暂存不存在", f"没有找到 {code!r}。")
        if rec.has_passcode:
            verdict = self._verify_passcode(self.stash, code, candidate)
            if verdict == "locked":
                return 429, [HTML_TYPE, ("Retry-After", "60"), NO_STORE], \
                    self._page("尝试过于频繁", "口令尝试太多次：请稍后再来。")
            if not verdict:
                hint = "口令不正确，没有删除。" if candidate is not None else ""
                return 200, [HTML_TYPE, NO_STORE], \
                    self._page("请确认", f"暂存 {code} 设有访问口令，删除需先输口令。",
                               extra_html=self._delete_form(code, protected=True, hint=hint))
        self.stash.delete(code)
        return 200, [HTML_TYPE, NO_STORE], \
            self._page("已删除", f"暂存 {code} 已删除，原链接即刻失效。")

    def _delete_form(self, code: str, *, protected: bool = False,
                     hint: str = "") -> str:
        """查看页的删除表单（受保护的多一个口令框）。口令提交走 POST body。"""
        hint_html = f'<p class="err">{html.escape(hint)}</p>' if hint else ""
        pass_input = '\n  <input type="password" name="passcode" placeholder="访问口令">' \
            if protected else ""
        return (f'{hint_html}<form method="post" action="/s/{code}/delete" class="del">'
                f'{pass_input}\n  <button type="submit">删除这条暂存</button></form>')

    def _query_param(self, request, key: str) -> str | None:
        return dict(request.query).get(key)

    def create_file(self, request):
        if self.files is None:
            return 501, [JSON_TYPE], self._error("本实例未装配文件暂存")
        body = request.body
        if len(body) > MAX_FILE_BYTES:
            return 413, [JSON_TYPE], self._error(
                f"文件 {len(body)} 字节，上限 {MAX_FILE_BYTES}")
        if not body:
            return 400, [JSON_TYPE], self._error("请求体为空——请把文件字节作为请求体上传")
        name = self._query_param(request, "name") or ""
        raw_ttl = self._query_param(request, "ttl_hours")
        try:
            ttl = float(raw_ttl) if raw_ttl else 24.0
        except ValueError:
            return 400, [JSON_TYPE], self._error("ttl_hours 必须是数字")
        passcode = self._query_param(request, "passcode")
        try:
            rec = self.files.create(body, name, ttl_hours=ttl, now=self.clock(),
                                    passcode=passcode)
        except FileError as exc:
            return 400, [JSON_TYPE], self._error(str(exc))
        payload = {"code": rec.code, "url": f"/f/{rec.code}", "name": rec.name,
                   "size": rec.size, "created_at": rec.created_at,
                   "expires_at": rec.expires_at, "protected": rec.has_passcode}
        return 201, [JSON_TYPE, ("Location", f"/f/{rec.code}"), NO_STORE], \
            self._json(payload)

    # ------------------------------------------------ 文件暂存：API 查询 / 删除
    def file_api(self, request):
        code, problem = self._code_from(request.path, "/api/files/")
        if problem:
            return 400, [JSON_TYPE], self._error(problem)
        if not is_code_shape(code):
            return 404, [JSON_TYPE], self._error(f"文件 {code!r} 不存在")
        try:
            rec = self.files.get(code, now=self.clock())
        except FileGone:
            return 410, [JSON_TYPE, NO_STORE], self._error("文件已过期")
        if rec is None:
            return 404, [JSON_TYPE], self._error(f"文件 {code!r} 不存在")
        if rec.has_passcode:
            verdict = self._verify_passcode(self.files, code,
                                            self._passcode_of(request))
            if verdict == "locked":
                return 429, [("Retry-After", "60"), JSON_TYPE, NO_STORE], \
                    self._error("口令尝试过于频繁：请稍后再来")
            if not verdict:
                return 401, [JSON_TYPE, NO_STORE], \
                    self._error("这个文件设有访问口令：请在查询串带 ?passcode=…")
        if request.method == "DELETE":
            self.files.delete(code)
            return 204, [JSON_TYPE], b""
        body = self._json({"code": rec.code, "name": rec.name, "size": rec.size,
                           "created_at": rec.created_at,
                           "expires_at": rec.expires_at})
        return 200, [JSON_TYPE, NO_STORE], body

    # ------------------------------------------------ 文件暂存：下载（/f/<code>）
    def _file_response(self, code: str, candidate: str | None,
                       method: str = "GET", inline: bool = False):
        """GET/HEAD/口令表单/预览共用：404 -> 410 -> 口令门 -> 字节下发。
        method 用于访问流水口径：HEAD 探活不算，GET/口令表单 POST 都算一次；
        inline（/view 预览）也不算——预览是衍生查看，下载才算一次取件。"""
        try:
            rec = self.files.get(code, now=self.clock())
        except FileGone:
            return 410, [HTML_TYPE], \
                self._page("文件已过期", "这个文件已到期被清除（内容不保留）。")
        if rec is None:
            return 404, [HTML_TYPE], \
                self._page("文件不存在", f"没有找到 {code!r}。")
        if rec.has_passcode:
            verdict = self._verify_passcode(self.files, code, candidate)
            if verdict == "locked":
                return 429, [HTML_TYPE, ("Retry-After", "60"), NO_STORE], \
                    self._page("尝试过于频繁", "口令尝试太多次：请稍后再来。")
            if not verdict:
                hint = "口令不正确，再试一次。" if candidate is not None else ""
                return 200, [HTML_TYPE, NO_STORE], \
                    self._pass_form(code, hint, noun="文件")
        if inline:
            ctype = preview_content_type(rec.name)
            if ctype is None:
                return 415, [HTML_TYPE, NO_STORE], \
                    self._page("不支持在线预览",
                               f"「{rec.name}」不是可预览类型（图片 / PDF / 文本），"
                               "请回到下载链接直接取件。")
        data = self.files.read(code)
        if method != "HEAD" and not inline:
            self.store.log_click("file", code, now=self.clock())
        if inline:
            # CSP sandbox：SVG 可携带 <script>，该头让浏览器把响应当沙箱文档
            # 渲染——脚本/表单/同源访问一律禁止（XSS 的最后一道闸，口径同
            # files.py 头注释：attachment 是默认闸，预览是白名单 + 沙箱）。
            return 200, [("Content-Type", ctype),
                         ("Content-Disposition", content_disposition_inline(rec.name)),
                         ("Content-Security-Policy", "sandbox"),
                         NO_STORE], data
        return 200, [DOWNLOAD_TYPE,
                     ("Content-Disposition", content_disposition(rec.name)),
                     NO_STORE], data

    def file_view(self, request):
        """GET /f/<code>/view：内联预览（升级动作②）。白名单类型才渲染，
        口令门与下载同门（?passcode= 或已过表单）。不记取件流水。"""
        stem = request.path[:-len(VIEW_SUFFIX)] if \
            request.path.endswith(VIEW_SUFFIX) else request.path
        code, problem = self._code_from(stem, "/f/")
        if problem:
            return 400, [TEXT_TYPE], problem.encode("utf-8")
        if not is_code_shape(code):
            return 404, [HTML_TYPE], \
                self._page("文件不存在", f"没有找到 {code!r}。")
        return self._file_response(code, self._passcode_of(request),
                                   method=request.method, inline=True)

    def file_download(self, request):
        code, problem = self._code_from(request.path, "/f/")
        if problem:
            return 400, [TEXT_TYPE], problem.encode("utf-8")
        if not is_code_shape(code):
            return 404, [HTML_TYPE], \
                self._page("文件不存在", f"没有找到 {code!r}。")
        return self._file_response(code, self._passcode_of(request),
                                   method=request.method)

    def file_download_post(self, request):
        """口令表单的 POST 提交——口令走请求体，成功即下载（不进 URL/历史）。"""
        code, problem = self._code_from(request.path, "/f/")
        if problem:
            return 400, [TEXT_TYPE], problem.encode("utf-8")
        if not is_code_shape(code):
            return 404, [HTML_TYPE], \
                self._page("文件不存在", f"没有找到 {code!r}。")
        ctype = request.header("content-type")
        if ctype is not None and \
                ctype.split(";")[0].strip() != "application/x-www-form-urlencoded":
            return 415, [TEXT_TYPE], \
                "表单要用 application/x-www-form-urlencoded 提交\n".encode("utf-8")
        try:
            fields = urllib.parse.parse_qs(request.body.decode("utf-8"),
                                           keep_blank_values=True)
        except UnicodeDecodeError:
            return 400, [TEXT_TYPE], "表单体不是 UTF-8\n".encode("utf-8")
        candidate = (fields.get("passcode") or [None])[0]
        return self._file_response(code, candidate, method="POST")

    def file_qr(self, request):
        """下载页 URL 的独立 SVG——只编码 /f/<码>，不编码口令。"""
        stem = request.path[:-len(QR_SUFFIX)] if \
            request.path.endswith(QR_SUFFIX) else request.path
        code, problem = self._code_from(stem, "/f/")
        if problem:
            return 400, [TEXT_TYPE], problem.encode("utf-8")
        if not is_code_shape(code):
            return 404, [JSON_TYPE], self._error(f"文件 {code!r} 不存在")
        try:
            rec = self.files.get(code, now=self.clock())
        except FileGone:
            return 410, [JSON_TYPE, NO_STORE], self._error("文件已过期")
        if rec is None:
            return 404, [JSON_TYPE], self._error(f"文件 {code!r} 不存在")
        svg = qr_svg(self._abs_view_url(f"/f/{code}", request))
        headers = [SVG_TYPE, NO_STORE]
        if (dict(request.query).get("download") or "") == "1":
            # L1 二维码下载（2026-10-07 功能增强）：物料存图/打印；code 已过形状闸，头部安全
            headers.append(("Content-Disposition", "attachment; filename=qr-file-" + code + ".svg"))
        return 200, headers, svg.encode("utf-8")

    # ------------------------------------------------ 暂存：浏览页（/s/<code>）
    def stash_page(self, request):
        code, problem = self._code_from(request.path, "/s/")
        if problem:
            return 400, [TEXT_TYPE], problem.encode("utf-8")
        if not is_code_shape(code):
            return 404, [HTML_TYPE], \
                self._page("暂存不存在", f"没有找到 {code!r}。")
        return self._render_stash(request, code, self._passcode_of(request))

    def stash_page_post(self, request):
        """M3：口令表单的 POST 提交——口令走请求体，不进 URL/浏览器历史。"""
        code, problem = self._code_from(request.path, "/s/")
        if problem:
            return 400, [TEXT_TYPE], problem.encode("utf-8")
        if not is_code_shape(code):
            return 404, [HTML_TYPE], \
                self._page("暂存不存在", f"没有找到 {code!r}。")
        ctype = request.header("content-type")
        if ctype is not None and \
                ctype.split(";")[0].strip() != "application/x-www-form-urlencoded":
            return 415, [TEXT_TYPE], \
                "表单要用 application/x-www-form-urlencoded 提交\n".encode("utf-8")
        try:
            fields = urllib.parse.parse_qs(request.body.decode("utf-8"),
                                           keep_blank_values=True)
        except UnicodeDecodeError:
            return 400, [TEXT_TYPE], "表单体不是 UTF-8\n".encode("utf-8")
        candidate = (fields.get("passcode") or [None])[0]
        return self._render_stash(request, code, candidate)

    def _render_stash(self, request, code: str, candidate: str | None):
        """get/410/404 之后：口令门 -> 解锁渲染（GET 查询串与 POST 表单共用）。"""
        try:
            rec = self.stash.get(code, now=self.clock())
        except StashGone:
            return 410, [HTML_TYPE], \
                self._page("暂存已过期", "这条暂存已到期被清除（内容不保留）。")
        if rec is None:
            return 404, [HTML_TYPE], \
                self._page("暂存不存在", f"没有找到 {code!r}。")
        if rec.has_passcode:
            verdict = self._verify_passcode(self.stash, code, candidate)
            if verdict == "locked":
                return 429, [HTML_TYPE, ("Retry-After", "60"), NO_STORE], \
                    self._page("尝试过于频繁", "口令尝试太多次：请稍后再来。")
            if not verdict:
                hint = "口令不正确，再试一次。" if candidate is not None else ""
                page = self._pass_form(code, hint)
                return 200, [HTML_TYPE, NO_STORE], page
        qr = qr_svg(self._stash_view_url(code, request))
        # 访问流水：口令解锁后的渲染也只算一次（GET 查询串与 POST 表单共用本出口）；
        # HEAD 是探活不算访问，与 B31 短链同口径。
        if request.method != "HEAD":
            self.store.log_click("stash", code, now=self.clock())
        body = self._page(f"暂存 {rec.code}", html.escape(rec.content),
                          note=f"创建于 {rec.created_at:.0f}，"
                               f"过期于 {rec.expires_at:.0f}（Unix 时间）"
                               + ("（设有访问口令）" if rec.has_passcode else ""),
                          qr=qr, qr_download="/s/" + code + "/qr.svg",
                          extra_html=self._delete_form(code,
                                                       protected=rec.has_passcode))
        return 200, [HTML_TYPE, NO_STORE], body

    # ------------------------------------------------ 暂存：二维码（/s/<code>/qr.svg）
    def stash_qr(self, request):
        """查看页 URL 的独立 SVG（给 <img>/分享用；页面内还内联了一份）。
        只编码 URL，不编码内容也不编码口令——扫出来的就是查看页地址。"""
        stem = request.path[:-len(QR_SUFFIX)] if \
            request.path.endswith(QR_SUFFIX) else request.path
        code, problem = self._code_from(stem, "/s/")
        if problem:
            return 400, [TEXT_TYPE], problem.encode("utf-8")
        if not is_code_shape(code):
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        try:
            rec = self.stash.get(code, now=self.clock())
        except StashGone:
            return 410, [JSON_TYPE, NO_STORE], self._error("暂存已过期")
        if rec is None:
            return 404, [JSON_TYPE], self._error(f"暂存 {code!r} 不存在")
        svg = qr_svg(self._stash_view_url(code, request))
        headers = [SVG_TYPE, NO_STORE]
        if (dict(request.query).get("download") or "") == "1":
            headers.append(("Content-Disposition", "attachment; filename=qr-stash-" + code + ".svg"))
        return 200, headers, svg.encode("utf-8")

    def _abs_view_url(self, path: str, request) -> str:
        """查看/下载页绝对 URL。Host 头是客户端可控的——和 B31 短链同口径：
        只用于"给人看/给手机扫"，访问本身不依赖它；放公网要改成配置域名（写进局限）。"""
        host = (request.header("host") or "").strip()
        if not host or len(host) > 120 or not host.isascii() \
                or any(ch in host for ch in "\r\n@ / "):
            host = self.self_hosts[0]
        if ":" not in host and self.port not in (None, 80, 443):
            host = f"{host}:{self.port}"
        return f"http://{host}{path}"

    def _stash_view_url(self, code: str, request) -> str:
        return self._abs_view_url(f"/s/{code}", request)

    def _pass_form(self, code: str, hint: str = "", noun: str = "暂存") -> bytes:
        """口令表单页。M3 起用 POST 提交（口令不进 URL/历史记录）；
        GET 查询串 ?passcode= 仍兼容程序化访问，局限已登记 README。
        noun 区分"暂存/文件"两种口令门文案。"""
        hint_html = f'<p class="err">{html.escape(hint)}</p>' if hint else ""
        page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>口令 · LinkBox</title>
<style>body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:2rem auto;max-width:46rem;padding:0 1rem;color:#16181d}}
h1{{font-size:1.3rem}}.note{{color:#5f6773;font-size:.9rem}}.err{{color:#b91c1c}}
input{{font-size:1rem;padding:.5rem .6rem;border:1px solid #c8cdd6;border-radius:6px;width:min(20rem,100%)}}
button{{font-size:1rem;padding:.5rem .9rem;border:0;border-radius:6px;background:#1d4ed8;color:#fff}}</style></head>
<body><h1>这个{noun}设有访问口令</h1>
{hint_html}
<form method="post"><input type="password" name="passcode" placeholder="访问口令" autofocus>
<button type="submit">查看</button></form>
<p class="note"><a href="/">← LinkBox 首页</a></p></body></html>"""
        return page.encode("utf-8")

    def _page(self, title: str, body_html: str, note: str = "",
              qr: str | None = None, qr_download: str | None = None,
              extra_html: str = "") -> bytes:
        safe_title = html.escape(title)
        note_html = f'<p class="note">{html.escape(note)}</p>' if note else ""
        qr_html = ""
        if qr:
            qr_html = f'<h2>扫码打开本页</h2>{qr}'
            if qr_download:
                qr_html += (f'<p class="note"><a href="{html.escape(qr_download)}?download=1">'
                            "下载二维码 SVG</a></p>")
        page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} · LinkBox</title>
<style>body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:2rem auto;max-width:46rem;padding:0 1rem;color:#16181d}}
pre{{white-space:pre-wrap;word-break:break-word;background:#0f1115;color:#e6e9ef;padding:1rem;border-radius:8px;font-size:15px}}
h1{{font-size:1.3rem}}h2{{font-size:1.05rem}}.note{{color:#5f6773;font-size:.9rem}}a{{color:#1d4ed8}}
svg{{background:#fff;border:1px solid #e3e6ec;border-radius:8px}}
form.del{{margin:1.5rem 0 0;padding-top:1rem;border-top:1px solid #e3e6ec}}
form.del input{{font-size:1rem;padding:.5rem .6rem;border:1px solid #c8cdd6;border-radius:6px;width:min(20rem,100%);margin-bottom:.5rem;display:block}}
form.del button{{font-size:.95rem;padding:.45rem .8rem;border:0;border-radius:6px;background:#b91c1c;color:#fff}}</style></head>
<body><h1>{safe_title}</h1>{note_html}<pre>{body_html}</pre>{qr_html}{extra_html}
<p class="note"><a href="/">← LinkBox 首页</a> · <a href="qr.svg">二维码单独打开</a></p></body></html>"""
        return page.encode("utf-8")
