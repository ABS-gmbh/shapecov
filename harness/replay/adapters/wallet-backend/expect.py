"""wallet-backend's vocabulary for the changes tools/oracle.py derives from a ledger.

  expectations(oracle_changes, network_passphrase) -> list of classify.py expectations

The oracle says what changed in ledger state. This file says which state-change row
wallet-backend stores for each kind of change, using the categories and reasons in its
internal/indexer/types/types.go and the producers in internal/indexer/processors (effects.go,
token_transfer.go, contract_deploy.go, contracts/sac.go). The mapping only names the row; whether
a row is expected comes from the ledger, never from what wallet-backend wrote.

Expectations for the same row in the same transaction are merged into one with a count.
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "tools"))
import strkey  # noqa: E402
from encode import Encoder  # noqa: E402

_ENC = {}

ROW = {
    ("account", "created"): ("ACCOUNT", "CREATE"),
    ("account", "removed"): ("ACCOUNT", "MERGE"),
    ("contract", "created"): ("ACCOUNT", "CREATE"),
    ("signer", "added"): ("SIGNER", "ADD"),
    ("signer", "removed"): ("SIGNER", "REMOVE"),
    ("signer", "reweighted"): ("SIGNER", "UPDATE"),
    ("threshold", "changed"): ("SIGNATURE_THRESHOLD", "UPDATE"),
    ("flags", "set"): ("FLAGS", "SET"),
    ("flags", "cleared"): ("FLAGS", "CLEAR"),
    ("home", "set"): ("HOME_DOMAIN", "SET"),
    ("home", "cleared"): ("HOME_DOMAIN", "CLEAR"),
    ("home", "changed"): ("HOME_DOMAIN", "UPDATE"),
    ("data", "added"): ("DATA_ENTRY", "ADD"),
    ("data", "removed"): ("DATA_ENTRY", "REMOVE"),
    ("data", "changed"): ("DATA_ENTRY", "UPDATE"),
    ("trustline", "added"): ("TRUSTLINE", "ADD"),
    ("trustline", "removed"): ("TRUSTLINE", "REMOVE"),
    ("trustline", "limit changed"): ("TRUSTLINE", "UPDATE"),
    ("trustauth", "set"): ("BALANCE_AUTHORIZATION", "SET"),
    ("trustauth", "cleared"): ("BALANCE_AUTHORIZATION", "CLEAR"),
}


def _encoder():
    if "e" not in _ENC:
        schema = json.load(open(os.path.join(HERE, "..", "..", "..", "..", "schema", "schema.json")))
        _ENC["e"] = Encoder(schema)
    return _ENC["e"]


def asset_contract(asset, passphrase):
    """The Stellar Asset Contract ID of a credit asset (CAP-46), as a C... address."""
    preimage = {"type": "ENVELOPE_TYPE_CONTRACT_ID", "contractID": {
        "networkID": hashlib.sha256(passphrase.encode()).hexdigest(),
        "contractIDPreimage": {"type": "CONTRACT_ID_PREIMAGE_FROM_ASSET", "fromAsset": asset}}}
    return strkey.contract(hashlib.sha256(_encoder().encode("HashIDPreimage", preimage)).hexdigest())


def expectations(changes, passphrase):
    merged = {}
    for c in changes:
        if not c["success"]:
            continue  # a failed transaction applies no operation; its fee is a balance change
        row = ROW.get((c["what"], c["how"]))
        if row is None:
            continue
        e = {"expect": "state_change", "category": row[0], "reason": row[1], "tx_hash": c["tx_hash"]}
        if c["what"] == "contract":
            e["account"] = c["contract"]
        else:
            e["account"] = c["account"]
        if c["what"] == "signer":
            e["signer_key"] = c["signer"]
        if c["what"] in ("trustline", "trustauth"):
            kind, value = c["holding"]
            if kind == "asset":
                e["token"] = asset_contract(value, passphrase)
            else:
                e["fields"] = {"liquidity_pool_id": value}
        where = "op %d %s" % (c["where"], c["op_type"]) if isinstance(c["where"], int) else "txChanges%s" % c["where"].capitalize()
        key = json.dumps(e, sort_keys=True)
        if key in merged:
            merged[key]["count"] = merged[key].get("count", 1) + 1
        else:
            merged[key] = dict(e, derived_from="oracle: %s %s (%s)" % (c["what"], c["how"], where),
                               via={"where": c["where"], "op_type": c["op_type"], "what": c["what"], "how": c["how"]})
    return list(merged.values())


_KNOWN = {}


def known_issue(expectation):
    """The open upstream issue that explains this expectation failing, from known.json, or None."""
    if "rules" not in _KNOWN:
        with open(os.path.join(HERE, "known.json")) as f:
            _KNOWN["rules"] = json.load(f)["rules"]
    via = expectation.get("via") or {}
    facts = {"category": expectation.get("category"), "reason": expectation.get("reason"),
             "account_kind": (expectation.get("account") or "?")[0], "op_type": via.get("op_type"),
             "where": via.get("where")}
    for rule in _KNOWN["rules"]:
        ok = True
        for k, want in rule["match"].items():
            got = facts.get(k)
            if (got not in want) if isinstance(want, list) else (got != want):
                ok = False
                break
        if ok:
            return rule["issue"]
    return None
