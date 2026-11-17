#!/usr/bin/env python3
"""stellar-etl#454, amounts above 2^53 stroops: does an exported amount read back to the ledger's
exact amount?

  python3 harness/replay/adapters/stellar-etl/amounts_check.py [OUT_DIR]

A narrow check, not an oracle rule over every amount. It reads the recorded exports of one corpus
ledger, `localcore-big-merge-4` (a payment of 2^53+1 stroops, then an account merge moving more than
2^53), in OUT_DIR (default harness/replay/out-stellar-etl), at every commit recorded there. Each
exported amount the issue names (an operation detail `amount`, `token_transfer.amount`) and, as a
control, each effect `amount` is read back exactly (the JSON number as written, as a decimal) and
times 10^7 compared with the exact amount the ledger gives: the payment's amount from the envelope,
each transfer's i128 from the CAP-67 event in the meta. Only amounts above 2^53 stroops count: below
that a float64 holds every stroop, and the issue's other half (the times 1e-7 scaling being inexact
for small values) would flag a large share of every export and bury the rest.

Exit 1 if what a field shows differs from the claim below, as the RFP sightings are checked.
"""
import glob
import gzip
import json
import os
import sys
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..", "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import oracle  # noqa: E402

ENTRY = "localcore-big-merge-4"
LIMIT = 2 ** 53
# field -> what stellar-etl at master shows for amounts above 2^53 stroops
CLAIMS = {"token_transfer.amount": "stroops lost", "operations.details.amount": "exact",
          "effects.details.amount": "exact"}


def exact_amounts():
    """{(tx_hash, op_order): {"payment": amount from the envelope, "transfers": [i128 from the meta's
    transfer events, in order]}} for the ledger."""
    _, v = oracle.load_entry(ENTRY)
    out = {}
    for tp in v["v%d" % v["v"]]["txProcessing"]:
        h = tp["result"]["transactionHash"]
        meta = tp["txApplyProcessing"]
        mv = meta["v%d" % meta["v"]]
        for i, op in enumerate(mv.get("operations") or []):
            for ev in op.get("events") or []:
                body = ev["body"]["v0"]
                if body["topics"] and body["topics"][0].get("sym") == "transfer" and body["data"]["type"] == "SCV_I128":
                    n = (int(body["data"]["i128"]["hi"]) << 64) + int(body["data"]["i128"]["lo"])
                    out.setdefault((h, i + 1), {}).setdefault("transfers", []).append(n)
    for h, (_env, tx, _who) in oracle.envelopes_by_hash(v, "Test SDF Network ; September 2015").items():
        for i, op in enumerate(tx["operations"]):
            if op["body"]["type"] == "PAYMENT":
                out.setdefault((h, i + 1), {})["payment"] = int(op["body"]["paymentOp"]["amount"])
    return out


def rows(path):
    out = []
    for p in sorted(glob.glob(os.path.join(path, "*.gz"))):
        with gzip.open(p, "rt") as f:
            out += [json.loads(x, parse_float=Decimal) for x in f if x.strip()]
    return out


def stroops(x):
    return int(Decimal(str(x)) * 10 ** 7)


def check(exports, exact):
    """[(field, tx, op, exact, exported text, read back)] for every amount above 2^53 stroops."""
    found = []
    tx_of = {}
    for t in rows(os.path.join(exports, "transactions")):
        tx_of[int(t["id"]) >> 12] = t["transaction_hash"]
    for o in rows(os.path.join(exports, "operations")):
        key = (tx_of.get(int(o["id"]) >> 12), int(o["id"]) & 0xFFF)
        want = exact.get(key, {}).get("payment")
        d = o.get("details") or {}
        if want is not None and want > LIMIT and "amount" in d:
            found.append(("operations.details.amount", key, want, str(d["amount"]), stroops(d["amount"])))
    seen = {}
    for t in rows(os.path.join(exports, "token_transfer")):
        if t.get("event_topic") != "transfer" or t.get("operation_id") is None:
            continue
        key = (t["transaction_hash"], int(t["operation_id"]) & 0xFFF)
        n = seen.get(key, 0)
        seen[key] = n + 1
        transfers = exact.get(key, {}).get("transfers") or []
        if n < len(transfers) and transfers[n] > LIMIT:
            found.append(("token_transfer.amount", key, transfers[n], str(t["amount"]), stroops(t["amount"])))
    for e in rows(os.path.join(exports, "effects")):
        d = e.get("details") or {}
        if "amount" not in d:
            continue
        key = (tx_of.get(int(e["operation_id"]) >> 12), int(e["operation_id"]) & 0xFFF)
        candidates = [x for x in [exact.get(key, {}).get("payment")] + (exact.get(key, {}).get("transfers") or [])
                      if x is not None and x > LIMIT]
        if candidates:
            got = stroops(d["amount"])
            want = got if got in candidates else candidates[0]
            found.append(("effects.details.amount", key, want, str(d["amount"]), got))
    return found


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "harness", "replay", "out-stellar-etl"))
    exact = exact_amounts()
    bad, runs = 0, 0
    for exports in sorted(glob.glob(os.path.join(out, "*", "datalake", ENTRY, "exports"))):
        runs += 1
        commit = exports.split(os.sep)[-4]
        status = {}
        for field, key, want, text, got in check(exports, exact):
            lost = want - got
            print("%-26s tx %s op %d: ledger %d stroops, exported %s, reads back %d (%s)" % (
                field, key[0][:10], key[1], want, text, got, "exact" if lost == 0 else "%+d stroops lost" % lost))
            status.setdefault(field, set()).add("exact" if lost == 0 else "stroops lost")
        for field, claim in CLAIMS.items():
            shown = status.get(field)
            got = None if not shown else ("stroops lost" if "stroops lost" in shown else "exact")
            ok = got == claim
            bad += not ok
            print("%-8s %s at %s: %s (claimed %s)" % ("ok" if ok else "DIFFERS", field, commit, got or "no amount above 2^53", claim))
    if not runs:
        print("no recorded run of %s in %s" % (ENTRY, out))
        return 1
    print("AMOUNTS OK" if not bad else "AMOUNTS DIFFER (%d)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
