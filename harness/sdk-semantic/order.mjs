// Checks "pool_pair_accepted" and "map_keys_host_order" for js-stellar-sdk (js-stellar-sdk#1766).
//
//   node order.mjs <sdk alias> <check> <XDR type> <value as base64> [<expected pool ID hex>]
//
// The value is the XDR at the manifest path, extracted by tools/corpus_check.py with the
// independent decoder, so an SDK that cannot decode the whole (newer) ledger is still tested on
// this one behaviour. Prints one JSON line.
//
// pool_pair_accepted   a liquidity-pool asset pair the network accepted, in the network's order:
//                      new LiquidityPoolAsset() must accept it, and getLiquidityPoolId() must give
//                      the pool ID the ledger records (expected, from the manifest).
// map_keys_host_order  a map the Soroban host wrote, in host key order: scvSortedMap() given the
//                      entries reversed must reproduce the host's exact bytes.
// string_bytes_kept    a memo whose text is not UTF-8 (js-stellar-sdk#1823): rebuilding it from the
//                      arm's `.value` must give the same bytes. Also reports whether the SDK's own
//                      Memo.fromXDRObject() round trip keeps them.
import { readFileSync } from "node:fs";

const [alias, check, type, b64, expected] = process.argv.slice(2);
const sdk = await import(alias);
const version = JSON.parse(
  readFileSync(new URL(`./node_modules/${alias}/package.json`, import.meta.url)),
).version;
const out = { sdk: `@stellar/stellar-sdk ${version}`, check };
// The schema writes SCVal where the SDK writes ScVal; accept either.
const xdrType = sdk.xdr[type] ?? sdk.xdr[type.replace(/^SC/, "Sc")];
const value = xdrType.fromXDR(b64, "base64");
// XDR fields are accessor methods before 17.x and plain properties from 17.x.
const f = (o, k) => (typeof o[k] === "function" ? o[k]() : o[k]);
const keyName = (k) => (typeof k.switch === "function" ? k.switch().name : (k.type ?? k.switch?.name ?? String(k)));

if (check === "string_bytes_kept") {
  const want = value.toXDR("hex");
  const viaValue = sdk.xdr.Memo.memoText(value.value).toXDR("hex");
  const viaMemo = sdk.Memo.fromXDRObject(value).toXDRObject().toXDR("hex");
  out.result = viaValue === want ? "pass" : "mishandled";
  out.detail = viaValue === want ? "" : `rebuilt from .value: ${viaValue}, the ledger has ${want}` +
    `; Memo.fromXDRObject round trip ${viaMemo === want ? "keeps the bytes" : "changes them too"}`;
  console.log(JSON.stringify(out));
  process.exit(0);
}

if (check === "pool_pair_accepted") {
  try {
    const a = sdk.Asset.fromOperation(f(value, "assetA"));
    const b = sdk.Asset.fromOperation(f(value, "assetB"));
    const lp = new sdk.LiquidityPoolAsset(a, b, f(value, "fee"));
    const id = Buffer.from(sdk.getLiquidityPoolId("constant_product", lp.getLiquidityPoolParameters())).toString("hex");
    out.pool_id = id;
    out.result = id === expected ? "pass" : "mishandled";
    if (id !== expected) out.detail = `pool ID ${id}, the ledger records ${expected}`;
  } catch (e) {
    out.result = "mishandled";
    out.detail = `rejected an asset pair the network accepted: ${e.message}`;
  }
} else if (check === "map_keys_host_order") {
  const entries = f(value, "map");
  const reversed = [...entries].reverse();
  try {
    const sorted = sdk.scvSortedMap(reversed);
    const ok = sorted.toXDR("base64") === b64;
    out.result = ok ? "pass" : "mishandled";
    if (!ok) {
      const keys = (m) => f(m, "map").map((e) => keyName(f(e, "key"))).join(", ");
      out.detail = `scvSortedMap gives keys in the order [${keys(sorted)}]; the host wrote [${keys(value)}]`;
    }
  } catch (e) {
    out.result = "mishandled";
    out.detail = `scvSortedMap refused a map the host wrote: ${e.message}`;
  }
} else {
  out.result = "error";
  out.detail = `unknown check ${check}`;
}
console.log(JSON.stringify(out));
