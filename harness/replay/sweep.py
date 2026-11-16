#!/usr/bin/env python3
"""Build a sweep corpus: real ledgers the oracle checks without adding them to corpus/.

  sweep.py build --index FILE [--index FILE ...] --cache DIR --out DIR [--min-txs N]

`tools/mine.py scan` indexes ledgers from Stellar's public ledger archive and keeps the files in its
cache. This writes those ledgers as a corpus directory in the same layout as corpus/ (manifest.json,
entries/<id>.LedgerCloseMeta.xdr.b64), with only the fields the replay harness reads. Then:

  replay.py run --corpus DIR --out DIR/out-<adapter> --adapter <adapter> --all-entries ...

replays every ledger and checks it against the oracle. A sweep is large and is not committed;
a ledger that shows something new is added to corpus/ on its own (tools/corpus_add.py).
"""
import argparse
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import mine  # noqa: E402


def build(a):
    os.makedirs(os.path.join(a.out, "entries"), exist_ok=True)
    entries = []
    for path in a.index:
        for line in open(path):
            r = json.loads(line)
            if r.get("error") or r.get("txs", 0) < a.min_txs:
                continue
            raw = mine.fetch(r["net"], r["seq"], a.cache)
            if raw is None:
                continue
            eid = "%s-%d" % (r["net"], r["seq"])
            rel = "entries/%s.LedgerCloseMeta.xdr.b64" % eid
            with open(os.path.join(a.out, rel), "wb") as f:
                f.write(base64.b64encode(raw))
            entries.append({"id": eid, "xdr_type": "LedgerCloseMeta", "file": rel,
                            "protocol_version": r["protocol"], "size_bytes": len(raw), "transactions": r["txs"],
                            "source": {"kind": "network_archive", "network_passphrase": mine.PASSPHRASE[r["net"]],
                                       "ledger_seq": r["seq"]}})
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump({"sweep": True, "entries": entries}, f, indent=1)
    print("sweep corpus: %d ledgers, %d transactions" % (len(entries), sum(e["transactions"] for e in entries)))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="verb", required=True)
    b = sub.add_parser("build")
    b.add_argument("--index", action="append", required=True)
    b.add_argument("--cache", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--min-txs", type=int, default=1)
    a = ap.parse_args()
    build(a)


if __name__ == "__main__":
    main()
