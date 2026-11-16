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


def balance_expectations(records, passphrase):
    """One balance_net expectation per oracle balance record. wallet-backend writes a transaction's
    net fee at operation position 0 and an operation's movements at its 1-based position, with the
    asset's contract ID (the native one for XLM) as token."""
    out = []
    for b in records:
        token = asset_contract({"type": "ASSET_TYPE_NATIVE"} if b["holding"] == "native" else b["holding"], passphrase)
        op_order = 0 if b["where"] == "fee" else b["where"] + 1
        out.append({"expect": "balance_net", "account": b["account"], "token": token, "tx_hash": b["tx_hash"],
                    "op_order": op_order, "delta": b["delta"],
                    "derived_from": "oracle: balance %+d (%s)" % (b["delta"], "fee" if b["where"] == "fee" else "op %d %s" % (b["where"], b["op_type"])),
                    "via": {"where": b["where"], "op_type": b["op_type"], "what": "balance", "how": "changed"}})
    return out


# The other direction: every account whose account entry the transaction changed is a transaction
# participant. wallet-backend misses it (stellar/wallet-backend#677: participantsForMeta reads
# TransactionMeta's v0 arm, which is nil for meta v1 to v4); known.json labels those failures.
CHECK_CHANGED = True


def participant_expectations(records, passphrase):
    """From oracle.participants(): the accounts whose account entry changed must be transaction
    participants, and nothing outside what the meta shows may be a transaction or operation
    participant. wallet-backend stores participants in transactions_accounts and
    operations_accounts; the adapter reads both back."""
    out = []
    for r in records:
        base = {"expect": "participants_within", "tx_hash": r["tx_hash"], "allowed": r["shown"], "success": r["success"]}
        if not r["success"]:
            kinds = [("failed transaction", {})]
        else:  # one check per kind, so that each kind of failure can be told apart
            kinds = [("account participant", {"where": ["participants"], "address_kind": "G"}),
                     ("contract participant", {"where": ["participants"], "address_kind": "C"}),
                     ("state change", {"where": ["state_changes"]})]
        for kind, sel in kinds:
            out.append(dict(base, **sel,
                            derived_from="oracle: addresses the %s transaction's meta shows (%s)" % (
                                "successful" if r["success"] else "failed", kind),
                            via={"what": "participant", "how": "outside meta", "kind": kind, "success": r["success"]}))
        for a in (r["changed"] if CHECK_CHANGED else []):
            out.append({"expect": "participant", "account": a, "tx_hash": r["tx_hash"],
                        "derived_from": "oracle: the transaction changes this account's entry",
                        "via": {"what": "participant", "how": "account changed"}})
    return out


_KNOWN = {}


def _before(commit, fix):
    """True when `commit` is a strict ancestor of `fix` in the wallet-backend clone the harness
    builds from. Without the clone, or for an unknown commit, False: the failure stays unexplained."""
    if not commit:
        return False
    work = os.environ.get("REPLAY_WORK", os.path.join(HERE, "..", "..", ".work"))
    clone = os.path.join(work, "wallet-backend")
    key = (commit, fix)
    if key not in _ANCESTRY:
        import subprocess
        r = subprocess.run(["git", "-C", clone, "merge-base", "--is-ancestor", commit, fix], capture_output=True)
        _ANCESTRY[key] = r.returncode == 0 and not fix.startswith(commit) and not commit.startswith(fix)
    return _ANCESTRY[key]


_ANCESTRY = {}


def fixed_upstream():
    """Labels of the rules for defects wallet-backend has fixed: at the commits before the fix they
    are real failures, mapped to a record, and the backtest still counts them as failures."""
    if "rules" not in _KNOWN:
        with open(os.path.join(HERE, "known.json")) as f:
            _KNOWN["rules"] = json.load(f)["rules"]
    return {r["issue"] for r in _KNOWN["rules"] if r.get("fixed_by")}


def known_issue(expectation, commit=None):
    rule = known_rule(expectation, commit)
    return rule["issue"] if rule else None


def known_rule(expectation, commit=None):
    """The upstream issue or finding record that explains this expectation failing at `commit`,
    from known.json, or None."""
    if "rules" not in _KNOWN:
        with open(os.path.join(HERE, "known.json")) as f:
            _KNOWN["rules"] = json.load(f)["rules"]
    via = expectation.get("via") or {}
    facts = {"category": expectation.get("category"), "reason": expectation.get("reason"),
             "account_kind": (expectation.get("account") or "?")[0], "op_type": via.get("op_type"),
             "where": via.get("where"), "what": via.get("what"), "how": via.get("how"), "kind": via.get("kind")}
    for rule in _KNOWN["rules"]:
        if rule.get("fixed_by") and not _before(commit, rule["fixed_by"]):
            continue  # a defect wallet-backend has fixed labels only the commits before its fix
        ok = True
        for k, want in rule["match"].items():
            got = facts.get(k)
            if (got not in want) if isinstance(want, list) else (got != want):
                ok = False
                break
        if ok:
            return rule
    return None
