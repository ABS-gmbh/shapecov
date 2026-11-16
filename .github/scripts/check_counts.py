#!/usr/bin/env python3
"""The headline numbers in the documentation agree with the repository.

  python3 .github/scripts/check_counts.py

Each count is computed from the files it describes (the corpus manifest, the generated cases, the
schema, FINDINGS.json, the sightings table, quickcheck.py, the guide's probes), and every place a
document states it, found by a pattern, must give the same number. A count that no document states
any more is reported too, so a reworded sentence cannot silently drop out of the check. Dated
documents (STATUS.md, release notes) are not checked: they record what was true on their date.
Exit status 1 on any mismatch. Run from the repository root.
"""
import importlib.util
import json
import re
import sys

DOCS = ("README.md", "VERIFY.md", "ARCHITECTURE.md", "corpus/README.md", "harness/sightings/README.md")


def load(path):
    with open(path) as f:
        return json.load(f)


def counts():
    entries = load("corpus/manifest.json")["entries"]
    kinds = [e["source"]["kind"] for e in entries]
    findings = load("FINDINGS.json")["findings"]
    rows = []
    with open("harness/sightings/README.md") as f:
        for line in f:
            cells = [c.strip() for c in line.split("|")]
            if len(cells) > 4 and cells[1].isdigit():
                rows.append(cells[3])
    with open("out/cases.jsonl") as f:
        cases = sum(1 for _ in f)
    cells = load("out/cases.jsonl.cells.json")
    spec = importlib.util.spec_from_file_location("quickcheck", "quickcheck.py")
    qc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qc)
    probes = load("guide/probes.json")["probes"]
    total_cells, hit_cells = len(cells["total"]), len(cells["hit"])
    corpus_cells = set().union(*(e["cells"] for e in entries))
    return {
        "corpus entries": len(entries),
        "real ledgers (not synthetic)": sum(1 for e in entries if not e["synthetic"]),
        "stellar-core golden entries": kinds.count("stellar_core_golden"),
        "findings records": len(findings),
        "findings found and filed by ShapeCov": sum(1 for r in findings if r["kind"] == "found"),
        "RFP sightings": len(rows),
        "RFP sightings reproduced": rows.count("reproduced"),
        "generated cases": cases,
        "schema types": len(load("schema/schema.json")["types"]),
        "schema cells": total_cells,
        "schema cells reached by valid cases": hit_cells,
        "quickcheck checks": len(qc.CHECKS),
        "guide probes (without the setup transaction)": sum(1 for p in probes if p["row"] != "(setup)"),
        "schema cells no valid case reaches": total_cells - hit_cells,
        "schema cells in no corpus entry": total_cells - len(corpus_cells & set(load("corpus/cell-protocols.json")["first_tag"])),
    }


# fact -> patterns; each pattern's first group is the number as written (commas allowed).
PATTERNS = {
    "corpus entries": [r"\bcorpus of ([\d,]+) entries", r"\bholds ([\d,]+) entries", r"Corpus: ([\d,]+) entries",
                       r"(?m)^([\d,]+) entries, each", r"\bfor all ([\d,]+) entries"],
    "real ledgers (not synthetic)": [r"\b([\d,]+) (?:of them )?real ledgers"],
    "stellar-core golden entries": [r"\b([\d,]+) corpus entries are stellar-core's golden"],
    "findings records": [r"\b(?:All )?([\d,]+) findings(?: in `FINDINGS\.json`|, with severity)",
                         r"`FINDINGS\.json`: ([\d,]+) findings"],
    "findings found and filed by ShapeCov": [r"\b([\d,]+) defects found and filed"],
    "RFP sightings": [r"\b(?:of|of the RFP's) ([\d,]+) (?:public )?sightings", r"\b[\d,]+ of ([\d,]+) reproduced"],
    "RFP sightings reproduced": [r"\b([\d,]+) of the RFP's [\d,]+ sightings", r"\b([\d,]+) of [\d,]+ reproduced"],
    "generated cases": [r"\b([\d,]+) (?:generated )?cases across"],
    "schema types": [r"\b([\d,]+) types\b"],
    "schema cells": [r"\b[\d,]+ of (?:the )?([\d,]+) schema cells"],
    "schema cells no valid case reaches": [r"\bof the ([\d,]+) schema cells no valid case"],
    "schema cells in no corpus entry": [r"\b([\d,]+) of the [\d,]+ schema cells appear in no corpus entry"],
    "schema cells reached by valid cases": [r"\breach(?:es)? ([\d,]+) of [\d,]+ schema cells",
                                            r"\bexercise ([\d,]+) of [\d,]+ schema cells"],
    "quickcheck checks": [r"\bfor all ([\d,]+) checks", r"\breruns the ([\d,]+) checks"],
    "guide probes (without the setup transaction)": [r"\b([\d,]+) probes, plus one setup"],
}


def main():
    facts = counts()
    texts = {}
    for d in DOCS:
        with open(d) as f:
            texts[d] = f.read()
    bad, stated = [], {k: 0 for k in facts}
    for fact, pats in PATTERNS.items():
        for pat in pats:
            for doc, text in texts.items():
                for m in re.finditer(pat, text):
                    n = int(m.group(1).replace(",", ""))
                    line = text.count("\n", 0, m.start()) + 1
                    stated[fact] += 1
                    if n != facts[fact]:
                        bad.append("%s:%d: %r says %d, but %s is %d" % (doc, line, m.group(0), n, fact, facts[fact]))
    for fact, value in facts.items():
        print("%-46s %6d   stated %d time(s)" % (fact, value, stated[fact]))
        if not stated[fact]:
            bad.append("%s (%d) is no longer stated in any of %s; update the pattern or drop the fact"
                       % (fact, value, ", ".join(DOCS)))
    print("mismatches: %d" % len(bad))
    for b in bad:
        print("  " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
