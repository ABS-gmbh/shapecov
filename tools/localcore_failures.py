"""Scenario failures-p30 for tools/localcore.py: operations and transactions that fail when they apply.

Every result code here is set while stellar-core applies a transaction, against ledger state (see
corpus/cell-classes.json, class local_core), so a transaction that sets the state up beforehand
reaches a ledger and fails there. The scenario builds that state over a few setup ledgers, then
closes ledgers that hold many failing transactions at once, one per source account (stellar-core
queues one transaction per account per ledger), so one corpus entry carries many result codes.

Recorded ledgers (run.json `ledger_<name>`):
  op-failures       about 60 transactions, each failing with one operation result code
  tx-failures-plain transactions an earlier transaction of the same ledger invalidates: the
                    source's sequence number, signers or balance changed before it applied
  tx-failures-bumped
                    the same, each victim inside a fee bump (the inner result codes), plus an
                    unclosed sponsorship sandwich
  upgrades          a ledger applying base fee, base reserve, max transaction set size and ledger
                    flags upgrades

stellar-core orders a ledger's transactions by hash, so each transaction-level case is sent four
times with different accounts; the order is fixed by the inputs, so every run gives the same
results. Not produced yet: txINSUFFICIENT_BALANCE at apply (draining the source to 50 stroops above
its reserve is not enough) and txBAD_AUTH_EXTRA outside a fee bump.

run.json also lists, per transaction, the code it was built to produce and the code it got.
"""
import hashlib
import json

import strkey

BIG = 2 ** 63 - 1
XLM = {"type": "ASSET_TYPE_NATIVE"}


def a4(code, issuer):
    return {"type": "ASSET_TYPE_CREDIT_ALPHANUM4",
            "alphaNum4": {"assetCode": (code.encode() + b"\0" * (4 - len(code))).hex(), "issuer": issuer.account()}}


def code4(code):
    return {"type": "ASSET_TYPE_CREDIT_ALPHANUM4", "assetCode4": (code.encode() + b"\0" * (4 - len(code))).hex()}


def no_opts(**kw):
    d = {"inflationDest": None, "clearFlags": None, "setFlags": None, "masterWeight": None, "lowThreshold": None,
         "medThreshold": None, "highThreshold": None, "homeDomain": None, "signer": None}
    d.update(kw)
    return d


def price(n, d=1):
    return {"n": n, "d": d}


class Run:
    """Accounts, sequence numbers and one queue of transactions per ledger."""

    def __init__(self, lc, core, enc, dec, root, step, run):
        self.lc, self.core, self.enc, self.dec, self.root, self.step, self.run = lc, core, enc, dec, root, step, run
        self.seq = {root.pub: 0}
        self.queue = []
        self.keys = {}
        run.setdefault("cases", [])

    def key(self, name):
        if name not in self.keys:
            self.keys[name] = self.lc.Keys("failures " + name)
            self.run.setdefault("accounts", {})[name] = strkey.account(self.keys[name].pub)
        return self.keys[name]

    def op(self, body_type, field, value, source=None):
        return self.lc.op(body_type, field, value, source)

    def tx(self, name, source, ops, signers=None, expect=None, memo=None, cond=None, fee=None, bump=None):
        """Queue a transaction for the next ledger. expect: the result code(s) it is built to produce,
        as {"tx": code} and/or {"op": [code per op or None]}. bump: a fee-bump fee source."""
        self.queue.append({"name": name, "source": source, "ops": ops, "signers": signers or [source],
                           "expect": expect or {}, "memo": memo, "cond": cond, "fee": fee, "bump": bump})

    def close(self, label, record=None):
        sent = []
        for t in self.queue:
            k = t["source"]
            self.seq[k.pub] += 1
            body = self.lc.tx(k.muxed(), self.seq[k.pub], t["ops"], fee=t["fee"] or 100 * len(t["ops"]) + 100, memo=t["memo"])
            if t["cond"]:
                body["cond"] = t["cond"]
            if t["bump"]:
                blob, h = self.fee_bump(body, t["signers"], t["bump"])
            else:
                blob, h = self.lc.envelope_multi(self.enc, self.core, body, t["signers"])
            rec = self.step("failures: " + t["name"], self.core.info()["ledger"]["version"], blob, h,
                            json.dumps(t["expect"]) or "applied")
            sent.append((t, h, rec))
        self.queue = []
        seq = self.core.close()
        got = self.results(seq)
        for t, h, rec in sent:
            case = {"ledger": label, "name": t["name"], "tx_hash": h, "submit": rec["status"],
                    "expect": t["expect"], "got": got.get(h)}
            case["ok"] = self.matches(t["expect"], case["got"]) if rec["status"] == "PENDING" else False
            self.run["cases"].append(case)
            if not t["expect"] and (not case["got"] or case["got"]["tx"] != "txSUCCESS"):
                print("    SETUP FAILED %-36s %s (%s)" % (t["name"], case["got"], rec["status"]), flush=True)
            if t["expect"] and not case["ok"]:
                print("    MISMATCH %-40s expected %s, got %s (%s)" % (t["name"], t["expect"], case["got"], rec["status"]), flush=True)
        if record:
            self.run["ledger_" + record] = seq
        return seq

    @staticmethod
    def matches(expect, got):
        if not got:
            return False
        if "tx" in expect and expect["tx"] != got["tx"]:
            return False
        if "op" in expect:
            for want, have in zip(expect["op"], got.get("op") or []):
                if want and want != have:
                    return False
        return True

    def results(self, seq):
        """{tx hash: {"tx": code (inner code for a fee bump), "op": [inner result code per op]}}"""
        v = self.lc.last_ledger(self.core, self.dec)
        body = v["v%d" % v["v"]]
        assert body["ledgerHeader"]["header"]["ledgerSeq"] == seq
        out = {}
        for tp in body["txProcessing"]:
            r = tp["result"]["result"]["result"]
            inner = r.get("innerResultPair", {}).get("result", {}).get("result") if r["code"].startswith("txFEE_BUMP") else None
            res = inner or r
            ops = []
            for o in res.get("results") or []:
                tr = o.get("tr")
                if not tr:
                    ops.append(o["code"])
                    continue
                arm = next((vv for kk, vv in tr.items() if kk != "type"), {})
                ops.append(arm.get("code") if isinstance(arm, dict) else arm)
            out[tp["result"]["transactionHash"]] = {"tx": res["code"], "outer": r["code"], "op": ops}
        return out

    def fee_bump(self, inner_tx, signers, fee_source):
        enc, core = self.enc, self.core
        payload = enc.encode("TransactionSignaturePayload", {"networkId": core.network_id.hex(),
                                                             "taggedTransaction": {"type": "ENVELOPE_TYPE_TX", "tx": inner_tx}})
        digest = hashlib.sha256(payload).digest()
        sigs = [{"hint": k.pub[-8:], "signature": self.lc.ed25519.sign(k.secret, digest).hex()} for k in signers]
        fb = {"feeSource": fee_source.muxed(), "fee": (inner_tx["fee"] + 100) * 2,
              "innerTx": {"type": "ENVELOPE_TYPE_TX", "v1": {"tx": inner_tx, "signatures": sigs}}, "ext": {"v": 0}}
        payload = enc.encode("TransactionSignaturePayload", {"networkId": core.network_id.hex(),
                                                             "taggedTransaction": {"type": "ENVELOPE_TYPE_TX_FEE_BUMP", "feeBump": fb}})
        digest = hashlib.sha256(payload).digest()
        env = {"type": "ENVELOPE_TYPE_TX_FEE_BUMP", "feeBump": {"tx": fb, "signatures": [
            {"hint": fee_source.pub[-8:], "signature": self.lc.ed25519.sign(fee_source.secret, digest).hex()}]}}
        return enc.encode("TransactionEnvelope", env), digest.hex()


def failures(lc, core, enc, dec, root, step, run, protocol=30):
    R = Run(lc, core, enc, dec, root, step, run)
    core.upgrade(protocol)
    K = R.key
    o = R.op
    I, J = K("issuer I"), K("issuer J")          # I: auth required, revocable, clawback; J: no flags
    IAA, JBB, JCC = a4("IAA", I), a4("JBB", J), a4("JCC", J)
    JDD, JEE = a4("JDD", J), a4("JEE", J)
    book = {"mbo cross self": JBB, "pprs cross self": JDD, "ppss cross self": JEE}  # one order book each
    pool_params = {"type": "LIQUIDITY_POOL_CONSTANT_PRODUCT", "constantProduct": {"assetA": JBB, "assetB": JCC, "fee": 30}}
    pool = hashlib.sha256(enc.encode("LiquidityPoolParameters", pool_params)).hexdigest()
    pool_line = {"type": "ASSET_TYPE_POOL_SHARE", "liquidityPool": pool_params}
    # pool of IAA/JBB, for a trustline that is not authorized to maintain liabilities
    pool2_params = {"type": "LIQUIDITY_POOL_CONSTANT_PRODUCT", "constantProduct": {"assetA": IAA, "assetB": JBB, "fee": 30}}
    pool2_line = {"type": "ASSET_TYPE_POOL_SHARE", "liquidityPool": pool2_params}

    # ---------------------------------------------------------------- accounts
    rich = ["issuer I", "issuer J", "holder", "maker", "claimant", "sponsor", "so too many signers"]
    workers = ["create exists", "merge subentries", "merge immutable", "merge sponsor", "merge seq far", "merge dest full",
               "allow no line", "allow cant revoke",
               "ct cannot delete", "ct line missing", "ct not auth maintain",
               "claim line full", "claim not auth", "cbcb missing", "cbcb not issuer", "cbcb not enabled",
               "cb not enabled", "cb no trust", "cb underfunded", "ccb underfunded", "ccb not auth",
               "lpd no trust", "lpd underfunded", "lpd bad price", "lpd not auth", "lpd line full",
               "lpw no trust", "lpw underfunded", "lpw under min", "lpw line full",
               "mbo buy no trust", "mbo sell not auth", "mbo line full", "mbo cross self",
               "mso buy not auth", "mso line full", "passive", "unauthorized", "maintain",
               "pprs no dest", "pprs no trust", "pprs not auth", "pprs src no trust", "pprs src not auth", "pprs cross self",
               "ppss no dest", "ppss not auth", "ppss src not auth", "ppss line full", "ppss cross self",
               "rs missing", "rs only transferable", "so revocable required", "so cant change", "so bad inflation",
               "stlf no line", "stlf cant revoke", "stlf invalid state", "bad sponsorship",
               "memo return"]
    poor = ["ct low reserve", "md low reserve", "so low reserve", "rs low reserve"]
    for n in rich + workers + poor:
        K(n)
    creates = [o("CREATE_ACCOUNT", "createAccountOp", {"destination": K(n).account(), "startingBalance": 10_000_0000000})
               for n in rich] + \
              [o("CREATE_ACCOUNT", "createAccountOp", {"destination": K(n).account(), "startingBalance": 100_0000000})
               for n in workers] + \
              [o("CREATE_ACCOUNT", "createAccountOp", {"destination": K(n).account(), "startingBalance": 20_5000000})
               for n in poor]  # base reserve 10 XLM: the minimum balance plus a few fees, not another subentry
    assert len(creates) <= 100, len(creates)
    R.tx("create accounts", root, creates, fee=100 * len(creates))
    born = R.close("accounts") << 32
    for n in rich + workers + poor:
        R.seq[K(n).pub] = born

    # ---------------------------------------------------------------- setup 1: flags, trustlines
    R.tx("I flags", I, [o("SET_OPTIONS", "setOptionsOp", no_opts(setFlags=1 | 2 | 8))])
    R.tx("cant change: immutable", K("so cant change"), [o("SET_OPTIONS", "setOptionsOp", no_opts(setFlags=4))])
    R.tx("merge immutable flag", K("merge immutable"), [o("SET_OPTIONS", "setOptionsOp", no_opts(setFlags=4))])
    R.tx("seq far", K("merge seq far"), [o("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": BIG - 10})])
    R.close("setup flags")
    R.seq[K("merge seq far").pub] = BIG - 10
    trust = lambda asset, limit=BIG: o("CHANGE_TRUST", "changeTrustOp", {"line": asset, "limit": limit})
    for n in ("holder", "maker", "claimant", "sponsor"):
        R.tx(n + " trusts", K(n), [trust(IAA), trust(JBB), trust(JCC)])
    for n, lines in {
            "merge subentries": [trust(JBB)], "ct cannot delete": [trust(JBB), trust(JCC)], "ct not auth maintain": [trust(JBB), trust(IAA)],
            "claim line full": [trust(JBB, 1)], "claim not auth": [trust(IAA)], "cb not enabled": [trust(JBB)],
            "cb underfunded": [trust(IAA)], "ccb underfunded": [trust(JBB)], "ccb not auth": [trust(IAA)],
            "lpd no trust": [trust(JBB), trust(JCC)], "lpd underfunded": [trust(JBB), trust(JCC)],
            "lpd bad price": [trust(JBB), trust(JCC)], "lpd not auth": [trust(IAA), trust(JBB)], "lpd line full": [trust(JBB), trust(JCC)],
            "lpw no trust": [trust(JBB), trust(JCC)], "lpw underfunded": [trust(JBB), trust(JCC)],
            "lpw under min": [trust(JBB), trust(JCC)], "lpw line full": [trust(JBB), trust(JCC)],
            "mbo buy no trust": [trust(JCC)], "mbo sell not auth": [trust(IAA), trust(JBB)], "mbo line full": [trust(JBB, 5), trust(JCC)],
            "mbo cross self": [trust(JBB), trust(JCC)], "mso buy not auth": [trust(IAA), trust(JBB)],
            "mso line full": [trust(JBB), trust(JCC, 5)], "passive": [trust(JBB), trust(JCC)],
            "unauthorized": [trust(IAA)], "maintain": [trust(IAA)],
            "pprs no trust": [trust(JBB)], "pprs not auth": [trust(IAA)], "pprs src not auth": [trust(IAA)],
            "pprs cross self": [trust(JDD), trust(JCC)], "ppss not auth": [trust(IAA)], "ppss src not auth": [trust(IAA)],
            "ppss line full": [trust(JBB)], "ppss cross self": [trust(JEE), trust(JCC)],
            "stlf invalid state": [], "merge immutable": [], "merge seq far": [],
            "rs low reserve": []}.items():
        if lines:
            R.tx(n + " trusts", K(n), lines)
    R.close("setup trust")

    # ---------------------------------------------------------------- setup 2: authorize, fund, offers
    auth = lambda who, flags=1: o("SET_TRUST_LINE_FLAGS", "setTrustLineFlagsOp",
                                  {"trustor": K(who).account(), "asset": IAA, "clearFlags": 0, "setFlags": flags})
    pay = lambda who, asset, amount, src=None: o("PAYMENT", "paymentOp", {"destination": K(who).muxed(), "asset": asset, "amount": amount}, src)
    R.tx("I authorizes and pays", I, [auth(n) for n in ("holder", "maker", "claimant", "sponsor", "cb underfunded", "maintain",
                                                         "pprs not auth", "ppss not auth", "mbo sell not auth")] +
         [pay("mbo sell not auth", IAA, 10_0000000)] +
         [pay(n, IAA, 1000_0000000) for n in ("holder", "maker", "claimant", "sponsor")] +
         [pay(n, IAA, 10_0000000) for n in ("pprs not auth", "ppss not auth")])
    R.tx("J pays", J, [pay(n, a, 1000_0000000) for n in ("holder", "maker", "sponsor") for a in (JBB, JCC)] +
         [pay(n, book[n], 100_0000000) for n in book] +
         [pay(n, JBB, 100_0000000) for n in ("ccb underfunded", "lpd not auth", "mso buy not auth", "ppss line full",
                                             "lpw line full", "lpw under min",
                                             "lpw underfunded", "lpd line full", "lpd bad price", "lpd underfunded",
                                             "mso line full", "passive", "lpw no trust", "lpd no trust")] +
         [pay(n, JCC, 100_0000000) for n in ("mbo cross self", "pprs cross self", "ppss cross self", "lpw line full",
                                             "lpw under min", "lpw underfunded", "lpd line full", "lpd bad price",
                                             "mbo line full", "passive", "lpw no trust", "lpd no trust", "mbo buy no trust")] +
         [pay("merge subentries", JBB, 1), pay("mbo line full", JBB, 5)])
    R.close("setup fund")

    # ---------------------------------------------------------------- setup 3: pools, offers, balances, sponsorship
    R.tx("I maintains and revokes", I, [o("SET_TRUST_LINE_FLAGS", "setTrustLineFlagsOp", {
        "trustor": K("maintain").account(), "asset": IAA, "clearFlags": 1, "setFlags": 2}),
        o("SET_TRUST_LINE_FLAGS", "setTrustLineFlagsOp", {
            "trustor": K("mbo sell not auth").account(), "asset": IAA, "clearFlags": 1, "setFlags": 0})])
    pl = lambda limit=BIG: o("CHANGE_TRUST", "changeTrustOp", {"line": pool_line, "limit": limit})
    dep = lambda a, b: o("LIQUIDITY_POOL_DEPOSIT", "liquidityPoolDepositOp", {"liquidityPoolID": pool, "maxAmountA": a,
                                                                              "maxAmountB": b, "minPrice": price(1, 2),
                                                                              "maxPrice": price(2, 1)})
    R.tx("holder pool", K("holder"), [pl(), dep(100_0000000, 100_0000000),
                                      o("CREATE_CLAIMABLE_BALANCE", "createClaimableBalanceOp", {
                                          "asset": JBB, "amount": 10_0000000, "claimants": [
                                              {"type": "CLAIMANT_TYPE_V0", "v0": {"destination": K("claim line full").account(),
                                                                                    "predicate": {"type": "CLAIM_PREDICATE_UNCONDITIONAL"}}}]}),
                                      o("CREATE_CLAIMABLE_BALANCE", "createClaimableBalanceOp", {
                                          "asset": IAA, "amount": 10_0000000, "claimants": [
                                              {"type": "CLAIMANT_TYPE_V0", "v0": {"destination": K("claim not auth").account(),
                                                                                    "predicate": {"type": "CLAIM_PREDICATE_UNCONDITIONAL"}}}]})])
    for n in ("lpw line full", "lpw under min", "lpw underfunded"):
        R.tx(n + " pool", K(n), [pl(), dep(10_0000000, 10_0000000)])
    R.tx("lpd line full pool", K("lpd line full"), [pl(1)])
    R.tx("ct cannot delete pool", K("ct cannot delete"), [pl()])
    R.tx("lpd bad price pool", K("lpd bad price"), [pl()])
    R.tx("lpd underfunded pool", K("lpd underfunded"), [pl()])
    R.tx("maker offers", K("maker"), [o("MANAGE_SELL_OFFER", "manageSellOfferOp", {"selling": JCC, "buying": JBB,
                                                                                   "amount": 100_0000000, "price": price(1),
                                                                                   "offerID": 0})])
    for n in ("mbo cross self", "pprs cross self", "ppss cross self"):
        R.tx(n + " offer", K(n), [o("MANAGE_SELL_OFFER", "manageSellOfferOp", {"selling": JCC, "buying": book[n],
                                                                                 "amount": 1_0000000, "price": price(1, 2),
                                                                                 "offerID": 0})])
    R.tx("merge sponsor", K("merge sponsor"), [o("BEGIN_SPONSORING_FUTURE_RESERVES", "beginSponsoringFutureReservesOp",
                                                 {"sponsoredID": K("rs only transferable").account()}),
                                               o("MANAGE_DATA", "manageDataOp", {"dataName": "x", "dataValue": "01"},
                                                 K("rs only transferable")),
                                               o("END_SPONSORING_FUTURE_RESERVES", None, None, K("rs only transferable"))],
         signers=[K("merge sponsor"), K("rs only transferable")])
    R.tx("signers", K("so too many signers"), [o("SET_OPTIONS", "setOptionsOp", no_opts(signer={
        "key": {"type": "SIGNER_KEY_TYPE_ED25519", "ed25519": hashlib.sha256(b"signer %d" % i).hexdigest()}, "weight": 1}))
        for i in range(20)], fee=2100)
    R.tx("J sells JBB for lots of XLM", J, [o("MANAGE_SELL_OFFER", "manageSellOfferOp", {
        "selling": JBB, "buying": XLM, "amount": BIG - 10_000_0000000 - 10_0000000, "price": price(1), "offerID": 0})])
    R.close("setup pools")
    v = lc.last_ledger(core, dec)
    bids = []
    for tp in v["v%d" % v["v"]]["txProcessing"]:
        for r in (tp["result"]["result"]["result"].get("results") or []):
            cb = (r.get("tr") or {}).get("createClaimableBalanceResult")
            if cb and cb.get("balanceID"):
                bids.append(cb["balanceID"])
    run["claimable_balances"] = bids
    jbb_bid, iaa_bid = bids[0], bids[1]

    # ---------------------------------------------------------------- the op-failures ledger
    F = lambda name, ops, code, **kw: R.tx(name, K(name), ops, expect={"op": [code]}, **kw)
    F("create exists", [o("CREATE_ACCOUNT", "createAccountOp", {"destination": K("holder").account(), "startingBalance": 1_0000000})],
      "CREATE_ACCOUNT_ALREADY_EXIST")
    merge = lambda dest: o("ACCOUNT_MERGE", "destination", dest.muxed())
    F("merge subentries", [merge(root)], "ACCOUNT_MERGE_HAS_SUB_ENTRIES")
    F("merge sponsor", [merge(root)], "ACCOUNT_MERGE_IS_SPONSOR")
    F("merge seq far", [merge(root)], "ACCOUNT_MERGE_SEQNUM_TOO_FAR")
    F("merge dest full", [merge(J)], "ACCOUNT_MERGE_DEST_FULL")
    allow = lambda who, a: o("ALLOW_TRUST", "allowTrustOp", {"trustor": K(who).account(), "asset": code4(a), "authorize": 0})
    def FO(name, op_, code, src):
        """A worker's transaction whose one operation runs as `src` (an issuer or a sponsor), so that
        the issuer, which can send one transaction per ledger, can fail in many of them."""
        op_ = dict(op_, sourceAccount=src.muxed())
        R.tx(name, K(name), [op_], signers=[K(name), src], expect={"op": [code]})
    FO("allow no line", allow("allow no line", "IAA"), "ALLOW_TRUST_NO_TRUST_LINE", I)
    FO("allow cant revoke", allow("holder", "JBB"), "ALLOW_TRUST_CANT_REVOKE", J)

    F("ct cannot delete", [trust(JBB, 0)], "CHANGE_TRUST_CANNOT_DELETE")
    F("ct line missing", [pl()], "CHANGE_TRUST_TRUST_LINE_MISSING")
    F("ct not auth maintain", [o("CHANGE_TRUST", "changeTrustOp", {"line": pool2_line, "limit": BIG})],
      "CHANGE_TRUST_NOT_AUTH_MAINTAIN_LIABILITIES")
    F("ct low reserve", [trust(JBB)], "CHANGE_TRUST_LOW_RESERVE")
    claim = lambda bid: o("CLAIM_CLAIMABLE_BALANCE", "claimClaimableBalanceOp", {"balanceID": bid})
    F("claim line full", [claim(jbb_bid)], "CLAIM_CLAIMABLE_BALANCE_LINE_FULL")
    F("claim not auth", [claim(iaa_bid)], "CLAIM_CLAIMABLE_BALANCE_NOT_AUTHORIZED")
    cbcb = lambda bid: o("CLAWBACK_CLAIMABLE_BALANCE", "clawbackClaimableBalanceOp", {"balanceID": bid})
    F("cbcb not issuer", [cbcb(iaa_bid)], "CLAWBACK_CLAIMABLE_BALANCE_NOT_ISSUER")
    F("cbcb missing", [cbcb({"type": "CLAIMABLE_BALANCE_ID_TYPE_V0", "v0": "ab" * 32})], "CLAWBACK_CLAIMABLE_BALANCE_DOES_NOT_EXIST")
    FO("cbcb not enabled", cbcb(jbb_bid), "CLAWBACK_CLAIMABLE_BALANCE_NOT_CLAWBACK_ENABLED", J)
    clawback = lambda asset, who, amount: o("CLAWBACK", "clawbackOp", {"asset": asset, "from": K(who).muxed(), "amount": amount})
    FO("cb underfunded", clawback(IAA, "cb underfunded", 1), "CLAWBACK_UNDERFUNDED", I)
    FO("cb no trust", clawback(IAA, "cb no trust", 1), "CLAWBACK_NO_TRUST", I)
    FO("cb not enabled", clawback(JBB, "holder", 1), "CLAWBACK_NOT_CLAWBACK_ENABLED", J)
    F("ccb underfunded", [o("CREATE_CLAIMABLE_BALANCE", "createClaimableBalanceOp", {"asset": JBB, "amount": 1000_0000000, "claimants": [
        {"type": "CLAIMANT_TYPE_V0", "v0": {"destination": K("holder").account(), "predicate": {"type": "CLAIM_PREDICATE_UNCONDITIONAL"}}}]})],
      "CREATE_CLAIMABLE_BALANCE_UNDERFUNDED")
    F("ccb not auth", [o("CREATE_CLAIMABLE_BALANCE", "createClaimableBalanceOp", {"asset": IAA, "amount": 1, "claimants": [
        {"type": "CLAIMANT_TYPE_V0", "v0": {"destination": K("holder").account(), "predicate": {"type": "CLAIM_PREDICATE_UNCONDITIONAL"}}}]})],
      "CREATE_CLAIMABLE_BALANCE_NOT_AUTHORIZED")
    F("lpd no trust", [dep(1_0000000, 1_0000000)], "LIQUIDITY_POOL_DEPOSIT_NO_TRUST")
    F("lpd underfunded", [dep(1000_0000000, 1000_0000000)], "LIQUIDITY_POOL_DEPOSIT_UNDERFUNDED")
    F("lpd bad price", [o("LIQUIDITY_POOL_DEPOSIT", "liquidityPoolDepositOp", {"liquidityPoolID": pool, "maxAmountA": 1_0000000,
                                                                                "maxAmountB": 1_0000000, "minPrice": price(3, 1),
                                                                                "maxPrice": price(4, 1)})],
      "LIQUIDITY_POOL_DEPOSIT_BAD_PRICE")
    F("lpd line full", [dep(10_0000000, 10_0000000)], "LIQUIDITY_POOL_DEPOSIT_LINE_FULL")
    wd = lambda amount, mina=1, minb=1: o("LIQUIDITY_POOL_WITHDRAW", "liquidityPoolWithdrawOp", {
        "liquidityPoolID": pool, "amount": amount, "minAmountA": mina, "minAmountB": minb})
    F("lpw no trust", [wd(1)], "LIQUIDITY_POOL_WITHDRAW_NO_TRUST")
    F("lpw underfunded", [wd(1000_0000000)], "LIQUIDITY_POOL_WITHDRAW_UNDERFUNDED")
    F("lpw under min", [wd(1_0000000, 100_0000000, 100_0000000)], "LIQUIDITY_POOL_WITHDRAW_UNDER_MINIMUM")
    sell = lambda s, b, amount, p=price(1): o("MANAGE_SELL_OFFER", "manageSellOfferOp", {"selling": s, "buying": b, "amount": amount, "price": p, "offerID": 0})
    buy = lambda s, b, amount, p=price(1): o("MANAGE_BUY_OFFER", "manageBuyOfferOp", {"selling": s, "buying": b, "buyAmount": amount, "price": p, "offerID": 0})
    F("mbo buy no trust", [buy(JCC, JBB, 1)], "MANAGE_BUY_OFFER_BUY_NO_TRUST")
    F("mbo sell not auth", [buy(IAA, JBB, 1)], "MANAGE_BUY_OFFER_SELL_NOT_AUTHORIZED")
    F("mbo line full", [buy(JCC, JBB, 1)], "MANAGE_BUY_OFFER_LINE_FULL")
    F("mbo cross self", [buy(JBB, JCC, 1_0000000)], "MANAGE_BUY_OFFER_CROSS_SELF")  # its own offer is the best on the book
    F("mso buy not auth", [sell(JBB, IAA, 1)], "MANAGE_SELL_OFFER_BUY_NOT_AUTHORIZED")
    F("mso line full", [sell(JBB, JCC, 10_0000000)], "MANAGE_SELL_OFFER_LINE_FULL")
    R.tx("passive", K("passive"), [o("CREATE_PASSIVE_SELL_OFFER", "createPassiveSellOfferOp", {
        "selling": JBB, "buying": JCC, "amount": 1_0000000, "price": price(5)})], expect={"op": ["MANAGE_SELL_OFFER_SUCCESS"]})
    F("md low reserve", [o("MANAGE_DATA", "manageDataOp", {"dataName": "x", "dataValue": "01"})], "MANAGE_DATA_LOW_RESERVE")
    pprs = lambda dest, s, d, amt=1: o("PATH_PAYMENT_STRICT_RECEIVE", "pathPaymentStrictReceiveOp", {
        "sendAsset": s, "sendMax": BIG, "destination": dest.muxed(), "destAsset": d, "destAmount": amt, "path": []})
    ppss = lambda dest, s, d, amt=1: o("PATH_PAYMENT_STRICT_SEND", "pathPaymentStrictSendOp", {
        "sendAsset": s, "sendAmount": amt, "destination": dest.muxed(), "destAsset": d, "destMin": 1, "path": []})
    nobody = lc.Keys("failures nobody")
    F("pprs no dest", [pprs(nobody, XLM, XLM)], "PATH_PAYMENT_STRICT_RECEIVE_NO_DESTINATION")
    F("pprs no trust", [pprs(K("allow no line"), XLM, JBB)],
      "PATH_PAYMENT_STRICT_RECEIVE_NO_TRUST")
    F("pprs not auth", [pprs(K("unauthorized"), IAA, IAA)], "PATH_PAYMENT_STRICT_RECEIVE_NOT_AUTHORIZED")
    F("pprs src no trust", [pprs(K("holder"), IAA, IAA)], "PATH_PAYMENT_STRICT_RECEIVE_SRC_NO_TRUST")
    F("pprs src not auth", [pprs(K("holder"), IAA, IAA)], "PATH_PAYMENT_STRICT_RECEIVE_SRC_NOT_AUTHORIZED")
    F("pprs cross self", [pprs(K("holder"), JDD, JCC, 1_0000000)], "PATH_PAYMENT_STRICT_RECEIVE_OFFER_CROSS_SELF")
    F("ppss no dest", [ppss(nobody, XLM, XLM)], "PATH_PAYMENT_STRICT_SEND_NO_DESTINATION")
    F("ppss not auth", [ppss(K("unauthorized"), IAA, IAA)], "PATH_PAYMENT_STRICT_SEND_NOT_AUTHORIZED")
    F("ppss src not auth", [ppss(K("holder"), IAA, IAA)], "PATH_PAYMENT_STRICT_SEND_SRC_NOT_AUTHORIZED")
    F("ppss line full", [ppss(K("claim line full"), JBB, JBB, 10)], "PATH_PAYMENT_STRICT_SEND_LINE_FULL")
    F("ppss cross self", [ppss(K("holder"), JEE, JCC, 1_0000000)], "PATH_PAYMENT_STRICT_SEND_OFFER_CROSS_SELF")
    revoke_data = lambda who: o("REVOKE_SPONSORSHIP", "revokeSponsorshipOp", {"type": "REVOKE_SPONSORSHIP_LEDGER_ENTRY", "ledgerKey": {
        "type": "DATA", "data": {"accountID": K(who).account(), "dataName": "x"}}})
    F("rs missing", [revoke_data("rs missing")], "REVOKE_SPONSORSHIP_DOES_NOT_EXIST")
    FO("rs only transferable", o("REVOKE_SPONSORSHIP", "revokeSponsorshipOp", {"type": "REVOKE_SPONSORSHIP_LEDGER_ENTRY", "ledgerKey": {
        "type": "CLAIMABLE_BALANCE", "claimableBalance": {"balanceID": jbb_bid}}}), "REVOKE_SPONSORSHIP_ONLY_TRANSFERABLE", K("holder"))
    F("so revocable required", [o("SET_OPTIONS", "setOptionsOp", no_opts(setFlags=8))], "SET_OPTIONS_AUTH_REVOCABLE_REQUIRED")
    F("so cant change", [o("SET_OPTIONS", "setOptionsOp", no_opts(clearFlags=4))], "SET_OPTIONS_CANT_CHANGE")
    F("so bad inflation", [o("SET_OPTIONS", "setOptionsOp", no_opts(inflationDest=nobody.account()))], "SET_OPTIONS_INVALID_INFLATION")
    F("so low reserve", [o("SET_OPTIONS", "setOptionsOp", no_opts(signer={"key": {"type": "SIGNER_KEY_TYPE_ED25519", "ed25519": "11" * 32}, "weight": 1}))],
      "SET_OPTIONS_LOW_RESERVE")
    F("so too many signers", [o("SET_OPTIONS", "setOptionsOp", no_opts(signer={"key": {"type": "SIGNER_KEY_TYPE_ED25519", "ed25519": "22" * 32}, "weight": 1}))],
      "SET_OPTIONS_TOO_MANY_SIGNERS")
    stlf = lambda who, clear, set_: o("SET_TRUST_LINE_FLAGS", "setTrustLineFlagsOp", {"trustor": K(who).account(), "asset": JBB, "clearFlags": clear, "setFlags": set_})
    FO("stlf no line", stlf("stlf no line", 0, 1), "SET_TRUST_LINE_FLAGS_NO_TRUST_LINE", J)
    FO("stlf cant revoke", stlf("holder", 1, 0), "SET_TRUST_LINE_FLAGS_CANT_REVOKE", J)
    FO("stlf invalid state", o("SET_TRUST_LINE_FLAGS", "setTrustLineFlagsOp", {"trustor": K("maintain").account(), "asset": IAA,
                                                                               "clearFlags": 0, "setFlags": 1}),
       "SET_TRUST_LINE_FLAGS_INVALID_STATE", I)
    R.tx("bad sponsorship", K("bad sponsorship"), [o("BEGIN_SPONSORING_FUTURE_RESERVES", "beginSponsoringFutureReservesOp",
                                                     {"sponsoredID": K("memo return").account()})],
         expect={"tx": "txBAD_SPONSORSHIP"})
    R.tx("memo return", K("memo return"), [o("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": 0})],
         memo={"type": "MEMO_RETURN", "retHash": "cd" * 32}, expect={"op": ["BUMP_SEQUENCE_SUCCESS"]})
    R.close("op failures", record="op_failures")

    # ---------------------------------------------------------------- the tx-failures ledger
    # Each victim transaction is valid when it is queued; an attacker transaction of the same ledger,
    # whose operation runs as the victim's account (signed by both), changes the victim's sequence
    # number, signers or balance first. stellar-core orders a ledger's transactions by hash, so each
    # case is sent three times with different accounts; run.json records which came out as built.
    kinds = ["bad seq", "bad auth", "insufficient balance", "min seq gap", "bad auth extra", "op bad auth"]
    REPLICAS = 4
    pairs = [(k, wrap, i) for k in kinds for wrap in ("plain", "bumped") for i in range(REPLICAS)]
    extra = []
    for k, wrap, i in pairs:
        tag = "%s %s %d" % (k, wrap, i)
        for role in ("victim", "attacker") + (("third",) if k == "op bad auth" else ()) + (("feepayer",) if wrap == "bumped" else ()):
            extra.append(role + " " + tag)
    for i in range(2):
        extra += ["victim bad sponsorship bumped %d" % i, "feepayer bad sponsorship bumped %d" % i]
    for n in extra:
        K(n)
    # a standalone core takes about 100 operations per ledger: one creating transaction per ledger
    for x in range(0, len(extra), 90):
        chunk = extra[x:x + 90]
        R.tx("create tx-failure accounts", root, [o("CREATE_ACCOUNT", "createAccountOp", {"destination": K(n).account(),
                                                                                          "startingBalance": 100_0000000})
                                                  for n in chunk], fee=100 * len(chunk))
        born2 = R.close("tx-failure accounts") << 32
        for n in chunk:
            R.seq[K(n).pub] = born2
    S_key = lambda tag: R.lc.Keys("failures extra signer " + tag)
    setup = []
    for k, wrap, i in pairs:
        tag = "%s %s %d" % (k, wrap, i)
        if k == "bad auth extra":
            # master weight 1 and thresholds 2: the victim needs its extra signer's signature too
            setup.append((K("victim " + tag), [o("SET_OPTIONS", "setOptionsOp", no_opts(
                signer={"key": {"type": "SIGNER_KEY_TYPE_ED25519", "ed25519": S_key(tag).pub}, "weight": 1},
                lowThreshold=2, medThreshold=2, highThreshold=2))]))
    for src, ops in setup:
        R.tx("setup extra signer", src, ops)
    if setup:
        R.close("tx-failure setup")
    nop = lambda: o("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": 0})
    for k, wrap, i in sorted(pairs, key=lambda p_: p_[1] == "bumped"):
        if wrap == "bumped" and not getattr(R, "_plain_closed", False):
            R.close("tx failures plain", record="tx_failures_plain")
            R._plain_closed = True
        tag = "%s %s %d" % (k, wrap, i)
        V, A = K("victim " + tag), K("attacker " + tag)
        bump = K("feepayer " + tag) if wrap == "bumped" else None
        vseq = R.seq[V.pub]
        expect = {"tx": {"bad seq": "txBAD_SEQ", "bad auth": "txBAD_AUTH", "insufficient balance": "txINSUFFICIENT_BALANCE",
                         "min seq gap": "txBAD_MIN_SEQ_AGE_OR_GAP", "bad auth extra": "txBAD_AUTH_EXTRA", "op bad auth": "txFAILED"}[k]}
        if k == "op bad auth":
            expect["op"] = ["opBAD_AUTH"]
        on_victim = lambda op_: dict(op_, sourceAccount=V.muxed())
        if k == "bad seq":
            attack = [on_victim(o("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": vseq + 5}))]
        elif k == "bad auth":
            attack = [on_victim(o("SET_OPTIONS", "setOptionsOp", no_opts(masterWeight=0)))]
        elif k == "insufficient balance":
            # leave the victim 50 stroops above its reserve, less than its fee
            attack = [on_victim(o("PAYMENT", "paymentOp", {"destination": A.muxed(), "asset": XLM, "amount": 80_0000000 - 200 - 50}))]
        elif k == "min seq gap":
            attack = [on_victim(o("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": vseq + 1}))]
        elif k == "bad auth extra":
            attack = [on_victim(o("SET_OPTIONS", "setOptionsOp", no_opts(masterWeight=2)))]
        else:
            W = K("third " + tag)
            attack = [dict(o("SET_OPTIONS", "setOptionsOp", no_opts(masterWeight=0)), sourceAccount=W.muxed())]
        R.tx("attacker " + tag, A, attack, signers=[A, W] if k == "op bad auth" else
             [A, V, S_key(tag)] if k == "bad auth extra" else [A, V])
        signers = [V, S_key(tag)] if k == "bad auth extra" else [V]
        ops = [nop()]
        cond = None
        if k == "min seq gap":
            # the victim's sequence number skips the one the attacker sets, which minSeqNum allows; a
            # minimum ledger gap of 1 then fails because its sequence number changed in this ledger
            cond = {"type": "PRECOND_V2", "v2": {"timeBounds": None, "ledgerBounds": None, "minSeqNum": vseq,
                                                 "minSeqAge": 0, "minSeqLedgerGap": 1, "extraSigners": []}}
            R.seq[V.pub] = vseq + 1
        if k == "op bad auth":
            ops = [dict(o("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": 0}), sourceAccount=W.muxed())]
            signers = [V, W]
        R.tx("victim " + tag, V, ops, signers=signers, expect=expect, cond=cond, bump=bump)
    for i in range(2):
        V = K("victim bad sponsorship bumped %d" % i)
        R.tx("victim bad sponsorship bumped %d" % i, V, [o("BEGIN_SPONSORING_FUTURE_RESERVES", "beginSponsoringFutureReservesOp",
                                                           {"sponsoredID": K("holder").account()})],
             expect={"tx": "txBAD_SPONSORSHIP"}, bump=K("feepayer bad sponsorship bumped %d" % i))
    R.close("tx failures bumped", record="tx_failures_bumped")

    # ---------------------------------------------------------------- the upgrades ledger
    core.http("upgrades?mode=set&upgradetime=1970-01-01T00:00:00Z&basefee=200&basereserve=60000000&maxtxsetsize=500&flags=1")
    run["upgrades_armed"] = core.http("upgrades?mode=get")
    R.close("upgrades", record="upgrades")
    run["failures_summary"] = {"cases": len(run["cases"]), "as_built": sum(1 for c in run["cases"] if c["expect"] and c["ok"]),
                               "not_as_built": [c["name"] for c in run["cases"] if c["expect"] and not c["ok"]]}
