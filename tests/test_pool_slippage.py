"""stellar-etl#451: the oracle's port of go-stellar-sdk's pool formulas (exp/orderbook/pools.go), and
the trade_detail check. The port is pinned on hand-computed cases; on the corpus it gives Horizon
v30.0.1's stored rounding slippage for every pool trade (harness/replay/out-horizon)."""
import sys
import unittest

from tests.helpers import ROOT, load_module

sys.path.insert(0, str(ROOT / "harness" / "replay"))
sys.path.insert(0, str(ROOT / "tools"))
import classify  # noqa: E402

etl = load_module("etl_expect_pools", "harness/replay/adapters/stellar-etl/expect.py")
TX = "aa" * 32


class PoolFormulas(unittest.TestCase):
    def test_expectation_follows_the_code_not_the_comment(self):
        # X=200, Y=300, y=3, fee 30: ceil(600/(297*0.997)) = 3; the code's slippage is 48, after its
        # final division by 100 (its comment says 4778).
        self.assertEqual(etl.pool_expectation_slippage(200, 300, 3, 30), 48)

    def test_exact_division_has_no_slippage(self):
        # X=100, Y=200, y=100, fee 0: 100*100/(100) = 100 exactly
        self.assertEqual(etl.pool_expectation_slippage(100, 200, 100, 0), 0)

    def test_expectation_refuses_draining_the_pool(self):
        self.assertIsNone(etl.pool_expectation_slippage(100, 200, 200, 30))

    def test_payout(self):
        # X=1000, Y=1000, x=10, fee 30: 1000*10*9970/(1000*10000+10*9970) = 9.87..., floored to 9
        self.assertEqual(etl.pool_payout_slippage(1000, 1000, 10, 30), 8)
        self.assertIsNone(etl.pool_payout_slippage(1000, 1000, 2 ** 63 - 1, 30))
        self.assertIsNone(etl.pool_payout_slippage(1000, 1000, 10, 10_000))


class TradeDetail(unittest.TestCase):
    EXP = {"expect": "trade_detail", "tx_hash": TX, "op_order": 1, "order": 0, "field": "rounding_slippage", "value": 0}

    def obs(self, **kw):
        o = {"ingested": True, "error": None, "transactions": [], "operations": [], "state_changes": [], "unreadable": []}
        o.update(kw)
        return o

    def test_met_wrong_missing_and_not_checked(self):
        row = {"tx_hash": TX, "op_order": 1, "order": 0, "rounding_slippage": 0}
        self.assertEqual(classify.classify([self.EXP], self.obs(trades=[row]))["result"], "pass")
        self.assertEqual(classify.classify([self.EXP], self.obs(trades=[dict(row, rounding_slippage=43)]))["result"], "mishandled")
        self.assertEqual(classify.classify([self.EXP], self.obs(trades=[dict(row, order=1)]))["result"], "dropped")
        self.assertEqual(classify.classify([self.EXP], self.obs())["result"], "pass")


if __name__ == "__main__":
    unittest.main()
