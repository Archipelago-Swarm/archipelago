import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev/smoke only: the app calls relative /v1 URLs, so forward them (and the stream WebSocket) to the API.
const target = process.env.ARCHIPELAGO_URL ?? "http://127.0.0.1:8000";
export default defineConfig({ plugins: [react()], server: { proxy: { "/v1": { target, ws: true }, "/api/mission": { target: process.env.MISSION_URL ?? "http://127.0.0.1:8765", changeOrigin: true } } } });
