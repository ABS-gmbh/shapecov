#!/usr/bin/env python3
"""Replay adapter for stellar/stellar-horizon. Contract: ../../ADAPTER.md

Runs the real, unmodified Horizon at a given ref (a release tag, e.g. v30.0.1):
  prepare  clone, export the commit, `go build` its own main package in the Go image its own
           docker/Dockerfile.dev names (Docker); read the effect type names from the commit's source
  up       PostgreSQL, the major version Horizon's own CI tests against
  run      a fresh database; the commit's own `horizon db migrate up`; then
           `horizon db reingest range <seq> <seq> --ledgerbackend datastore`, reading the one ledger
           from the harness's data lake (Galexie layout on S3, the feeder); then Horizon's history
           tables are read back: transactions, operations, effects and both participants tables
  down     remove the containers

`db reingest range` is how Horizon backfills history from a data lake. It needs no captive core and
no history archive, and it fills the same history tables live ingestion fills. It does not build
Horizon's current-state tables (accounts, offers, ...), which need a checkpoint; those are not read.

Nothing in the Horizon tree is edited and no dependency is changed. Everything third-party runs in
Docker. Python standard library only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import strkeyx  # noqa: E402

REPO_URL = "https://github.com/stellar/stellar-horizon"
DEFAULT_GO_IMAGE = "golang:1.25-bookworm"
DB_IMAGE = "postgres:16"  # the newer of the two versions (12, 16) Horizon's own CI tests against
# REPLAY_PREFIX (default shapecov-replay) names every container, as replay.py does, so that two
# replays can run side by side.
PREFIX = os.environ.get("REPLAY_PREFIX", "shapecov-replay")
DB = PREFIX + "-horizon-db"
RUN = PREFIX + "-horizon"
BUILD = PREFIX + "-horizon-build"
# Go's module and build caches: Docker volumes, or, with REPLAY_GO_CACHE_DIR, two directories under
# it, which CI keeps between runs so that a rebuild takes about a minute instead of nine.
_GO_CACHE_DIR = os.environ.get("REPLAY_GO_CACHE_DIR")
GO_CACHE = ((os.path.join(_GO_CACHE_DIR, "mod"), os.path.join(_GO_CACHE_DIR, "build")) if _GO_CACHE_DIR
            else ("shapecov-replay-gomod", "shapecov-replay-gobuild"))
DB_URL = "postgres://postgres@%s:5432/horizon?sslmode=disable" % DB
# stellar-core's test networks and the local scenarios are on other passphrases; Horizon takes any.
STRKEY = re.compile(r"^[GMCPTXLB][A-Z2-7]{55,}$")


def sh(args, check=True, timeout=None):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s" % (p.returncode, " ".join(args), p.stdout or ""))
    return p


def psql(sql, db="horizon", check=True):
    return sh(["docker", "exec", DB, "psql", "-U", "postgres", "-d", db, "-AtX", "-v", "ON_ERROR_STOP=1",
               "-c", sql], check=check)


def query(sql):
    """Rows of a query as dicts (json_agg, so types and NULLs survive)."""
    out = psql("select coalesce(json_agg(t), '[]') from (%s) t" % sql).stdout.strip()
    return json.loads(out or "[]")


def binary_name(commit):
    return "horizon-" + commit


def effect_names(src):
    """{effect type number: name}, from the commit's own source (history.EffectType constants and
    resourceadapter.EffectTypeNames)."""
    consts = dict(re.findall(r"^\s*(Effect\w+)\s+EffectType\s*=\s*(\d+)",
                             open(os.path.join(src, "internal", "db2", "history", "main.go")).read(), re.M))
    names = re.findall(r"^\s*history\.(Effect\w+):\s*\"(\w+)\"",
                       open(os.path.join(src, "internal", "resourceadapter", "effects.go")).read(), re.M)
    return {int(consts[c]): n for c, n in names if c in consts}


# ---------------------------------------------------------------- prepare

def prepare(a):
    work = os.path.abspath(a.work)
    clone = os.path.join(work, "stellar-horizon")
    bindir = os.path.join(work, "bin")
    os.makedirs(bindir, exist_ok=True)
    if not os.path.isdir(os.path.join(clone, ".git")):
        sh(["git", "clone", "-q", REPO_URL, clone])
    if sh(["git", "-C", clone, "cat-file", "-e", a.ref + "^{commit}"], check=False).returncode != 0:
        sh(["git", "-C", clone, "fetch", "-q", "--tags", "origin"])
    commit = sh(["git", "-C", clone, "rev-parse", a.ref + "^{commit}"]).stdout.strip()
    info_path = os.path.join(bindir, binary_name(commit) + ".json")
    if os.path.isfile(info_path) and os.path.isfile(os.path.join(bindir, binary_name(commit))):
        with open(info_path) as f:
            info = json.load(f)
        info["cached"] = True
        print(json.dumps(info))
        return
    src = os.path.join(work, "src-horizon", commit)
    os.makedirs(src, exist_ok=True)
    tar = subprocess.Popen(["git", "-C", clone, "archive", commit], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", src], stdin=tar.stdout, check=True)
    tar.wait()
    gomod = open(os.path.join(src, "go.mod")).read()
    pins = dict(re.findall(r"^\s*(github\.com/stellar/\S+)\s+(\S+)", gomod, re.M))
    go_image = DEFAULT_GO_IMAGE
    dockerfile = os.path.join(src, "docker", "Dockerfile.dev")
    if os.path.isfile(dockerfile):
        m = re.search(r"^FROM\s+(golang:\S+)", open(dockerfile).read(), re.M)
        if m:
            go_image = m.group(1)
    go_image = os.environ.get("REPLAY_HORIZON_GO_IMAGE", go_image)
    t0 = time.time()
    sh(["docker", "rm", "-f", BUILD], check=False)
    if _GO_CACHE_DIR:
        for d in GO_CACHE:
            os.makedirs(d, exist_ok=True)
    # Network is needed here only: `go mod download` fetches the modules the commit pins.
    build = sh(["docker", "run", "--rm", "--name", BUILD, "-v", src + ":/src:ro", "-v", bindir + ":/out",
                "-v", GO_CACHE[0] + ":/go/pkg/mod", "-v", GO_CACHE[1] + ":/root/.cache/go-build",
                "-w", "/src", "-e", "GOFLAGS=-buildvcs=false -mod=readonly", go_image, "sh", "-c",
                "go version && go mod download && go build -o /out/%s ." % binary_name(commit)], check=False)
    with open(os.path.join(bindir, binary_name(commit) + ".build.log"), "w") as f:
        f.write(build.stdout or "")
    if build.returncode != 0:
        raise RuntimeError("build failed, see %s" % f.name)
    info = {"adapter": "horizon", "ref": a.ref, "commit": commit,
            "commit_date": sh(["git", "-C", clone, "show", "-s", "--format=%cI", commit]).stdout.strip(),
            "subject": sh(["git", "-C", clone, "show", "-s", "--format=%s", commit]).stdout.strip(),
            "source_modified": False, "dependency_pins": pins, "dependencies_modified": False,
            "inputs": ["datalake"], "go_image": go_image, "db_image": DB_IMAGE,
            "go_version": (build.stdout or "").splitlines()[0] if build.stdout else "",
            "effect_types": effect_names(src), "build_seconds": round(time.time() - t0, 1), "cached": False}
    with open(info_path, "w") as f:
        json.dump(info, f, indent=1)
    print(json.dumps(info))


def load_info(work, commit):
    with open(os.path.join(os.path.abspath(work), "bin", binary_name(commit) + ".json")) as f:
        return json.load(f)


# ---------------------------------------------------------------- up / down

def up(a):
    sh(["docker", "rm", "-f", DB, RUN], check=False)
    sh(["docker", "run", "-d", "--name", DB, "--network", a.network, "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
        "--tmpfs", "/var/lib/postgresql/data", DB_IMAGE])
    ok = 0
    for _ in range(120):
        r = sh(["docker", "exec", DB, "psql", "-U", "postgres", "-AtXc", "select 1"], check=False)
        ok = ok + 1 if r.returncode == 0 else 0
        if ok >= 3:  # the image restarts postgres once while initialising
            print(json.dumps({"services": [DB], "db_image": DB_IMAGE,
                              "db_version": psql("select version()", "postgres").stdout.strip()}))
            return
        time.sleep(0.5)
    raise RuntimeError("postgres did not start")


def down(a):
    sh(["docker", "rm", "-f", DB, RUN], check=False)
    print(json.dumps({}))


# ---------------------------------------------------------------- run

OP_TYPES = None


def op_type_names():
    """OperationType numbers -> Horizon's operation type names (snake case of the XDR enum)."""
    global OP_TYPES
    if OP_TYPES is None:
        schema = json.load(open(os.path.join(HERE, "..", "..", "..", "..", "schema", "schema.json")))
        members = schema["types"]["OperationType"]["members"]
        OP_TYPES = {int(v): n.lower() for n, v in members}
    return OP_TYPES


def toid_parts(i):
    i = int(i)
    return i >> 32, (i >> 12) & 0xFFFFF, i & 0xFFF


def unreadable_strings(table, rows):
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


def read_back(obs, seq, info, out):
    lo, hi = seq << 32, (seq + 1) << 32
    txs = query("select id, transaction_hash, application_order, successful, account, fee_account, "
                "account_muxed, fee_account_muxed, fee_charged, operation_count "
                "from history_transactions where ledger_sequence = %d order by id" % seq)
    ops = query("select id, transaction_id, application_order, type, source_account, source_account_muxed, details "
                "from history_operations where id >= %d and id < %d order by id" % (lo, hi))
    effs = query("select e.history_operation_id as op_id, e.\"order\", e.type, a.address, e.address_muxed, e.details "
                 "from history_effects e join history_accounts a on a.id = e.history_account_id "
                 "where e.history_operation_id >= %d and e.history_operation_id < %d "
                 "order by e.history_operation_id, e.\"order\"" % (lo, hi))
    tparts = query("select p.history_transaction_id as tx_id, a.address from history_transaction_participants p "
                   "join history_accounts a on a.id = p.history_account_id "
                   "where p.history_transaction_id >= %d and p.history_transaction_id < %d" % (lo, hi))
    oparts = query("select p.history_operation_id as op_id, a.address from history_operation_participants p "
                   "join history_accounts a on a.id = p.history_account_id "
                   "where p.history_operation_id >= %d and p.history_operation_id < %d" % (lo, hi))
    with open(os.path.join(out, "tables.json"), "w") as f:
        json.dump({"history_transactions": txs, "history_operations": ops, "history_effects": effs,
                   "history_transaction_participants": tparts, "history_operation_participants": oparts}, f, indent=1)
    names = {int(k): v for k, v in info.get("effect_types", {}).items()}
    tx_hash = {}
    for t in txs:
        _, order, _ = toid_parts(t["id"])
        tx_hash[order] = t["transaction_hash"]
        obs["transactions"].append({"hash": t["transaction_hash"], "tx_order": order,
                                    "successful": t["successful"], "result_code": None,
                                    "participants": sorted({p["address"] for p in tparts if p["tx_id"] == t["id"]})})
    for o in ops:
        _, order, op = toid_parts(o["id"])
        obs["operations"].append({"tx_hash": tx_hash.get(order), "tx_order": order, "op_order": op,
                                  "type": op_type_names().get(o["type"], str(o["type"])),
                                  "participants": sorted({p["address"] for p in oparts if p["op_id"] == o["id"]})})
    for e in effs:
        _, order, op = toid_parts(e["op_id"])
        d = e["details"] or {}
        # The same reading of an effect's details as the stellar-etl adapter's: stellar-etl's effects
        # export is a copy of Horizon's effects processor, with the same detail keys.
        fields = {"op_order": op}
        token = None
        if d.get("asset_type") and d["asset_type"] != "liquidity_pool":
            token = "native" if d["asset_type"] == "native" else "%s:%s" % (d.get("asset_code"), d.get("asset_issuer"))
        elif isinstance(d.get("asset"), str):
            token = d["asset"]
        if d.get("liquidity_pool_id"):
            fields["liquidity_pool_id"] = d["liquidity_pool_id"]
        elif isinstance(d.get("liquidity_pool"), dict) and d["liquidity_pool"].get("id"):
            fields["liquidity_pool_id"] = d["liquidity_pool"]["id"]
        for k in ("weight", "name", "data_name", "trustor", "offer_id", "balance_id", "home_domain",
                  "low_threshold", "med_threshold", "high_threshold"):
            if k in d:
                fields[k] = d[k]
        if e["address_muxed"]:
            fields["address_muxed"] = e["address_muxed"]
        obs["state_changes"].append({"tx_hash": tx_hash.get(order), "tx_order": order, "op_order": op,
                                     "category": "EFFECT", "reason": names.get(e["type"], "type_%d" % e["type"]),
                                     "account": e["address"], "signer_key": d.get("public_key") or d.get("signer"),
                                     "token": token, "spender": None, "creator": None, "destination": None,
                                     "fields": fields})
    obs["unreadable"] = (unreadable_strings("history_operations", ops) + unreadable_strings("history_effects", effs)
                         + unreadable_strings("history_transactions", txs))
    obs["row_counts"] = {"history_transactions": len(txs), "history_operations": len(ops),
                         "history_effects": len(effs), "history_transaction_participants": len(tparts),
                         "history_operation_participants": len(oparts)}


def run(a):
    with open(a.job) as f:
        job = json.load(f)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    seq = job["ledger"]["seq"]
    t0 = time.time()
    obs = {"observation_version": 1, "adapter": "horizon", "commit": job["commit"], "input": job["input"],
           "entry_id": job["entry_id"], "ledger_seq": seq, "ingested": False, "error": None,
           "adapter_failure": False, "transactions": [], "operations": [], "state_changes": [],
           "unreadable": [], "row_counts": {}}

    def finish():
        obs["seconds_to_outcome"] = round(time.time() - t0, 1)
        with open(os.path.join(out, "observation.json"), "w") as f:
            json.dump(obs, f, indent=1)
        print(json.dumps({"observation": os.path.join(out, "observation.json"), "ingested": obs["ingested"],
                          "error": obs["error"]}))

    if job["input"] != "datalake":
        obs["adapter_failure"], obs["error"] = True, "Horizon's adapter reads only the data lake"
        return finish()
    work = job["work_dir"]
    info = load_info(work, job["commit"])
    binary = "/hz/" + binary_name(job["commit"])
    psql("drop database if exists horizon with (force)", "postgres")
    psql("create database horizon", "postgres")
    cfg_dir = os.path.join(out, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    dl = job["datalake"]
    with open(os.path.join(cfg_dir, "datastore.toml"), "w") as f:
        f.write('[datastore_config]\ntype = "S3"\n\n[datastore_config.params]\n'
                'destination_bucket_path = "%s"\nregion = "%s"\nendpoint_url = "%s"\n\n'
                '[datastore_config.schema]\nledgers_per_file = 1\nfiles_per_partition = 64000\n\n'
                '[buffered_storage_backend_config]\nbuffer_size = 2\nnum_workers = 1\nretry_limit = 2\n'
                'retry_wait = "1s"\n' % (dl["bucket_path"], dl["region"], dl["s3_endpoint"]))
    base = ["docker", "run", "--rm", "--name", RUN, "--network", job["docker_network"],
            "--memory", job.get("memory_limit", "2g"), "-v", os.path.join(os.path.abspath(work), "bin") + ":/hz:ro",
            "-v", cfg_dir + ":/cfg:ro", "-e", "DATABASE_URL=" + DB_URL,
            "-e", "NETWORK_PASSPHRASE=" + job["network_passphrase"],
            "-e", "HISTORY_ARCHIVE_URLS=" + job["history_archive"]["url"],
            # The S3 client wants credentials to exist; the feeder ignores them.
            "-e", "AWS_ACCESS_KEY_ID=shapecov", "-e", "AWS_SECRET_ACCESS_KEY=shapecov",
            "-e", "AWS_EC2_METADATA_DISABLED=true", info["go_image"], binary]
    mig = sh(base[:-2] + [info["go_image"], binary, "db", "migrate", "up"], check=False,
             timeout=job.get("timeout_seconds", 120))
    with open(os.path.join(out, "migrate.log"), "w") as f:
        f.write(mig.stdout or "")
    if mig.returncode != 0:
        obs["adapter_failure"], obs["error"] = True, "horizon db migrate up failed (exit %d)" % mig.returncode
        return finish()
    cmd = ["db", "reingest", "range", str(seq), str(seq), "--ledgerbackend", "datastore",
           "--datastore-config", "/cfg/datastore.toml", "--parallel-workers", "1", "--retries", "0"]
    obs["command"] = "horizon " + " ".join(cmd)
    try:
        ing = sh(base + cmd, check=False, timeout=job.get("timeout_seconds", 120))
        code, log = ing.returncode, ing.stdout or ""
    except subprocess.TimeoutExpired as e:
        sh(["docker", "rm", "-f", RUN], check=False)
        code, log = None, (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
    with open(os.path.join(out, "ingest.log"), "w") as f:
        f.write(log)
    obs["exit_code"] = code
    stored = psql("select count(*) from history_ledgers where sequence = %d" % seq, check=False).stdout.strip()
    obs["ingested"] = code == 0 and stored == "1"
    if not obs["ingested"]:
        errs = [x for x in log.splitlines() if "level=error" in x or "error" in x.lower()]
        obs["error"] = (errs[-1] if errs else "exit %s, history_ledgers rows for %d: %s" % (code, seq, stored))[-600:]
    read_back(obs, seq, info, out)
    finish()


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("--ref", required=True)
    s.add_argument("--work", required=True)
    s = sub.add_parser("up")
    s.add_argument("--commit", required=True)
    s.add_argument("--work", required=True)
    s.add_argument("--network", required=True)
    s = sub.add_parser("run")
    s.add_argument("--job", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("down")
    s.add_argument("--work", required=True)
    a = p.parse_args()
    {"prepare": prepare, "up": up, "run": run, "down": down}[a.verb](a)


if __name__ == "__main__":
    main()
