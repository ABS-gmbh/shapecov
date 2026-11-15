#!/usr/bin/env python3
"""Replay harness: run LedgerCloseMeta corpus entries against an indexer through an adapter.

  replay.py run --refs REF[,REF...] [--adapter wallet-backend] [--inputs rpc,datalake]
                [--entries ID,ID | --all-entries] [--max-protocol N] [--timeout 120]
                [--proposed FILE] [--work DIR] [--out DIR]
  replay.py report [--out DIR]       regenerate RESULTS.md from out/results.jsonl

Entries are discovered from corpus/manifest.json (xdr_type == LedgerCloseMeta). By default the
entries that carry `expected.indexer` are run; --all-entries runs every LedgerCloseMeta entry
(entries without expectations are still checked for "ingested without error, every stored
address reads back").

The harness itself runs on the host with the Python standard library; the feeder, the
database and the indexer run in Docker on an internal network with no route to the internet.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import classify  # noqa: E402

NET = "shapecov-replay-net"
FEEDER = "shapecov-replay-feeder"
FEEDER_IMAGE = os.environ.get("REPLAY_FEEDER_IMAGE", "python:3.14-slim")
RESULT_ORDER = {"mishandled": 0, "dropped": 1, "error": 2, "pass": 3}


def sh(args, check=True):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if check and p.returncode != 0:
        raise SystemExit("command failed (%d): %s\n%s" % (p.returncode, " ".join(args), p.stdout))
    return p


def adapter(name, *args):
    exe = os.path.join(HERE, "adapters", name, "adapter.py")
    p = subprocess.run([sys.executable, exe] + list(args), stdout=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise SystemExit("adapter %s %s failed" % (name, args[0]))
    return json.loads(p.stdout.strip().splitlines()[-1])


def start_feeder(work):
    fw = os.path.join(work, "feeder")
    os.makedirs(fw, exist_ok=True)
    for f in ("feeder-index.json", "feeder-requests.jsonl"):
        if os.path.exists(os.path.join(fw, f)):
            os.remove(os.path.join(fw, f))
    if sh(["docker", "network", "inspect", NET], check=False).returncode != 0:
        sh(["docker", "network", "create", "--internal", NET])
    sh(["docker", "rm", "-f", FEEDER], check=False)
    sh(["docker", "run", "-d", "--name", FEEDER, "--network", NET, "--memory", "256m",
        "-v", REPO + ":/repo:ro", "-e", "SHAPECOV_REPO=/repo", "-v", fw + ":/work", FEEDER_IMAGE,
        "python3", "/repo/harness/replay/feeder/feeder.py", "--corpus", "/repo/corpus", "--work", "/work"])
    for _ in range(240):
        logs = sh(["docker", "logs", FEEDER], check=False).stdout
        if "rpc on" in logs:
            break
        if sh(["docker", "inspect", "-f", "{{.State.Running}}", FEEDER], check=False).stdout.strip() != "true":
            raise SystemExit("feeder stopped:\n" + logs)
        time.sleep(0.5)
    else:
        raise SystemExit("feeder did not start")
    with open(os.path.join(fw, "feeder-index.json")) as f:
        return json.load(f)


def feeder_stats():
    p = sh(["docker", "exec", FEEDER, "python3", "-c",
            "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/__stats').read().decode())"],
           check=False)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"error": p.stdout[-300:]}


def load_results(out):
    path = os.path.join(out, "results.jsonl")
    res = {}
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                res[(r["entry_id"], r["commit"], r["input"])] = r
    return res


def save_results(out, res):
    with open(os.path.join(out, "results.jsonl"), "w") as f:
        for k in sorted(res):
            f.write(json.dumps(res[k], sort_keys=True) + "\n")


def cmd_run(a):
    work, out = os.path.abspath(a.work), os.path.abspath(a.out)
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    t_start = time.time()
    with open(os.path.join(REPO, "corpus", "manifest.json")) as f:
        manifest = json.load(f)
    proposed = {}
    if a.proposed:
        with open(a.proposed) as f:
            proposed = json.load(f).get("expected_indexer", {})
    index = start_feeder(work)
    lcm = [e for e in manifest["entries"] if e.get("xdr_type") == "LedgerCloseMeta"]
    selected = []
    for e in lcm:
        if a.entries:
            if e["id"] not in a.entries.split(","):
                continue
        elif not a.all_entries and not (e.get("expected", {}).get("indexer") or e["id"] in proposed):
            continue
        if a.max_protocol is not None and e.get("protocol_version", 0) > a.max_protocol:
            continue
        selected.append(e)
    print("corpus: %d LedgerCloseMeta entries in the manifest, %d selected; feeder problems: %d"
          % (len(lcm), len(selected), len(index["problems"])), flush=True)
    results = load_results(out)
    run_meta = {"started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "adapter": a.adapter, "inputs": a.inputs.split(","), "refs": [], "entries": [e["id"] for e in selected],
                "feeder_problems": index["problems"], "feeder_maxrss_kb_after_build": index["maxrss_kb_after_build"]}
    req_log = os.path.join(work, "feeder", "feeder-requests.jsonl")
    try:
        for ref in a.refs.split(","):
            info = adapter(a.adapter, "prepare", "--ref", ref, "--work", work)
            commit = info["commit"]
            run_meta["refs"].append(info)
            print("== %s %s (%s) go-stellar-sdk %s" % (a.adapter, commit[:12], info["subject"][:60],
                                                       info["dependency_pins"].get("github.com/stellar/go-stellar-sdk")), flush=True)
            adapter(a.adapter, "up", "--commit", commit, "--work", work, "--network", NET)
            for inp in a.inputs.split(","):
                for e in selected:
                    ix = index["entries"].get(e["id"])
                    jdir = os.path.join(out, commit[:12], inp, e["id"])
                    os.makedirs(jdir, exist_ok=True)
                    base = {"entry_id": e["id"], "adapter": a.adapter, "ref": ref, "commit": commit, "input": inp,
                            "protocol_version": e.get("protocol_version"),
                            "sdk_pin": info["dependency_pins"].get("github.com/stellar/go-stellar-sdk"),
                            "mode": "unmodified"}
                    if ix is None:
                        problem = next((p["problem"] for p in index["problems"] if p["id"] == e["id"]), "not indexed")
                        r = dict(base, result="error", note="the feeder cannot serve this entry: " + problem)
                        results[(e["id"], commit, inp)] = r
                        continue
                    job = {"job_version": 1, "entry_id": e["id"], "ref": ref, "commit": commit, "input": inp,
                           "network_passphrase": ix["passphrase"],
                           "ledger": {"seq": ix["seq"], "hash": ix["hash"], "close_time": ix["close_time"],
                                      "protocol": ix["protocol"]},
                           "rpc": {"url": "http://%s:8000/rpc/%s" % (FEEDER, e["id"])},
                           "datalake": {"s3_endpoint": "http://%s:9000" % FEEDER,
                                        "bucket_path": "shapecov-lake/" + e["id"], "region": "us-east-1"},
                           "history_archive": {"url": "http://%s:8000/archive/%s" % (FEEDER, e["id"])},
                           "docker_network": NET, "timeout_seconds": a.timeout, "work_dir": work}
                    with open(os.path.join(jdir, "job.json"), "w") as f:
                        json.dump(job, f, indent=1)
                    offset = os.path.getsize(req_log) if os.path.exists(req_log) else 0
                    adapter(a.adapter, "run", "--job", os.path.join(jdir, "job.json"), "--out", jdir)
                    # The recorded job is evidence that may be published: keep the local path out of it.
                    with open(os.path.join(jdir, "job.json"), "w") as f:
                        json.dump(dict(job, work_dir="$REPLAY_WORK"), f, indent=1)
                    with open(os.path.join(jdir, "observation.json")) as f:
                        obs = json.load(f)
                    reqs = []
                    if os.path.exists(req_log):
                        with open(req_log) as f:
                            f.seek(offset)
                            reqs = f.readlines()
                    with open(os.path.join(jdir, "feeder-requests.jsonl"), "w") as f:
                        f.writelines(reqs)
                    exps = list(e.get("expected", {}).get("indexer") or [])
                    source = "manifest" if exps else "none (implicit checks only)"
                    if e["id"] in proposed:
                        exps += proposed[e["id"]]
                        source = "proposed (not in the manifest yet): " + os.path.basename(a.proposed)
                    c = classify.classify(exps, obs)
                    r = dict(base, result=c["result"], mishandled=c["mishandled"], dropped=c["dropped"],
                             checks=c["checks"], expectations=len(exps), expectations_source=source,
                             ledger=job["ledger"], ingested=obs.get("ingested"), row_counts=obs.get("row_counts"),
                             process=obs.get("process"), seconds=obs.get("seconds"),
                             feeder_requests=len(reqs), evidence=os.path.relpath(jdir, HERE))
                    if c.get("note"):
                        r["note"] = c["note"]
                    with open(os.path.join(jdir, "result.json"), "w") as f:
                        json.dump(r, f, indent=1)
                    results[(e["id"], commit, inp)] = r
                    save_results(out, results)
                    print("%-10s %-8s %-45s %5.1fs  %s" % (r["result"], inp, e["id"][:45], obs.get("seconds") or 0,
                                                          (c["mishandled"] + c["dropped"] + [""])[0][:150]), flush=True)
            adapter(a.adapter, "down", "--work", work)
    finally:
        run_meta["feeder_stats"] = feeder_stats()
        run_meta["seconds"] = round(time.time() - t_start, 1)
        if not a.keep:
            sh(["docker", "rm", "-f", FEEDER, "shapecov-replay-db", "shapecov-replay-ingest",
                "shapecov-replay-migrate"], check=False)
            sh(["docker", "network", "rm", NET], check=False)
    runs_path = os.path.join(out, "runs.jsonl")
    with open(runs_path, "a") as f:
        f.write(json.dumps(run_meta, sort_keys=True) + "\n")
    save_results(out, results)
    cmd_report(a)
    print("feeder: %s" % json.dumps(run_meta["feeder_stats"]))
    print("done in %.0fs; results in %s" % (run_meta["seconds"], os.path.join(out, "results.jsonl")))


def cmd_report(a):
    out = os.path.abspath(a.out)
    results = load_results(out)
    runs = []
    if os.path.isfile(os.path.join(out, "runs.jsonl")):
        with open(os.path.join(out, "runs.jsonl")) as f:
            runs = [json.loads(x) for x in f]
    commits = {}
    for run in runs:
        for info in run["refs"]:
            commits[info["commit"]] = info
    # Parse the dates: ISO strings with different UTC offsets do not sort by time as text.
    order = sorted(commits, key=lambda c: datetime.datetime.fromisoformat(commits[c]["commit_date"]))
    order += sorted({k[1] for k in results} - set(order))
    inputs = sorted({k[2] for k in results}, reverse=True)
    entries = []
    for k in sorted(results):
        if k[0] not in entries:
            entries.append(k[0])
    with_exp = [e for e in entries if any(r.get("expectations") for k, r in results.items() if k[0] == e)]
    without = [e for e in entries if e not in with_exp]
    L = ["# Replay results", "",
         "Generated by `harness/replay/replay.py report` from `out/results.jsonl`. Do not edit by hand.", "",
         "Each cell is the result for one entry at one commit, per input: `rpc` is the mock stellar-rpc",
         "`getLedgers` endpoint, `datalake` is the Galexie layout on an S3-compatible store. Every cell is a run",
         "of the indexer's own `ingest` command against PostgreSQL/TimescaleDB with the tables read back.", "",
         "## Commits", "", "| Commit | Date | Subject | go-stellar-sdk pin | Source or dependencies modified |",
         "|---|---|---|---|---|"]
    for c in order:
        i = commits.get(c, {})
        L.append("| `%s` | %s | %s | %s | %s |" % (c[:12], i.get("commit_date", "")[:10], i.get("subject", ""),
                                                  i.get("dependency_pins", {}).get("github.com/stellar/go-stellar-sdk", ""),
                                                  "no" if not (i.get("source_modified") or i.get("dependencies_modified")) else "YES"))

    def matrix(title, ents, note):
        if not ents:
            return
        L.extend(["", "## " + title, "", note, "",
                  "| Entry | Protocol | Input | " + " | ".join("`%s`" % c[:8] for c in order) + " |",
                  "|---|---|---|" + "---|" * len(order)])
        for e in ents:
            for inp in inputs:
                cells, proto = [], ""
                for c in order:
                    r = results.get((e, c, inp))
                    cells.append(r["result"] if r else "not run")
                    if r:
                        proto = r.get("protocol_version", "")
                if any(x != "not run" for x in cells):
                    L.append("| `%s` | %s | %s | %s |" % (e, proto, inp, " | ".join(cells)))

    matrix("Entries with indexer expectations", with_exp,
           "Expectations come from `expected.indexer` in the corpus manifest unless the detail section says otherwise.")
    matrix("Entries without indexer expectations", without,
           "Only the implicit checks apply: the ledger is ingested without an error and every stored address "
           "reads back as a valid SEP-23 address. `pass` here does not say the stored rows are right.")
    counts = {}
    for (e, c, inp), r in results.items():
        counts.setdefault((c, inp), {}).setdefault(r["result"], 0)
        counts[(c, inp)][r["result"]] += 1
    L.extend(["", "## Totals", "", "| Commit | Input | pass | mishandled | dropped | error |", "|---|---|---|---|---|---|"])
    for c in order:
        for inp in inputs:
            n = counts.get((c, inp))
            if n:
                L.append("| `%s` | %s | %d | %d | %d | %d |" % (c[:8], inp, n.get("pass", 0), n.get("mishandled", 0),
                                                              n.get("dropped", 0), n.get("error", 0)))
    L.extend(["", "## Details of every result that is not `pass`", ""])
    for k in sorted(results, key=lambda k: (k[0], order.index(k[1]) if k[1] in order else 99, k[2])):
        r = results[k]
        if r["result"] == "pass":
            continue
        L.append("### `%s` at `%s`, input %s: %s" % (k[0], k[1][:12], k[2], r["result"]))
        L.append("")
        if r.get("note"):
            L.append("- note: " + r["note"])
        for m in r.get("mishandled", []):
            L.append("- mishandled: " + m.replace("|", "\\|"))
        for d in r.get("dropped", []):
            L.append("- dropped: " + d.replace("|", "\\|"))
        if r.get("expectations_source"):
            L.append("- expectations: %d, source: %s" % (r.get("expectations", 0), r["expectations_source"]))
        if r.get("process"):
            L.append("- indexer process: %s (exit code %s)" % (r["process"]["outcome"], r["process"]["exit_code"]))
        if r.get("evidence"):
            L.append("- evidence: `%s/` (job.json, ingest.log, observation.json, result.json, feeder-requests.jsonl)"
                     % r["evidence"])
        L.append("")
    if runs:
        L.extend(["## Runs", "", "| Started (UTC) | Refs | Inputs | Entries | Seconds | Feeder peak RSS (kB) | Ledgers served by RPC | Objects served by S3 |",
                  "|---|---|---|---|---|---|---|---|"])
        for run in runs:
            s = run.get("feeder_stats", {})
            L.append("| %s | %s | %s | %d | %s | %s | %s | %s |" % (
                run["started"], ", ".join("`%s`" % i["commit"][:8] for i in run["refs"]), ", ".join(run["inputs"]),
                len(run["entries"]), run.get("seconds"), s.get("maxrss_kb"), s.get("ledgers_served_rpc"),
                s.get("objects_served_s3")))
    with open(os.path.join(HERE, "RESULTS.md"), "w") as f:
        f.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("run")
    p.add_argument("--adapter", default="wallet-backend")
    p.add_argument("--refs", required=True)
    p.add_argument("--inputs", default="rpc,datalake")
    p.add_argument("--entries")
    p.add_argument("--all-entries", action="store_true")
    p.add_argument("--max-protocol", type=int)
    p.add_argument("--proposed", help="JSON file of expectations proposed for the manifest; results are labelled")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--keep", action="store_true", help="leave the containers running")
    p.add_argument("--work", default=os.environ.get("REPLAY_WORK", os.path.join(HERE, ".work")))
    p.add_argument("--out", default=os.path.join(HERE, "out"))
    p = sub.add_parser("report")
    p.add_argument("--out", default=os.path.join(HERE, "out"))
    a = ap.parse_args()
    {"run": cmd_run, "report": cmd_report}[a.verb](a)


if __name__ == "__main__":
    main()
