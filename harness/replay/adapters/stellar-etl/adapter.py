#!/usr/bin/env python3
"""Replay adapter for stellar/stellar-etl. Contract: ../../ADAPTER.md

Runs the real, unmodified exporter at a given commit:
  prepare  clone, export the commit, `go build` its own main package with cgo, in the Go image its
           own docker/Dockerfile names (Docker)
  up       nothing: stellar-etl keeps no state between runs
  run      the commit's own `export_transactions`, `export_operations`, `export_effects` and
           `export_token_transfer` commands for the one ledger, reading the data lake through the
           Google Cloud Storage client pointed at the feeder with STORAGE_EMULATOR_HOST
           -> the exported JSON lines are read back
  down     remove the container

stellar-etl reads ledgers only from a GCS data lake (its datastore type is fixed to GCS) and only
for pubnet, testnet and futurenet (`--testnet`, `--futurenet`, default pubnet). The feeder serves
the same Galexie files it serves over S3 through the GCS JSON and XML APIs, so the only input is
`datalake`. Entries on any other network are reported as not applicable (see `supported_networks`).

Nothing in the stellar-etl tree is edited and no dependency is changed. Everything third-party
runs in Docker. Python standard library only.
"""
import argparse
import glob
import gzip
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import strkeyx  # noqa: E402

REPO_URL = "https://github.com/stellar/stellar-etl"
DEFAULT_GO_IMAGE = "golang:1.27"
RUN = "shapecov-replay-etl"
BUILD = "shapecov-replay-etl-build"
GCS_HOST = "shapecov-replay-feeder:9100"
NETWORK_FLAGS = {"Public Global Stellar Network ; September 2015": [],
                 "Test SDF Network ; September 2015": ["--testnet"],
                 "Test SDF Future Network ; October 2022": ["--futurenet"]}
# export command -> output name. Order matters only for the log.
EXPORTS = [("export_transactions", "transactions"), ("export_operations", "operations"),
           ("export_effects", "effects"), ("export_token_transfer", "token_transfer")]
STRKEY = re.compile(r"^[GMCPTXLB][A-Z2-7]{55,}$")


def sh(args, check=True, timeout=None):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s" % (p.returncode, " ".join(args), p.stdout or ""))
    return p


def binary_name(commit):
    return "stellar-etl-" + commit


# ---------------------------------------------------------------- prepare

def prepare(a):
    work = os.path.abspath(a.work)
    clone = os.path.join(work, "stellar-etl")
    bindir = os.path.join(work, "bin")
    os.makedirs(bindir, exist_ok=True)
    if not os.path.isdir(os.path.join(clone, ".git")):
        sh(["git", "clone", "-q", REPO_URL, clone])
    if sh(["git", "-C", clone, "cat-file", "-e", a.ref + "^{commit}"], check=False).returncode != 0:
        sh(["git", "-C", clone, "fetch", "-q", "origin"])
    commit = sh(["git", "-C", clone, "rev-parse", a.ref + "^{commit}"]).stdout.strip()
    info_path = os.path.join(bindir, binary_name(commit) + ".json")
    if os.path.isfile(info_path) and os.path.isfile(os.path.join(bindir, binary_name(commit))):
        with open(info_path) as f:
            info = json.load(f)
        info["cached"] = True
        print(json.dumps(info))
        return
    src = os.path.join(work, "src-etl", commit)
    os.makedirs(src, exist_ok=True)
    tar = subprocess.Popen(["git", "-C", clone, "archive", commit], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", src], stdin=tar.stdout, check=True)
    tar.wait()
    gomod = open(os.path.join(src, "go.mod")).read()
    pins = dict(re.findall(r"^\s*(github\.com/stellar/\S+)\s+(\S+)", gomod, re.M))
    # The commit's own build recipe: docker/Dockerfile builds with CGO_ENABLED=1 in a golang image.
    go_image = DEFAULT_GO_IMAGE
    dockerfile = os.path.join(src, "docker", "Dockerfile")
    if os.path.isfile(dockerfile):
        m = re.search(r"^FROM\s+(golang:\S+)", open(dockerfile).read(), re.M)
        if m:
            go_image = m.group(1)
    go_image = os.environ.get("REPLAY_ETL_GO_IMAGE", go_image)
    t0 = time.time()
    sh(["docker", "rm", "-f", BUILD], check=False)
    # Network is needed here only: `go mod download` fetches the modules the commit pins.
    build = sh(["docker", "run", "--rm", "--name", BUILD, "-v", src + ":/src:ro", "-v", bindir + ":/out",
                "-v", "shapecov-replay-gomod:/go/pkg/mod", "-v", "shapecov-replay-gobuild:/root/.cache/go-build",
                "-w", "/src", "-e", "GOFLAGS=-buildvcs=false -mod=readonly", "-e", "CGO_ENABLED=1", go_image, "sh", "-c",
                "go version && go mod download && go build -o /out/%s ." % binary_name(commit)], check=False)
    with open(os.path.join(bindir, binary_name(commit) + ".build.log"), "w") as f:
        f.write(build.stdout or "")
    if build.returncode != 0:
        raise RuntimeError("build failed, see %s" % f.name)
    info = {"adapter": "stellar-etl", "ref": a.ref, "commit": commit,
            "commit_date": sh(["git", "-C", clone, "show", "-s", "--format=%cI", commit]).stdout.strip(),
            "subject": sh(["git", "-C", clone, "show", "-s", "--format=%s", commit]).stdout.strip(),
            "source_modified": False, "dependency_pins": pins, "dependencies_modified": False,
            "supported_networks": sorted(NETWORK_FLAGS), "inputs": ["datalake"],
            "go_image": go_image, "go_version": (build.stdout or "").splitlines()[0] if build.stdout else "",
            "build_seconds": round(time.time() - t0, 1), "cached": False}
    with open(info_path, "w") as f:
        json.dump(info, f, indent=1)
    print(json.dumps(info))


# ---------------------------------------------------------------- up / down

def up(a):
    sh(["docker", "rm", "-f", RUN], check=False)
    print(json.dumps({"services": []}))


def down(a):
    sh(["docker", "rm", "-f", RUN], check=False)
    print(json.dumps({}))


# ---------------------------------------------------------------- run

def read_lines(path):
    """The exported JSON lines; each file is then kept gzipped (mtime 0, so reruns are byte-identical)."""
    rows = []
    for p in sorted(glob.glob(os.path.join(path, "*.txt"))):
        with open(p, "rb") as f:
            data = f.read()
        rows += [json.loads(x) for x in data.decode().splitlines() if x.strip()]
        with open(p + ".gz", "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as z:
            z.write(data)
        os.remove(p)
    return rows


def toid_parts(i):
    """TOID -> (ledger, tx order, op order), as in go-stellar-sdk toid."""
    i = int(i)
    return i >> 32, (i >> 12) & 0xFFFFF, i & 0xFFF


def unreadable_strings(table, rows):
    """Every exported string that looks like a strkey but does not decode as a valid one."""
    out = []

    def walk(v, col):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, col + "." + k if col else k)
        elif isinstance(v, list):
            for x in v:
                walk(x, col)
        elif isinstance(v, str) and STRKEY.match(v):
            try:
                strkeyx.to_raw(v)
            except ValueError as err:
                out.append({"table": table, "column": col, "stored_hex": v.encode().hex(), "reads_back_as": v,
                            "problem": str(err)})
    for r in rows:
        walk(r, "")
    return out


def run(a):
    with open(a.job) as f:
        job = json.load(f)
    out = os.path.abspath(a.out)
    seq = job["ledger"]["seq"]
    obs = {"observation_version": 1, "adapter": "stellar-etl", "commit": job["commit"], "input": job["input"],
           "entry_id": job["entry_id"], "ledger_seq": seq, "ingested": False, "error": None,
           "adapter_failure": False, "transactions": [], "operations": [], "state_changes": [],
           "balance_movements": [], "unreadable": [], "row_counts": {}}

    def finish():
        with open(os.path.join(out, "observation.json"), "w") as f:
            json.dump(obs, f, indent=1)
        print(json.dumps({"observation": os.path.join(out, "observation.json"), "ingested": obs["ingested"],
                          "error": obs["error"]}))

    if job["input"] != "datalake" or job["network_passphrase"] not in NETWORK_FLAGS:
        obs["adapter_failure"] = True
        obs["error"] = ("stellar-etl reads only the GCS data lake for pubnet, testnet and futurenet; this job is "
                        "input %s on network %r" % (job["input"], job["network_passphrase"]))
        return finish()
    work = job["work_dir"]
    with open(os.path.join(work, "bin", binary_name(job["commit"]) + ".json")) as f:
        info = json.load(f)
    exports = os.path.join(out, "exports")
    sh(["rm", "-rf", exports])
    os.makedirs(exports)
    flags = ["--start-ledger", str(seq), "--end-ledger", str(seq), "--batch-size", "1",
             "--datastore-path", job["datalake"]["bucket_path"], "--retry-limit", "0", "--retry-wait", "1",
             "--num-workers", "1", "--buffer-size", "1"] + NETWORK_FLAGS[job["network_passphrase"]]
    script = "cd /exports\n"
    for cmd, name in EXPORTS:
        script += ("/etl/%s %s %s --output /exports/%s/ > /exports/%s.log 2>&1; echo $? > /exports/%s.exit\n"
                   % (binary_name(job["commit"]), cmd, " ".join("'%s'" % x for x in flags), name, name, name))
    t0 = time.time()
    sh(["docker", "rm", "-f", RUN], check=False)
    timed_out = False
    try:
        p = sh(["docker", "run", "--rm", "--name", RUN, "--network", job["docker_network"], "--memory", "2g",
                "-e", "STORAGE_EMULATOR_HOST=" + GCS_HOST, "-v", os.path.join(work, "bin") + ":/etl:ro",
                "-v", exports + ":/exports", info["go_image"], "sh", "-c", script], check=False,
               timeout=job.get("timeout_seconds", 120) * len(EXPORTS))
    except subprocess.TimeoutExpired:
        timed_out = True
        sh(["docker", "rm", "-f", RUN], check=False)
    obs["seconds"] = round(time.time() - t0, 1)
    if not timed_out and p.returncode != 0:
        obs["adapter_failure"] = True
        obs["error"] = "the container failed: " + (p.stdout or "")[-500:]
        return finish()
    failed = []
    for _cmd, name in EXPORTS:
        code_path = os.path.join(exports, name + ".exit")
        code = open(code_path).read().strip() if os.path.isfile(code_path) else None
        if code != "0":
            log = open(os.path.join(exports, name + ".log")).read() if os.path.isfile(
                os.path.join(exports, name + ".log")) else ""
            fatal = [x for x in log.splitlines() if "level=fatal" in x or "level=error" in x or "panic" in x]
            failed.append("%s exited %s: %s" % (name, code or "(timed out)", (fatal or log.splitlines()[-1:] or [""])[-1][:400]))
    obs["process"] = {"outcome": "timed out" if timed_out else "exited", "exit_code": None if timed_out else 0 if not failed else 1}
    rows = {name: read_lines(os.path.join(exports, name)) for _c, name in EXPORTS}
    obs["row_counts"] = {k: len(v) for k, v in rows.items()}
    if failed:
        obs["error"] = "; ".join(failed)
    else:
        obs["ingested"] = True
    tx_by_id = {}
    for t in rows["transactions"]:
        _l, order, _o = toid_parts(t["id"])
        tx_by_id[order] = t["transaction_hash"]
        obs["transactions"].append({"hash": t["transaction_hash"], "tx_order": order,
                                    "result_code": t.get("transaction_result_code"),
                                    "successful": t.get("successful"), "participants": []})
    for o in rows["operations"]:
        _l, order, op = toid_parts(o["id"])
        obs["operations"].append({"tx_hash": tx_by_id.get(order), "tx_order": order, "op_order": op,
                                  "type": o.get("type_string"), "participants": []})
    for e in rows["effects"]:
        _l, order, op = toid_parts(e["operation_id"])
        d = e.get("details") or {}
        fields = {"op_order": op}
        token = None
        if d.get("asset_type"):
            token = "native" if d["asset_type"] == "native" else "%s:%s" % (d.get("asset_code"), d.get("asset_issuer"))
        if d.get("liquidity_pool_id"):
            fields["liquidity_pool_id"] = d["liquidity_pool_id"]
        for k in ("weight", "name", "trustor", "home_domain", "low_threshold", "med_threshold", "high_threshold"):
            if k in d:
                fields[k] = d[k]
        obs["state_changes"].append({"tx_hash": tx_by_id.get(order), "tx_order": order, "op_order": op,
                                     "category": "EFFECT", "reason": e.get("type_string"),
                                     "account": e.get("address"), "signer_key": d.get("public_key"),
                                     "token": token, "spender": None, "creator": None, "destination": None,
                                     "fields": fields})
    # Token transfer events -> signed balance movements. transfer: from -amount, to +amount; mint: to
    # +amount (the issuer's side is not a balance); burn and clawback: from -amount; fee: from -amount
    # (a refund is a fee event with a negative amount).
    for t in rows["token_transfer"]:
        op = toid_parts(t["operation_id"])[2] if t.get("operation_id") is not None else 0
        amount = int(t["amount_raw"])
        legs = {"transfer": [(t.get("from"), -amount), (t.get("to"), amount)], "mint": [(t.get("to"), amount)],
                "burn": [(t.get("from"), -amount)], "clawback": [(t.get("from"), -amount)],
                "fee": [(t.get("from"), -amount)]}.get(t.get("event_topic"), [])
        for account, delta in legs:
            if account:
                # token_kind: "asset" for a Stellar Asset Contract, "contract" for any other token
                # contract (stellar-etl leaves `asset` empty for those).
                obs["balance_movements"].append({"tx_hash": t["transaction_hash"], "op_order": op, "account": account,
                                                 "token": t.get("contract_id"), "delta": delta,
                                                 "token_kind": "asset" if t.get("asset") else "contract",
                                                 "event": t.get("event_topic")})
    for name, rs in rows.items():
        obs["unreadable"] += unreadable_strings(name, rs)
    finish()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--ref", required=True)
    p.add_argument("--work", required=True)
    p = sub.add_parser("up")
    p.add_argument("--commit", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--network", required=True)
    p = sub.add_parser("run")
    p.add_argument("--job", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("down")
    p.add_argument("--work", required=True)
    a = ap.parse_args()
    {"prepare": prepare, "up": up, "run": run, "down": down}[a.verb](a)


if __name__ == "__main__":
    main()
