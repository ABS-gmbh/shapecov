// Check "transactions_decode" for js-stellar-sdk.
//
//   node tx_decode.mjs <sdk alias> < txcases.tsv > results.tsv
//
// Input: the TSV written by tools/txcases.py. For each transaction, the SDK's own transaction
// model (TransactionBuilder.fromXDR) must decode the envelope and report the hash, operation
// count and source account that the ledger implies. Output: entry, index, status, detail.
//   pass        decoded, and hash, operation count and source all match
//   mishandled  decoded without an error but reported a different value
//   error       the SDK raised an error on a transaction the network accepted
import { readFileSync } from "node:fs";

const alias = process.argv[2];
const sdk = await import(alias);
const lines = readFileSync(0, "utf8").split("\n").filter(Boolean);
for (const line of lines) {
  const [entry, index, passphrase, b64, hash, ops, source] = line.split("\t");
  let status = "pass", detail = "";
  try {
    const tx = sdk.TransactionBuilder.fromXDR(b64, passphrase);
    const inner = tx.innerTransaction ?? tx;
    const got = {
      hash: Buffer.from(tx.hash()).toString("hex"),
      ops: String(inner.operations.length),
      source: tx.innerTransaction ? tx.feeSource : tx.source,
    };
    const wrong = [];
    if (got.hash !== hash) wrong.push(`hash ${got.hash}`);
    if (got.ops !== ops) wrong.push(`operations ${got.ops} (expected ${ops})`);
    if (got.source !== source) wrong.push(`source ${got.source} (expected ${source})`);
    if (wrong.length) { status = "mishandled"; detail = wrong.join("; "); }
  } catch (e) {
    status = "error";
    detail = String(e.message).split("\n")[0].slice(0, 200);
  }
  console.log([entry, index, status, detail].join("\t"));
}
