import { renderToStaticMarkup } from "react-dom/server";
import { writeFileSync } from "node:fs";
import { StraitMap } from "../src/components/StraitMap";
import { c } from "../src/tokens";
const k = 8;
writeFileSync("dbg.html", `<body style="margin:0;background:#0a0a0a">${renderToStaticMarkup(<div><StraitMap w={165 * k / 1.5} h={146 * k / 1.5} view={[0, 0, 165, 146]} children={(P) => <>{Array.from({ length: 17 }, (_, i) => <text key={i} x={P(i * 10, 0)[0]} y={12} fill="#f47b3c" fontSize={11}>{i * 10}</text>)}{Array.from({ length: 15 }, (_, i) => <text key={i} x={2} y={P(0, i * 10)[1]} fill="#f47b3c" fontSize={11}>{i * 10}</text>)}</>} /></div>)}</body>`);
