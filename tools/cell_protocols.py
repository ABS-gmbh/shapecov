#!/usr/bin/env python3
"""Date every schema cell to the stellar-xdr release that introduced it, and check the hand-assigned
CAP tags against those dates.

  cell_protocols.py [--cache DIR]      writes corpus/cell-protocols.json (needs `gh` to fetch the tags)

For every tag of stellar/stellar-xdr from v19 to v30.0, the .x files are parsed with
tools/xdrschema.py (the same parser that builds schema/schema.json) and the union arms and enum
members listed. Each cell of the current schema gets the first tag that has it. stellar-xdr has no
v29 tag, so a cell first seen in v30.0 was added in protocol 29 or 30; a cell already in v19 was
added in protocol 19 or earlier.

Then every cell that corpus/cap-map.json attributes to a CAP is compared with the protocol that CAP
shipped in (corpus/cap-coverage.json). A disagreement is reported, not corrected.
"""
import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import xdrschema  # noqa: E402
from gen import all_cells  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TAGS = ["v19", "v20", "v20.1", "v21.0", "v21.1", "v22.0", "v23.0", "v24.0", "v25.0", "v26.0", "v27.0", "v28.0", "v30.0"]


def protocol_of(tag):
    major = int(re.match(r"v(\d+)", tag).group(1))
    return {"v19": "19 or earlier", "v30.0": "29 or 30"}.get(tag, str(major))


def fetch(tag, cache):
    d = cache / tag
    if not d.exists():
        raw = subprocess.run(["gh", "api", "repos/stellar/stellar-xdr/tarball/" + tag], capture_output=True, check=True).stdout
        d.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(raw)) as t:
            for m in t.getmembers():
                name = m.name.split("/", 1)[-1]
                if m.isfile() and name.endswith(".x") and "/" not in name:  # the release's own .x files, at the top
                    (d / name).write_bytes(t.extractfile(m).read())
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(Path.home() / ".cache" / "shapecov" / "stellar-xdr-tags"))
    a = ap.parse_args()
    cache = Path(a.cache)
    current = all_cells(json.load(open(ROOT / "schema" / "schema.json")))
    first, per_tag = {}, {}
    for tag in TAGS:
        cells = all_cells(xdrschema.load(fetch(tag, cache)))
        per_tag[tag] = len(cells)
        for c in cells:
            first.setdefault(c, tag)
    undated = sorted(current - set(first))
    capmap = json.load(open(ROOT / "corpus" / "cap-map.json"))["cells"]
    caps = {c["cap"]: c["protocol"] for c in json.load(open(ROOT / "corpus" / "cap-coverage.json"))["caps"]}
    checks = []
    for cell, cap in sorted(capmap.items()):
        cap = cap if isinstance(cap, str) else cap[0]
        tag = first.get(cell)
        shipped = caps.get(cap, "?")
        dated = protocol_of(tag) if tag else "not in any tag"
        if tag is None:
            ok = False
        elif tag == "v19":
            ok = shipped == "-" or all(int(p) <= 19 for p in re.findall(r"\d+", shipped))
        elif tag == "v30.0":
            ok = any(p in ("29", "30") for p in re.findall(r"\d+", shipped))
        else:
            ok = dated in re.findall(r"\d+", shipped) or (shipped == "-")
        checks.append({"cell": cell, "cap": cap, "cap_protocol": shipped, "first_tag": tag, "dated_protocol": dated, "agrees": ok})
    out = {"note": "First stellar/stellar-xdr tag that has each cell of schema/schema.json; see tools/cell_protocols.py.",
           "tags": per_tag, "first_tag": {c: first[c] for c in sorted(current) if c in first},
           "undated": undated, "cap_tag_checks": checks}
    (ROOT / "corpus" / "cell-protocols.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    bad = [c for c in checks if not c["agrees"]]
    print("dated %d of %d cells; %d CAP-tagged cells checked, %d disagree" % (
        len(current) - len(undated), len(current), len(checks), len(bad)))
    for c in bad:
        print("  DISAGREES %s: tagged %s (protocol %s), first in %s" % (c["cell"], c["cap"], c["cap_protocol"], c["first_tag"]))


if __name__ == "__main__":
    main()
