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
    "cell runs the commit's own `export_transactions`, `export_operations`, `export_effects` and",
    "`export_token_transfer` for the one ledger and reads the exported JSON back. stellar-etl reads only",
    "pubnet, testnet and futurenet, so entries from stellar-core's test data are `n/a`.",
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
    for e in allow_trust_types(changes):
        merged[json.dumps(e, sort_keys=True)] = e
    return list(merged.values())


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
