#!/usr/bin/env python3
"""Mutation testing of the replay oracle: seeded indexer bugs, one at a time. No Docker.

  python3 harness/replay/adapters/example/mutants.py            write MUTANTS.md and mutants.json here
  python3 harness/replay/adapters/example/mutants.py --check    exit 1 if a result differs from mutants.json

The backtest (harness/replay/BACKTEST.md) measures detection on wallet-backend's real history. This
measures it under control. A "full" toy indexer stores what the oracle checks, in wallet-backend's
vocabulary: state changes, BALANCE rows (CREDIT and DEBIT per transaction and operation, the net
fee at position 0) and each transaction's participants. The baseline stores exactly what each
ledger's meta shows, so it passes. Each mutant changes one thing, the way a real indexer gets it
wrong; the harness's own verdict (replay.py's oracle_verdict, with wallet-backend's mapping and no
known issues) judges it on every ledger below. A mutant is:
- killed: some ledger it changes is judged a failure;
- survived: it changes some ledger, and none of them fails; the report names the check that would
  catch it;
- not exercised: no ledger here has the shape it changes.
The toy indexer runs in-process on the decoded corpus ledgers, not through the feeder; the example
adapter (README.md here) shows the same toy family through the real harness.
"""
import argparse
import copy
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPLAY = HERE.parent.parent
ROOT = REPLAY.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(REPLAY))
import base64  # noqa: E402

import oracle  # noqa: E402
import strkey  # noqa: E402
from decode import Decoder  # noqa: E402

LEDGERS = ["localcore-classic-p22-3", "localcore-memo-and-offer-p30-4", "localcore-sac-trust-p28-5",
           "localcore-pool-revoke-two-pools-7", "localcore-claim-and-sponsor-8", "localcore-sponsorship-transfer-9",
           "localcore-preauth-failed-6", "localcore-maintain-liabilities-5", "localcore-muxed-source-p22-3",
           "localcore-planted-auth-5", "localcore-declared-deploy-6", "localcore-tx-failures-plain-12",
           "localcore-op-failures-8", "testnet-4437357-signed-payload-signer", "testnet-5709224", "pubnet-65480300"]
OUT_JSON, OUT_MD = HERE / "mutants.json", HERE / "MUTANTS.md"
STRANGER = "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ"


class Mapping:
    """wallet-backend's oracle mapping with no known issues: every failure counts as a detection."""

    def __init__(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("wb_expect", REPLAY / "adapters/wallet-backend/expect.py")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.expectations = self.m.expectations
        self.balance_expectations = self.m.balance_expectations
        self.participant_expectations = self.m.participant_expectations

    def known_issue(self, expectation, commit=None):
        return None


def baseline(exps, parts):
    """The toy indexer that stores exactly what the meta shows: one row per expected row."""
    obs = {"ingested": True, "error": None, "adapter_failure": False, "transactions": [], "operations": [],
           "state_changes": [], "unreadable": []}
    for e in exps:
        if e["expect"] == "state_change":
            row = {k: e[k] for k in ("category", "reason", "account", "token", "signer_key", "tx_hash", "fields")
                   if k in e}
            row["_via"] = e.get("via", {})
            obs["state_changes"] += [dict(row) for _ in range(e.get("count", 1))]
        elif e["expect"] == "balance_net" and e["delta"]:
            obs["state_changes"].append({"category": "BALANCE", "reason": "CREDIT" if e["delta"] > 0 else "DEBIT",
                                         "account": e["account"], "token": e["token"], "tx_hash": e["tx_hash"],
                                         "op_order": e["op_order"], "fields": {"amount": abs(e["delta"])},
                                         "_via": e.get("via", {})})
    for r in parts:
        obs["transactions"].append({"hash": r["tx_hash"], "participants": list(r["changed"]), "_success": r["success"]})
    return obs


# ---- the mutants: (name, what it does, the check that catches it, function(obs, ledger) -> obs or None)

def _rows(obs, keep):
    out = copy.deepcopy(obs)
    out["state_changes"] = [r for r in out["state_changes"] if keep(r)]
    return out if len(out["state_changes"]) != len(obs["state_changes"]) else None


def ignore_fee(obs, L):
    return _rows(obs, lambda r: not (r["category"] == "BALANCE" and r.get("op_order") == 0))


def skip_failed(obs, L):
    failed = {t["hash"] for t in obs["transactions"] if not t["_success"]}
    out = _rows(obs, lambda r: r["tx_hash"] not in failed)
    if out is not None:
        out["transactions"] = [t for t in out["transactions"] if t["hash"] not in failed]
    return out


def drop_op_type(op_type):
    def f(obs, L):
        return _rows(obs, lambda r: (r.get("_via") or {}).get("op_type") != op_type)
    return f


def swap_parties(obs, L):
    """Payments stored with source and destination swapped."""
    out, changed = copy.deepcopy(obs), False
    groups = {}
    for r in out["state_changes"]:
        if r["category"] == "BALANCE" and (r.get("_via") or {}).get("op_type") == "PAYMENT":
            groups.setdefault((r["tx_hash"], r["op_order"], r["token"]), []).append(r)
    for rows in groups.values():
        cr = [r for r in rows if r["reason"] == "CREDIT"]
        db = [r for r in rows if r["reason"] == "DEBIT"]
        if len(cr) == 1 and len(db) == 1 and cr[0]["account"] != db[0]["account"]:
            cr[0]["account"], db[0]["account"] = db[0]["account"], cr[0]["account"]
            changed = True
    return out if changed else None


def negate(obs, L):
    out = copy.deepcopy(obs)
    rows = [r for r in out["state_changes"] if r["category"] == "BALANCE" and r.get("op_order")]
    for r in rows:
        r["reason"] = "DEBIT" if r["reason"] == "CREDIT" else "CREDIT"
    return out if rows else None


def op_order_shift(obs, L):
    out = copy.deepcopy(obs)
    rows = [r for r in out["state_changes"] if r["category"] == "BALANCE" and r.get("op_order")]
    for r in rows:
        r["op_order"] += 1
    return out if rows else None


def truncate_addresses(obs, L):
    """Addresses stored in a column too short for them: the last character lost."""
    out = copy.deepcopy(obs)
    for r in out["state_changes"]:
        r["account"] = r["account"][:-1]
    return out if out["state_changes"] else None


def amount_from_envelope(obs, L):
    """A path payment's source debit taken from the envelope's sendMax (strict receive) instead of
    the meta, and its destination credit from destMin (strict send)."""
    out, changed = copy.deepcopy(obs), False
    for h, (_, tx, _) in L["envelopes"].items():
        for k, op in enumerate(tx["operations"]):
            body = op["body"]
            t = body["type"]
            if t == "PATH_PAYMENT_STRICT_RECEIVE":
                field, side = body["pathPaymentStrictReceiveOp"]["sendMax"], "DEBIT"
            elif t == "PATH_PAYMENT_STRICT_SEND":
                field, side = body["pathPaymentStrictSendOp"]["destMin"], "CREDIT"
            else:
                continue
            for r in out["state_changes"]:
                if r["category"] == "BALANCE" and r["tx_hash"] == h and r.get("op_order") == k + 1 \
                        and r["reason"] == side and r["fields"]["amount"] != field:
                    r["fields"]["amount"] = field
                    changed = True
                    break
    return out if changed else None


def float_amounts(obs, L):
    """Amounts held in a float64 on the way to the database."""
    out, changed = copy.deepcopy(obs), False
    for r in out["state_changes"]:
        if r["category"] == "BALANCE" and int(float(r["fields"]["amount"])) != r["fields"]["amount"]:
            r["fields"]["amount"] = int(float(r["fields"]["amount"]))
            changed = True
    return out if changed else None


def drop_category(cat, reason=None):
    def f(obs, L):
        return _rows(obs, lambda r: not (r["category"] == cat and (reason is None or r["reason"] == reason)))
    return f


def drop_contract_trustlines(obs, L):
    return _rows(obs, lambda r: not (r["category"] == "TRUSTLINE" and r["reason"] == "ADD"
                                     and (r.get("_via") or {}).get("op_type") == "INVOKE_HOST_FUNCTION"))


def envelope_participants(obs, L):
    """Participants taken from the envelope: every address its operations name."""
    out, changed = copy.deepcopy(obs), False
    for t in out["transactions"]:
        env = L["envelopes"].get(t["hash"])
        if not env:
            continue
        found = set()
        oracle._addresses([env[2]] + env[1]["operations"], found)
        new = sorted(found | set(t["participants"]))
        if new != sorted(t["participants"]):
            t["participants"], changed = new, True
    return out if changed else None


def no_participants(obs, L):
    out = copy.deepcopy(obs)
    changed = any(t["participants"] for t in out["transactions"])
    for t in out["transactions"]:
        t["participants"] = []
    return out if changed else None


def spurious_balance(obs, L):
    out = copy.deepcopy(obs)
    if not out["transactions"]:
        return None
    out["state_changes"].append({"category": "BALANCE", "reason": "CREDIT", "account": STRANGER,
                                 "token": L["native_token"], "tx_hash": out["transactions"][0]["hash"], "op_order": 1,
                                 "fields": {"amount": 1}, "_via": {}})
    return out


def fee_per_operation(obs, L):
    """The fee stored once per operation instead of once per transaction."""
    out, changed = copy.deepcopy(obs), False
    ops = {h: len(tx["operations"]) for h, (_, tx, _) in L["envelopes"].items()}
    for r in out["state_changes"]:
        if r["category"] == "BALANCE" and r.get("op_order") == 0 and ops.get(r["tx_hash"], 1) > 1:
            r["fields"]["amount"] *= ops[r["tx_hash"]]
            changed = True
    return out if changed else None


def duplicate_state_changes(obs, L):
    out = copy.deepcopy(obs)
    extra = [copy.deepcopy(r) for r in out["state_changes"] if r["category"] != "BALANCE"]
    out["state_changes"] += extra
    return out if extra else None


def stranger_state_change(obs, L):
    out = copy.deepcopy(obs)
    if not out["transactions"]:
        return None
    out["state_changes"].append({"category": "TRUSTLINE", "reason": "ADD", "account": STRANGER, "token": L["native_token"],
                                 "tx_hash": out["transactions"][0]["hash"], "_via": {}})
    return out


def contract_balance(obs, L):
    out = copy.deepcopy(obs)
    if not out["transactions"]:
        return None
    out["state_changes"].append({"category": "BALANCE", "reason": "CREDIT", "account": L["native_token"],
                                 "token": L["native_token"], "tx_hash": out["transactions"][0]["hash"], "op_order": 1,
                                 "fields": {"amount": 1}, "_via": {}})
    return out


MUTANTS = [
    ("ignore the fee", "no BALANCE row for the fee", "balance_net at position 0", ignore_fee),
    ("fee once per operation", "the fee multiplied by the operation count", "balance_net at position 0", fee_per_operation),
    ("skip failed transactions", "a failed transaction stored with no rows at all", "balance_net for its fee", skip_failed),
    ("drop payments", "no rows for PAYMENT operations", "balance_net", drop_op_type("PAYMENT")),
    ("drop path payments (strict send)", "no rows for PATH_PAYMENT_STRICT_SEND", "balance_net",
     drop_op_type("PATH_PAYMENT_STRICT_SEND")),
    ("drop contract calls", "no rows for INVOKE_HOST_FUNCTION", "balance_net, state_change", drop_op_type("INVOKE_HOST_FUNCTION")),
    ("swap source and destination", "a payment's debit and credit stored on the wrong accounts", "balance_net", swap_parties),
    ("sign flipped", "CREDIT and DEBIT swapped for every operation", "balance_net", negate),
    ("operation index off by one", "operation positions shifted by one", "balance_net", op_order_shift),
    ("truncate addresses", "every stored address loses its last character", "state_change, balance_net", truncate_addresses),
    ("amount from the envelope", "a path payment's amount from sendMax or destMin, not from the meta",
     "balance_net", amount_from_envelope),
    ("amounts through float64", "amounts above 2^53 rounded", "balance_net", float_amounts),
    ("drop signers", "no SIGNER rows", "state_change", drop_category("SIGNER")),
    ("drop account creation", "no ACCOUNT CREATE rows", "state_change", drop_category("ACCOUNT", "CREATE")),
    ("drop account merge", "no ACCOUNT MERGE rows", "state_change", drop_category("ACCOUNT", "MERGE")),
    ("drop trustline authorization", "no BALANCE_AUTHORIZATION rows", "state_change",
     drop_category("BALANCE_AUTHORIZATION")),
    ("drop contract-created trustlines", "no TRUSTLINE ADD made by a contract call (CAP-73)", "state_change",
     drop_contract_trustlines),
    ("participants from the envelope", "every address the envelope names is a participant", "participants_within",
     envelope_participants),
    ("no participants", "transactions stored with no participants", "participant", no_participants),
    ("a stranger's balance", "a BALANCE row for an account the ledger never touches", "unexpected balance movement",
     spurious_balance),
    ("duplicate state changes", "every state change stored twice",
     "none: state changes are checked for presence, not for extra copies", duplicate_state_changes),
    ("a stranger's state change", "a TRUSTLINE ADD row for an account the ledger never touches",
     "participants_within: a stored state change's account must be an address the meta shows", stranger_state_change),
    ("a contract's balance", "a BALANCE row for a contract the ledger never touches",
     "only incidentally, through participants_within, when the contract is absent from the meta: balances held "
     "by contracts are not compared, because the oracle does not read contract storage", contract_balance),
]


def load_ledgers():
    import replay
    schema = json.load(open(ROOT / "schema/schema.json"))
    dec = Decoder(schema)
    manifest = {e["id"]: e for e in json.load(open(ROOT / "corpus/manifest.json"))["entries"]}
    mapping = Mapping()
    out = []
    for eid in LEDGERS:
        if eid not in manifest:
            continue
        e = manifest[eid]
        value = dec.decode("LedgerCloseMeta", base64.b64decode((ROOT / "corpus" / e["file"]).read_text()))
        pp = e["source"]["network_passphrase"]
        exps = mapping.expectations(oracle.changes(value), pp) + \
            mapping.balance_expectations(oracle.balances(value), pp) + \
            mapping.participant_expectations(oracle.participants(value, pp), pp)
        out.append({"id": eid, "entry": e, "value": value, "exps": exps, "parts": oracle.participants(value, pp),
                    "envelopes": oracle.envelopes_by_hash(value, pp),
                    "native_token": mapping.m.asset_contract({"type": "ASSET_TYPE_NATIVE"}, pp)})
    return out, mapping, replay


def judge(replay, L, mapping, obs):
    clean = copy.deepcopy(obs)
    for r in clean["state_changes"]:
        r.pop("_via", None)
    for t in clean["transactions"]:
        t.pop("_success", None)
    replay._EXPS.clear()
    v = replay.oracle_verdict(L["entry"], clean, mapping, L["value"])
    return v["verdict"] != "pass", v


def run():
    ledgers, mapping, replay = load_ledgers()
    base_ok = {}
    for L in ledgers:
        failed, v = judge(replay, L, mapping, baseline(L["exps"], L["parts"]))
        base_ok[L["id"]] = not failed
        if failed:
            print("BASELINE FAILS on %s: %s" % (L["id"], v["unexplained"][:2]))
    results = []
    for name, what, catcher, fn in MUTANTS:
        exercised, detected = [], []
        for L in ledgers:
            if not base_ok[L["id"]]:
                continue
            m = fn(baseline(L["exps"], L["parts"]), L)
            if m is None:
                continue
            exercised.append(L["id"])
            if judge(replay, L, mapping, m)[0]:
                detected.append(L["id"])
        status = "not exercised" if not exercised else ("killed" if detected else "survived")
        results.append({"mutant": name, "what": what, "check": catcher, "status": status,
                        "ledgers_changed": len(exercised), "ledgers_failing": len(detected)})
        print("%-34s %-14s %d of %d changed ledgers fail" % (name, status, len(detected), len(exercised)))
    return {"ledgers": [L["id"] for L in ledgers], "baseline_passes": sum(base_ok.values()), "mutants": results}


def render(d):
    killed = sum(1 for r in d["mutants"] if r["status"] == "killed")
    exercised = sum(1 for r in d["mutants"] if r["status"] != "not exercised")
    survivors = [r["mutant"] for r in d["mutants"] if r["status"] == "survived"]
    L = ["# Mutation testing of the replay oracle", "",
         "Generated by `mutants.py` in this directory; do not edit by hand. A toy indexer that stores what the oracle "
         "checks, in wallet-backend's vocabulary, is changed one bug at a time, and the harness's own verdict judges "
         "each mutant on %d corpus ledgers (the baseline passes on %d). The method is in the script's docstring."
         % (len(d["ledgers"]), d["baseline_passes"]), "",
         "**%d of the %d mutants the ledgers exercise are killed.** Survivors: %s. The checks require every row "
         "the ledger implies; extra rows are caught only by the participant rule and by the balance cross-check on "
         "accounts, so a row stored twice passes, and a contract's balance is caught only by chance. Where a mutant "
         "fails on only some of the ledgers it changes, the others happen to satisfy every check."
         % (killed, exercised, ", ".join(survivors) or "none"),
         "",
         "| Mutant | What it stores wrongly | Status | Changed ledgers that fail | Check that catches it, or what would |",
         "|---|---|---|---|---|"]
    for r in d["mutants"]:
        cell = "%d of %d" % (r["ledgers_failing"], r["ledgers_changed"]) if r["ledgers_changed"] else "—"
        check = r["check"] if " " in r["check"].split(":")[0] or r["check"].startswith("none") else "`%s`" % r["check"]
        L.append("| %s | %s | %s | %s | %s |" % (r["mutant"], r["what"], r["status"], cell, check))
    L += ["", "Ledgers: " + ", ".join("`%s`" % x for x in d["ledgers"]) + "."]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    d = run()
    if a.check:
        old = json.loads(OUT_JSON.read_text())
        same = old == d and OUT_MD.read_text() == render(d)
        print("MUTANTS OK" if same else "MUTANTS DIFFER from mutants.json or MUTANTS.md; rerun mutants.py")
        return 0 if same else 1
    OUT_JSON.write_text(json.dumps(d, indent=1) + "\n")
    OUT_MD.write_text(render(d))
    print("wrote MUTANTS.md and mutants.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
