"""An adversarial review of tools/oracle.py and the adapters' oracle mappings (16 November 2026).

Each test states what the oracle should report for a ledger shape, against stellar-core's semantics.
A test marked expectedFailure is a hole the review found: it fails today, so the decorator keeps CI
green, and it will report an unexpected success once the oracle is fixed, which is the signal to
drop the decorator. The tests without the decorator pin behaviour the review checked and found right.
"""
import json
import unittest

from tests.helpers import ROOT, load_module

import sys
sys.path.insert(0, str(ROOT / "tools"))
import oracle  # noqa: E402
import strkey  # noqa: E402

wb = load_module("expect_wallet_backend", "harness/replay/adapters/wallet-backend/expect.py")

A = "11" * 32
B = "22" * 32
T = "33" * 32  # a pre-authorized transaction hash


def account(key, balance=10_000_000, signers=(), thresholds="01000000", sponsor=None):
    entry = {"data": {"type": "ACCOUNT", "account": {
        "accountID": {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": key}, "balance": balance, "seqNum": 1,
        "numSubEntries": len(signers), "inflationDest": None, "flags": 0, "homeDomain": "",
        "thresholds": thresholds, "signers": list(signers), "ext": {"v": 0}}}, "ext": {"v": 0}}
    if sponsor:
        entry["ext"] = {"v": 1, "v1": {"sponsoringID": {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": sponsor}}}
    return entry


def preauth(h, weight=1):
    return {"key": {"type": "SIGNER_KEY_TYPE_PRE_AUTH_TX", "preAuthTx": h}, "weight": weight}


def state(e):
    return {"type": "LEDGER_ENTRY_STATE", "state": e}


def updated(e):
    return {"type": "LEDGER_ENTRY_UPDATED", "updated": e}


def removed_account(key):
    return {"type": "LEDGER_ENTRY_REMOVED", "removed": {"type": "ACCOUNT", "account": {
        "accountID": {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": key}}}}


def changes_of(chs):
    out = []
    for k, pre, post in oracle.pairs(chs):
        out += list(oracle.diff(k, pre and pre["data"], post and post["data"]))
        out += list(oracle.sponsorship(k, pre, post))
    return out


class Holes(unittest.TestCase):
    @unittest.expectedFailure
    def test_master_key_weight_change_is_reported(self):
        """SetOptions masterWeight changes thresholds[0]. Horizon reports it as a signer change for the
        account's own key; the oracle compares thresholds 1 to 3 only, so the change is invisible and
        no indexer row for it is ever checked."""
        found = changes_of([state(account(A, thresholds="01000000")), updated(account(A, thresholds="00000000"))])
        self.assertIn({"what": "signer", "how": "removed", "account": strkey.account(A), "signer": strkey.account(A)},
                      found)

    @unittest.expectedFailure
    def test_wallet_backend_expects_the_one_time_signer_removed_by_a_failed_transaction(self):
        """stellar-core removes a pre-authorized-transaction signer when its transaction is applied,
        even when it fails (CAP-28; TransactionFrame::processSignatures), in txChangesBefore. The
        wallet-backend mapping skips every change of a failed transaction, so the SIGNER REMOVE row is
        never expected and known.json's rule for stellar/wallet-backend#818 can never match."""
        c = {"what": "signer", "how": "removed", "account": strkey.account(A),
             "signer": oracle.signer_strkey(preauth(T)["key"]), "tx": 0, "tx_hash": "ab" * 32, "success": False,
             "where": "before", "op_type": None}
        exps = wb.expectations([c], "Test SDF Network ; September 2015")
        self.assertTrue(any(e.get("category") == "SIGNER" and e.get("reason") == "REMOVE" for e in exps), exps)


class CheckedAndRight(unittest.TestCase):
    def test_one_time_signer_removal_is_derived_from_tx_changes_before(self):
        found = changes_of([state(account(A, signers=[preauth(T)])), updated(account(A))])
        self.assertEqual([c["what"] + " " + c["how"] for c in found], ["signer removed"])

    def test_account_merge_moves_the_whole_balance(self):
        chs = [state(account(A, balance=5_000)), removed_account(A),
               state(account(B, balance=1_000)), updated(account(B, balance=6_000))]
        d = oracle._balance_holdings(chs)
        self.assertEqual(d, {(A, "native"): -5_000, (B, "native"): 5_000})

    def test_sponsorship_ends_when_the_sponsored_account_is_merged(self):
        found = changes_of([state(account(A, sponsor=B)), removed_account(A)])
        self.assertIn("sponsorship removed", [c["what"] + " " + c["how"] for c in found])

    def test_fee_bump_fee_and_soroban_refund_are_netted_per_list(self):
        """balances() nets feeProcessing and postTxApplyFeeProcessing separately and sums them: a
        refund after a charge gives the net fee, not the charge."""
        value = {"v": 2, "v2": {"txProcessing": [{
            "result": {"transactionHash": "cd" * 32, "result": {"feeCharged": 70, "result": {
                "code": "txFEE_BUMP_INNER_SUCCESS", "innerResultPair": {"result": {"result": {"code": "txSUCCESS",
                                                                                      "results": []}}}}}},
            "feeProcessing": [state(account(B, balance=1_000)), updated(account(B, balance=900))],
            "txApplyProcessing": {"v": 4, "v4": {"txChangesBefore": [], "operations": [], "txChangesAfter": []}},
            "postTxApplyFeeProcessing": [state(account(B, balance=900)), updated(account(B, balance=930))]}]}}
        recs = oracle.balances(value)
        self.assertEqual([(r["where"], r["account"], r["delta"]) for r in recs], [("fee", strkey.account(B), -70)])

    def test_a_failed_transaction_gets_no_operation_changes(self):
        value = {"v": 2, "v2": {"txProcessing": [{
            "result": {"transactionHash": "ef" * 32, "result": {"feeCharged": 100, "result": {
                "code": "txFAILED", "results": [{"code": "opINNER", "tr": {"type": "PAYMENT"}}]}}},
            "feeProcessing": [], "txApplyProcessing": {"v": 4, "v4": {
                "txChangesBefore": [], "operations": [], "txChangesAfter": []}}}]}}
        self.assertEqual(oracle.changes(value), [])


if __name__ == "__main__":
    unittest.main()
