// Check "ids_exact" for js-stellar-sdk.
//
//   node ids.mjs <sdk alias> <entry .xdr.b64> <spec.json>
//
// spec.json is the manifest's expected.sdk item: the exact text every 64-bit identifier in the
// entry must decode to, and inputs the SDK's builders must refuse. Prints one JSON line.
import { readFileSync } from "node:fs";

const [alias, file, specFile] = process.argv.slice(2);
const sdk = await import(alias);
const version = JSON.parse(readFileSync(new URL(`./node_modules/${alias}/package.json`, import.meta.url))).version;
const spec = JSON.parse(readFileSync(specFile, "utf8"));
const b64 = readFileSync(file, "utf8").trim();
const out = { sdk: `@stellar/stellar-sdk ${version}`, check: "ids_exact", wrong: [], accepted: [] };
const G = "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ";

try {
  const tx = sdk.TransactionBuilder.fromXDR(b64, sdk.Networks.TESTNET);
  const stroops = (dec) => { const [a, b = ""] = String(dec).split("."); return (BigInt(a) * 10000000n + BigInt((b + "0000000").slice(0, 7))).toString(); };
  const got = {
    offer_id: String(tx.operations[0].offerId),
    source: tx.source,
    destination: tx.operations[1].destination,
    memo_id: String(tx.memo.value),
    amount_stroops: stroops(tx.operations[1].amount),
  };
  for (const [k, v] of Object.entries(got)) if (spec.ids[k] !== v) out.wrong.push(`${k}: decoded ${v}, expected ${spec.ids[k]}`);
} catch (e) {
  out.wrong.push(`decode failed: ${String(e.message).split("\n")[0]}`);
}

const tryBuild = (kind, input) => {
  if (kind === "offer_id") {
    const op = sdk.Operation.manageSellOffer({ selling: sdk.Asset.native(), buying: new sdk.Asset("USD", G), amount: "1", price: "1", offerId: input });
    return String(sdk.Operation.fromXDRObject(op).offerId);
  }
  const m = new sdk.MuxedAccount(new sdk.Account(G, "1"), input);
  return `${m.accountId()} (id() returns ${JSON.stringify(m.id())})`;
};
for (const [kind, cases] of Object.entries(spec.must_reject)) {
  for (const c of cases) {
    try {
      const encoded = tryBuild(kind, c.input);
      out.accepted.push(`${kind} ${JSON.stringify(c.input)} (${c.why}) accepted, encodes ${encoded}`);
    } catch { /* rejected, as required */ }
  }
}
out.result = out.wrong.length || out.accepted.length ? "mishandled" : "pass";
console.log(JSON.stringify(out));
