import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { App } from "./App.tsx";

// ?recon loads Recon.tsx when it exists; the glob keeps the build working while that file is absent.
const recon = import.meta.glob("./Recon.tsx");
const Recon = recon["./Recon.tsx"] ? lazy(recon["./Recon.tsx"] as () => Promise<{ default: React.ComponentType }>) : null;
const showRecon = Recon && new URLSearchParams(location.search).has("recon");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {showRecon ? <Suspense fallback={null}><Recon /></Suspense> : <App />}
  </StrictMode>,
);
