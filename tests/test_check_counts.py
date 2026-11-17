"""Docs check: .github/scripts/check_counts.py, on a small synthetic repository."""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import run_script, write_jsonl, write_tree

SCRIPT = ".github/scripts/check_counts.py"

# Every fact stated once, with the numbers the fixture below produces.
README = """# Fixture

Corpus: 4 entries, 3 of them real ledgers.
**1 defects found, filed in 1 issues** in one SDK. All 2 findings, with severity, CAPs and a reproducing entry.
**1 of the RFP's 2 sightings reproduced**.
**4 generated cases across all 2 types**; valid cases reach 2 of the 3 schema cells.
## Check it in under 9 seconds
| Linter | linter/ | 3 | Partly met: 2 findings on wallet-backend, both real |
Read the 1 statements (sides of 1 rows) that rest on a source citation alone.
The linter does not run clean on wallet-backend or on stellar-etl (1, all real, in uncalled code).
It reruns the 1 fast checks that work from the repository alone: 2 seconds on a laptop.
`python3 quickcheck.py --full` adds the unit tests and the mutation testing, 2 checks in 12 seconds.
Coverage of the 1 schema cells no valid case reaches yet.
So 1 of the 2 cells a ledger reader can meet appear in a corpus entry. Each of the other 1 is classified.
Valid cases exercise 2 of 3 schema cells, and 2 of the 2 a ledger reader can meet.
The schema has 1 union arms and 2 enum members. The decoder accepts all 3 valid generated cases,
rejects all 1
faulty ones. One GitHub Actions workflows run it.
The harness detects 1 of wallet-backend's 2 in-scope fixes (1 on ledgers not chosen for the bug)
and flags 0 of stellar-etl's 1 in-scope issues (0 blind).
Of its 3-item checklist, 2 items name the corpus ledgers that exercise them and 1 the upstream fix or issue behind it.
The ledgers are pubnet and testnet history from protocol 25 to 25.
For wallet-backend, no other row is missing for any of the 2 ledgers: 9 of 10 checks per input pass.
The 1 that fail are the 1 rows above.
All 4 live CAPs are accounted for: 3 have a shape in ledger data, and of those 1 are covered, 1 is covered except for
one form and 1 is a gap; the other 1 have no shape in ledger data. 1 of the 2 cells a ledger reader can meet, and 1 of
the 2 that can occur in a closed ledger. 3 can never be in a closed ledger, 1 predate protocol 20, 0 appear only in
metadata from an older core, 2 appear only in consensus messages, and 0 is impractical.
"""
CAP_COVERAGE = """| CAP | Protocol | Title | Status | Evidence | Gap |
|---|---|---|---|---|---|
| CAP-0001 | 10 | A | covered | x | — |
| CAP-0046-01 | 20 | B | partly covered | x | y |
| CAP-0083 | 28 | C | gap | | y |
| CAP-0002 | 10 | D | no shape | why | — |
"""
GUIDE = """# Guide

<!-- checklist-evidence:begin: generated -->

| # | Exercised by | Where an indexer, SDK or exporter got it wrong |
|---|---|---|
| 1 | `l` | [r #1](https://github.com/o/r/issues/1) |
| 2 | `n` | none recorded yet |
| 3 | none in the corpus yet | none recorded yet |

<!-- checklist-evidence:end -->
"""
VERIFY = "35 probes, plus one setup transaction.\n".replace("35", "1")
SIGHTINGS = """**1 of 2 reproduced.**

| # | Sighting | Status | How |
|---|---|---|---|
| 1 | o/r#1 | reproduced | x |
| 2 | o/r#2 | not reproduced | y |

1 corpus entries are stellar-core's golden ledgers.
"""
QUICKCHECK = ('FULL_ONLY = {"M"}\nBUDGET_SECONDS = 9\n'
              'CHECKS = [("A", "a", ["python", "a.py"]), ("M", "m", ["python", "m.py"])]\n')


class CheckCounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        entries = [
            {"id": "g", "synthetic": False, "source": {"kind": "stellar_core_golden"}, "cells": ["arm:U.A"]},
            {"id": "n", "synthetic": False, "source": {"kind": "network_ledger", "network": "testnet"}, "cells": [],
             "protocol_version": 25},
            {"id": "l", "synthetic": False, "source": {"kind": "local_stellar_core"}, "cells": []},
            {"id": "s", "synthetic": True, "source": {"kind": "generated"}, "cells": []},
        ]
        write_tree(self.dir, {
            "corpus/manifest.json": {"entries": entries},
            "corpus/coverage.json": {"schema_cells": 3, "generator_covers": 2, "reachable_cells": 2,
                                     "corpus_covers_reachable": 1, "generator_covers_reachable": 2,
                                     "uncovered_reachable": 1, "closed_ledger_cells": 2,
                                     "uncovered_by_class": {"never_in_ledger": 3, "before_protocol": 1, "consensus": 2}},
            "corpus/CAP-COVERAGE.md": CAP_COVERAGE,
            "FINDINGS.json": {"findings": [{"kind": "found", "upstream": ["u1"]}, {"kind": "sighting"}]},
            "schema/schema.json": {"types": {"U": {"k": "union", "arms": [{}]}, "E": {"k": "enum", "members": [[1], [2]]}}},
            ".github/workflows/ci.yml": "name: ci\n",
            "quickcheck.py": QUICKCHECK,
            "guide/probes.json": {"probes": [{"row": "Home domain"}, {"row": "(setup)"}]},
            "guide/verdicts.json": {"rows": [{"field": "Fee", "checked": {"citation_only": "x"}, "not_checked": {"probes": ["p"]}}]},
            "linter/accepted/wallet-backend.json": {"pinned_commit": "a" * 40, "accepted": []},
            "linter/accepted/stellar-etl.json": {"pinned_commit": "b" * 40, "accepted": []},
            "linter/results/wallet-backend-aaaaaaaaaaaa.json": {"findings": [{}, {}]},
            "linter/results/stellar-etl-bbbbbbbbbbbb.json": {"findings": [{}]},
            "harness/replay/backtest.json": {"items": [
                {"pipeline": "wallet-backend", "verdict": "detected", "entries": [{"entry": "e", "blind": True}]},
                {"pipeline": "wallet-backend", "verdict": "missed", "entries": []},
                {"pipeline": "wallet-backend", "verdict": "out_of_scope", "entries": []},
                {"pipeline": "stellar-etl", "verdict": "missed", "entries": []}]},
            "README.md": README, "VERIFY.md": VERIFY, "ARCHITECTURE.md": "", "FINDINGS.md": "",
            "corpus/README.md": "| a | 1 | `stellar_core_golden` |\n| testnet (1) and pubnet (0) history | 1 | "
                                "`network_ledger` |\n| b | 1 | `local_stellar_core` |\n| c | 1 | `generated` |\n",
            "harness/sightings/README.md": SIGHTINGS,
            "guide/INDEXER-HARDENING.md": GUIDE, "releases/v0.2.0.md": "",
            "IssueTracker.md": "The full list, including the 2 that others reported first.\n| Issues filed | 1 (1 open) |\n",
        })
        write_jsonl(self.dir, "out/cases.jsonl", [{"id": i, "valid": i < 3} for i in range(4)])
        # wallet-backend's recorded replays: two ledgers at the commit with the most results, on both inputs,
        # an older commit with one, and a sequence member, which is not counted.
        wb = [{"entry_id": e, "commit": "main", "input": inp, "oracle": {"rows_expected": n, "rows_met": m}}
              for inp in ("rpc", "datalake") for e, n, m in (("a", 6, 6), ("b", 4, 3))]
        wb += [{"entry_id": "a", "commit": "old", "input": "rpc", "oracle": {"rows_expected": 6, "rows_met": 1}},
               {"entry_id": "a", "commit": "main", "input": "rpc", "in_sequence": True,
                "oracle": {"rows_expected": 6, "rows_met": 0}}]
        write_jsonl(self.dir, "harness/replay/out/results.jsonl", wb)

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

    def test_checklist_figures_come_from_the_guides_evidence_table(self):
        write_tree(self.dir, {"README.md": README.replace("2 items name the corpus", "3 items name the corpus")})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("but guide checklist items exercised by a corpus ledger is 2", out)

    def test_cap_figures_come_from_the_per_cap_table(self):
        write_tree(self.dir, {"README.md": README.replace("of those 1 are covered", "of those 2 are covered")})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("but CAPs covered is 1", out)

    def test_wallet_backend_figures_come_from_its_results_at_main(self):
        write_tree(self.dir, {"README.md": README.replace("9 of 10 checks per input", "10 of 10 checks per input")})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("but wallet-backend oracle checks met per input at main is 9", out)

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

    def test_quick_check_time_over_its_budget_fails(self):
        write_tree(self.dir, {"README.md": README.replace(": 2 seconds on a laptop", ": 11 seconds on a laptop")})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("is over the quick check's budget of 9 s", out)

    def test_quick_check_counts_with_and_without_full(self):
        write_tree(self.dir, {"README.md": README.replace("the 1 fast checks", "the 2 fast checks")})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("says 2, but quickcheck checks without --full is 1", out)

    def test_a_fact_no_document_states_fails(self):
        write_tree(self.dir, {"VERIFY.md": ""})
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn("guide probes (without the setup transaction) (1) is no longer stated", out)


if __name__ == "__main__":
    unittest.main()
