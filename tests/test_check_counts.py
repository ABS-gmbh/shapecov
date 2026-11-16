"""Docs check: .github/scripts/check_counts.py, on a small synthetic repository."""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import run_script, write_jsonl, write_tree

SCRIPT = ".github/scripts/check_counts.py"

# Every fact stated once, with the numbers the fixture below produces.
README = """# Fixture

Corpus: 4 entries, 3 of them real ledgers.
**1 defects found and filed** in one SDK. All 2 findings, with severity, CAPs and a reproducing entry.
**1 of the RFP's 2 sightings reproduced**.
**4 generated cases across all 2 types**; valid cases reach 2 of the 3 schema cells.
It reruns the 1 checks that work from the repository alone.
Coverage of the 1 schema cells no valid case reaches yet.
So 1 of the 2 cells a ledger reader can meet appear in a corpus entry. Each of the other 1 is classified.
Valid cases exercise 2 of 3 schema cells, and 2 of the 2 a ledger reader can meet.
The harness detects 1 of wallet-backend's 2 in-scope fixes (1 on ledgers not chosen for the bug)
and flags 0 of stellar-etl's 1 in-scope issues (0 blind).
"""
VERIFY = "35 probes, plus one setup transaction.\n".replace("35", "1")
SIGHTINGS = """**1 of 2 reproduced.**

| # | Sighting | Status | How |
|---|---|---|---|
| 1 | o/r#1 | reproduced | x |
| 2 | o/r#2 | not reproduced | y |

1 corpus entries are stellar-core's golden ledgers.
"""
QUICKCHECK = 'CHECKS = [("A", "a", ["python", "a.py"])]\n'


class CheckCounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        entries = [
            {"id": "g", "synthetic": False, "source": {"kind": "stellar_core_golden"}, "cells": ["arm:U.A"]},
            {"id": "n", "synthetic": False, "source": {"kind": "network_ledger", "network": "testnet"}, "cells": []},
            {"id": "l", "synthetic": False, "source": {"kind": "local_stellar_core"}, "cells": []},
            {"id": "s", "synthetic": True, "source": {"kind": "generated"}, "cells": []},
        ]
        write_tree(self.dir, {
            "corpus/manifest.json": {"entries": entries},
            "corpus/coverage.json": {"schema_cells": 3, "generator_covers": 2, "reachable_cells": 2,
                                     "corpus_covers_reachable": 1, "generator_covers_reachable": 2,
                                     "uncovered_reachable": 1},
            "FINDINGS.json": {"findings": [{"kind": "found"}, {"kind": "sighting"}]},
            "schema/schema.json": {"types": {"U": {}, "E": {}}},
            "quickcheck.py": QUICKCHECK,
            "guide/probes.json": {"probes": [{"row": "Home domain"}, {"row": "(setup)"}]},
            "harness/replay/backtest.json": {"items": [
                {"pipeline": "wallet-backend", "verdict": "detected", "entries": [{"entry": "e", "blind": True}]},
                {"pipeline": "wallet-backend", "verdict": "missed", "entries": []},
                {"pipeline": "wallet-backend", "verdict": "out_of_scope", "entries": []},
                {"pipeline": "stellar-etl", "verdict": "missed", "entries": []}]},
            "README.md": README, "VERIFY.md": VERIFY, "ARCHITECTURE.md": "", "FINDINGS.md": "",
            "corpus/README.md": "| a | 1 | `stellar_core_golden` |\n| testnet (1) and pubnet (0) history | 1 | "
                                "`network_ledger` |\n| b | 1 | `local_stellar_core` |\n| c | 1 | `generated` |\n",
            "harness/sightings/README.md": SIGHTINGS,
        })
        write_jsonl(self.dir, "out/cases.jsonl", [{"id": i} for i in range(4)])

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self):
        return run_script(SCRIPT, cwd=self.dir)

    def test_agreeing_numbers_pass(self):
        rc, out = self.run_check()
        self.assertEqual(rc, 0, out)
        self.assertIn("mismatches: 0", out)

    def test_a_stale_number_fails(self):
        write_tree(self.dir, {"README.md": README.replace("Corpus: 4 entries", "Corpus: 71 entries")})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("'Corpus: 71 entries' says 71, but corpus entries is 4", out)

    def test_commas_in_numbers_are_read(self):
        write_tree(self.dir, {"README.md": README.replace("4 generated cases", "4,000 generated cases")})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("says 4000, but generated cases is 4", out)

    def test_backtest_numbers_follow_backtest_json(self):
        write_tree(self.dir, {"README.md": README.replace("detects 1 of wallet-backend's 2", "detects 4 of wallet-backend's 2")})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("says 4, but backtest: wallet-backend fixes detected is 1", out)

    def test_a_fact_no_document_states_fails(self):
        write_tree(self.dir, {"VERIFY.md": ""})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("guide probes (without the setup transaction) (1) is no longer stated", out)


if __name__ == "__main__":
    unittest.main()
