#!/usr/bin/env python3
"""Check the RFP acceptance claims in a few minutes, with Python only.

  python3 quickcheck.py

Needs Python 3.10 or later and one package, `pip install jsonschema` (for the manifest's JSON
Schema). No Docker, no SDK toolchain and no network. It reruns every check that works from the
repository alone, and checks the recorded results of those that need an indexer, an SDK or
stellar-core against their expected verdicts. One line per check: PASS or FAIL, and how long it
took. The checks it does not rerun, and the CI jobs that do, are printed at the end. Exit status 1
if any check fails.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

CHECKS = [
    ("RFP check 1", "every corpus entry decodes strictly, re-encodes to the same bytes, and matches its manifest "
                    "record, hashes and the manifest's JSON Schema",
     [PY, "tools/corpus_check.py", "--quiet"]),
    ("RFP check 2", "the recorded wallet-backend replays: each sighting fails before its fix and passes after; "
                    "no unexplained oracle failure",
     [PY, "harness/replay/replay.py", "check", "--out", "harness/replay/out", "--oracle"]),
    ("RFP check 2", "the recorded stellar-etl replays: no unexplained oracle failure",
     [PY, "harness/replay/replay.py", "check", "--out", "harness/replay/out-stellar-etl", "--oracle"]),
    ("RFP check 3", "the recorded linter report on wallet-backend has no finding outside the accepted list",
     [PY, "linter/scripts/check_accepted.py", "linter/results/wallet-backend-3e22515a4497.json",
      "linter/accepted/wallet-backend.json"]),
    ("RFP check 4", "the guide's tables agree with the corpus manifest; every row has a recorded stellar-core "
                    "verdict or a stated citation",
     [PY, "guide/check_guide.py"]),
    ("RFP check 6", "every oracle failure in the recorded replays maps to a filed issue or a claimed sighting",
     [PY, ".github/scripts/check_findings.py"]),
    ("CAP coverage", "every live CAP is accounted for, and the table matches the corpus",
     [PY, "tools/cap_coverage.py", "--check"]),
]

NOT_RERUN = [
    ("RFP check 1", "byte-for-byte agreement with stellar-core's golden files, and round trips through rs-stellar-xdr "
                    "and five SDKs", "ci › RFP check 1; ci › RFP checks 1 and 5"),
    ("RFP check 2", "the wallet-backend replays themselves (Docker, the indexer, TimescaleDB)",
     "replay › RFP check 2"),
    ("RFP check 3", "the linter's seeded-violation tests and the run on wallet-backend (Go)", "ci › RFP check 3"),
    ("RFP check 4", "the probes against a live stellar-core 30.0.0 (Docker)", "ci › RFP check 4"),
    ("RFP check 5", "the JavaScript sightings on their pre-fix releases (Node, npm)", "ci › RFP checks 1 and 5"),
    ("Other", "memory budget, both passphrases, the Rust sightings, stellar-etl replay",
     "replay workflow, one job each"),
]


def main():
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        print("needs one package: pip install jsonschema")
        return 2
    failed = 0
    start = time.monotonic()
    for check, what, cmd in CHECKS:
        t = time.monotonic()
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        took = time.monotonic() - t
        ok = p.returncode == 0
        failed += not ok
        print("%s  %-12s %5.1f s  %s" % ("PASS" if ok else "FAIL", check, took, what), flush=True)
        if not ok:
            lines = (p.stdout + p.stderr).strip().splitlines()
            bad = [x for x in lines if re.search(r"FAIL|ERROR|DIFFERS|UNEXPLAINED|MISSING|NEW |Traceback|Error", x)]
            for line in (bad or lines)[-8:]:
                print("        " + line.strip())
    print("\n%d of %d checks passed in %.0f s." % (len(CHECKS) - failed, len(CHECKS), time.monotonic() - start))
    print("\nNot rerun here, because they need Docker, an SDK toolchain or the network; CI reruns them:")
    for check, what, job in NOT_RERUN:
        print("  %-12s %s  ->  %s" % (check, what, job))
    print("CI: https://github.com/ABS-gmbh/shapecov/actions")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
