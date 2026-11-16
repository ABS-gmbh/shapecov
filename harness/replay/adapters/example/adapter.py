#!/usr/bin/env python3
"""Replay adapter for the toy indexer in toy.py: the adapter interface by example. Contract: ../../ADAPTER.md

  prepare  --ref envelope|meta   the "commit" is the variant: a digest of the variant and toy.py
  up                             nothing: the toy keeps its state in one SQLite file per run
  run      --job JOB --out DIR   run toy.py in the pinned Python image on the harness's network,
                                 then read its SQLite file back into observation.json
  down                           nothing to remove (each run's container is --rm)

  python3 harness/replay/replay.py run --adapter example --refs envelope,meta --inputs rpc \\
          --entries localcore-preauth-failed-6,testnet-4437357-signed-payload-signer --out harness/replay/out-example

The toy reads only the mock stellar-rpc, so the commit record says `inputs: ["rpc"]`.
"""
import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
IMAGE = "python:3.14-slim"
VARIANTS = {"envelope": "toy indexer: participants from the envelope",
            "meta": "toy indexer: participants from the meta"}


def emit(obj):
    print(json.dumps(obj))


def toy_digest(variant):
    with open(os.path.join(HERE, "toy.py"), "rb") as f:
        return hashlib.sha1(variant.encode() + b"\0" + f.read()).hexdigest()


def prepare(a):
    if a.ref not in VARIANTS:
        sys.exit("ref must be one of %s" % ", ".join(VARIANTS))
    # The harness orders commits by commit_date, which must be ISO 8601: toy.py's last commit, or
    # its modification time before it is committed.
    date = subprocess.run(["git", "-C", REPO, "log", "-1", "--format=%cI", "--", os.path.join(HERE, "toy.py")],
                          capture_output=True, text=True).stdout.strip()
    if not date:
        date = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(HERE, "toy.py")),
                                               datetime.timezone.utc).isoformat(timespec="seconds")
    emit({"adapter": "example", "ref": a.ref, "commit": toy_digest(a.ref), "commit_date": date,
          "subject": VARIANTS[a.ref], "source_modified": False, "dependency_pins": {},
          "dependencies_modified": False, "inputs": ["rpc"], "variant": a.ref})


def run(a):
    job = json.load(open(a.job))
    variant = next(v for v in VARIANTS if toy_digest(v) == job["commit"])
    out = os.path.abspath(a.out)
    db = os.path.join(out, "toy.sqlite")
    if os.path.exists(db):
        os.remove(db)
    p = subprocess.run(["docker", "run", "--rm", "--name", "shapecov-replay-example", "--network", job["docker_network"],
                        "--memory", "512m", "-v", REPO + ":/repo:ro", "-v", out + ":/out", IMAGE,
                        "python3", "/repo/harness/replay/adapters/example/toy.py", "--variant", variant,
                        "--rpc", job["rpc"]["url"], "--seq", str(job["ledger"]["seq"]),
                        "--passphrase", job["network_passphrase"], "--db", "/out/toy.sqlite"],
                       capture_output=True, text=True, timeout=job.get("timeout_seconds", 120))
    with open(os.path.join(out, "ingest.log"), "w") as f:
        f.write(p.stdout + p.stderr)
    obs = {"observation_version": 1, "adapter": "example", "commit": job["commit"], "input": job["input"],
           "entry_id": job["entry_id"], "ledger_seq": job["ledger"]["seq"], "ingested": p.returncode == 0,
           "error": None if p.returncode == 0 else (p.stderr.strip().splitlines() or ["toy.py failed"])[-1],
           "adapter_failure": False, "transactions": [], "operations": [], "state_changes": [], "unreadable": []}
    if p.returncode == 0:
        con = sqlite3.connect(db)
        for h, order, ok, parts in con.execute("SELECT hash, tx_order, success, participants FROM transactions ORDER BY tx_order"):
            obs["transactions"].append({"hash": h, "tx_order": order, "result_code": "success" if ok else "failed",
                                        "participants": json.loads(parts)})
        for h, order, op, parts in con.execute("SELECT tx_hash, tx_order, op_order, participants FROM operations"):
            obs["operations"].append({"tx_hash": h, "tx_order": order, "op_order": op, "type": None,
                                      "participants": json.loads(parts)})
        con.close()
        os.remove(db)
    obs["row_counts"] = {"transactions": len(obs["transactions"]), "operations": len(obs["operations"])}
    path = os.path.join(out, "observation.json")
    with open(path, "w") as f:
        json.dump(obs, f, indent=1, sort_keys=True)
    emit({"observation": path, "ingested": obs["ingested"], "error": obs["error"]})


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--ref", required=True)
    p.add_argument("--work")
    p = sub.add_parser("up")
    for x in ("--commit", "--work", "--network"):
        p.add_argument(x)
    p = sub.add_parser("run")
    p.add_argument("--job", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("down")
    p.add_argument("--work")
    a = ap.parse_args()
    if a.verb == "prepare":
        prepare(a)
    elif a.verb == "run":
        run(a)
    else:
        emit({})


if __name__ == "__main__":
    main()
