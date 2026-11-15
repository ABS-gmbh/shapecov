"""Select ledgers from mining indexes and add them to the corpus.

  corpus_add.py --goldens-index F --goldens-checkout DIR \\
                --network-index F [--network-index F ...] --cache DIR [--min-cells N] [--dry-run]
  corpus_add.py --local-run DIR [--local-run DIR ...] [--dry-run]

--local-run adds the scenario ledgers of a tools/localcore.py run (every `ledger_<scenario>` key in
its run.json). Each is designated for the patterns and cells it brings that no entry has yet.

Selection, in this order (see tools/mine.py for how the indexes are made):
  1. stellar-core goldens: the fewest ledgers that cover every named pattern found in the goldens,
     then ledgers that add at least --min-cells schema cells not covered yet;
  2. each network index (testnet, pubnet): the fewest ledgers that cover every named pattern found
     on that network, then ledgers that add at least --min-cells cells nothing chosen so far covers.
Ties go to the smaller ledger. A pattern gets exactly one designated entry per source.

For every chosen ledger this writes the entry file and a manifest record whose derived fields
(hash, protocol, cells, patterns with their paths, CAP tags, expected decoded values) all come from
the bytes via the independent decoder. Existing entries are never rewritten.
"""
import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mine  # noqa: E402
from decode import Decoder, get  # noqa: E402
from gen import all_cells  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
GOLDEN_PASSPHRASE = "(V) (;,,;) (V)"
MAX_EXPECTED = 40


def cover(rows, covered_patterns, covered_cells, min_cells, patterns_only_from=None):
    """Greedy: all patterns first (fewest, then smallest ledgers), then cells."""
    chosen = []
    want = {p for r in rows for p in r["patterns"]} - covered_patterns
    while want:
        best = max(rows, key=lambda r: (len(set(r["patterns"]) & want), -r["size"]))
        got = set(best["patterns"]) & want
        if not got:
            break
        chosen.append((best, sorted(got), sorted(set(best["cells"]) - covered_cells)))
        want -= got
        covered_patterns |= got
        covered_cells |= set(best["cells"])
    while True:
        best = max(rows, key=lambda r: (len(set(r["cells"]) - covered_cells), -r["size"]))
        gain = set(best["cells"]) - covered_cells
        if len(gain) < min_cells:
            break
        chosen.append((best, [], sorted(gain)))
        covered_cells |= gain
    return chosen


def expected_for(dec, value, designated_patterns, designated_cells, pattern_paths, types):
    ver = f"v{value['v']}"
    hdr = f"{ver}.ledgerHeader"
    out = [{"path": "v", "value": value["v"]},
           {"path": f"{hdr}.header.ledgerSeq", "value": get(value, f"{hdr}.header.ledgerSeq")},
           {"path": f"{hdr}.header.ledgerVersion", "value": get(value, f"{hdr}.header.ledgerVersion")},
           {"path": f"{hdr}.hash", "value": get(value, f"{hdr}.hash")},
           {"path": f"{hdr}.header.scpValue.closeTime", "value": get(value, f"{hdr}.header.scpValue.closeTime")}]
    seen = {x["path"] for x in out}

    def add(path, note):
        v = get(value, path)
        if isinstance(v, dict):
            for disc in ("type", "v", "code"):
                if disc in v and not isinstance(v[disc], (dict, list)):
                    path, v = f"{path}.{disc}", v[disc]
                    break
            else:
                return
        elif isinstance(v, list):
            return
        if path not in seen and len(out) < MAX_EXPECTED:
            seen.add(path)
            out.append({"path": path, "value": v, "note": note})

    for p in designated_patterns:
        add(pattern_paths[p], f"pattern {p}")
    for c in designated_cells:
        path = dec.cells[c]
        kind, rest = c.split(":", 1)
        tname = rest.split(".", 1)[0]
        if kind == "arm":
            add(f"{path}.{types[tname]['discName']}" if path else types[tname]["discName"], f"cell {c}")
        else:
            add(path, f"cell {c}")
    return out


def caps_for(designated_patterns, designated_cells, catalog, capmap):
    by_cap = {}
    for p in designated_patterns:
        for cap in catalog[p]["caps"]:
            by_cap.setdefault(cap, {"cap": cap, "cells": [], "patterns": []})["patterns"].append(p)
    for c in designated_cells:
        if c in capmap:
            by_cap.setdefault(capmap[c], {"cap": capmap[c], "cells": [], "patterns": []})["cells"].append(c)
    return [by_cap[k] for k in sorted(by_cap)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goldens-index"); ap.add_argument("--goldens-checkout")
    ap.add_argument("--network-index", action="append", default=[])
    ap.add_argument("--cache", default="lake-cache")
    ap.add_argument("--min-cells", type=int, default=3)
    ap.add_argument("--local-run", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    schema = json.load(open(ROOT / "schema/schema.json"))
    types = schema["types"]
    new_cells = all_cells(schema) - all_cells(json.load(open(ROOT / "schema/schema-v28.0.json")))
    catalog = json.load(open(CORPUS / "patterns.json"))["patterns"]
    capmap = json.load(open(CORPUS / "cap-map.json"))["cells"]
    manifest = json.load(open(CORPUS / "manifest.json"))
    have = {e["id"] for e in manifest["entries"]}
    dec = Decoder(schema)

    covered_cells = {c for e in manifest["entries"] for c in e["cells"]}
    plan = []
    if a.goldens_index:
        rows = [json.loads(l) for l in open(a.goldens_index)]
        for r, pats, cells in cover(rows, set(), covered_cells, a.min_cells):
            plan.append(("golden", r, pats, cells))
    for f in a.network_index:
        rows = [r for r in map(json.loads, open(f)) if "error" not in r]
        for r, pats, cells in cover(rows, set(), covered_cells, a.min_cells):
            plan.append(("network", r, pats, cells))

    have_patterns = {p for e in manifest["entries"] for p in (e.get("patterns") or {})}
    for d in a.local_run:
        run = json.load(open(Path(d) / "run.json"))
        for key, seq in sorted(run.items()):
            if not key.startswith("ledger_") or not isinstance(seq, int):
                continue
            raw = (Path(d) / "ledgers" / f"{seq}.xdr").read_bytes()
            found = mine.patterns(dec.decode("LedgerCloseMeta", raw))
            fresh = sorted(set(dec.cells) - covered_cells)
            r = {"raw": raw, "run": run, "seq": seq, "scenario": key[len("ledger_"):].replace("_", "-")}
            plan.append(("local", r, sorted(set(found) - have_patterns), fresh))
            have_patterns |= set(found)
            covered_cells |= set(fresh)

    core_commit = None
    if a.goldens_checkout:
        core_commit = subprocess.run(["git", "-C", a.goldens_checkout, "rev-parse", "HEAD"],
                                     capture_output=True, text=True).stdout.strip()
    added = 0
    for kind, r, pats, cells in plan:
        if kind == "golden":
            rel, k = r["seq"].rsplit("#", 1)
            raw = mine.golden_records(Path(a.goldens_checkout) / rel)[int(k)]
            test_file, h = Path(rel).parent.name, Path(rel).stem
            index = json.load(open(Path(a.goldens_checkout) / Path(rel).parent / "index.json"))
            test_name = index.get(h, "")
            eid = f"golden-{re.sub('tests$', '', test_file.lower())}-{h[:8]}-{k}"
            fname = f"entries/{eid}.LedgerCloseMeta.xdr.b64"
            source = {"kind": "stellar_core_golden", "stellar_core_commit": core_commit, "golden_file": rel,
                      "record": int(k), "test": test_name, "network_passphrase": GOLDEN_PASSPHRASE}
        elif kind == "local":
            raw = r["raw"]
            eid = f"localcore-{r['scenario']}-{r['seq']}"
            fname = f"entries/{eid}.LedgerCloseMeta.xdr.b64"
            source = None
        else:
            raw = mine.fetch(r["net"], r["seq"], a.cache)
            eid = f"{r['net']}-{r['seq']}"
            fname = f"entries/{eid}.LedgerCloseMeta.xdr.b64"
            source = None
        if eid in have:
            continue
        value = dec.decode("LedgerCloseMeta", raw)
        ppaths = mine.patterns(value, with_paths=True)
        hdr = value[f"v{value['v']}"]["ledgerHeader"]
        if source is None and kind == "local":
            source = {"kind": "local_stellar_core", "stellar_core_version": r["run"]["stellar_core_version"],
                      "image": r["run"]["stellar_core_image"], "network_passphrase": r["run"]["network_passphrase"],
                      "ledger_seq": hdr["header"]["ledgerSeq"], "ledger_hash": hdr["hash"],
                      "scenario": r["scenario"], "generator": "tools/localcore.py",
                      "notes": "Standalone network, manual close, fixed keys and close times; "
                               "see the scenario in tools/localcore.py."}
        if source is None:
            source = {"kind": "network_ledger", "network": r["net"],
                      "network_passphrase": mine.PASSPHRASE[r["net"]], "ledger_seq": hdr["header"]["ledgerSeq"],
                      "ledger_hash": hdr["hash"], "close_time": hdr["header"]["scpValue"]["closeTime"],
                      "retrieved_from": mine.ledger_url(r["net"], r["seq"]), "retrieved_on": "2026-11-14"}
        what = [catalog[p]["title"] for p in pats]
        if kind == "golden":
            title = f"stellar-core golden: {source['test'] or source['golden_file']}"
        elif kind == "local":
            title = f"Local stellar-core, scenario {r['scenario']}" + (f": {what[0]}" if what else "")
            if len(what) > 1:
                title += f" and {len(what) - 1} more pattern(s)"
        else:
            title = f"{r['net'].capitalize()} ledger {r['seq']}" + (f": {what[0]}" if what else "")
            if len(what) > 1:
                title += f" and {len(what) - 1} more pattern(s)"
        shape = (" ".join(f"{catalog[p]['title']}. {catalog[p]['why']}" for p in pats)
                 if pats else f"Selected because it exercises {len(cells)} schema cell(s) that no other entry reaches.")
        entry = {
            "id": eid, "title": title, "xdr_type": "LedgerCloseMeta", "file": fname,
            "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
            "protocol_version": hdr["header"]["ledgerVersion"],
            "caps": caps_for(pats, cells, catalog, capmap),
            "synthetic": False, "source": source, "shape": shape,
            "patterns": dict(sorted(ppaths.items())),
            "designated": {"patterns": pats, "cells": cells},
            "cells": sorted(dec.cells), "cells_new_in_protocol": sorted(set(dec.cells) & new_cells),
            "expected": {"decoded": expected_for(dec, value, pats, cells, ppaths, types)},
            "validation": {"independent_decoder": "not_run", "rs_stellar_xdr_roundtrip": "not_run",
                           "stellar_core": {"version": "30.0.0", "command": "", "result": "not_run"},
                           "core_golden": "pass" if kind == "golden" else "not_applicable"},
            "sightings": [],
        }
        print(f"{'would add' if a.dry_run else 'add'} {eid}: {len(raw)} bytes, p{entry['protocol_version']}, "
              f"{len(pats)} pattern(s), {len(cells)} new cell(s)")
        if not a.dry_run:
            (CORPUS / fname).write_text(base64.b64encode(raw).decode() + "\n")
            manifest["entries"].append(entry)
            have.add(eid)
        added += 1
    if not a.dry_run:
        (CORPUS / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"{added} entr{'y' if added == 1 else 'ies'} {'planned' if a.dry_run else 'added'}; "
          f"corpus now {len(manifest['entries'])}")


if __name__ == "__main__":
    main()
