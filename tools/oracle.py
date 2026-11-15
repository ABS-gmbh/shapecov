#!/usr/bin/env python3
"""Indexer-neutral oracle: what changed in ledger state, read from a LedgerCloseMeta.

  oracle.py ENTRY_ID [--json]        print the changes the oracle derives for a corpus entry

For every transaction in the ledger, this walks the ledger-entry changes stellar-core recorded
(per operation, and before and after the operations) and reports what changed, in terms any
indexer can be checked against:

  account   created | removed                              (account)
  signer    added | removed | reweighted                   (account, signer key)
  threshold changed, one per level: low, medium, high      (account)
  flags     set | cleared                                  (account, flag names)
  home      set | cleared | changed                        (account)
  data      added | removed | changed                      (account, name)
  trustline added | removed | limit changed                (account, asset or pool)
  trustauth set | cleared                                  (account, asset or pool, flag names)
  contract  created                                        (contract)

Each change carries where it happened: the transaction hash, the operation index and type (or
"before" / "after" for the transaction-level changes), so an adapter can tell an operation's own
effect from one stellar-core made around it.

Balances come separately, from balances(): for every transaction, the net change of each
account's XLM balance and each credit-asset trustline balance, per operation, plus one "fee"
bucket per transaction (fee processing, the changes before and after the operations, and
protocol 23's post-apply fee refunds). Pool-share trustlines and balances held by contracts are not
covered.

Deliberately not covered yet: the master key's weight, offers, claimable balances, liquidity pool
reserves, contract balances and contract storage other than instances.

Everything comes from the bytes through tools/decode.py; no SDK and no indexer is involved.
"""
import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import strkey  # noqa: E402
from decode import Decoder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

ACCOUNT_FLAGS = {1: "auth_required", 2: "auth_revocable", 4: "auth_immutable", 8: "auth_clawback_enabled"}
TRUSTLINE_FLAGS = {1: "authorized", 2: "authorized_to_maintain_liabilities", 4: "clawback_enabled"}
SUCCESS = {"txSUCCESS", "txFEE_BUMP_INNER_SUCCESS"}


def signer_strkey(key):
    t = key["type"]
    if t == "SIGNER_KEY_TYPE_ED25519":
        return strkey.account(key["ed25519"])
    if t == "SIGNER_KEY_TYPE_PRE_AUTH_TX":
        return strkey.encode("pre_auth_tx", bytes.fromhex(key["preAuthTx"]))
    if t == "SIGNER_KEY_TYPE_HASH_X":
        return strkey.encode("hash_x", bytes.fromhex(key["hashX"]))
    if t == "SIGNER_KEY_TYPE_ED25519_SIGNED_PAYLOAD":
        p = key["ed25519SignedPayload"]
        return strkey.signed_payload(p["ed25519"], p["payload"])
    raise ValueError("unknown signer key type %s" % t)


def account_of(pk):
    return strkey.account(pk["ed25519"])


def entry_key(data):
    """A hashable identity for a ledger entry's data, or None for kinds the oracle ignores."""
    t = data["type"]
    if t == "ACCOUNT":
        return ("account", data["account"]["accountID"]["ed25519"])
    if t == "TRUSTLINE":
        tl = data["trustLine"]
        return ("trustline", tl["accountID"]["ed25519"], json.dumps(tl["asset"], sort_keys=True))
    if t == "DATA":
        d = data["data"]
        name = d["dataName"] if isinstance(d["dataName"], str) else json.dumps(d["dataName"])
        return ("data", d["accountID"]["ed25519"], name)
    if t == "CONTRACT_DATA":
        cd = data["contractData"]
        if cd["key"]["type"] == "SCV_LEDGER_KEY_CONTRACT_INSTANCE" and cd["contract"]["type"] == "SC_ADDRESS_TYPE_CONTRACT":
            return ("instance", cd["contract"]["contractId"])
    return None


def ledger_key_identity(key):
    """The same identity for a LedgerKey (what a REMOVED change carries)."""
    t = key["type"]
    if t == "ACCOUNT":
        return ("account", key["account"]["accountID"]["ed25519"])
    if t == "TRUSTLINE":
        tl = key["trustLine"]
        return ("trustline", tl["accountID"]["ed25519"], json.dumps(tl["asset"], sort_keys=True))
    if t == "DATA":
        d = key["data"]
        name = d["dataName"] if isinstance(d["dataName"], str) else json.dumps(d["dataName"])
        return ("data", d["accountID"]["ed25519"], name)
    if t == "CONTRACT_DATA":
        cd = key["contractData"]
        if cd["key"]["type"] == "SCV_LEDGER_KEY_CONTRACT_INSTANCE" and cd["contract"]["type"] == "SC_ADDRESS_TYPE_CONTRACT":
            return ("instance", cd["contract"]["contractId"])
    return None


def pairs(changes):
    """Turn a LedgerEntryChanges list into (identity, pre data or None, post data or None)."""
    state, out = {}, []
    for ch in changes:
        t = ch["type"]
        if t == "LEDGER_ENTRY_STATE":
            k = entry_key(ch["state"]["data"])
            if k:
                state[k] = ch["state"]["data"]
        elif t == "LEDGER_ENTRY_CREATED":
            k = entry_key(ch["created"]["data"])
            if k:
                out.append((k, None, ch["created"]["data"]))
        elif t == "LEDGER_ENTRY_UPDATED":
            k = entry_key(ch["updated"]["data"])
            if k:
                out.append((k, state.get(k), ch["updated"]["data"]))
        elif t == "LEDGER_ENTRY_RESTORED":
            # An archived entry made live again (protocol 23+). It existed before, so a restore is
            # never a creation: it counts as the pre-image for any later change in the same list.
            k = entry_key(ch["restored"]["data"])
            if k:
                state.setdefault(k, ch["restored"]["data"])
        elif t == "LEDGER_ENTRY_REMOVED":
            k = ledger_key_identity(ch["removed"])
            if k:
                out.append((k, state.get(k), None))
    return out


def flag_names(bits, table):
    return sorted(name for bit, name in table.items() if bits & bit)


def asset_of(tl_asset):
    """('asset', asset dict) for a credit trustline, ('pool', pool id hex) for a pool share."""
    if tl_asset["type"] == "ASSET_TYPE_POOL_SHARE":
        return ("pool", tl_asset["liquidityPoolID"])
    return ("asset", tl_asset)


def diff(k, pre, post):
    """Yield change dicts (without context) for one entry's pre/post pair."""
    kind = k[0]
    if kind == "account":
        acct = strkey.account(k[1])
        if pre is None and post is not None:
            yield {"what": "account", "how": "created", "account": acct}
            return
        if post is None:
            yield {"what": "account", "how": "removed", "account": acct}
            return
        a, b = pre["account"], post["account"]
        sa = {signer_strkey(s["key"]): s["weight"] for s in a["signers"]}
        sb = {signer_strkey(s["key"]): s["weight"] for s in b["signers"]}
        for key in sorted(set(sa) | set(sb)):
            if key not in sa:
                yield {"what": "signer", "how": "added", "account": acct, "signer": key, "weight": sb[key]}
            elif key not in sb:
                yield {"what": "signer", "how": "removed", "account": acct, "signer": key}
            elif sa[key] != sb[key]:
                yield {"what": "signer", "how": "reweighted", "account": acct, "signer": key, "weight": sb[key]}
        ta, tb = bytes.fromhex(a["thresholds"]), bytes.fromhex(b["thresholds"])
        for i, level in ((1, "low"), (2, "medium"), (3, "high")):
            if ta[i] != tb[i]:
                yield {"what": "threshold", "how": "changed", "account": acct, "level": level, "old": ta[i], "new": tb[i]}
        set_bits, clear_bits = b["flags"] & ~a["flags"], a["flags"] & ~b["flags"]
        if set_bits:
            yield {"what": "flags", "how": "set", "account": acct, "flags": flag_names(set_bits, ACCOUNT_FLAGS)}
        if clear_bits:
            yield {"what": "flags", "how": "cleared", "account": acct, "flags": flag_names(clear_bits, ACCOUNT_FLAGS)}
        ha, hb = a["homeDomain"], b["homeDomain"]
        if ha != hb:
            how = "set" if not ha else "cleared" if not hb else "changed"
            yield {"what": "home", "how": how, "account": acct}
        return
    if kind == "data":
        acct = strkey.account(k[1])
        how = "added" if pre is None else "removed" if post is None else (
            "changed" if pre["data"]["dataValue"] != post["data"]["dataValue"] else None)
        if how:
            yield {"what": "data", "how": how, "account": acct, "name": k[2]}
        return
    if kind == "trustline":
        acct = strkey.account(k[1])
        tl_asset = json.loads(k[2])
        holding = asset_of(tl_asset)
        if pre is None and post is not None:
            yield {"what": "trustline", "how": "added", "account": acct, "holding": holding}
            yield {"what": "trustauth", "how": "set", "account": acct, "holding": holding,
                   "flags": flag_names(post["trustLine"]["flags"], TRUSTLINE_FLAGS), "new_trustline": True}
            return
        if post is None:
            yield {"what": "trustline", "how": "removed", "account": acct, "holding": holding}
            return
        a, b = pre["trustLine"], post["trustLine"]
        if a["limit"] != b["limit"]:
            yield {"what": "trustline", "how": "limit changed", "account": acct, "holding": holding}
        set_bits, clear_bits = b["flags"] & ~a["flags"], a["flags"] & ~b["flags"]
        if set_bits:
            yield {"what": "trustauth", "how": "set", "account": acct, "holding": holding,
                   "flags": flag_names(set_bits, TRUSTLINE_FLAGS)}
        if clear_bits:
            yield {"what": "trustauth", "how": "cleared", "account": acct, "holding": holding,
                   "flags": flag_names(clear_bits, TRUSTLINE_FLAGS)}
        return
    if kind == "instance" and pre is None and post is not None:
        yield {"what": "contract", "how": "created", "contract": strkey.contract(k[1])}


def _balance_holdings(changes):
    """(account ed25519 hex, holding) -> net balance change in stroops, for one change list.
    holding is "native" or the credit asset dict as JSON; pool shares are left out."""
    state, delta = {}, {}

    def key_and_balance(data):
        if data["type"] == "ACCOUNT":
            return (data["account"]["accountID"]["ed25519"], "native"), data["account"]["balance"]
        if data["type"] == "TRUSTLINE":
            tl = data["trustLine"]
            if tl["asset"]["type"] == "ASSET_TYPE_POOL_SHARE":
                return None, 0
            return (tl["accountID"]["ed25519"], json.dumps(tl["asset"], sort_keys=True)), tl["balance"]
        return None, 0

    for ch in changes:
        t = ch["type"]
        if t in ("LEDGER_ENTRY_STATE", "LEDGER_ENTRY_RESTORED"):
            d = ch["state"] if t == "LEDGER_ENTRY_STATE" else ch["restored"]
            k, bal = key_and_balance(d["data"])
            if k:
                state[k] = bal
        elif t in ("LEDGER_ENTRY_CREATED", "LEDGER_ENTRY_UPDATED"):
            d = ch["created"] if t == "LEDGER_ENTRY_CREATED" else ch["updated"]
            k, bal = key_and_balance(d["data"])
            if k:
                before = state.get(k, 0) if t == "LEDGER_ENTRY_UPDATED" else 0
                delta[k] = delta.get(k, 0) + bal - before
                state[k] = bal
        elif t == "LEDGER_ENTRY_REMOVED":
            r = ch["removed"]
            if r["type"] == "ACCOUNT":
                k = (r["account"]["accountID"]["ed25519"], "native")
            elif r["type"] == "TRUSTLINE" and r["trustLine"]["asset"]["type"] != "ASSET_TYPE_POOL_SHARE":
                k = (r["trustLine"]["accountID"]["ed25519"], json.dumps(r["trustLine"]["asset"], sort_keys=True))
            else:
                continue
            delta[k] = delta.get(k, 0) - state.get(k, 0)
            state[k] = 0
    return delta


def balances(value):
    """Net balance changes in a decoded LedgerCloseMeta: one record per (transaction, bucket,
    account, holding) with a nonzero change. bucket is the operation index or "fee"."""
    body = value["v%d" % value["v"]]
    out = []
    for i, tp in enumerate(body["txProcessing"]):
        res = tp["result"]
        r = res["result"]["result"]
        code = r["code"]
        inner = r.get("innerResultPair", {}).get("result", {}).get("result") if code.startswith("txFEE_BUMP") else None
        op_types = [(o.get("tr") or {}).get("type") for o in ((inner or r).get("results") or [])]
        meta = tp["txApplyProcessing"]
        mv = meta["v%d" % meta["v"]] if "v%d" % meta["v"] in meta else meta
        fee_changes = list(tp.get("feeProcessing") or []) + list(mv.get("txChanges") or []) + \
            list(mv.get("txChangesBefore") or []) + list(mv.get("txChangesAfter") or []) + \
            list(tp.get("postTxApplyFeeProcessing") or [])
        buckets = [("fee", fee_changes)] + [(k, op.get("changes") or []) for k, op in enumerate(mv.get("operations") or [])]
        for where, chs in buckets:
            # Fee buckets mix separate change lists; each list is netted on its own, then summed.
            if where == "fee":
                parts = [tp.get("feeProcessing") or [], mv.get("txChanges") or [], mv.get("txChangesBefore") or [],
                         mv.get("txChangesAfter") or [], tp.get("postTxApplyFeeProcessing") or []]
                total = {}
                for part in parts:
                    for k, d in _balance_holdings(part).items():
                        total[k] = total.get(k, 0) + d
            else:
                total = _balance_holdings(chs)
            for (acct, holding), d in sorted(total.items()):
                if d:
                    out.append({"tx": i, "tx_hash": res["transactionHash"], "success": code in SUCCESS,
                                "where": where, "op_type": op_types[where] if isinstance(where, int) and where < len(op_types) else None,
                                "account": strkey.account(acct),
                                "holding": "native" if holding == "native" else json.loads(holding), "delta": d})
    return out


def tx_envelopes(body):
    """Envelopes by transaction hash are not needed; operation types come from the results."""
    return None


def changes(value):
    """Every change in a decoded LedgerCloseMeta, with its context."""
    body = value["v%d" % value["v"]]
    out = []
    for i, tp in enumerate(body["txProcessing"]):
        res = tp["result"]
        tx_hash = res["transactionHash"]
        r = res["result"]["result"]
        code = r["code"]
        inner = r.get("innerResultPair", {}).get("result", {}).get("result") if code.startswith("txFEE_BUMP") else None
        ok = code in SUCCESS
        op_results = (inner or r).get("results") or []
        op_types = [(o.get("tr") or {}).get("type") for o in op_results]
        meta = tp["txApplyProcessing"]
        mv = meta["v%d" % meta["v"]] if "v%d" % meta["v"] in meta else meta
        ctx_base = {"tx": i, "tx_hash": tx_hash, "success": ok}
        groups = [("before", mv.get("txChangesBefore") or [])]
        for k, op in enumerate(mv.get("operations") or []):
            groups.append((k, op.get("changes") or []))
        groups.append(("after", mv.get("txChangesAfter") or []))
        if "txChanges" in mv:  # TransactionMeta v1
            groups.insert(0, ("before", mv["txChanges"]))
        for where, chs in groups:
            for k, pre, post in pairs(chs):
                for c in diff(k, pre, post):
                    c = dict(c, **ctx_base)
                    c["where"] = where
                    c["op_type"] = op_types[where] if isinstance(where, int) and where < len(op_types) else None
                    out.append(c)
    return out


def load_entry(entry_id):
    manifest = json.load(open(ROOT / "corpus" / "manifest.json"))
    e = next(e for e in manifest["entries"] if e["id"] == entry_id)
    if e["xdr_type"] != "LedgerCloseMeta":
        raise SystemExit("%s is a %s, not a LedgerCloseMeta" % (entry_id, e["xdr_type"]))
    schema = json.load(open(ROOT / "schema" / "schema.json"))
    raw = base64.b64decode((ROOT / "corpus" / e["file"]).read_text())
    return e, Decoder(schema).decode("LedgerCloseMeta", raw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entry")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    _, value = load_entry(a.entry)
    cs = changes(value)
    if a.json:
        print(json.dumps(cs, indent=1))
        return
    for c in cs:
        where = "op %d %s" % (c["where"], c["op_type"]) if isinstance(c["where"], int) else c["where"]
        rest = {k: v for k, v in c.items() if k not in ("what", "how", "tx", "tx_hash", "success", "where", "op_type")}
        print("tx %-3d %-28s %-9s %-13s %s" % (c["tx"], where, c["what"], c["how"], json.dumps(rest)[:140]))
    print("%d change(s)" % len(cs))


if __name__ == "__main__":
    main()
