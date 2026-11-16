#!/usr/bin/env python3
"""Schema-cell coverage of the corpus and the generator, over the cells a ledger reader can meet.

  cell_coverage.py [--check]        writes corpus/COVERAGE.md and corpus/coverage.json

Definitions:
- A cell is a union arm, or a member of an enum that appears as a value in its own right (a struct
  field, an array element, a typedef, an optional, a union arm's type). A member of an enum used only
  as a union's discriminant is not a separate cell: it is covered exactly when its arm is.
- Reachable: in a type that LedgerCloseMeta reaches through struct fields, union arms and union
  discriminants. The other types (overlay messages, SCP, history archive files, ...) are listed once.

Every reachable cell that no corpus entry has must carry a class and a reason in
corpus/cell-classes.json; --check fails if one is missing, if a classified cell is now covered, or if
the files on disk are out of date.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen import all_cells  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
ROOT_TYPE = "LedgerCloseMeta"


def _refs(t, out):
    if t["r"] == "ref":
        out.append(t["name"])
    elif t["r"] in ("array", "opt"):
        _refs(t["of"], out)


def children(types, name):
    d, out = types[name], []
    if d["k"] == "struct":
        for _, t in d["fields"]:
            _refs(t, out)
    elif d["k"] == "union":
        for a in d["arms"]:
            if a.get("t"):
                _refs(a["t"], out)
        if d.get("default") and d["default"].get("t"):
            _refs(d["default"]["t"], out)
    elif d["k"] == "typedef":
        _refs(d["t"], out)
    return out


def discriminant_only(types):
    """Enums that appear nowhere as a value, only as a union's discriminant (or nowhere at all)."""
    valued = {c for n in types for c in children(types, n) if types.get(c, {}).get("k") == "enum"}
    return {n for n, d in types.items() if d["k"] == "enum" and n not in valued}


def reachable(types, root=ROOT_TYPE):
    seen, stack = set(), [root]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack += children(types, n)
        d = types[n]
        if d["k"] == "union" and d["disc"]["r"] == "ref":
            stack.append(d["disc"]["name"])
    return seen


def type_of(cell):
    return cell.split(":", 1)[1].split(".", 1)[0]


def cells(schema):
    """-> (all cells, reachable cells, reachable types) under the definitions above."""
    types = schema["types"]
    drop = discriminant_only(types)
    every = {c for c in all_cells(schema) if not (c.startswith("enum:") and type_of(c) in drop)}
    reach = reachable(types)
    return every, {c for c in every if type_of(c) in reach}, reach


def defining_file(names):
    """{type: .x file} for the given type names, read from schema/x."""
    out = {}
    for f in sorted((ROOT / "schema" / "x").glob("*.x")):
        text = f.read_text()
        for n in names:
            if n not in out and re.search(r"\b(struct|union|enum|typedef)[^;{]*\b%s\b" % re.escape(n), text):
                out[n] = f.name
    for n in names:  # an anonymous type hoisted out of a parent is named Parent + Field
        if n not in out:
            parent = max((m for m in out if n.startswith(m) and m != n), key=len, default=None)
            if parent:
                out[n] = out[parent]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    schema = json.load(open(ROOT / "schema" / "schema.json"))
    old = all_cells(schema)
    every, reach_cells, reach_types = cells(schema)
    manifest = json.load(open(CORPUS / "manifest.json"))
    corpus = set()
    for e in manifest["entries"]:
        corpus |= set(e.get("cells") or [])
    gen = set(json.load(open(ROOT / "out" / "cases.jsonl.cells.json"))["hit"])
    spec = json.load(open(CORPUS / "cell-classes.json"))
    classes, classified = spec["classes"], spec["cells"]
    uncovered = sorted(reach_cells - corpus)
    errors = []
    for c in uncovered:
        if c not in classified:
            errors.append("%s is reachable, in no corpus entry and has no class in corpus/cell-classes.json" % c)
    for c in sorted(classified):
        if c in corpus:
            errors.append("%s is classified but a corpus entry now has it: remove it from cell-classes.json" % c)
        elif c not in reach_cells:
            errors.append("%s is classified but is not a reachable cell" % c)
        elif classified[c]["class"] not in classes:
            errors.append("%s has an unknown class %r" % (c, classified[c]["class"]))
    by_class = Counter(classified[c]["class"] for c in uncovered if c in classified)
    unreachable = sorted(set(schema["types"]) - reach_types)
    files = defining_file(set(schema["types"]))
    per_file = defaultdict(list)
    for n in unreachable:
        per_file[files.get(n, "?")].append(n)
    unreach_cells = every - reach_cells
    covered = len(reach_cells & corpus)
    data = {
        "note": "Generated by tools/cell_coverage.py. Do not edit by hand.",
        "definition": "a cell is a union arm, or a member of an enum that appears as a value; reachable means in a type LedgerCloseMeta reaches",
        "schema_cells_old_definition": len(old),
        "schema_cells": len(every),
        "discriminant_only_enums": len(discriminant_only(schema["types"])),
        "reachable_types": len(reach_types), "types": len(schema["types"]),
        "reachable_cells": len(reach_cells), "unreachable_cells": len(unreach_cells),
        "corpus_covers_reachable": covered,
        "generator_covers": len(gen & every), "generator_covers_reachable": len(gen & reach_cells),
        "uncovered_reachable": len(uncovered),
        "uncovered_by_class": dict(sorted(by_class.items())),
        "unclassified": [c for c in uncovered if c not in classified or classified[c]["class"] == "unclassified"],
    }
    L = ["# Schema-cell coverage", "",
         "Generated by `tools/cell_coverage.py` from `schema/schema.json`, the manifest and `corpus/cell-classes.json`. "
         "Do not edit by hand.", "",
         "## What a cell is", "",
         "A cell is a union arm, or a member of an enum that appears as a value in its own right. A member of "
         "an enum used only as a union's discriminant is not counted again: it is covered exactly when its arm "
         "is. The schema has %d such enums, which is why it has %d cells, not %d." % (
             data["discriminant_only_enums"], len(every), len(old)), "",
         "Coverage is measured over the cells a ledger reader can meet: those in the %d of %d types that "
         "`LedgerCloseMeta` reaches. %d cells are in types no ledger carries (listed at the end)." % (
             len(reach_types), len(schema["types"]), len(unreach_cells)), "",
         "## Numbers", "",
         "| | Cells | Covered |", "|---|---|---|",
         "| Reachable from `LedgerCloseMeta`, by the corpus | %d | %d (%.1f%%) |" % (
             len(reach_cells), covered, 100.0 * covered / len(reach_cells)),
         "| All cells, by the generator's valid cases (`out/cases.jsonl`) | %d | %d (%.1f%%) |" % (
             len(every), data["generator_covers"], 100.0 * data["generator_covers"] / len(every)),
         "| Reachable cells, by the generator | %d | %d (%.1f%%) |" % (
             len(reach_cells), data["generator_covers_reachable"], 100.0 * data["generator_covers_reachable"] / len(reach_cells)),
         "", "## The %d reachable cells no corpus entry has" % len(uncovered), "",
         "Each is classified from stellar-core `%s` (`src/transactions`: the function that sets each result "
         "code) in `corpus/cell-classes.json`." % spec["stellar_core_commit"][:12], "",
         "| Class | Cells | Meaning |", "|---|---|---|"]
    for k in classes:
        L.append("| `%s` | %d | %s |" % (k, by_class.get(k, 0), classes[k]))
    for k in classes:
        rows = [c for c in uncovered if classified.get(c, {}).get("class") == k]
        if not rows:
            continue
        L += ["", "### `%s` (%d)" % (k, len(rows)), "", "| Cell | Why |", "|---|---|"]
        L += ["| `%s` | %s |" % (c, classified[c]["why"].replace("|", "/")) for c in rows]
    L += ["", "## Types no ledger carries", "",
          "%d types, %d cells, never reached from `LedgerCloseMeta`. Most describe other artifacts: overlay "
          "messages, persisted consensus state, history archive and bucket files, contract spec and metadata "
          "inside Wasm, and preimages that are hashed, never stored. The flag enums (`AccountFlags`, "
          "`TrustLineFlags`, ...) name bits of a `uint32` field; the oracle and the guide treat those as flags, "
          "not as cells." % (len(unreachable), len(unreach_cells)), ""]
    for f in sorted(per_file):
        L.append("- `%s`: %s" % (f, ", ".join("`%s`" % n for n in per_file[f])))
    text = "\n".join(L) + "\n"
    out_md, out_json = CORPUS / "COVERAGE.md", CORPUS / "coverage.json"
    blob = json.dumps(data, indent=1, sort_keys=True) + "\n"
    if a.check:
        if not out_md.exists() or out_md.read_text() != text or not out_json.exists() or out_json.read_text() != blob:
            errors.append("corpus/COVERAGE.md or corpus/coverage.json is out of date: run tools/cell_coverage.py")
    else:
        out_md.write_text(text)
        out_json.write_text(blob)
    for e in errors:
        print("ERROR: " + e)
    print("reachable cells %d, corpus covers %d (%.1f%%); %d uncovered: %s" % (
        len(reach_cells), covered, 100.0 * covered / len(reach_cells), len(uncovered),
        ", ".join("%s %d" % kv for kv in sorted(by_class.items()))))
    print("COVERAGE OK" if not errors else "COVERAGE FAILED")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
