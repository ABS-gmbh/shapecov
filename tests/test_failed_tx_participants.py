"""Who is a participant of a failed transaction: a declared parameter of each adapter's mapping.

wallet-backend: what the meta shows (its fix R11). Horizon: also every address the envelope names,
its design (include_failed lists a failed transaction under them). The oracle's records are the same
for both; only the declared parameter changes the expectation."""
import sys
import unittest

from tests.helpers import ROOT, load_module

sys.path.insert(0, str(ROOT / "harness" / "replay"))
sys.path.insert(0, str(ROOT / "tools"))
import strkey  # noqa: E402

wb = load_module("wb_expect_failed", "harness/replay/adapters/wallet-backend/expect.py")
hz = load_module("hz_expect_failed", "harness/replay/adapters/horizon/expect.py")

SRC = strkey.account("11" * 32)
DEST = strkey.account("22" * 32)
TX = "aa" * 32
FAILED = [{"tx_hash": TX, "success": False, "shown": [SRC], "changed": [SRC]}]


def failed_allowed(exps):
    return [e["allowed"] for e in exps if e["expect"] == "participants_within" and not e["success"]]


class FailedTransactionParticipants(unittest.TestCase):
    def test_declared_values(self):
        self.assertEqual(wb.FAILED_TX_PARTICIPANTS, "meta")
        self.assertEqual(hz.FAILED_TX_PARTICIPANTS, "envelope and meta")

    def test_wallet_backend_allows_only_what_the_meta_shows(self):
        self.assertEqual(failed_allowed(wb.participant_expectations(FAILED, "p")), [[SRC]])

    def test_horizon_also_allows_what_the_envelope_names(self):
        old = hz._envelope_addresses
        hz._envelope_addresses = lambda value, passphrase: {TX: {DEST}}
        try:
            exps = hz.participant_expectations(FAILED, "p", value={})
        finally:
            hz._envelope_addresses = old
        self.assertEqual(failed_allowed(exps), [sorted([SRC, DEST])])
        # and a failed transaction asks no participant for the accounts it changed: only the fee
        self.assertFalse([e for e in exps if e["expect"] == "participant"])

    def test_horizon_successful_transactions_stay_within_the_meta(self):
        ok = [{"tx_hash": TX, "success": True, "shown": [SRC], "changed": [SRC]}]
        old = hz._envelope_addresses
        hz._envelope_addresses = lambda value, passphrase: {TX: {DEST}}
        try:
            exps = hz.participant_expectations(ok, "p", value={})
        finally:
            hz._envelope_addresses = old
        within = [e for e in exps if e["expect"] == "participants_within"]
        self.assertEqual([e["allowed"] for e in within], [[SRC]])


if __name__ == "__main__":
    unittest.main()
