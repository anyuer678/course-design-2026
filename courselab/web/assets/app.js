/* CourseLab 共享脚本：API 封装 + 顶栏（会话感知）。（零依赖） */
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
      return r.json().then(function (data) { return { status: r.status, data: data }; });
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

  CL.me = null;

  CL.navbar = function () {
    var bar = document.getElementById("topbar");
    if (!bar) return;
    CL.api("/api/me").then(function (res) {
      CL.me = (res.data && res.data.user) || null;
      render(CL.me);
    }).catch(function () { render(null); });

    function render(user) {
      bar.textContent = "";
      var brand = CL.el("a", "brand", "课程工坊 CourseLab");
      brand.href = "/";
      bar.appendChild(brand);
      var links = CL.el("div", "navlinks");
      var dir = CL.el("a", null, "课程目录");
      dir.href = "/";
      links.appendChild(dir);
      bar.appendChild(links);
      var auth = CL.el("div", "navauth");
      if (user) {
        var me = CL.el("a", "me-link", user.display_name + "（" + CL.roleName(user.role) + "）");
        me.href = "/me.html";
        var out = CL.el("button", "btn btn-ghost", "退出");
        out.addEventListener("click", function () {
          CL.api("/api/auth/logout", { method: "POST", body: {} }).then(function () {
            location.href = "/";
          });
        });
        auth.appendChild(me);
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
    }
  };
})();
