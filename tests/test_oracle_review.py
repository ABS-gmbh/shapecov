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
    def test_master_key_weight_change_is_reported(self):
        """SetOptions masterWeight changes thresholds[0]. Horizon reports it as a signer change for the
        account's own key; the oracle compares thresholds 1 to 3 only, so the change is invisible and
        no indexer row for it is ever checked."""
        found = changes_of([state(account(A, thresholds="01000000")), updated(account(A, thresholds="00000000"))])
        self.assertIn({"what": "signer", "how": "removed", "account": strkey.account(A), "signer": strkey.account(A)},
                      found)

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


def offer_entry(seller, offer_id, amount):
    return {"data": {"type": "OFFER", "offer": {"sellerID": {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": seller},
            "offerID": offer_id, "selling": {"type": "ASSET_TYPE_NATIVE"}, "buying": {"type": "ASSET_TYPE_NATIVE"},
            "amount": amount, "price": {"n": 1, "d": 1}, "flags": 0, "ext": {"v": 0}}}, "ext": {"v": 0}}


def removed_offer(seller, offer_id):
    return {"type": "LEDGER_ENTRY_REMOVED", "removed": {"type": "OFFER", "offer": {
        "sellerID": {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": seller}, "offerID": offer_id}}}


def credit_trustline(key, balance, code="USD", issuer=B):
    return {"data": {"type": "TRUSTLINE", "trustLine": {
        "accountID": {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": key},
        "asset": {"type": "ASSET_TYPE_CREDIT_ALPHANUM4", "alphaNum4": {"assetCode": code,
                  "issuer": {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": issuer}}},
        "balance": balance, "limit": 10 ** 12, "flags": 1, "ext": {"v": 0}}}, "ext": {"v": 0}}


def ledger(code, op_type, op_result, op_changes, fee=(), after=()):
    return {"v": 1, "v1": {"txProcessing": [{
        "result": {"transactionHash": "aa" * 32, "result": {"feeCharged": 100, "result": {
            "code": code, "results": [{"code": "opINNER", "tr": dict({"type": op_type}, **op_result)}]}}},
        "feeProcessing": list(fee),
        "txApplyProcessing": {"v": 3, "v3": {"txChangesBefore": [], "operations": [{"changes": list(op_changes)}],
                                             "txChangesAfter": list(after)}}}]}}


class MoreCheckedAndRight(unittest.TestCase):
    def test_multi_hop_path_payment_gives_each_crossed_maker_a_trade(self):
        claimed = {"pathPaymentStrictSendResult": {"code": "PATH_PAYMENT_STRICT_SEND_SUCCESS", "success": {"offers": [
            {"type": "CLAIM_ATOM_TYPE_ORDER_BOOK", "orderBook": {"sellerID": {"ed25519": A}, "offerID": 7,
                                                                   "amountSold": 5, "amountBought": 5}},
            {"type": "CLAIM_ATOM_TYPE_ORDER_BOOK", "orderBook": {"sellerID": {"ed25519": B}, "offerID": 8,
                                                                   "amountSold": 9, "amountBought": 9}},
            {"type": "CLAIM_ATOM_TYPE_LIQUIDITY_POOL", "liquidityPool": {"liquidityPoolID": "44" * 32}}]}}}
        chs = [state(offer_entry(A, 7, 10)), updated(offer_entry(A, 7, 5)),
               state(offer_entry(B, 8, 9)), removed_offer(B, 8)]
        found = oracle.changes(ledger("txSUCCESS", "PATH_PAYMENT_STRICT_SEND", claimed, chs))
        trades = sorted((c["account"], c["offer_id"]) for c in found if c["what"] == "trade")
        self.assertEqual(trades, [(strkey.account(A), 7), (strkey.account(B), 8)])

    def test_an_offer_its_owner_deletes_is_no_trade(self):
        claimed = {"manageSellOfferResult": {"code": "MANAGE_SELL_OFFER_SUCCESS", "success": {"offersClaimed": []}}}
        found = oracle.changes(ledger("txSUCCESS", "MANAGE_SELL_OFFER", claimed,
                                      [state(offer_entry(A, 7, 10)), removed_offer(A, 7)]))
        self.assertEqual([c["how"] for c in found if c["what"] == "offer"], ["removed"])
        self.assertFalse([c for c in found if c["what"] == "trade"])

    def test_clawback_is_a_credit_balance_decrease_on_the_clawback_operation(self):
        chs = [state(credit_trustline(A, 1_000)), updated(credit_trustline(A, 400))]
        recs = oracle.balances(ledger("txSUCCESS", "CLAWBACK", {}, chs))
        self.assertEqual([(r["op_type"], r["account"], r["delta"]) for r in recs], [("CLAWBACK", strkey.account(A), -600)])

    def test_soroban_refund_in_tx_changes_after_counts_before_protocol_23(self):
        """Before protocol 23 (meta v3) the unused resource fee comes back in txChangesAfter; the net
        fee is the charge minus that refund (as on golden-invokehostfunction-f2fc9bf3-12)."""
        fee = [state(account(A, balance=1_000_000)), updated(account(A, balance=866_900))]
        after = [state(account(A, balance=866_900)), updated(account(A, balance=977_218))]
        recs = oracle.balances(ledger("txFAILED", "INVOKE_HOST_FUNCTION", {}, [], fee=fee, after=after))
        self.assertEqual([(r["where"], r["delta"]) for r in recs], [("fee", -22_782)])

    def test_pool_deposit_reserves_and_trustlines_are_exact(self):
        def pool(ra, rb, shares):
            return {"data": {"type": "LIQUIDITY_POOL", "liquidityPool": {"liquidityPoolID": "44" * 32, "body": {
                "type": "LIQUIDITY_POOL_CONSTANT_PRODUCT", "constantProduct": {
                    "params": {"assetA": {"type": "ASSET_TYPE_NATIVE"}, "assetB": {"type": "ASSET_TYPE_NATIVE"}, "fee": 30},
                    "reserveA": ra, "reserveB": rb, "totalPoolShares": shares, "poolSharesTrustLineCount": 1}}}},
                "ext": {"v": 0}}
        found = changes_of([state(pool(1_000, 2_000, 1_414)), updated(pool(1_333, 2_666, 1_885))])
        self.assertEqual([(c["reserve_a"], c["reserve_b"], c["shares"]) for c in found if c["what"] == "pool"],
                         [(333, 666, 471)])


if __name__ == "__main__":
    unittest.main()
