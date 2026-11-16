#!/usr/bin/env python3
"""Open one issue per upstream release that is newer than ShapeCov's pin.

  upstream_drift.py [--dry-run]

Reads each pin from the file that holds it, asks GitHub for the upstream's latest release (or
latest tag, for stellar-xdr), and for every upstream that has moved, opens an issue in this
repository titled "Upstream release: <name> <latest> (pinned <pin>)". It skips an upstream if an
issue with that title already exists, open or closed. The issue carries the matching checklist
from MAINTENANCE.md: the protocol-upgrade runbook for stellar-core and stellar-xdr, the
SDK-release steps for the SDKs. Uses the `gh` CLI; in GitHub Actions it needs `issues: write`.
--dry-run prints what it would open.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path, pattern):
    m = re.search(pattern, (ROOT / path).read_text(), re.M)
    if not m:
        raise SystemExit("pin not found: %s /%s/" % (path, pattern))
    return m.group(1)


PINS = [
    ("stellar-core", "stellar/stellar-core", "release", "protocol",
     lambda: read("tools/corpus_check.py", r'^CORE_IMAGE = "stellar/stellar-core:(\d+\.\d+\.\d+)'), "tools/corpus_check.py"),
    ("stellar-xdr", "stellar/stellar-xdr", "tag", "protocol",
     lambda: read("schema/SOURCE", r"^x/\s+stellar/stellar-xdr\s+(v\S+)"), "schema/SOURCE"),
    ("rs-stellar-xdr", "stellar/rs-stellar-xdr", "release", "sdk",
     lambda: read("runners/rust/Cargo.toml", r'stellar-xdr = \{ version = "=([^"]+)"'), "runners/rust/Cargo.toml"),
    ("js-stellar-sdk", "stellar/js-stellar-sdk", "release", "sdk",
     lambda: read("runners/js/package.json", r'"@stellar/stellar-sdk": "([^"]+)"'), "runners/js/package.json"),
    ("py-stellar-base", "StellarCN/py-stellar-base", "release", "sdk",
     lambda: read(".github/workflows/ci.yml", r"pip install stellar-sdk==(\S+)"), ".github/workflows/ci.yml"),
    ("py-stellar-xdr", "lightsail-network/py-stellar-xdr", "release", "sdk",
     lambda: read("runners/python-xdr/requirements.txt", r"^stellar-xdr==(\S+)"), "runners/python-xdr/requirements.txt"),
    ("go-stellar-sdk", "stellar/go-stellar-sdk", "release", "sdk",
     lambda: read("runners/go/build.sh", r"github\.com/stellar/go-stellar-sdk@(v\S+)"), "runners/go/build.sh"),
    ("java-stellar-sdk", "lightsail-network/java-stellar-sdk", "release", "sdk",
     lambda: read("runners/java/pom.xml", r"<artifactId>stellar-sdk</artifactId><version>([^<]+)</version>"),
     "runners/java/pom.xml"),
]


def gh(args):
    return subprocess.run(["gh"] + args, capture_output=True, text=True, check=True).stdout


def latest(repo, kind):
    if kind == "release":
        return json.loads(gh(["api", "repos/%s/releases/latest" % repo]))["tag_name"]
    tags = [t["name"] for t in json.loads(gh(["api", "repos/%s/tags?per_page=100" % repo]))]
    tags = [t for t in tags if re.fullmatch(r"v\d+\.\d+(\.\d+)?", t)]
    return max(tags, key=lambda t: tuple(int(x) for x in t[1:].split(".")))


def norm(v):
    return v.lstrip("v")


def checklist(kind):
    text = (ROOT / "MAINTENANCE.md").read_text()
    if kind == "protocol":
        part = text.split("## Protocol upgrade", 1)[1].split("\n## ", 1)[0]
        steps = re.findall(r"^(\d+)\. \*\*(.+?)\*\*", part, re.M)
        return "\n".join("- [ ] %s. %s" % s for s in steps)
    part = text.split("**New SDK releases.**", 1)[1].split("\n- **", 1)[0]
    steps = re.findall(r"^\s+(\d+)\. (.+)$", part, re.M)
    return "\n".join("- [ ] %s. %s" % s for s in steps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    existing = {i["title"] for i in json.loads(gh(["issue", "list", "--state", "all", "--limit", "500",
                                                    "--search", "Upstream release: in:title", "--json", "title"]))}
    opened = 0
    for name, repo, kind, steps, pinned_fn, pin_file in PINS:
        pinned, new = pinned_fn(), latest(repo, kind)
        if norm(new) == norm(pinned):
            print("%-18s pinned %-10s latest %-10s current" % (name, pinned, new))
            continue
        title = "Upstream release: %s %s (pinned %s)" % (name, new, pinned)
        if title in existing:
            print("%-18s pinned %-10s latest %-10s issue exists" % (name, pinned, new))
            continue
        what = "a new protocol" if steps == "protocol" else "an SDK release"
        body = ("%s has %s, `%s`. ShapeCov pins `%s` in `%s`.\n\nRelease: https://github.com/%s/%s/%s\n\n"
                "Checklist, from [MAINTENANCE.md](../blob/main/MAINTENANCE.md):\n\n%s\n\n"
                "Opened by the upstream-drift workflow (`.github/workflows/upstream-drift.yml`)."
                % (name, what, new, pinned, pin_file, repo, "releases/tag" if kind == "release" else "tree", new,
                   checklist(steps)))
        if a.dry_run:
            print("%-18s pinned %-10s latest %-10s WOULD OPEN: %s" % (name, pinned, new, title))
            print("  " + body.replace("\n", "\n  "))
        else:
            gh(["issue", "create", "--title", title, "--body", body])
            print("%-18s pinned %-10s latest %-10s opened: %s" % (name, pinned, new, title))
        opened += 1
    print("%d upstream release(s) newer than the pins" % opened)
    return 0


if __name__ == "__main__":
    sys.exit(main())
