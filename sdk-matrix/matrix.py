#!/usr/bin/env python3
"""Cross-SDK defect matrix: which SDK release has which defect class, from runs, not from memory.

  python3 sdk-matrix/matrix.py

Writes sdk-matrix/MATRIX.md and sdk-matrix/matrix.json. One row per defect class, one column per
decoder. A cell is filled only from a run made by this script, or from a citation that the script
names (a release, a changelog or a merged pull request). Otherwise it says "not tested".

Two kinds of rows:
- XDR codec faults (trailing bytes, non-zero padding, an optional flag other than 0 or 1, a bool
  word other than 0 or 1). Every faulty case of that kind the generator made (out/cases.jsonl) runs
  through each decoder's runner (tools/run.py's runners). The cell says how many of them the decoder
  accepted. stellar-core's column is read from its recorded run (out/core/), for the types its
  print-xdr command can decode.
- SDK behaviour above the codec (issuer order, map key order, colliding map keys, IDs beyond 2^53,
  non-UTF-8 strings). The corpus's pinned-SDK checks (harness/sdk-semantic/) run on every installed
  release. The cell names the first release that passes and any release that still fails.

Needs what CI's conformance job needs: the six runners built (README.md, "Run it"), `npm install`
in harness/sdk-semantic, and Docker for the Go and Java runners.
"""
import base64
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
import run as R  # noqa: E402
from decode import Decoder, get  # noqa: E402
from encode import Encoder  # noqa: E402

SEM = ROOT / "harness" / "sdk-semantic"
PY = str(ROOT / "runners/python/.venv/bin/python")
JS_RELEASES = ["16.3.0", "16.4.1", "17.2.0", "17.2.1", "17.3.0", "17.4.0"]
COLUMNS = ["rust", "js", "python", "python-xdr", "go", "java"]
NAMES = {"rust": "rs-stellar-xdr", "js": "js-stellar-sdk", "python": "py-stellar-base (`stellar_sdk.xdr`)",
         "python-xdr": "py-stellar-xdr (`stellar-xdr`)", "go": "go-stellar-sdk", "java": "java-stellar-sdk"}

CODEC = [
    ("trailing", "Trailing bytes after a value",
     "java-stellar-sdk #833 (14 Nov), fixed on `master` by #842 (16 Nov), not released; go-stellar-sdk #6039 "
     "(13 Nov), fix PR #6041 open"),
    ("pad_nonzero", "Non-zero XDR padding", "py-stellar-base #1262 (14 Nov), fixed in the new `stellar-xdr` package"),
    ("opt_flag_not_01", "Optional flag other than 0 or 1",
     "py-stellar-base #1263 (14 Nov), fixed in the new `stellar-xdr` package"),
    ("bool_not_01", "Bool word other than 0 or 1",
     "rs-stellar-xdr #622 (13 Nov, open); stellar-core #5509 (15 Nov, open). stellar-core itself accepts it"),
]

# Cells this script cannot run, with the source that says what is known. Anything else is "not tested".
CITED = {
    ("pool_pair_accepted", "go"): "not run here; js-stellar-sdk#1766 says the Go SDK had already fixed it",
    ("pool_pair_accepted", "java"): "not run here; fixed on `master` by #832 (5 Nov), listed as pending in "
                                    "the CHANGELOG, after 6.0.0",
}

SEMANTIC = [
    ("pool_pair_accepted", "testnet-5708889", "Liquidity-pool issuers ordered by strkey text, not key bytes",
     "js-stellar-sdk #1766 (30 Sep); py-stellar-base #1246 (4 Nov), fixed by #1247 (5 Nov); "
     "java-stellar-sdk #832 (5 Nov)"),
    ("map_keys_host_order", "testnet-5712621", "Map keys not sorted in the host's order",
     "js-stellar-sdk #1766 (30 Sep)"),
    ("map_entries_preserved", "synthetic-scmap-colliding-keys",
     "Map entries dropped when keys collide (u32 `1` and symbol `\"1\"`)",
     "js-stellar-sdk #1789 (7 Oct)"),
    ("map_entries_preserved:host", "testnet-5712621",
     "Map entries dropped when keys collide (u32 `1` and i64 `1`, a map the host wrote)",
     "js-stellar-sdk #1789 (7 Oct); py-stellar-base #1250 (13 Nov), fixed on `main` by #1252 (16 Nov)"),
    ("ids_exact", "synthetic-ids-beyond-f64", "Offer and muxed IDs beyond 2^53 encode a different ID",
     "js-stellar-sdk #1785 (8 Oct); py-stellar-base #1251 (13 Nov), fixed on `main` by #1253 (14 Nov)"),
    ("string_bytes_kept", "localcore-memo-and-offer-p30-4", "Non-UTF-8 string bytes changed by the string arm's `.value`",
     "js-stellar-sdk #1823 (16 Oct), closed on 20 Oct by documenting the behaviour (#1824), not by a code change"),
]


def codec_rows():
    cases = [json.loads(l) for l in open(ROOT / "out/cases.jsonl")]
    want = {k for k, _, _ in CODEC}
    faulty = [c for c in cases if not c["valid"] and (c.get("fault") or {}).get("kind") in want]
    kind = {c["id"]: c["fault"]["kind"] for c in faulty}
    lines = ["%s\t%s\t%s\n" % (c["id"], c["type"], c["b64"]) for c in faulty]
    acc = {sdk: Counter() for sdk in COLUMNS}
    tot = {sdk: Counter() for sdk in COLUMNS}
    versions = {}
    for sdk in COLUMNS:
        cfg = R.RUNNERS[sdk]
        versions[sdk] = cfg["version"]
        print("running %d faulty cases through %s" % (len(lines), cfg["version"]), flush=True)
        for line in R.run(cfg["cmd"], lines):
            cid, status = line.split("\t", 2)[:2]
            if status == "notype" or cid not in kind:
                continue
            tot[sdk][kind[cid]] += 1
            acc[sdk][kind[cid]] += status == "ok"
    core_kind = {}
    for l in open(ROOT / "out/core/cases.jsonl"):
        x = json.loads(l)
        if not x["valid"]:
            core_kind[x["id"]] = (x.get("fault") or {}).get("kind")
    core_acc, core_tot = Counter(), Counter()
    for l in open(ROOT / "out/core/res.core.tsv"):
        p = l.rstrip("\n").split("\t")
        if core_kind.get(p[0]) in want:
            core_tot[core_kind[p[0]]] += 1
            core_acc[core_kind[p[0]]] += p[1] == "ok"
    rows = []
    for k, title, issues in CODEC:
        cells = {}
        for sdk in COLUMNS:
            n, t = acc[sdk][k], tot[sdk][k]
            cells[sdk] = "not tested" if not t else ("rejects all %d" % t if n == 0 else "**accepts %d of %d**" % (n, t))
        n, t = core_acc[k], core_tot[k]
        core = "rejects all %d" % t if t and n == 0 else ("accepts %d of %d" % (n, t) if t else "not tested")
        rows.append({"class": title, "kind": k, "core": core, "cells": cells, "issues": issues})
    return rows, versions


def semantic_result(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=SEM)
    try:
        return json.loads(p.stdout.strip().split("\n")[-1])["result"]
    except (ValueError, IndexError, KeyError):
        return "error"


def semantic_rows():
    schema = json.load(open(ROOT / "schema/schema.json"))
    dec, enc = Decoder(schema), Encoder(schema)
    manifest = {e["id"]: e for e in json.load(open(ROOT / "corpus/manifest.json"))["entries"]}
    rows = []
    for check, eid, title, issues in SEMANTIC:
        e = manifest[eid]
        entry = str(ROOT / "corpus" / e["file"])
        js, py = {}, None
        if check == "map_entries_preserved:host":
            # The host-written map of the map_keys_host_order check, run through the collision check.
            x = next(s for s in e["expected"]["sdk"] if s["check"] == "map_keys_host_order")
            whole = dec.decode(e["xdr_type"], base64.b64decode(Path(entry).read_text()))
            x = {"path": x["path"], "entries": len(get(whole, x["path"])["map"])}
        else:
            x = next(s for s in e["expected"]["sdk"] if s["check"] == check)
        if check.startswith("map_entries_preserved"):
            tail = [e["xdr_type"], entry, x["path"], str(x["entries"])]
            for v in JS_RELEASES:
                js[v] = semantic_result(["node", str(SEM / "map_entries.mjs"), "sdk-" + v] + tail)
            py = semantic_result([PY, str(SEM / "map_entries.py")] + tail)
        elif check == "ids_exact":
            spec = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
            json.dump(x, spec)
            spec.close()
            for v in JS_RELEASES:
                js[v] = semantic_result(["node", str(SEM / "ids.mjs"), "sdk-" + v, entry, spec.name])
            py = semantic_result([PY, str(SEM / "ids.py"), entry, spec.name])
        else:
            whole = dec.decode(e["xdr_type"], base64.b64decode(Path(entry).read_text()))
            b64 = base64.b64encode(enc.encode(x["xdr_type"], get(whole, x["path"]))).decode()
            extra = [x["pool_id"]] if check == "pool_pair_accepted" else []
            for v in JS_RELEASES:
                js[v] = semantic_result(["node", str(SEM / "order.mjs"), "sdk-" + v, check, x["xdr_type"], b64] + extra)
            if check == "pool_pair_accepted":
                py = semantic_result([PY, str(SEM / "order.py"), check, x["xdr_type"], b64] + extra)
        cells = {sdk: CITED.get((check, sdk), "not tested") for sdk in COLUMNS}
        cells["js"] = js_cell(js)
        if py is not None:
            cells["python"] = "passes in 17.0.1" if py == "pass" else (
                "check could not run" if py == "error" else "**present in 17.0.1**")
        print("%-24s js %s; python %s" % (check, js, py), flush=True)
        rows.append({"class": title, "check": check, "entry": eid, "core": "—", "cells": cells,
                     "js_releases": js, "python_17_0_1": py, "issues": issues})
    return rows


def js_cell(res):
    """One clause per release line: the first release that passes for good, or the latest that fails."""
    parts = []
    for line in ("17", "16"):
        vs = [v for v in JS_RELEASES if v.split(".")[0] == line]
        tested = [v for v in vs if res[v] != "error"]
        if not tested:
            parts.append("%s.x: check could not run (%s)" % (line, ", ".join(vs)))
            continue
        latest = tested[-1]
        errs = [v for v in vs if res[v] == "error"]
        note = " (could not run on %s)" % ", ".join(errs) if errs else ""
        if res[latest] != "pass":
            parts.append("%s.x: **present in %s**%s" % (line, latest, note))
            continue
        first = next(v for v in tested if all(res[w] == "pass" for w in tested[tested.index(v):]))
        if first == tested[0]:
            parts.append("%s.x: passes in %s%s" % (line, ", ".join(tested), note))
        else:
            parts.append("%s.x: fixed in %s%s" % (line, first, note))
    return "; ".join(parts)


def main():
    codec, versions = codec_rows()
    semantic = semantic_rows()
    data = {"versions": versions, "js_releases": JS_RELEASES, "codec": codec, "semantic": semantic}
    (HERE / "matrix.json").write_text(json.dumps(data, indent=1) + "\n")
    (HERE / "MATRIX.md").write_text(render(data))
    print("wrote sdk-matrix/MATRIX.md and sdk-matrix/matrix.json")


def render(d):
    v = {s: re.search(r"v?\d+\.\d+\.\d+", d["versions"][s]).group(0) for s in COLUMNS}
    head = ["Defect class", "stellar-core 30.0.0"] + ["%s %s" % (NAMES[s], v[s]) for s in COLUMNS] + ["Upstream"]
    L = ["# Cross-SDK defect matrix", "",
         "Generated by `sdk-matrix/matrix.py`; do not edit by hand. Each defect class below was found or reported in "
         "one SDK. The matrix shows whether the others have it. A cell comes from a run of this script, or from the "
         "source it names; otherwise it says \"not tested\". **Bold** marks a defect that is present.", "",
         "Codec faults ran on one release of each decoder, named in the table's header. The SDK behaviour checks ran on "
         "every js-stellar-sdk release from %s to %s that the pinned-SDK checks install, and on py-stellar-base 17.0.1."
         % (d["js_releases"][0], d["js_releases"][-1]),
         "",
         "## XDR codec faults", "",
         "Every faulty case of that kind the generator made, run through each decoder. A case whose type a decoder does "
         "not have is not counted, so the totals differ. stellar-core's column comes from "
         "its recorded run, for the types its `print-xdr` command can decode. RFC 4506 says a decoder must reject "
         "each of these; stellar-core rejects all of them except the bool word, which it reads as true.", "",
         "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in d["codec"]:
        L.append("| %s | %s | %s | %s |" % (r["class"], r["core"], " | ".join(r["cells"][s] for s in COLUMNS), r["issues"]))
    L += ["", "## SDK behaviour above the codec", "",
          "The corpus's pinned-SDK checks (`harness/sdk-semantic/`), each on the corpus entry named. These helpers "
          "(asset ordering, `scValToNative` and the like) exist in the JavaScript and Python SDKs; the other "
          "columns are not tested unless a source is named.", "",
          "| " + " | ".join(["Defect class", "Corpus entry"] + [NAMES[s] for s in COLUMNS] + ["Upstream"]) + " |",
          "|" + "---|" * (len(COLUMNS) + 3)]
    for r in d["semantic"]:
        L.append("| %s | `%s` | %s | %s |" % (r["class"], r["entry"], " | ".join(r["cells"][s] for s in COLUMNS),
                                              r["issues"]))
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
