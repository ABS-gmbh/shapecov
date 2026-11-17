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
PARTICIPANT = {"expect": "participants_within", "via": {"what": "participant", "how": "outside meta", "kind": "failed transaction"}}


class Failing(unittest.TestCase):
    def r(self, result="pass", ingested=True, **oracle):
        return {"result": result, "ingested": ingested, "oracle": oracle}

    def test_pass(self):
        self.assertFalse(replay._failing(self.r(known={"stellar/wallet-backend#815": 3}, unexplained=[])))

    def test_indexer_failure(self):
        self.assertTrue(replay._failing(self.r("mishandled")))
        self.assertTrue(replay._failing(self.r("dropped")))

    def test_unexplained_oracle_failure(self):
        self.assertTrue(replay._failing(self.r(unexplained=["x"])))

    def test_a_failure_labelled_as_fixed_upstream_still_fails(self):
        self.assertTrue(replay._failing(self.r(known={"record:R11": 2}, unexplained=[],
                                               fixed_upstream={"R11 failed transaction": 2},
                                               fixed_by={"R11 failed transaction": "9538b3ca"})))


class Detection(unittest.TestCase):
    F = {"R11 failed transaction": "9538b3ca", "R11 contract participant": "e2da4cad"}

    def r(self, result="pass", ingested=True, unexplained=(), **kinds):
        o = {"unexplained": list(unexplained), "known": {}, "fixed_upstream": {}, "fixed_by": {}}
        for k, n in kinds.items():
            name = "R11 " + k.replace("_", " ")
            o["fixed_upstream"][name] = n
            o["fixed_by"][name] = self.F[name]
        return {"result": result, "ingested": ingested, "oracle": o}

    def test_the_kind_this_fix_owns_must_be_gone(self):
        parent = self.r(failed_transaction=56, contract_participant=99)
        self.assertTrue(replay._fixed_by(parent, self.r(contract_participant=99), "9538b3ca"))
        self.assertFalse(replay._fixed_by(parent, self.r(failed_transaction=1, contract_participant=99), "9538b3ca"))

    def test_another_fix_s_failures_are_ignored(self):
        parent = self.r(contract_participant=99)
        self.assertFalse(replay._fixed_by(parent, self.r(), "9538b3ca"), "nothing at the parent bears on 9538b3ca")
        self.assertTrue(replay._fixed_by(parent, self.r(), "e2da4cad"))

    def test_an_indexer_failure_gone_at_the_fix(self):
        self.assertTrue(replay._fixed_by(self.r("mishandled", ingested=False), self.r(contract_participant=3), "22660cf4"))

    def test_a_halt_at_the_fix_is_never_a_detection(self):
        self.assertFalse(replay._fixed_by(self.r("mishandled", unexplained=["x"]), self.r("mishandled", ingested=False), "6e5a5910"))


@unittest.skipUnless(os.path.isdir(CLONE), "needs the wallet-backend clone the harness builds from")
class FixedUpstream(unittest.TestCase):
    def test_labelled_only_before_the_fix(self):
        self.assertEqual(WB.known_issue(PARTICIPANT, commit="666a64d426263fa6bd2a0ee61ee8dfb1f4729019"), "record:R11")
        self.assertIsNone(WB.known_issue(PARTICIPANT, commit="9538b3caeaebfeb3d034146c0ce9643c3066cf8a"),
                          "a failed transaction's envelope participants are fixed in 9538b3c")
        self.assertIsNone(WB.known_issue(PARTICIPANT, commit="3e22515a44979fdc3a558fda3991ca2b48e38cef"))

    def test_unknown_commit_stays_unexplained(self):
        self.assertIsNone(WB.known_issue(PARTICIPANT, commit="0" * 40))
        self.assertIsNone(WB.known_issue(PARTICIPANT))

    def test_fixed_upstream_labels(self):
        self.assertIn("record:R11", WB.fixed_upstream())



class Protocols(unittest.TestCase):
    """wallet-backend replays produce SEP41 and BLEND unless told otherwise; other adapters produce none."""
    def a(self, adapter, protocols=None):
        import argparse
        return argparse.Namespace(adapter=adapter, protocols=protocols)

    def test_defaults_and_overrides(self):
        self.assertEqual(replay.protocols_of(self.a("wallet-backend")), ["SEP41", "BLEND"])
        self.assertEqual(replay.protocols_of(self.a("wallet-backend", "none")), [])
        self.assertEqual(replay.protocols_of(self.a("wallet-backend", "SEP41")), ["SEP41"])
        self.assertEqual(replay.protocols_of(self.a("stellar-etl")), [])


if __name__ == "__main__":
    unittest.main()
