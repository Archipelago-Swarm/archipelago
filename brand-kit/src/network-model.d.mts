export const nodes: { id: string; x: number; y: number }[];
export const edges: number[][];
export const stages: string[];
export function networkState(progress?: number): {
  progress: number;
  stage: number;
  label: string;
  accepted: number[];
  offline: number[];
  packet: { from: number; to: number; t: number } | null;
};
