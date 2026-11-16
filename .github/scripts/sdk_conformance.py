#!/usr/bin/env python3
"""Run ShapeCov's conformance corpus through one SDK, for that SDK's own CI.

  sdk_conformance.py build --sdk SDK [--version SPEC]
  sdk_conformance.py run   --sdk SDK [--known-failures FILE] [--report report.json]

SDK is one of rust, js, python, python-xdr, go, java. SPEC is what the package manager installs
instead of the kit's pin: a version ("17.4.0"), or for js, python and go a git reference the
package manager understands (an npm spec such as "github:stellar/js-stellar-sdk#<sha>", a pip
spec such as "git+https://github.com/StellarCN/py-stellar-base@<sha>", or a Go version such as a
commit hash). `build` needs that SDK's toolchain (Docker for go and java); `run` needs only Python.

`run` sends three kinds of input through the SDK's runner:
- every corpus entry: it must decode and re-encode to the same bytes;
- every valid value the generator made (out/cases.jsonl): it must decode and re-encode to the
  same bytes;
- every faulty value the generator made: it carries one fault that RFC 4506 says a decoder must
  reject, and the SDK must reject it.
A case whose type the SDK does not have is skipped. Every other outcome that breaks those rules is a
divergence. Each divergence has an id (`entry:<id>` or `case:<id>`) and a class (`entry`, `valid`,
`fault:<kind>` or `crash`).

Known failures. One pattern per line, matched against a divergence's id or class (shell-style
wildcards); text after `#` is a comment. Example:

  fault:trailing          # accepted trailing bytes; tracked in our issue #6039
  case:SponsorshipDescriptor/*

`run` exits 1 if any divergence matches no pattern, and lists patterns that matched nothing, so a
known failure that has been fixed shows up.
"""
import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT / "tools"))
import run as R  # noqa: E402

RUN = KIT / "runners"
PLAIN = re.compile(r"^v?\d+\.\d+\.\d+([-+.][0-9A-Za-z.]+)?$")


def sh(cmd, cwd=None):
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def build(sdk, spec):
    if sdk == "rust":
        if spec:
            toml = RUN / "rust/Cargo.toml"
            text = toml.read_text()
            toml.write_text(re.sub(r'stellar-xdr = \{ version = "=[^"]+"', 'stellar-xdr = { version = "=%s"'
                                   % spec.lstrip("v"), text))
        sh(["cargo", "build", "--release"] + ([] if spec else ["--locked"]), cwd=RUN / "rust")
    elif sdk == "js":
        sh(["npm", "ci", "--no-audit", "--no-fund"], cwd=RUN / "js")
        if spec:
            pkg = "@stellar/stellar-sdk@" + spec if PLAIN.match(spec) else spec
            sh(["npm", "install", "--no-save", "--no-audit", "--no-fund", pkg], cwd=RUN / "js")
    elif sdk in ("python", "python-xdr"):
        venv = RUN / sdk / ".venv"
        sh([sys.executable, "-m", "venv", str(venv)])
        pip = [str(venv / "bin/pip"), "install", "-q"]
        if sdk == "python":
            sh(pip + ["stellar-sdk==" + spec if spec and PLAIN.match(spec) else (spec or "stellar-sdk==17.0.1")])
        else:
            sh(pip + ["-r", str(RUN / "python-xdr/requirements.txt")])
            if spec:
                sh(pip + ["stellar-xdr==" + spec if PLAIN.match(spec) else spec])
    elif sdk == "go":
        script = (RUN / "go/build.sh").read_text()
        if spec:
            script = script.replace("github.com/stellar/go-stellar-sdk@v0.9.0", "github.com/stellar/go-stellar-sdk@" + spec)
        (RUN / "go/build-conformance.sh").write_text(script)
        sh(["docker", "run", "--rm", "-v", "%s:/work" % (RUN / "go"), "golang:1.26", "sh", "/work/build-conformance.sh"])
    elif sdk == "java":
        if spec:
            pom = RUN / "java/pom.xml"
            pom.write_text(re.sub(r"(<artifactId>stellar-sdk</artifactId><version>)[^<]+(</version>)",
                                  r"\g<1>%s\g<2>" % spec.lstrip("v"), pom.read_text()))
        cmd = ("mvn -q org.apache.maven.plugins:maven-dependency-plugin:3.8.1:copy-dependencies -DoutputDirectory=lib "
               "&& javac -cp 'lib/*' Runner.java")
        for attempt in range(3):
            p = subprocess.run(["docker", "run", "--rm", "-v", "%s:/work" % (RUN / "java"), "-w", "/work",
                                "maven:3.9-eclipse-temurin-21", "sh", "-c", cmd])
            if p.returncode == 0:
                break
        else:
            raise SystemExit("java runner build failed three times")
    else:
        raise SystemExit("unknown sdk %s" % sdk)


def inputs():
    """(id, class-if-wrong, type, base64, must) for every input. must is 'roundtrip' or 'reject'."""
    out = []
    manifest = json.load(open(KIT / "corpus/manifest.json"))
    for e in manifest["entries"]:
        b64 = (KIT / "corpus" / e["file"]).read_text().strip()
        out.append(("entry:" + e["id"], "entry", e["xdr_type"], b64, "roundtrip"))
    for line in open(KIT / "out/cases.jsonl"):
        c = json.loads(line)
        if c["valid"]:
            out.append(("case:" + c["id"], "valid", c["type"], c["b64"], "roundtrip"))
        else:
            out.append(("case:" + c["id"], "fault:" + (c.get("fault") or {}).get("kind", "?"), c["type"], c["b64"],
                        "reject"))
    return out


def load_patterns(path):
    pats = []
    if path:
        for raw in open(path):
            p = raw.split("#", 1)[0].strip()
            if p:
                pats.append(p)
    return pats


def run(sdk, known_path, report_path):
    items = inputs()
    by_id = {i[0]: i for i in items}
    lines = ["%s\t%s\t%s\n" % (i[0], i[2], i[3]) for i in items]
    results = R.run(R.RUNNERS[sdk]["cmd"], lines)
    skipped, passed, divergences = 0, 0, []
    for line in results:
        cid, status, rest = (line.split("\t", 2) + ["", ""])[:3]
        item = by_id.get(cid)
        if item is None:
            continue
        _, cls, _, b64, must = item
        if status in ("notype", "unsupported"):
            skipped += 1
            continue
        if status in ("crash", "hang", "panic"):
            divergences.append({"id": cid, "class": "crash", "detail": "%s: %s" % (status, rest[:200])})
        elif must == "roundtrip" and (status != "ok" or rest != b64):
            divergences.append({"id": cid, "class": cls,
                                "detail": ("rejected: " + rest[:200]) if status != "ok" else "re-encodes to different bytes"})
        elif must == "reject" and status == "ok":
            divergences.append({"id": cid, "class": cls, "detail": "accepted"})
        else:
            passed += 1
    pats = load_patterns(known_path)
    used = {p: 0 for p in pats}
    unexpected = []
    for d in divergences:
        hit = [p for p in pats if fnmatch.fnmatchcase(d["id"], p) or fnmatch.fnmatchcase(d["class"], p)]
        for p in hit:
            used[p] += 1
        d["known"] = bool(hit)
        if not hit:
            unexpected.append(d)
    stale = [p for p, n in used.items() if n == 0]
    report = {"sdk": sdk, "runner": R.RUNNERS[sdk]["version"], "inputs": len(items), "passed": passed,
              "skipped_no_type": skipped, "divergences": len(divergences), "known": len(divergences) - len(unexpected),
              "unexpected": unexpected, "stale_patterns": stale}
    if report_path:
        Path(report_path).write_text(json.dumps(report, indent=1) + "\n")
    summary = ["%s: %d inputs, %d pass, %d skipped (type not in the SDK), %d divergences, %d of them known"
               % (sdk, len(items), passed, skipped, len(divergences), len(divergences) - len(unexpected))]
    classes = {}
    for d in divergences:
        classes.setdefault((d["class"], d["known"]), 0)
        classes[(d["class"], d["known"])] += 1
    for (cls, known), n in sorted(classes.items()):
        summary.append("  %-24s %5d  %s" % (cls, n, "known" if known else "NOT IN THE KNOWN-FAILURES FILE"))
    for d in unexpected[:30]:
        summary.append("  UNEXPECTED %s (%s): %s" % (d["id"], d["class"], d["detail"]))
    for p in stale:
        summary.append("  stale known-failure pattern, matched nothing: %s" % p)
    summary.append("CONFORMANCE OK" if not unexpected else "%d UNEXPECTED DIVERGENCE(S)" % len(unexpected))
    text = "\n".join(summary)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("```\n" + text + "\n```\n")
    return 1 if unexpected else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run"])
    ap.add_argument("--sdk", required=True, choices=sorted(R.RUNNERS))
    ap.add_argument("--version", default="")
    ap.add_argument("--known-failures", default="")
    ap.add_argument("--report", default="")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.sdk, a.version.strip())
        return 0
    return run(a.sdk, a.known_failures, a.report)


if __name__ == "__main__":
    sys.exit(main())
