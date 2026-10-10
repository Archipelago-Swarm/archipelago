// Browser smoke: headless Edge/Chrome (raw CDP, no deps) drives the real dashboard against a real API.
// Usage: node tests/web/browser-smoke.mjs   (spawns `uv run uvicorn` and `vite`; set BROWSER=path to override)
import { spawn } from "node:child_process";
import { mkdtempSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import assert from "node:assert/strict";

const API = 8765, WEB = 5199, CDP = 9333;
const TOKEN = "smoke-token-0123456789";
const browserPath = process.env.BROWSER ?? [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium"].find(existsSync);
assert.ok(browserPath, "no Edge/Chrome found; set BROWSER");

const kids = [];
const run = (cmd, args, env = {}, cwd) => { const p = spawn(cmd, args, { cwd, stdio: "ignore", env: { ...process.env, ...env }, shell: process.platform === "win32" && cmd !== browserPath }); kids.push(p); return p; };
const kill = () => kids.forEach((p) => { try { process.platform === "win32" ? spawn("taskkill", ["/pid", p.pid, "/T", "/F"], { stdio: "ignore" }) : p.kill(); } catch {} });
const until = async (fn, what, ms = 30000) => { const t = Date.now(); for (;;) { try { const v = await fn(); if (v) return v; } catch {} if (Date.now() - t > ms) throw new Error(`timeout: ${what}`); await new Promise((r) => setTimeout(r, 150)); } };

try {
  run("uv", ["run", "--with", "websockets", "uvicorn", "archipelago_api.app:create_app_from_env", "--factory", "--port", `${API}`],
    { ARCHIPELAGO_API_TOKEN: TOKEN, ARCHIPELAGO_DATA_DIR: mkdtempSync(join(tmpdir(), "arch-api-")), ARCHIPELAGO_ADAPTER: process.env.ARCHIPELAGO_ADAPTER ?? "fixture" });
  run("npx", ["vite", "--port", `${WEB}`, "--strictPort", "--host", "127.0.0.1"], { ARCHIPELAGO_URL: `http://127.0.0.1:${API}` }, new URL("../../apps/web", import.meta.url));
  run(browserPath, ["--headless=new", `--remote-debugging-port=${CDP}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), "arch-br-"))}`, "--no-first-run", "--disable-extensions", "--disable-sync", "about:blank"]);
  await until(() => fetch(`http://127.0.0.1:${API}/healthz`).then((r) => r.status < 500), "api");
  await until(() => fetch(`http://127.0.0.1:${WEB}/`).then((r) => r.ok), "vite");
  const tabs = await until(() => fetch(`http://127.0.0.1:${CDP}/json`).then((r) => r.json()).then((t) => t.find((x) => x.type === "page" && x.url === "about:blank")), "browser");

  const ws = new WebSocket(tabs.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let n = 0; const pending = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); pending.get(d.id)?.(d); };
  const send = (method, params = {}) => new Promise((res, rej) => { pending.set(++n, res); setTimeout(() => rej(new Error(`cdp timeout: ${method} ${JSON.stringify(params).slice(0, 120)}`)), 15000); ws.send(JSON.stringify({ id: n, method, params })); });
  const js = async (expression) => { const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }); if (r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails)); return r.result.result.value; };
  const text = () => js("document.body.innerText");
  const waitText = (re, what) => until(async () => re.test(await text()) && true, `${what} (page: ${""})`).catch(async (e) => { throw new Error(`${e.message}\n--- page text ---\n${await text()}`); });
  const click = (label) => js(`[...document.querySelectorAll("button")].find((b) => b.textContent.trim() === ${JSON.stringify(label)}).click()`);

  await send("Page.enable");
  await send("Page.navigate", { url: `http://127.0.0.1:${WEB}/` });
  await waitText(/Start run/, "dashboard renders");
  assert.match(await text(), /fixture/i, "default view is labelled as fixture, not live");

  // 401 -> sign in with the owner token
  await js(`(async () => { await fetch("/v1/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token: ${JSON.stringify(TOKEN)} }) }); })()`);

  await click("Start run"); // navigates to ?run=ID
  await waitText(/LIVE/, "live label");
  const t = await text();
  const id = new URL(await js("location.href")).searchParams.get("run");
  assert.ok(id && t.includes(id), "run ID visible");
  assert.match(t, /cells|%/, "units visible");

  await click("pause");
  await until(async () => (await js(`fetch("/v1/runs/${id}").then((r) => r.json()).then((r) => r.status)`)) === "paused", "paused");
  await click("resume");
  await until(async () => (await js(`fetch("/v1/runs/${id}").then((r) => r.json()).then((r) => r.status)`)) === "running", "resumed");
  await click("pause");
  await click("stop");

  await send("Page.navigate", { url: `http://127.0.0.1:${WEB}/?run=${id}&replay=1` });
  await waitText(/REPLAY/i, "replay label");
  await waitText(/Frame 1\//, "replay frames loaded");
  assert.ok((await text()).includes(id), "replay shows run ID");
  console.log(`ok: browser smoke start/pause/resume/stop/replay for ${id}`);
  ws.close();
} catch (e) { console.error(e); process.exitCode = 1; } finally { kill(); }
