/* 轮十七走查：LinkBox 统计页 + CourseLab 管理端看板 ECharts 化。
   证据：canvas 真渲染尺寸、console 错误清点、元素截图。
   用法：node scripts/walk_round17.js <courselab口令>
   （口令由调用方传入，本文件不入库任何凭据。） */
const { chromium } = require("playwright-core");
const path = require("path");
const OUT = "p-验收";
const CL_PASS = process.argv[2] || "";

function errs() { return []; }
function listen(page, bag) {
  page.on("pageerror", (e) => bag.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") bag.push("console: " + m.text()); });
}
async function canvasInfo(page, sel) {
  return page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el) return null;
    const c = el.tagName === "CANVAS" ? el : el.querySelector("canvas");
    if (!c) return { canvas: false, html: el.innerHTML.slice(0, 80) };
    return { canvas: true, w: c.width, h: c.height,
             hidden: !el.offsetParent && el.offsetHeight === 0 };
  }, sel);
}

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });

  // ---- LinkBox :8018 —— 先造演示数据（3 短链 + 命中），再开统计页
  const lb = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const lbErr = errs(); listen(lb, lbErr);
  await lb.goto("http://127.0.0.1:8018/", { waitUntil: "networkidle" });
  const tag = Date.now().toString(36).slice(-5);   // 每次运行唯一，种子幂等
  const seeds = [
    ["https://github.com/anyuer678", "gh" + tag],
    ["https://www.workbuddy.cn/docs/workbuddy/Overview", "wbd" + tag],
    ["https://example.com/very/long/path?with=query", null]
  ];
  const ghAlias = "gh" + tag, wbAlias = "wbd" + tag;
  for (const [url, alias] of seeds) {
    await lb.evaluate(async ({ url, alias }) => {
      await fetch("/api/links", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, alias }) });
    }, { url, alias }).catch(() => {});
  }
  // 制造命中差异：gh 3 次、wb-docs 1 次
  for (let i = 0; i < 3; i++) {
    await lb.evaluate((a) => fetch("/l/" + a, { redirect: "manual" }), ghAlias);
  }
  await lb.evaluate((a) => fetch("/l/" + a, { redirect: "manual" }), wbAlias);
  await lb.evaluate((t) => fetch("/api/stash", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content: "walkthrough demo stash " + t, ttl_hours: 1 }) }), tag);

  await lb.goto("http://127.0.0.1:8018/#stats", { waitUntil: "networkidle" });  await lb.waitForTimeout(700);
  const bar = await canvasInfo(lb, "#stats-top");
  const pie = await canvasInfo(lb, "#stats-inv");
  console.log("linkbox-bar:", JSON.stringify(bar));
  console.log("linkbox-pie:", JSON.stringify(pie));
  await lb.locator("#tab-stats").screenshot({ path: path.join(OUT, "echarts-linkbox-stats.png") });
  console.log("linkbox-errors:", lbErr.length, lbErr.slice(0, 3));

  // ---- CourseLab :8024 —— 登录 walkadmin → /admin.html 看板
  const cl = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const clErr = errs(); listen(cl, clErr);
  await cl.goto("http://127.0.0.1:8024/login.html", { waitUntil: "networkidle" });
  await cl.fill("#username", "walkadmin");
  await cl.fill("#password", CL_PASS);
  await cl.click("#submit");
  await cl.waitForTimeout(1200);
  await cl.goto("http://127.0.0.1:8024/admin.html", { waitUntil: "networkidle" });
  await cl.waitForSelector("#board-labs canvas", { timeout: 8000 }).catch(() => {});
  await cl.waitForTimeout(500);
  const labs = await canvasInfo(cl, "#board-labs");
  const tasks = await canvasInfo(cl, "#board-tasks");
  console.log("courselab-labs:", JSON.stringify(labs));
  console.log("courselab-tasks:", JSON.stringify(tasks));
  await cl.locator("#board").screenshot({ path: path.join(OUT, "echarts-courselab-board.png") });
  console.log("courselab-errors:", clErr.length, clErr.slice(0, 3));

  await browser.close();
})();
