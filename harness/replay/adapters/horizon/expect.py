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

REPORT_NOTES = [
    "## Coverage",
    "",
    "The recorded run covers 95 of the 95 corpus ledgers in the manifest at ShapeCov commit `d6e9559`, at",
    "stellar-horizon v30.0.1. Ledgers added to the corpus since are listed by `replay.py check` as having no",
    "result yet; the quick check counts them and does not fail. The replay workflow's Horizon job reruns three",
    "of them (`pubnet-60280000`, `localcore-pool-revoke-two-pools-7`, `golden-offer-9a363b75-30`) on every",
    "change to the harness and compares the verdicts with this run.",
    "",
    "## Reproductions, not blind detections",
    "",
    "The participant rule is the one written for wallet-backend, and stellar/stellar-horizon#259 was known",
    "when this adapter was written, so its 179 missed transaction participants on 15 ledgers are a",
    "reproduction of an open issue on real ledgers (record H1), not a detection. stellar-etl #513 and #514",
    "(records E2 and E3) were filed saying Horizon has the same code; on `localcore-pool-revoke-two-pools-7`",
    "Horizon stores the same 16 effects as stellar-etl, so both reproduce in Horizon itself.",
    "",
    "## A difference by design",
    "",
    "On 965 failed transactions in 34 ledgers, Horizon records 1,106 addresses as participants that the",
    "transaction's meta does not show: every address its envelope names. wallet-backend records none of them.",
    "Each is right for its API. A failed transaction changes nothing but its fee and sequence number;",
    "wallet-backend therefore attributes it to its source and fee source only. Horizon lists a failed",
    "transaction in the history of every account its envelope names, so that `include_failed=true` shows,",
    "for example, a failed payment under its intended destination: at v30.0.1 `ParticipantsForTransaction`",
    "(`internal/ingest/processors/participants_processor.go:176`) adds `operation.Participants()` for every",
    "operation with no success check, and `TransactionsQ.ForAccount` (`internal/db2/history/transaction.go:105`)",
    "finds an account's transactions only through that participants table. The oracle checks each indexer",
    "against its own declared choice (`FAILED_TX_PARTICIPANTS` in each adapter's `expect.py`), so these",
    "addresses meet Horizon's expectation and are not failures.",
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


# Who is a participant of a failed transaction: Horizon's design, declared here rather than left as
# an exception. A failed transaction changes nothing in the ledger but its fee and sequence number,
# yet Horizon lists it under every account its envelope names, so that an account's history with
# include_failed=true shows, for example, a failed payment to it. At v30.0.1:
# - internal/ingest/processors/participants_processor.go:176, ParticipantsForTransaction: the
#   source, the fee-bump account, the meta and fee changes, and operation.Participants() for every
#   operation (line 207), which reads the envelope, with no success check;
# - internal/db2/history/transaction.go:105, TransactionsQ.ForAccount, finds an account's
#   transactions through history_transaction_participants (line 113); IncludeFailed (line 176)
#   drops the "successful = true" filter (line 203). So that table is the only way a failed
#   transaction reaches the history of an account other than the fee payer.
# The API reference describes include_failed as "Set to true to include failed operations in
# results" and says no more about whose history; we treat the code as Horizon's design.
# wallet-backend declares the other choice ("meta", ../wallet-backend/expect.py).
FAILED_TX_PARTICIPANTS = "envelope and meta"


def _envelope_addresses(value, passphrase):
    """{transaction hash: every account or contract address its envelope names}."""
    import oracle
    out = {}
    for h, (_env, tx, _who) in oracle.envelopes_by_hash(value, passphrase).items():
        found = set()
        oracle._addresses(tx, found)
        out[h] = found
    return out


def participant_expectations(records, passphrase, value=None):
    """From oracle.participants(). Horizon's participants processor records, per transaction, its
    source and fee source, every operation's participants, and the accounts its meta changed
    (participantsForMeta). So every account whose entry a successful transaction changed must be a
    transaction participant, and nothing outside what the meta shows may be one; for a failed
    transaction, nothing outside what the meta shows or the envelope names (FAILED_TX_PARTICIPANTS)."""
    envelope = _envelope_addresses(value, passphrase) if value is not None else {}
    out = []
    for r in records:
        if r["success"]:
            out.append({"expect": "participants_within", "tx_hash": r["tx_hash"], "allowed": r["shown"],
                        "success": True, "where": ["participants"], "address_kind": "G",
                        "derived_from": "oracle: addresses the successful transaction's meta shows",
                        "via": {"what": "participant", "how": "outside meta", "kind": "account participant",
                                "success": True}})
            for a in r["changed"]:
                out.append({"expect": "participant", "account": a, "tx_hash": r["tx_hash"],
                            "derived_from": "oracle: the transaction changes this account's entry",
                            "via": {"what": "participant", "how": "account changed"}})
        else:
            allowed = sorted(set(r["shown"]) | envelope.get(r["tx_hash"], set()))
            out.append({"expect": "participants_within", "tx_hash": r["tx_hash"], "allowed": allowed, "success": False,
                        "derived_from": "oracle: addresses the failed transaction's meta shows, and, by Horizon's design "
                                        "(FAILED_TX_PARTICIPANTS), every address its envelope names",
                        "via": {"what": "participant", "how": "outside meta and envelope", "kind": "failed transaction",
                                "success": False}})
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
