/* ECharts 化走查（2026-10-11）：CacheKV :8021 + SensorHub :8022
   门槛：零 console error / 零 pageerror / echarts canvas 真实渲染 + 截图目检。 */
const { chromium } = require("playwright-core");

(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const report = [];
  async function walk(name, url, actions) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on("console", m => { if (m.type() === "error") errors.push("console: " + m.text()); });
    page.on("pageerror", e => errors.push("pageerror: " + e.message));
    page.on("requestfailed", r => errors.push("reqfail: " + r.url()));
    await page.goto(url, { waitUntil: "networkidle", timeout: 15000 });
    await actions(page);
    await page.waitForTimeout(2500);
    const canvasCount = await page.evaluate(() => document.querySelectorAll("canvas").length);
    await page.screenshot({ path: `p-验收/echarts-${name}.png`, fullPage: false });
    report.push({ name, url, canvasCount, errors });
    await page.close();
  }

  await walk("cachekv", "http://127.0.0.1:8021/", async (page) => {
    // 注入演示数据，让命中率环/趋势/TTL 分布都有内容
    await page.evaluate(() => fetch("/api/demo", { method: "POST" }));
    // 触发几次 GET 产生命中/未命中与趋势采样
    for (let i = 0; i < 3; i++) {
      await page.evaluate(() => fetch("/api/kv/demo:user:" + Math.floor(Math.random() * 10)));
    }
    await page.waitForTimeout(4500);           // 等两个 2s 采样周期
  });

  await walk("sensorhub", "http://127.0.0.1:8022/", async (page) => {
    await page.selectOption("#metric", "temp");
    await page.click("#btn-chart");
    await page.waitForTimeout(1500);
  });

  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch(e => { console.error("WALK-FAIL", e); process.exit(1); });
