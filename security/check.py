#!/usr/bin/env python3
"""Static security checks of the repository. Standard library only; no Docker, no network.

  python3 security/check.py

Fails (exit 1) when:
- images: the code names a Docker image tag that security/images.lock.json does not pin by
  digest, uses the tag `latest`, or the lock has an entry no code names and no `named_by` explains;
- actions: a workflow or the linter's composite action uses a third-party action by tag or branch
  instead of a full 40-character commit SHA;
- permissions: a workflow has no top-level `permissions:`, grants `write-all`, or grants a write
  permission that is not in ALLOWED_WRITES below (INFRASTRUCTURE.md lists the same);
- triggers: a workflow runs on `pull_request_target`, which gives a fork's code the base
  repository's token and secrets, or a workflow that can write runs on `pull_request`;
- secrets: a workflow references `secrets.*` (the test workflows need none; the two that write use
  the job's own `github.token`);
- action owners: an action comes from outside ACTION_OWNERS (GitHub's own `actions/`);
- evidence: a recorded result, report or log names a home directory (`/Users/<name>`,
  `/home/<name>`), which would publish who ran it and where;
- networks: code creates a Docker network without `--internal`, which would give third-party code
  run on it a route to the internet (security/isolation.py tests the route itself, with Docker);
- injection: a `run:` script interpolates `${{ github.event.* }}` or `${{ github.head_ref }}`,
  text an outside contributor controls. Pass such values through `env:` instead.
Run from the repository root. THREAT-MODEL.md says which threat each check addresses.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "security/images.lock.json"
CODE = re.compile(r"(\.py|\.sh|\.ya?ml|\.mjs|\.js|Dockerfile[^/]*)$")
SKIP = re.compile(r"^(tests/|security/|.*node_modules/)")
IMAGE = re.compile(r"(?<![\w./-])((?:[a-z0-9][a-z0-9_.-]*/)?(?:golang|python|node|maven|rust|ubuntu|debian|alpine|postgres|"
                   r"redis|eclipse-temurin|openjdk|stellar-core|quickstart|timescaledb(?:-ha)?|minio)):"
                   r"(latest|\d[A-Za-z0-9._-]*[A-Za-z0-9])")
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
ALLOWED_WRITES = {
    ("release.yml", "contents"), ("release.yml", "id-token"), ("release.yml", "attestations"),
    ("upstream-drift.yml", "issues"),
}
ACTION_OWNERS = {"actions"}
EVIDENCE = ("harness/replay/out", "harness/replay/out-stellar-etl", "harness/replay/out-horizon", "harness/replay/backtest", "linter/results", "out/",
            "protocol-drill/", "sdk-matrix/", "guide/probes.json", "corpus/")
HOME = re.compile(r"/(Users|home)/[a-z][a-z0-9._-]+/")
UNTRUSTED = re.compile(r"\$\{\{[^}]*\b(github\.event\.|github\.head_ref)")


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if CODE.search(p) and not SKIP.match(p)]


def check_images(files, bad):
    lock = json.loads(LOCK.read_text())["images"]
    for tag, e in lock.items():
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", e.get("digest", "")):
            bad.append("images.lock.json: %s has no sha256 digest" % tag)
    named = set()
    for p in files:
        for n, line in enumerate((ROOT / p).read_text(errors="replace").splitlines(), 1):
            for m in IMAGE.finditer(line):
                ref = "%s:%s" % (m.group(1), m.group(2))
                named.add(ref)
                if m.group(2) == "latest":
                    bad.append("%s:%d: image %s uses the tag latest" % (p, n, ref))
                elif ref not in lock:
                    bad.append("%s:%d: image %s is not pinned in security/images.lock.json" % (p, n, ref))
    for tag, e in lock.items():
        if tag not in named and not e.get("named_by"):
            bad.append("images.lock.json: %s is named by no code and no named_by says who names it" % tag)
    return len(lock), len(named)


NETWORK_CREATE = re.compile(r"""network["',\s]+create""")


def check_networks(files, bad):
    n = 0
    for p in files:
        for i, line in enumerate((ROOT / p).read_text(errors="replace").splitlines(), 1):
            if NETWORK_CREATE.search(line) and not line.lstrip().startswith("#"):
                n += 1
                if "--internal" not in line:
                    bad.append("%s:%d: a Docker network is created without --internal" % (p, i))
    return n


def check_workflows(bad):
    files = sorted((ROOT / ".github/workflows").glob("*.yml")) + [ROOT / "linter/action.yml"]
    actions = 0
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        lines = f.read_text().splitlines()
        is_workflow = f.parent.name == "workflows"
        if is_workflow and not any(re.match(r"permissions:", line) for line in lines):
            bad.append("%s: no top-level permissions; set them, read-only unless the workflow must write" % rel)
        if is_workflow and any((f.name, p) in ALLOWED_WRITES for p in ("contents", "id-token", "attestations", "issues")) \
                and any(re.match(r"\s+pull_request\s*:?\s*$", line) for line in lines):
            bad.append("%s: a workflow that can write runs on pull_request" % rel)
        run_indent = None
        for n, line in enumerate(lines, 1):
            m = USES.match(line)
            if m and not m.group(1).startswith("./"):
                actions += 1
                if m.group(1).split("/")[0] not in ACTION_OWNERS:
                    bad.append("%s:%d: %s is not from %s" % (rel, n, m.group(1), ", ".join(sorted(ACTION_OWNERS))))
                ref = m.group(1).rsplit("@", 1)
                if len(ref) != 2 or not re.fullmatch(r"[0-9a-f]{40}", ref[1]):
                    bad.append("%s:%d: %s is not pinned to a commit SHA" % (rel, n, m.group(1)))
            if "secrets." in line and not line.lstrip().startswith("#"):
                bad.append("%s:%d: references a secret" % (rel, n))
            if re.search(r"\bwrite-all\b", line):
                bad.append("%s:%d: write-all" % (rel, n))
            w = re.match(r"\s*([a-z-]+):\s*write\s*$", line)
            if w and (f.name, w.group(1)) not in ALLOWED_WRITES:
                bad.append("%s:%d: %s: write is not an allowed write permission" % (rel, n, w.group(1)))
            if re.search(r"\bpull_request_target\b", line) and not line.lstrip().startswith("#"):
                bad.append("%s:%d: pull_request_target trigger" % (rel, n))
            # run: scripts, inline or as a block, and only those: env: values are not interpolated into a shell.
            indent = len(line) - len(line.lstrip())
            if run_indent is not None and line.strip() and indent <= run_indent:
                run_indent = None
            r = re.match(r"(\s*)(?:-\s*)?run:\s*(.*)$", line)
            if r:
                if r.group(2).strip() in ("|", ">", "|-", ">-"):
                    run_indent = len(r.group(1))
                elif UNTRUSTED.search(r.group(2)):
                    bad.append("%s:%d: run interpolates untrusted text; pass it through env:" % (rel, n))
            elif run_indent is not None and UNTRUSTED.search(line):
                bad.append("%s:%d: run interpolates untrusted text; pass it through env:" % (rel, n))
    return len(files), actions


def check_evidence(bad):
    out = subprocess.run(["git", "ls-files", *EVIDENCE], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    n = 0
    for p in out.splitlines():
        if p.endswith((".xdr", ".b64", ".zst", ".png")):
            continue
        n += 1
        text = (ROOT / p).read_text(errors="replace")
        m = HOME.search(text)
        if m:
            bad.append("%s: names a home directory (%s)" % (p, m.group(0)))
    return n


def main():
    bad = []
    files = tracked()
    n_lock, n_named = check_images(files, bad)
    n_nets = check_networks(files, bad)
    n_files, n_actions = check_workflows(bad)
    n_evidence = check_evidence(bad)
    print("images: %d pinned by digest in security/images.lock.json, %d tags named in the code" % (n_lock, n_named))
    print("networks: %d places in the code create a Docker network" % n_nets)
    print("workflows: %d files, %d third-party action references" % (n_files, n_actions))
    print("evidence: %d recorded files checked for home-directory paths" % n_evidence)
    print("problems: %d" % len(bad))
    for b in bad:
        print("  " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
