"""stellar-etl's vocabulary for the changes tools/oracle.py derives from a ledger.

stellar-etl exports Horizon's effect model (`export_effects`, effect types from its
internal/transform/effects.go) and the CAP-67 token transfer events (`export_token_transfer`).
The adapter turns each effect into a row with category EFFECT and the effect type as reason, and
each token transfer event into signed balance movements. This file says which effect each oracle
change should produce. Whether one is expected always comes from the ledger.

Effects belong to operations: a change the oracle sees outside any operation (fee processing,
txChangesBefore/After) has no effect by design and is not checked here; its balance part is
checked through the fee events.

Offers: Horizon's model has no effect for an offer being placed, changed or cancelled by its owner
(the offer_* types exist but Horizon never emits them; stellar-etl emits them only alongside trades,
see stellar-etl#456). So offers are checked through trades: a resting offer crossed in an
operation must give its seller a `trade` effect naming that offer.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "tools"))
import strkey  # noqa: E402
from encode import Encoder  # noqa: E402

REPORT_INTRO = [
    "Each cell is the result for one entry at one commit. stellar-etl reads ledgers only from a data lake",
    "on Google Cloud Storage, so the one input is `datalake`: the Galexie layout served through the GCS JSON",
    "and XML APIs, with the exporter's own GCS client pointed at the feeder by `STORAGE_EMULATOR_HOST`. Every",
    "cell runs the commit's own `export_transactions`, `export_operations`, `export_effects`,",
    "`export_token_transfer`, `export_contract_events` and `export_trades` for the one ledger and reads the exported JSON",
    "back. stellar-etl reads only",
    "pubnet, testnet and futurenet, so entries from stellar-core's test data are `n/a`.",
]

REPORT_INTRO_SEQUENCE = [
    "Each sequence is a run of consecutive corpus ledgers (`corpus/sequences.json`) served as one window.",
    "stellar-etl reads them from the data lake through the GCS JSON and XML APIs, with the exporter's own",
    "GCS client pointed at the feeder by `STORAGE_EMULATOR_HOST`. Every export runs once over the whole",
    "range: `export_transactions`, `export_operations`, `export_effects`, `export_token_transfer`,",
    "`export_contract_events`, `export_trades`, and `export_ledger_entry_changes` for accounts, trustlines,",
    "offers, liquidity pools and claimable balances, which writes nothing for a range of one ledger and",
    "so is checked on sequences only. Each member ledger is judged like a single-ledger replay; the",
    "sequence's own end-state checks compare the exported entry changes with each ledger's net change.",
]

EVIDENCE_FILES = ("job.json, observation.json, result.json, feeder-requests.jsonl, and exports/: each command's "
                  "JSON lines (gzipped), log and exit code")

# (oracle what, how) -> effect type. One effect per account and operation covers every change of
# that kind (thresholds, flags, home domain); signers, data entries and trustlines get one each.
EFFECT = {
    ("account", "created"): "account_created",
    ("account", "removed"): "account_removed",
    ("signer", "added"): "signer_created",
    ("signer", "removed"): "signer_removed",
    ("signer", "reweighted"): "signer_updated",
    ("threshold", "changed"): "account_thresholds_updated",
    ("flags", "set"): "account_flags_updated",
    ("flags", "cleared"): "account_flags_updated",
    ("home", "set"): "account_home_domain_updated",
    ("home", "cleared"): "account_home_domain_updated",
    ("home", "changed"): "account_home_domain_updated",
    ("data", "added"): "data_created",
    ("data", "removed"): "data_removed",
    ("data", "changed"): "data_updated",
    ("trustline", "added"): "trustline_created",
    ("trustline", "removed"): "trustline_removed",
    ("trustline", "limit changed"): "trustline_updated",
    ("trustauth", "set"): "trustline_flags_updated",
    ("trustauth", "cleared"): "trustline_flags_updated",
}
POOL_CHANGE = {"LIQUIDITY_POOL_DEPOSIT": "liquidity_pool_deposited", "LIQUIDITY_POOL_WITHDRAW": "liquidity_pool_withdrew",
               "ALLOW_TRUST": "liquidity_pool_revoked", "SET_TRUST_LINE_FLAGS": "liquidity_pool_revoked",
               "PATH_PAYMENT_STRICT_RECEIVE": "liquidity_pool_trade", "PATH_PAYMENT_STRICT_SEND": "liquidity_pool_trade",
               "MANAGE_SELL_OFFER": "liquidity_pool_trade", "MANAGE_BUY_OFFER": "liquidity_pool_trade",
               "CREATE_PASSIVE_SELL_OFFER": "liquidity_pool_trade"}
CLAIMABLE_REMOVED = {"CLAIM_CLAIMABLE_BALANCE": "claimable_balance_claimed",
                     "CLAWBACK_CLAIMABLE_BALANCE": "claimable_balance_clawed_back"}
# Horizon's model has sponsorship effects for these entry kinds; offers have none.
SPONSORED = {"account", "trustline", "data", "claimable_balance"}
PER_OPERATION = {"account_thresholds_updated", "account_flags_updated", "account_home_domain_updated",
                 "trustline_flags_updated"}

_ENC = {}


def _encoder():
    if "e" not in _ENC:
        schema = json.load(open(os.path.join(HERE, "..", "..", "..", "..", "schema", "schema.json")))
        _ENC["e"] = Encoder(schema)
    return _ENC["e"]


def asset_contract(asset, passphrase):
    """The Stellar Asset Contract ID of an asset (CAP-46), as a C... address."""
    preimage = {"type": "ENVELOPE_TYPE_CONTRACT_ID", "contractID": {
        "networkID": hashlib.sha256(passphrase.encode()).hexdigest(),
        "contractIDPreimage": {"type": "CONTRACT_ID_PREIMAGE_FROM_ASSET", "fromAsset": asset}}}
    return strkey.contract(hashlib.sha256(_encoder().encode("HashIDPreimage", preimage)).hexdigest())


def asset_text(asset):
    """An oracle asset dict -> CODE:ISSUER, the form the adapter gives effect rows."""
    if asset["type"] == "ASSET_TYPE_NATIVE":
        return "native"
    body = asset.get("alphaNum4") or asset.get("alphaNum12")
    code = bytes.fromhex(body["assetCode"]).rstrip(b"\0").decode()
    issuer = body["issuer"]
    if isinstance(issuer, dict):
        issuer = strkey.account(issuer.get("ed25519") or issuer["value"])
    return "%s:%s" % (code, issuer)


def manifest_expectations(exps):
    """The manifest's hand-written expectations name wallet-backend rows. Only a stored transaction
    is meaningful for stellar-etl; the oracle covers the rest in stellar-etl's own vocabulary."""
    return [e for e in exps if e.get("expect") == "transaction"]


def effects_for(c):
    """The effect rows (without context) one oracle change should produce, as (reason, selectors)."""
    what, how = c["what"], c["how"]
    if (what, how) in EFFECT:
        return [(EFFECT[(what, how)], {"account": c["account"]})]
    if what == "trade":
        return [("trade", {"account": c["account"], "fields": {"offer_id": c["offer_id"]}})]
    if what == "claimable":
        f = {"fields": {"balance_id": c["balance_id"]}}
        if how == "created":
            return [("claimable_balance_created", f)] + [
                ("claimable_balance_claimant_created", {"account": a, "fields": {"balance_id": c["balance_id"]}})
                for a in c["claimants"]]
        reason = CLAIMABLE_REMOVED.get(c["op_type"])
        return [(reason, f)] if reason else []
    if what == "pool":
        f = {"fields": {"liquidity_pool_id": c["pool_id"]}}
        if how == "created":
            return [("liquidity_pool_created", f)]
        if how == "removed":
            # A revocation that empties a pool removes it; it is still a revocation of that pool.
            extra = [("liquidity_pool_revoked", f)] if POOL_CHANGE.get(c["op_type"]) == "liquidity_pool_revoked" else []
            return [("liquidity_pool_removed", f)] + extra
        reason = POOL_CHANGE.get(c["op_type"])
        return [(reason, f)] if reason else []
    if what == "sponsorship" and c["entry"] in SPONSORED:
        reason = "%s_sponsorship_%s" % (c["entry"], how)
        if c["entry"] in ("account", "trustline"):
            sel = {"account": c["account"]}
            if c["entry"] == "trustline":
                kind, value = c["holding"]
                if kind == "asset":
                    sel["token"] = asset_text(value)
                else:
                    sel["fields"] = {"liquidity_pool_id": value}
            return [(reason, sel)]
        # Data and claimable balance sponsorship effects belong to the operation's source; match the entry.
        if c["entry"] == "data":
            return [(reason, {"fields": {"data_name": c["name"]}})]
        return [(reason, {"fields": {"balance_id": c["balance_id"]}})]
    if what == "signer-sponsorship":
        return [("signer_sponsorship_%s" % how, {"account": c["account"], "signer_key": c["signer"]})]
    return []


def expectations(changes, passphrase):
    # Trustline authorization that comes with a trustline being created or removed in the same
    # operation is part of trustline_created / trustline_removed, not a separate flags effect.
    born = {(c["tx_hash"], c["where"], c["account"], json.dumps(c["holding"], sort_keys=True))
            for c in changes if c["what"] == "trustline" and c["how"] in ("added", "removed")}
    merged = {}
    for c in changes:
        if not c["success"] or not isinstance(c["where"], int):
            continue
        effect = EFFECT.get((c["what"], c["how"]))
        if effect is None:
            for reason, sel in effects_for(c):
                e = {"expect": "state_change", "category": "EFFECT", "reason": reason, "tx_hash": c["tx_hash"]}
                e.update({k: v for k, v in sel.items() if k != "fields"})
                e["fields"] = dict(sel.get("fields") or {}, op_order=c["where"] + 1)
                key = json.dumps(e, sort_keys=True)
                if key in merged:
                    merged[key]["count"] = merged[key].get("count", 1) + 1
                else:
                    merged[key] = dict(e, derived_from="oracle: %s %s (op %d %s)" % (c["what"], c["how"], c["where"], c["op_type"]),
                                       via={"where": c["where"], "op_type": c["op_type"], "what": c["what"], "how": c["how"]})
            continue
        if c["what"] == "trustauth" and (c["tx_hash"], c["where"], c["account"],
                                         json.dumps(c["holding"], sort_keys=True)) in born:
            continue
        e = {"expect": "state_change", "category": "EFFECT", "reason": effect, "tx_hash": c["tx_hash"],
             "account": c["account"], "fields": {"op_order": c["where"] + 1}}
        if effect == "trustline_flags_updated":
            # Horizon's model: the effect belongs to the operation's source (the issuer) and names the
            # trustor in its details.
            del e["account"]
            e["fields"]["trustor"] = c["account"]
        if c["what"] == "signer":
            e["signer_key"] = c["signer"]
        if c["what"] == "data":
            e["fields"]["name"] = c.get("name")
        if c["what"] in ("trustline", "trustauth"):
            kind, value = c["holding"]
            if kind == "asset":
                e["token"] = asset_text(value)
            else:
                e["fields"]["liquidity_pool_id"] = value
        key = json.dumps(e, sort_keys=True)
        if key in merged:
            if effect not in PER_OPERATION:
                merged[key]["count"] = merged[key].get("count", 1) + 1
        else:
            merged[key] = dict(e, derived_from="oracle: %s %s (op %d %s)" % (c["what"], c["how"], c["where"], c["op_type"]),
                               via={"where": c["where"], "op_type": c["op_type"], "what": c["what"], "how": c["how"]})
    for e in allow_trust_types(changes) + offer_effect_bounds(changes):
        merged[json.dumps(e, sort_keys=True)] = e
    return list(merged.values())


OFFER_EFFECTS = ["offer_created", "offer_updated", "offer_removed"]


def offer_effect_bounds(changes):
    """For every operation that changed an offer entry: no more offer_created/updated/removed effects
    than offer entries the ledger changed in it (stellar-etl#456: a trade claim emits offer effects
    for buyer and seller, several per claimed offer; Horizon emits none)."""
    per, traded = {}, set()
    for c in changes:
        if c["success"] and isinstance(c["where"], int):
            k = (c["tx_hash"], c["where"])
            if c["what"] == "offer":
                per[k] = per.get(k, 0) + 1
            elif c["what"] == "trade":
                traded.add(k)
    return [{"expect": "effect_count_at_most", "tx_hash": tx, "op_order": where + 1, "reasons": OFFER_EFFECTS, "max": n,
             "derived_from": "oracle: %d offer entr%s changed in op %d" % (n, "y" if n == 1 else "ies", where),
             "via": {"where": where, "what": "offer effects",
                     "how": "more than the ledger changed, in a trade" if (tx, where) in traded else "more than the ledger changed"}}
            for (tx, where), n in sorted(per.items())]


def deploy_expectations(value, passphrase):
    """A contract deploy's details: the contract ID derived from the envelope's preimage, and, for an
    address preimage, its salt (stellar-etl#462: the salt is omitted, and contract_id is the first
    contract-data key of the footprint)."""
    import oracle
    out = []
    for d in oracle.deploys(value, passphrase):
        base = {"expect": "operation_detail", "tx_hash": d["tx_hash"], "op_order": d["where"] + 1,
                "via": {"where": d["where"], "what": "deploy details"}}
        out.append(dict(base, field="contract_id", value=d["contract"], derived_from="oracle: the contract ID of the deploy's preimage",
                        via=dict(base["via"], how="contract_id")))
        if d["from"] == "address":
            out.append(dict(base, field="salt", derived_from="oracle: the deploy's preimage carries a salt",
                            via=dict(base["via"], how="salt")))
    return out


def meta_events(value):
    """Per transaction, the contract events its meta carries outside the diagnostic list: protocol 23+
    (meta v4) each operation's `events` and the transaction-level `events` (fee events); before 23
    (meta v3) `sorobanMeta.events`. Yields (tx_hash, success, [ContractEvent value, ...])."""
    import oracle
    for tp in value["v%d" % value["v"]]["txProcessing"]:
        res = tp["result"]
        meta = tp["txApplyProcessing"]
        mv = meta.get("v%d" % meta["v"]) or {}
        events = []
        if meta["v"] >= 4:
            events += [te["event"] for te in mv.get("events") or []]
            for op in mv.get("operations") or []:
                events += op.get("events") or []
        elif meta["v"] == 3:
            events += (mv.get("sorobanMeta") or {}).get("events") or []
        yield res["transactionHash"], res["result"]["result"]["code"] in oracle.SUCCESS, events


def event_expectations(value, passphrase):
    """stellar-etl's history_contract_events: every contract event of the meta exported exactly as
    often as the meta carries it (stellar-etl#452: the diagnostic list, which repeats a successful
    call's contract events, is exported as well), and `in_successful_contract_call` true only for a
    successful transaction (#452: hard-coded true)."""
    out = []
    for tx, ok, events in meta_events(value):
        counts = {}
        for ev in events:
            x = hashlib.sha256(_encoder().encode("ContractEvent", ev)).hexdigest()
            counts[x] = counts.get(x, 0) + 1
        for x, n in counts.items():
            base = {"tx_hash": tx, "event_sha256": x, "via": {"what": "contract event", "success": ok}}
            out.append(dict(base, expect="contract_event", count=n,
                            derived_from="oracle: the event appears %d time(s) in the transaction's meta, diagnostics "
                                         "aside" % n, via=dict(base["via"], how="exported as often as the meta has it")))
            out.append(dict(base, expect="contract_event_flag", in_successful_contract_call=ok,
                            derived_from="oracle: the transaction %s" % ("succeeded" if ok else "failed"),
                            via=dict(base["via"], how="in_successful_contract_call")))
    return out


# Rounding slippage of a liquidity-pool trade (stellar-etl#451): Horizon's definition, which the
# issue takes as the reference. go-stellar-sdk exp/orderbook/pools.go, ported exactly (integer
# arithmetic; a result Go would flag as not ok is None).
MAX_BIPS = 10_000
INT64_MAX = 2 ** 63 - 1


def _slippage_bips(numer, denom, result):
    unrounded = numer * MAX_BIPS // denom
    if unrounded == 0:
        return 0  # uint256 division by zero is 0
    return abs(unrounded - result * MAX_BIPS) * MAX_BIPS // unrounded // 100


def pool_payout_slippage(reserve_a, reserve_b, received, fee):
    """CalculatePoolPayout(reserveA, reserveB, received, fee, true): the slippage in bips, or None."""
    if reserve_a < 0 or reserve_b < 0 or received < 0 or not 0 <= fee < MAX_BIPS:
        return None
    if received > INT64_MAX - reserve_a:
        return None
    f = MAX_BIPS - fee
    denom = reserve_a * MAX_BIPS + received * f
    if denom == 0:
        return None
    numer = reserve_b * received * f
    result, slip = numer // denom, 0
    if numer % denom:
        slip = _slippage_bips(numer, denom, result)
        if slip > INT64_MAX:
            return None
    return slip if 0 < result <= INT64_MAX else None


def pool_expectation_slippage(reserve_a, reserve_b, disbursed, fee):
    """CalculatePoolExpectation(reserveA, reserveB, disbursed, fee, true): the slippage in bips, or None."""
    if reserve_a < 0 or reserve_b < 0 or disbursed < 0 or not 0 <= fee < MAX_BIPS:
        return None
    if disbursed >= reserve_b:
        return None
    f = MAX_BIPS - fee
    denom = (reserve_b - disbursed) * f
    if denom == 0:
        return None
    numer = reserve_a * disbursed * MAX_BIPS
    result, slip = numer // denom, 0
    if numer % denom:
        result += 1
        slip = _slippage_bips(numer, denom, result)
        if slip > INT64_MAX:
            return None
    return slip if 0 <= result <= INT64_MAX - reserve_a else None


def pool_trades(value):
    """Every liquidity-pool trade of a successful path payment: (tx_hash, op_order, order, op type,
    expected rounding slippage in bips). Reserves are the pool's state before the operation's last
    change to it, as both indexers read them; deposited and disbursed are from the pool's side."""
    import oracle
    out = []
    for tp in value["v%d" % value["v"]]["txProcessing"]:
        res = tp["result"]
        if res["result"]["result"]["code"] not in oracle.SUCCESS:
            continue
        inner = res["result"]["result"]
        results = inner.get("results") or (inner.get("innerResultPair") or {}).get("result", {}).get("result", {}).get("results") or []
        meta = tp["txApplyProcessing"]
        mv = meta.get("v%d" % meta["v"]) or {}
        ops_meta = mv.get("operations") or []
        for i, r in enumerate(results):
            tr = r.get("tr") or {}
            kind = tr.get("type")
            if kind not in ("PATH_PAYMENT_STRICT_RECEIVE", "PATH_PAYMENT_STRICT_SEND"):
                continue
            body = tr.get("pathPaymentStrictReceiveResult") or tr.get("pathPaymentStrictSendResult") or {}
            offers = (body.get("success") or {}).get("offers") or []
            pre = {}
            for k, before, _after in oracle.pairs(ops_meta[i].get("changes") or [] if i < len(ops_meta) else []):
                if before and before["data"]["type"] == "LIQUIDITY_POOL":
                    pre[before["data"]["liquidityPool"]["liquidityPoolID"]] = before["data"]["liquidityPool"]
            for order, claim in enumerate(offers):
                if claim["type"] != "CLAIM_ATOM_TYPE_LIQUIDITY_POOL":
                    continue
                c = claim["liquidityPool"]
                pool = pre.get(c["liquidityPoolID"])
                if pool is None:
                    continue
                cp = pool["body"]["constantProduct"]
                a, b = int(cp["reserveA"]), int(cp["reserveB"])
                if json.dumps(c["assetSold"], sort_keys=True) != json.dumps(cp["params"]["assetA"], sort_keys=True):
                    a, b = b, a
                disbursed_reserve, deposited_reserve, fee = a, b, int(cp["params"]["fee"])
                if kind == "PATH_PAYMENT_STRICT_RECEIVE":
                    slip = pool_expectation_slippage(deposited_reserve, disbursed_reserve, int(c["amountSold"]), fee)
                else:
                    slip = pool_payout_slippage(deposited_reserve, disbursed_reserve, int(c["amountBought"]), fee)
                out.append((res["transactionHash"], i + 1, order, kind, INT64_MAX if slip is None else slip))
    return out


def ledger_expectations(value, passphrase):
    """stellar-etl#451: every liquidity-pool trade exported with the rounding slippage Horizon's
    definition gives (CalculatePoolExpectation for a strict receive, CalculatePoolPayout for a strict
    send, the maximum int64 when the calculation would overflow)."""
    return [{"expect": "trade_detail", "tx_hash": tx, "op_order": op, "order": order, "field": "rounding_slippage",
             "value": slip, "derived_from": "oracle: the pool's reserves before the operation, %s" % kind.lower(),
             "via": {"where": op - 1, "op_type": kind, "what": "trade", "how": "rounding slippage"}}
            for tx, op, order, kind, slip in pool_trades(value)]


# --------------------------------------------------------------- entry changes (sequences)
# export_ledger_entry_changes writes, per ledger, one row per account, trustline, offer, liquidity pool
# and claimable balance the ledger changed, with that ledger's net change: it compacts each ledger's
# changes on their own (ExtractBatch makes a ChangeCompactor per ledger). Net change: created (did not
# exist before the ledger, exists after), updated (existed, exists), removed (existed, does not),
# restored (an archived entry made live, then whatever followed), and nothing for an entry created and
# removed in the same ledger. The harness runs it on sequences only: for a range of one ledger it
# writes nothing.
CHANGE_CREATED, CHANGE_UPDATED, CHANGE_REMOVED, CHANGE_RESTORED = 0, 1, 2, 4
ENTRY_TABLES = {"ACCOUNT": "account", "TRUSTLINE": "trustline", "OFFER": "offer",
                "LIQUIDITY_POOL": "liquidity_pool", "CLAIMABLE_BALANCE": "claimable_balance"}


def entry_identity(kind, body):
    """(table, key as stellar-etl exports it) of a ledger entry's data or ledger key, or None."""
    import base64
    table = ENTRY_TABLES.get(kind)
    if table == "account":
        return table, strkey.account(body["accountID"].get("ed25519") or body["accountID"]["value"])
    if table == "trustline":
        lk = {"type": "TRUSTLINE", "trustLine": {"accountID": body["accountID"], "asset": body["asset"]}}
        return table, base64.b64encode(_encoder().encode("LedgerKey", lk)).decode()
    if table == "offer":
        return table, str(body["offerID"])
    if table == "liquidity_pool":
        return table, body["liquidityPoolID"]
    if table == "claimable_balance":
        import oracle
        return table, oracle.balance_id_hex(body["balanceID"])
    return None


ARM = {"ACCOUNT": "account", "TRUSTLINE": "trustLine", "OFFER": "offer", "LIQUIDITY_POOL": "liquidityPool",
       "CLAIMABLE_BALANCE": "claimableBalance"}


def ledger_entry_changes(value):
    """{(table, key): net change} for one ledger, from its change lists in the order stellar-core
    applies them (oracle.close_order)."""
    import oracle
    seen = {}  # identity -> [existed before the ledger, exists now, restored]
    for lst in oracle.close_order(value):
        for ch in lst or []:
            t = ch["type"]
            if t == "LEDGER_ENTRY_REMOVED":
                key = ch["removed"]
                ident = entry_identity(key["type"], key.get(ARM.get(key["type"], ""), {})) if key["type"] in ARM else None
            else:
                arm = {"LEDGER_ENTRY_STATE": "state", "LEDGER_ENTRY_CREATED": "created", "LEDGER_ENTRY_UPDATED": "updated",
                       "LEDGER_ENTRY_RESTORED": "restored"}.get(t)
                data = (ch.get(arm) or {}).get("data") if arm else None
                ident = entry_identity(data["type"], data[ARM[data["type"]]]) if data and data["type"] in ARM else None
            if ident is None:
                continue
            first = ident not in seen
            st = seen.setdefault(ident, [t != "LEDGER_ENTRY_CREATED" and t != "LEDGER_ENTRY_RESTORED", False, False])
            if t == "LEDGER_ENTRY_REMOVED":
                st[1] = False
            elif t == "LEDGER_ENTRY_RESTORED":
                st[1], st[2] = True, True
            elif t in ("LEDGER_ENTRY_CREATED", "LEDGER_ENTRY_UPDATED"):
                st[1] = True
            elif t == "LEDGER_ENTRY_STATE" and first:
                st[1] = True
    out = {}
    for ident, (before, after, restored) in seen.items():
        if restored:
            out[ident] = CHANGE_RESTORED if after else CHANGE_REMOVED
        elif before and after:
            out[ident] = CHANGE_UPDATED
        elif before:
            out[ident] = CHANGE_REMOVED
        elif after:
            out[ident] = CHANGE_CREATED
    return out


def end_state_expectations(values, passphrase):
    """For a sequence: every ledger's entry changes as export_ledger_entry_changes should write them,
    one row per entry and ledger with its net change, and no row for an entry the ledger did not change."""
    out = []
    names = {0: "created", 1: "updated", 2: "removed", 4: "restored"}
    for value in values:
        seq = value["v%d" % value["v"]]["ledgerHeader"]["header"]["ledgerSeq"]
        net = ledger_entry_changes(value)
        for (table, key), change in sorted(net.items()):
            out.append({"expect": "entry_change", "table": table, "key": key, "ledger": seq, "change": change,
                        "deleted": change == CHANGE_REMOVED,
                        "derived_from": "oracle: the %s is %s in ledger %d (net of the ledger's changes)" % (table, names[change], seq),
                        "via": {"what": "entry change", "how": names[change], "table": table}})
        for table in sorted(set(ENTRY_TABLES.values())):
            out.append({"expect": "entry_changes_only", "table": table, "ledger": seq,
                        "keys": sorted(k for (t, k) in net if t == table),
                        "derived_from": "oracle: the %s entries ledger %d changed" % (table, seq),
                        "via": {"what": "entry change", "how": "no other row", "table": table}})
    return out


def allow_trust_types(changes):
    """Horizon's model gives an AllowTrust operation, before its trustline_flags_updated effect, an
    effect whose type says the trustline's new authorization: trustline_authorized (23),
    trustline_authorized_to_maintain_liabilities (25) or trustline_deauthorized (24). The ledger
    gives that state: the flags the operation set and cleared on the trustline."""
    ops = {}
    for c in changes:
        if c["success"] and c["what"] == "trustauth" and c["op_type"] == "ALLOW_TRUST" and isinstance(c["where"], int):
            k = (c["tx_hash"], c["where"], c["account"], json.dumps(c["holding"], sort_keys=True))
            ops.setdefault(k, {"set": set(), "cleared": set(), "c": c})[c["how"]].update(c.get("flags") or [])
    out = []
    for (tx, where, account, _), d in sorted(ops.items()):
        if "authorized" in d["set"]:
            effect = "trustline_authorized"
        elif "authorized_to_maintain_liabilities" in d["set"]:
            effect = "trustline_authorized_to_maintain_liabilities"
        else:
            effect = "trustline_deauthorized"
        e = {"expect": "state_change", "category": "EFFECT", "reason": effect, "tx_hash": tx,
             "fields": {"op_order": where + 1, "trustor": account}}
        kind, value = d["c"]["holding"]
        if kind == "asset":
            e["token"] = asset_text(value)
        out.append(dict(e, derived_from="oracle: trustauth %s by ALLOW_TRUST (op %d), Horizon's effect type" % (
            ", ".join(sorted(["set " + f for f in d["set"]] + ["cleared " + f for f in d["cleared"]])), where),
            via={"where": where, "op_type": "ALLOW_TRUST", "what": "trustauth", "how": "allow_trust effect type"}))
    return out


def balance_expectations(records, passphrase):
    """One balance_net expectation per oracle balance record. stellar-etl's token transfer events
    carry the asset's contract ID and, except for fees, the operation's TOID."""
    out = []
    for b in records:
        token = asset_contract({"type": "ASSET_TYPE_NATIVE"} if b["holding"] == "native" else b["holding"], passphrase)
        op_order = 0 if b["where"] == "fee" else b["where"] + 1
        out.append({"expect": "balance_net", "account": b["account"], "token": token, "tx_hash": b["tx_hash"],
                    "op_order": op_order, "delta": b["delta"],
                    "derived_from": "oracle: balance %+d (%s)" % (b["delta"], "fee" if b["where"] == "fee" else "op %d %s" % (b["where"], b["op_type"])),
                    "via": {"where": b["where"], "op_type": b["op_type"], "what": "balance", "how": "changed"}})
    return out


def muxed_expectations(records, passphrase):
    """One muxed_destination expectation per CAP-67 transfer or mint event that names `to_muxed_id`:
    stellar-etl's token transfer row for that receipt must carry the muxed address for an integer ID,
    and none for a text or hash memo."""
    return [{"expect": "muxed_destination", "tx_hash": m["tx_hash"], "op_order": m["where"] + 1,
             "account": m["account"], "muxed": m["muxed"], "amount": m.get("amount"),
             "derived_from": "oracle: to_muxed_id %s (op %d)" % (m["kind"], m["where"]),
             "via": {"where": m["where"], "what": "muxed", "how": m["kind"]}} for m in records]


_KNOWN = {}


def known_issue(expectation):
    """The open upstream issue that explains this expectation failing, from known.json, or None."""
    if "rules" not in _KNOWN:
        with open(os.path.join(HERE, "known.json")) as f:
            _KNOWN["rules"] = json.load(f)["rules"]
    via = expectation.get("via") or {}
    facts = {"category": expectation.get("category"), "reason": expectation.get("reason"),
             "account_kind": (expectation.get("account") or "?")[0], "op_type": via.get("op_type"),
             "where": via.get("where"), "what": via.get("what"), "how": via.get("how"),
             "error": expectation.get("error")}
    for rule in _KNOWN["rules"]:
        ok = True
        for k, want in rule["match"].items():
            if k.endswith("_contains"):
                if want not in (facts.get(k[:-len("_contains")]) or ""):
                    ok = False
                    break
                continue
            got = facts.get(k)
            if (got not in want) if isinstance(want, list) else (got != want):
                ok = False
                break
        if ok:
            return rule["issue"]
    return None
