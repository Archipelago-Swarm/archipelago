import type { ReactNode } from "react";
import { c, mono, strait } from "../tokens";

export type PT = (x: number, y: number) => [number, number];

/**
 * Stylised Taiwan Strait operational map. Land is the demo's coast mask (cell units, ~5.2 km per cell).
 * `view` = [x0,y0,x1,y1] crop in cells. Overlays get P (cell -> px) and k (px per cell). Geography only; all overlays are illustrative.
 */
export const StraitMap = ({ w, h, view, children, grid = true, labels = true, land = "#171717" }: { w: number; h: number; view: [number, number, number, number]; children?: (P: PT, k: number) => ReactNode; grid?: boolean; labels?: boolean; land?: string }) => {
  const [x0, y0, x1] = view, k = w / (x1 - x0);
  const P: PT = (x, y) => [(x - x0) * k, (y - y0) * k];
  const gx: number[] = [], gy: number[] = [];
  for (let i = Math.ceil(x0 / 10) * 10; i < x1; i += 10) gx.push(i);
  for (let j = Math.ceil(y0 / 10) * 10; j < y0 + h / k; j += 10) gy.push(j);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block" }}>
      <defs><clipPath id="mapclip"><rect width={w} height={h} /></clipPath></defs>
      <g clipPath="url(#mapclip)">
        {grid && gx.map((i) => <line key={"x" + i} x1={P(i, 0)[0]} y1={0} x2={P(i, 0)[0]} y2={h} stroke="#fff" strokeOpacity={0.07} />)}
        {grid && gy.map((j) => <line key={"y" + j} x1={0} y1={P(0, j)[1]} x2={w} y2={P(0, j)[1]} stroke="#fff" strokeOpacity={0.07} />)}
        <g transform={`translate(${-x0 * k},${-y0 * k}) scale(${k})`}>
          {strait.fill.map((d, i) => <path key={i} d={d} fill={land} />)}
          {strait.coast.map((d, i) => <path key={i} d={d} fill="none" stroke={c.stone} strokeOpacity={0.55} strokeWidth={1.4} vectorEffect="non-scaling-stroke" />)}
        </g>
        {labels && [["FUJIAN", 40, 72], ["TAIWAN", 126, 96], ["TAIWAN STRAIT", 97, 68]].map(([t, x, y]) => {
          const [px, py] = P(x as number, y as number);
          return <text key={t as string} x={px} y={py} textAnchor="middle" fill={c.grey} fontFamily={mono} fontSize={Math.min(20, Math.max(11, k * 1.5))} letterSpacing={Math.min(8, Math.max(3, k * 0.5))} transform={`rotate(${t === "TAIWAN" ? 74 : t === "FUJIAN" ? 38 : 58} ${px} ${py})`} opacity={0.7}>{t}</text>;
        })}
        {children?.(P, k)}
      </g>
    </svg>
  );
};
