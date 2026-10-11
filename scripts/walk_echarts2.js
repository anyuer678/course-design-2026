/* 补充取证：SensorHub 曲线元素 + CacheKV TTL 分布元素 特写截图 */
const { chromium } = require("playwright-core");
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const errors = [];

  // SensorHub：滚到曲线区，元素截图
  let page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on("console", m => { if (m.type() === "error") errors.push("sh console: " + m.text()); });
  page.on("pageerror", e => errors.push("sh pageerror: " + e.message));
  await page.goto("http://127.0.0.1:8022/", { waitUntil: "networkidle" });
  await page.click("#btn-chart");
  await page.waitForTimeout(2000);
  await page.locator("#chartbox").scrollIntoViewIfNeeded();
  await page.waitForTimeout(1200);                      // 等一次 2s 自刷新重绘
  await page.locator("#chartbox").screenshot({ path: "C:/Users/30816/Desktop/课设/p-验收/echarts-sensorhub-curve.png" });
  const curveInfo = await page.evaluate(() => {
    const c = document.querySelector("#chart canvas");
    return c ? { w: c.width, h: c.height } : null;
  });
  await page.close();

  // CacheKV：滚到键空间 TTL 分布
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on("console", m => { if (m.type() === "error") errors.push("kv console: " + m.text()); });
  page.on("pageerror", e => errors.push("kv pageerror: " + e.message));
  await page.goto("http://127.0.0.1:8021/", { waitUntil: "networkidle" });
  await page.evaluate(() => fetch("/api/demo", { method: "POST" }));
  await page.waitForTimeout(1500);
  await page.locator("#ttl-dist").scrollIntoViewIfNeeded();
  await page.waitForTimeout(800);
  await page.locator("#keys").screenshot({ path: "C:/Users/30816/Desktop/课设/p-验收/echarts-cachekv-ttl.png" });
  await page.close();

  console.log(JSON.stringify({ curveInfo, errors }, null, 2));
  await browser.close();
})().catch(e => { console.error("FAIL", e); process.exit(1); });
