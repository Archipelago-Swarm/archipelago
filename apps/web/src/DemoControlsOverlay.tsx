import { ACTS, POLICY, type DemoController, type DemoState, type Scene } from "./demoScriptController";
import { LineagePanel } from "./Lineage";
import type { Lineage } from "./live";

const bar = { position: "sticky", top: 0, zIndex: 10, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", padding: 8, background: "#0a0a0af2", color: "#ede7df", borderBottom: "1px solid #333" } as const;
const card = { position: "fixed", right: 16, zIndex: 11, maxWidth: 360, padding: 12, background: "#0a0a0af2", color: "#ede7df", border: "1px solid #f47b3c", borderRadius: 0 } as const;

export function DemoControlsOverlay({ ctl, state, scene, lineage }: { ctl: DemoController; state: DemoState; scene: Scene; lineage: Lineage }) {
  const done = scene.act === ACTS.length - 1;
  return (
    <>
      <div role="toolbar" aria-label="Demo controls" style={bar}>
        <strong>Scripted demo (synthetic, not a measurement)</strong>
        {ACTS.map((a, i) => <button key={a.name} aria-pressed={scene.act === i} title={a.name} onClick={() => ctl.jump(i)}>Act {i + 1}</button>)}
        <button onClick={() => (state.playing ? ctl.pause() : ctl.play())} disabled={done}>{state.playing ? "Pause" : "Play"}</button>
        {([1, 2, 5] as const).map((s) => <button key={s} aria-pressed={state.speed === s} onClick={() => ctl.setSpeed(s)}>{s}×</button>)}
        <a className="button" href={location.pathname}>Exit Demo Mode</a>
        <p role="status" aria-live="polite" style={{ flexBasis: "100%", margin: 0 }}>{scene.callout}</p>
      </div>
      {scene.validation && (
        <div role="dialog" aria-label="Recipient-side validation" style={{ ...card, top: 130 }}>
          <strong>Beta: validating {POLICY} delta</strong>
          <ul style={{ margin: "6px 0", paddingLeft: 18 }}>
            {["Lineage chain verified", "Encoder id matches", "Canyon check against local baseline"].map((c) => <li key={c}>{scene.validation === "passed" ? "✓" : "…"} {c}</li>)}
          </ul>
          <em>{scene.validation === "passed" ? "Accepted: adopted." : "Checking…"} (scripted illustration)</em>
        </div>
      )}
      {done && <LineagePanel lineage={lineage} />}
    </>
  );
}
