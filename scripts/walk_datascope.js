/* DataScope ECharts 报告走查：加载示例 → 加配方 → 清洗 → 生成报告 → 截图取证。 */
const { chromium } = require("playwright-core");
const path = require("path");

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

  await page.goto("http://127.0.0.1:8020/", { waitUntil: "networkidle" });

  // 1. 加载示例数据
  await page.click("#btn-sample");
  await page.waitForFunction(() =>
    document.getElementById("profile-rows").children.length > 1, { timeout: 8000 });

  // 2. 组配方：去重行 + 去空格 + 填充缺失(金额)
  await page.selectOption("#op", "drop_duplicates");
  await page.click("#btn-add-step");
  await page.selectOption("#op", "trim");
  await page.click("#btn-add-step");
  await page.selectOption("#op", "fill_missing");
  await page.selectOption("#op-col", "金额");
  await page.click("#btn-add-step");

  // 3. 清洗
  await page.click("#btn-clean");
  await page.waitForSelector("#clean-tiles:not([hidden])", { timeout: 8000 });
  const cleanTiles = await page.evaluate(() => ({
    before: document.getElementById("ct-before").textContent,
    after: document.getElementById("ct-after").textContent,
    steps: document.getElementById("ct-steps").textContent,
  }));

  // 4. 生成报告（默认 apriori：聚篮列=第1列 商品列=第2列）
  await page.click("#btn-report");
  await page.waitForSelector("#report-charts:not([hidden])", { timeout: 8000 });
  await page.waitForTimeout(1200); // echarts 动画

  // 5. 取证：canvas 尺寸 + 报告注记
  const info = await page.evaluate(() => {
    const ids = ["chart-steps", "chart-profile", "chart-mining"];
    return ids.map((id) => {
      const el = document.getElementById(id);
      const cv = el && el.querySelector("canvas");
      return { id, w: cv ? cv.clientWidth : -1, h: cv ? cv.clientHeight : -1,
               hasCanvas: !!cv };
    }).concat([{ note: document.getElementById("report-note").textContent,
                 mineTitle: document.getElementById("chart-mine-title").textContent }]);
  });
  console.log("cleanTiles:", JSON.stringify(cleanTiles));
  console.log("charts:", JSON.stringify(info, null, 1));
  console.log("consoleErrors:", errors.length ? errors : "none");

  const out = "p-验收";
  await page.screenshot({ path: path.join(out, "echarts-datascope.png"), fullPage: true });
  await page.locator("#chart-steps").screenshot({ path: path.join(out, "echarts-datascope-steps.png") });
  await page.locator("#chart-mining").screenshot({ path: path.join(out, "echarts-datascope-mining.png") });

  await browser.close();
})();
