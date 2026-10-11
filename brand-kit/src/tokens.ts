// Values come from the ARCHIPELAGO media kit (public/brand/brand.json, copied from ARCHIPELAGO-website.zip).
// Palette: black 60 / stone+white 30 / orange 10. Orange is an accent only.
import { readFileSync } from "node:fs";

export const c = {
  bg: "#0A0A0A",
  surface: "#141414",
  elevated: "#1C1C1C",
  border: "#333333",
  stone: "#EDE7DF",
  white: "#FFFFFF",
  orange: "#F47B3C",
  grey: "#8A8A8A",
};
export const font = "Arial, Helvetica, sans-serif";
export const mono = "Consolas, 'Courier New', monospace";
// Traced vector logo from the media kit, embedded unaltered (viewBox 1400x1336).
export const LOGO_SRC = `data:image/svg+xml;base64,${readFileSync(new URL("../public/brand/archipelago-logo.svg", import.meta.url)).toString("base64")}`;
export const LOGO_ASPECT = 1400 / 1336;
export const TAGLINE = "Decentralized learning across UAV squadrons.";
export const TAGLINE_CAPS = TAGLINE.toUpperCase();
export const DESCRIPTION = "A decentralized capability-sharing layer for autonomous edge systems.";

const b64 = (f: string) => readFileSync(new URL(`../public/brand/${f}`, import.meta.url)).toString("base64");
export const LOGO_LIGHT_SRC = `data:image/svg+xml;base64,${b64("archipelago-logo-light.svg")}`;
/** Inner SVG markup of a logo file (for composing standalone lockup SVGs). Source viewBox is 1400x1336. */
export const logoInner = (theme: "dark" | "light") => {
  const s = readFileSync(new URL(`../public/brand/archipelago-logo${theme === "light" ? "-light" : ""}.svg`, import.meta.url), "utf8");
  return s.slice(s.indexOf(">") + 1, s.lastIndexOf("</svg>")).replace(/<title>.*?<\/title>/, "");
};
export const strait = JSON.parse(readFileSync(new URL("../assets/strait-coast.json", import.meta.url), "utf8")) as { W: number; H: number; fill: string[]; coast: string[] };
