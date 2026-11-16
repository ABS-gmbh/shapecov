#!/usr/bin/env python3
"""Check that tools/localcore.py reproduces its corpus ledgers, under both passphrases.

  localcore_repro.py run    --passphrase testnet|pubnet --out DIR [--scenario NAME ...]
  localcore_repro.py check  --run DIR [--run DIR ...] [--update]

`run` runs every scenario that records ledgers. `check` compares each scenario ledger with
corpus/localcore-reproducible.json (one record per scenario ledger and passphrase), and, for the
testnet passphrase, with the corpus entry itself. `--update` rewrites the record instead.

Two things in stellar-core's own output are not deterministic between runs, and are normalized
before comparing; everything else must match byte for byte:

  1. The order of the entries within one LedgerEntryChanges list. Core collects an operation's
     changes in hash maps seeded per process, and its own tests normalize meta the same way. Each
     STATE entry stays paired with the UPDATED or REMOVED entry that follows it; the units are
     sorted by their XDR bytes.
  2. The `invoke_time_nsecs` value in core's `core_metrics` diagnostic events: wall-clock time.

The record keeps the SHA-256 of the raw ledger as emitted and of the normalized ledger.
"""
import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from decode import Decoder  # noqa: E402
from encode import Encoder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RECORD = ROOT / "corpus" / "localcore-reproducible.json"
# Scenarios that record corpus ledgers (muxed-source-refused-p24 records only a refusal).
SCENARIOS = ["classic-p22", "muxed-source-p22", "memo-and-offer-p30", "sac-trust-p28", "pools-sponsorship-p30",
             "flags-preauth-p30", "participants-p28", "failures-p30", "big-merge-p30",
             "trustline-churn-p28", "deployer-cb-p28"]
NETWORKS = {"testnet": "Test SDF Network ; September 2015", "pubnet": "Public Global Stellar Network ; September 2015"}

_CODEC = {}


def codec():
    if not _CODEC:
        schema = json.load(open(ROOT / "schema" / "schema.json"))
        _CODEC["dec"], _CODEC["enc"] = Decoder(schema), Encoder(schema)
    return _CODEC["dec"], _CODEC["enc"]


def _normalize_changes(changes, enc):
    units, i = [], 0
    while i < len(changes):
        ch = changes[i]
        if ch["type"] == "LEDGER_ENTRY_STATE" and i + 1 < len(changes) and \
                changes[i + 1]["type"] in ("LEDGER_ENTRY_UPDATED", "LEDGER_ENTRY_REMOVED"):
            units.append([ch, changes[i + 1]])
            i += 2
        else:
            units.append([ch])
            i += 1
    units.sort(key=lambda u: b"".join(enc.encode("LedgerEntryChange", c) for c in u))
    return [c for u in units for c in u]


def normalize(value):
    """Normalize a decoded LedgerCloseMeta in place (see the module docstring) and return it."""
    _, enc = codec()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, list) and v and all(isinstance(c, dict) and str(c.get("type", "")).startswith("LEDGER_ENTRY_")
                                                     for c in v):
                    x[k] = _normalize_changes(v, enc)
                else:
                    walk(v)
            body = (x.get("body") or {}).get("v0") if "body" in x else None
            if body and body.get("topics"):
                syms = [t.get("sym") for t in body["topics"]]
                if syms[:2] == ["core_metrics", "invoke_time_nsecs"] and body["data"].get("type") == "SCV_U64":
                    body["data"]["u64"] = 0
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(value)
    return value


def digests(raw):
    dec, enc = codec()
    norm = enc.encode("LedgerCloseMeta", normalize(dec.decode("LedgerCloseMeta", raw)))
    return {"raw_sha256": hashlib.sha256(raw).hexdigest(), "normalized_sha256": hashlib.sha256(norm).hexdigest()}


def cmd_run(a):
    out = Path(a.out)
    for sc in a.scenario or SCENARIOS:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "localcore.py"), "--scenario", sc,
                            "--passphrase", a.passphrase, "--out", str(out / sc)], capture_output=True, text=True)
        print("%-24s %s %s" % (sc, a.passphrase, "ok" if r.returncode == 0 else "FAILED\n" + r.stdout[-800:] + r.stderr[-800:]),
              flush=True)
        if r.returncode != 0:
            sys.exit(1)


def cmd_check(a):
    record = json.load(open(RECORD)) if RECORD.exists() else {"ledgers": {}}
    manifest = {e["id"]: e for e in json.load(open(ROOT / "corpus" / "manifest.json"))["entries"]}
    bad = 0
    for run_dir in a.run:
        for sc_dir in sorted(p for p in Path(run_dir).iterdir() if (p / "run.json").exists()):
            run = json.load(open(sc_dir / "run.json"))
            net = next(k for k, v in NETWORKS.items() if v == run["network_passphrase"])
            for key, seq in sorted(run.items()):
                if not key.startswith("ledger_") or not isinstance(seq, int):
                    continue
                name = key[len("ledger_"):].replace("_", "-")
                got = dict(digests((sc_dir / "ledgers" / ("%d.xdr" % seq)).read_bytes()), seq=seq)
                slot = record["ledgers"].setdefault(name, {})
                if a.update:
                    slot[net] = got
                    print("recorded  %-26s %s seq %d" % (name, net, seq))
                    continue
                want = slot.get(net)
                ok = want is not None and want["normalized_sha256"] == got["normalized_sha256"] and want["seq"] == seq
                note = "" if ok else " (recorded %s)" % (want and want["normalized_sha256"][:12])
                if net == "testnet":
                    eid = "localcore-%s-%d" % (name, seq)
                    e = manifest.get(eid)
                    if e is None:
                        ok, note = False, note + "; no corpus entry %s" % eid
                    else:
                        entry = digests(base64.b64decode((ROOT / "corpus" / e["file"]).read_text()))
                        if entry["normalized_sha256"] != got["normalized_sha256"]:
                            ok, note = False, note + "; differs from corpus entry %s" % eid
                bad += not ok
                print("%-9s %-26s %s seq %d normalized %s raw %s%s" % (
                    "ok" if ok else "DIFFERS", name, net, seq, got["normalized_sha256"][:12],
                    "same" if want and want["raw_sha256"] == got["raw_sha256"] else "differs", note))
    if a.update:
        record["note"] = ("SHA-256 of each tools/localcore.py scenario ledger per passphrase, raw and normalized; "
                          "see tools/localcore_repro.py for the normalization. Checked in CI by regenerating.")
        json.dump(record, open(RECORD, "w"), indent=1, sort_keys=True)
        RECORD.open("a").write("\n")
        return
    print("REPRODUCIBLE" if not bad else "%d LEDGER(S) DO NOT REPRODUCE" % bad)
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="verb", required=True)
    r = sub.add_parser("run")
    r.add_argument("--passphrase", choices=sorted(NETWORKS), required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--scenario", action="append")
    c = sub.add_parser("check")
    c.add_argument("--run", action="append", required=True)
    c.add_argument("--update", action="store_true")
    a = ap.parse_args()
    {"run": cmd_run, "check": cmd_check}[a.verb](a)


if __name__ == "__main__":
    main()
