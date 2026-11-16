"""tools/oracle.py: the rows it derives from a ledger, against facts the test writes out by hand.

Each expectation comes from somewhere other than the code path under test: what a tools/localcore.py
scenario submitted (keys derive from fixed strings, amounts are in the scenario), or, for network and
golden ledgers, the operation body in the envelope and the result stellar-core reported. The negative
tests build an observation that meets every row the oracle derives for a transaction, check it passes,
then take one row away and check the verdict turns.
"""
import copy
import sys
import unittest

from tests.helpers import ROOT, load_module

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "harness" / "replay"))
import classify  # noqa: E402
import oracle  # noqa: E402
import strkey  # noqa: E402
from localcore import Keys  # noqa: E402

WB = load_module("wb_expect", "harness/replay/adapters/wallet-backend/expect.py")
_CACHE = {}


def ledger(eid):
    if eid not in _CACHE:
        _CACHE[eid] = oracle.load_entry(eid)
    return _CACHE[eid]


def tx_of(eid, prefix):
    """(full hash, envelope, signed transaction, TransactionResult) of the transaction whose hash starts with prefix."""
    e, v = ledger(eid)
    envs = oracle.envelopes_by_hash(v, e["source"]["network_passphrase"])
    h = next(k for k in envs if k.startswith(prefix))
    res = next(tp["result"]["result"] for tp in v["v%d" % v["v"]]["txProcessing"] if tp["result"]["transactionHash"] == h)
    return h, envs[h][0], envs[h][1], res


def acct(key):
    """MuxedAccount, AccountID or SCAddress dict -> G address of the base account."""
    if "med25519" in key:
        return strkey.account(key["med25519"]["ed25519"])
    return strkey.account(key["ed25519"])


def balance(eid, h, account, holding, where):
    if isinstance(holding, dict) and holding.get("type") == "ASSET_TYPE_NATIVE":
        holding = "native"
    _, v = ledger(eid)
    got = [b["delta"] for b in oracle.balances(v) if b["tx_hash"] == h and b["account"] == account
           and b["where"] == where and (b["holding"] == holding or (holding != "native" and b["holding"] != "native"
                                                                   and _same_asset(b["holding"], holding)))]
    return sum(got) if got else None


def _same_asset(a, b):
    return {k: v for k, v in a.items() if k != "type"} == {k: v for k, v in b.items() if k != "type"}


def changes(eid, h=None):
    _, v = ledger(eid)
    return [c for c in oracle.changes(v) if h is None or c["tx_hash"] == h]


class Payment(unittest.TestCase):
    """localcore-memo-and-offer-p30-4: the root account pays the payee 1 XLM; then the payee's offer fails."""
    E = "localcore-memo-and-offer-p30-4"

    def test_payment_moves_one_xlm(self):
        root = strkey.account(Keys(secret=__import__("hashlib").sha256(
            b"Test SDF Network ; September 2015").digest()).pub)
        payee = strkey.account(Keys("memo payee").pub)
        _, v = ledger(self.E)
        pays = [b for b in oracle.balances(v) if b["where"] == 0 and b["holding"] == "native"]
        self.assertIn((payee, 1_0000000), [(b["account"], b["delta"]) for b in pays])
        self.assertIn((root, -1_0000000), [(b["account"], b["delta"]) for b in pays])

    def test_failed_transaction_changes_nothing_but_its_fee(self):
        payee = strkey.account(Keys("memo payee").pub)
        _, v = ledger(self.E)
        failed = [tp["result"] for tp in v["v%d" % v["v"]]["txProcessing"]
                  if tp["result"]["result"]["result"]["code"] == "txFAILED"]
        self.assertEqual(len(failed), 1)
        h = failed[0]["transactionHash"]
        self.assertEqual([c for c in oracle.changes(v) if c["tx_hash"] == h and c["what"] != "sponsorship"], [])
        rows = [b for b in oracle.balances(v) if b["tx_hash"] == h]
        self.assertEqual([(b["account"], b["where"], b["delta"]) for b in rows],
                         [(payee, "fee", -failed[0]["result"]["feeCharged"])])
        pp = "Test SDF Network ; September 2015"
        p = next(p for p in oracle.participants(v, pp) if p["tx_hash"] == h)
        self.assertFalse(p["success"])
        # protocol 23+: the fee event is emitted in the name of the native asset contract
        self.assertEqual(p["shown"], sorted([payee, WB.asset_contract({"type": "ASSET_TYPE_NATIVE"}, pp)]))


class PathPayment(unittest.TestCase):
    def test_strict_receive_credits_dest_amount(self):
        e = "golden-pathpayment-34519f44-22"
        h, _, tx, res = tx_of(e, "ca554a576e40")
        op = tx["operations"][0]["body"]["pathPaymentStrictReceiveOp"]
        self.assertEqual(res["result"]["code"], "txSUCCESS")
        self.assertEqual(balance(e, h, acct(op["destination"]), op["destAsset"], 0), op["destAmount"])
        source = acct(tx["operations"][0].get("sourceAccount") or tx["sourceAccount"])
        sent = -balance(e, h, source, op["sendAsset"], 0)
        self.assertTrue(0 < sent <= op["sendMax"], sent)

    def test_strict_send_debits_send_amount_and_credits_the_result(self):
        e = "golden-frozenledgerkeys-7a27fd53-34"
        h, _, tx, res = tx_of(e, "20c4e6cc9648")
        op = tx["operations"][0]["body"]["pathPaymentStrictSendOp"]
        last = res["result"]["results"][0]["tr"]["pathPaymentStrictSendResult"]["success"]["last"]
        source = acct(tx["operations"][0].get("sourceAccount") or tx["sourceAccount"])
        dest = acct(op["destination"])
        self.assertNotEqual(source, dest)
        self.assertEqual(balance(e, h, source, op["sendAsset"], 0), -op["sendAmount"])
        self.assertEqual(balance(e, h, dest, op["destAsset"], 0), last["amount"])


class FeeBump(unittest.TestCase):
    def test_the_fee_source_pays_the_fee_and_the_inner_source_pays_nothing(self):
        e = "golden-invokehostfunction-f5fa0a4b-12"
        h, env, inner, res = tx_of(e, "26a20d50145d")
        self.assertEqual(env["type"], "ENVELOPE_TYPE_TX_FEE_BUMP")
        fee_source = acct(env["feeBump"]["tx"]["feeSource"])
        self.assertEqual(balance(e, h, fee_source, "native", "fee"), -res["feeCharged"])
        self.assertIsNone(balance(e, h, acct(inner["sourceAccount"]), "native", "fee"))


class FinalBalances(unittest.TestCase):
    def test_a_fee_bump_fee_source_ends_lower_by_the_fee(self):
        """The case wallet-backend#641 fixed: the fee source's balance moves only in the fee phase."""
        e = "golden-invokehostfunction-f5fa0a4b-12"
        h, env, inner, res = tx_of(e, "26a20d50145d")
        _, v = ledger(e)
        before, after = oracle.final_native_balances(v)[acct(env["feeBump"]["tx"]["feeSource"])]
        self.assertEqual(before - after, res["feeCharged"])

    def test_created_and_merged_accounts(self):
        """classic-p22: root creates the payee with 100 XLM."""
        _, v = ledger("localcore-classic-p22-3")
        payee = strkey.account(Keys("memo payee").pub)
        self.assertEqual(oracle.final_native_balances(v)[payee], (None, 100_0000000))


class ClaimableBalance(unittest.TestCase):
    def test_created_with_the_claimants_and_amount_of_the_operation(self):
        e = "golden-frozenledgerkeys-a0fb94c3-10"
        h, _, tx, res = tx_of(e, "58acd92a9c9e")
        op = tx["operations"][0]["body"]["createClaimableBalanceOp"]
        bid = res["result"]["results"][0]["tr"]["createClaimableBalanceResult"]["balanceID"]
        c = next(c for c in changes(e, h) if c["what"] == "claimable")
        self.assertEqual((c["how"], c["balance_id"], c["amount"]), ("created", "00000000" + bid["v0"], op["amount"]))
        self.assertEqual(sorted(c["claimants"]), sorted(acct(x["v0"]["destination"]) for x in op["claimants"]))
        source = acct(tx["operations"][0].get("sourceAccount") or tx["sourceAccount"])
        self.assertEqual(balance(e, h, source, op["asset"], 0), -op["amount"])

    def test_claimed(self):
        e = "golden-claimablebalance-3635a801-1"
        h, _, tx, _ = tx_of(e, "6b6008c925d3")
        bid = tx["operations"][0]["body"]["claimClaimableBalanceOp"]["balanceID"]
        c = next(c for c in changes(e, h) if c["what"] == "claimable")
        self.assertEqual((c["how"], c["balance_id"]), ("removed", "00000000" + bid["v0"]))
        claimant = acct(tx["operations"][0].get("sourceAccount") or tx["sourceAccount"])
        self.assertEqual(balance(e, h, claimant, "native", 0), c["amount"])


class Pool(unittest.TestCase):
    def test_deposit_moves_the_depositors_assets_into_the_reserves(self):
        e = "golden-frozenledgerkeys-0d70bfa2-11"
        h, _, tx, _ = tx_of(e, "9bab2b1450bf")
        op = tx["operations"][0]["body"]["liquidityPoolDepositOp"]
        c = next(c for c in changes(e, h) if c["what"] == "pool")
        self.assertEqual(c["pool_id"], op["liquidityPoolID"])
        self.assertTrue(0 < c["reserve_a"] <= op["maxAmountA"] and 0 < c["reserve_b"] <= op["maxAmountB"])
        source = acct(tx["operations"][0].get("sourceAccount") or tx["sourceAccount"])
        self.assertEqual(balance(e, h, source, c["assets"][0], 0), -c["reserve_a"])
        self.assertEqual(balance(e, h, source, c["assets"][1], 0), -c["reserve_b"])
        self.assertGreater(c["shares"], 0)

    def test_withdraw_burns_the_shares_of_the_operation(self):
        e = "testnet-5718650"
        h, _, tx, _ = tx_of(e, "b4d98aef2041")
        op = tx["operations"][0]["body"]["liquidityPoolWithdrawOp"]
        c = next(c for c in changes(e, h) if c["what"] == "pool")
        self.assertEqual((c["pool_id"], c["shares"]), (op["liquidityPoolID"], -op["amount"]))
        self.assertTrue(-c["reserve_a"] >= op["minAmountA"] and -c["reserve_b"] >= op["minAmountB"])
        source = acct(tx["sourceAccount"])
        self.assertEqual(balance(e, h, source, c["assets"][0], 0), -c["reserve_a"])

    def test_revocation_removes_both_pool_share_trustlines(self):
        """pools-sponsorship-p30: revoking AAA redeems the trustor's shares in AAA/BBB and AAA/CCC."""
        trustor = strkey.account(Keys("pools trustor").pub)
        cs = changes("localcore-pool-revoke-two-pools-7")
        removed = [c for c in cs if c["what"] == "trustline" and c["how"] == "removed"]
        self.assertEqual(len(removed), 2)
        self.assertTrue(all(c["account"] == trustor and c["holding"][0] == "pool" for c in removed))
        self.assertEqual(len({c["holding"][1] for c in removed}), 2)
        cleared = [c for c in cs if c["what"] == "trustauth" and c["how"] == "cleared"]
        self.assertEqual([c["account"] for c in cleared], [trustor])


class Clawback(unittest.TestCase):
    def test_takes_the_amount_from_the_holder(self):
        e = "testnet-5600000"
        h, _, tx, _ = tx_of(e, "887fc0052d18")
        op = tx["operations"][0]["body"]["clawbackOp"]
        self.assertEqual(balance(e, h, acct(op["from"]), op["asset"], 0), -op["amount"])


class Sponsorship(unittest.TestCase):
    """pools-sponsorship-p30: sponsor one pays for the claimant's data entry and signer; sponsor two takes over."""
    claimant, s1, s2 = (strkey.account(Keys(n).pub) for n in ("pools claimant", "sponsor one", "sponsor two"))

    def test_begin_sponsoring(self):
        cs = changes("localcore-claim-and-sponsor-8")
        self.assertIn(("data", "added", self.claimant), [(c["what"], c["how"], c.get("account")) for c in cs])
        sp = [(c["entry"], c["sponsor"]) for c in cs if c["what"] == "sponsorship" and c["how"] == "created"]
        self.assertIn(("data", self.s1), sp)
        sig = [c for c in cs if c["what"] == "signer-sponsorship"]
        self.assertEqual([(c["account"], c["signer"], c["sponsor"]) for c in sig], [(self.claimant, self.s2, self.s1)])

    def test_transfer(self):
        cs = changes("localcore-sponsorship-transfer-9")
        moved = sorted((c["what"], c["former_sponsor"], c["sponsor"]) for c in cs if c["how"] == "updated")
        self.assertEqual(moved, [("signer-sponsorship", self.s1, self.s2), ("sponsorship", self.s1, self.s2)])


class ContractCreatesTrustline(unittest.TestCase):
    def test_trust_creates_an_authorized_usd_trustline(self):
        """sac-trust-p28: the trustor calls the USD asset contract's trust(); no ChangeTrust runs."""
        trustor = strkey.account(Keys("sac trustor").pub)
        cs = changes("localcore-sac-trust-p28-5")
        self.assertEqual(sorted((c["what"], c["how"], c["account"], c["op_type"]) for c in cs),
                         [("trustauth", "set", trustor, "INVOKE_HOST_FUNCTION"),
                          ("trustline", "added", trustor, "INVOKE_HOST_FUNCTION")])
        tl = next(c for c in cs if c["what"] == "trustline")
        self.assertEqual(bytes.fromhex(tl["holding"][1]["alphaNum4"]["assetCode"]), b"USD\0")


class Participants(unittest.TestCase):
    """participants-p28: an authorization entry nothing matches, and one declaring a deploy that never runs."""
    P = "Test SDF Network ; September 2015"

    def shown(self, eid):
        _, v = ledger(eid)
        (p,) = oracle.participants(v, self.P)
        return p

    def test_planted_account_is_not_shown(self):
        p = self.shown("localcore-planted-auth-5")
        caller, planted = strkey.account(Keys("participants caller").pub), strkey.account(Keys("participants planted").pub)
        self.assertTrue(p["success"])
        self.assertIn(caller, p["shown"])
        self.assertNotIn(planted, p["shown"])
        self.assertTrue(any(a.startswith("C") for a in p["shown"]), "the asset contract emitted the transfer event")

    def test_declared_contract_is_not_shown_or_created(self):
        p = self.shown("localcore-declared-deploy-6")
        deployer = strkey.account(Keys("participants deployer").pub)
        self.assertNotIn(deployer, p["shown"])
        self.assertEqual([c for c in changes("localcore-declared-deploy-6") if c["what"] == "contract"], [])

    def test_a_strkey_written_in_an_event_counts(self):
        out = set()
        oracle._addresses({"type": "SCV_STRING", "str": "USD:" + strkey.account("11" * 32)}, out)
        self.assertEqual(out, {strkey.account("11" * 32)})
        bad = strkey.account("11" * 32)[:-1] + ("A" if strkey.account("11" * 32)[-1] != "A" else "B")
        out = set()
        oracle._addresses({"type": "SCV_STRING", "str": "USD:" + bad}, out)
        self.assertEqual(out, set(), "a bad checksum is not an address")

    def test_diagnostic_events_do_not_count(self):
        out = set()
        oracle._addresses({"type": "DIAGNOSTIC", "body": {"ed25519": "11" * 32}}, out)
        self.assertEqual(out, set())


def satisfying(exps):
    """An observation that meets every expectation the wallet-backend mapping derives."""
    obs = {"ingested": True, "transactions": {}, "operations": [], "state_changes": [], "unreadable": []}
    for x in exps:
        k = x["expect"]
        if k == "state_change":
            for _ in range(int(x.get("count", 1))):
                obs["state_changes"].append({kk: x.get(kk) for kk in ("category", "reason", "tx_hash", "account",
                                                                      "token", "signer_key")} | {"fields": x.get("fields") or {}})
        elif k == "balance_net":
            obs["state_changes"].append({"category": "BALANCE", "reason": "CREDIT" if x["delta"] > 0 else "DEBIT",
                                         "tx_hash": x["tx_hash"], "op_order": x["op_order"], "account": x["account"],
                                         "token": x["token"], "fields": {"amount": str(abs(x["delta"]))}})
        elif k == "participant":
            obs["transactions"].setdefault(x["tx_hash"], set()).add(x["account"])
    obs["transactions"] = [{"hash": h, "participants": sorted(p)} for h, p in obs["transactions"].items()]
    # BALANCE rows name accounts the meta shows; keep only those, as wallet-backend's main does
    return obs


class Negative(unittest.TestCase):
    """For each kind: the observation built from the oracle's rows passes; one row less does not."""
    CASES = [("payment", "localcore-memo-and-offer-p30-4", None, "balance_net"),
             ("path payment", "golden-pathpayment-34519f44-22", "ca554a576e40", "balance_net"),
             ("fee bump", "golden-invokehostfunction-f5fa0a4b-12", "26a20d50145d", "balance_net"),
             ("claimable balance", "golden-frozenledgerkeys-a0fb94c3-10", "58acd92a9c9e", "balance_net"),
             ("pool deposit", "golden-frozenledgerkeys-0d70bfa2-11", "9bab2b1450bf", "balance_net"),
             ("pool withdraw", "testnet-5718650", "b4d98aef2041", "balance_net"),
             ("clawback", "testnet-5600000", "887fc0052d18", "balance_net"),
             ("pool-share revocation", "localcore-pool-revoke-two-pools-7", None, "state_change"),
             ("sponsored signer", "localcore-claim-and-sponsor-8", None, "state_change"),
             ("contract-created trustline", "localcore-sac-trust-p28-5", None, "state_change")]

    def expectations(self, eid, prefix):
        e, v = ledger(eid)
        pp = e["source"]["network_passphrase"]
        exps = WB.expectations(oracle.changes(v), pp) + WB.balance_expectations(oracle.balances(v), pp)
        return [x for x in exps if prefix is None or x["tx_hash"].startswith(prefix)]

    def test_each_kind(self):
        for name, eid, prefix, kind in self.CASES:
            with self.subTest(name):
                exps = self.expectations(eid, prefix)
                self.assertTrue(any(x["expect"] == kind for x in exps), "no %s row for %s" % (kind, name))
                good = satisfying(exps)
                self.assertEqual(classify.classify(exps, copy.deepcopy(good))["result"], "pass")
                i = next(i for i, r in enumerate(good["state_changes"])
                         if (r["category"] == "BALANCE") == (kind == "balance_net"))
                short = dict(good, state_changes=good["state_changes"][:i] + good["state_changes"][i + 1:])
                self.assertIn(classify.classify(exps, short)["result"], ("dropped", "mishandled"))

    def test_failed_transaction_with_an_envelope_participant(self):
        e, v = ledger("localcore-memo-and-offer-p30-4")
        pp = e["source"]["network_passphrase"]
        exps = WB.participant_expectations(oracle.participants(v, pp), pp)
        h = next(x["tx_hash"] for x in exps if x["expect"] == "participants_within" and not x["success"])
        within = [x for x in exps if x["tx_hash"] == h]
        ok = {"ingested": True, "transactions": [{"hash": h, "participants": within[0]["allowed"]}]}
        self.assertEqual(classify.classify(within, ok)["result"], "pass")
        root = strkey.account(Keys(secret=__import__("hashlib").sha256(pp.encode()).digest()).pub)
        planted = {"ingested": True, "transactions": [{"hash": h, "participants": within[0]["allowed"] + [root]}]}
        self.assertEqual(classify.classify(within, planted)["result"], "mishandled")

    def test_planted_authorization_entry(self):
        e, v = ledger("localcore-planted-auth-5")
        pp = e["source"]["network_passphrase"]
        exps = WB.participant_expectations(oracle.participants(v, pp), pp)
        x = next(x for x in exps if x["expect"] == "participants_within")
        planted = strkey.account(Keys("participants planted").pub)
        obs = {"ingested": True, "transactions": [{"hash": x["tx_hash"], "participants": x["allowed"]}]}
        self.assertEqual(classify.classify([x], obs)["result"], "pass")
        obs["operations"] = [{"tx_hash": x["tx_hash"], "op_order": 1, "participants": [planted]}]
        self.assertEqual(classify.classify([x], obs)["result"], "mishandled")


if __name__ == "__main__":
    unittest.main()
