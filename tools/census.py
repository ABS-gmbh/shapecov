#!/usr/bin/env python3
"""Shape census: how often each named pattern occurs in a sample of real ledgers, and the largest
values seen for the sizes the hardening guide sets caps on.

  census.py --corpus DIR [--jobs N] [--out corpus/CENSUS.md] [--json corpus/census.json]

DIR is a corpus directory (manifest.json, entries/) of network ledgers, such as the sweep built by
harness/replay/sweep.py. For every ledger and every transaction in it:

- patterns: the named patterns of tools/mine.py, counted per ledger and per transaction. A
  transaction's envelope is matched to its processing record by transaction hash, so a pattern
  that shows in both counts once;
- maxima, each with the ledger and transaction where it occurs: authorization-tree depth, ScVal
  nesting depth, vector and map lengths, string, symbol and bytes lengths in ScVals, memo text
  length, operations per transaction, signatures per envelope.

Counts are per network and per protocol. The output states the sample; it is not a measurement of
the whole network.
"""
import argparse
import base64
import concurrent.futures as cf
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mine  # noqa: E402
from decode import Decoder  # noqa: E402
from encode import Encoder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NETS = {"Public Global Stellar Network ; September 2015": "pubnet", "Test SDF Network ; September 2015": "testnet"}
MAXIMA = ["auth_tree_depth", "scval_depth", "scvec_length", "scmap_length", "scstring_bytes", "scsymbol_bytes",
          "scbytes_bytes", "memo_text_bytes", "operations_per_tx", "signatures_per_envelope"]


def envelopes(body):
    """Every TransactionEnvelope in a LedgerCloseMeta body's transaction set."""
    ts = body.get("txSet") or {}
    if "txs" in ts:
        return ts["txs"]
    out = []
    for ph in (ts.get("v1TxSet") or {}).get("phases", []):
        for comp in ph.get("v0Components") or []:
            out += (comp.get("txsMaybeDiscountedFee") or {}).get("txs", [])
        par = ph.get("parallelTxsComponent")
        if par:
            for stage in par.get("executionStages", []):
                for cluster in stage:
                    out += cluster
    return out


def tx_hash(enc, network_id, env):
    t = env["type"]
    if t == "ENVELOPE_TYPE_TX_FEE_BUMP":
        tagged = {"type": t, "feeBump": env["feeBump"]["tx"]}
    elif t == "ENVELOPE_TYPE_TX":
        tagged = {"type": t, "tx": env["v1"]["tx"]}
    else:  # ENVELOPE_TYPE_TX_V0 hashes as a v1 transaction
        v0 = env["v0"]["tx"]
        tagged = {"type": "ENVELOPE_TYPE_TX", "tx": {
            "sourceAccount": {"type": "KEY_TYPE_ED25519", "ed25519": v0["sourceAccountEd25519"]},
            "fee": v0["fee"], "seqNum": v0["seqNum"],
            "cond": {"type": "PRECOND_TIME", "timeBounds": v0["timeBounds"]} if v0.get("timeBounds") else {"type": "PRECOND_NONE"},
            "memo": v0["memo"], "operations": v0["operations"], "ext": {"v": 0}}}
    return hashlib.sha256(enc.encode("TransactionSignaturePayload", {"networkId": network_id, "taggedTransaction": tagged})).hexdigest()


def measure(x, m):
    """Update maxima m from one decoded value."""
    if isinstance(x, list):
        for v in x:
            measure(v, m)
        return
    if not isinstance(x, dict):
        return
    t = x.get("type")
    if "rootInvocation" in x:
        m["auth_tree_depth"] = max(m["auth_tree_depth"], mine.auth_depth(x["rootInvocation"]))
    if t in ("SCV_VEC", "SCV_MAP"):
        m["scval_depth"] = max(m["scval_depth"], mine.scval_depth(x))
        if t == "SCV_VEC" and x.get("vec"):
            m["scvec_length"] = max(m["scvec_length"], len(x["vec"]))
        if t == "SCV_MAP" and x.get("map"):
            m["scmap_length"] = max(m["scmap_length"], len(x["map"]))
    for typ, field, key in (("SCV_STRING", "str", "scstring_bytes"), ("SCV_SYMBOL", "sym", "scsymbol_bytes"),
                            ("SCV_BYTES", "bytes", "scbytes_bytes")):
        if t == typ and field in x:
            v = x[field]
            n = len(bytes.fromhex(v["$hex"])) if isinstance(v, dict) else (len(v) // 2 if typ == "SCV_BYTES" else len(v.encode()))
            m[key] = max(m[key], n)
    if t == "MEMO_TEXT" and "text" in x:
        v = x["text"]
        m["memo_text_bytes"] = max(m["memo_text_bytes"], len(bytes.fromhex(v["$hex"])) if isinstance(v, dict) else len(v.encode()))
    if isinstance(x.get("operations"), list) and x["operations"] and isinstance(x["operations"][0], dict) \
            and "body" in x["operations"][0]:
        m["operations_per_tx"] = max(m["operations_per_tx"], len(x["operations"]))
    if isinstance(x.get("signatures"), list):
        m["signatures_per_envelope"] = max(m["signatures_per_envelope"], len(x["signatures"]))
    for v in x.values():
        measure(v, m)


def one(args):
    path, passphrase = args
    schema = json.load(open(ROOT / "schema" / "schema.json"))
    dec, enc = Decoder(schema), Encoder(schema)
    value = dec.decode("LedgerCloseMeta", base64.b64decode(open(path).read()))
    ver = "v%d" % value["v"]
    body = value[ver]
    nid = hashlib.sha256(passphrase.encode()).hexdigest()
    by_hash = {}
    for env in envelopes(body):
        try:
            by_hash[tx_hash(enc, nid, env)] = env
        except Exception:  # noqa: BLE001  an envelope that does not re-encode is still counted by its meta
            pass
    txs, unmatched = [], 0
    for tp in body.get("txProcessing", []):
        h = tp["result"]["transactionHash"]
        env = by_hash.get(h)
        unmatched += env is None
        mini = {"v": value["v"], ver: {"txProcessing": [tp], "envelope": env}}
        m = dict.fromkeys(MAXIMA, 0)
        measure(env, m)
        measure(tp, m)
        txs.append({"hash": h, "patterns": sorted(mine.patterns(mini)), "maxima": m})
    hdr = body["ledgerHeader"]["header"]
    return {"seq": hdr["ledgerSeq"], "protocol": hdr["ledgerVersion"], "network": NETS.get(passphrase, "other"),
            "patterns": sorted(mine.patterns(value)), "txs": txs, "unmatched": unmatched}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "corpus" / "CENSUS.md"))
    ap.add_argument("--json", default=str(ROOT / "corpus" / "census.json"))
    a = ap.parse_args()
    corpus = Path(a.corpus)
    manifest = json.load(open(corpus / "manifest.json"))
    work = [(str(corpus / e["file"]), e["source"]["network_passphrase"]) for e in manifest["entries"]
            if e.get("xdr_type") == "LedgerCloseMeta"]
    with cf.ProcessPoolExecutor(a.jobs) as ex:
        ledgers = list(ex.map(one, work, chunksize=2))
    catalog = json.load(open(ROOT / "corpus" / "patterns.json"))["patterns"]
    groups = {}
    for L in ledgers:
        groups.setdefault((L["network"], L["protocol"]), []).append(L)
    cols = sorted(groups)
    stats = {"sample": {"ledgers": len(ledgers), "transactions": sum(len(L["txs"]) for L in ledgers),
                        "unmatched_envelopes": sum(L["unmatched"] for L in ledgers),
                        "by_network_protocol": {"%s p%d" % k: {"ledgers": len(v), "transactions": sum(len(L["txs"]) for L in v)}
                                                for k, v in sorted(groups.items())}},
             "patterns": {}, "maxima": {}}
    for p in catalog:
        row = {}
        for k in cols:
            ls = groups[k]
            row["%s p%d" % k] = {"ledgers": sum(p in L["patterns"] for L in ls),
                                 "transactions": sum(p in t["patterns"] for L in ls for t in L["txs"])}
        stats["patterns"][p] = {"ledgers": sum(p in L["patterns"] for L in ledgers),
                                "transactions": sum(p in t["patterns"] for L in ledgers for t in L["txs"]), "by": row}
    for key in MAXIMA:
        best = {}
        for L in ledgers:
            for t in L["txs"]:
                b = best.get(L["network"])
                if b is None or t["maxima"][key] > b["value"]:
                    best[L["network"]] = {"value": t["maxima"][key], "ledger": L["seq"], "protocol": L["protocol"], "tx": t["hash"]}
        stats["maxima"][key] = best
    json.dump(stats, open(a.json, "w"), indent=1, sort_keys=True)
    s = stats["sample"]
    lines = ["# Shape census", "",
             "Generated by `tools/census.py` from a sample of network ledgers. Do not edit by hand.", "",
             "**The sample:** %d ledgers holding %d transactions: every 20,000th ledger of pubnet from 59,000,000 "
             "(protocol 23) to 65,480,000 and of testnet since its December 2025 reset, from Stellar's public ledger "
             "archive (`harness/replay/README.md`, \"Sweep\"). That is about one ledger in 20,000; counts are of this "
             "sample, not of the network, and a shape absent here can still occur." % (s["ledgers"], s["transactions"]), "",
             "| Network, protocol | Ledgers | Transactions |", "|---|---|---|"]
    for k, v in s["by_network_protocol"].items():
        lines.append("| %s | %d | %d |" % (k, v["ledgers"], v["transactions"]))
    lines += ["", "## Named patterns", "",
              "Ledgers and transactions in the sample that contain each pattern (`corpus/patterns.json`). A transaction "
              "counts once, whether the pattern is in its envelope, its result or its meta.", "",
              "| Pattern | Ledgers | Transactions | Share of transactions | By network and protocol (transactions) |",
              "|---|---|---|---|---|"]
    for p, v in sorted(stats["patterns"].items(), key=lambda kv: (-kv[1]["transactions"], kv[0])):
        by = ", ".join("%s: %d" % (k, x["transactions"]) for k, x in v["by"].items() if x["transactions"])
        share = "%.3f%%" % (100.0 * v["transactions"] / s["transactions"]) if s["transactions"] else "—"
        lines.append("| `%s` | %d | %d | %s | %s |" % (p, v["ledgers"], v["transactions"], share, by or "not seen"))
    notes = {"scval-wide-integer": "From protocol 23 every transaction emits a CAP-67 fee event whose amount is an "
                                   "i128, so every transaction in this sample carries one.",
             "soroban-created-trustline": "The shape behind wallet-backend#731 and stellar-etl#460: one transaction in "
                                          "the whole sample, which is why the corpus keeps such shapes on purpose."}
    lines += [""] + ["- `%s`: %s" % (p, n) for p, n in notes.items()]
    labels = {"auth_tree_depth": "Authorization-tree depth (root = 1)", "scval_depth": "ScVal nesting depth (vectors and maps)",
              "scvec_length": "ScVal vector length", "scmap_length": "ScVal map length",
              "scstring_bytes": "ScVal string length (bytes)", "scsymbol_bytes": "ScVal symbol length (bytes)",
              "scbytes_bytes": "ScVal bytes length", "memo_text_bytes": "Memo text length (bytes)",
              "operations_per_tx": "Operations per transaction", "signatures_per_envelope": "Signatures per envelope"}
    lines += ["", "## Largest values seen", "",
              "The largest value of each size in the sample, with where it occurs, for comparison with the caps in "
              "`guide/INDEXER-HARDENING.md`. These are observations, not limits: the protocol allows more.", "",
              "| Size | pubnet | testnet |", "|---|---|---|"]
    for key in MAXIMA:
        cells = []
        for net in ("pubnet", "testnet"):
            b = stats["maxima"][key].get(net)
            cells.append("**%d** (ledger %d, p%d, tx `%s…`)" % (b["value"], b["ledger"], b["protocol"], b["tx"][:12]) if b else "—")
        lines.append("| %s | %s |" % (labels[key], " | ".join(cells)))
    if s["unmatched_envelopes"]:
        lines += ["", "%d processing records had no envelope matched by hash; their envelope-side patterns are not "
                  "counted." % s["unmatched_envelopes"]]
    Path(a.out).write_text("\n".join(lines) + "\n")
    print("census: %d ledgers, %d transactions, %d unmatched" % (s["ledgers"], s["transactions"], s["unmatched_envelopes"]))


if __name__ == "__main__":
    main()
