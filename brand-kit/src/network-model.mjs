export const nodes = [
  { id: "01", x: 92, y: 186 },
  { id: "02", x: 239, y: 82 },
  { id: "03", x: 436, y: 113 },
  { id: "04", x: 170, y: 344 },
  { id: "05", x: 340, y: 247 },
  { id: "06", x: 487, y: 351 },
];
export const edges = [
  [0, 1],
  [1, 2],
  [0, 3],
  [0, 4],
  [1, 4],
  [2, 4],
  [4, 5],
  [3, 5],
];
export const stages = [
  "Discovery",
  "Local learning",
  "Local validation",
  "Announcement",
  "Peer transfer",
  "Peer validation",
  "Propagation",
  "Node disconnect",
  "Peer rerouting",
];
export function networkState(progress = 0) {
  const p = Math.max(0, Math.min(1, Number.isFinite(progress) ? progress : 0));
  const stage = Math.min(8, Math.floor(p * 9));
  const accepted =
    stage >= 6
      ? [0, 1, 2, 3, 4, 5]
      : stage >= 5
        ? [0, 4]
        : stage >= 3
          ? [0]
          : [];
  return {
    progress: p,
    stage,
    label: stages[stage],
    accepted,
    offline: stage >= 7 ? [1] : [],
    packet:
      stage === 4
        ? { from: 0, to: 4, t: (p * 9) % 1 }
        : stage === 6
          ? { from: 4, to: 5, t: (p * 9) % 1 }
          : null,
  };
}
