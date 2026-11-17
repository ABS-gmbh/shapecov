#!/usr/bin/env python3
"""Replay harness: run LedgerCloseMeta corpus entries against an indexer through an adapter.

  replay.py run --refs REF[,REF...] [--adapter wallet-backend] [--inputs rpc,datalake]
                [--entries ID,ID | --all-entries] [--max-protocol N] [--timeout 120]
                [--proposed FILE] [--work DIR] [--out DIR]
  replay.py report [--out DIR]       regenerate RESULTS.md from out/results.jsonl
  replay.py rejudge [--out DIR]      recompute the oracle verdicts from the stored observations
  replay.py backtest                 verify backtest.json against the recorded results
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
import inspect
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

CORPUS = os.path.join(REPO, "corpus")  # --corpus replaces it, e.g. with a sweep of mined ledgers
# REPLAY_PREFIX names this run's containers and network, so two replays can run side by side.
PREFIX = os.environ.get("REPLAY_PREFIX", "shapecov-replay")
NET = PREFIX + "-net"
FEEDER = PREFIX + "-feeder"
FEEDER_DIR = "feeder" if PREFIX == "shapecov-replay" else FEEDER  # under --work
FEEDER_IMAGE = os.environ.get("REPLAY_FEEDER_IMAGE", "python:3.14-slim")
RESULT_ORDER = {"mishandled": 0, "dropped": 1, "error": 2, "pass": 3, "not applicable": 4}


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
    fw = os.path.join(work, FEEDER_DIR)
    os.makedirs(fw, exist_ok=True)
    for f in ("feeder-index.json", "feeder-requests.jsonl"):
        if os.path.exists(os.path.join(fw, f)):
            os.remove(os.path.join(fw, f))
    if sh(["docker", "network", "inspect", NET], check=False).returncode != 0:
        sh(["docker", "network", "create", "--internal", NET])
    sh(["docker", "rm", "-f", FEEDER], check=False)
    sh(["docker", "run", "-d", "--name", FEEDER, "--network", NET, "--memory", "256m",
        "-v", REPO + ":/repo:ro", "-v", CORPUS + ":/corpus:ro", "-e", "SHAPECOV_REPO=/repo", "-v", fw + ":/work",
        FEEDER_IMAGE, "python3", "/repo/harness/replay/feeder/feeder.py", "--corpus", "/corpus", "--work", "/work"])
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
                # A ledger replayed inside a sequence is keyed with the sequence: several sequences may share it.
                key = r["entry_id"] + ("@" + r["in_sequence"] if r.get("in_sequence") else "")
                res[(key, r["commit"], r["input"])] = r
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


_EXPS = {}


def oracle_verdict(entry, obs, mapping, value):
    """Check every row the oracle derives from the ledger; label each failure as a known upstream
    issue (adapters/<name>/known.json) or unexplained."""
    import copy
    import oracle
    passphrase = entry["source"]["network_passphrase"]
    key = (entry["id"], id(value), id(mapping))
    if key not in _EXPS:
        # The rows depend only on the ledger: derive them once per decoded ledger (rejudge judges
        # every commit's replay of the same ledger in a row).
        exps = mapping.expectations(oracle.changes(value), passphrase)
        if hasattr(mapping, "balance_expectations"):
            exps += mapping.balance_expectations(oracle.balances(value), passphrase)
        if hasattr(mapping, "muxed_expectations"):
            exps += mapping.muxed_expectations(oracle.muxed_destinations(value), passphrase)
        if hasattr(mapping, "participant_expectations"):
            records = oracle.participants(value, passphrase)
            if "value" in inspect.signature(mapping.participant_expectations).parameters:
                # A mapping that needs more than the meta (Horizon's participants of a failed
                # transaction come from its envelope) gets the decoded ledger too.
                exps += mapping.participant_expectations(records, passphrase, value=value)
            else:
                exps += mapping.participant_expectations(records, passphrase)
        if hasattr(mapping, "state_expectations"):
            exps += mapping.state_expectations(value, passphrase)
        if hasattr(mapping, "deploy_expectations"):
            exps += mapping.deploy_expectations(value, passphrase)
        if hasattr(mapping, "event_expectations"):
            exps += mapping.event_expectations(value, passphrase)
        if hasattr(mapping, "ledger_expectations"):
            exps += mapping.ledger_expectations(value, passphrase)
        _EXPS.clear()
        _EXPS[key] = (value, exps)  # holding the value keeps id(value) from being reused
    exps = copy.deepcopy(_EXPS[key][1])
    c = classify.classify(exps, obs)
    known, unexplained, fixed, fixed_by, known_outcome = {}, [], {}, {}, {}
    if not obs.get("ingested"):
        # Every check is moot when the indexer did not take the ledger: that failure is itself the
        # finding, unless a known issue explains it.
        failure = {"expect": "ingested", "error": obs.get("error") or "", "via": {}}
        what = ("the indexer did not ingest this ledger: %s" % obs["error"]) if obs.get("error") else \
               "the indexer did not ingest this ledger and raised no error"
        issue = _known(mapping, failure, obs)
        if issue:
            known.setdefault(issue, []).append(what)
        else:
            unexplained.append(what)
    if hasattr(mapping, "balance_expectations") and obs.get("ingested"):
        # The other direction: a stored balance movement for an account where the ledger shows none.
        # Only accounts (G...) are compared; the oracle does not see balances held by contracts.
        # Tokens other than Stellar Asset Contracts keep balances in contract storage, which the
        # oracle does not read, so their movements are not compared either.
        expected_keys = {(x["tx_hash"], x["op_order"], x["account"], x["token"]) for x in exps if x["expect"] == "balance_net"}
        unseen = {(m.get("tx_hash"), m.get("op_order"), m.get("account"), m.get("token"))
                  for m in obs.get("balance_movements") or [] if m.get("token_kind") == "contract"}
        for k, total in sorted(classify.balance_sums(obs).items(), key=str):
            if k not in expected_keys and k not in unseen and total and (k[2] or "").startswith("G"):
                unexplained.append("balance of %s in token %s, tx %s, %s: the stored rows add up to %+d, the "
                                   "ledger shows no change" % (k[2], k[3], (k[0] or "?")[:12],
                                                               "the fee" if k[1] == 0 else "operation %s" % k[1], total))
    for ch in c["checks"]:
        if ch["outcome"] in ("met", "not_checked"):
            continue
        issue = _known(mapping, ch["expect"], obs)
        if issue:
            known.setdefault(issue, []).append(ch["detail"])
            worst = "mishandled" if ch["outcome"] == "wrong_value" else "dropped"
            if known_outcome.get(issue) != "mishandled":
                known_outcome[issue] = worst
            rule = mapping.known_rule(ch["expect"], commit=obs.get("commit")) if hasattr(mapping, "known_rule") else None
            if rule and rule.get("fixed_by"):
                # A defect fixed later: counted per rule, i.e. per kind of failure and the fix it belongs to.
                fixed[rule["kind"]] = fixed.get(rule["kind"], 0) + 1
                fixed_by[rule["kind"]] = rule["fixed_by"][:8]
        else:
            unexplained.append(ch["detail"])
    met = sum(1 for ch in c["checks"] if ch["outcome"] == "met")
    if not obs.get("ingested"):
        verdict = c["result"]
    elif unexplained:
        verdict = "mishandled" if any(ch["outcome"] == "wrong_value" and not _known(mapping, ch["expect"], obs)
                                      for ch in c["checks"]) else "dropped"
    else:
        verdict = "pass" if not known else "known issues only"
    out = {"verdict": verdict, "rows_expected": len(exps), "rows_met": met,
           "known": {k: len(v) for k, v in known.items()}, "unexplained": unexplained}
    if known_outcome:
        out["known_outcome"] = known_outcome  # per label: a wrong stored value or a missing row
    if fixed:
        out["fixed_upstream"] = fixed
        out["fixed_by"] = fixed_by
    return out


def entry_verdict(r):
    """The per-entry verdict a report shows: the worse of the indexer's result (against the manifest's
    expectations) and the oracle's checks of every row, with the issue labels that explain the oracle's
    failures, or "unexplained". E.g. "pass", "dropped: #815", "mishandled: unexplained"."""
    res = r["result"]
    if res == "not applicable":
        return "n/a"
    o = r.get("oracle") or {}
    rank = {"pass": 0, "dropped": 1, "mishandled": 2, "error": 3}
    word, labels = res, []
    outcome = dict(o.get("known_outcome") or {})
    for label in sorted(o.get("known") or {}):
        w = outcome.get(label)
        if w is None:  # recorded before known_outcome existed
            w = o.get("verdict") if o.get("verdict") in ("mishandled", "dropped") else "dropped"
        labels.append(_short(label))
        word = max(word, w, key=lambda x: rank.get(x, 0))
    if o.get("unexplained"):
        w = o.get("verdict") if o.get("verdict") in ("mishandled", "dropped") else "mishandled"
        labels.append("unexplained")
        word = max(word, w, key=lambda x: rank.get(x, 0))
    return word + (": " + ", ".join(labels) if labels and word != "pass" else "")


def _short(label):
    """stellar/wallet-backend#815 -> #815; record:R11 -> R11."""
    if label.startswith("record:"):
        return label[len("record:"):]
    return label.split("/")[-1].split(" ")[0] if "#" in label else label


def _known(mapping, expectation, obs):
    import inspect
    if "commit" in inspect.signature(mapping.known_issue).parameters:
        return mapping.known_issue(expectation, commit=obs.get("commit"))
    return mapping.known_issue(expectation)


def use_corpus(a):
    global CORPUS
    if getattr(a, "corpus", None):
        CORPUS = os.path.abspath(a.corpus)


def cmd_run(a):
    use_corpus(a)
    work, out = os.path.abspath(a.work), os.path.abspath(a.out)
    os.makedirs(work, exist_ok=True)
    os.makedirs(out, exist_ok=True)
    t_start = time.time()
    with open(os.path.join(CORPUS, "manifest.json")) as f:
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
    sequences = []
    if a.sequence:
        with open(os.path.join(CORPUS, "sequences.json")) as f:
            listed = {s["id"]: s for s in json.load(f)["sequences"]}
        for name in a.sequence.split(","):
            if name not in listed or name not in (index.get("sequences") or {}):
                raise SystemExit("no sequence %r the feeder serves; feeder problems: %s" % (name, index["problems"]))
            sequences.append(listed[name])
        selected = []
    print("corpus: %d LedgerCloseMeta entries in the manifest, %d selected; feeder problems: %d"
          % (len(lcm), len(selected), len(index["problems"])), flush=True)
    results = load_results(out)
    run_meta = {"started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "adapter": a.adapter, "inputs": a.inputs.split(","), "refs": [], "entries": [e["id"] for e in selected],
                "sequences": [sq["id"] for sq in sequences],
                "feeder_problems": index["problems"], "feeder_maxrss_kb_after_build": index["maxrss_kb_after_build"]}
    req_log = os.path.join(work, FEEDER_DIR, "feeder-requests.jsonl")
    try:
        for ref in a.refs.split(","):
            info = adapter(a.adapter, "prepare", "--ref", ref, "--work", work)
            commit = info["commit"]
            run_meta["refs"].append(info)
            pins = info.get("dependency_pins") or {}
            pin = pins.get("github.com/stellar/go-stellar-sdk")
            print("== %s %s (%s)%s" % (a.adapter, commit[:12], info["subject"][:60],
                                       " go-stellar-sdk %s" % pin if pin else ""), flush=True)
            adapter(a.adapter, "up", "--commit", commit, "--work", work, "--network", NET)
            for inp in a.inputs.split(","):
                if info.get("inputs") and inp not in info["inputs"]:
                    print("skipping input %s: the adapter reads only %s" % (inp, ", ".join(info["inputs"])), flush=True)
                    continue
                for sq in sequences:
                    run_sequence(a, sq, index, info, ref, inp, out, work, mapping, results, req_log)
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
                    if info.get("supported_networks") and ix["passphrase"] not in info["supported_networks"]:
                        r = dict(base, result="not applicable",
                                 note="the indexer reads only these networks: %s; this entry is on %r"
                                      % ("; ".join(info["supported_networks"]), ix["passphrase"]))
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
                           "protocols": (a.protocols or "").split(",") if a.protocols else [],
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
                    if exps and mapping is not None and hasattr(mapping, "manifest_expectations"):
                        # The manifest's expectations are in wallet-backend's vocabulary; an adapter keeps
                        # the ones that apply to its indexer.
                        exps = mapping.manifest_expectations(exps)
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
                            open(os.path.join(CORPUS, e["file"])).read()))
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
            sh(["docker", "rm", "-f", FEEDER, PREFIX + "-db", PREFIX + "-ingest",
                PREFIX + "-migrate", PREFIX + "-etl"], check=False)
            sh(["docker", "network", "rm", NET], check=False)
    runs_path = os.path.join(out, "runs.jsonl")
    with open(runs_path, "a") as f:
        f.write(json.dumps(run_meta, sort_keys=True) + "\n")
    save_results(out, results)
    cmd_report(a)
    print("feeder: %s" % json.dumps(run_meta["feeder_stats"]))
    print("done in %.0fs; results in %s" % (run_meta["seconds"], os.path.join(out, "results.jsonl")))


def _decode_entry(e):
    import base64
    from decode import Decoder
    dec = _DEC.setdefault("dec", Decoder(json.load(open(os.path.join(REPO, "schema", "schema.json")))))
    return dec.decode("LedgerCloseMeta", base64.b64decode(open(os.path.join(CORPUS, e["file"])).read()))


_DEC = {}


def sequence_verdict(sq, obs, mapping, values, member_obs=None):
    """The end-state check of a sequence: every row the oracle says the current-state tables hold
    after the last ledger, plus the sequence's own expectations (corpus/sequences.json, each judged
    on the ledger it names), labelled like oracle_verdict's failures."""
    passphrase = sq["_passphrase"]
    exps = mapping.end_state_expectations(values, passphrase) if hasattr(mapping, "end_state_expectations") else []
    c = classify.classify(exps, obs)
    for x in sq.get("expectations") or []:
        e = {k: v for k, v in x.items() if k != "entry"}
        mo = (member_obs or {}).get(x.get("entry"))
        if mo is None:
            c["checks"].append({"expect": e, "outcome": "not_checked", "detail": "no observation of %s" % x.get("entry")})
        else:
            c["checks"] += classify.classify([e], mo)["checks"]
    exps = exps + list(sq.get("expectations") or [])
    known, unexplained, fixed, fixed_by, known_outcome = {}, [], {}, {}, {}
    if not obs.get("ingested"):
        unexplained.append("the indexer did not ingest the whole sequence: %s" % (obs.get("error") or "no error raised"))
    for ch in c["checks"]:
        if ch["outcome"] in ("met", "not_checked"):
            continue
        issue = _known(mapping, ch["expect"], obs)
        if not issue:
            unexplained.append(ch["detail"])
            continue
        known.setdefault(issue, []).append(ch["detail"])
        known_outcome[issue] = "mishandled" if ch["outcome"] == "wrong_value" or known_outcome.get(issue) == "mishandled" else "dropped"
        rule = mapping.known_rule(ch["expect"], commit=obs.get("commit")) if hasattr(mapping, "known_rule") else None
        if rule and rule.get("fixed_by"):
            fixed[rule["kind"]] = fixed.get(rule["kind"], 0) + 1
            fixed_by[rule["kind"]] = rule["fixed_by"][:8]
    met = sum(1 for ch in c["checks"] if ch["outcome"] == "met")
    checked = sum(1 for ch in c["checks"] if ch["outcome"] != "not_checked")
    verdict = ("mishandled" if unexplained else "known issues only" if known else
               "pass" if checked else "not checked")
    out = {"verdict": verdict, "rows_expected": len(exps), "rows_met": met, "rows_checked": checked,
           "known": {k: len(v) for k, v in known.items()}, "unexplained": unexplained, "checks": c["checks"]}
    if known_outcome:
        out["known_outcome"] = known_outcome
    if fixed:
        out["fixed_upstream"], out["fixed_by"] = fixed, fixed_by
    return out


def run_sequence(a, sq, index, info, ref, inp, out, work, mapping, results, req_log):
    """Ingest the ledgers of one sequence in one run, then judge each ledger as an entry and the
    indexer's current state at the end (result entry_id = the sequence's name)."""
    commit = info["commit"]
    with open(os.path.join(CORPUS, "manifest.json")) as f:
        entries = {e["id"]: e for e in json.load(f)["entries"]}
    six = index["sequences"][sq["id"]]
    members = [index["entries"][m] for m in six["members"]]
    sq["_passphrase"] = six["passphrase"]
    jdir = os.path.join(out, commit[:12], inp, sq["id"])
    os.makedirs(jdir, exist_ok=True)
    last = members[-1]
    job = {"job_version": 1, "entry_id": sq["id"], "ref": ref, "commit": commit, "input": inp,
           "network_passphrase": six["passphrase"],
           "ledger": {"seq": last["seq"], "hash": last["hash"], "close_time": last["close_time"], "protocol": last["protocol"]},
           "sequence": {"id": sq["id"], "ledgers": [{"entry_id": m, "seq": x["seq"], "hash": x["hash"]}
                                                     for m, x in zip(six["members"], members)]},
           "rpc": {"url": "http://%s:8000/rpc/%s" % (FEEDER, sq["id"])},
           "datalake": {"s3_endpoint": "http://%s:9000" % FEEDER, "bucket_path": "shapecov-lake/" + sq["id"],
                        "region": "us-east-1"},
           "history_archive": {"url": "http://%s:8000/archive/%s" % (FEEDER, sq["id"])},
           "protocols": sq.get("protocols") or ((a.protocols or "").split(",") if a.protocols else []),
           "live_persist_max_batch_size": sq.get("persist_batch"),
           "protocol_cursors": sq.get("protocol_cursors") or ["history", "current_state"],
           "commits": [[index["entries"][m]["seq"] for m in g] for g in sq.get("commits") or []],
           "feeder_container": FEEDER,
                           "docker_network": NET, "timeout_seconds": a.timeout * len(members), "work_dir": work}
    with open(os.path.join(jdir, "job.json"), "w") as f:
        json.dump(job, f, indent=1)
    offset = os.path.getsize(req_log) if os.path.exists(req_log) else 0
    adapter(a.adapter, "run", "--job", os.path.join(jdir, "job.json"), "--out", jdir)
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
    base = {"adapter": a.adapter, "ref": ref, "commit": commit, "input": inp,
            "sdk_pin": (info.get("dependency_pins") or {}).get("github.com/stellar/go-stellar-sdk"),
            "mode": "sequence " + sq["id"]}
    values, member_obs = [], {}
    for m in six["members"]:
        e = entries[m]
        mdir = os.path.join(jdir, m)
        os.makedirs(mdir, exist_ok=True)
        mobs = {k: v for k, v in obs.items() if k not in ("ledgers", "end_state")}
        mobs.update((obs.get("ledgers") or {}).get(m) or {"ingested": False})
        mobs["entry_id"], mobs["ledger_seq"] = m, index["entries"][m]["seq"]
        if m != six["members"][-1]:
            # Current-state tables are read once, after the last ledger: they say nothing about an
            # earlier one, whose current-state checks are then not made.
            mobs.pop("native_balances", None)
        with open(os.path.join(mdir, "observation.json"), "w") as f:
            json.dump(mobs, f, indent=1)
        exps = list(e.get("expected", {}).get("indexer") or [])
        if exps and mapping is not None and hasattr(mapping, "manifest_expectations"):
            exps = mapping.manifest_expectations(exps)
        c = classify.classify(exps, mobs)
        r = dict(base, entry_id=m, protocol_version=e.get("protocol_version"), result=c["result"],
                 mishandled=c["mishandled"], dropped=c["dropped"], checks=c["checks"], expectations=len(exps),
                 expectations_source="manifest" if exps else "none (implicit checks only)",
                 ledger={k: index["entries"][m][k] for k in ("seq", "hash", "close_time", "protocol")},
                 ingested=mobs.get("ingested"), row_counts=mobs.get("row_counts"), process=obs.get("process"),
                 seconds=obs.get("seconds"), evidence=os.path.relpath(mdir, HERE), in_sequence=sq["id"])
        member_obs[m] = mobs
        value = _decode_entry(e)
        values.append(value)
        if mapping is not None and not obs.get("adapter_failure"):
            r["oracle"] = oracle_verdict(e, mobs, mapping, value)
        with open(os.path.join(mdir, "result.json"), "w") as f:
            json.dump(r, f, indent=1)
        results[(m + "@" + sq["id"], commit, inp)] = r
    r = dict(base, entry_id=sq["id"], protocol_version=last["protocol"], ledger=job["ledger"],
             sequence={"members": six["members"], "blind": sq.get("blind"), "built_for": sq.get("built_for")},
             ingested=obs.get("ingested"), process=obs.get("process"), seconds=obs.get("seconds"),
             feeder_requests=len(reqs), evidence=os.path.relpath(jdir, HERE))
    if mapping is not None and not obs.get("adapter_failure"):
        r["oracle"] = sequence_verdict(sq, obs, mapping, values, member_obs)
    r["result"] = "error" if obs.get("adapter_failure") else (
        "pass" if (r.get("oracle") or {}).get("verdict") in ("pass", "not checked") else "mishandled")
    with open(os.path.join(jdir, "result.json"), "w") as f:
        json.dump(r, f, indent=1)
    results[(sq["id"], commit, inp)] = r
    save_results(out, results)
    for m in six["members"] + [sq["id"]]:
        x = results[(m + "@" + sq["id"] if m != sq["id"] else m, commit, inp)]
        orc = x.get("oracle") or {}
        print("%-10s %-8s %-45s %5.1fs  oracle %s %d/%d%s  %s" % (
            x["result"], inp, ("  " if m != sq["id"] else "") + m[:43], obs.get("seconds") or 0, orc.get("verdict"),
            orc.get("rows_met", 0), orc.get("rows_expected", 0),
            (" known " + ",".join(sorted(orc["known"]))) if orc.get("known") else "",
            (orc.get("unexplained") or [""])[0][:100]), flush=True)


def cmd_rejudge(a):
    """Recompute every oracle verdict from the stored observations, e.g. after expect.py or known.json
    changed. The indexer is not run again."""
    import base64
    import oracle
    from decode import Decoder
    use_corpus(a)
    out = os.path.abspath(a.out)
    mapping = adapter_mapping(adapter_of(out))
    if mapping is None:
        raise SystemExit("the adapter has no oracle mapping")
    with open(os.path.join(CORPUS, "manifest.json")) as f:
        entries = {e["id"]: e for e in json.load(f)["entries"]}
    dec = Decoder(json.load(open(os.path.join(REPO, "schema", "schema.json"))))
    results, n = load_results(out), 0
    seq_path = os.path.join(CORPUS, "sequences.json")
    listed_sequences = {x["id"]: x for x in json.load(open(seq_path))["sequences"]} if os.path.isfile(seq_path) else {}
    decoded = {}
    for k, r in sorted(results.items(), key=lambda kv: kv[0][0]):  # by entry: decode each ledger once
        path = os.path.join(HERE, r.get("evidence") or "-", "observation.json")
        if not os.path.isfile(path) or (r["entry_id"] not in entries and not r.get("sequence")):
            continue
        with open(path) as f:
            obs = json.load(f)
        if obs.get("adapter_failure"):
            continue
        if r.get("sequence"):
            members = r["sequence"]["members"]
            sq = dict(listed_sequences.get(k[0], {}), id=k[0],
                      _passphrase=entries[members[0]]["source"]["network_passphrase"])
            member_obs = {}
            for m in members:
                mp = os.path.join(HERE, r["evidence"], m, "observation.json")
                if os.path.isfile(mp):
                    member_obs[m] = json.load(open(mp))
            r["oracle"] = sequence_verdict(sq, obs, mapping, [_decode_entry(entries[m]) for m in members], member_obs)
            r["result"] = "pass" if r["oracle"]["verdict"] in ("pass", "not checked") else "mishandled"
            with open(os.path.join(HERE, r["evidence"], "result.json"), "w") as f:
                json.dump(r, f, indent=1)
            n += 1
            continue
        e = entries[r["entry_id"]]
        if e["id"] not in decoded:
            decoded = {e["id"]: dec.decode("LedgerCloseMeta", base64.b64decode(open(os.path.join(CORPUS, e["file"])).read()))}
        r["oracle"] = oracle_verdict(e, obs, mapping, decoded[e["id"]])
        with open(os.path.join(HERE, r["evidence"], "result.json"), "w") as f:
            json.dump(r, f, indent=1)
        n += 1
    save_results(out, results)
    print("rejudged %d results" % n)
    cmd_report(a)


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
    sequence_results = {k: r for k, r in results.items() if r.get("sequence")}
    for k in sorted(results):
        if k[0] not in entries and k not in sequence_results:
            entries.append(k[0])
    with_exp = [e for e in entries if any(r.get("expectations") for k, r in results.items() if k[0] == e)]
    without = [e for e in entries if e not in with_exp]
    name = adapter_of(out)
    mapping = adapter_mapping(name)
    intro = (sequence_results and getattr(mapping, "REPORT_INTRO_SEQUENCE", None)) or getattr(mapping, "REPORT_INTRO", None) or [
        "Each cell is the result for one entry at one commit, per input: `rpc` is the mock stellar-rpc",
        "`getLedgers` endpoint, `datalake` is the Galexie layout on an S3-compatible store. Every cell is a run",
        "of the indexer's own `ingest` command against PostgreSQL/TimescaleDB with the tables read back."]
    L = ["# Replay results: %s" % name if name != "wallet-backend" else "# Replay results", "",
         "Generated by `harness/replay/replay.py report --out %s` from `%s/results.jsonl`. Do not edit by hand."
         % (os.path.relpath(out, HERE), os.path.relpath(out, HERE)), ""] + list(intro) + ["",
         "A cell is the entry's verdict: the worse of the indexer's result against the manifest's expectations and",
         "the oracle's check of every row the ledger implies (`pass`, `dropped`: a row or the ledger is missing,",
         "`mishandled`: an error or a wrong stored value). After the colon: the upstream issues or records that",
         "explain the failures, or `unexplained` (a candidate new finding). The details below list each failure."]
    # REPORT_NOTES: what the adapter's mapping states about this indexer (coverage, declared choices).
    notes = list(getattr(mapping, "REPORT_NOTES", None) or [])
    if sequence_results:
        # A sequence: its ledgers are ingested in one run; the end-state checks are what it adds.
        notes = ["## Sequences", "",
                 "| Sequence | Ledgers | Commit | Input | End-state checks met | Known issues | Unexplained |",
                 "|---|---|---|---|---|---|---|"]
        for (sid, commit, inp), r in sorted(sequence_results.items()):
            o = r.get("oracle") or {}
            notes.append("| `%s` | %s | `%s` | %s | %d of %d | %s | %d |" % (
                sid, ", ".join("`%s`" % m for m in r["sequence"]["members"]), commit[:8], inp,
                o.get("rows_met", 0), o.get("rows_expected", 0),
                "; ".join("%d: %s" % (n, i) for i, n in sorted((o.get("known") or {}).items())) or "none",
                len(o.get("unexplained") or [])))
    L += ([""] + notes + [""] if notes else []) + [
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
                    cells.append(entry_verdict(r) if r else "not run")
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
        word = "not applicable" if r["result"] == "not applicable" else entry_verdict(r).split(":")[0]
        counts.setdefault((c, inp), {}).setdefault(word, 0)
        counts[(c, inp)][word] += 1
    na = any("not applicable" in n for n in counts.values())
    L.extend(["", "## Totals", "", "| Commit | Input | pass | mishandled | dropped | error |" + (" not applicable |" if na else ""),
              "|---|---|---|---|---|---|" + ("---|" if na else "")])
    for c in order:
        for inp in inputs:
            n = counts.get((c, inp))
            if n:
                L.append("| `%s` | %s | %d | %d | %d | %d |" % (c[:8], inp, n.get("pass", 0), n.get("mishandled", 0),
                                                              n.get("dropped", 0), n.get("error", 0))
                         + (" %d |" % n.get("not applicable", 0) if na else ""))
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
            claimed = {(x["entry"], x["commit"]): x["issue"] for x in json.load(f)["sightings"]
                       if x["expect"] != "pass" and x.get("adapter", "wallet-backend") == name}
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
    notes = sorted({r["note"] for r in results.values() if r["result"] == "not applicable"})
    if notes:
        L.extend(["`n/a` (not applicable): %d runs. %s" % (sum(r["result"] == "not applicable" for r in results.values()),
                                                         " ".join(n[0].upper() + n[1:] + "." for n in notes)), ""])
    for k in sorted(results, key=lambda k: (k[0], order.index(k[1]) if k[1] in order else 99, k[2])):
        r = results[k]
        if r["result"] in ("pass", "not applicable"):
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
            L.append("- evidence: `%s/` (%s)" % (r["evidence"], getattr(
                mapping, "EVIDENCE_FILES", "job.json, ingest.log, observation.json, result.json, feeder-requests.jsonl")))
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
    # The committed reports belong to the default output directories; any other (a sweep) keeps its
    # report next to its results.
    default = os.path.join(HERE, "out" if name == "wallet-backend" else "out-" + name)
    if os.path.abspath(out) == default:
        report = os.path.join(HERE, "RESULTS.md" if name == "wallet-backend" else "RESULTS-%s.md" % name)
    else:
        report = os.path.join(out, "RESULTS.md")
    with open(report, "w") as f:
        f.write("\n".join(L) + "\n")


def adapter_of(out):
    """The adapter whose runs are recorded in this out directory (wallet-backend if none are)."""
    path = os.path.join(out, "runs.jsonl")
    if os.path.isfile(path):
        with open(path) as f:
            names = {json.loads(x).get("adapter", "wallet-backend") for x in f if x.strip()}
        if len(names) == 1:
            return names.pop()
        if names:
            raise SystemExit("%s mixes adapters %s: use one --out directory per adapter" % (out, sorted(names)))
    return "wallet-backend"


def cmd_check(a):
    """Compare recorded results with the claims in sightings.json; exit 1 on any difference."""
    name = adapter_of(os.path.abspath(a.out))
    with open(os.path.join(HERE, "sightings.json")) as f:
        claims = [c for c in json.load(f)["sightings"] if c.get("adapter", "wallet-backend") == name]
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
    # Coverage: results for a ledger the manifest does not have fail; ledgers added to the corpus
    # after the run are only counted, so a new entry does not fail the check until the next rerun.
    with open(os.path.join(CORPUS, "manifest.json")) as f:
        ledgers = {e["id"] for e in json.load(f)["entries"] if e.get("xdr_type") == "LedgerCloseMeta"}
    # A sequence's own result is named after it; a member's result is ENTRY@SEQUENCE (in_sequence).
    covered = {k[0].split("@")[0] if r.get("in_sequence") else k[0] for k, r in results.items() if not r.get("sequence")}
    for e in sorted(covered - ledgers):
        print("NOT IN THE MANIFEST  %s has a recorded result but is no corpus ledger" % e)
        bad += 1
    print("coverage: %d of the manifest's %d ledgers have a recorded result here; %d have none yet"
          % (len(covered & ledgers), len(ledgers), len(ledgers - covered)))
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


def _failing(r):
    """A replay counts as failing when the indexer mishandled or dropped the ledger, or the oracle has
    a failure that no known issue explains, or one labelled as a defect wallet-backend later fixed
    (known.json `fixed_by`; the label maps it to a record, it is still a failure at that commit)."""
    return bool(_failures(r))


def _failures(r, fix=None):
    """The failures of one replay that bear on `fix` (a commit), counted by kind: the indexer's own
    result when it is not `pass`, the unexplained oracle failures, and the oracle failures of each
    known.json kind wallet-backend fixed in that commit. Failures attributed to another fix, or to an
    open issue, are left out: they say nothing about this one."""
    o = r.get("oracle") or {}
    out = {}
    if r["result"] in ("mishandled", "dropped"):
        out["indexer: " + r["result"]] = 1
    n = o.get("unexplained_count", len(o.get("unexplained") or []))
    if n:
        out["unexplained"] = n
    for kind, k in (o.get("fixed_upstream") or {}).items():
        if fix is None or (o.get("fixed_by") or {}).get(kind, "")[:8] == fix[:8]:
            out[kind] = k
    return out


def _fixed_by(parent, fix_result, fix):
    """A fix is detected on a ledger when the ledger has failures bearing on the fix at its parent and
    none at the fix. A fix that halts on a ledger its parent ingested never counts: the failure changed
    form, and the fix's oracle failures are unknown, not gone."""
    if parent.get("ingested", True) and not fix_result.get("ingested", True):
        return False
    return bool(_failures(parent, fix)) and not _failures(fix_result, fix)


def cmd_backtest(a):
    """Verify backtest.json against recorded results: every "detected" claim must show each named
    entry with failures bearing on the fix at the parent and none at the fix (_fixed_by), with the
    counts recorded in the claim (or, for an open issue with no fix, flagged
    with that issue at the commit named in "at"); every "missed" claim must have no recorded entry
    that does. Prints the table and K of N per pipeline; exits 1 on any claim that does not hold."""
    spec = json.load(open(os.path.join(HERE, "backtest.json")))
    results = {}
    for name, path in spec["results"].items():
        with open(os.path.join(HERE, path)) as f:
            for line in f:
                r = json.loads(line)
                # a ledger replayed inside a sequence is a member of that sequence's claim, not a claim
                results[(name, r["commit"][:8], r["entry_id"] + ("@" + r["in_sequence"] if r.get("in_sequence") else ""))] = r
    bad, tally = 0, {}
    for it in spec["items"]:
        ok = True
        if it["verdict"] == "out_of_scope":
            flips = []
        elif it.get("at"):
            # An open issue with no fix to compare: detected means the oracle flagged its rows at this commit.
            at = it["at"][:8]
            flips = sorted("%s:%s" % (src, e) for (src, c, e), r in results.items()
                           if c == at and it["issue"] in ((r.get("oracle") or {}).get("known") or {}))
        else:
            p, f = it["parent"][:8], it["fix"][:8]
            flips = sorted("%s:%s" % (src, e) for (src, c, e), r in results.items()
                           if c == p and "@" not in e and (src, f, e) in results and _fixed_by(r, results[(src, f, e)], f))
            counts = {"%s:%s" % (src, e): {"parent": _failures(r, f), "fix": _failures(results[(src, f, e)], f)}
                      for (src, c, e), r in results.items() if c == p and (src, f, e) in results}
        if it["verdict"] == "detected":
            for claim in it["entries"]:
                key = "%s:%s" % (claim["results"], claim["entry"])
                ok &= key in flips
                if "parent" in claim and not it.get("at"):  # the recorded counts must be the replays'
                    ok &= counts.get(key) == {"parent": claim["parent"], "fix": claim["fix"]}
        elif it["verdict"] == "missed":
            ok = not flips
        t = tally.setdefault(it["pipeline"], {"detected": 0, "blind": 0, "in_scope": 0})
        if it["verdict"] in ("detected", "missed"):
            t["in_scope"] += 1
        if it["verdict"] == "detected":
            t["detected"] += 1
            t["blind"] += any(c.get("blind") for c in it["entries"])
        bad += not ok
        print("%-8s %-14s %-24s %-9s %s" % ("ok" if ok else "DIFFERS", it["pipeline"], it["id"], it["verdict"],
                                           ", ".join(flips)[:120] if it["verdict"] != "out_of_scope" else it["reason"][:90]))
    for k, t in tally.items():
        print("%s: detected %d of %d in-scope fixes (%d with a blind entry)" % (k, t["detected"], t["in_scope"], t["blind"]))
    print("BACKTEST OK" if not bad else "%d BACKTEST CLAIM(S) DO NOT HOLD" % bad)
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
    p.add_argument("--protocols", help="protocol IDs to produce, comma-separated (wallet-backend: SEP41,BLEND): "
                                       "the adapter runs the commit's protocol-setup and sets the protocol cursors")
    p.add_argument("--sequence", help="names in corpus/sequences.json, comma-separated: each is ingested in one "
                                      "run into one database, judged per ledger and at the end")
    p.add_argument("--max-protocol", type=int)
    p.add_argument("--proposed", help="JSON file of expectations proposed for the manifest; results are labelled")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--keep", action="store_true", help="leave the containers running")
    p.add_argument("--work", default=os.environ.get("REPLAY_WORK", os.path.join(HERE, ".work")))
    p.add_argument("--out", default=os.path.join(HERE, "out"))
    p.add_argument("--corpus", help="a corpus directory (manifest.json, entries/) other than corpus/")
    p = sub.add_parser("report")
    p.add_argument("--out", default=os.path.join(HERE, "out"))
    sub.add_parser("backtest")
    p = sub.add_parser("rejudge")
    p.add_argument("--out", default=os.path.join(HERE, "out"))
    p.add_argument("--corpus", help="the corpus directory the results were run from")
    p = sub.add_parser("check")
    p.add_argument("--out", default=os.path.join(HERE, "out"))
    p.add_argument("--oracle", action="store_true", help="also fail on unexplained oracle failures")
    a = ap.parse_args()
    {"run": cmd_run, "report": cmd_report, "rejudge": cmd_rejudge, "check": cmd_check,
     "backtest": cmd_backtest}[a.verb](a)


if __name__ == "__main__":
    main()
