#!/usr/bin/env node
// RFP sighting 17, js-xdr#165: Writer primitives coerce invalid inputs instead of throwing.
//
//   node check.cjs              js-xdr as pinned here (5.0.0, the latest release): each of the issue's own
//                               cases must behave as the issue shows (silently coerced); exit 1 otherwise
//   node check.cjs --dir DIR    js-xdr as installed under DIR/node_modules (the weekly run installs the newest
//                               published release there): exit 1 once it rejects the cases with XdrError, the
//                               sign that a release carries the fix (PR #173, merged 16 October 2026) and the
//                               scoreboard row can become a before-and-after pair
//
// The cases are the issue's own reproduction, unchanged.
"use strict";
const path = require("path");

const args = process.argv.slice(2);
const dir = args[0] === "--dir" ? path.resolve(args[1]) : __dirname;
const lib = require(require.resolve("@stellar/js-xdr", { paths: [dir] }));
const version = require(require.resolve("@stellar/js-xdr/package.json", { paths: [dir] })).version;
const hex = (u) => Buffer.from(u).toString("hex");

// [name, what the issue shows on 5.0.0, a function returning the observed value]
const CASES = [
  ["writeUint32(2 ** 32)", "00000000", () => { const w = new lib.Writer(); w.writeUint32(2 ** 32); return hex(w.toUint8Array()); }],
  ["writeUint32(-1)", "ffffffff", () => { const w = new lib.Writer(); w.writeUint32(-1); return hex(w.toUint8Array()); }],
  ["writeInt32(1000.75)", "000003e8", () => { const w = new lib.Writer(); w.writeInt32(1000.75); return hex(w.toUint8Array()); }],
  ["writeUint32(NaN)", "00000000", () => { const w = new lib.Writer(); w.writeUint32(NaN); return hex(w.toUint8Array()); }],
  ["writeInt32(2 ** 31)", "80000000", () => { const w = new lib.Writer(); w.writeInt32(2 ** 31); return hex(w.toUint8Array()); }],
  ["writePadding(1.5), then offset", "2.5", () => { const w = new lib.Writer(); w.writePadding(1.5); return String(w.offset); }],
  ["writeBytes({ length: -4 }) after two words, then a third", "aaaaaaaacccccccc", () => {
    const w = new lib.Writer();
    w.writeUint32(0xaaaaaaaa); w.writeUint32(0xbbbbbbbb);
    w.writeBytes({ length: -4 });
    w.writeUint32(0xcccccccc);
    return hex(w.toUint8Array());
  }],
];

let coerced = 0, rejected = 0, other = 0;
for (const [name, shown, run] of CASES) {
  let got;
  try {
    got = run();
  } catch (e) {
    const isXdr = lib.XdrError && e instanceof lib.XdrError;
    got = (isXdr ? "XdrError: " : (e && e.name ? e.name + ": " : "error: ")) + (e && e.message);
    if (isXdr) rejected++; else other++;
    console.log(`rejected  ${name}: ${got}`);
    continue;
  }
  if (got === shown) coerced++; else other++;
  console.log(`${got === shown ? "coerced " : "DIFFERS "}  ${name}: ${got}${got === shown ? "" : ` (the issue shows ${shown})`}`);
}
console.log(`js-xdr ${version}: ${coerced} coerced as the issue shows, ${rejected} rejected with XdrError, ${other} other`);
if (args[0] === "--dir") {
  if (rejected) {
    console.log(`JS-XDR ${version} REJECTS ${rejected} OF THE ISSUE'S CASES: a release carries the fix; ` +
                `make harness/sightings/README.md row 17 a before-and-after pair`);
    process.exit(1);
  }
  console.log(`JS-XDR ${version} STILL COERCES: no published release carries the fix yet`);
  process.exit(0);
}
if (coerced !== CASES.length) {
  console.log("JS-XDR#165 DIFFERS: not every case behaves on the pinned release as the issue shows");
  process.exit(1);
}
console.log("JS-XDR#165 OK: every case coerced on the pinned release, as the issue shows");
