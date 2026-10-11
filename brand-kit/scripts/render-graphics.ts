// On-demand only: nothing here runs in CI. Needs a Chromium (Playwright's, installed Chrome/Edge, or CHROMIUM_PATH).
// Usage: npm run render:graphics [-- name-substring ...]   -> exports/<group>/<file>.png (+ .svg for logos)
import { mkdirSync, writeFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { chromium } from "playwright-core";
import { OUTPUTS } from "../src/registry";

const only = process.argv.slice(2);
const launch = async () => {
  if (process.env.CHROMIUM_PATH) return chromium.launch({ executablePath: process.env.CHROMIUM_PATH });
  for (const channel of [undefined, "chrome", "msedge"] as const) {
    try { return await chromium.launch({ channel }); } catch { /* try next */ }
  }
  throw new Error("No Chromium found: run `npx playwright-core install chromium` or set CHROMIUM_PATH");
};
const browser = await launch();
try {
  for (const o of OUTPUTS.filter((x) => !only.length || only.some((s) => x.file.includes(s) || x.group === s))) {
    const dir = new URL(`../exports/${o.group}/`, import.meta.url);
    mkdirSync(dir, { recursive: true });
    const page = await browser.newPage({ viewport: { width: o.w, height: Math.min(o.h, 4000) }, deviceScaleFactor: o.scale });
    const bg = o.transparent ? "transparent" : "#0A0A0A";
    await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:${bg}}</style></head><body>${renderToStaticMarkup(o.el())}</body></html>`, { waitUntil: "load" });
    await page.evaluate(() => document.fonts.ready);
    writeFileSync(new URL(`${o.file}.png`, dir), await page.screenshot({ type: "png", omitBackground: !!o.transparent, clip: { x: 0, y: 0, width: o.w, height: o.h } }));
    if (o.svg) writeFileSync(new URL(`${o.file}.svg`, dir), o.svg);
    console.log(`${o.group}/${o.file}.png  ${o.w * o.scale}x${o.h * o.scale}`);
    await page.close();
  }
} finally {
  await browser.close();
}
