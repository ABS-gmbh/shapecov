#!/usr/bin/env python3
"""Protocol-upgrade drill: what the next protocol's XDR adds, and what stellar-core's next goldens exercise.

  python3 protocol-drill/drill.py --next-xdr DIR [--candidate NAME=DIR ...] --core CHECKOUT [--jobs N]

A worked example of MAINTENANCE.md's upgrade runbook, run before the upgrade instead of after it.

  --next-xdr DIR        the .x files of stellar-xdr's `next` branch (the next protocol's XDR)
  --candidate NAME=DIR  .x files of a pending XDR change to report as well (for example `lcm_v3`)
  --core CHECKOUT       a stellar-core checkout holding test-lcm-current/ and test-lcm-next/

Steps, all with the kit's own tools and no SDK:
1. Build a schema from each XDR tree with tools/xdrschema.py (`#ifdef` blocks are left out, as for
   the kit's own schema).
2. Diff each against the kit's protocol 30 schema (schema/schema.json): types added or removed,
   and cells (union arms and enum members) added or removed. The retrospective diff from
   protocol 28 to 30 (schema/schema-v28.0.json) is included as the size of a real upgrade.
3. Decode every LedgerCloseMeta in stellar-core's test-lcm-next and test-lcm-current golden
   files with tools/decode.py and the protocol 30 schema. Record the protocol versions, any
   ledger that does not decode, and the cells each set exercises.
4. Write protocol-drill/REPORT.md and protocol-drill/drill.json: the new cells and which of them
   the next goldens exercise, and the cells the next goldens exercise that the corpus lacks.
"""
import argparse
import concurrent.futures as cf
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
import xdrschema  # noqa: E402
from decode import Decoder, XdrError  # noqa: E402
from gen import all_cells  # noqa: E402
from mine import golden_records  # noqa: E402

_dec = None


def _init():
    global _dec
    _dec = Decoder(json.load(open(ROOT / "schema/schema.json")))


def _one(path):
    out = {"file": path, "ledgers": 0, "protocols": [], "cells": set(), "errors": []}
    for k, raw in enumerate(golden_records(path)):
        try:
            v = _dec.decode("LedgerCloseMeta", raw)
        except XdrError as e:
            out["errors"].append("%s#%d: %s" % (os.path.basename(path), k, str(e)[:160]))
            continue
        out["ledgers"] += 1
        out["protocols"].append(v["v%d" % v["v"]]["ledgerHeader"]["header"]["ledgerVersion"])
        out["cells"].update(_dec.cells)
    return out


def scan_goldens(tree, jobs):
    files = sorted(str(p) for p in Path(tree).rglob("*.xdr"))
    total = {"files": len(files), "ledgers": 0, "protocols": {}, "cells": set(), "errors": []}
    with cf.ProcessPoolExecutor(jobs, initializer=_init) as ex:
        for r in ex.map(_one, files, chunksize=4):
            total["ledgers"] += r["ledgers"]
            for p in r["protocols"]:
                total["protocols"][p] = total["protocols"].get(p, 0) + 1
            total["cells"] |= r["cells"]
            total["errors"] += r["errors"]
    return total


def diff(old, new):
    ot, nt = set(old["types"]), set(new["types"])
    changed = sorted(t for t in ot & nt if old["types"][t] != new["types"][t])
    oc, nc = all_cells(old), all_cells(new)
    return {"types_added": sorted(nt - ot), "types_removed": sorted(ot - nt), "types_changed": changed,
            "cells_added": sorted(nc - oc), "cells_removed": sorted(oc - nc)}


def git_head(d):
    try:
        return subprocess.run(["git", "-C", d, "log", "-1", "--format=%H %cI %s"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def corpus_cells():
    m = json.load(open(ROOT / "corpus/manifest.json"))
    cells = set()
    for e in m["entries"]:
        cells.update(e.get("cells") or [])
    return cells


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--next-xdr", required=True)
    ap.add_argument("--candidate", action="append", default=[])
    ap.add_argument("--core", required=True)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    a = ap.parse_args()

    curr = json.load(open(ROOT / "schema/schema.json"))
    v28 = json.load(open(ROOT / "schema/schema-v28.0.json"))
    sources = {"next": (a.next_xdr, xdrschema.load(a.next_xdr))}
    for c in a.candidate:
        name, d = c.split("=", 1)
        sources[name] = (d, xdrschema.load(d))
    diffs = {"v28.0 -> v30.0 (retrospective)": diff(v28, curr)}
    for name, (d, schema) in sources.items():
        diffs["v30.0 -> %s" % name] = diff(curr, schema)

    print("decoding test-lcm-next ...", flush=True)
    nxt = scan_goldens(Path(a.core) / "test-lcm-next", a.jobs)
    print("decoding test-lcm-current ...", flush=True)
    cur = scan_goldens(Path(a.core) / "test-lcm-current", a.jobs)
    corpus = corpus_cells()
    new_cells = sorted(set().union(*(d["cells_added"] for k, d in diffs.items() if not k.startswith("v28"))))
    data = {
        "kit_schema": "stellar-xdr v30.0 (schema/SOURCE)",
        "sources": {name: {"git": git_head(d)} for name, (d, _) in sources.items()},
        "stellar_core": git_head(a.core),
        "diffs": diffs,
        "goldens": {
            name: {"files": g["files"], "ledgers": g["ledgers"],
                   "protocols": {str(k): v for k, v in sorted(g["protocols"].items())},
                   "cells": len(g["cells"]), "decode_errors": g["errors"][:20], "decode_error_count": len(g["errors"])}
            for name, g in (("test-lcm-next", nxt), ("test-lcm-current", cur))},
        "new_cells_exercised_by_next_goldens": sorted(set(new_cells) & nxt["cells"]),
        "cells_in_next_goldens_not_in_current_goldens": sorted(nxt["cells"] - cur["cells"]),
        "cells_in_next_goldens_not_in_corpus": sorted(nxt["cells"] - corpus),
        "corpus_cells": len(corpus),
    }
    (HERE / "drill.json").write_text(json.dumps(data, indent=1) + "\n")
    (HERE / "REPORT.md").write_text(report(data))
    print("wrote protocol-drill/REPORT.md and protocol-drill/drill.json")


def report(d):
    L = ["# Protocol-upgrade drill", "",
         "Generated by `protocol-drill/drill.py`; do not edit by hand. A worked example of the upgrade runbook in "
         "`MAINTENANCE.md` (steps 1 to 3 and 6), run before the next protocol ships.", "",
         "## Inputs", "",
         "| Input | Version |", "|---|---|",
         "| The kit's schema | %s |" % d["kit_schema"]]
    for name, s in d["sources"].items():
        L.append("| stellar-xdr `%s` | `%s` |" % (name, s["git"][:100]))
    L.append("| stellar-core golden files | `%s` |" % d["stellar_core"][:100])
    L += ["", "## What each XDR change adds", "",
          "Cells are union arms and enum members: the unit the generator and the corpus count. A type is "
          "\"changed\" when its definition differs.", "",
          "| Diff | Types added | Types changed | Types removed | Cells added | Cells removed |",
          "|---|---|---|---|---|---|"]
    for name, x in d["diffs"].items():
        def lst(v):
            return ", ".join("`%s`" % t for t in v) if v and len(v) <= 8 else (str(len(v)) if v else "none")
        L.append("| %s | %s | %s | %s | %s | %s |" % (name, lst(x["types_added"]), lst(x["types_changed"]),
                                                      lst(x["types_removed"]), lst(x["cells_added"]),
                                                      lst(x["cells_removed"])))
    nxt_name = next((k for k in d["diffs"] if k == "v30.0 -> next"), None)
    nxt = d["diffs"].get(nxt_name, {})
    g = d["goldens"]["test-lcm-next"]
    top = max(g["protocols"], key=int) if g["protocols"] else "?"
    summary = []
    if nxt and not nxt["cells_added"] and not nxt["cells_removed"]:
        summary.append("**The next protocol, as stellar-xdr's `next` branch defines it today, needs no schema change "
                       "for the kit.** It adds %s and no union arm or enum member. All %d ledgers in stellar-core's "
                       "`test-lcm-next` golden files, %d of them at protocol %s, decode with the protocol 30 schema "
                       "(%d do not)." % (", ".join("`%s`" % t for t in nxt["types_added"]) or "no type",
                                         g["ledgers"], g["protocols"].get(top, 0), top, g["decode_error_count"]))
    for name, x in d["diffs"].items():
        if name.startswith("v30.0 -> ") and name != "v30.0 -> next" and x["cells_added"]:
            summary.append("The pending change `%s` adds %s. No golden ledger uses %s yet; when the change "
                           "lands, step 2 of the runbook reports %s as uncovered until a corpus entry carries %s."
                           % (name.split(" -> ")[1], ", ".join("`%s`" % c for c in x["cells_added"]),
                              "it" if len(x["cells_added"]) == 1 else "them",
                              "it" if len(x["cells_added"]) == 1 else "them",
                              "it" if len(x["cells_added"]) == 1 else "them"))
    missing = len(d["cells_in_next_goldens_not_in_corpus"])
    if missing:
        summary.append("%d cells that stellar-core's golden files exercise are not in any corpus entry yet (listed at "
                       "the end). They are the next entries to mine from the goldens (`tools/mine.py goldens`), "
                       "whatever the next protocol brings." % missing)
    else:
        summary.append("Every cell that stellar-core's golden files exercise is carried by at least one corpus entry "
                       "(%d corpus cells)." % d["corpus_cells"])
    L += ["", "## What this means", ""] + ["- " + x for x in summary]
    L += ["", "## What stellar-core's golden files exercise", "",
          "Every LedgerCloseMeta in the golden files was decoded strictly with the kit's protocol 30 schema.", "",
          "| Golden set | Files | Ledgers | Protocol versions (ledgers) | Ledgers that do not decode | Cells |",
          "|---|---|---|---|---|---|"]
    for name, g in d["goldens"].items():
        prot = ", ".join("%s (%d)" % (k, v) for k, v in g["protocols"].items())
        L.append("| `%s` | %d | %d | %s | %d | %d |" % (name, g["files"], g["ledgers"], prot,
                                                       g["decode_error_count"], g["cells"]))
    def cells(v):
        return ", ".join("`%s`" % c for c in v) if v else "none"
    L += ["", "- New cells (any diff above, apart from the retrospective one) that `test-lcm-next` exercises: %s."
          % cells(d["new_cells_exercised_by_next_goldens"]),
          "- Cells `test-lcm-next` exercises and `test-lcm-current` does not: %s."
          % cells(d["cells_in_next_goldens_not_in_current_goldens"]),
          "- Cells `test-lcm-next` exercises and no corpus entry carries (%d corpus cells): %s."
          % (d["corpus_cells"], cells(d["cells_in_next_goldens_not_in_corpus"])), ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
