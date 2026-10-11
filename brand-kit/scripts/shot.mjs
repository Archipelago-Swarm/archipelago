// debug helper: node scripts/shot.mjs in.html out.png width height
import { chromium } from "playwright-core";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
let b;
for (const channel of [undefined, "chrome", "msedge"]) { try { b = await chromium.launch({ channel }); break; } catch { /* next */ } }
const [, , i, o, w, h] = process.argv;
const p = await b.newPage({ viewport: { width: +w, height: +h } });
await p.goto(pathToFileURL(resolve(i)).href);
await p.screenshot({ path: o });
await b.close();
