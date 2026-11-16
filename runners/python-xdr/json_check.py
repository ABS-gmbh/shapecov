#!/usr/bin/env python3
"""SEP-51 XDR-JSON differential check: stellar-xdr (Python) against rs-stellar-xdr 30.0.0.

  json_check.py OUT_DIR PYTHON_EXE

OUT_DIR holds cases.jsonl and res.rust.tsv (tools/run.py). Every valid case that the Rust reference
decodes and re-encodes to the same bytes is checked four ways:

  same_json      Python's to_json_value() equals Rust's serde JSON, compared as parsed JSON
                 (so a number and a string holding that number differ, as SEP-51 says they do)
  py_reads_rust  Python's from_json_value(Rust's JSON) encodes back to the original bytes
  rust_reads_py  Rust's from_json(Python's JSON) encodes back to the original bytes
  py_roundtrip   Python's from_json_value(its own JSON) encodes back to the original bytes

Writes OUT_DIR/json.jsonl (one record per failing case) and prints a summary by check and type.
"""
import collections
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import run as R  # noqa: E402

REF = os.path.join(HERE, "ref-json", "target", "release", "ref-json")
PY_RUNNER = os.path.join(HERE, "run.py")


def results(lines):
    return {l.split("\t", 2)[0]: tuple(l.split("\t", 2)[1:]) for l in lines if l.count("\t") >= 2}


def first_diff(a, b, path="$"):
    if type(a) is not type(b):
        return "%s: %s %r vs %s %r" % (path, type(a).__name__, a, type(b).__name__, b)
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return "%s: key %r only in %s" % (path, k, "python" if k in a else "rust")
            d = first_diff(a[k], b[k], "%s.%s" % (path, k))
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return "%s: %d vs %d items" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, "%s[%d]" % (path, i))
            if d:
                return d
        return None
    return None if a == b else "%s: %r vs %r" % (path, a, b)


def main():
    out, py = sys.argv[1], sys.argv[2]
    cases = {r["id"]: r for r in map(json.loads, open(os.path.join(out, "cases.jsonl")))}
    ref = results(open(os.path.join(out, "res.rust.tsv")).read().splitlines())
    valid = [c for c in cases.values() if c["valid"] and ref.get(c["id"], ("", ""))[0] == "ok"
             and ref[c["id"]][1] == c["b64"]]
    lines = ["%s\t%s\t%s\n" % (c["id"], c["type"], c["b64"]) for c in valid]
    rj = results(R.run([REF, "tojson"], lines, timeout=300))
    pj = results(R.run([py, PY_RUNNER, "tojson"], lines, timeout=300))
    # Cross-reading: each side decodes the other's JSON (and Python its own).
    feed = lambda src: ["%s\t%s\t%s\n" % (c["id"], c["type"], src[c["id"]][1]) for c in valid
                        if src.get(c["id"], ("",))[0] == "ok"]
    py_reads_rust = results(R.run([py, PY_RUNNER, "fromjson"], feed(rj), timeout=300))
    rust_reads_py = results(R.run([REF, "fromjson"], feed(pj), timeout=300))
    py_roundtrip = results(R.run([py, PY_RUNNER, "fromjson"], feed(pj), timeout=300))
    fails, counts = [], collections.Counter()
    for c in valid:
        cid, rec = c["id"], {}
        r, p = rj.get(cid, ("missing", "")), pj.get(cid, ("missing", ""))
        if r[0] != "ok":
            rec["rust_tojson"] = r
        if p[0] != "ok":
            rec["python_tojson"] = p
        if r[0] == "ok" and p[0] == "ok":
            d = first_diff(json.loads(p[1]), json.loads(r[1]))
            if d:
                rec["same_json"] = d
        for name, res in (("py_reads_rust", py_reads_rust), ("rust_reads_py", rust_reads_py),
                          ("py_roundtrip", py_roundtrip)):
            got = res.get(cid)
            if got is not None and got != ("ok", c["b64"]):
                rec[name] = got
        counts["checked"] += 1
        if rec:
            for k in rec:
                counts[k] += 1
            fails.append(dict(rec, id=cid, type=c["type"], input=c["b64"],
                              rust_json=r[1][:600], python_json=p[1][:600]))
    with open(os.path.join(out, "json.jsonl"), "w") as f:
        for x in fails:
            f.write(json.dumps(x) + "\n")
    print(json.dumps(counts))
    by = collections.Counter((k, x["type"]) for x in fails for k in x if k in (
        "same_json", "py_reads_rust", "rust_reads_py", "py_roundtrip", "python_tojson", "rust_tojson"))
    for (k, t), n in by.most_common(40):
        print("%-14s %-36s %d" % (k, t, n))


if __name__ == "__main__":
    main()
