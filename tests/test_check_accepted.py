"""RFP check 3, triage half: linter/scripts/check_accepted.py."""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import run_script, write_tree

SCRIPT = "linter/scripts/check_accepted.py"


def finding(rule="SC002", file="p/deploy.go", line=116, message="recursive closure walkInvocation has no depth cap"):
    return {"rule": rule, "file": file, "line": line, "message": message}


def entry(**kw):
    e = {"rule": "SC002", "file": "p/deploy.go", "message_contains": "recursive closure walkInvocation",
         "upstream": "https://github.com/o/r/issues/1", "reason": "real, low severity"}
    e.update(kw)
    return e


class CheckAccepted(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, report, accepted):
        write_tree(self.dir, {"report.json": report, "accepted.json": accepted})
        return run_script(SCRIPT, str(self.dir / "report.json"), str(self.dir / "accepted.json"))

    def test_every_finding_accepted_passes(self):
        rc, out = self.run_check({"findings": [finding()]}, {"accepted": [entry()]})
        self.assertEqual(rc, 0, out)
        self.assertIn("1 findings: 1 accepted, 0 not accepted", out)

    def test_a_moved_line_still_matches(self):
        rc, out = self.run_check({"findings": [finding(line=999)]}, {"accepted": [entry()]})
        self.assertEqual(rc, 0, out)

    def test_new_finding_fails(self):
        new = finding(rule="SC003", file="p/participants.go", message="participants is filled from the envelope")
        rc, out = self.run_check({"findings": [finding(), new]}, {"accepted": [entry()]})
        self.assertEqual(rc, 1, out)
        self.assertIn("NEW       SC003 p/participants.go:116", out)

    def test_entry_matching_nothing_is_reported_resolved(self):
        rc, out = self.run_check({"findings": []}, {"accepted": [entry()]})
        self.assertEqual(rc, 0, out)
        self.assertIn("resolved  SC002 p/deploy.go", out)

    def test_entry_without_reason_is_malformed(self):
        rc, out = self.run_check({"findings": [finding()]}, {"accepted": [entry(reason="")]})
        self.assertEqual(rc, 2, out)
        self.assertIn("lacks reason", out)

    def test_incomplete_report_is_malformed(self):
        rc, out = self.run_check({"findings": [finding()], "load_errors": 3}, {"accepted": [entry()]})
        self.assertEqual(rc, 2, out)
        self.assertIn("3 package load errors", out)

    def test_unreadable_input_is_malformed(self):
        (self.dir / "report.json").write_text("{not json")
        write_tree(self.dir, {"accepted.json": {"accepted": []}})
        rc, out = run_script(SCRIPT, str(self.dir / "report.json"), str(self.dir / "accepted.json"))
        self.assertEqual(rc, 2, out)

    def test_committed_wallet_backend_report_passes(self):
        rc, out = run_script(SCRIPT, "linter/results/wallet-backend-3e22515a4497.json",
                             "linter/accepted/wallet-backend.json")
        self.assertEqual(rc, 0, out)
        self.assertIn("2 findings: 2 accepted, 0 not accepted", out)


if __name__ == "__main__":
    unittest.main()
