/* CourseLab 共享脚本：API 封装 + 顶栏 + Toast + 细节辅助。（零依赖）
   1. CL.api 把网络错误归一成 {status:0, data:{error}} —— 页面不再因
      fetch 异常卡在"加载中"，统一走错误分支；
   2. CL.toast —— 全局通知（自动消失、aria-live），替代散落的提示；
   3. CL.busy —— 按钮在途状态（禁用 + aria-busy，文案由调用方改）；
   4. 跳转正文链接 + 导航当前页高亮（aria-current）。 */
(function () {
  "use strict";
  var CL = window.CL = {};

  CL.api = function (path, opts) {
    opts = opts || {};
    var init = { method: opts.method || "GET", headers: {} };
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(path, init).then(function (r) {
      return r.json().then(function (data) {
        return { status: r.status, data: data };
      });
    }).catch(function () {
      // 网络层错误归一：调用方只需处理 data.error，不再各自兜底
      return { status: 0, data: { error: "网络错误，请确认服务是否在运行。" } };
    });
  };

  CL.el = function (tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };

  CL.param = function (name) {
    return new URLSearchParams(location.search).get(name) || "";
  };

  CL.roleName = function (r) {
    return r === "admin" ? "管理员" : r === "teacher" ? "教师" : "学生";
  };

  CL.nextTarget = function () {
    var next = CL.param("next");
    return (next && next.charAt(0) === "/") ? next : "/";
  };

  /* ------------------------------------------------ Toast（全局通知） */
  CL.toast = function (msg, kind) {
    var box = document.getElementById("toasts");
    if (!box) {
      box = CL.el("div", "toasts");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }
    var t = CL.el("div", "toast " + (kind || "info"), msg);
    box.appendChild(t);
    setTimeout(function () {
      t.classList.add("out");
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 350);
    }, 3500);
  };

  CL.me = null;
  CL.unread = 0;

  /* ------------------------------------------------ 顶栏（会话感知 + 当前页高亮 + 主题切换） */
  CL.navbar = function () {
    var bar = document.getElementById("topbar");
    if (!bar) return Promise.resolve(null);
    return CL.api("/api/me").then(function (res) {
      CL.me = (res.data && res.data.user) || null;
      CL.unread = (res.data && res.data.unread) || 0;
      render(CL.me);
      return CL.me;
    });

    function render(user) {
      bar.textContent = "";
      var skip = CL.el("a", "skip", "跳到主要内容");
      skip.href = "#main";
      bar.appendChild(skip);
      var brand = CL.el("a", "brand", "课程工坊 CourseLab");
      brand.href = "/";
      bar.appendChild(brand);
      var links = CL.el("nav", "navlinks");
      links.setAttribute("aria-label", "主导航");
      var here = location.pathname;
      function navLink(href, text) {
        var a = CL.el("a", null, text);
        a.href = href;
        if (here === href) {                       // 当前页高亮（无查询串比较）
          a.setAttribute("aria-current", "page");
          a.className = "active";
        }
        return a;
      }
      links.appendChild(navLink("/", "课程目录"));
      if (user) {
        links.appendChild(navLink("/tasks.html", "我的任务"));
        var nt = CL.el("a", null, "通知" + (CL.unread ? "（" + CL.unread + "）" : ""));
        nt.href = "/notices.html";
        if (here === "/notices.html") nt.setAttribute("aria-current", "page");
        links.appendChild(nt);
      }
      if (user && (user.role === "teacher" || user.role === "admin")) {
        links.appendChild(navLink("/teacher.html", "教师台"));
      }
      if (user && user.role === "admin") {
        links.appendChild(navLink("/admin.html", "管理端"));
      }
      // 课程/项目详情页归属"课程目录"：详情页上也要高亮它的入口
      if (here === "/course.html" || here === "/project.html") {
        var dirLink = links.children[0];
        if (dirLink) { dirLink.setAttribute("aria-current", "page"); dirLink.className = "active"; }
      }
      bar.appendChild(links);
      var auth = CL.el("div", "navauth");
      if (user) {
        var me = CL.el("a", "me-link",
                       user.display_name + "（" + CL.roleName(user.role) + "）");
        me.href = "/me.html";
        if (here === "/me.html") me.setAttribute("aria-current", "page");
        auth.appendChild(me);
        var out = CL.el("button", "btn btn-ghost", "退出");
        out.addEventListener("click", function () {
          CL.api("/api/auth/logout", { method: "POST", body: {} }).then(function () {
            location.href = "/";
          });
        });
        auth.appendChild(out);
      } else {
        var lg = CL.el("a", "btn btn-ghost", "登录");
        lg.href = "/login.html?next=" + encodeURIComponent(location.pathname + location.search);
        var rg = CL.el("a", "btn", "注册");
        rg.href = "/register.html";
        auth.appendChild(lg);
        auth.appendChild(rg);
      }
      bar.appendChild(auth);
      var main = document.querySelector("main");
      if (main && !main.id) main.id = "main";
    }
  };

  /* 按钮"在途"状态：禁用 + aria-busy（CSS 侧给省略号动画）。
     用法：var done = CL.busy(btn); ... ; done(); */
  CL.busy = function (btn) {
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    return function () {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
    };
  };
})();
