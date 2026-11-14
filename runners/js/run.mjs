// JS runner: @stellar/stellar-sdk. Reads "id\ttype\tb64", writes "id\tstatus\tpayload".
import { xdr } from "@stellar/stellar-sdk";
import readline from "node:readline";
const byName = new Map(Object.keys(xdr).map((k) => [k.toLowerCase(), xdr[k]]));
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
const clean = (s) => String(s).replace(/[\t\n\r]/g, " ").slice(0, 300);
for await (const line of rl) {
  const [id, type, b64] = line.split("\t");
  const T = xdr[type] ?? byName.get(type.toLowerCase());
  let out;
  if (!T || (typeof T.fromXDR !== "function" && typeof T.fromXdr !== "function")) out = `${id}\tnotype\t`;
  else {
    try {
      const v = T.fromXDR ? T.fromXDR(b64, "base64") : T.fromXdr(Buffer.from(b64, "base64"));
      if (v === null || typeof v !== "object" || (typeof v.toXDR !== "function" && typeof v.toXdr !== "function")) {
        out = `${id}\tnotype\t`; // bare primitive typedef: no value-level encoder to round-trip through
      } else {
        const enc = typeof v.toXDR === "function" ? v.toXDR("base64") : Buffer.from(v.toXdr()).toString("base64");
        out = `${id}\tok\t${enc}`;
      }
    } catch (e) {
      out = `${id}\terr\t${clean(e && e.message)}`;
    }
  }
  process.stdout.write(out + "\n");
}
