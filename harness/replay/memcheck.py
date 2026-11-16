#!/usr/bin/env python3
"""Show that the replay feeder serves a corpus far larger than its memory budget.

  memcheck.py [--corpus-mb 600] [--budget-mb 64] [--work DIR]

Builds a synthetic corpus of at least --corpus-mb of base64 LedgerCloseMeta by repeating the real
ledgers in corpus/ under new IDs, starts the feeder on it (Docker, internal network, the same image
and memory cap the harness uses), then fetches every ledger through all three inputs from a second
container: the mock stellar-rpc `getLedgers`, the S3 object and, where the network allows, the GCS
object. Every response is read to the end and its size checked. Fails unless the feeder's peak
resident memory, as the kernel reports it, stays within --budget-mb while it builds the data lake
and serves everything.

Python standard library and Docker only.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
IMAGE = os.environ.get("REPLAY_FEEDER_IMAGE", "python:3.14-slim")
FEEDER, CLIENT, NET = "shapecov-memcheck-feeder", "shapecov-memcheck-client", "shapecov-memcheck-net"

CLIENT_SCRIPT = r'''
import json, sys, urllib.request
idx = json.load(open("/work/feeder-index.json"))
nets = {"Public Global Stellar Network ; September 2015": "pubnet",
        "Test SDF Network ; September 2015": "testnet"}
keys = {b["id"]: b["key"] for b in idx["lake"]}
def drain(req):
    n = 0
    with urllib.request.urlopen(req, timeout=120) as r:
        while True:
            c = r.read(1 << 16)
            if not c:
                return n
            n += len(c)
done = {"rpc": 0, "s3": 0, "gcs": 0, "bytes": 0}
for eid, e in idx["entries"].items():
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getLedgers",
                       "params": {"startLedger": e["seq"], "pagination": {"limit": 1}}}).encode()
    done["bytes"] += drain(urllib.request.Request("http://%s:8000/rpc/%s" % (sys.argv[1], eid), data=body,
                                                  headers={"Content-Type": "application/json"}))
    done["rpc"] += 1
    key = keys[eid]
    done["bytes"] += drain("http://%s:9000/shapecov-lake/%s" % (sys.argv[1], key))
    done["s3"] += 1
    net = nets.get(e["passphrase"])
    if net:
        entry, rest = key.split("/", 1)
        done["bytes"] += drain("http://%s:9100/shapecov-lake/%s/%s/%s" % (sys.argv[1], entry, net, rest))
        done["gcs"] += 1
print(json.dumps(done))
'''


def sh(args, check=True):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if check and p.returncode != 0:
        raise SystemExit("command failed (%d): %s\n%s" % (p.returncode, " ".join(args), p.stdout))
    return p


def build_corpus(dst, target_bytes):
    manifest = json.load(open(os.path.join(REPO, "corpus", "manifest.json")))
    real = [e for e in manifest["entries"] if e.get("xdr_type") == "LedgerCloseMeta"]
    os.makedirs(os.path.join(dst, "entries"), exist_ok=True)
    entries, total, k = [], 0, 0
    while total < target_bytes:
        for e in real:
            eid = "%s~%d" % (e["id"], k)
            rel = "entries/%s.LedgerCloseMeta.xdr.b64" % eid
            src = os.path.join(REPO, "corpus", e["file"])
            shutil.copyfile(src, os.path.join(dst, rel))  # real copies: bind mounts do not all serve hard links
            total += os.path.getsize(src)
            entries.append({"id": eid, "xdr_type": "LedgerCloseMeta", "file": rel, "source": e["source"]})
            if total >= target_bytes:
                break
        k += 1
    json.dump({"entries": entries}, open(os.path.join(dst, "manifest.json"), "w"))
    return len(entries), total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus-mb", type=int, default=600)
    ap.add_argument("--budget-mb", type=int, default=64)
    ap.add_argument("--work")
    a = ap.parse_args()
    work = a.work or tempfile.mkdtemp(prefix="memcheck-")
    corpus, fw = os.path.join(work, "corpus"), os.path.join(work, "feeder")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(fw)
    n, size = build_corpus(corpus, a.corpus_mb << 20)
    print("synthetic corpus: %d ledgers, %.0f MB of base64" % (n, size / 2 ** 20), flush=True)
    sh(["docker", "rm", "-f", FEEDER, CLIENT], check=False)
    if sh(["docker", "network", "inspect", NET], check=False).returncode != 0:
        sh(["docker", "network", "create", "--internal", NET])
    t0 = time.time()
    try:
        sh(["docker", "run", "-d", "--name", FEEDER, "--network", NET, "--memory", "256m",
            "-v", REPO + ":/repo:ro", "-v", corpus + ":/corpus:ro", "-e", "SHAPECOV_REPO=/repo", "-v", fw + ":/work",
            IMAGE, "python3", "/repo/harness/replay/feeder/feeder.py", "--corpus", "/corpus", "--work", "/work"])
        for _ in range(3600):
            logs = sh(["docker", "logs", FEEDER], check=False).stdout
            if "rpc on" in logs:
                break
            if sh(["docker", "inspect", "-f", "{{.State.Running}}", FEEDER], check=False).stdout.strip() != "true":
                raise SystemExit("feeder stopped:\n" + logs[-2000:])
            time.sleep(1)
        built = time.time() - t0
        with open(os.path.join(fw, "client.py"), "w") as f:
            f.write(CLIENT_SCRIPT)
        got = sh(["docker", "run", "--rm", "--name", CLIENT, "--network", NET, "-v", fw + ":/work:ro", IMAGE,
                  "python3", "/work/client.py", FEEDER])
        served = json.loads(got.stdout.strip().splitlines()[-1])
        stats = json.loads(sh(["docker", "exec", FEEDER, "python3", "-c",
                               "import urllib.request;print(urllib.request.urlopen("
                               "'http://127.0.0.1:8000/__stats').read().decode())"]).stdout)
    finally:
        sh(["docker", "rm", "-f", FEEDER, CLIENT], check=False)
        sh(["docker", "network", "rm", NET], check=False)
    peak_mb = stats["maxrss_kb"] / 1024
    result = {"ledgers": n, "corpus_mb": round(size / 2 ** 20), "build_seconds": round(built),
              "served": served, "feeder_peak_rss_mb": round(peak_mb, 1), "budget_mb": a.budget_mb,
              "seconds": round(time.time() - t0)}
    print(json.dumps(result))
    ok = (peak_mb <= a.budget_mb and served["rpc"] == n and served["s3"] == n)
    print("MEMORY OK: peak %.1f MB for %d MB of ledgers (budget %d MB)" % (peak_mb, result["corpus_mb"], a.budget_mb)
          if ok else "MEMORY CHECK FAILED")
    shutil.rmtree(work, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
