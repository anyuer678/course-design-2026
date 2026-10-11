// scripts/shoot.js - headless Edge screenshots of the 8 web products.
// Usage: NODE_PATH=<workspace>/node_modules node shoot.js
const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

const OUT = path.resolve(__dirname, "..", "screenshots");
const SHOTS = [
  ["studio", "http://127.0.0.1:8017/"],
  ["linkbox", "http://127.0.0.1:8018/"],
  ["simlab", "http://127.0.0.1:8019/"],
  ["datascope", "http://127.0.0.1:8020/", async (page) => {
    // load sample data so the shot shows a real profile, not an empty form
    await page.click("text=加载示例数据");
    await page.click("text=解析并载入");
    await page.waitForTimeout(1500);
  }],
  ["cachekv", "http://127.0.0.1:8021/", async (page) => {
    // inject demo keys, then let the client-side sampler accumulate a trend
    await page.click("text=注入演示数据");
    await page.waitForTimeout(9000);
  }],
  ["sensorhub", "http://127.0.0.1:8022/", async (page) => {
    // switch to the WebSocket live curve, then scroll it into view
    await page.click("text=看曲线");
    await page.waitForTimeout(4000);
    await page.locator("canvas").last().scrollIntoViewIfNeeded();
    await page.waitForTimeout(2500);
  }],
  ["courselab", "http://127.0.0.1:8024/"],
  ["boardweb", "http://127.0.0.1:8025/"],
];

(async () => {
  const only = process.argv.slice(2); // optional: product names to shoot
  const shots = only.length ? SHOTS.filter(([n]) => only.includes(n)) : SHOTS;
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1360, height: 850 },
    deviceScaleFactor: 2,
    locale: "zh-CN",
  });
  const errors = [];
  for (const [name, url] of shots) {
    const page = await ctx.newPage();
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(`${name}: console.error ${m.text()}`);
    });
    page.on("pageerror", (e) => errors.push(`${name}: pageerror ${e.message}`));
    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: 20000 });
      const act = SHOTS.find(([n]) => n === name) && SHOTS.find(([n]) => n === name)[2];
      if (act) await act(page);
    } catch (e) {
      errors.push(`${name}: goto ${e.message.split("\n")[0]}`);
    }
    await page.waitForTimeout(2500); // charts / WS live line settle
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log(`shot ${name} -> ${name}.png`);
    await page.close();
  }
  await browser.close();
  if (errors.length) {
    console.log("ERRORS:\n" + errors.join("\n"));
    process.exitCode = 1;
  } else {
    console.log("ALL-CLEAN");
  }
})();
