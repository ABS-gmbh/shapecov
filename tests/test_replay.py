"""harness/replay/replay.py: what counts as a failure in the backtest, and the scoping of rules for
defects wallet-backend has since fixed."""
import os
import sys
import unittest

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "harness" / "replay"))
sys.path.insert(0, str(ROOT / "tools"))
import replay  # noqa: E402

WB = replay.adapter_mapping("wallet-backend")
CLONE = os.path.join(os.environ.get("REPLAY_WORK", str(ROOT / "harness" / "replay" / ".work")), "wallet-backend", ".git")
PARTICIPANT = {"expect": "participants_within", "via": {"what": "participant", "how": "outside meta"}}


class Failing(unittest.TestCase):
    def r(self, result="pass", **oracle):
        return {"result": result, "oracle": oracle}

    def test_pass(self):
        self.assertFalse(replay._failing(self.r(known={"stellar/wallet-backend#815": 3}, unexplained=[])))

    def test_indexer_failure(self):
        self.assertTrue(replay._failing(self.r("mishandled")))
        self.assertTrue(replay._failing(self.r("dropped")))

    def test_unexplained_oracle_failure(self):
        self.assertTrue(replay._failing(self.r(unexplained=["x"])))

    def test_a_failure_labelled_as_fixed_upstream_still_fails(self):
        self.assertTrue(replay._failing(self.r(known={"record:R11": 2}, unexplained=[], fixed_upstream={"record:R11": 2})))


@unittest.skipUnless(os.path.isdir(CLONE), "needs the wallet-backend clone the harness builds from")
class FixedUpstream(unittest.TestCase):
    def test_labelled_only_before_the_fix(self):
        self.assertEqual(WB.known_issue(PARTICIPANT, commit="666a64d426263fa6bd2a0ee61ee8dfb1f4729019"), "record:R11")
        self.assertIsNone(WB.known_issue(PARTICIPANT, commit="e2da4cadf2689380e9fc2dd0e1bce64191f411b8"))
        self.assertIsNone(WB.known_issue(PARTICIPANT, commit="3e22515a44979fdc3a558fda3991ca2b48e38cef"))

    def test_unknown_commit_stays_unexplained(self):
        self.assertIsNone(WB.known_issue(PARTICIPANT, commit="0" * 40))
        self.assertIsNone(WB.known_issue(PARTICIPANT))

    def test_fixed_upstream_labels(self):
        self.assertIn("record:R11", WB.fixed_upstream())


if __name__ == "__main__":
    unittest.main()
