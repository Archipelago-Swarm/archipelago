# ARCHIPELAGO media kit

Code-generated brand, Devpost and GitHub assets (React + SVG, rendered to PNG with Playwright/Chromium). Standalone: not in the root npm workspaces, not run by CI, needs no backend, Docker or secrets.

```sh
cd brand-kit
npm install
npm run render:graphics              # everything -> exports/
npm run render:graphics -- slide-05  # only matching files, or a group: logo | devpost | github | brand-guide
npm run typecheck
```

A Chromium is needed: Playwright's (`npx playwright-core install chromium`), else installed Chrome/Edge, or set `CHROMIUM_PATH`.

## Brand direction (defense is the core theme)

ARCHIPELAGO is decentralized learning for collaborative autonomous platforms: UAV squadrons in contested, communications-constrained environments, with the Taiwan Strait as the demo scenario. Defense and military-adjacent imagery (fixed-wing UAVs, operational maps, sensor footprints, comms-denied zones) is on-brand and expected. This replaces the earlier media-kit rule that said to avoid military-specific positioning. The brand stays broad enough for search and rescue, robotics and disaster response, so the logo and system never depend on drone clipart. Avoid photorealistic war imagery, crypto and cyberpunk looks, and generic AI gradients. Slogan: **Decentralized learning across UAV squadrons.** Palette: black 60 / stone+white 30 / orange <=10. Details in `docs/BRAND_DIRECTION.md`.

## Layout

| Path | What |
|---|---|
| `src/components/` | `StraitMap` (real coast mask), `Scenario` (routes, footprints, partition), `FixedWing`, `motifs` (Card, Tag, Telemetry, Callout, Divider, Icon, SectionTitle), `primitives` |
| `src/slides/` | 11 slide templates (`slides-a.tsx` 1-5, `slides-b.tsx` 6-11) on a shared `Slide` frame |
| `src/figures/` | `logos.ts` (SVG lockups), `devpost-github.tsx` (thumbnail, social, banner, README figures), `guide.tsx` |
| `src/registry.tsx` | the list of exports (size, scale, group) |
| `assets/strait-coast.json` | coastline paths, generated once by `scripts/extract-coast.mjs` from the demo's terrain mask |
| `public/brand/` | media-kit logo SVGs and `brand.json` |
| `exports/{logo,devpost,github,brand-guide}/` | outputs (PNG; logos also SVG) |

## Exports

- `exports/logo/`: icon, horizontal, stacked, primary (with slogan) x dark/light, SVG + transparent PNG; `archipelago-icon-square-1024.png` for avatars. SVG wordmarks are live Arial Bold text.
- `exports/devpost/`: `thumbnail-3x2-1500x1000.png` (+ 3000x2000), `slide-01..11-*.png` (1920x1080).
- `exports/github/`: `social-preview-1280x640`, `readme-banner-1600x400`, `readme-architecture`, `readme-how-it-works`, `readme-capability-transfer`, `readme-stack`.
- `exports/brand-guide/brand-guide.png`.

## Editing

Change copy and layout in the component files and re-render. All maps, routes, topologies and node states are **illustrative**; the replay slide is a template with no values. Never put unmeasured numbers into an export. To feed real results into a chart, pass measured data to a component and cite its source on the graphic.

## Needs human input

See `docs/BRAND_DIRECTION.md` (open items): demo URL, roadmap status tags, the updated project story text, and whether to name Taiwan Strait labels on public assets.
