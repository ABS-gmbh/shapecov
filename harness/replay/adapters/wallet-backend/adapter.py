#!/usr/bin/env python3
"""Reference replay adapter for stellar/wallet-backend. Contract: ../../ADAPTER.md

Runs the real, unmodified indexer at a given commit:
  prepare  clone, export the commit, `go build` its own main package (Docker, golang image)
  up       start the TimescaleDB image the commit's own docker-compose.yaml names
  run      fresh database -> the commit's own `migrate up` -> the commit's own `ingest`
           (live mode) fed by the mock RPC or the data lake -> read the tables back
  down     remove the containers

Nothing in the wallet-backend tree is edited and no dependency is changed.
The one thing the adapter writes into the database itself is the ingest
cursor (two rows in ingest_store set to ledger-1), which positions the indexer
directly before the entry's ledger; see README.md "How the indexer is positioned".

Everything third-party runs in Docker. Python standard library only.
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

REPO_URL = "https://github.com/stellar/wallet-backend"
GO_IMAGE = os.environ.get("REPLAY_GO_IMAGE", "golang:1.26")
DEFAULT_DB_IMAGE = "timescale/timescaledb:2.28.2-pg17"
PREFIX = os.environ.get("REPLAY_PREFIX", "shapecov-replay")  # set by replay.py's environment
DB = PREFIX + "-db"
INGEST = PREFIX + "-ingest"
MIGRATE = PREFIX + "-migrate"
BUILD = PREFIX + "-build"
DB_URL = "postgres://postgres@%s:5432/replay?sslmode=disable" % DB
ADDRESS_COLUMNS = ("account_id", "token_id", "signer_account_id", "spender_account_id",
                   "creator_account_id", "destination_account_id")
KNOWN_NETWORKS = {"Test SDF Network ; September 2015": "testnet",
                  "Public Global Stellar Network ; September 2015": "mainnet"}


def sh(args, check=True, capture=True, timeout=None, **kw):
    p = subprocess.run(args, stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None, text=True, timeout=timeout, **kw)
    if check and p.returncode != 0:
        raise RuntimeError("command failed (%d): %s\n%s" % (p.returncode, " ".join(args), p.stdout or ""))
    return p


def psql(sql, db="replay", check=True):
    return sh(["docker", "exec", DB, "psql", "-U", "postgres", "-d", db, "-AtX", "-v", "ON_ERROR_STOP=1",
               "-c", sql], check=check)


def binary_name(commit):
    return "wallet-backend-" + commit


# ---------------------------------------------------------------- prepare

def prepare(a):
    work = os.path.abspath(a.work)
    clone = os.path.join(work, "wallet-backend")
    os.makedirs(os.path.join(work, "bin"), exist_ok=True)
    if not os.path.isdir(os.path.join(clone, ".git")):
        sh(["git", "clone", "-q", REPO_URL, clone])
    if sh(["git", "-C", clone, "cat-file", "-e", a.ref + "^{commit}"], check=False).returncode != 0:
        sh(["git", "-C", clone, "fetch", "-q", "origin"])
    commit = sh(["git", "-C", clone, "rev-parse", a.ref + "^{commit}"]).stdout.strip()
    info_path = os.path.join(work, "bin", binary_name(commit) + ".json")
    if os.path.isfile(info_path) and os.path.isfile(os.path.join(work, "bin", binary_name(commit))):
        with open(info_path) as f:
            info = json.load(f)
        info["cached"] = True
        print(json.dumps(info))
        return
    src = os.path.join(work, "src", commit)
    os.makedirs(src, exist_ok=True)
    tar = subprocess.Popen(["git", "-C", clone, "archive", commit], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", src], stdin=tar.stdout, check=True)
    tar.wait()
    gomod = open(os.path.join(src, "go.mod")).read()
    pins = dict(re.findall(r"^\s*(github\.com/stellar/\S+)\s+(\S+)", gomod, re.M))
    db_image = DEFAULT_DB_IMAGE
    compose = os.path.join(src, "docker-compose.yaml")
    if os.path.isfile(compose):
        m = re.search(r"image:\s*(timescale/\S+)", open(compose).read())
        if m:
            db_image = m.group(1)
    t0 = time.time()
    sh(["docker", "rm", "-f", BUILD], check=False)
    # Network is needed here only: `go mod download` fetches the modules the commit pins.
    build = sh(["docker", "run", "--rm", "--name", BUILD, "-v", src + ":/src:ro", "-v", os.path.join(work, "bin") + ":/out",
                "-v", "shapecov-replay-gomod:/go/pkg/mod", "-v", "shapecov-replay-gobuild:/root/.cache/go-build",
                "-w", "/src", "-e", "GOFLAGS=-buildvcs=false -mod=readonly", "-e", "CGO_ENABLED=0", GO_IMAGE, "sh", "-c",
                "go version && go mod download && go build -o /out/%s -ldflags '-X main.GitCommit=%s' ."
                % (binary_name(commit), commit)], check=False)
    with open(os.path.join(work, "bin", binary_name(commit) + ".build.log"), "w") as f:
        f.write(build.stdout or "")
    if build.returncode != 0:
        raise RuntimeError("build failed, see %s" % f.name)
    if sh(["docker", "image", "inspect", db_image], check=False).returncode != 0:
        sh(["docker", "pull", "-q", db_image])
    info = {"adapter": "wallet-backend", "ref": a.ref, "commit": commit,
            "commit_date": sh(["git", "-C", clone, "show", "-s", "--format=%cI", commit]).stdout.strip(),
            "subject": sh(["git", "-C", clone, "show", "-s", "--format=%s", commit]).stdout.strip(),
            "source_modified": False, "dependency_pins": pins, "dependencies_modified": False,
            "go_image": GO_IMAGE, "go_version": (build.stdout or "").splitlines()[0] if build.stdout else "",
            "db_image": db_image, "build_seconds": round(time.time() - t0, 1), "cached": False}
    with open(info_path, "w") as f:
        json.dump(info, f, indent=1)
    print(json.dumps(info))


def load_info(work, commit):
    with open(os.path.join(work, "bin", binary_name(commit) + ".json")) as f:
        return json.load(f)


# ---------------------------------------------------------------- up / down

def up(a):
    info = load_info(os.path.abspath(a.work), a.commit)
    sh(["docker", "rm", "-f", DB, INGEST, MIGRATE], check=False)
    sh(["docker", "run", "-d", "--name", DB, "--network", a.network, "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
        "--tmpfs", "/var/lib/postgresql/data", info["db_image"], "postgres",
        "-c", "timescaledb.enable_chunk_skipping=on", "-c", "timescaledb.enable_sparse_index_bloom=on",
        "-c", "timescaledb.telemetry_level=off", "-c", "fsync=off"])
    ok = 0
    for _ in range(120):
        r = sh(["docker", "exec", DB, "psql", "-U", "postgres", "-AtXc", "select 1"], check=False)
        ok = ok + 1 if r.returncode == 0 else 0
        if ok >= 3:  # the image restarts postgres once while initialising
            print(json.dumps({"db_image": info["db_image"],
                              "db_version": psql("select version()", "postgres").stdout.strip()}))
            return
        time.sleep(0.5)
    raise RuntimeError("database did not become ready")


def down(a):
    sh(["docker", "rm", "-f", DB, INGEST, MIGRATE, BUILD], check=False)
    print("{}")


# ---------------------------------------------------------------- run

def toid(n):
    n = int(n)
    return {"ledger": n >> 32, "tx_order": (n >> 12) & 0xFFFFF, "op_order": n & 0xFFF}


def rows(table, where):
    out = psql("select coalesce(json_agg(to_jsonb(t)), '[]'::json) from (select * from %s where %s) t" % (table, where),
               check=False)
    if out.returncode != 0:
        return None
    return json.loads(out.stdout)


def address(value, table, column, unreadable):
    """Stored BYTEA (version byte + payload) -> SEP-23 strkey, noting values that do not read back."""
    if value is None:
        return None
    raw = bytes.fromhex(value[2:]) if value.startswith("\\x") else value.encode()
    text, problem = strkeyx.describe_stored(raw)
    if problem:
        unreadable.append({"table": table, "column": column, "stored_hex": raw.hex(),
                           "reads_back_as": text, "problem": problem})
    return {"strkey": text, "stored_hex": raw.hex(), "valid": problem is None}


def read_back(seq):
    lo, hi = seq << 32, (seq + 1) << 32
    unreadable = []
    obs = {"transactions": [], "operations": [], "state_changes": []}
    txs = rows("transactions", "ledger_number = %d order by to_id" % seq) or []
    tx_acc = rows("transactions_accounts", "tx_to_id >= %d and tx_to_id < %d" % (lo, hi)) or []
    ops = rows("operations", "id >= %d and id < %d order by id" % (lo, hi)) or []
    op_acc = rows("operations_accounts", "operation_id >= %d and operation_id < %d" % (lo, hi)) or []
    scs = rows("state_changes", "ledger_number = %d order by to_id, operation_id, state_change_id" % seq) or []
    hash_by_toid = {}
    for t in txs:
        h = t["hash"][2:] if isinstance(t.get("hash"), str) and t["hash"].startswith("\\x") else t.get("hash")
        hash_by_toid[int(t["to_id"])] = h
        parts = [address(x["account_id"], "transactions_accounts", "account_id", unreadable)
                 for x in tx_acc if int(x["tx_to_id"]) == int(t["to_id"])]
        obs["transactions"].append({"hash": h, "tx_order": toid(t["to_id"])["tx_order"],
                                    "result_code": t.get("result_code"),
                                    "participants": sorted(p["strkey"] for p in parts if p)})
    for o in ops:
        parts = [address(x["account_id"], "operations_accounts", "account_id", unreadable)
                 for x in op_acc if int(x["operation_id"]) == int(o["id"])]
        t = toid(o["id"])
        obs["operations"].append({"tx_hash": hash_by_toid.get(int(o["id"]) & ~0xFFF), "tx_order": t["tx_order"],
                                  "op_order": t["op_order"], "type": o.get("operation_type"),
                                  "participants": sorted(p["strkey"] for p in parts if p)})
    for s in scs:
        row = {"tx_hash": hash_by_toid.get(int(s["to_id"])), "tx_order": toid(s["to_id"])["tx_order"],
               "op_order": toid(s["operation_id"])["op_order"] if int(s["operation_id"]) else 0,
               "category": s.get("state_change_category"), "reason": s.get("state_change_reason"), "stored": {}}
        for col in ADDRESS_COLUMNS:
            v = address(s.get(col), "state_changes", col, unreadable)
            name = {"account_id": "account", "token_id": "token", "signer_account_id": "signer_key",
                    "spender_account_id": "spender", "creator_account_id": "creator",
                    "destination_account_id": "destination"}[col]
            row[name] = v["strkey"] if v else None
            if v:
                row["stored"][name] = v["stored_hex"]
        for col, v in s.items():
            if col in ADDRESS_COLUMNS or col in ("to_id", "operation_id", "state_change_id", "state_change_category",
                                                 "state_change_reason", "ingested_at", "ledger_number",
                                                 "ledger_created_at"):
                continue
            if v is not None:
                row.setdefault("fields", {})[col] = v
        obs["state_changes"].append(row)
    nb = rows("native_balances", "true")
    if nb is not None:  # the current-state table of XLM balances (since January 2026)
        obs["native_balances"] = [{"account": (address(r["account_id"], "native_balances", "account_id", unreadable) or {}).get("strkey"),
                                   "balance": int(r["balance"])} for r in nb]
    obs["unreadable"] = unreadable
    obs["row_counts"] = {"transactions": len(txs), "transactions_accounts": len(tx_acc), "operations": len(ops),
                         "operations_accounts": len(op_acc), "state_changes": len(scs)}
    return obs


def read_end_state():
    """The current-state tables after a sequence of ledgers. None for a table the commit lacks."""
    unreadable = []
    tl = rows("trustline_balances b join trustline_assets a on a.id = b.asset_id", "true")
    out = {"trustlines": None if tl is None else [
        {"account": (address(r["account_id"], "trustline_balances", "account_id", unreadable) or {}).get("strkey"),
         "code": r["code"], "issuer": r["issuer"], "balance": int(r["balance"]), "limit": int(r["trust_limit"])}
        for r in tl]}
    # Protocol classification and Blend pools, when the commit has those tables (read as text).
    for table, cols in (("protocol_wasms", "encode(wasm_hash, 'hex') as wasm_hash, protocol_id"),
                        ("protocol_contracts", "contract_id, encode(wasm_hash, 'hex') as wasm_hash, name"),
                        ("blend_pools", "*")):
        r = psql("select coalesce(json_agg(to_jsonb(t)), '[]'::json) from (select %s from %s) t" % (cols, table), check=False)
        out[table] = json.loads(r.stdout) if r.returncode == 0 else None
    out["unreadable"] = unreadable
    return out


def release(job, last):
    """Let the feeder serve the job's sequence up to ledger `last` (feeder.py, /__release)."""
    sh(["docker", "exec", job["feeder_container"], "python3", "-c",
        "import urllib.request; urllib.request.urlopen(urllib.request.Request("
        "'http://127.0.0.1:8000/__release?name=%s&last=%d', method='POST'))" % (job["sequence"]["id"], last)])


def psql_detached(sql):
    """Run SQL in its own session in the background (the database container's psql)."""
    sh(["docker", "exec", "-d", DB, "psql", "-U", "postgres", "-d", "replay", "-c", sql])


def wait_cursor(seq, deadline):
    while time.time() < deadline:
        cur = cursor()
        if cur is not None and cur >= seq:
            return True
        if sh(["docker", "inspect", "-f", "{{.State.Running}}", INGEST], check=False).stdout.strip() != "true":
            return False
        time.sleep(0.2)
    return False


def cursor():
    r = psql("select value from ingest_store where key = 'latest_ingest_ledger'", check=False)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return None


def run(a):
    with open(a.job) as f:
        job = json.load(f)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    work = os.path.abspath(job["work_dir"])
    commit, seq = job["commit"], job["ledger"]["seq"]
    # A sequence (replay.py run --sequence) is ingested in one run: from before its first ledger
    # to its last, which job["ledger"] names.
    members = (job.get("sequence") or {}).get("ledgers") or [{"entry_id": job["entry_id"], "seq": seq}]
    first = members[0]["seq"]
    binary = "/wb/" + binary_name(commit)
    obs = {"observation_version": 1, "adapter": "wallet-backend", "commit": commit, "input": job["input"],
           "entry_id": job["entry_id"], "ledger_seq": seq, "ingested": False, "error": None}
    t0 = time.time()
    sh(["docker", "rm", "-f", INGEST, MIGRATE], check=False)
    psql("drop database if exists replay with (force)", "postgres")
    psql("create database replay", "postgres")
    mig = sh(["docker", "run", "--rm", "--name", MIGRATE, "--network", job["docker_network"],
              "-v", os.path.join(work, "bin") + ":/wb:ro", "-e", "DATABASE_URL=" + DB_URL, GO_IMAGE,
              binary, "migrate", "up"], check=False)
    with open(os.path.join(out, "migrate.log"), "w") as f:
        f.write(mig.stdout or "")
    if mig.returncode != 0:
        obs["error"] = "adapter: the commit's own `migrate up` failed, see migrate.log"
        obs["adapter_failure"] = True
        return finish(obs, out, t0)
    # Position the indexer directly before the entry's ledger (a sequence's first).
    psql("insert into ingest_store (key, value) values ('latest_ingest_ledger', '%d'), ('oldest_ingest_ledger', '%d')"
         % (first - 1, first - 1))
    protocols = job.get("protocols") or []
    if protocols:
        # Protocol production (SEP-41, Blend) the way an operator turns it on: the commit's own
        # protocol-setup, then the protocol cursors where protocol-migrate leaves them once it has
        # migrated up to the ledger before the replay.
        setup = sh(["docker", "run", "--rm", "--name", MIGRATE, "--network", job["docker_network"],
                    "-v", os.path.join(work, "bin") + ":/wb:ro", "-e", "DATABASE_URL=" + DB_URL,
                    "-e", "RPC_URL=" + job["rpc"]["url"], "-e", "NETWORK_PASSPHRASE=" + job["network_passphrase"],
                    GO_IMAGE, binary, "protocol-setup"] + sum((["--protocol-id", p] for p in protocols), []), check=False)
        with open(os.path.join(out, "protocol-setup.log"), "w") as f:
            f.write(setup.stdout or "")
        if setup.returncode != 0:
            obs["error"] = "adapter: the commit's own `protocol-setup` failed, see protocol-setup.log"
            obs["adapter_failure"] = True
            return finish(obs, out, t0)
        # Both cursors by default; a job may set only some (e.g. history production alone).
        kinds = job.get("protocol_cursors") or ["history", "current_state"]
        psql("insert into ingest_store (key, value) values %s" % ", ".join(
            "('protocol_%s_%s_cursor', '%d')" % (p, k, first - 1) for p in protocols for k in kinds))
        obs["protocol_cursors"] = kinds
        obs["protocols"] = protocols
    env = {"DATABASE_URL": DB_URL, "NETWORK_PASSPHRASE": job["network_passphrase"],
           "NETWORK": KNOWN_NETWORKS.get(job["network_passphrase"], "standalone"),
           "INGESTION_MODE": "live", "LOG_LEVEL": "INFO", "STELLAR_ENVIRONMENT": "development", "GET_LEDGERS_LIMIT": "10",
           "RPC_URL": job["rpc"]["url"], "ARCHIVE_URL": job["history_archive"]["url"],
           "LEDGER_BACKEND_TYPE": {"rpc": "rpc", "datalake": "datastore"}[job["input"]],
           "DATASTORE_BUCKET_PATH": job["datalake"]["bucket_path"], "DATASTORE_REGION": job["datalake"]["region"],
           "DATASTORE_ENDPOINT_URL": job["datalake"]["s3_endpoint"],
           "DATASTORE_BUFFER_SIZE": "4", "DATASTORE_NUM_WORKERS": "2",
           # A sequence may ask for several ledgers per persist commit (--live-persist-max-batch-size).
           **({"LIVE_PERSIST_MAX_BATCH_SIZE": str(job["live_persist_max_batch_size"])}
              if job.get("live_persist_max_batch_size") else {}),
           # The S3 client wants credentials to exist; the local store ignores them.
           "AWS_ACCESS_KEY_ID": "shapecov", "AWS_SECRET_ACCESS_KEY": "shapecov", "AWS_EC2_METADATA_DISABLED": "true"}
    cmd = ["docker", "run", "-d", "--name", INGEST, "--network", job["docker_network"],
           "--memory", job.get("memory_limit", "2g"), "-v", os.path.join(work, "bin") + ":/wb:ro"]
    for k, v in env.items():
        cmd += ["-e", "%s=%s" % (k, v)]
    cmd += [GO_IMAGE, binary, "ingest"]
    obs["command"] = "wallet-backend ingest  (configured by environment: %s)" % ", ".join(
        "%s=%s" % (k, v) for k, v in sorted(env.items()) if not k.startswith("AWS_"))
    groups = job.get("commits") or []  # ledger groups a sequence wants committed apart, as lists of seqs
    if groups:
        release(job, groups[0][-1])
    sh(cmd)
    deadline = time.time() + job.get("timeout_seconds", 120)
    if len(groups) > 2:
        # Make each later group one persist commit: hold ingest_store locked so the commit of group i
        # stays open while group i+1 is fetched and processed; when the lock ends, group i commits and
        # group i+1, already queued, drains into the next batch (up to --live-persist-max-batch-size).
        obs["commit_groups"] = groups
        wait_cursor(groups[0][-1], deadline)
        for i in range(1, len(groups) - 1):
            psql_detached("BEGIN; LOCK TABLE ingest_store IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(6); COMMIT;")
            time.sleep(1)
            release(job, groups[i][-1])
            time.sleep(2)
            release(job, groups[i + 1][-1])
            wait_cursor(groups[i + 1][-1], deadline)
    elif groups:
        release(job, groups[-1][-1])
    state, cur = "timeout", None
    while time.time() < deadline:
        cur = cursor()
        if cur is not None and cur >= seq:
            state = "ingested"
            break
        st = sh(["docker", "inspect", "-f", "{{.State.Running}}", INGEST], check=False).stdout.strip()
        if st != "true":
            state = "exited"
            break
        time.sleep(0.3)
    obs["seconds_to_outcome"] = round(time.time() - t0, 1)
    if state == "ingested":
        time.sleep(0.5)  # let the indexer ask for the next ledger, to see it idles and does not fail
    sh(["docker", "stop", "-t", "15", INGEST], check=False)
    code = sh(["docker", "inspect", "-f", "{{.State.ExitCode}} {{.State.OOMKilled}}", INGEST], check=False).stdout.split()
    log = sh(["docker", "logs", INGEST], check=False).stdout or ""
    with open(os.path.join(out, "ingest.log"), "w") as f:
        f.write(log)
    stats = sh(["docker", "inspect", "-f", "{{.State.StartedAt}} {{.State.FinishedAt}}", INGEST], check=False).stdout.strip()
    sh(["docker", "rm", "-f", INGEST], check=False)
    cur = cursor()
    obs["cursor"] = cur
    obs["ingested"] = cur is not None and cur >= seq
    obs["process"] = {"outcome": {"ingested": "stopped by the adapter after the ledger was ingested",
                                  "exited": "exited by itself before the ledger was ingested",
                                  "timeout": "still running at the timeout, ledger not ingested"}[state],
                      "exit_code": int(code[0]) if code and code[0].lstrip("-").isdigit() else None,
                      "oom_killed": len(code) > 1 and code[1] == "true", "started_finished": stats}
    errors = [ln for ln in log.splitlines() if re.search(r"level=(error|fatal|panic)|^Error:|^panic:|\bFATA\b", ln)]
    warns = [ln for ln in log.splitlines() if "level=warning" in ln]
    obs["log_errors"] = errors[-5:]
    obs["log_warnings"] = len(warns)
    if not obs["ingested"]:
        if errors:
            obs["error"] = errors[-1][:2000]
        elif state == "exited":
            obs["error"] = "process exited with code %s before ingesting the ledger; last log line: %s" % (
                code[0] if code else "?", (log.strip().splitlines() or [""])[-1][:1000])
        elif warns:
            obs["error"] = "not ingested within %ds; the indexer kept retrying: %s" % (
                job.get("timeout_seconds", 120), warns[-1][:1000])
    if job.get("sequence"):
        obs["ledgers"] = {m["entry_id"]: dict(read_back(m["seq"]), ingested=cur is not None and cur >= m["seq"])
                          for m in members}
        obs["end_state"] = read_end_state()
    else:
        obs.update(read_back(seq))
    return finish(obs, out, t0)


def finish(obs, out, t0):
    obs["seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(out, "observation.json"), "w") as f:
        json.dump(obs, f, indent=1)
    print(json.dumps({"observation": os.path.join(out, "observation.json"), "ingested": obs["ingested"],
                      "error": obs["error"]}))


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
    try:
        main()
    except RuntimeError as err:
        print("adapter error: %s" % err, file=sys.stderr)
        sys.exit(1)
