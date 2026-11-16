#!/usr/bin/env python3
"""A toy indexer, to show the adapter interface and the RFP's second rule. Standard library only.

  toy.py --variant envelope|meta --rpc URL --seq N --passphrase P --db FILE

It reads one ledger from a stellar-rpc `getLedgers` endpoint, decodes it with the kit's own decoder
(tools/decode.py), and stores each transaction's participants, and each operation's, in SQLite.

- `envelope`: participants are every address the transaction's envelope names: its source and
  fee-bump source, and each operation's source, destinations, trustors, claimants and authorization
  entries. A failed transaction's payment destination becomes a participant, though nothing
  happened to it.
- `meta`: participants are the source and fee-bump source (they signed), plus the owner of every
  account, trustline, offer or data entry the transaction changed. A failed transaction changed
  only its fee and sequence number, so it has only its signers.
"""
import argparse
import base64
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "tools"))
import oracle  # noqa: E402  (the kit's decoder output helpers; no indexer logic)
from decode import Decoder  # noqa: E402

OWNER = {"ACCOUNT": ("account", "accountID"), "TRUSTLINE": ("trustLine", "accountID"),
         "OFFER": ("offer", "sellerID"), "DATA": ("data", "accountID")}


def addresses(x):
    found = set()
    oracle._addresses(x, found)
    return found


def owners(changes):
    """Accounts whose account, trustline, offer or data entry a list of ledger entry changes touches."""
    out = set()
    for ch in changes or []:
        t = ch["type"]
        if t == "LEDGER_ENTRY_REMOVED":
            data = ch["removed"]
        else:
            data = ch[t.split("_")[-1].lower()]["data"]
        arm = OWNER.get(data["type"])
        if arm:
            out.add(oracle.account_of(data[arm[0]][arm[1]]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["envelope", "meta"], required=True)
    for a in ("--rpc", "--seq", "--passphrase", "--db"):
        ap.add_argument(a, required=True)
    a = ap.parse_args()
    req = {"jsonrpc": "2.0", "id": 1, "method": "getLedgers",
           "params": {"startLedger": int(a.seq), "pagination": {"limit": 1}}}
    resp = json.load(urllib.request.urlopen(urllib.request.Request(
        a.rpc, json.dumps(req).encode(), {"Content-Type": "application/json"}), timeout=60))
    raw = base64.b64decode(resp["result"]["ledgers"][0]["metadataXdr"])
    value = Decoder(json.load(open(REPO / "schema/schema.json"))).decode("LedgerCloseMeta", raw)
    envelopes = oracle.envelopes_by_hash(value, a.passphrase)

    db = sqlite3.connect(a.db)
    db.execute("CREATE TABLE transactions (hash TEXT, tx_order INT, success INT, participants TEXT)")
    db.execute("CREATE TABLE operations (tx_hash TEXT, tx_order INT, op_order INT, participants TEXT)")
    body = value["v%d" % value["v"]]
    for i, tp in enumerate(body["txProcessing"], 1):
        h = tp["result"]["transactionHash"]
        ok = tp["result"]["result"]["result"]["code"] in oracle.SUCCESS
        _, tx, signers = envelopes[h]
        meta = tp["txApplyProcessing"]
        mv = meta.get("v%d" % meta["v"], meta)
        ops = []
        for k, op in enumerate(tx["operations"]):
            if a.variant == "envelope":
                ops.append(addresses(op))
            else:
                applied = (mv.get("operations") or [])[k]["changes"] if ok and mv.get("operations") else []
                ops.append(owners(applied))
        tx_parts = addresses(signers) | set().union(*ops)
        if a.variant == "meta":
            for key in ("txChanges", "txChangesBefore", "txChangesAfter"):
                tx_parts |= owners(mv.get(key))
            tx_parts |= owners(tp.get("feeProcessing")) | owners(tp.get("postTxApplyFeeProcessing"))
        db.execute("INSERT INTO transactions VALUES (?, ?, ?, ?)", (h, i, ok, json.dumps(sorted(tx_parts))))
        for k, parts in enumerate(ops, 1):
            db.execute("INSERT INTO operations VALUES (?, ?, ?, ?)", (h, i, k, json.dumps(sorted(parts))))
    db.commit()
    print("stored %d transactions" % len(body["txProcessing"]))


if __name__ == "__main__":
    main()
