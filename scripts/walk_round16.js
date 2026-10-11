/* 轮十六走查：SimLab 回放图表（Dijkstra 柱状 + 背包热力图）与 Studio 监控大盘。
   证据：canvas 尺寸 + 零 console 错误 + 截图目检。 */
const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");
const OUT = "p-验收";
// 口令不入库：运行时从 gitignore 的 studio/data/ 读
const PASSWORD = fs.readFileSync("studio/data/password.txt", "utf-8")
  .split("\n").map((l) => l.trim())
  .filter((l) => l && !l.startsWith("#"))[0];

async function probe(page, id) {
  return page.evaluate((id) => {
    const el = document.getElementById(id);
    const cv = el && el.querySelector("canvas");
    return { id, hasCanvas: !!cv, w: cv ? cv.clientWidth : -1, h: cv ? cv.clientHeight : -1 };
  }, id);
}

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });

  // ---------- SimLab：默认载入 Dijkstra → 切背包
  const sl = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  const slErr = [];
  sl.on("console", (m) => { if (m.type() === "error") slErr.push(m.text()); });
  sl.on("pageerror", (e) => slErr.push("pageerror: " + e.message));
  await sl.goto("http://127.0.0.1:8019/", { waitUntil: "networkidle" });
  await sl.waitForSelector("#player:not([hidden])", { timeout: 10000 });
  await sl.click("#btn-last");                    // 末帧才有收敛形态可看
  await sl.waitForTimeout(600);
  const dij = await probe(sl, "stage");
  console.log("simlab-dijkstra:", JSON.stringify(dij), "errs:", slErr.length);
  await sl.locator("#stage").screenshot({ path: path.join(OUT, "echarts-simlab-dijkstra.png") });

  await sl.selectOption("#experiment-list", "b12-knapsack");
  await sl.click("#btn-render");
  await sl.waitForTimeout(900);   // 现算 + 渲染
  await sl.click("#btn-last");
  await sl.waitForTimeout(400);
  const kn = await probe(sl, "stage");
  console.log("simlab-knapsack:", JSON.stringify(kn), "errs:", slErr.length);
  await sl.locator("#stage").screenshot({ path: path.join(OUT, "echarts-simlab-knapsack.png") });

  // 播放 3 帧验证逐帧重建不炸
  await sl.click("#btn-play");
  await sl.waitForTimeout(1600);
  await sl.click("#btn-play");
  console.log("simlab-after-play errs:", slErr.length ? slErr : "none");
  await sl.close();

  // ---------- Studio：登录 → 看大盘（先造几笔审计：启停一个产品）
  const st = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  const stErr = [];
  st.on("console", (m) => { if (m.type() === "error") stErr.push(m.text()); });
  st.on("pageerror", (e) => stErr.push("pageerror: " + e.message));
  await st.goto("http://127.0.0.1:8017/", { waitUntil: "networkidle" });
  await st.fill("#login-pass", PASSWORD);
  await st.click("#btn-login");
  await st.waitForFunction(() =>
    document.getElementById("whoami").textContent.indexOf("owner") >= 0, { timeout: 8000 });

  // 造审计数据：启停 cachekv 各一次（幂等失败也入账，都有得画）
  await st.evaluate(async () => {
    await fetch("/api/products/cachekv/start", { method: "POST" });
    await new Promise((res) => setTimeout(res, 1500));
    await fetch("/api/products/cachekv/stop", { method: "POST" });
    await new Promise((res) => setTimeout(res, 1500));
  });
  await st.waitForSelector("#dash:not([hidden])", { timeout: 10000 });
  await st.waitForTimeout(700);
  const a1 = await probe(st, "dash-actions");
  const a2 = await probe(st, "dash-outcomes");
  console.log("studio-dash:", JSON.stringify([a1, a2]), "errs:", stErr.length ? stErr : "none");
  await st.locator("#dash").screenshot({ path: path.join(OUT, "echarts-studio-dash.png") });

  await browser.close();
  console.log("DONE");
})();
