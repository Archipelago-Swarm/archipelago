import { createElement, type ReactElement } from "react";
import { BrandGuide, GH, GW } from "./figures/guide";
import { CapabilityTransfer, DevpostThumb, GithubSocial, ReadmeBanner, Scaled } from "./figures/devpost-github";
import { logoSvg, logoUri, type Layout, type Theme } from "./figures/logos";
import { S1Hero, S2Problem, S3What, S4How, S5Scenario } from "./slides/slides-a";
import { S10Roadmap, S11End, S6Arch, S7Results, S8Stack, S9Insight } from "./slides/slides-b";
import { H, W } from "./slides/frame";

/** One entry per exported file. Output px = w*scale x h*scale. `svg` also writes a standalone .svg next to the PNG. */
export interface Out { group: "logo" | "devpost" | "github" | "brand-guide"; file: string; w: number; h: number; scale: number; el: () => ReactElement; transparent?: boolean; svg?: string }

const slides: [string, () => ReactElement][] = [
  ["01-hero", S1Hero], ["02-problem", S2Problem], ["03-what-it-does", S3What], ["04-how-it-works", S4How], ["05-operational-scenario", S5Scenario],
  ["06-architecture", S6Arch], ["07-replay-observability", S7Results], ["08-stack", S8Stack], ["09-what-we-learned", S9Insight], ["10-roadmap", S10Roadmap], ["11-end", S11End],
];
const logos: Out[] = [];
for (const layout of ["icon", "horizontal", "stacked", "primary"] as Layout[]) {
  for (const theme of ["dark", "light"] as Theme[]) {
    const { w, h, svg } = logoSvg(layout, theme);
    const width = layout === "icon" ? 1000 : 2400; // PNG width
    const k = width / w;
    logos.push({ group: "logo", file: `archipelago-${layout}-${theme}`, w: width, h: Math.round(h * k), scale: 1, transparent: true, svg, el: () => createElement("img", { src: logoUri(layout, theme), width, height: Math.round(h * k), style: { display: "block" } }) });
  }
}
// Square social avatar: dark solid
logos.push({ group: "logo", file: "archipelago-icon-square-1024", w: 1024, h: 1024, scale: 1, el: () => createElement("div", { style: { width: 1024, height: 1024, background: "#0A0A0A", display: "flex", alignItems: "center", justifyContent: "center" } }, createElement("img", { src: logoUri("icon", "dark"), height: 700 })) });

export const OUTPUTS: Out[] = [
  ...logos,
  { group: "devpost", file: "thumbnail-3x2-1500x1000", w: 1500, h: 1000, scale: 1, el: () => createElement(DevpostThumb) },
  { group: "devpost", file: "thumbnail-3x2-3000x2000", w: 1500, h: 1000, scale: 2, el: () => createElement(DevpostThumb) },
  ...slides.map(([f, C]): Out => ({ group: "devpost", file: `slide-${f}`, w: W, h: H, scale: 1, el: () => createElement(C) })),
  { group: "github", file: "social-preview-1280x640", w: 1280, h: 640, scale: 1, el: () => createElement(GithubSocial) },
  { group: "github", file: "readme-banner-1600x400", w: 1600, h: 400, scale: 1, el: () => createElement(ReadmeBanner) },
  { group: "github", file: "readme-architecture", w: 1200, h: 675, scale: 1, el: () => createElement(Scaled, { k: 0.625, w: W, h: H, children: createElement(S6Arch) }) },
  { group: "github", file: "readme-how-it-works", w: 1200, h: 675, scale: 1, el: () => createElement(Scaled, { k: 0.625, w: W, h: H, children: createElement(S4How) }) },
  { group: "github", file: "readme-capability-transfer", w: 1200, h: 520, scale: 1, el: () => createElement(CapabilityTransfer) },
  { group: "github", file: "readme-stack", w: 1200, h: 675, scale: 1, el: () => createElement(Scaled, { k: 0.625, w: W, h: H, children: createElement(S8Stack) }) },
  { group: "brand-guide", file: "brand-guide", w: GW, h: GH, scale: 1, el: () => createElement(BrandGuide) },
];
