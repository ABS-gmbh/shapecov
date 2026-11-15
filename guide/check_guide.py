#!/usr/bin/env python3
"""Check that the indexer-hardening guide agrees with the corpus.

  python3 guide/check_guide.py            exit 0 if the guide agrees, 1 if not

Checks, all against corpus/patterns.json and corpus/manifest.json:

1. Every corpus pattern the guide names exists.
2. Every corpus pattern is named somewhere in the guide, so no known shape goes undocumented.
3. Every corpus entry ID the guide names exists in the manifest.
4. In every table with the columns "Corpus shape", "CAP" and "Entries":
   - "CAP" lists exactly the CAPs that patterns.json gives the row's patterns ("none" if none);
   - "Entries" gives, for each pattern of the row in order, how many manifest entries carry
     that pattern ("none yet" for zero).

Standard library only.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GUIDE = os.path.join(HERE, "INDEXER-HARDENING.md")

ENTRY_RE = re.compile(r"`((?:testnet|pubnet|golden|synthetic)-[a-z0-9-]+)`")
TICK_RE = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`")
CAP_RE = re.compile(r"CAP-\d{2,4}(?:-\d{2})?")


def norm_cap(c):
    """CAP-27, CAP-0027 -> CAP-0027; CAP-46-11 -> CAP-0046-11."""
    parts = c.split("-")
    parts[1] = parts[1].zfill(4)
    return "-".join(parts)


def tables(text):
    """Yield (header cells, [row cells]) for each markdown table."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|(\s*:?-+:?\s*\|)+\s*$", lines[i + 1]):
            head = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in re.split(r"(?<!\\)\|", lines[i].strip().strip("|"))])
                i += 1
            yield head, rows
        else:
            i += 1


def main():
    with open(os.path.join(REPO, "corpus", "patterns.json")) as f:
        patterns = json.load(f)["patterns"]
    with open(os.path.join(REPO, "corpus", "manifest.json")) as f:
        manifest = json.load(f)
    with open(GUIDE) as f:
        text = f.read()

    entry_ids = {e["id"] for e in manifest["entries"]}
    carriers = {p: [] for p in patterns}
    for e in manifest["entries"]:
        for x in e.get("patterns") or []:
            name = x if isinstance(x, str) else (x.get("pattern") or x.get("name"))
            carriers.setdefault(name, []).append(e["id"])

    errors = []
    named = set()
    for m in TICK_RE.finditer(text):
        tok = m.group(1)
        if tok in patterns:
            named.add(tok)
    # Tokens in "(Corpus: ...)" notes and "Corpus shape" cells must be patterns.
    claimed = set()
    for note in re.findall(r"\(Corpus: ([^)]*)\)", text):
        claimed.update(TICK_RE.findall(note))
    checked_rows = 0
    for head, rows in tables(text):
        if not {"Corpus shape", "CAP", "Entries"} <= set(head):
            continue
        ci, ki, ni = head.index("Corpus shape"), head.index("CAP"), head.index("Entries")
        for r in rows:
            if len(r) != len(head):
                errors.append("table row has %d cells, header has %d: %s" % (len(r), len(head), " | ".join(r)[:120]))
                continue
            pats = TICK_RE.findall(r[ci])
            claimed.update(pats)
            if not pats:
                continue
            checked_rows += 1
            unknown = [p for p in pats if p not in patterns]
            if unknown:
                continue  # reported below
            want_caps = sorted({norm_cap(c) for p in pats for c in patterns[p].get("caps", [])})
            got_caps = sorted({norm_cap(c) for c in CAP_RE.findall(r[ki])})
            if r[ki].strip().lower() in ("none", "—", "-", ""):
                got_caps = []
            if got_caps != want_caps:
                errors.append("row %s: CAP column says %s, patterns.json says %s"
                              % (", ".join(pats), got_caps or "none", want_caps or "none"))
            want_n = ["none yet" if not carriers.get(p) else str(len(carriers[p])) for p in pats]
            got_n = [x.strip() for x in r[ni].split(",")]
            if got_n != want_n:
                errors.append("row %s: Entries column says %r, the manifest has %r"
                              % (", ".join(pats), ", ".join(got_n), ", ".join(want_n)))
    for p in sorted(claimed - set(patterns)):
        errors.append("the guide names corpus pattern `%s`, which corpus/patterns.json does not define" % p)
    for p in sorted(set(patterns) - named):
        errors.append("corpus pattern `%s` is not mentioned anywhere in the guide" % p)
    for eid in sorted(set(ENTRY_RE.findall(text)) - entry_ids):
        errors.append("the guide names corpus entry `%s`, which is not in the manifest" % eid)

    missing = sorted(p for p in patterns if not carriers.get(p))
    print("guide: %d patterns named, %d table rows checked against the manifest" % (len(named), checked_rows))
    if missing:
        print("patterns with no corpus entry yet: %s" % ", ".join(missing))
    for e in errors:
        print("ERROR: " + e)
    print("GUIDE OK" if not errors else "GUIDE DISAGREES WITH THE CORPUS (%d)" % len(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
