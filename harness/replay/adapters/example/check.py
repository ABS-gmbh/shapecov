#!/usr/bin/env python3
"""Check the recorded runs of the example adapter (harness/replay/out-example/results.jsonl).

  python3 harness/replay/adapters/example/check.py

On every recorded ledger, the `meta` variant of the toy indexer must pass the oracle's participant
rule, and the `envelope` variant must fail it: these ledgers are chosen because their envelopes name
addresses their meta does not show. Exit 1 otherwise, or if a variant or ledger is missing. No
Docker; rerunning the toy itself needs Docker (README.md in this directory).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "..", "..", "out-example", "results.jsonl")
sys.path.insert(0, HERE)
from adapter import VARIANTS, toy_digest  # noqa: E402

WANT = {"envelope": "fail", "meta": "pass"}


def main():
    variant = {toy_digest(v): v for v in VARIANTS}
    seen, bad = {}, []
    with open(RESULTS) as f:
        for line in f:
            r = json.loads(line)
            v = variant.get(r["commit"])
            if v is None:
                bad.append("%s: commit %s is no variant of the current toy.py; rerun the example" % (r["entry_id"], r["commit"][:12]))
                continue
            got = "pass" if r["result"] == "pass" and r["oracle"]["verdict"] == "pass" else "fail"
            seen.setdefault(r["entry_id"], {})[v] = got
            print("%-40s %-9s %s" % (r["entry_id"], v, got))
            if got != WANT[v]:
                bad.append("%s: the %s variant should %s the participant rule" % (r["entry_id"], v, WANT[v]))
    for entry, vs in sorted(seen.items()):
        for v in VARIANTS:
            if v not in vs:
                bad.append("%s: no recorded run of the %s variant" % (entry, v))
    if not seen:
        bad.append("no recorded runs in %s" % RESULTS)
    for b in bad:
        print("  " + b)
    print("EXAMPLE OK" if not bad else "%d problem(s)" % len(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
