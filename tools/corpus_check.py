"""Verify the corpus: manifest against its schema, every entry against its record.

  corpus_check.py [--sdks rust,js,python,go,java] [--core] [--sdk-checks] [--record]

Always run (no SDK, no Docker):
  * the manifest validates against corpus/manifest.schema.json;
  * each entry file matches sha256 and size_bytes;
  * the independent strict decoder (tools/decode.py) decodes it, re-encoding
    gives the same bytes, and the cells it exercises equal the recorded cells;
  * every expected.decoded value matches;
  * the source record agrees with the bytes (ledger sequence, hash, close time
    and protocol for a network ledger; value file for a generated entry);
  * CAP cells are among the entry's cells, and protocol tagging is consistent
    with the difference between the two schema versions;
  * indexer expectations follow from the decoded entry.

Optional:
  --sdks        decode and re-encode each entry with the listed SDK runners;
                rs-stellar-xdr (rust) is the round trip the RFP asks for.
  --core        have stellar-core 30.0.0 decode each entry (Docker) and compare
                its own JSON output with expected.decoded.
  --sdk-checks  run the expected.sdk checks against pinned SDK versions and
                print the matrix. These are findings, not corpus failures.
  --record      write the results into the manifest's validation blocks.

Exit status is non-zero if any corpus check fails.
"""
import argparse
import base64
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mine  # noqa: E402
import strkey  # noqa: E402
from decode import Decoder, XdrError, get  # noqa: E402
from encode import Encoder  # noqa: E402
from gen import all_cells  # noqa: E402
from run import RUNNERS, run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
CORE_IMAGE = "stellar/stellar-core:30.0.0-3642.0e49751aa.noble"
CORE_FILETYPE = {"Asset": "asset", "LedgerEntry": "ledgerentry", "LedgerHeader": "ledgerheader",
                 "TransactionMeta": "meta", "TransactionResult": "result",
                 "TransactionResultPair": "resultpair", "TransactionEnvelope": "tx"}


class Report:
    def __init__(self):
        self.failures = 0

    def check(self, entry, name, ok, detail=""):
        if not ok:
            self.failures += 1
        print(f"  {'ok  ' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")
        return ok


def static_checks(e, raw, dec, enc, new_cells, schema_protocol, rep, ctx=None):
    ctx = ctx or {}
    eid = e["id"]
    rep.check(eid, "sha256 and size", hashlib.sha256(raw).hexdigest() == e["sha256"] and len(raw) == e["size_bytes"])
    try:
        v = dec.decode(e["xdr_type"], raw)
    except XdrError as err:
        rep.check(eid, "independent decoder", False, str(err))
        return None
    rep.check(eid, "independent decoder", True, f"{e['xdr_type']}, {len(raw)} bytes")
    rep.check(eid, "re-encode is byte-identical", enc.encode(e["xdr_type"], v) == raw)
    rep.check(eid, "cells", sorted(dec.cells) == e["cells"], f"{len(dec.cells)} cells")
    bad = []
    for x in e["expected"]["decoded"]:
        try:
            got = get(v, x["path"])
        except (KeyError, IndexError, TypeError) as err:
            got = f"<{err}>"
        if got != x["value"]:
            bad.append(f"{x['path']}: expected {x['value']!r}, got {got!r}")
    rep.check(eid, "expected decoded values", not bad,
              "; ".join(bad) if bad else f"{len(e['expected']['decoded'])} of {len(e['expected']['decoded'])}")

    src = e["source"]
    if src["kind"] == "network_ledger":
        body = v[f"v{v['v']}"]
        hdr = body["ledgerHeader"]
        ok = (hdr["header"]["ledgerSeq"] == src["ledger_seq"] and hdr["hash"] == src["ledger_hash"]
              and hdr["header"]["scpValue"]["closeTime"] == src["close_time"]
              and hdr["header"]["ledgerVersion"] == e["protocol_version"])
        rep.check(eid, "source record matches the ledger header", ok and not e["synthetic"])
    elif src["kind"] in ("stellar_core_golden", "local_stellar_core"):
        hdr = v[f"v{v['v']}"]["ledgerHeader"]
        ok = hdr["header"]["ledgerVersion"] == e["protocol_version"] and not e["synthetic"]
        if src["kind"] == "local_stellar_core":
            ok = ok and hdr["header"]["ledgerSeq"] == src["ledger_seq"] and hdr["hash"] == src["ledger_hash"]
        rep.check(eid, "source record matches the ledger header", ok)
        if src["kind"] == "stellar_core_golden" and ctx.get("goldens"):
            f = Path(ctx["goldens"]) / src["golden_file"]
            same = f.exists() and mine.golden_records(f)[src["record"]] == raw
            rep.check(eid, "byte-identical to the stellar-core golden record", same, src["golden_file"])
            e["validation"]["core_golden"] = "pass" if same else "fail"
    elif src["kind"] == "generated":
        value = json.load(open(CORPUS / src["value_file"]))
        rep.check(eid, "value file encodes to the entry bytes",
                  enc.encode(e["xdr_type"], value) == raw and e["synthetic"])

    evidence = [x["evidence"] for x in e.get("sightings", []) if x.get("evidence")]
    if evidence:
        gone = [x for x in evidence if not (CORPUS / x).resolve().is_file()]
        rep.check(eid, "sighting evidence files exist", not gone,
                  ("missing: " + ", ".join(gone)) if gone else ", ".join(evidence))

    cap_cells = {c for cap in e["caps"] for c in cap.get("cells", [])}
    cap_pats = {p for cap in e["caps"] for p in cap.get("patterns", [])}
    known = all(cap["cap"] in ctx.get("caps", {cap["cap"]: 1}) for cap in e["caps"])
    rep.check(eid, "CAP tags are official CAPs and are exercised by the entry",
              known and cap_cells <= set(e["cells"]) and cap_pats <= set(e.get("patterns", {})))
    if e["xdr_type"] == "LedgerCloseMeta" and "patterns" in e:
        rep.check(eid, "patterns", mine.patterns(v, with_paths=True) == e["patterns"], f"{len(e['patterns'])} pattern(s)")
    if "designated" in e:
        d = e["designated"]
        rep.check(eid, "designated patterns and cells are in the entry",
                  set(d["patterns"]) <= set(e.get("patterns", {})) and set(d["cells"]) <= set(e["cells"]))
    new_here = sorted(set(e["cells"]) & new_cells)
    ok = new_here == e.get("cells_new_in_protocol", [])
    if new_here:
        ok = ok and e["protocol_version"] == schema_protocol
    rep.check(eid, "protocol tagging", ok, f"{len(new_here)} cell(s) new in protocol {schema_protocol}")

    for x in e["expected"].get("indexer", []):
        if x["expect"] == "signer_state_change":
            k = get(v, x["derived_from"])
            want = None
            if k["type"] == "SIGNER_KEY_TYPE_ED25519_SIGNED_PAYLOAD":
                want = strkey.signed_payload(k["ed25519SignedPayload"]["ed25519"], k["ed25519SignedPayload"]["payload"])
            rep.check(eid, "indexer expectation follows from the entry", want == x["signer_key"], x["signer_key"])
    return v


def sdk_roundtrips(entries, raws, sdks, rep):
    lines = [f"{e['id']}\t{e['xdr_type']}\t{base64.b64encode(raws[e['id']]).decode()}\n" for e in entries]
    out = {e["id"]: {} for e in entries}
    for s in sdks:
        res = {l.split("\t")[0]: l.split("\t") for l in run(RUNNERS[s]["cmd"], lines)}
        for e in entries:
            r = res.get(e["id"], [e["id"], "crash", ""])
            same = r[1] == "ok" and r[2].strip() == base64.b64encode(raws[e["id"]]).decode()
            out[e["id"]][s] = "agree" if same else ("unsupported" if r[1] == "notype" else
                                                    r[1] if r[1] in ("crash", "hang") else "disagree")
    for e in entries:
        print(f"{e['id']}")
        for s in sdks:
            if s == "rust":      # the round trip the RFP requires of every entry
                rep.check(e["id"], f"{RUNNERS[s]['version']} decodes and re-encodes identically",
                          out[e["id"]][s] == "agree", "" if out[e["id"]][s] == "agree" else out[e["id"]][s])
            elif out[e["id"]][s] == "agree":
                print(f"  ok   {RUNNERS[s]['version']} decodes and re-encodes identically")
            else:                # an SDK failing on a valid entry is a finding about the SDK
                print(f"  FINDING {RUNNERS[s]['version']}: {out[e['id']][s]}")
    return out


def core_decode(entries, raws, rep):
    tmp = ROOT / "out" / ".corecheck"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    script, how = [], {}
    for e in entries:
        raw = raws[e["id"]]
        if e["xdr_type"] == "LedgerCloseMeta":
            # stellar-core reads a meta-debug file as a record-marked stream of LedgerCloseMeta
            (tmp / f"meta-debug-{e['id']}.xdr").write_bytes(struct.pack(">I", len(raw) | 0x80000000) + raw)
            script.append(f"stellar-core dump-xdr /d/meta-debug-{e['id']}.xdr > /o/{e['id']}.json 2>/o/{e['id']}.err")
            how[e["id"]] = "dump-xdr (meta-debug stream)"
        elif e["xdr_type"] in CORE_FILETYPE:
            (tmp / f"{e['id']}.b64").write_text(base64.b64encode(raw).decode() + "\n")
            ft = CORE_FILETYPE[e["xdr_type"]]
            script.append(f"stellar-core print-xdr /d/{e['id']}.b64 --filetype {ft} --base64 > /o/{e['id']}.json 2>/o/{e['id']}.err")
            how[e["id"]] = f"print-xdr --filetype {ft}"
    (tmp / "o").mkdir()
    subprocess.run(["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none", "--entrypoint", "sh",
                    "-v", f"{tmp}:/d:ro", "-v", f"{tmp / 'o'}:/o", CORE_IMAGE, "-c", "; ".join(script) + "; true"],
                   check=True, capture_output=True)
    out = {}
    for e in entries:
        print(f"{e['id']}")
        if e["id"] not in how:
            out[e["id"]] = {"version": "30.0.0", "command": "", "result": "not_applicable"}
            print("  --   stellar-core has no command that decodes this type on its own")
            continue
        # stellar-core prints string bytes as they are, so its JSON is not always valid UTF-8
        text = (tmp / "o" / f"{e['id']}.json").read_bytes().decode("utf-8", "replace")
        try:
            j = json.loads(text, strict=False)
        except json.JSONDecodeError:
            err = (tmp / "o" / f"{e['id']}.err").read_bytes().decode("utf-8", "replace").strip().split("\n")[-1]
            rep.check(e["id"], f"stellar-core 30.0.0 {how[e['id']]}", False, (text.strip() or err)[:200])
            out[e["id"]] = {"version": "30.0.0", "command": how[e["id"]], "result": "fail"}
            continue
        j = j[0] if isinstance(j, list) else j[e["xdr_type"]]
        agree = other = 0
        wrong = []
        for x in e["expected"]["decoded"]:
            try:
                got = get(j, x["path"])
            except (KeyError, IndexError, TypeError):
                other += 1
                continue
            if got == x["value"]:
                agree += 1
            else:
                wrong.append(f"{x['path']}: stellar-core prints {got!r}")
        rep.check(e["id"], f"stellar-core 30.0.0 {how[e['id']]}", not wrong,
                  "; ".join(wrong) if wrong else
                  f"decoded; confirms {agree} of {len(e['expected']['decoded'])} expected values"
                  + (f", prints {other} in another form" if other else ""))
        out[e["id"]] = {"version": "30.0.0", "command": how[e["id"]], "result": "fail" if wrong else "pass",
                        "expected_values_agree": agree, "expected_values_rendered_differently": other}
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def sdk_checks(entries):
    """Run each entry's expected.sdk checks against pinned SDK versions. Findings about SDKs are
    printed; they are not corpus failures and do not change the exit status."""
    sem = ROOT / "harness" / "sdk-semantic"
    py = str(ROOT / "runners/python/.venv/bin/python")
    for e in entries:
        entry = str(CORPUS / e["file"])
        for x in e["expected"].get("sdk", []):
            if x["check"] == "map_entries_preserved":
                print(f"{e['id']}: {x['check']} at {x['path']} (expect {x['entries']} entries)")
                tail = [e["xdr_type"], entry, x["path"], str(x["entries"])]
                targets = [["node", str(sem / "map_entries.mjs"), "sdk-17.2.1"] + tail,
                           ["node", str(sem / "map_entries.mjs"), "sdk-17.4.0"] + tail,
                           [py, str(sem / "map_entries.py")] + tail]
            elif x["check"] == "ids_exact":
                print(f"{e['id']}: {x['check']} at {x['path']}")
                spec = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
                json.dump(x, spec)
                spec.close()
                targets = [["node", str(sem / "ids.mjs"), "sdk-17.2.1", entry, spec.name],
                           ["node", str(sem / "ids.mjs"), "sdk-17.4.0", entry, spec.name],
                           [py, str(sem / "ids.py"), entry, spec.name]]
            elif x["check"] in ("pool_pair_accepted", "map_keys_host_order", "string_bytes_kept"):
                # Extract the value with the independent decoder, so SDK releases that cannot decode
                # the whole (newer) ledger are still tested on this behaviour (js-stellar-sdk#1766).
                print(f"{e['id']}: {x['check']} at {x['path']}")
                schema = json.load(open(ROOT / "schema/schema.json"))
                whole = Decoder(schema).decode(e["xdr_type"], base64.b64decode((CORPUS / e["file"]).read_text()))
                b64 = base64.b64encode(Encoder(schema).encode(x["xdr_type"], get(whole, x["path"]))).decode()
                extra = [x["pool_id"]] if x["check"] == "pool_pair_accepted" else []
                # 16.4.1: the maintained v16 line; 17.2.0: the last release before #1766; 17.2.1: the fix
                versions = ("sdk-17.2.1", "sdk-17.4.0") if x["check"] == "string_bytes_kept" else \
                    ("sdk-16.4.1", "sdk-17.2.0", "sdk-17.2.1")
                targets = [["node", str(sem / "order.mjs"), v, x["check"], x["xdr_type"], b64] + extra
                           for v in versions]
                if x["check"] == "pool_pair_accepted":
                    targets.append([py, str(sem / "order.py"), x["check"], x["xdr_type"], b64] + extra)
            else:
                print(f"{e['id']}: {x['check']}: no runner for this check kind in corpus_check")
                continue
            for cmd in targets:
                p = subprocess.run(cmd, capture_output=True, text=True, cwd=sem)
                try:
                    r = json.loads(p.stdout.strip().split("\n")[-1])
                except (json.JSONDecodeError, IndexError):
                    print(f"  error      {' '.join(cmd[1:3])}: {p.stderr.strip()[-200:]}")
                    continue
                detail = r.get("detail") or "; ".join(r.get("wrong", []) + r.get("accepted", []))
                print(f"  {r['result']:<10} {r['sdk']}" + (f": {detail[:300]}" if detail else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdks", default="")
    ap.add_argument("--core", action="store_true")
    ap.add_argument("--sdk-checks", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--goldens", help="a stellar-core checkout; golden entries are compared byte for byte with it")
    ap.add_argument("--quiet", action="store_true", help="print only failures, findings and totals")
    a = ap.parse_args()

    import jsonschema
    manifest = json.load(open(CORPUS / "manifest.json"))
    mschema = json.load(open(CORPUS / "manifest.schema.json"))
    rep = Report()
    errs = list(jsonschema.Draft202012Validator(mschema).iter_errors(manifest))
    print("manifest")
    rep.check("manifest", "validates against manifest.schema.json", not errs,
              "; ".join(f"{list(x.path)}: {x.message[:120]}" for x in errs[:5]))
    ids = [e["id"] for e in manifest["entries"]]
    rep.check("manifest", "entry IDs are unique", len(ids) == len(set(ids)), f"{len(ids)} entries")

    schema = json.load(open(ROOT / "schema/schema.json"))
    new_cells = all_cells(schema) - all_cells(json.load(open(ROOT / "schema/schema-v28.0.json")))
    dec, enc = Decoder(schema), Encoder(schema)
    caps = json.load(open(CORPUS / "caps.json"))["caps"]
    raws = {}
    for e in manifest["entries"]:
        print(e["id"])
        raws[e["id"]] = base64.b64decode((CORPUS / e["file"]).read_text().strip(), validate=True)
        before = rep.failures
        static_checks(e, raws[e["id"]], dec, enc, new_cells, manifest["xdr_schema"]["protocol_version"], rep,
                      {"goldens": a.goldens, "caps": caps})
        e["validation"]["independent_decoder"] = "pass" if rep.failures == before else "fail"

    if a.sdks:
        sdks = a.sdks.split(",")
        missing = [s for s in sdks if s not in RUNNERS or not (shutil.which(RUNNERS[s]["cmd"][0]) or Path(RUNNERS[s]["cmd"][0]).exists())]
        if missing:
            print("runner(s) not built: %s. Build them once (README, 'Run it'), or leave them out of --sdks; "
                  "without --sdks every other check still runs." % ", ".join(missing))
            sys.exit(2)
        print("\nSDK round trips")
        res = sdk_roundtrips(manifest["entries"], raws, sdks, rep)
        for e in manifest["entries"]:
            if "rust" in sdks:
                e["validation"]["rs_stellar_xdr_roundtrip"] = "pass" if res[e["id"]]["rust"] == "agree" else "fail"
            e["validation"].setdefault("sdk_decoders", {}).update(
                {RUNNERS[s]["version"]: res[e["id"]][s] for s in sdks if s != "rust"})
    if a.core:
        print("\nstellar-core")
        res = core_decode(manifest["entries"], raws, rep)
        for e in manifest["entries"]:
            e["validation"]["stellar_core"] = res[e["id"]]
    if a.sdk_checks:
        print("\nSDK checks (findings about SDKs, not corpus failures)")
        sdk_checks(manifest["entries"])
    if a.record:
        (CORPUS / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        print("\nrecorded validation results in corpus/manifest.json")
    print(f"\n{'CORPUS OK' if rep.failures == 0 else f'{rep.failures} CHECK(S) FAILED'}")
    sys.exit(1 if rep.failures else 0)


if __name__ == "__main__":
    main()
