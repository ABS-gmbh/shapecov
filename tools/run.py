"""Run every SDK runner over a case file. A runner that dies or hangs loses only the
case it was on: that case is recorded as `crash`/`hang` and the run resumes after it.

Usage: run.py out/cases.jsonl [sdk ...]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "runners"
DOCKER = ["docker", "run", "-i", "--rm", "--network", "none", "--memory", "2g", "--cpus", "2"]
RUNNERS = {
    "rust": {"cmd": [str(R / "rust/target/release/runner-rust")], "version": "stellar-xdr 30.0.0 (reference)"},
    "js": {"cmd": ["node", str(R / "js/run.mjs")], "version": "@stellar/stellar-sdk 17.4.0"},
    "python": {"cmd": [str(R / "python/.venv/bin/python"), str(R / "python/run.py")], "version": "stellar-sdk 17.0.1"},
    "go": {"cmd": DOCKER + ["-v", f"{R / 'go'}:/work:ro", "golang:1.26", "/work/runner-go"],
           "version": "go-stellar-sdk v0.9.0"},
    "java": {"cmd": DOCKER + ["-v", f"{R / 'java'}:/work:ro", "-w", "/work", "maven:3.9-eclipse-temurin-21",
                              "java", "-Xmx1g", "-Xss4m", "-cp", "lib/*:.", "Runner"],
             "version": "network.lightsail:stellar-sdk 6.0.0"},
}


def run(cmd, lines, timeout=180):
    results, i = [], 0
    while i < len(lines):
        chunk = "".join(lines[i:])
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        hang = False
        try:
            out, err = p.communicate(chunk.encode(), timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
            hang = True
        got = [l for l in out.decode("utf-8", "replace").split("\n") if l.count("\t") >= 2]
        results += got
        i += len(got)
        if i < len(lines):  # the runner stopped on case i
            cid = lines[i].split("\t", 1)[0]
            tail = err.decode("utf-8", "replace").strip().split("\n")[-1][:200].replace("\t", " ")
            results.append(f"{cid}\t{'hang' if hang else 'crash'}\t{tail}")
            i += 1
    return results


def main():
    cases = Path(sys.argv[1])
    sdks = sys.argv[2:] or list(RUNNERS)
    lines = []
    for l in cases.open():
        r = json.loads(l)
        lines.append(f"{r['id']}\t{r['type']}\t{r['b64']}\n")
    outdir = cases.parent
    for s in sdks:
        res = run(RUNNERS[s]["cmd"], lines)
        (outdir / f"res.{s}.tsv").write_text("\n".join(res) + "\n")
        counts = {}
        for l in res:
            st = l.split("\t")[1]
            counts[st] = counts.get(st, 0) + 1
        print(s, RUNNERS[s]["version"], counts, flush=True)
    json.dump({s: RUNNERS[s]["version"] for s in RUNNERS}, open(outdir / "versions.json", "w"), indent=1)


if __name__ == "__main__":
    main()
