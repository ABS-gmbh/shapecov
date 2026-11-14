"""Compare every SDK's results with the reference decoder and cluster the disagreements.

Usage: diff.py out/cases.jsonl  ->  out/divergences.jsonl, out/REPORT.md
"""
import collections
import json
import re
import sys
from pathlib import Path

REF = "rust"


def load(path):
    d = {}
    for l in path.open():
        p = l.rstrip("\n").split("\t", 2)
        if len(p) == 3:
            d[p[0]] = (p[1], p[2])
    return d


def norm(msg):
    msg = re.sub(r"0x[0-9a-fA-F]+|\d+", "N", msg)
    return re.sub(r"\s+", " ", msg)[:110]


def main():
    cases_path = Path(sys.argv[1])
    out = cases_path.parent
    cases = {}
    for l in cases_path.open():
        r = json.loads(l)
        cases[r["id"]] = r
    versions = json.load(open(out / "versions.json"))
    sdks = [s for s in versions if (out / f"res.{s}.tsv").exists()]
    res = {s: load(out / f"res.{s}.tsv") for s in sdks}
    ref = res[REF]

    matrix = collections.defaultdict(lambda: collections.Counter())
    clusters = collections.defaultdict(list)
    div = []
    ref_notes = collections.Counter()
    for cid, c in cases.items():
        kind = "valid" if c["valid"] else c["fault"]["kind"]
        rst, rpl = ref.get(cid, ("missing", ""))
        if rst == "notype":
            continue
        if c["valid"] and not (rst == "ok" and rpl == c["b64"]):
            ref_notes[f"generator/reference disagree on a valid case ({rst})"] += 1
            continue
        if not c["valid"] and rst == "ok":
            ref_notes[f"reference accepts fault {kind}"] += 1
        for s in sdks:
            if s == REF:
                continue
            st, pl = res[s].get(cid, ("missing", ""))
            if st == "notype":
                matrix[kind][(s, "unsupported")] += 1
                continue
            if st in ("crash", "hang", "panic"):
                cls = st
            elif rst == "ok":
                if st == "ok":
                    cls = "agree" if pl == rpl else "reencodes_differently"
                else:
                    cls = "rejects_valid"
            else:
                cls = "agree" if st != "ok" else "accepts_invalid"
            matrix[kind][(s, cls)] += 1
            if cls == "agree":
                continue
            sig = c["fault"]["site"] if not c["valid"] and cls == "accepts_invalid" else norm(pl)
            sig = norm(sig) if cls == "accepts_invalid" else sig
            key = (s, cls, kind, sig)
            clusters[key].append(cid)
            div.append({"id": cid, "sdk": s, "class": cls, "kind": kind, "type": c["type"],
                        "fault": c.get("fault"), "tags": c["tags"], "input": c["b64"],
                        "reference": {"status": rst, "payload": rpl[:400]},
                        "sdk_result": {"status": st, "payload": pl[:400]}})
    with open(out / "divergences.jsonl", "w") as f:
        for d in div:
            f.write(json.dumps(d) + "\n")

    kinds = ["valid"] + sorted(k for k in matrix if k != "valid")
    others = [s for s in sdks if s != REF]
    cells = json.load(open(str(cases_path) + ".cells.json"))
    L = ["# Differential run report", "",
         f"Cases: {len(cases)} generated from the Protocol 30 XDR schema (stellar-xdr v30.0). "
         f"Reference decoder: {versions[REF]}.", "",
         f"Schema cells exercised by valid cases (union arms and enum members): "
         f"{len(cells['hit'])} of {len(cells['total'])} ({100 * len(cells['hit']) / len(cells['total']):.1f}%).", "",
         "## Disagreements with the reference, by case kind", "",
         "Each cell is `disagreements / cases run` for that SDK. `valid` rows are values the reference "
         "decodes and re-encodes byte-for-byte; the other rows carry one injected fault.", "",
         "| Case kind | " + " | ".join(f"{s} ({versions[s]})" for s in others) + " |",
         "|---|" + "---|" * len(others)]
    for k in kinds:
        row = [k]
        for s in others:
            tot = sum(v for (ss, cls), v in matrix[k].items() if ss == s and cls != "unsupported")
            bad = sum(v for (ss, cls), v in matrix[k].items() if ss == s and cls not in ("agree", "unsupported"))
            row.append(f"{bad} / {tot}")
        L.append("| " + " | ".join(row) + " |")
    L += ["", "## Reference notes", ""]
    L += [f"- {k}: {v}" for k, v in sorted(ref_notes.items())] or ["- none"]
    L += ["", "## Clusters", "",
          "Disagreements grouped by SDK, class, case kind and message or fault site. "
          "A cluster is a lead to triage, not a confirmed bug.", "",
          "| SDK | Class | Case kind | Signature | Cases | Example |", "|---|---|---|---|---|---|"]
    for (s, cls, kind, sig), ids in sorted(clusters.items(), key=lambda kv: (kv[0][0], kv[0][1], -len(kv[1]))):
        L.append(f"| {s} | {cls} | {kind} | `{sig.replace('|', '/')}` | {len(ids)} | `{ids[0]}` |")
    (out / "REPORT.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:9 + 6 + len(kinds)]))
    print(f"\nclusters: {len(clusters)}  divergent results: {len(div)}")


if __name__ == "__main__":
    main()
