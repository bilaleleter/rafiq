// Lists every UI string that goes through t()/tr() plus the label tables translated indirectly.
// Usage: node scripts/i18n-keys.mjs [--check]   (--check exits 1 if fr/ar miss a key)
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
const files = [];
const walk = (d) => readdirSync(d).forEach((f) => { const p = join(d, f); statSync(p).isDirectory() ? walk(p) : /\.(jsx?|mjs)$/.test(f) && files.push(p); });
walk("src");
const keys = new Set();
const direct = /\bt[r]?\(\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g;
const ternary = /\bt[r]?\(\s*[^()"']*?\?\s*("(?:[^"\\]|\\.)*")\s*:\s*("(?:[^"\\]|\\.)*")/g;
const tables = /\b(?:T|L)\(\s*(?:"[^"]*",\s*)?(?:"[^"]*",\s*)?(?:\[[^\]]*\],\s*)?"([^"]+)"\s*\)/g;
const statusTable = /\bS\(\s*"[^"]*",\s*"([^"]+)",\s*"--[a-z-]+"\s*\)/g;
for (const f of files) {
  if (f.includes("DevPanel") || f.includes("i18n.dict")) continue;
  const s = readFileSync(f, "utf8");
  for (const m of s.matchAll(direct)) keys.add(JSON.parse(m[1].startsWith("'") ? `"${m[1].slice(1, -1).replace(/"/g, '\\"')}"` : m[1]));
  for (const m of s.matchAll(ternary)) { keys.add(JSON.parse(m[1])); keys.add(JSON.parse(m[2])); }
  for (const m of s.matchAll(tables)) keys.add(m[1]);
  for (const m of s.matchAll(statusTable)) keys.add(m[1]);
  // label tables: [["key", "Label"], ...] / {k: "Label"} passed to t() later
  for (const block of s.matchAll(/const (QUICK|BODY|KINDS|FILTERS|SOURCES|NUM_LABEL|CAT|CAT_PLURAL|METHOD|ANCHOR|M) = ([\s\S]*?);\n/g)) {
    const body = block[2];
    if (["NUM_LABEL", "CAT", "CAT_PLURAL", "ANCHOR"].includes(block[1])) for (const m of body.matchAll(/:\s*"([^"]+)"/g)) keys.add(m[1]);
    else if (block[1] === "METHOD" || block[1] === "M") for (const m of body.matchAll(/"([^"]+)"/g)) { if (!/^[a-z-]+$/.test(m[1]) || m[1].includes(" ")) keys.add(m[1]); }
    else for (const m of body.matchAll(/\["[a-z_]+",\s*(?:"[a-z-]+",\s*)?"([^"]+)"/g)) keys.add(m[1]);
  }
}
// tab labels in App.jsx and sourceOf names are caught by the regexes above; add dynamic ones:
["Explore", "Trip", "Report", "SOS", "confirmed", "likely", "unconfirmed"].forEach((k) => keys.add(k));
const list = [...keys].filter((k) => k && !k.startsWith("--") && k !== "..." && !/^[a-z]+_[a-z_]+$/.test(k)).sort();
if (process.argv.includes("--check")) {
  const dict = readFileSync("src/i18n.dict.js", "utf8");
  const { FR, AR } = await import(new URL("../src/i18n.dict.js", import.meta.url));
  const miss = { fr: list.filter((k) => !(k in FR)), ar: list.filter((k) => !(k in AR)) };
  const extra = Object.keys(FR).filter((k) => !list.includes(k));
  console.log(`keys ${list.length} · missing fr ${miss.fr.length} · missing ar ${miss.ar.length} · unused ${extra.length}`);
  if (miss.fr.length || miss.ar.length) { console.log(JSON.stringify(miss, null, 1)); process.exit(1); }
  if (extra.length) console.log("unused:", JSON.stringify(extra));
} else console.log(JSON.stringify(list, null, 0));
