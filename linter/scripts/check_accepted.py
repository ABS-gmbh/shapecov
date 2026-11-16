#!/usr/bin/env python3
"""Compare a linter report with a file of accepted findings.

    check_accepted.py REPORT.json ACCEPTED.json

Exit status 0 when every finding in the report is listed in ACCEPTED.json, 1 when at least one is
not (a new finding to triage), 2 when either file is malformed. An accepted entry that matches no
finding is printed as resolved: the code changed upstream, so remove the entry.

An entry matches a finding when the rule and file are equal and the finding's message contains
the entry's message_contains. Line numbers are not compared, so unrelated edits upstream do not
break the match. Every entry must give a non-empty reason.
"""
import json
import sys


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("cannot read %s: %s" % (path, e))
        sys.exit(2)


def main():
    if len(sys.argv) != 3:
        print(__doc__.strip())
        return 2
    report, accepted = load(sys.argv[1]), load(sys.argv[2])
    findings = report.get("findings")
    entries = accepted.get("accepted")
    if not isinstance(findings, list) or not isinstance(entries, list):
        print("malformed input: the report needs a findings list and the accepted file an accepted list")
        return 2
    for i, e in enumerate(entries):
        missing = [k for k in ("rule", "file", "message_contains", "reason") if not e.get(k)]
        if missing:
            print("accepted entry %d lacks %s" % (i, ", ".join(missing)))
            return 2
    if report.get("load_errors"):
        print("the linter reported %d package load errors; the report is incomplete" % report["load_errors"])
        return 2

    used = [0] * len(entries)
    new = []
    for f in findings:
        hit = [i for i, e in enumerate(entries)
               if e["rule"] == f["rule"] and e["file"] == f["file"] and e["message_contains"] in f["message"]]
        if hit:
            for i in hit:
                used[i] += 1
        else:
            new.append(f)

    print("%d findings: %d accepted, %d not accepted" % (len(findings), len(findings) - len(new), len(new)))
    for i, e in enumerate(entries):
        where = "%s %s (%s)" % (e["rule"], e["file"], e["message_contains"])
        if used[i]:
            print("  accepted  %s: %s" % (where, e.get("upstream") or "no upstream issue; see reason"))
        else:
            print("  resolved  %s: matches no finding, remove the entry" % where)
    for f in new:
        print("  NEW       %s %s:%d: %s" % (f["rule"], f["file"], f["line"], f["message"]))
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
