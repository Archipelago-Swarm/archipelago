import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Dev/smoke only: the app calls relative /v1 URLs, so forward them (and the stream WebSocket) to the API.
const target = process.env.ARCHIPELAGO_URL ?? "http://127.0.0.1:8000";
const mission = process.env.MISSION_URL ?? "http://127.0.0.1:8765";

// `npm run dev` also starts the mission simulator server (stdlib Python) unless MISSION_URL points at another one.
const missionServer = (): Plugin => ({
  name: "mission-server",
  apply: "serve",
  configureServer(server) {
    if (process.env.MISSION_URL) return;
    const root = fileURLToPath(new URL("../..", import.meta.url));
    const sep = process.platform === "win32" ? ";" : ":";
    const py = spawn(process.env.MISSION_PYTHON ?? (process.platform === "win32" ? "python" : "python3"), ["-m", "archipelago_mission.serve", "--port", new URL(mission).port], {
      cwd: root, stdio: "inherit", env: { ...process.env, PYTHONPATH: ["packages/mission", "packages/sim"].join(sep) },
    });
    py.on("error", (e) => server.config.logger.warn(`mission server not started (${e.message}); set MISSION_PYTHON or run it by hand`));
    server.httpServer?.on("close", () => py.kill());
    process.on("exit", () => py.kill());
  },
});

export default defineConfig({ plugins: [react(), missionServer()], server: { proxy: { "/v1": { target, ws: true }, "/api/mission": { target: mission, changeOrigin: true } } } });
