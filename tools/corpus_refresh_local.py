#!/usr/bin/env python3
"""Replace the local stellar-core corpus entries with a fresh tools/localcore.py run.

  corpus_refresh_local.py --run DIR [--run DIR ...] [--dry-run]

Each DIR is one scenario's localcore.py output (run.json, ledgers/) on the testnet passphrase.
For every `ledger_<name>` in it, the entry `localcore-<name>-<seq>` gets the new ledger bytes and
every field derived from them is recomputed exactly as tools/corpus_add.py computes it: hash, size,
source record, patterns, cells and the expected decoded values. Hand-written fields stay: title,
shape, designated patterns and cells, CAP tags, sightings, and the expected indexer rows and SDK
checks. An entry whose ledger sequence would change is refused.
"""
import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mine  # noqa: E402
from corpus_add import expected_for  # noqa: E402
from decode import Decoder  # noqa: E402
from gen import all_cells  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    schema = json.load(open(ROOT / "schema" / "schema.json"))
    types = schema["types"]
    new_cells = all_cells(schema) - all_cells(json.load(open(ROOT / "schema" / "schema-v28.0.json")))
    manifest = json.load(open(CORPUS / "manifest.json"))
    by_id = {e["id"]: e for e in manifest["entries"]}
    changed = 0
    for d in a.run:
        run = json.load(open(Path(d) / "run.json"))
        if run["network_passphrase"] != "Test SDF Network ; September 2015":
            raise SystemExit("%s: corpus entries are on the testnet passphrase" % d)
        for key, seq in sorted(run.items()):
            if not key.startswith("ledger_") or not isinstance(seq, int):
                continue
            name = key[len("ledger_"):].replace("_", "-")
            eid = "localcore-%s-%d" % (name, seq)
            e = by_id.get(eid)
            if e is None:
                raise SystemExit("no corpus entry %s (did the ledger sequence change?)" % eid)
            raw = (Path(d) / "ledgers" / ("%d.xdr" % seq)).read_bytes()
            if hashlib.sha256(raw).hexdigest() == e["sha256"]:
                print("same      %s" % eid)
                continue
            dec = Decoder(schema)
            value = dec.decode("LedgerCloseMeta", raw)
            hdr = value["v%d" % value["v"]]["ledgerHeader"]
            if hdr["header"]["ledgerSeq"] != seq:
                raise SystemExit("%s: header says ledger %d" % (eid, hdr["header"]["ledgerSeq"]))
            ppaths = mine.patterns(value, with_paths=True)
            designated = e.get("designated") or {"patterns": [], "cells": []}
            e["sha256"] = hashlib.sha256(raw).hexdigest()
            e["size_bytes"] = len(raw)
            e["protocol_version"] = hdr["header"]["ledgerVersion"]
            e["source"].update({"stellar_core_version": run["stellar_core_version"], "image": run["stellar_core_image"],
                                "ledger_seq": seq, "ledger_hash": hdr["hash"],
                                "notes": "Standalone network, manual close, fixed keys and close times; "
                                         "reproducible with tools/localcore_repro.py. See the scenario in "
                                         "tools/localcore.py."})
            e["patterns"] = dict(sorted(ppaths.items()))
            e["cells"] = sorted(dec.cells)
            e["cells_new_in_protocol"] = sorted(set(dec.cells) & new_cells)
            keep = {k: v for k, v in e["expected"].items() if k != "decoded"}
            e["expected"] = dict({"decoded": expected_for(dec, value, designated["patterns"], designated["cells"],
                                                          ppaths, types)}, **keep)
            print("%s %s: %d bytes, ledger hash %s" % ("would refresh" if a.dry_run else "refreshed", eid, len(raw),
                                                        hdr["hash"][:12]))
            if not a.dry_run:
                (CORPUS / e["file"]).write_text(base64.b64encode(raw).decode() + "\n")
            changed += 1
    if not a.dry_run and changed:
        (CORPUS / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    print("%d entr%s refreshed" % (changed, "y" if changed == 1 else "ies"))


if __name__ == "__main__":
    main()
