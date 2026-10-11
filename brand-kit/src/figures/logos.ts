import { logoInner } from "../tokens";

export type Layout = "icon" | "horizontal" | "stacked" | "primary";
export type Theme = "dark" | "light";

/** Standalone lockup SVGs built from the media-kit logo paths. Wordmark is live Arial Bold text (Arial metrics assumed for placement). */
export const logoSvg = (layout: Layout, theme: Theme) => {
  const ink = theme === "dark" ? "#FFFFFF" : "#0A0A0A";
  const accent = "#F47B3C";
  const mark = (x: number, y: number, s = 1) => `<g transform="translate(${x},${y}) scale(${s})">${logoInner(theme)}</g>`;
  const word = (x: number, y: number, size: number, anchor: string) => `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="Arial, Helvetica, sans-serif" font-weight="700" font-size="${size}" letter-spacing="${-size * 0.04}" fill="${ink}">ARCHIPELAGO</text>`;
  let w = 1400, h = 1336, body = mark(0, 0);
  if (layout === "horizontal") { w = 5100; body = mark(0, 0) + word(1620, 1336 / 2 + 180, 500, "start"); }
  if (layout === "stacked" || layout === "primary") {
    w = 3600; h = layout === "stacked" ? 1930 : 2230;
    body = mark(1100, 0) + word(1800, 1336 + 150 + 360, 500, "middle");
    if (layout === "primary") body += `<text x="1800" y="2130" text-anchor="middle" font-family="Consolas, 'Courier New', monospace" font-size="105" letter-spacing="14" fill="${accent}">DECENTRALIZED LEARNING ACROSS UAV SQUADRONS.</text>`;
  }
  const pad = layout === "icon" ? 0 : 40;
  return { w: w + pad * 2, h: h + pad * 2, svg: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${-pad} ${-pad} ${w + pad * 2} ${h + pad * 2}" width="${w + pad * 2}" height="${h + pad * 2}"><title>ARCHIPELAGO ${layout} (${theme})</title>${body}</svg>` };
};
export const logoUri = (layout: Layout, theme: Theme) => `data:image/svg+xml;base64,${Buffer.from(logoSvg(layout, theme).svg).toString("base64")}`;
