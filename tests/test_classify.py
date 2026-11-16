"""harness/replay/classify.py: pass, mishandled and dropped from synthetic observations."""
import sys
import unittest

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "harness" / "replay"))
sys.path.insert(0, str(ROOT / "tools"))
import classify  # noqa: E402
import strkey  # noqa: E402
import strkeyx  # noqa: E402

A = strkey.account("11" * 32)
B = strkey.account("22" * 32)
C = strkey.contract("33" * 32)
TX = "aa" * 32


def obs(**kw):
    o = {"ingested": True, "error": None, "transactions": [], "operations": [], "state_changes": [],
         "unreadable": []}
    o.update(kw)
    return o


def sc(category, reason, account, **kw):
    r = {"category": category, "reason": reason, "account": account, "tx_hash": TX, "stored": {}}
    r.update(kw)
    return r


class Ledger(unittest.TestCase):
    def test_ingested_with_no_expectation_passes(self):
        self.assertEqual(classify.classify([], obs())["result"], "pass")

    def test_error_on_a_valid_ledger_is_mishandled(self):
        r = classify.classify([], obs(ingested=False, error="panic: index out of range"))
        self.assertEqual(r["result"], "mishandled")
        self.assertIn("panic", r["mishandled"][0])

    def test_silently_missing_ledger_is_dropped(self):
        r = classify.classify([], obs(ingested=False, error=None, ledger_seq=7))
        self.assertEqual(r["result"], "dropped")
        self.assertIn("ledger 7 is missing", r["dropped"][0])

    def test_adapter_failure_is_not_blamed_on_the_indexer(self):
        self.assertEqual(classify.classify([], obs(adapter_failure=True, error="build failed"))["result"], "error")

    def test_an_address_that_does_not_read_back_is_mishandled(self):
        bad = {"table": "state_changes", "column": "account_id", "stored_hex": "30" + "00" * 31,
               "reads_back_as": "?", "problem": "32 bytes, expected 33"}
        self.assertEqual(classify.classify([], obs(unreadable=[bad]))["result"], "mishandled")


class StateChange(unittest.TestCase):
    EXP = {"expect": "state_change", "category": "SIGNER", "reason": "ADD", "account": A, "tx_hash": TX}

    def test_row_present(self):
        r = classify.classify([self.EXP], obs(state_changes=[sc("SIGNER", "ADD", A)]))
        self.assertEqual(r["result"], "pass")

    def test_row_absent_is_dropped(self):
        r = classify.classify([self.EXP], obs(state_changes=[sc("SIGNER", "ADD", B)]))
        self.assertEqual(r["result"], "dropped")

    def test_truncated_address_is_mishandled(self):
        full = strkeyx.to_raw(A)
        row = sc("SIGNER", "ADD", "GTRUNCATED", stored={"account": full[:20].hex()})
        r = classify.classify([self.EXP], obs(state_changes=[row]))
        self.assertEqual(r["result"], "mishandled", r)
        self.assertIn("truncated", r["mishandled"][0])

    def test_count(self):
        exp = dict(self.EXP, count=2)
        self.assertEqual(classify.classify([exp], obs(state_changes=[sc("SIGNER", "ADD", A)]))["result"], "dropped")
        two = [sc("SIGNER", "ADD", A), sc("SIGNER", "ADD", A)]
        self.assertEqual(classify.classify([exp], obs(state_changes=two))["result"], "pass")

    def test_wrong_field_value_is_mishandled(self):
        exp = dict(self.EXP, fields={"weight": 1})
        row = sc("SIGNER", "ADD", A, fields={"weight": 2})
        self.assertEqual(classify.classify([exp], obs(state_changes=[row]))["result"], "mishandled")

    def test_exact_count_fails_a_duplicate(self):
        exp = dict(self.EXP, exact=True)
        self.assertEqual(classify.classify([exp], obs(state_changes=[sc("SIGNER", "ADD", A)]))["result"], "pass")
        two = [sc("SIGNER", "ADD", A), sc("SIGNER", "ADD", A)]
        r = classify.classify([exp], obs(state_changes=two))
        self.assertEqual(r["result"], "mishandled")
        self.assertIn("2 rows stored", r["mishandled"][0])

    def test_exact_count_passes_a_row_that_records_no_change(self):
        """A threshold set to its old value gets its own row: an extra row, not a duplicate."""
        exp = dict(self.EXP, exact=True)
        rows = [sc("SIGNER", "ADD", A, fields={"threshold": "LOW", "threshold_old": 1, "threshold_new": 1}),
                sc("SIGNER", "ADD", A, fields={"threshold": "HIGH", "threshold_old": 1, "threshold_new": 2})]
        r = classify.classify([exp], obs(state_changes=rows))
        self.assertEqual(r["result"], "pass")
        self.assertIn("record no change", r["checks"][0]["detail"])

    def test_no_state_change(self):
        exp = dict(self.EXP, expect="no_state_change")
        self.assertEqual(classify.classify([exp], obs())["result"], "pass")
        self.assertEqual(classify.classify([exp], obs(state_changes=[sc("SIGNER", "ADD", A)]))["result"], "mishandled")


class Balance(unittest.TestCase):
    EXP = {"expect": "balance_net", "account": A, "token": C, "tx_hash": TX, "op_order": 1, "delta": -5}

    def rows(self, *pairs):
        return [sc("BALANCE", reason, A, token=C, op_order=1, fields={"amount": str(n)}) for reason, n in pairs]

    def test_credit_minus_debit(self):
        r = classify.classify([self.EXP], obs(state_changes=self.rows(("DEBIT", 7), ("CREDIT", 2))))
        self.assertEqual(r["result"], "pass")

    def test_wrong_sum_is_mishandled(self):
        self.assertEqual(classify.classify([self.EXP], obs(state_changes=self.rows(("DEBIT", 7))))["result"], "mishandled")

    def test_no_row_is_dropped(self):
        self.assertEqual(classify.classify([self.EXP], obs())["result"], "dropped")

    def test_signed_movements_from_another_indexer(self):
        mv = [{"tx_hash": TX, "op_order": 1, "account": A, "token": C, "delta": -5}]
        self.assertEqual(classify.classify([self.EXP], obs(balance_movements=mv))["result"], "pass")


class Participants(unittest.TestCase):
    def tx(self, *parts):
        return [{"hash": TX, "participants": list(parts)}]

    def test_participant(self):
        exp = {"expect": "participant", "account": A, "tx_hash": TX}
        self.assertEqual(classify.classify([exp], obs(transactions=self.tx(A)))["result"], "pass")
        self.assertEqual(classify.classify([exp], obs(transactions=self.tx(B)))["result"], "dropped")

    def test_within_meta(self):
        exp = {"expect": "participants_within", "tx_hash": TX, "allowed": [A, C], "success": True}
        self.assertEqual(classify.classify([exp], obs(transactions=self.tx(A, C)))["result"], "pass")

    def test_an_envelope_only_address_is_mishandled(self):
        exp = {"expect": "participants_within", "tx_hash": TX, "allowed": [A], "success": False}
        r = classify.classify([exp], obs(transactions=self.tx(A, B)))
        self.assertEqual(r["result"], "mishandled")
        self.assertIn(B, r["mishandled"][0])
        self.assertIn("failed", r["mishandled"][0])

    def test_operation_participants_and_state_changes_count_too(self):
        exp = {"expect": "participants_within", "tx_hash": TX, "allowed": [A]}
        ops = [{"tx_hash": TX, "op_order": 1, "participants": [A, B]}]
        self.assertEqual(classify.classify([exp], obs(transactions=self.tx(A), operations=ops))["result"], "mishandled")
        rows = [sc("ACCOUNT", "CREATE", C)]
        r = classify.classify([exp], obs(transactions=self.tx(A), state_changes=rows))
        self.assertEqual(r["result"], "mishandled")
        self.assertIn("ACCOUNT/CREATE", r["mishandled"][0])


class Muxed(unittest.TestCase):
    EXP = {"expect": "muxed_destination", "tx_hash": TX, "op_order": 1, "account": A, "muxed": None, "amount": 10}

    def mv(self, to_muxed, delta=10):
        return [{"tx_hash": TX, "op_order": 1, "account": A, "delta": delta, "to_muxed": to_muxed}]

    def test_memo_payment_has_no_muxed_destination(self):
        self.assertEqual(classify.classify([self.EXP], obs(balance_movements=self.mv(None)))["result"], "pass")

    def test_fabricated_muxed_destination_is_mishandled(self):
        r = classify.classify([self.EXP], obs(balance_movements=self.mv("MFABRICATED")))
        self.assertEqual(r["result"], "mishandled")

    def test_an_observation_without_the_field_is_not_judged(self):
        mv = [{"tx_hash": TX, "op_order": 1, "account": A, "delta": 10}]
        r = classify.classify([self.EXP], obs(balance_movements=mv))
        self.assertEqual((r["result"], r["checks"][0]["outcome"]), ("pass", "not_checked"))

    def test_no_receipt_is_dropped(self):
        self.assertEqual(classify.classify([self.EXP], obs(balance_movements=[]))["result"], "dropped")


class NativeBalance(unittest.TestCase):
    def test_balance(self):
        exp = {"expect": "native_balance", "account": A, "balance": 7}
        self.assertEqual(classify.classify([exp], obs(native_balances=[{"account": A, "balance": 7}]))["result"], "pass")
        self.assertEqual(classify.classify([exp], obs(native_balances=[{"account": A, "balance": 8}]))["result"], "mishandled")
        self.assertEqual(classify.classify([exp], obs(native_balances=[]))["result"], "dropped")

    def test_removed_account(self):
        exp = {"expect": "native_balance", "account": A, "balance": None}
        self.assertEqual(classify.classify([exp], obs(native_balances=[]))["result"], "pass")
        self.assertEqual(classify.classify([exp], obs(native_balances=[{"account": A, "balance": 0}]))["result"], "mishandled")

    def test_an_observation_without_current_state_is_not_judged(self):
        exp = {"expect": "native_balance", "account": A, "balance": 7}
        r = classify.classify([exp], obs())
        self.assertEqual((r["result"], r["checks"][0]["outcome"]), ("pass", "not_checked"))


class AtMost(unittest.TestCase):
    """stellar-etl#456: no more offer effects for an operation than the offer entries it changed."""
    EXP = {"expect": "effect_count_at_most", "tx_hash": TX, "op_order": 1,
           "reasons": ["offer_created", "offer_updated", "offer_removed"], "max": 1}

    def rows(self, *reasons):
        return [sc("EFFECT", r, A, fields={"op_order": 1}) for r in reasons]

    def test_within_the_bound(self):
        self.assertEqual(classify.classify([self.EXP], obs(state_changes=self.rows("offer_updated", "trade")))["result"], "pass")

    def test_spurious_offer_effects_are_mishandled(self):
        r = classify.classify([self.EXP], obs(state_changes=self.rows("offer_updated", "offer_removed", "offer_created")))
        self.assertEqual(r["result"], "mishandled")
        self.assertIn("3 stored", r["mishandled"][0])


class OperationDetail(unittest.TestCase):
    """stellar-etl#462: a deploy's details carry its salt and the contract ID its preimage gives."""
    def ops(self, **details):
        return [{"tx_hash": TX, "op_order": 1, "details": details}]

    def test_present_and_equal(self):
        exp = {"expect": "operation_detail", "tx_hash": TX, "op_order": 1, "field": "contract_id", "value": C}
        self.assertEqual(classify.classify([exp], obs(operations=self.ops(contract_id=C)))["result"], "pass")
        self.assertEqual(classify.classify([exp], obs(operations=self.ops(contract_id=strkey.contract("44" * 32))))["result"], "mishandled")

    def test_missing_field_is_dropped(self):
        exp = {"expect": "operation_detail", "tx_hash": TX, "op_order": 1, "field": "salt"}
        self.assertEqual(classify.classify([exp], obs(operations=self.ops(contract_id=C)))["result"], "dropped")


class Unknown(unittest.TestCase):
    def test_unknown_kind_is_counted_not_judged(self):
        r = classify.classify([{"expect": "from_the_future"}], obs())
        self.assertEqual((r["result"], r["unknown_expectations"]), ("pass", 1))


if __name__ == "__main__":
    unittest.main()
