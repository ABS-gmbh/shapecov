// Semantic check "map_entries_preserved" for js-stellar-sdk.
//
//   node map_entries.mjs <sdk alias> <XDR type> <entry .xdr.b64> <path to an ScVal map> <expected entries>
//
// Decodes the corpus entry with the given SDK version, walks to the ScVal at
// <path>, converts it with scValToNative and counts the entries that survive.
// Prints one JSON line. The expected count comes from the corpus manifest.
import { readFileSync } from "node:fs";

const [alias, type, file, path, expected] = process.argv.slice(2);
const sdk = await import(alias);
const version = JSON.parse(
  readFileSync(new URL(`./node_modules/${alias}/package.json`, import.meta.url)),
).version;

let node = sdk.xdr[type].fromXDR(readFileSync(file, "utf8").trim(), "base64");
for (const m of path.matchAll(/([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]/g)) {
  if (m[1] === undefined) node = node[Number(m[2])];
  else node = typeof node[m[1]] === "function" ? node[m[1]]() : node[m[1]];
}
const mapOf = (v) => (typeof v.map === "function" ? v.map() : v.map);
const inXdr = mapOf(node).length;

const out = { sdk: `@stellar/stellar-sdk ${version}`, check: "map_entries_preserved", entries_in_xdr: inXdr };
try {
  const native = sdk.scValToNative(node);
  const kept = native instanceof Map ? native.size : Object.keys(native).length;
  out.entries_after_conversion = kept;
  out.converted = native instanceof Map ? [...native].map(([k, v]) => [typeof k, String(k), v]) : native;
  out.result = kept === Number(expected) ? "pass" : "mishandled";
  if (kept !== Number(expected)) out.detail = `${Number(expected) - kept} entry(ies) dropped without an error`;
} catch (e) {
  out.result = "pass";
  out.detail = `conversion refused with an error instead of dropping entries: ${e.message}`;
}
console.log(JSON.stringify(out));
