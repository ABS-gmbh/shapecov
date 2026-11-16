"""Horizon's vocabulary for the changes tools/oracle.py derives from a ledger.

Horizon stores its effect model in `history_effects`, and who took part in each transaction and
operation in `history_transaction_participants` and `history_operation_participants`. stellar-etl's
`export_effects` is a copy of Horizon's effects processor, so the effect rows each oracle change
should produce are the stellar-etl adapter's (`../stellar-etl/expect.py`), which already follow
Horizon where the two differ (AllowTrust's authorization effect, no offer effects). What is
Horizon's own here: the participant rule, and `known.json`.

Effects belong to operations: a change outside any operation (fee processing,
txChangesBefore/After) has no effect by design and is not checked.
"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("stellar_etl_expect", os.path.join(HERE, "..", "stellar-etl", "expect.py"))
_etl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_etl)

REPORT_INTRO = [
    "Each cell is the result for one entry at one Horizon release. Horizon reads the one ledger from a data",
    "lake: the Galexie layout on S3, served by the feeder, through `horizon db reingest range <seq> <seq>",
    "--ledgerbackend datastore`, Horizon's own backfill command, into PostgreSQL after its own",
    "`db migrate up`. The history tables are read back: transactions, operations, effects, and the",
    "transaction and operation participants. Current-state tables are not built by a reingest and not read.",
]

EVIDENCE_FILES = ("job.json, observation.json, result.json, feeder-requests.jsonl, migrate.log, ingest.log, "
                  "tables.json (the rows read back), config/datastore.toml")


def manifest_expectations(exps):
    """The manifest's hand-written expectations name wallet-backend rows; only a stored transaction
    is meaningful for Horizon. The oracle covers the rest in Horizon's own vocabulary."""
    return [e for e in exps if e.get("expect") == "transaction"]


def expectations(changes, passphrase):
    """The effect rows the ledger's changes should produce: Horizon's effect model, as stellar-etl
    copies it."""
    return _etl.expectations(changes, passphrase)


def participant_expectations(records, passphrase):
    """From oracle.participants(). Horizon's participants processor records, per transaction, its
    source and fee source, every operation's participants, and the accounts its meta changed
    (participantsForMeta). So every account whose entry a successful transaction changed must be a
    transaction participant, and nothing outside what the meta shows may be one."""
    out = []
    for r in records:
        base = {"expect": "participants_within", "tx_hash": r["tx_hash"], "allowed": r["shown"], "success": r["success"]}
        kind = "account participant" if r["success"] else "failed transaction"
        sel = {"where": ["participants"], "address_kind": "G"} if r["success"] else {}
        out.append(dict(base, **sel, derived_from="oracle: addresses the %s transaction's meta shows" % (
            "successful" if r["success"] else "failed"),
            via={"what": "participant", "how": "outside meta", "kind": kind, "success": r["success"]}))
        if r["success"]:
            for a in r["changed"]:
                out.append({"expect": "participant", "account": a, "tx_hash": r["tx_hash"],
                            "derived_from": "oracle: the transaction changes this account's entry",
                            "via": {"what": "participant", "how": "account changed"}})
    return out


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
