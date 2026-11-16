"""Compare an adapter's observation with the manifest's expectations and classify the entry.

Indexer-neutral: this file knows nothing about any particular indexer. It
reads the observation JSON described in ADAPTER.md and `expected.indexer`
from corpus/manifest.json.

Result, exactly one of:
  pass        the ledger was ingested, every stored address reads back, and every expectation is met
  mishandled  the indexer raised an error on this (valid) ledger, or stored a wrong value
  dropped     the ledger, or a row the manifest expects, is missing and no error was raised
If both apply, `mishandled` wins and the dropped expectations are still listed.

Expectation kinds (`expect`):
  signer_state_change  {signer_key}                       = state_change with category SIGNER
  state_change         {category, reason?, account?, token?, signer_key?, spender?, creator?,
                        destination?, tx_hash?, fields?: {name: value}, count?: n}
  no_state_change      same selectors; no stored row may match
  participant          {account, tx_hash?}                the account is recorded on the transaction
  no_participant       {account, tx_hash?}                the address must not be recorded
  participants_within  {tx_hash, allowed: [address]}      every participant stored for the transaction
                       or any of its operations, and the account of every state change stored for
                       it, is in `allowed` (the addresses its meta shows)
  transaction          {hash}                             the transaction is stored
  balance_net          {account, token, tx_hash, op_order, delta}
                       the account's BALANCE rows for that token in that transaction and
                       operation (op_order 0: the transaction's fee row) add up to delta:
                       CREDIT counts +amount, DEBIT -amount. MINT and BURN rows mark the
                       issuer's side and are not balance movements.
Every entry also carries the implicit expectation that the ledger is ingested without error
and that every stored address is a valid SEP-23 address.
"""
import strkeyx

ADDRESS_FIELDS = ("account", "token", "signer_key", "spender", "creator", "destination")
SELECTORS = ("category", "reason", "tx_hash") + ADDRESS_FIELDS


def _raw(strkey):
    try:
        return strkeyx.to_raw(strkey)
    except ValueError:
        return None


def _state_change(exp, obs):
    """-> (outcome, detail). outcome: met | wrong_value | missing"""
    want = {k: exp[k] for k in SELECTORS if exp.get(k) is not None}
    fields = exp.get("fields") or {}
    need = int(exp.get("count", 1))
    rows = obs.get("state_changes") or []
    full, near = [], []
    for r in rows:
        if any(r.get(k) != want[k] for k in ("category", "reason", "tx_hash") if k in want):
            continue
        addr_diff = [k for k in ADDRESS_FIELDS if k in want and r.get(k) != want[k]]
        field_diff = [k for k, v in fields.items() if str((r.get("fields") or {}).get(k)) != str(v)]
        if not addr_diff and not field_diff:
            full.append(r)
            continue
        # A row is a damaged version of the expected one when every differing address is a
        # truncation of the expected bytes (or an invalid address), and nothing else differs
        # except, possibly, the value fields the expectation lists.
        damaged = []
        for k in addr_diff:
            stored = bytes.fromhex((r.get("stored") or {}).get(k, ""))
            expected = _raw(want[k])
            if expected and stored and len(stored) < len(expected) and expected.startswith(stored):
                damaged.append("%s is stored truncated: %d of %d bytes (%s); it reads back as %s, expected %s"
                               % (k, len(stored), len(expected), stored.hex(), r.get(k), want[k]))
        if addr_diff and len(damaged) == len(addr_diff):
            near.append("; ".join(damaged))
        elif not addr_diff and field_diff:
            near.append("; ".join("%s is %r, expected %r" % (k, (r.get("fields") or {}).get(k), fields[k])
                                  for k in field_diff))
    label = "%s%s state change %s" % (want.get("category", "?"), "/" + want["reason"] if "reason" in want else "",
                                      ", ".join("%s=%s" % (k, want[k]) for k in ADDRESS_FIELDS + ("tx_hash",) if k in want))
    if len(full) >= need:
        return "met", "%s: %d row(s) stored" % (label, len(full))
    if near:
        return "wrong_value", "%s: %s" % (label, " | ".join(near))
    return "missing", "%s: %d row(s) stored, %d expected" % (label, len(full), need)


def balance_sums(obs):
    """(tx_hash, op_order, account, token) -> net stored movement. An adapter either lists signed
    `balance_movements` itself, or stores wallet-backend BALANCE rows: CREDIT minus DEBIT."""
    sums = {}
    if "balance_movements" in obs:
        for m in obs["balance_movements"] or []:
            k = (m.get("tx_hash"), m.get("op_order"), m.get("account"), m.get("token"))
            sums[k] = sums.get(k, 0) + int(m["delta"])
        return sums
    for r in obs.get("state_changes") or []:
        if r.get("category") != "BALANCE" or r.get("reason") not in ("CREDIT", "DEBIT"):
            continue
        try:
            amount = int(str((r.get("fields") or {}).get("amount")))
        except ValueError:
            continue
        k = (r.get("tx_hash"), r.get("op_order"), r.get("account"), r.get("token"))
        sums[k] = sums.get(k, 0) + (amount if r["reason"] == "CREDIT" else -amount)
    return sums


def _muxed(exp, obs):
    rows = [m for m in obs.get("balance_movements") or [] if m.get("tx_hash") == exp["tx_hash"]
            and m.get("op_order") == exp["op_order"] and m.get("account") == exp["account"] and m.get("delta", 0) > 0]
    if exp.get("amount") is not None and any(m.get("delta") == exp["amount"] for m in rows):
        # The same account can receive several times in one operation: compare the receipt of this amount.
        rows = [m for m in rows if m.get("delta") == exp["amount"]]
    label = "receipt of %s in tx %s, operation %d" % (exp["account"], exp["tx_hash"][:12], exp["op_order"])
    if rows and not any("to_muxed" in m for m in rows):
        # An observation recorded before its adapter reported muxed destinations says nothing about them.
        return "not_checked", "%s: the observation does not report muxed destinations" % label
    if not rows:
        return "missing", "%s: no stored transfer to it" % label
    got = {m.get("to_muxed") for m in rows}
    # The same account can receive the same amount more than once in one operation (a path payment
    # through itself), and only the event for the final receipt names to_muxed_id. So: one of the
    # receipts must carry the destination the event gives.
    if exp["muxed"] in got:
        return "met", label
    return "wrong_value", "%s: stored muxed destination %s, the event says %s" % (
        label, ", ".join(sorted(str(g) for g in got)), exp["muxed"] or "none (its to_muxed_id is a memo, not an ID)")


def _within(exp, obs):
    """Optional filters split the check by kind: `where` is "participants" or "state_changes" (default
    both), `address_kind` a strkey prefix such as "G" or "C" (default any)."""
    allowed = set(exp["allowed"])
    where = exp.get("where") or ("participants", "state_changes")
    kind = exp.get("address_kind")
    stored = {}
    if "participants" in where:
        for t in obs.get("transactions") or []:
            if t.get("hash") == exp["tx_hash"]:
                for p in t.get("participants") or []:
                    stored.setdefault(p, "the transaction")
        for o in obs.get("operations") or []:
            if o.get("tx_hash") == exp["tx_hash"]:
                for p in o.get("participants") or []:
                    stored.setdefault(p, "operation %s" % o.get("op_order"))
    if "state_changes" in where:
        for r in obs.get("state_changes") or []:
            if r.get("tx_hash") == exp["tx_hash"] and r.get("account"):
                stored.setdefault(r["account"], "a %s/%s state change" % (r.get("category"), r.get("reason")))
    if kind:
        stored = {p: w for p, w in stored.items() if p.startswith(kind)}
    extra = sorted(p for p in stored if p not in allowed)
    label = "addresses recorded for tx %s" % exp["tx_hash"][:12]
    if extra:
        return "wrong_value", "%s: %s recorded, which the transaction's meta does not show it affected%s" % (
            label, ", ".join("%s (on %s)" % (p, stored[p]) for p in extra),
            "" if exp.get("success", True) else " (the transaction failed: only its fee and sequence number applied)")
    return "met", "%s: %d stored, all shown by the meta" % (label, len(stored))


def _native_balance(exp, obs):
    """An account's XLM balance in the indexer's current-state rows after the ledger."""
    if "native_balances" not in obs:
        return "not_checked", "the observation does not report current balances"
    got = {r["account"]: r["balance"] for r in obs["native_balances"]}
    label = "current XLM balance of %s" % exp["account"]
    if exp["balance"] is None:
        if exp["account"] in got:
            return "wrong_value", "%s: a row is stored, the ledger removed the account" % label
        return "met", "%s: no row, the account was removed" % label
    if exp["account"] not in got:
        return "missing", "%s: no row stored, the ledger leaves it at %d" % (label, exp["balance"])
    if got[exp["account"]] != exp["balance"]:
        return "wrong_value", "%s: stored %d, the ledger leaves it at %d" % (label, got[exp["account"]], exp["balance"])
    return "met", "%s: %d" % (label, exp["balance"])


def _at_most(exp, obs):
    """No more stored rows of these reasons for one operation than the ledger gives cause for."""
    rows = [r for r in obs.get("state_changes") or [] if r.get("tx_hash") == exp["tx_hash"]
            and r.get("category") == exp.get("category", "EFFECT") and r.get("reason") in exp["reasons"]
            and (r.get("fields") or {}).get("op_order", r.get("op_order")) == exp["op_order"]]
    label = "%s rows for tx %s, operation %d" % ("/".join(exp["reasons"]), exp["tx_hash"][:12], exp["op_order"])
    if len(rows) > exp["max"]:
        return "wrong_value", "%s: %d stored, the ledger changes %d offer entr%s in it" % (
            label, len(rows), exp["max"], "y" if exp["max"] == 1 else "ies")
    return "met", "%s: %d stored, at most %d" % (label, len(rows), exp["max"])


def _detail(exp, obs):
    """A field in the details of one stored operation: present, and equal to `value` when one is given."""
    ops = [o for o in obs.get("operations") or [] if o.get("tx_hash") == exp["tx_hash"] and o.get("op_order") == exp["op_order"]]
    label = "%s of operation %d in tx %s" % (exp["field"], exp["op_order"], exp["tx_hash"][:12])
    if not ops:
        return "missing", "%s: the operation is not stored" % label
    d = ops[0].get("details") or {}
    if exp["field"] not in d:
        return "missing", "%s: not in the stored details" % label
    if exp.get("value") is not None and d[exp["field"]] != exp["value"]:
        return "wrong_value", "%s: stored %s, the envelope gives %s" % (label, d[exp["field"]], exp["value"])
    return "met", "%s: %s" % (label, d[exp["field"]])


def _check(exp, obs):
    if exp.get("expect") == "operation_detail":
        return _detail(exp, obs)
    if exp.get("expect") == "effect_count_at_most":
        return _at_most(exp, obs)
    if exp.get("expect") == "native_balance":
        return _native_balance(exp, obs)
    if exp.get("expect") == "participants_within":
        return _within(exp, obs)
    if exp.get("expect") == "muxed_destination":
        return _muxed(exp, obs)
    if exp.get("expect") == "balance_net":
        sums = obs.setdefault("_balance_sums", balance_sums(obs))
        k = (exp["tx_hash"], exp["op_order"], exp["account"], exp["token"])
        where = "the fee" if exp["op_order"] == 0 else "operation %d" % exp["op_order"]
        label = "balance of %s in token %s, tx %s, %s" % (exp["account"], exp["token"], exp["tx_hash"][:12], where)
        if k not in sums:
            return "missing", "%s: the ledger changes it by %+d, no BALANCE row is stored" % (label, exp["delta"])
        if sums[k] != exp["delta"]:
            return "wrong_value", "%s: the stored rows add up to %+d, the ledger changes it by %+d" % (label, sums[k], exp["delta"])
        return "met", "%s: %+d" % (label, exp["delta"])
    kind = exp.get("expect")
    if kind == "signer_state_change":
        e = dict(exp, category="SIGNER")
        return _state_change(e, obs)
    if kind == "state_change":
        return _state_change(exp, obs)
    if kind == "no_state_change":
        outcome, detail = _state_change(dict(exp, count=1), obs)
        if outcome == "met":
            return "wrong_value", "a row that must not exist is stored: " + detail
        return "met", "no such row stored"
    if kind in ("participant", "no_participant"):
        txs = [t for t in obs.get("transactions") or [] if exp.get("tx_hash") in (None, t.get("hash"))]
        found = any(exp["account"] in (t.get("participants") or []) for t in txs)
        where = "transaction %s" % exp["tx_hash"] if exp.get("tx_hash") else "any transaction of the ledger"
        if kind == "participant":
            if found:
                return "met", "%s is a participant of %s" % (exp["account"], where)
            return "missing", "%s is not recorded as a participant of %s" % (exp["account"], where)
        if found:
            return "wrong_value", "%s is recorded as a participant of %s and must not be" % (exp["account"], where)
        return "met", "%s is not recorded as a participant" % exp["account"]
    if kind == "transaction":
        if any(t.get("hash") == exp["hash"] for t in obs.get("transactions") or []):
            return "met", "transaction %s stored" % exp["hash"]
        return "missing", "transaction %s is not stored" % exp["hash"]
    return "unknown", "expectation kind %r is not known to this harness version" % kind


def classify(expectations, obs):
    """-> dict(result, mishandled[], dropped[], checks[], unknown_expectations)"""
    mishandled, dropped, checks = [], [], []
    if obs.get("adapter_failure"):
        return {"result": "error", "mishandled": [], "dropped": [], "checks": [],
                "note": "the adapter could not run the indexer: %s" % obs.get("error")}
    if not obs.get("ingested"):
        if obs.get("error"):
            mishandled.append("the indexer raised an error on this ledger and did not ingest it: " + obs["error"])
        else:
            dropped.append("ledger %s is missing: the indexer did not ingest it and raised no error"
                           % obs.get("ledger_seq"))
    for u in obs.get("unreadable") or []:
        mishandled.append("%s.%s holds a value that does not read back as a valid address: stored %s reads as %s (%s)"
                          % (u["table"], u["column"], u["stored_hex"], u["reads_back_as"], u["problem"]))
    unknown = 0
    for exp in expectations or []:
        outcome, detail = _check(exp, obs) if obs.get("ingested") else ("not_checked", "ledger was not ingested")
        checks.append({"expect": exp, "outcome": outcome, "detail": detail})
        if outcome == "wrong_value":
            mishandled.append(detail)
        elif outcome == "missing":
            dropped.append(detail)
        elif outcome == "unknown":
            unknown += 1
    result = "mishandled" if mishandled else "dropped" if dropped else "pass"
    return {"result": result, "mishandled": mishandled, "dropped": dropped, "checks": checks,
            "unknown_expectations": unknown}
