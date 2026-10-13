// 轮三十八：八产品截图刷新（无头 Edge，亮色，1280x800）
const { chromium } = require("playwright-core");
const OUT = require("path").join(__dirname, "..", "screenshots") + "/";

const SHOTS = [
  { name: "studio",    url: "http://127.0.0.1:8017/", full: true },
  { name: "linkbox",   url: "http://127.0.0.1:8018/", full: true },
  { name: "simlab",    url: "http://127.0.0.1:8019/", full: true },
  { name: "datascope", url: "http://127.0.0.1:8020/", full: true },
  { name: "cachekv",   url: "http://127.0.0.1:8021/", full: true },
  { name: "sensorhub", url: "http://127.0.0.1:8022/", full: true },
  { name: "courselab", url: "http://127.0.0.1:8024/", full: true },
  { name: "boardweb",  url: "http://127.0.0.1:8025/", full: false },
];

(async () => {
  const b = await chromium.launch({ channel: "msedge", headless: true });
  const ctx = await b.newContext({ viewport: { width: 1280, height: 800 },
                                   deviceScaleFactor: 2 });
  const p = await ctx.newPage();
  for (const s of SHOTS) {
    try {
      await p.goto(s.url, { waitUntil: "networkidle", timeout: 20000 });
      await p.waitForTimeout(s.name === "studio" ? 2500 : 1200);
      if (s.name === "datascope") {   // 载入内置示例，画面有内容
        const btn = await p.$('button:has-text("示例")');
        if (btn) { await btn.click(); await p.waitForTimeout(1500); }
      }
      await p.screenshot({ path: OUT + s.name + ".png", fullPage: s.full });
      console.log("OK  " + s.name);
    } catch (e) {
      console.log("FAIL " + s.name + ": " + e.message.split("\n")[0]);
    }
  }
  await b.close();
})();
