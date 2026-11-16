#!/usr/bin/env python3
"""Compare a fresh Horizon replay with the recorded one, entry by entry.

  python3 harness/replay/adapters/horizon/compare.py FRESH_OUT [RECORDED_OUT]

For every result in FRESH_OUT/results.jsonl, the recorded result for the same entry, commit and
input must have the same indexer result, the same oracle verdict, the same known-issue counts and
the same number of unexplained failures. Exit 1 on any difference or a missing recorded result.
Used by the replay workflow's Horizon job, which reruns a few ledgers; the full set is the recorded
evidence (harness/replay/out-horizon), checked by the quick check.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(out):
    with open(os.path.join(out, "results.jsonl")) as f:
        rows = [json.loads(x) for x in f if x.strip()]
    return {(r["entry_id"], r["commit"], r["input"]): r for r in rows}


def summary(r):
    o = r.get("oracle") or {}
    return {"result": r["result"], "verdict": o.get("verdict"), "known": o.get("known") or {},
            "unexplained": len(o.get("unexplained") or [])}


def main():
    fresh = load(sys.argv[1])
    recorded = load(sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "..", "out-horizon"))
    bad = 0
    for k, r in sorted(fresh.items()):
        got, want = summary(r), summary(recorded[k]) if k in recorded else None
        ok = got == want
        bad += not ok
        print("%-8s %s at %s, %s: %s%s" % ("same" if ok else "DIFFERS", k[0], k[1][:12], k[2], json.dumps(got),
                                          "" if ok else "; recorded " + json.dumps(want)))
    print("HORIZON SAME AS RECORDED" if not bad and fresh else "HORIZON DIFFERS (%d)" % bad)
    return 1 if bad or not fresh else 0


if __name__ == "__main__":
    sys.exit(main())
