"""Scenario reserve-pool-p30 for tools/localcore.py: failures at apply that need several ledgers of state.

Each result code here is set while stellar-core applies an operation, against ledger state that
earlier ledgers build (corpus/cell-classes.json, class local_core). The setup ledgers create the
accounts, trustlines, pools and sponsorships; the last ledger holds one failing transaction per
case, each from its own source account:

  ACCOUNT_MERGE_IMMUTABLE_SET      an account with AUTH_IMMUTABLE set merges itself
  SET_TRUST_LINE_FLAGS_LOW_RESERVE an issuer revokes a trustline whose holder has a pool-share
                                   trustline in that asset, inside a sponsorship sandwich whose
                                   sponsor is at its minimum balance: the claimable balances the
                                   redemption creates need a reserve the sponsor does not have
                                   (TransactionUtils.cpp, removeOffersAndPoolShareTrustLines)
  ALLOW_TRUST_LOW_RESERVE          the same, with AllowTrust
  REVOKE_SPONSORSHIP_LOW_RESERVE   a sponsor revokes its sponsorship of a data entry whose owner
                                   is at its minimum balance and cannot take the reserve over
  LIQUIDITY_POOL_DEPOSIT_NOT_AUTHORIZED
                                   a deposit whose asset trustline is authorized only to
                                   maintain liabilities
  LIQUIDITY_POOL_DEPOSIT_POOL_FULL a deposit that would take the pool's reserves past 2^63-1
  LIQUIDITY_POOL_WITHDRAW_LINE_FULL
                                   a withdrawal into a trustline whose limit equals its balance
  txBAD_AUTH_EXTRA                 a transaction signed by its source's master key and its extra
                                   signer, valid when queued; an earlier transaction of the same
                                   ledger removes that signer and raises the master weight, so at
                                   apply one signature matches no signer (TransactionFrame.cpp,
                                   processSignatures). stellar-core orders a ledger's transactions
                                   by hash, so the case is sent BAE_REPLICAS times with different
                                   accounts; a replica whose victim applies first succeeds instead.

Recorded ledger (run.json `ledger_<name>`): reserve_pool_failures. run.json lists, per
transaction, the code it was built to produce and the code it got.
"""
import hashlib

import localcore_failures as lf

BIG = 2 ** 63 - 1
BAE_REPLICAS = 6
HALF = 5 * 10 ** 18  # two deposits of this much overflow a pool's reserve (2^63-1 is about 9.2 * 10^18)
XLM = lf.XLM


def reserve_pool(lc, core, enc, dec, root, step, run, protocol=30):
    R = lf.Run(lc, core, enc, dec, root, step, run)
    core.upgrade(protocol)
    K = R.key
    o = R.op
    I, Q = K("revocable issuer"), K("pool issuer")
    RVA, QA, QB = lf.a4("RVA", I), lf.a4("QA", Q), lf.a4("QB", Q)

    def params(a, b):
        return {"type": "LIQUIDITY_POOL_CONSTANT_PRODUCT", "constantProduct": {"assetA": a, "assetB": b, "fee": 30}}

    rva_pool, q_pool = params(XLM, RVA), params(QA, QB)  # the native asset sorts first
    pool_id = lambda p: hashlib.sha256(enc.encode("LiquidityPoolParameters", p)).hexdigest()
    run["pools"] = {"XLM/RVA": pool_id(rva_pool), "QA/QB": pool_id(q_pool)}
    pool_line = lambda p: o("CHANGE_TRUST", "changeTrustOp", {"line": {"type": "ASSET_TYPE_POOL_SHARE", "liquidityPool": p},
                                                              "limit": BIG})
    trust = lambda asset, limit=BIG: o("CHANGE_TRUST", "changeTrustOp", {"line": asset, "limit": limit})
    deposit = lambda p, a, b: o("LIQUIDITY_POOL_DEPOSIT", "liquidityPoolDepositOp", {
        "liquidityPoolID": pool_id(p), "maxAmountA": a, "maxAmountB": b,
        "minPrice": lf.price(1, 2), "maxPrice": lf.price(2, 1)})

    # ---------------------------------------------------------------- accounts
    rich = ["revocable issuer", "pool issuer", "stlf trustor", "allow trustor", "lpd not auth", "first depositor",
            "lpd pool full", "lpw line full", "merge immutable", "data sponsor"] + \
           ["bae %s %d" % (role, i) for i in range(BAE_REPLICAS) for role in ("victim", "attacker")]
    # Exactly the minimum balance (two base reserves): no spare reserve. These accounts never pay a fee.
    poor = ["stlf sandwich sponsor", "allow sandwich sponsor", "data owner"]
    for n in rich + poor:
        K(n)
    R.tx("create accounts", root,
         [o("CREATE_ACCOUNT", "createAccountOp", {"destination": K(n).account(), "startingBalance": 10_000_0000000})
          for n in rich] +
         [o("CREATE_ACCOUNT", "createAccountOp", {"destination": K(n).account(), "startingBalance": 20_0000000})
          for n in poor], fee=100 * (len(rich) + len(poor)))
    born = R.close("accounts") << 32
    for n in rich + poor:
        R.seq[K(n).pub] = born

    # ---------------------------------------------------------------- setup: flags and trustlines
    R.tx("issuer is AUTH_REVOCABLE", I, [o("SET_OPTIONS", "setOptionsOp", lf.no_opts(setFlags=2))])
    R.tx("AUTH_IMMUTABLE", K("merge immutable"), [o("SET_OPTIONS", "setOptionsOp", lf.no_opts(setFlags=4))])
    for n in ("stlf trustor", "allow trustor", "lpd not auth"):
        R.tx(n + " trusts RVA", K(n), [trust(RVA)])
    for n in ("first depositor", "lpd pool full", "lpw line full"):
        R.tx(n + " trusts QA, QB", K(n), [trust(QA), trust(QB)])
    extra_signer = lambda i: lc.Keys("reserve bae signer %d" % i)
    for i in range(BAE_REPLICAS):
        # master weight 1, thresholds 2: the victim needs its extra signer's signature too
        R.tx("bae victim %d adds a signer" % i, K("bae victim %d" % i), [o("SET_OPTIONS", "setOptionsOp", lf.no_opts(
            signer={"key": {"type": "SIGNER_KEY_TYPE_ED25519", "ed25519": extra_signer(i).pub}, "weight": 1},
            lowThreshold=2, medThreshold=2, highThreshold=2))])
    # the data sponsor pays the reserve of the data owner's one entry
    R.tx("sponsored data entry", K("data sponsor"), [
        o("BEGIN_SPONSORING_FUTURE_RESERVES", "beginSponsoringFutureReservesOp", {"sponsoredID": K("data owner").account()}),
        o("MANAGE_DATA", "manageDataOp", {"dataName": "sponsored", "dataValue": "01"}, K("data owner")),
        o("END_SPONSORING_FUTURE_RESERVES", None, None, K("data owner"))],
        signers=[K("data sponsor"), K("data owner")])
    R.close("setup trust")

    # ---------------------------------------------------------------- setup: fund
    pay = lambda who, asset, amount: o("PAYMENT", "paymentOp", {"destination": K(who).muxed(), "asset": asset, "amount": amount})
    R.tx("RVA issuer pays", I, [pay(n, RVA, 100_0000000) for n in ("stlf trustor", "allow trustor", "lpd not auth")])
    R.tx("QA/QB issuer pays", Q, [pay(n, a, HALF) for n in ("first depositor", "lpd pool full") for a in (QA, QB)] +
         [pay("lpw line full", a, 100_0000000) for a in (QA, QB)])
    R.close("setup fund")

    # ---------------------------------------------------------------- setup: pools
    for n in ("stlf trustor", "allow trustor"):
        R.tx(n + " deposits", K(n), [pool_line(rva_pool), deposit(rva_pool, 10_0000000, 10_0000000)])
    R.tx("lpd not auth pool line", K("lpd not auth"), [pool_line(rva_pool)])
    R.tx("first depositor deposits half of 2^64", K("first depositor"), [pool_line(q_pool), deposit(q_pool, HALF, HALF)])
    R.tx("lpd pool full pool line", K("lpd pool full"), [pool_line(q_pool)])
    # after the deposit the QA balance is 90; a limit of 90 leaves no room to receive any
    R.tx("lpw line full deposits, then fills its QA line", K("lpw line full"),
         [pool_line(q_pool), deposit(q_pool, 10_0000000, 10_0000000), trust(QA, 90_0000000)])
    R.close("setup pools")

    # ---------------------------------------------------------------- setup: maintain liabilities only
    R.tx("RVA issuer: lpd not auth to maintain liabilities", I, [o("SET_TRUST_LINE_FLAGS", "setTrustLineFlagsOp", {
        "trustor": K("lpd not auth").account(), "asset": RVA, "clearFlags": 1, "setFlags": 2})])
    R.close("setup maintain")

    # ---------------------------------------------------------------- the failures ledger
    def F(name, ops, code, signers=None):
        R.tx(name, K(name), ops, signers=signers or [K(name)], expect={"op": code})

    F("merge immutable", [o("ACCOUNT_MERGE", "destination", root.muxed())], ["ACCOUNT_MERGE_IMMUTABLE_SET"])

    def sandwich(trustor, sponsor, revoke):
        """The trustor's transaction: the sponsor sponsors the trustor's future reserves while the
        issuer revokes the trustor's RVA line, which redeems its pool shares."""
        return [o("BEGIN_SPONSORING_FUTURE_RESERVES", "beginSponsoringFutureReservesOp",
                  {"sponsoredID": K(trustor).account()}, K(sponsor)),
                revoke,
                o("END_SPONSORING_FUTURE_RESERVES", None, None, K(trustor))]
    F("stlf trustor", sandwich("stlf trustor", "stlf sandwich sponsor", o("SET_TRUST_LINE_FLAGS", "setTrustLineFlagsOp", {
        "trustor": K("stlf trustor").account(), "asset": RVA, "clearFlags": 1, "setFlags": 0}, I)),
      [None, "SET_TRUST_LINE_FLAGS_LOW_RESERVE"], signers=[K("stlf trustor"), K("stlf sandwich sponsor"), I])
    F("allow trustor", sandwich("allow trustor", "allow sandwich sponsor", o("ALLOW_TRUST", "allowTrustOp", {
        "trustor": K("allow trustor").account(), "asset": lf.code4("RVA"), "authorize": 0}, I)),
      [None, "ALLOW_TRUST_LOW_RESERVE"], signers=[K("allow trustor"), K("allow sandwich sponsor"), I])
    F("data sponsor", [o("REVOKE_SPONSORSHIP", "revokeSponsorshipOp", {"type": "REVOKE_SPONSORSHIP_LEDGER_ENTRY", "ledgerKey": {
        "type": "DATA", "data": {"accountID": K("data owner").account(), "dataName": "sponsored"}}})],
      ["REVOKE_SPONSORSHIP_LOW_RESERVE"])
    F("lpd not auth", [deposit(rva_pool, 1_0000000, 1_0000000)], ["LIQUIDITY_POOL_DEPOSIT_NOT_AUTHORIZED"])
    F("lpd pool full", [deposit(q_pool, HALF, HALF)], ["LIQUIDITY_POOL_DEPOSIT_POOL_FULL"])
    F("lpw line full", [o("LIQUIDITY_POOL_WITHDRAW", "liquidityPoolWithdrawOp", {
        "liquidityPoolID": pool_id(q_pool), "amount": 1_0000000, "minAmountA": 1, "minAmountB": 1})],
      ["LIQUIDITY_POOL_WITHDRAW_LINE_FULL"])
    for i in range(BAE_REPLICAS):
        V, A, S = K("bae victim %d" % i), K("bae attacker %d" % i), extra_signer(i)
        R.tx("bae attacker %d" % i, A, [o("SET_OPTIONS", "setOptionsOp", lf.no_opts(
            masterWeight=2, signer={"key": {"type": "SIGNER_KEY_TYPE_ED25519", "ed25519": S.pub}, "weight": 0}), V)],
            signers=[A, V, S])
        R.tx("bae victim %d" % i, V, [o("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": 0})], signers=[V, S],
             expect={"tx": "txBAD_AUTH_EXTRA"})
    R.close("reserve and pool failures", record="reserve_pool_failures")
    run["failures_summary"] = {"cases": len(run["cases"]), "as_built": sum(1 for c in run["cases"] if c["expect"] and c["ok"]),
                               "not_as_built": [c["name"] for c in run["cases"] if c["expect"] and not c["ok"]]}


MAKERS, OFFERS_PER_MAKER = 11, 100  # 1100 resting offers; stellar-core crosses at most 1000 in one operation


def work_limit(lc, core, enc, dec, root, step, run, protocol=30):
    """Scenario work-limit-p30: an offer that would cross more resting offers than stellar-core allows in
    one operation (MAX_OFFERS_TO_CROSS, 1000) fails with opEXCEEDED_WORK_LIMIT
    (ManageOfferOpFrameBase::doApply). The setup raises the ledger's maximum transaction set size to
    2000 operations, so that 11 makers can place 100 offers each in one ledger.

    Recorded ledger: work_limit (the failing offer). The ledger with the 1100 offers is not recorded
    (about 1 MB); run.json names it as offers_ledger."""
    R = lf.Run(lc, core, enc, dec, root, step, run)
    core.upgrade(protocol)
    K = R.key
    o = R.op
    X = K("work limit issuer")
    WLX = lf.a4("WLX", X)
    names = ["work limit issuer", "work limit taker"] + ["work limit maker %d" % i for i in range(MAKERS)]
    R.tx("create accounts", root, [o("CREATE_ACCOUNT", "createAccountOp", {"destination": K(n).account(),
                                                                          "startingBalance": 10_000_0000000})
                                   for n in names], fee=100 * len(names))
    core.http("upgrades?mode=set&upgradetime=1970-01-01T00:00:00Z&maxtxsetsize=2000")
    run["upgrades_armed"] = core.http("upgrades?mode=get")
    born = R.close("accounts and set size") << 32
    for n in names:
        R.seq[K(n).pub] = born
    for n in names[1:]:
        R.tx(n + " trusts WLX", K(n), [o("CHANGE_TRUST", "changeTrustOp", {"line": WLX, "limit": BIG})])
    R.close("trust")
    R.tx("issuer pays the makers", X, [o("PAYMENT", "paymentOp", {"destination": K(n).muxed(), "asset": WLX,
                                                                  "amount": 1000_0000000}) for n in names[2:]])
    R.close("fund")
    for n in names[2:]:
        R.tx(n + " offers", K(n), [o("MANAGE_SELL_OFFER", "manageSellOfferOp", {
            "selling": WLX, "buying": XLM, "amount": 1_0000000, "price": lf.price(1), "offerID": 0})
            for _ in range(OFFERS_PER_MAKER)], fee=100 * OFFERS_PER_MAKER + 100)
    run["offers_ledger"] = R.close("offers")
    R.tx("work limit taker", K("work limit taker"), [o("MANAGE_BUY_OFFER", "manageBuyOfferOp", {
        "selling": XLM, "buying": WLX, "buyAmount": MAKERS * OFFERS_PER_MAKER * 1_0000000, "price": lf.price(1),
        "offerID": 0})], expect={"op": ["opEXCEEDED_WORK_LIMIT"]})
    R.close("work limit", record="work_limit")
    run["failures_summary"] = {"cases": len(run["cases"]), "as_built": sum(1 for c in run["cases"] if c["expect"] and c["ok"]),
                               "not_as_built": [c["name"] for c in run["cases"] if c["expect"] and not c["ok"]]}
