// Captures the REAL dashboard (apps/web, fixture view, no backend) into public/screenshots/dashboard.png.
// Start it first: (cd ../apps/web && npx vite --port 5199 --host 127.0.0.1)   Usage: tsx scripts/capture-screenshot.ts [url]
import { chromium } from "playwright-core";
const url = process.argv[2] ?? "http://127.0.0.1:5199/";
let browser;
for (const channel of [undefined, "chrome", "msedge"] as const) { try { browser = await chromium.launch({ channel }); break; } catch { /* next */ } }
if (!browser) throw new Error("no browser");
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await page.screenshot({ path: new URL("../public/screenshots/dashboard.png", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1") });
await browser.close();
