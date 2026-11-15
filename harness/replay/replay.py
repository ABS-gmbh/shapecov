#!/usr/bin/env python3
"""Replay harness: run LedgerCloseMeta corpus entries against an indexer through an adapter.

  replay.py run --refs REF[,REF...] [--adapter wallet-backend] [--inputs rpc,datalake]
                [--entries ID,ID | --all-entries] [--max-protocol N] [--timeout 120]
                [--proposed FILE] [--work DIR] [--out DIR]
  replay.py report [--out DIR]       regenerate RESULTS.md from out/results.jsonl
  replay.py check [--out DIR]        fail unless out/results.jsonl matches every claim in sightings.json

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
sys.path.insert(0, os.path.join(REPO, "tools"))
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


def adapter_mapping(name):
    """The adapter's oracle mapping (adapters/<name>/expect.py), or None if it has none."""
    path = os.path.join(HERE, "adapters", name, "expect.py")
    if not os.path.isfile(path):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("expect_" + name.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def oracle_verdict(entry, obs, mapping, value):
    """Check every row the oracle derives from the ledger; label each failure as a known upstream
    issue (adapters/<name>/known.json) or unexplained."""
    import oracle
    passphrase = entry["source"]["network_passphrase"]
    exps = mapping.expectations(oracle.changes(value), passphrase)
    if hasattr(mapping, "balance_expectations"):
        exps += mapping.balance_expectations(oracle.balances(value), passphrase)
    c = classify.classify(exps, obs)
    known, unexplained = {}, []
    if hasattr(mapping, "balance_expectations") and obs.get("ingested"):
        # The other direction: a stored balance movement for an account where the ledger shows none.
        # Only accounts (G...) are compared; the oracle does not see balances held by contracts.
        expected_keys = {(x["tx_hash"], x["op_order"], x["account"], x["token"]) for x in exps if x["expect"] == "balance_net"}
        for k, total in sorted(classify.balance_sums(obs).items(), key=str):
            if k not in expected_keys and total and (k[2] or "").startswith("G"):
                unexplained.append("balance of %s in token %s, tx %s, %s: the stored rows add up to %+d, the "
                                   "ledger shows no change" % (k[2], k[3], (k[0] or "?")[:12],
                                                               "the fee" if k[1] == 0 else "operation %s" % k[1], total))
    for ch in c["checks"]:
        if ch["outcome"] in ("met", "not_checked"):
            continue
        issue = mapping.known_issue(ch["expect"])
        if issue:
            known.setdefault(issue, []).append(ch["detail"])
        else:
            unexplained.append(ch["detail"])
    met = sum(1 for ch in c["checks"] if ch["outcome"] == "met")
    if not obs.get("ingested"):
        verdict = c["result"]
    elif unexplained:
        verdict = "mishandled" if any(ch["outcome"] == "wrong_value" and not mapping.known_issue(ch["expect"])
                                      for ch in c["checks"]) else "dropped"
    else:
        verdict = "pass" if not known else "known issues only"
    return {"verdict": verdict, "rows_expected": len(exps), "rows_met": met,
            "known": {k: len(v) for k, v in known.items()}, "unexplained": unexplained}


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
    mapping = adapter_mapping(a.adapter)
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
                    if mapping is not None and not obs.get("adapter_failure"):
                        import base64
                        import oracle
                        from decode import Decoder
                        dec = Decoder(json.load(open(os.path.join(REPO, "schema", "schema.json"))))
                        value = dec.decode("LedgerCloseMeta", base64.b64decode(
                            open(os.path.join(REPO, "corpus", e["file"])).read()))
                        r["oracle"] = oracle_verdict(e, obs, mapping, value)
                    with open(os.path.join(jdir, "result.json"), "w") as f:
                        json.dump(r, f, indent=1)
                    results[(e["id"], commit, inp)] = r
                    save_results(out, results)
                    orc = r.get("oracle")
                    print("%-10s %-8s %-45s %5.1fs  %s%s" % (
                        r["result"], inp, e["id"][:45], obs.get("seconds") or 0,
                        ("oracle %s %d/%d%s  " % (orc["verdict"], orc["rows_met"], orc["rows_expected"],
                                                 (" known " + ",".join(sorted(orc["known"]))) if orc["known"] else "")) if orc else "",
                        (c["mishandled"] + c["dropped"] + [""])[0][:110]), flush=True)
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
    orc = {k: r["oracle"] for k, r in results.items() if r.get("oracle")}
    if orc:
        L.extend(["", "## Oracle checks", "",
                  "`tools/oracle.py` derives from each ledger what changed in ledger state, and the adapter's",
                  "`expect.py` names the row the indexer should store for each change. Every such row is",
                  "checked. A failure is labelled with the open upstream issue that explains it",
                  "(`adapters/<name>/known.json`) or listed as **unexplained**: a candidate new finding.", "",
                  "| Commit | Input | Replays | Rows expected | Rows met | Known issues | Unexplained |",
                  "|---|---|---|---|---|---|---|"])
        for c in order:
            for inp in inputs:
                rs = [v for k, v in orc.items() if k[1] == c and k[2] == inp]
                if not rs:
                    continue
                known = {}
                for v in rs:
                    for issue, n in v["known"].items():
                        known[issue] = known.get(issue, 0) + n
                L.append("| `%s` | %s | %d | %d | %d | %s | %d |" % (
                    c[:8], inp, len(rs), sum(v["rows_expected"] for v in rs), sum(v["rows_met"] for v in rs),
                    ", ".join("%s (%d)" % (i.split("/")[-1], n) for i, n in sorted(known.items())) or "none",
                    sum(len(v["unexplained"]) for v in rs)))
        # A failure at a commit that sightings.json claims fails for this entry is that sighting,
        # found again by the oracle without the manifest's expectation; anything else is unexplained.
        with open(os.path.join(HERE, "sightings.json")) as f:
            claimed = {(x["entry"], x["commit"]): x["issue"] for x in json.load(f)["sightings"] if x["expect"] != "pass"}
        rows = [(k, d) for k, v in sorted(orc.items()) for d in v["unexplained"]]
        sighting = [(k, d) for k, d in rows if (k[0], k[1]) in claimed]
        unexplained = [(k, d) for k, d in rows if (k[0], k[1]) not in claimed]
        L.extend(["", "Failures that are a claimed sighting (found by the oracle alone, without the manifest's expectation):" if sighting else "", ""])
        for k, d in sighting:
            L.append("- %s: `%s` at `%s`, %s: %s" % (claimed[(k[0], k[1])], k[0], k[1][:12], k[2], d.replace("|", "\\|")))
        L.extend(["", "**Unexplained oracle failures (candidate new findings):**" if unexplained else "**No unexplained oracle failures.**", ""])
        for k, d in unexplained:
            L.append("- `%s` at `%s`, %s: %s" % (k[0], k[1][:12], k[2], d.replace("|", "\\|")))
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


def cmd_check(a):
    """Compare recorded results with the claims in sightings.json; exit 1 on any difference."""
    with open(os.path.join(HERE, "sightings.json")) as f:
        claims = json.load(f)["sightings"]
    results = load_results(os.path.abspath(a.out))
    bad = 0
    for c in claims:
        got = {k[2]: r["result"] for k, r in results.items() if k[0] == c["entry"] and k[1] == c["commit"]}
        if not got:
            print("MISSING   %-40s %s at %s: no recorded run" % (c["issue"], c["entry"], c["commit"][:12]))
            bad += 1
            continue
        for inp, res in sorted(got.items()):
            ok = res == c["expect"]
            bad += not ok
            print("%-9s %-40s %s at %s, %s: %s (claimed %s)" % ("ok" if ok else "DIFFERS", c["issue"], c["entry"],
                                                              c["commit"][:12], inp, res, c["expect"]))
    print("SIGHTINGS OK" if not bad else "%d SIGHTING CHECK(S) FAILED" % bad)
    if a.oracle:
        # An oracle failure that is neither a known open issue nor a claimed sighting is a candidate
        # new finding: fail, so CI raises it.
        claimed = {(c["entry"], c["commit"]) for c in claims if c["expect"] != "pass"}
        new = [(k, d) for k, r in sorted(results.items()) if r.get("oracle")
               for d in r["oracle"]["unexplained"] if (k[0], k[1]) not in claimed]
        for k, d in new:
            print("UNEXPLAINED %s at %s, %s: %s" % (k[0], k[1][:12], k[2], d[:200]))
        print("ORACLE OK: no unexplained failures" if not new else "%d UNEXPLAINED ORACLE FAILURE(S)" % len(new))
        bad += len(new)
    sys.exit(1 if bad else 0)


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
    p = sub.add_parser("check")
    p.add_argument("--out", default=os.path.join(HERE, "out"))
    p.add_argument("--oracle", action="store_true", help="also fail on unexplained oracle failures")
    a = ap.parse_args()
    {"run": cmd_run, "report": cmd_report, "check": cmd_check}[a.verb](a)


if __name__ == "__main__":
    main()
