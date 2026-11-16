#!/usr/bin/env python3
"""The SDK behaviour checks for the SDKs other than JavaScript and py-stellar-base: Go, Java, Rust
and py-stellar-xdr. Do they share the defects found in one SDK?

  python3 harness/sdk-semantic/siblings.py [--sdk go,java,rust,python-xdr] [--out FILE]

For each row of the behaviour table in sdk-matrix/MATRIX.md, the input is taken from the same
corpus entry and path as the JavaScript check (corpus/manifest.json, `expected.sdk`), with the kit's
own decoder. Each SDK runs its equivalent helper on the pinned release:
- java-stellar-sdk 6.0.0: harness/sdk-semantic/java/Behaviour.java (Docker, the Maven image, --network none);
- go-stellar-sdk v0.9.0: harness/sdk-semantic/go-behaviour/ (Docker, the Go image);
- rs-stellar-xdr 30.0.0: `ScMap::sorted_from` for the key-order row (harness/sdk-semantic/rust-behaviour/,
  built with cargo); the codec round trip for the IDs and string rows;
- py-stellar-xdr 0.2.1: a codec only; the codec round trip for the IDs and string rows;
- py-stellar-base 17.0.1 (`python`): the two rows its own checks (order.py and friends) do not cover.
Where a row's helper does not exist the cell says so and why (SIBLINGS_NA below).
Writes harness/sdk-semantic/out/siblings.json, one record per row and SDK: result (pass,
mishandled, not applicable, error) and detail. sdk-matrix/matrix.py reads it.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from decode import Decoder, get  # noqa: E402
from encode import Encoder  # noqa: E402

OUT = HERE / "out" / "siblings.json"
JAVA_IMAGE = "maven:3.9-eclipse-temurin-21"
GO_IMAGE = "golang:1.26"
ROWS = ["pool_pair_accepted", "map_keys_host_order", "map_entries_preserved", "map_entries_preserved:host",
        "ids_exact", "string_bytes_kept"]

# Rows whose helper does not exist in an SDK, with the reason; the cell says "not applicable".
SIBLINGS_NA = {
    ("go", "map_keys_host_order"): "go-stellar-sdk has no helper that builds an ScMap from native values",
    ("go", "map_entries_preserved"): "go-stellar-sdk has no conversion of an ScMap to native values",
    ("go", "map_entries_preserved:host"): "go-stellar-sdk has no conversion of an ScMap to native values",
    ("rust", "pool_pair_accepted"): "rs-stellar-xdr is a codec with no asset or liquidity-pool helpers",
    ("rust", "map_entries_preserved"): "rs-stellar-xdr has no conversion of a map to native values",
    ("rust", "map_entries_preserved:host"): "rs-stellar-xdr has no conversion of a map to native values",
    ("python", "map_keys_host_order"): "py-stellar-base builds a map from the entries it is given and does not sort them",
    ("python-xdr", "pool_pair_accepted"): "stellar-xdr is a codec with no asset or liquidity-pool helpers",
    ("python-xdr", "map_keys_host_order"): "stellar-xdr builds no maps from native values",
    ("python-xdr", "map_entries_preserved"): "stellar-xdr has no conversion of a map to native values",
    ("python-xdr", "map_entries_preserved:host"): "stellar-xdr has no conversion of a map to native values",
}


def inputs():
    """{row: (args...)} from the corpus, the same values the JavaScript checks get."""
    schema = json.load(open(ROOT / "schema/schema.json"))
    dec, enc = Decoder(schema), Encoder(schema)
    manifest = {e["id"]: e for e in json.load(open(ROOT / "corpus/manifest.json"))["entries"]}

    def spec(eid, check):
        e = manifest[eid]
        whole = dec.decode(e["xdr_type"], base64.b64decode((ROOT / "corpus" / e["file"]).read_text()))
        return e, whole, next(s for s in e["expected"]["sdk"] if s["check"] == check)

    out = {}
    e, whole, x = spec("testnet-5708889", "pool_pair_accepted")
    out["pool_pair_accepted"] = ("pool", base64.b64encode(enc.encode(x["xdr_type"], get(whole, x["path"]))).decode(),
                                 x["pool_id"])
    e, whole, x = spec("testnet-5712621", "map_keys_host_order")
    host_map = get(whole, x["path"])
    host_b64 = base64.b64encode(enc.encode("SCVal", host_map)).decode()
    out["map_keys_host_order"] = ("mapkeys", host_b64)
    out["map_entries_preserved:host"] = ("mapentries", host_b64, str(len(host_map["map"])))
    e, whole, x = spec("synthetic-scmap-colliding-keys", "map_entries_preserved")
    out["map_entries_preserved"] = ("mapentries", base64.b64encode(enc.encode("SCVal", get(whole, x["path"]))).decode(),
                                    str(x["entries"]))
    e, whole, x = spec("synthetic-ids-beyond-f64", "ids_exact")
    out["ids_exact"] = ("ids", (ROOT / "corpus" / e["file"]).read_text().strip(), json.dumps(x))
    e, whole, x = spec("localcore-memo-and-offer-p30-4", "string_bytes_kept")
    env_path = x["path"][:-len(".v1.tx.memo")]
    out["string_bytes_kept"] = ("string", base64.b64encode(enc.encode(x["xdr_type"], get(whole, x["path"]))).decode(),
                                base64.b64encode(enc.encode("TransactionEnvelope", get(whole, env_path))).decode())
    return out


def run_java(args):
    """Compile Behaviour.java once and run every row; the spec file goes in through the mount."""
    with tempfile.TemporaryDirectory() as tmp:
        script = ["javac -cp '/jars/*' -d /tmp/out /src/Behaviour.java >&2"]
        for row, a in args.items():
            a = list(a)
            if a[0] == "ids":
                Path(tmp, "spec.json").write_text(a[2])
                a[2] = "/data/spec.json"
            script.append("echo '@@%s'; java -cp '/jars/*:/tmp/out' Behaviour %s" % (row, " ".join("'%s'" % v for v in a)))
        p = subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh",
                            "-v", "%s:/jars:ro" % (ROOT / "runners/java/lib"), "-v", "%s:/src:ro" % (HERE / "java"),
                            "-v", "%s:/data:ro" % tmp, JAVA_IMAGE, "-c", "; ".join(script)],
                           capture_output=True, text=True)
    return parse(p)


def run_go(args):
    # Fetch the pinned modules first (network), then build and run with --network none.
    subprocess.run(["docker", "run", "--rm", "-v", "shapecov-linter-gomod:/go/pkg/mod", "-v", "%s:/src:ro" % (HERE / "go-behaviour"),
                    GO_IMAGE, "sh", "-c", "mkdir -p /tmp/src && cp /src/go.mod /src/go.sum /tmp/src/ && cd /tmp/src && go mod download"],
                   capture_output=True, text=True)
    with tempfile.TemporaryDirectory() as tmp:
        script = ["mkdir -p /tmp/src && cp /src/main.go /src/go.mod /src/go.sum /tmp/src/ && cd /tmp/src && go build -o /tmp/b . >&2"]
        for row, a in args.items():
            if ("go", row) in SIBLINGS_NA:
                continue
            a = list(a)
            if a[0] == "ids":
                Path(tmp, "spec.json").write_text(a[2])
                a[2] = "/data/spec.json"
            script.append("echo '@@%s'; /tmp/b %s" % (row, " ".join("'%s'" % v for v in a)))
        p = subprocess.run(["docker", "run", "--rm", "--network", "none", "-e", "GOPROXY=off", "-e", "GOFLAGS=-mod=mod",
                            "-v", "shapecov-linter-gomod:/go/pkg/mod", "-v", "%s:/src:ro" % (HERE / "go-behaviour"),
                            "-v", "%s:/data:ro" % tmp, GO_IMAGE, "sh", "-c", "; ".join(script)],
                           capture_output=True, text=True)
    res = parse(p)
    res.update({row: {"result": "not applicable", "detail": SIBLINGS_NA[("go", row)]}
                for row in args if ("go", row) in SIBLINGS_NA})
    return res


def parse(p):
    res, row = {}, None
    for line in p.stdout.splitlines():
        if line.startswith("@@"):
            row = line[2:]
        elif row and line.startswith("{"):
            res[row] = json.loads(line)
    if not res:
        res["_error"] = {"result": "error", "detail": (p.stderr or p.stdout).strip()[-600:]}
    return res


def run_codec(sdk, args):
    """rs-stellar-xdr and py-stellar-xdr: the codec questions, through the conformance runners."""
    from run import RUNNERS, run  # tools/run.py: one runner process per SDK, TSV in and out
    res = {}
    for row, a in args.items():
        if (sdk, row) in SIBLINGS_NA:
            res[row] = {"result": "not applicable", "detail": SIBLINGS_NA[(sdk, row)]}
    if sdk == "rust":
        crate = HERE / "rust-behaviour"
        binary = crate / "target/release/rust-behaviour"
        if not binary.exists():
            subprocess.run(["cargo", "build", "--release", "--quiet"], cwd=crate, check=True)
        p = subprocess.run([str(binary), "mapkeys", args["map_keys_host_order"][1]], capture_output=True, text=True)
        res["map_keys_host_order"] = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else \
            {"result": "error", "detail": p.stderr.strip()[-300:]}
    checks = {"ids_exact": ("TransactionEnvelope", args["ids_exact"][1]),
              "string_bytes_kept": ("Memo", args["string_bytes_kept"][1])}
    lines = ["%s\t%s\t%s\n" % (row, t, b64) for row, (t, b64) in checks.items()]
    for line in run(RUNNERS[sdk]["cmd"], lines):
        row, status, payload = (line.rstrip("\n").split("\t") + ["", ""])[:3]
        if row not in checks:
            continue
        want = checks[row][1]
        if status == "ok" and payload == want:
            res[row] = {"result": "pass", "detail": "decodes and re-encodes to the same bytes; "
                        + ("64-bit IDs are integer types" if row == "ids_exact" else "the string type holds bytes")}
        else:
            res[row] = {"result": "mishandled", "detail": "%s: %s" % (status, payload[:200])}
    return res


def run_python_base(args):
    """py-stellar-base: the memo row (its other rows run through order.py, map_entries.py, ids.py)."""
    py = ROOT / "runners/python/.venv/bin/python"
    code = ("import json,sys\nfrom stellar_sdk import xdr, Memo\nb=sys.argv[1]\n"
            "m=Memo.from_xdr_object(xdr.Memo.from_xdr(b))\nok=m.to_xdr_object().to_xdr()==b\n"
            "print(json.dumps({'result':'pass' if ok else 'mishandled','detail':'TextMemo.memo_text is bytes; '"
            "+('the round trip keeps them' if ok else 'the round trip changes them')}))")
    p = subprocess.run([str(py), "-c", code, args["string_bytes_kept"][1]], capture_output=True, text=True)
    res = {"string_bytes_kept": json.loads(p.stdout) if p.returncode == 0 else
           {"result": "error", "detail": p.stderr.strip()[-300:]}}
    res["map_keys_host_order"] = {"result": "not applicable", "detail": SIBLINGS_NA[("python", "map_keys_host_order")]}
    return res


# Upstream issues and notes recorded next to a result (they do not change the result).
ANNOTATIONS = {
    ("java", "ids_exact"): {"issue": "https://github.com/lightsail-network/java-stellar-sdk/issues/843"},
    ("java", "string_bytes_kept"): {"issue": "https://github.com/lightsail-network/java-stellar-sdk/issues/843"},
    ("java", "map_entries_preserved"): {"note": "keys that differ only in type; exact duplicates are java-stellar-sdk #838"},
    ("java", "map_entries_preserved:host"): {"note": "keys that differ only in type; exact duplicates are java-stellar-sdk #838"},
}


def annotate(out):
    for (sdk, row), extra in ANNOTATIONS.items():
        if row in out.get(sdk, {}):
            out[sdk][row].update(extra)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", default="java,go,rust,python-xdr,python")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true", help="rerun and compare each result with the recorded one")
    a = ap.parse_args()
    if a.check:
        recorded = json.load(open(OUT))
        fresh = Path(tempfile.mkdtemp()) / "siblings.json"
        a.out = str(fresh)
    args = inputs()
    out = json.load(open(a.out)) if os.path.exists(a.out) else {}
    for sdk in a.sdk.split(","):
        if sdk in ("java", "go", "python"):
            res = {"java": run_java, "go": run_go, "python": run_python_base}[sdk](args)
        else:
            res = run_codec(sdk, args)
        out[sdk] = res
        for row in (ROWS if sdk != "python" else ["map_keys_host_order", "string_bytes_kept"]):
            r = res.get(row, res.get("_error", {"result": "error", "detail": "no result"}))
            print("%-12s %-28s %-15s %s" % (sdk, row, r["result"], r.get("detail", "")[:150]))
    Path(a.out).parent.mkdir(exist_ok=True)
    Path(a.out).write_text(json.dumps(annotate(out), indent=1, sort_keys=True) + "\n")
    if a.check:
        diff = ["%s %s: recorded %s, now %s" % (sdk, row, r["result"], out.get(sdk, {}).get(row, {}).get("result"))
                for sdk, rows in recorded.items() if sdk in a.sdk.split(",") for row, r in rows.items()
                if out.get(sdk, {}).get(row, {}).get("result") != r["result"]]
        for d in diff:
            print("CHANGED " + d)
        print("SIBLINGS OK" if not diff else "SIBLINGS DIFFER (%d)" % len(diff))
        sys.exit(1 if diff else 0)


if __name__ == "__main__":
    main()
