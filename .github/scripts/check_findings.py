#!/usr/bin/env python3
"""RFP check 6: every failure maps to a filed issue.

Reads the committed replay results of both indexers (harness/replay/out*/results.jsonl, written by
the replay workflow) and checks every oracle failure in them. A failure passes when it is labelled
with an upstream issue (adapters/<name>/known.json) or when it is an RFP sighting that
harness/replay/sightings.json claims fails at that pre-fix commit. Anything else is printed and
the script exits 1. Run from the repository root.
"""
import json, re, sys
sightings = json.load(open("harness/replay/sightings.json"))["sightings"]
claimed = {(s["entry"], s["commit"], s.get("adapter", "wallet-backend")): s["issue"] for s in sightings if s["expect"] != "pass"}
issue = re.compile(r"^[\w.-]+/[\w.-]+#\d+")
labelled = unexplained_claimed = 0
bad = []
for out in ("harness/replay/out", "harness/replay/out-stellar-etl"):
    for line in open(out + "/results.jsonl"):
        r = json.loads(line)
        o = r.get("oracle")
        if not o:
            continue
        for label, n in o["known"].items():
            if not issue.match(label):
                bad.append("%s %s: label %r is not an issue reference" % (r["entry_id"], r["commit"][:12], label))
            labelled += n
        if o["unexplained"]:
            key = (r["entry_id"], r["commit"], r["adapter"])
            if key in claimed:
                unexplained_claimed += len(o["unexplained"])
            else:
                bad += ["%s at %s (%s, %s): %s" % (r["entry_id"], r["commit"][:12], r["adapter"], r["input"], u[:160]) for u in o["unexplained"]]
print("oracle failures labelled with a filed issue: %d" % labelled)
print("failures that are a claimed RFP sighting at its pre-fix commit: %d" % unexplained_claimed)
print("failures that map to neither: %d" % len(bad))
for b in bad:
    print("  " + b)
sys.exit(1 if bad else 0)
