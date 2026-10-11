/* scripts/walk_ws21.js —— BoardWeb 协同白板走查：双页面真协同验证。
   A 画笔画 → B 画布出现像素且徽标 2 人；B 画矩形 → A 像素数增加。
   证据 = 像素计数 + 徽标文本 + 双截图（不只看 console）。 */
const { chromium } = require("playwright-core");
const fs = require("fs");

const URL = "http://127.0.0.1:18025/";
const OUT = __dirname + "/../p-验收/ws-BoardWeb协同-2026-10-11";

function nonWhite(page) {
  return page.evaluate(() => {
    const c = document.getElementById("board");
    const g = c.getContext("2d");
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let n = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] < 250 || d[i + 1] < 250 || d[i + 2] < 250) n++;
    }
    return n;
  });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 820 }, deviceScaleFactor: 2 });
  const a = await ctx.newPage(), b = await ctx.newPage();
  a.on("dialog", d => d.accept());          // 清空确认框：无头模式自动接受
  b.on("dialog", d => d.accept());
  a.on("console", m => { if (m.type() === "error") console.log("[A console]", m.text()); });
  b.on("console", m => { if (m.type() === "error") console.log("[B console]", m.text()); });

  await a.goto(URL, { waitUntil: "networkidle" });
  await b.goto(URL, { waitUntil: "networkidle" });
  await a.waitForTimeout(1000);

  const badgeA = await a.evaluate(() => document.getElementById("ws-state").textContent);
  const badgeB = await b.evaluate(() => document.getElementById("ws-state").textContent);
  console.log("badge A:", badgeA, "| badge B:", badgeB);

  // A 画一条波浪笔迹
  const box = await (await a.$("#board")).boundingBox();
  const cx = box.x, cy = box.y;
  await a.mouse.move(cx + 100, cy + 120);
  await a.mouse.down();
  for (let i = 0; i <= 24; i++)
    await a.mouse.move(cx + 100 + i * 9, cy + 120 + Math.sin(i / 2.5) * 35);
  await a.mouse.up();
  await a.waitForTimeout(700);

  const pxB1 = await nonWhite(b);
  console.log("B 像素（A 画笔后）:", pxB1);

  // B 切矩形工具画一个框
  await b.click('[data-tool="rect"]');
  const boxB = await (await b.$("#board")).boundingBox();
  const bx = boxB.x, by = boxB.y;
  await b.mouse.move(bx + 620, by + 300);
  await b.mouse.down();
  await b.mouse.move(bx + 820, by + 420, { steps: 8 });
  await b.mouse.up();
  await b.waitForTimeout(700);

  const pxA1 = await nonWhite(a);
  console.log("A 像素（B 画矩形后）:", pxA1);

  // A 清空 → B 画布应干净
  await a.click("#btn-clear");
  await a.waitForTimeout(700);
  const pxB2 = await nonWhite(b);
  console.log("B 像素（A 清空后）:", pxB2);

  await a.screenshot({ path: OUT + "/page-A.png", fullPage: true });
  await b.screenshot({ path: OUT + "/page-B.png", fullPage: true });
  console.log("screenshots →", OUT);
  await browser.close();
})();
