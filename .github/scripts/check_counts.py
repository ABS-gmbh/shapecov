#!/usr/bin/env python3
"""The headline numbers in the documentation agree with the repository.

  python3 .github/scripts/check_counts.py

Each count is computed from the files it describes (the corpus manifest, the generated cases, the
schema, FINDINGS.json, the sightings table, quickcheck.py, the guide's probes, the detection
backtest's claims in harness/replay/backtest.json), and every place a
document states it, found by a pattern, must give the same number. A count that no document states
any more is reported too, so a reworded sentence cannot silently drop out of the check. Dated
documents (STATUS.md, release notes) are not checked: they record what was true on their date.
Exit status 1 on any mismatch. Run from the repository root.
"""
import importlib.util
import json
import os
import re
import sys

WORDS = {w: i for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
                                     "nine", "ten"])}
DOCS = ("README.md", "VERIFY.md", "ARCHITECTURE.md", "FINDINGS.md", "corpus/README.md", "harness/sightings/README.md")


def load(path):
    with open(path) as f:
        return json.load(f)


def linter_findings(target):
    """Findings in the recorded linter report at the commit the accepted list pins."""
    pin = load("linter/accepted/%s.json" % target)["pinned_commit"][:12]
    return len(load("linter/results/%s-%s.json" % (target, pin))["findings"])


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
    valid = faulty = 0
    with open("out/cases.jsonl") as f:
        for line in f:
            if json.loads(line)["valid"]:
                valid += 1
            else:
                faulty += 1
    cases = valid + faulty
    types = load("schema/schema.json")["types"]
    workflows = len([n for n in os.listdir(".github/workflows") if n.endswith((".yml", ".yaml"))])
    cov = load("corpus/coverage.json")
    spec = importlib.util.spec_from_file_location("quickcheck", "quickcheck.py")
    qc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qc)
    probes = load("guide/probes.json")["probes"]
    backtest = {}
    for it in load("harness/replay/backtest.json")["items"]:
        t = backtest.setdefault(it["pipeline"], {"detected": 0, "blind": 0, "in_scope": 0})
        if it["verdict"] in ("detected", "missed"):
            t["in_scope"] += 1
        if it["verdict"] == "detected":
            t["detected"] += 1
            t["blind"] += any(c.get("blind") for c in it["entries"])
    wb, etl = backtest.get("wallet-backend", {}), backtest.get("stellar-etl", {})
    return {
        "corpus entries": len(entries),
        "real ledgers (not synthetic)": sum(1 for e in entries if not e["synthetic"]),
        "stellar-core golden entries": kinds.count("stellar_core_golden"),
        "network ledger entries": kinds.count("network_ledger"),
        "testnet network ledgers": sum(1 for e in entries if e["source"].get("network") == "testnet"),
        "pubnet network ledgers": sum(1 for e in entries if e["source"].get("network") == "pubnet"),
        "local stellar-core entries": kinds.count("local_stellar_core"),
        "generated entries": kinds.count("generated"),
        "findings records": len(findings),
        "findings found and filed by ShapeCov": sum(1 for r in findings if r["kind"] == "found"),
        "RFP sightings": len(rows),
        "RFP sightings reproduced": rows.count("reproduced"),
        "generated cases": cases,
        "valid generated cases": valid,
        "faulty generated cases": faulty,
        "schema union arms": sum(len(t["arms"]) for t in types.values() if t["k"] == "union"),
        "schema enum members": sum(len(t["members"]) for t in types.values() if t["k"] == "enum"),
        "GitHub Actions workflows": workflows,
        "schema types": len(load("schema/schema.json")["types"]),
        "schema cells": cov["schema_cells"],
        "schema cells reached by valid cases": cov["generator_covers"],
        "cells a ledger reader can meet": cov["reachable_cells"],
        "reachable cells in a corpus entry": cov["corpus_covers_reachable"],
        "reachable cells reached by valid cases": cov["generator_covers_reachable"],
        "reachable cells in no corpus entry": cov["uncovered_reachable"],
        "quickcheck checks": len(qc.CHECKS),
        "guide sides that rest on a source citation alone": sum(
            1 for r in load("guide/verdicts.json")["rows"] for side in ("checked", "not_checked")
            if r[side].get("citation_only") and not r[side].get("nothing_claimed")),
        "linter findings on wallet-backend": linter_findings("wallet-backend"),
        "linter findings on stellar-etl": linter_findings("stellar-etl"),
        "quickcheck checks without --full": sum(1 for c in qc.CHECKS if c[0] not in qc.FULL_ONLY),
        "quickcheck time budget, seconds": qc.BUDGET_SECONDS,
        "guide probes (without the setup transaction)": sum(1 for p in probes if p["row"] != "(setup)"),
        "schema cells no valid case reaches": cov["schema_cells"] - cov["generator_covers"],
        "backtest: wallet-backend fixes detected": wb.get("detected", 0),
        "backtest: wallet-backend fixes in scope": wb.get("in_scope", 0),
        "backtest: wallet-backend detections on a blind ledger": wb.get("blind", 0),
        "backtest: stellar-etl issues flagged": etl.get("detected", 0),
        "backtest: stellar-etl issues in scope": etl.get("in_scope", 0),
        "backtest: stellar-etl flags on a blind ledger": etl.get("blind", 0),
    }


# fact -> patterns; each pattern's first group is the number as written (commas allowed).
PATTERNS = {
    "corpus entries": [r"\bcorpus of ([\d,]+) entries", r"\bholds ([\d,]+) entries", r"Corpus: ([\d,]+) entries",
                       r"(?m)^([\d,]+) entries, each", r"\bfor all ([\d,]+) entries"],
    "real ledgers (not synthetic)": [r"\b([\d,]+) (?:of them )?real ledgers"],
    "stellar-core golden entries": [r"\b([\d,]+) corpus entries are stellar-core's golden",
                                    r"\| ([\d,]+) \| `stellar_core_golden` \|",
                                    r"\bthe ([\d,]+) corpus entries copied from stellar-core"],
    "network ledger entries": [r"\| ([\d,]+) \| `network_ledger` \|", r"\bthe ([\d,]+) ledgers from Stellar's public"],
    "testnet network ledgers": [r"\btestnet \(([\d,]+)\) and pubnet"],
    "pubnet network ledgers": [r"\band pubnet \(([\d,]+)\)"],
    "local stellar-core entries": [r"\| ([\d,]+) \| `local_stellar_core` \|"],
    "generated entries": [r"\| ([\d,]+) \| `generated` \|"],
    "findings records": [r"\b(?:All )?([\d,]+) findings(?: in `FINDINGS\.json`|, with severity)",
                         r"`FINDINGS\.json`: ([\d,]+) findings"],
    "findings found and filed by ShapeCov": [r"\b([\d,]+) defects found and filed"],
    "RFP sightings": [r"\b(?:of|of the RFP's) ([\d,]+) (?:public )?sightings", r"\b[\d,]+ of ([\d,]+) reproduced"],
    "RFP sightings reproduced": [r"\b([\d,]+) of the RFP's [\d,]+ sightings", r"\b([\d,]+) of [\d,]+ reproduced"],
    "generated cases": [r"\b([\d,]+) (?:generated )?cases across"],
    "valid generated cases": [r"\baccepts all ([\d,]+) valid generated cases"],
    "faulty generated cases": [r"\brejects all ([\d,]+)\s+faulty ones"],
    "schema union arms": [r"\b([\d,]+) union arms\b"],
    "schema enum members": [r"\b([\d,]+) enum members\b"],
    "GitHub Actions workflows": [r"(?i)\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+) GitHub Actions workflows"],
    "schema types": [r"\b([\d,]+) types\b"],
    "schema cells": [r"\b[\d,]+ of (?:the )?([\d,]+) schema cells"],
    "cells a ledger reader can meet": [r"\b[\d,]+ of the ([\d,]+) (?:reachable cells|cells a ledger reader can meet|a ledger reader)"],
    "reachable cells in a corpus entry": [r"\b([\d,]+) of the [\d,]+ (?:reachable cells|cells a ledger reader can meet)"],
    "reachable cells reached by valid cases": [r"\band ([\d,]+) of the [\d,]+ a ledger reader can"],
    "reachable cells in no corpus entry": [r"\bEach of the other ([\d,]+) is classified"],
    "schema cells no valid case reaches": [r"\bof the ([\d,]+) schema cells no valid case"],
    "backtest: wallet-backend fixes detected": [r"\bdetects ([\d,]+) of wallet-backend's [\d,]+ in-scope fixes"],
    "backtest: wallet-backend fixes in scope": [r"\bof wallet-backend's ([\d,]+) in-scope fixes"],
    "backtest: wallet-backend detections on a blind ledger": [r"\bin-scope fixes \(([\d,]+) on ledgers not chosen"],
    "backtest: stellar-etl issues flagged": [r"\bflags ([\d,]+) of stellar-etl's [\d,]+ in-scope issues"],
    "backtest: stellar-etl issues in scope": [r"\bof stellar-etl's ([\d,]+) in-scope issues"],
    "backtest: stellar-etl flags on a blind ledger": [r"\bstellar-etl's [\d,]+ in-scope issues \(([\d,]+) blind\)"],
    "schema cells reached by valid cases": [r"\breach(?:es)? ([\d,]+) of (?:the )?[\d,]+ schema cells",
                                            r"\bexercise ([\d,]+) of [\d,]+ schema cells"],
    "guide sides that rest on a source citation alone": [r"\bthe\s+([\d,]+) statements that rest on a source citation alone"],
    "linter findings on wallet-backend": [r"\bPartly met: ([\d,]+) findings on wallet-backend",
                                          r"\bwallet-backend `main` \(([\d,]+) findings",
                                          r"\bOn wallet-backend the linter reports ([\d,]+) findings"],
    "linter findings on stellar-etl": [r"\bor on stellar-etl\s+\(([\d,]+), all real",
                                       r"\.json\)\): ([\d,]+) findings, all real"],
    "quickcheck checks": [r"--full` adds the unit tests and the mutation testing[,:] ([\d,]+) checks"],
    "quickcheck checks without --full": [r"\bthe ([\d,]+) fast checks"],
    "quickcheck time budget, seconds": [r"## Check it in under ([\d,]+) seconds"],
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
                    word = m.group(1).lower()
                    n = WORDS[word] if word in WORDS else int(word.replace(",", ""))
                    line = text.count("\n", 0, m.start()) + 1
                    stated[fact] += 1
                    if n != facts[fact]:
                        bad.append("%s:%d: %r says %d, but %s is %d" % (doc, line, m.group(0), n, fact, facts[fact]))
    for fact, value in facts.items():
        print("%-56s %6d   stated %d time(s)" % (fact, value, stated[fact]))
        if not stated[fact]:
            bad.append("%s (%d) is no longer stated in any of %s; update the pattern or drop the fact"
                       % (fact, value, ", ".join(DOCS)))
    # The measured time of the default quick check must stay within the budget the heading states.
    for doc, text in texts.items():
        for m in re.finditer(r"fast checks[^.]*?\*{0,2}([\d,]+) seconds", text):
            if int(m.group(1)) > facts["quickcheck time budget, seconds"]:
                bad.append("%s:%d: %r is over the quick check's budget of %d s (quickcheck.py BUDGET_SECONDS)"
                           % (doc, text.count("\n", 0, m.start()) + 1, m.group(0),
                              facts["quickcheck time budget, seconds"]))
    print("mismatches: %d" % len(bad))
    for b in bad:
        print("  " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
