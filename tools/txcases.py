"""List every transaction in the corpus's ledgers, with what an SDK must report for it.

  txcases.py [out.tsv]

For each LedgerCloseMeta entry, every TransactionEnvelope in its transaction set is re-encoded on
its own and its hash is computed here, from the XDR and the entry's network passphrase, with no
Stellar SDK. Each hash must also be one the ledger itself records in txProcessing; if not, this
tool stops, because the expectation would be wrong.

Output columns: entry id, index, network passphrase, envelope base64, expected hash,
operation count, source account (G... or M...), envelope type.
"""
import base64
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import strkey  # noqa: E402
from decode import Decoder  # noqa: E402
from encode import Encoder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
ENVELOPE_TYPE_TX, ENVELOPE_TYPE_TX_FEE_BUMP = 2, 5


def envelopes(v, path=""):
    if isinstance(v, list):
        for k, x in enumerate(v):
            yield from envelopes(x, f"{path}[{k}]")
    elif isinstance(v, dict):
        if str(v.get("type", "")).startswith("ENVELOPE_TYPE_TX") and ({"v0", "v1", "feeBump"} & set(v)):
            yield path, v
            return
        for name, x in v.items():
            yield from envelopes(x, f"{path}.{name}" if path else name)


def source_strkey(m):
    if m["type"] == "KEY_TYPE_ED25519":
        return strkey.account(m["ed25519"])
    return strkey.muxed(m["med25519"]["ed25519"], m["med25519"]["id"])


def tx_hash(enc, env, passphrase):
    net = hashlib.sha256(passphrase.encode()).digest()
    if env["type"] == "ENVELOPE_TYPE_TX_FEE_BUMP":
        body = enc.encode("FeeBumpTransaction", env["feeBump"]["tx"])
        return hashlib.sha256(net + struct.pack(">i", ENVELOPE_TYPE_TX_FEE_BUMP) + body).hexdigest()
    if env["type"] == "ENVELOPE_TYPE_TX":
        tx = env["v1"]["tx"]
    else:  # a v0 envelope is hashed as the equivalent v1 transaction
        t = env["v0"]["tx"]
        tx = {"sourceAccount": {"type": "KEY_TYPE_ED25519", "ed25519": t["sourceAccountEd25519"]},
              "fee": t["fee"], "seqNum": t["seqNum"],
              "cond": ({"type": "PRECOND_TIME", "timeBounds": t["timeBounds"]} if t["timeBounds"] is not None
                       else {"type": "PRECOND_NONE"}),
              "memo": t["memo"], "operations": t["operations"], "ext": {"v": 0}}
    return hashlib.sha256(net + struct.pack(">i", ENVELOPE_TYPE_TX) + enc.encode("Transaction", tx)).hexdigest()


def describe(env):
    if env["type"] == "ENVELOPE_TYPE_TX_FEE_BUMP":
        inner = env["feeBump"]["tx"]["innerTx"]["v1"]["tx"]
        return len(inner["operations"]), source_strkey(env["feeBump"]["tx"]["feeSource"])
    if env["type"] == "ENVELOPE_TYPE_TX":
        return len(env["v1"]["tx"]["operations"]), source_strkey(env["v1"]["tx"]["sourceAccount"])
    t = env["v0"]["tx"]
    return len(t["operations"]), strkey.account(t["sourceAccountEd25519"])


def cases():
    schema = json.load(open(ROOT / "schema/schema.json"))
    dec, enc = Decoder(schema), Encoder(schema)
    manifest = json.load(open(CORPUS / "manifest.json"))
    for e in manifest["entries"]:
        if e["xdr_type"] != "LedgerCloseMeta":
            continue
        passphrase = e["source"]["network_passphrase"]
        v = dec.decode("LedgerCloseMeta", base64.b64decode((CORPUS / e["file"]).read_text().strip()))
        body = v[f"v{v['v']}"]
        recorded = {tp["result"]["transactionHash"] for tp in body.get("txProcessing", [])}
        for k, (path, env) in enumerate(envelopes(body["txSet"])):
            h = tx_hash(enc, env, passphrase)
            if h not in recorded:
                sys.exit(f"{e['id']} {path}: computed hash {h} is not recorded in the ledger")
            ops, src = describe(env)
            yield (e["id"], str(k), passphrase, base64.b64encode(enc.encode("TransactionEnvelope", env)).decode(),
                   h, str(ops), src, env["type"])


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "txcases.tsv"
    rows = list(cases())
    out.write_text("".join("\t".join(r) + "\n" for r in rows))
    kinds = {}
    for r in rows:
        kinds[r[7]] = kinds.get(r[7], 0) + 1
    print(json.dumps({"transactions": len(rows), "entries": len({r[0] for r in rows}), "by_type": kinds,
                      "muxed_sources": sum(r[6].startswith("M") for r in rows), "out": str(out)}))
