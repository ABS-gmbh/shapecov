"""stellar-etl's entry changes on a sequence: the oracle's net change per entry and ledger (as
export_ledger_entry_changes compacts each ledger), and the entry_change / entry_changes_only checks."""
import sys
import unittest

from tests.helpers import ROOT, load_module

sys.path.insert(0, str(ROOT / "harness" / "replay"))
sys.path.insert(0, str(ROOT / "tools"))
import classify  # noqa: E402
import strkey  # noqa: E402

etl = load_module("etl_expect_entries", "harness/replay/adapters/stellar-etl/expect.py")


def account(n):
    return {"type": "ACCOUNT", "account": {"accountID": {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": n * 32}}}


def entry(kind, data):
    return {"type": kind, {"LEDGER_ENTRY_STATE": "state", "LEDGER_ENTRY_CREATED": "created",
                           "LEDGER_ENTRY_UPDATED": "updated"}[kind]: {"data": data}}


def removed(n):
    return {"type": "LEDGER_ENTRY_REMOVED", "removed": {"type": "ACCOUNT", "account": {
        "accountID": {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": n * 32}}}}


def ledger(*op_changes):
    return {"v": 1, "v1": {"ledgerHeader": {"header": {"ledgerSeq": 7}}, "txProcessing": [{
        "feeProcessing": [], "postTxApplyFeeProcessing": [],
        "txApplyProcessing": {"v": 3, "v3": {"txChangesBefore": [], "txChangesAfter": [],
                                             "operations": [{"changes": list(op_changes)}]}}}],
        "upgradesProcessing": []}}


class NetChange(unittest.TestCase):
    def test_compacted_per_ledger(self):
        v = ledger(entry("LEDGER_ENTRY_STATE", account("11")), entry("LEDGER_ENTRY_UPDATED", account("11")),
                   entry("LEDGER_ENTRY_CREATED", account("22")),
                   entry("LEDGER_ENTRY_CREATED", account("33")), removed("33"),
                   entry("LEDGER_ENTRY_STATE", account("44")), removed("44"))
        net = {k[1]: c for k, c in etl.ledger_entry_changes(v).items()}
        self.assertEqual(net, {strkey.account("11" * 32): etl.CHANGE_UPDATED, strkey.account("22" * 32): etl.CHANGE_CREATED,
                               strkey.account("44" * 32): etl.CHANGE_REMOVED})  # 33: created and removed, no row

    def test_expectations_per_ledger(self):
        exps = etl.end_state_expectations([ledger(entry("LEDGER_ENTRY_CREATED", account("22")))], "p")
        rows = [e for e in exps if e["expect"] == "entry_change"]
        self.assertEqual([(e["table"], e["ledger"], e["change"], e["deleted"]) for e in rows], [("account", 7, 0, False)])
        only = [e for e in exps if e["expect"] == "entry_changes_only" and e["table"] == "account"]
        self.assertEqual(only[0]["keys"], [strkey.account("22" * 32)])


class Checks(unittest.TestCase):
    EXP = {"expect": "entry_change", "table": "account", "key": "GA", "ledger": 7, "change": 2, "deleted": True}
    ONLY = {"expect": "entry_changes_only", "table": "account", "ledger": 7, "keys": ["GA"]}

    def obs(self, *rows):
        return {"ingested": True, "error": None, "transactions": [], "operations": [], "state_changes": [],
                "unreadable": [], "entry_changes": list(rows)}

    def row(self, **kw):
        r = {"table": "account", "key": "GA", "ledger": 7, "change": 2, "deleted": True}
        r.update(kw)
        return r

    def test_met_wrong_missing(self):
        self.assertEqual(classify.classify([self.EXP, self.ONLY], self.obs(self.row()))["result"], "pass")
        self.assertEqual(classify.classify([self.EXP], self.obs(self.row(change=1, deleted=False)))["result"], "mishandled")
        self.assertEqual(classify.classify([self.EXP], self.obs(self.row(ledger=8)))["result"], "dropped")

    def test_a_row_for_an_unchanged_entry_is_mishandled(self):
        r = classify.classify([self.ONLY], self.obs(self.row(), self.row(key="GB", change=1, deleted=False)))
        self.assertEqual(r["result"], "mishandled")
        self.assertIn("GB", r["mishandled"][0])

    def test_not_checked_without_entry_changes(self):
        o = self.obs()
        del o["entry_changes"]
        self.assertEqual(classify.classify([self.EXP], o)["result"], "pass")


if __name__ == "__main__":
    unittest.main()
