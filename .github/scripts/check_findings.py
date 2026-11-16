#!/usr/bin/env python3
"""RFP check 6: every failure maps to a finding, and every finding is a complete record.

  python3 .github/scripts/check_findings.py           check
  python3 .github/scripts/check_findings.py --write   also regenerate the table in FINDINGS.md

FINDINGS.json holds one record per finding, in the form the RFP asks for. This script fails when:
- a record lacks a field, has an unknown kind or severity, names no CAP and gives no reason, or
  has a date that is not YYYY-MM-DD;
- a record's reproduction does not exist: a corpus entry missing from corpus/manifest.json, a
  generated case missing from out/cases.jsonl (or that the named runner does not accept, per
  out/divergences.jsonl), or a
  file that is not in the repository;
- an oracle failure in the committed replay results of either indexer (harness/replay/out*/
  results.jsonl) carries a label no record claims, or is unexplained and is not an RFP sighting
  that harness/replay/sightings.json claims fails at that pre-fix commit. A known.json rule may
  label a failure `record:<ID>` to map it to a record that has no filed issue; those are counted
  and printed apart from the failures that map to a filed issue;
- a claimed sighting, a reproduced sighting in harness/sightings/README.md, or an accepted linter
  finding (linter/accepted/<indexer>.json) maps to no record;
- a label names an issue that is not among the record's upstream links;
- the table at the top of FINDINGS.md differs from what this script generates.
Run from the repository root.
"""
import glob
import json
import os
import re
import sys

FINDINGS_JSON = "FINDINGS.json"
FINDINGS_MD = "FINDINGS.md"
BEGIN = "<!-- findings-table:begin (generated from FINDINGS.json by .github/scripts/check_findings.py --write; do not edit by hand) -->"
END = "<!-- findings-table:end -->"
REQUIRED = ("id", "kind", "title", "component", "severity", "caps", "reproduction", "upstream",
            "first_reported_by", "reported", "status", "labels")
REPRO_KEYS = ("corpus_entry", "generated_case", "evidence_file", "linter_report")
ISSUE = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)")
URL = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/(issues|pull|commit)/(\d+|[0-9a-f]{40})$")
CAP = re.compile(r"^CAP-\d{4}(-\d{2})?$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RESULTS = ("harness/replay/out", "harness/replay/out-stellar-etl", "harness/replay/out-horizon")
REFERENCE = "rust"  # the conformance runner's reference decoder


def load_json(path):
    with open(path) as f:
        return json.load(f)


def short_ref(url):
    m = URL.match(url)
    if not m:
        return url
    if m.group(3) == "commit":
        return "%s/%s@%s" % (m.group(1), m.group(2), m.group(4)[:7])
    return "%s/%s#%s" % (m.group(1), m.group(2), m.group(4))


_DIVERGENCES = None


def runner_status(case_id, runner):
    """A runner's result on a generated case, from out/divergences.jsonl ('ok', 'err' or None)."""
    global _DIVERGENCES
    if _DIVERGENCES is None:
        with open("out/divergences.jsonl") as f:
            _DIVERGENCES = [json.loads(line) for line in f]
    for d in _DIVERGENCES:
        if d["id"] != case_id:
            continue
        if runner == REFERENCE:
            return d["reference"]["status"]
        if d["sdk"] == runner:
            return d["sdk_result"]["status"]
    return None


def validate_records(doc, bad):
    """Field and reproduction checks. Returns {label: record id}."""
    levels = {s["level"] for s in doc["severity_scale"]}
    kinds = doc["kinds"]
    manifest = load_json("corpus/manifest.json")
    entries = {e["id"] for e in (manifest["entries"] if isinstance(manifest, dict) else manifest)}
    cases = {}
    with open("out/cases.jsonl") as f:
        for line in f:
            c = json.loads(line)
            cases[c["id"]] = c
    seen, label_owner = set(), {}
    for r in doc["findings"]:
        rid = r.get("id", "?")
        for k in REQUIRED:
            if k not in r:
                bad.append("%s: missing field %r" % (rid, k))
        if rid in seen:
            bad.append("%s: duplicate id" % rid)
        seen.add(rid)
        if r.get("kind") not in kinds:
            bad.append("%s: kind %r is not one of %s" % (rid, r.get("kind"), sorted(kinds)))
        if r.get("severity") not in levels:
            bad.append("%s: severity %r is not one of %s" % (rid, r.get("severity"), sorted(levels)))
        for k in ("title", "component", "first_reported_by", "status"):
            if k in r and not str(r[k]).strip():
                bad.append("%s: field %r is empty" % (rid, k))
        caps = r.get("caps", [])
        if not caps and not str(r.get("caps_none_reason", "")).strip():
            bad.append("%s: no CAP and no caps_none_reason" % rid)
        for c in caps:
            if not CAP.match(c):
                bad.append("%s: %r is not a CAP number such as CAP-0067 or CAP-0046-01" % (rid, c))
        if "reported" in r and not DATE.match(r["reported"]):
            bad.append("%s: reported %r is not YYYY-MM-DD" % (rid, r["reported"]))
        ups = r.get("upstream", [])
        if not ups and r.get("kind") not in ("linter", "unfiled"):
            bad.append("%s: no upstream link (only an accepted linter finding or an unfiled one may have none)" % rid)
        for u in ups:
            if not URL.match(u):
                bad.append("%s: upstream %r is not a GitHub issue, pull request or full-SHA commit URL" % (rid, u))
        rep = r.get("reproduction", {})
        if not any(k in rep for k in REPRO_KEYS):
            bad.append("%s: reproduction names none of %s" % (rid, ", ".join(REPRO_KEYS)))
        for e in ([rep["corpus_entry"]] if "corpus_entry" in rep else []) + rep.get("also", []):
            if e not in entries:
                bad.append("%s: corpus entry %r is not in corpus/manifest.json" % (rid, e))
        if "generated_case" in rep:
            c = cases.get(rep["generated_case"])
            if c is None:
                bad.append("%s: generated case %r is not in out/cases.jsonl" % (rid, rep["generated_case"]))
            elif "runner" in rep:
                # The case is invalid by construction; the finding is that this runner accepts it.
                # out/divergences.jsonl (committed) records every case on which a runner differs
                # from the reference decoder, rs-stellar-xdr; the reference's own result rides along.
                verdict = runner_status(c["id"], rep["runner"])
                if c.get("valid") or verdict != "ok":
                    bad.append("%s: %s does not reproduce: valid=%s, the %s runner's result is %r"
                               % (rid, c["id"], c.get("valid"), rep["runner"], verdict))
        for k in ("evidence_file", "linter_report"):
            if k in rep and not os.path.exists(rep[k]):
                bad.append("%s: %s %r does not exist" % (rid, k, rep[k]))
        for label in r.get("labels", []):
            if label in label_owner:
                bad.append("%s: label %r is already claimed by %s" % (rid, label, label_owner[label]))
            label_owner[label] = rid
            m = ISSUE.match(label)
            if m and not any(short_ref(u) == m.group(0) for u in ups):
                bad.append("%s: label %r names an issue that is not among its upstream links" % (rid, label))
    return label_owner


def check_failures(doc, label_owner, bad):
    """Every oracle failure in the committed results maps to a record."""
    sightings = load_json("harness/replay/sightings.json")["sightings"]
    claimed = {(s["entry"], s["commit"], s.get("adapter", "wallet-backend")): s["issue"]
               for s in sightings if s["expect"] != "pass"}
    rule_labels = set()
    for adapter in os.listdir("harness/replay/adapters"):
        p = "harness/replay/adapters/%s/known.json" % adapter
        if os.path.exists(p):
            rule_labels |= {rule["issue"] for rule in load_json(p)["rules"]}
    labelled = unexplained_claimed = unfiled = 0
    used = set()
    record_ids = {r.get("id") for r in doc["findings"]}
    for out in RESULTS:
        with open(out + "/results.jsonl") as f:
            for line in f:
                r = json.loads(line)
                o = r.get("oracle")
                if not o:
                    continue
                where = "%s at %s (%s, %s)" % (r["entry_id"], r["commit"][:12], r["adapter"], r["input"])
                for label, n in o["known"].items():
                    used.add(label)
                    if label.startswith("record:"):
                        # A failure explained by a record that has no filed issue (a design choice,
                        # for example). Counted apart, so "maps to a filed issue" stays exact.
                        if label[len("record:"):] not in record_ids:
                            bad.append("%s: label %r names no record in FINDINGS.json" % (where, label))
                        unfiled += n
                        continue
                    labelled += n
                    if not ISSUE.match(label):
                        bad.append("%s: label %r is not an issue reference" % (where, label))
                    elif label not in label_owner:
                        bad.append("%s: %d failure(s) labelled %r, which no record in FINDINGS.json claims"
                                   % (where, n, label))
                if o["unexplained"]:
                    key = (r["entry_id"], r["commit"], r["adapter"])
                    if key in claimed:
                        unexplained_claimed += len(o["unexplained"])
                        used.add(claimed[key])
                    else:
                        bad += ["%s: %s" % (where, u[:160]) for u in o["unexplained"]]
    for s in sightings:
        if s["expect"] != "pass" and s["issue"] not in label_owner:
            bad.append("sighting %s at %s (%r) maps to no record" % (s["entry"], s["commit"][:12], s["issue"]))
    known_labels = rule_labels | set(claimed.values())
    for label, rid in label_owner.items():
        if label not in known_labels:
            bad.append("%s: label %r is neither a known.json rule nor a claimed sighting" % (rid, label))
    unused_rules = sorted(rule_labels - used - set(label_owner) - {l for l in rule_labels if l.startswith("record:")})
    return labelled, unexplained_claimed, unfiled, unused_rules


def check_rfp_sightings(doc, bad):
    """Every sighting harness/sightings/README.md marks reproduced has a record."""
    by_row = {r["rfp_sighting"]: r.get("id") for r in doc["findings"] if "rfp_sighting" in r}
    exempt = {int(k) for k in doc.get("sightings_without_record", {})}
    reproduced = []
    with open("harness/sightings/README.md") as f:
        for line in f:
            cells = [c.strip() for c in line.split("|")]
            if len(cells) > 4 and cells[1].isdigit() and cells[3] == "reproduced":
                reproduced.append(int(cells[1]))
    for n in reproduced:
        if n not in by_row and n not in exempt:
            bad.append("RFP sighting %d is reproduced (harness/sightings/README.md) but no record has rfp_sighting %d" % (n, n))
    for n, rid in by_row.items():
        if n not in reproduced:
            bad.append("%s: rfp_sighting %d is not marked reproduced in harness/sightings/README.md" % (rid, n))
    return len(reproduced), len([n for n in reproduced if n in exempt])


def check_linter(doc, bad):
    """Every accepted linter finding, for every indexer the linter runs on (linter/accepted/<name>.json),
    has a record whose linter report is for that indexer, with the same upstream link."""
    owner = {}
    for r in doc["findings"]:
        rep = r.get("reproduction", {})
        target = re.sub(r"-[0-9a-f]{12}\.json$", "", os.path.basename(rep.get("linter_report", "")))
        for m in rep.get("accepted", []):
            owner[(target, m)] = r
    n = 0
    for path in sorted(glob.glob("linter/accepted/*.json")):
        target = os.path.basename(path)[:-len(".json")]
        for a in load_json(path)["accepted"]:
            n += 1
            r = owner.get((target, a["message_contains"]))
            if r is None:
                bad.append("accepted %s linter finding %s %r maps to no record" % (target, a["rule"], a["message_contains"]))
            elif a.get("upstream") and a["upstream"] not in r.get("upstream", []):
                bad.append("%s: accepted linter finding cites %s, which the record does not" % (r.get("id"), a["upstream"]))
    return n


def cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def render(doc):
    scale = {s["level"]: s["name"] for s in doc["severity_scale"]}
    lines = [BEGIN, ""]
    counts = {}
    for r in doc["findings"]:
        counts[r.get("kind")] = counts.get(r.get("kind"), 0) + 1
    lines.append("%d findings in `FINDINGS.json`, one record each. Severity: %s. Dates are UTC."
                 % (len(doc["findings"]), "; ".join("**%s** %s" % (k, v) for k, v in scale.items())))
    for kind, heading in doc["kinds"].items():
        rows = [r for r in doc["findings"] if r.get("kind") == kind]
        if not rows:
            continue
        lines += ["", "**%s** (%d)" % (heading[0].upper() + heading[1:], len(rows)), "",
                  "| ID | Finding | Component | Severity | CAPs | Reproduction | Upstream | First reported | Status |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            # Tolerates an incomplete record: validate_records() has already reported what is missing.
            rep = r.get("reproduction", {})
            repro = []
            if "corpus_entry" in rep:
                repro.append("entry `%s`" % rep["corpus_entry"])
            if "generated_case" in rep:
                repro.append("case `%s`" % rep["generated_case"])
            for k in ("evidence_file", "linter_report"):
                if k in rep:
                    repro.append("`%s`" % rep[k])
            sev = r.get("severity", "?") + ("; " + r["severity_note"] if r.get("severity_note") else "")
            caps = ", ".join(r.get("caps") or []) or "none: " + r.get("caps_none_reason", "?")
            ups = ", ".join("[%s](%s)" % (short_ref(u), u) for u in r.get("upstream", [])) or "not filed"
            first = "%s, %s" % (r.get("first_reported_by", "?"), r.get("reported", "?"))
            lines.append("| " + " | ".join(cell(r.get(k, "?")) for k in ("id", "title", "component")) + " | "
                         + " | ".join(cell(x) for x in (sev, caps, "; ".join(repro), ups, first, r.get("status", "?")))
                         + " |")
    lines += ["", END]
    return "\n".join(lines)


def main():
    write = "--write" in sys.argv[1:]
    doc = load_json(FINDINGS_JSON)
    bad = []
    label_owner = validate_records(doc, bad)
    labelled, claimed, unfiled, unused_rules = check_failures(doc, label_owner, bad)
    n_sightings, n_exempt = check_rfp_sightings(doc, bad)
    n_accepted = check_linter(doc, bad)

    with open(FINDINGS_MD) as f:
        md = f.read()
    table = render(doc)
    if BEGIN in md and END in md:
        new_md = md[:md.index(BEGIN)] + table + md[md.index(END) + len(END):]
    else:
        bad.append("FINDINGS.md has no generated table (markers missing); run with --write after adding them")
        new_md = md
    if new_md != md:
        if write:
            with open(FINDINGS_MD, "w") as f:
                f.write(new_md)
            print("FINDINGS.md: table regenerated")
        else:
            bad.append("FINDINGS.md: the table differs from FINDINGS.json; run "
                       "python3 .github/scripts/check_findings.py --write")

    print("records in FINDINGS.json: %d (%s)" % (len(doc["findings"]), ", ".join(
        "%d %s" % (sum(1 for r in doc["findings"] if r.get("kind") == k), k) for k in doc["kinds"])))
    print("oracle failures labelled with a filed issue that a record claims: %d" % labelled)
    print("failures that are a claimed RFP sighting at its pre-fix commit: %d" % claimed)
    print("failures mapped to a record with no filed issue (label record:<ID>): %d" % unfiled)
    print("reproduced RFP sightings: %d, %d with a record, %d exempt with a reason (sightings_without_record)"
          % (n_sightings, n_sightings - n_exempt, n_exempt))
    print("accepted linter findings with a record: %d" % n_accepted)
    if unused_rules:
        print("known.json rules no committed failure matches yet, with no record: %s" % ", ".join(unused_rules))
    print("problems: %d" % len(bad))
    for b in bad:
        print("  " + b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
