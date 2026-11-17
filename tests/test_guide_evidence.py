"""The guide's checklist evidence (guide/evidence.py): every id resolves, every detected fix is mapped,
and the rendered table names corpus entries, counts sweep ledgers and links the upstream fixes."""
import unittest

from tests.helpers import load_module

ev = load_module("guide_evidence", "guide/evidence.py")

BACKTEST = {"items": [
    {"id": "wallet-backend#9", "pipeline": "wallet-backend", "fix": "abcdef12", "verdict": "detected",
     "entries": [{"entry": "localcore-a-4"}, {"entry": "pubnet-1"}]},
    {"id": "1234abcd", "pipeline": "wallet-backend", "fix": "1234abcd", "verdict": "detected", "entries": [{"entry": "seq-x"}]},
    {"id": "stellar/stellar-etl#7", "issue": "stellar/stellar-etl#7", "pipeline": "stellar-etl", "verdict": "missed", "entries": []}]}
FINDINGS = {"findings": [{"id": "R1", "upstream": ["https://github.com/stellar/js-stellar-sdk/issues/5"],
                          "reproduction": {"corpus_entry": "localcore-a-4", "also": ["synthetic-b"]}}]}


def evidence(**items):
    return {"items": items, "outside_checklist": {}}


class Errors(unittest.TestCase):
    def test_agreeing_evidence_passes(self):
        e = evidence(**{"1": {"backtest": ["wallet-backend#9"], "findings": ["R1"]}, "2": {"backtest": ["1234abcd"], "findings": []}})
        self.assertEqual(ev.errors(e, BACKTEST, FINDINGS, ["1", "2"]), [])

    def test_unknown_ids_missed_items_and_unmapped_fixes_fail(self):
        e = evidence(**{"1": {"backtest": ["nope", "stellar/stellar-etl#7"], "findings": ["X9"]}, "3": {"backtest": [], "findings": []}})
        out = "\n".join(ev.errors(e, BACKTEST, FINDINGS, ["1", "2"]))
        self.assertIn("backtest item nope", out)
        self.assertIn("whose verdict is missed", out)
        self.assertIn("finding X9", out)
        self.assertIn("checklist item 2 has no entry", out)
        self.assertIn("names checklist item 3", out)
        self.assertIn("detected backtest item wallet-backend#9 maps to no checklist item", out)

    def test_a_fix_listed_outside_the_checklist_with_a_reason_passes(self):
        e = {"items": {"1": {"backtest": ["1234abcd"], "findings": []}}, "outside_checklist": {"wallet-backend#9": "a reason"}}
        self.assertEqual(ev.errors(e, BACKTEST, FINDINGS, ["1"]), [])


class Render(unittest.TestCase):
    def test_table(self):
        e = evidence(**{"1": {"backtest": ["wallet-backend#9"], "findings": ["R1"]}, "2": {"backtest": [], "findings": []}})
        out = ev.render(e, BACKTEST, FINDINGS, known={"localcore-a-4", "synthetic-b", "seq-x"})
        self.assertIn("| 1 | `localcore-a-4`, `synthetic-b`; 1 ledger of the sweep | "
                      "[wallet-backend #9](https://github.com/stellar/wallet-backend/pull/9), "
                      "[js-stellar-sdk #5](https://github.com/stellar/js-stellar-sdk/issues/5) |", out)
        self.assertIn("| 2 | none in the corpus yet | none recorded yet |", out)

    def test_commit_fixes_link_the_commit(self):
        e = evidence(**{"1": {"backtest": ["1234abcd"], "findings": []}})
        self.assertIn("[wallet-backend `1234abcd`](https://github.com/stellar/wallet-backend/commit/1234abcd)",
                      ev.render(e, BACKTEST, FINDINGS, known={"seq-x"}))


if __name__ == "__main__":
    unittest.main()
