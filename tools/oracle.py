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
  offer     created | updated | removed                    (seller, offer ID)
  trade     maker                                          (seller, offer ID): a resting offer was
                                                           crossed: it shrank or went in this
                                                           operation, and the operation's result
                                                           lists it as claimed with a nonzero amount
                                                           (which tells it from the source's own
                                                           offer changing)
  claimable created | removed                              (balance ID, asset, claimants)
  pool      created | removed | reserves changed           (pool ID, reserve and share deltas)
  sponsorship created | updated | removed                  (entry kind and identity, sponsor):
                                                           for accounts, trustlines, data entries,
                                                           claimable balances and offers
  signer-sponsorship created | updated | removed           (account, signer key, sponsor)

Each change carries where it happened: the transaction hash, the operation index and type (or
"before" / "after" for the transaction-level changes), so an adapter can tell an operation's own
effect from one stellar-core made around it.

Balances come separately, from balances(): for every transaction, the net change of each
account's XLM balance and each credit-asset trustline balance, per operation, plus one "fee"
bucket per transaction (fee processing, the changes before and after the operations, and
protocol 23's post-apply fee refunds). Pool-share trustlines and balances held by contracts are not
covered.

Deliberately not covered yet: the taking side of a trade, contract balances
and contract storage other than instances.

Everything comes from the bytes through tools/decode.py; no SDK and no indexer is involved.
"""
import argparse
import base64
import json
import re
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
    if t == "OFFER":
        o = data["offer"]
        return ("offer", o["sellerID"]["ed25519"], o["offerID"])
    if t == "CLAIMABLE_BALANCE":
        return ("claimable", balance_id_hex(data["claimableBalance"]["balanceID"]))
    if t == "LIQUIDITY_POOL":
        return ("pool", data["liquidityPool"]["liquidityPoolID"])
    return None


def balance_id_hex(bid):
    """A ClaimableBalanceID as the hex of its XDR: the 4-byte type, then the hash."""
    return "00000000" + bid["v0"]


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
    if t == "OFFER":
        return ("offer", key["offer"]["sellerID"]["ed25519"], key["offer"]["offerID"])
    if t == "CLAIMABLE_BALANCE":
        return ("claimable", balance_id_hex(key["claimableBalance"]["balanceID"]))
    if t == "LIQUIDITY_POOL":
        return ("pool", key["liquidityPool"]["liquidityPoolID"])
    return None


def pairs(changes):
    """Turn a LedgerEntryChanges list into (identity, pre entry or None, post entry or None), with
    whole LedgerEntry values (data plus the extension that names a sponsor)."""
    state, out = {}, []
    for ch in changes:
        t = ch["type"]
        if t == "LEDGER_ENTRY_STATE":
            k = entry_key(ch["state"]["data"])
            if k:
                state[k] = ch["state"]
        elif t == "LEDGER_ENTRY_CREATED":
            k = entry_key(ch["created"]["data"])
            if k:
                out.append((k, None, ch["created"]))
        elif t == "LEDGER_ENTRY_UPDATED":
            k = entry_key(ch["updated"]["data"])
            if k:
                out.append((k, state.get(k), ch["updated"]))
        elif t == "LEDGER_ENTRY_RESTORED":
            # An archived entry made live again (protocol 23+). It existed before, so a restore is
            # never a creation: it counts as the pre-image for any later change in the same list.
            k = entry_key(ch["restored"]["data"])
            if k:
                state.setdefault(k, ch["restored"])
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
        if ta[0] != tb[0]:
            # thresholds[0] is the master key's weight: Horizon's model reports it as a signer change
            # for the account's own key
            if tb[0] == 0:
                yield {"what": "signer", "how": "removed", "account": acct, "signer": acct}
            elif ta[0] == 0:
                yield {"what": "signer", "how": "added", "account": acct, "signer": acct, "weight": tb[0]}
            else:
                yield {"what": "signer", "how": "reweighted", "account": acct, "signer": acct, "weight": tb[0]}
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
        return
    if kind == "offer":
        acct = strkey.account(k[1])
        o = (post or pre)["offer"]
        base = {"what": "offer", "account": acct, "offer_id": k[2], "selling": o["selling"], "buying": o["buying"]}
        if pre is None:
            yield dict(base, how="created", amount=o["amount"])
        elif post is None:
            yield dict(base, how="removed", amount_before=pre["offer"]["amount"])
        elif pre["offer"]["amount"] != post["offer"]["amount"] or pre["offer"]["price"] != post["offer"]["price"]:
            yield dict(base, how="updated", amount_before=pre["offer"]["amount"], amount=post["offer"]["amount"])
        return
    if kind == "claimable":
        cb = (post or pre)["claimableBalance"]
        base = {"what": "claimable", "balance_id": k[1], "asset": cb["asset"], "amount": cb["amount"],
                "claimants": [account_of(c["v0"]["destination"]) for c in cb["claimants"]]}
        if pre is None and post is not None:
            yield dict(base, how="created")
        elif post is None:
            yield dict(base, how="removed")
        return
    if kind == "pool":
        lp = (post or pre)["liquidityPool"]["body"]["constantProduct"]
        base = {"what": "pool", "pool_id": k[1], "assets": [lp["params"]["assetA"], lp["params"]["assetB"]]}
        if pre is None and post is not None:
            yield dict(base, how="created")
        elif post is None:
            yield dict(base, how="removed")
        else:
            a, b = pre["liquidityPool"]["body"]["constantProduct"], lp
            d = {"reserve_a": b["reserveA"] - a["reserveA"], "reserve_b": b["reserveB"] - a["reserveB"],
                 "shares": b["totalPoolShares"] - a["totalPoolShares"]}
            if any(d.values()):
                yield dict(base, how="reserves changed", **d)
        return


SPONSORED_KINDS = {"account": "account", "trustline": "trustline", "data": "data", "claimable": "claimable_balance",
                   "offer": "offer"}


def sponsor_of(entry):
    ext = (entry or {}).get("ext") or {}
    sid = (ext.get("v1") or {}).get("sponsoringID") if ext.get("v") == 1 else None
    return account_of(sid) if sid else None


def signer_sponsors(entry):
    """signer strkey -> sponsor G..., for the signers that have one."""
    if not entry:
        return {}
    acct = entry["data"]["account"]
    v1 = (acct.get("ext") or {}).get("v1") or {}
    v2 = ((v1.get("ext") or {}).get("v2") or {}) if (v1.get("ext") or {}).get("v") == 2 else {}
    ids = v2.get("signerSponsoringIDs") or []
    return {signer_strkey(s["key"]): account_of(sp) for s, sp in zip(acct["signers"], ids) if sp}


def sponsorship(k, pre, post):
    """Sponsorship changes for one entry's pre/post pair (whole LedgerEntry values)."""
    kind = k[0]
    if kind not in SPONSORED_KINDS:
        return
    before, after = sponsor_of(pre), sponsor_of(post)
    if before != after:
        how = "created" if before is None else "removed" if after is None else "updated"
        c = {"what": "sponsorship", "how": how, "entry": SPONSORED_KINDS[kind], "sponsor": after, "former_sponsor": before}
        if kind in ("account", "trustline", "data", "offer"):
            c["account"] = strkey.account(k[1])
        if kind == "trustline":
            c["holding"] = asset_of(json.loads(k[2]))
        if kind == "data":
            c["name"] = k[2]
        if kind == "claimable":
            c["balance_id"] = k[1]
        if kind == "offer":
            c["offer_id"] = k[2]
        yield c
    if kind == "account":
        sa, sb = signer_sponsors(pre), signer_sponsors(post)
        for key in sorted(set(sa) | set(sb)):
            if sa.get(key) != sb.get(key):
                how = "created" if key not in sa else "removed" if key not in sb else "updated"
                yield {"what": "signer-sponsorship", "how": how, "account": strkey.account(k[1]), "signer": key,
                       "sponsor": sb.get(key), "former_sponsor": sa.get(key)}


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


def muxed_destinations(value):
    """CAP-67 transfer and mint events that say who received the asset: one record per event whose data
    names `to_muxed_id`. An integer ID means the destination was a muxed account; a string or bytes
    (a text or hash memo) means it was not, and no muxed address should be derived from it."""
    body = value["v%d" % value["v"]]
    out = []
    for tp in body["txProcessing"]:
        res = tp["result"]
        meta = tp["txApplyProcessing"]
        mv = meta.get("v%d" % meta["v"]) or {}
        for k, op in enumerate(mv.get("operations") or []):
            for ev in op.get("events") or []:
                b = (ev.get("body") or {}).get("v0") or {}
                topics = b.get("topics") or []
                if len(topics) < 3 or topics[0].get("sym") not in ("transfer", "mint"):
                    continue
                to = topics[2 if topics[0]["sym"] == "transfer" else 1].get("address") or {}
                if to.get("type") != "SC_ADDRESS_TYPE_ACCOUNT":
                    continue
                data = b.get("data") or {}
                if data.get("type") != "SCV_MAP":
                    continue
                mid = next((e["val"] for e in data["map"] if e["key"].get("sym") == "to_muxed_id"), None)
                if mid is None:
                    continue
                account = account_of(to["accountId"])
                amt = next((e["val"] for e in data["map"] if e["key"].get("sym") == "amount"), {})
                amount = (amt["i128"]["hi"] << 64) + amt["i128"]["lo"] if amt.get("type") == "SCV_I128" else None
                kind = {"SCV_U64": "id", "SCV_STRING": "text", "SCV_BYTES": "hash"}.get(mid["type"], mid["type"])
                out.append({"tx_hash": res["transactionHash"], "where": k, "account": account, "kind": kind,
                            "amount": amount,
                            "muxed": strkey.muxed(to["accountId"]["ed25519"], mid["u64"]) if kind == "id" else None})
    return out


_STRKEY = re.compile(r"(?<![A-Z2-7])[GC][A-Z2-7]{55}(?![A-Z2-7])")


def _strkey_in(text):
    """G... and C... addresses written out as text (a Stellar Asset Contract's events name the asset as
    CODE:ISSUER), checksum verified."""
    for m in _STRKEY.findall(text):
        raw = base64.b32decode(m + "=" * (-len(m) % 8))
        if strkey.crc16_xmodem(raw[:-2]).to_bytes(2, "little") == raw[-2:]:
            yield m


def _addresses(x, out):
    """Every account or contract address in a decoded value, skipping diagnostic events (which echo
    the invocation's arguments, i.e. the envelope)."""
    if isinstance(x, str):
        if len(x) >= 56:
            out.update(_strkey_in(x))
        return
    if isinstance(x, dict):
        if x.get("type") == "DIAGNOSTIC":
            return
        h = x.get("ed25519")
        if isinstance(h, str) and len(h) == 64:
            out.add(strkey.account(h))
        for key in ("contractId", "contractID"):  # an SCAddress; a contract event's emitter
            h = x.get(key)
            if isinstance(h, str) and len(h) == 64:
                out.add(strkey.contract(h))
        for k, v in x.items():
            if k not in ("diagnosticEvents",):
                _addresses(v, out)
    elif isinstance(x, list):
        for v in x:
            _addresses(v, out)


def _changed_accounts(changes, out):
    for ch in changes or []:
        t = ch["type"]
        if t in ("LEDGER_ENTRY_CREATED", "LEDGER_ENTRY_UPDATED"):
            d = ch[t.split("_")[-1].lower()]["data"]
            if d["type"] == "ACCOUNT":
                out.add(account_of(d["account"]["accountID"]))
        elif t == "LEDGER_ENTRY_REMOVED" and ch["removed"]["type"] == "ACCOUNT":
            out.add(account_of(ch["removed"]["account"]["accountID"]))


_ENCODER = {}


def _envelopes(x):
    if isinstance(x, dict):
        if x.get("type") in ("ENVELOPE_TYPE_TX", "ENVELOPE_TYPE_TX_V0", "ENVELOPE_TYPE_TX_FEE_BUMP") and \
                any(k in x for k in ("v0", "v1", "feeBump")):
            yield x
            return
        for v in x.values():
            yield from _envelopes(v)
    elif isinstance(x, list):
        for v in x:
            yield from _envelopes(v)


def envelopes_by_hash(value, passphrase):
    """{transaction hash: (envelope, the signed transaction body, [source, fee-bump fee source])} for
    every envelope in the ledger's transaction set. The hash is the one stellar-core reports in the
    result: SHA-256 of the signature payload for this network."""
    import hashlib
    from encode import Encoder
    if "e" not in _ENCODER:
        _ENCODER["e"] = Encoder(json.load(open(ROOT / "schema" / "schema.json")))
    enc = _ENCODER["e"]
    network = hashlib.sha256(passphrase.encode()).hexdigest()
    body = value["v%d" % value["v"]]
    out = {}
    for env in _envelopes(body.get("txSet")):
        t = env["type"]
        if t == "ENVELOPE_TYPE_TX_FEE_BUMP":
            fb = env["feeBump"]["tx"]
            tagged = {"type": t, "feeBump": fb}
            inner = fb["innerTx"]["v1"]["tx"]
            who = [fb["feeSource"], inner["sourceAccount"]]
        elif t == "ENVELOPE_TYPE_TX":
            inner = env["v1"]["tx"]
            tagged = {"type": t, "tx": inner}
            who = [inner["sourceAccount"]]
        else:  # a v0 envelope is hashed as the equivalent v1 transaction
            v0 = env["v0"]["tx"]
            src = {"type": "KEY_TYPE_ED25519", "ed25519": v0["sourceAccountEd25519"]}
            tb = v0.get("timeBounds")
            inner = {"sourceAccount": src, "fee": v0["fee"], "seqNum": v0["seqNum"],
                     "cond": {"type": "PRECOND_TIME", "timeBounds": tb} if tb else {"type": "PRECOND_NONE"},
                     "memo": v0["memo"], "operations": v0["operations"], "ext": v0["ext"]}
            tagged = {"type": "ENVELOPE_TYPE_TX", "tx": inner}
            who = [src]
        h = hashlib.sha256(enc.encode("TransactionSignaturePayload", {"networkId": network, "taggedTransaction": tagged})).hexdigest()
        out[h] = (env, inner, who)
    return out


def tx_sources(value, passphrase):
    """{transaction hash: the source account and any fee-bump fee source, as G addresses}. These
    signed the transaction, so no submitter can name them falsely."""
    out = {}
    for h, (_, _, who) in envelopes_by_hash(value, passphrase).items():
        found = set()
        _addresses(who, found)
        out[h] = sorted(found)
    return out


def participants(value, passphrase=None):
    """Who each transaction affected, read from its meta and never from its envelope (the RFP's
    second rule). One record per transaction:
      shown    every account or contract address the transaction's meta carries: ledger entries
               created, changed or removed (with their keys, so a token holder's balance entry or a
               nonce entry names its address), and contract and system events. For a failed
               transaction only the fee processing and the changes around the operations count:
               its operations applied nothing.
               With a network passphrase, also the transaction's source and fee-bump fee source from
               its envelope: they signed it (a fee bump whose inner transaction fails before it
               applies can leave the inner source's entry untouched); and, for a successful
               transaction, each operation's own source, which signed for its operation.
      changed  the accounts whose account entry the transaction created, changed or removed, the
               source and any fee-bump fee source among them (fee and sequence number).
    An indexer's stored participants should include `changed` and stay within `shown`. An address
    only the envelope names (a payment destination of a failed transaction, an authorization entry
    no require_auth matched, a declared deploy that never ran) is outside `shown`."""
    body = value["v%d" % value["v"]]
    envs = envelopes_by_hash(value, passphrase) if passphrase else {}
    signers = tx_sources(value, passphrase) if passphrase else {}
    out = []
    for tp in body["txProcessing"]:
        res = tp["result"]
        ok = res["result"]["result"]["code"] in SUCCESS
        meta = tp["txApplyProcessing"]
        mv = meta.get("v%d" % meta["v"]) or {}
        if "v%d" % meta["v"] not in meta:
            mv = {"operations": meta.get("operations") or []}
        shown, changed = set(), set()
        fee_lists = [tp.get("feeProcessing"), tp.get("postTxApplyFeeProcessing"), mv.get("txChanges"),
                     mv.get("txChangesBefore"), mv.get("txChangesAfter")]
        for lst in fee_lists:
            _addresses(lst, shown)
            _changed_accounts(lst, changed)
        _addresses(mv.get("events"), shown)  # protocol 23+: the transaction's fee events
        if ok:
            _addresses({k: v for k, v in mv.items() if k not in ("txChanges", "txChangesBefore", "txChangesAfter", "events")}, shown)
            for op in mv.get("operations") or []:
                _changed_accounts(op.get("changes"), changed)
        shown.update(signers.get(res["transactionHash"], []))
        if ok and res["transactionHash"] in envs:
            # An operation of a successful transaction ran with its source's authorization, so that
            # source signed. In a failed transaction it may not have: that can be why it failed.
            _addresses([op.get("sourceAccount") for op in envs[res["transactionHash"]][1]["operations"]], shown)
        out.append({"tx_hash": res["transactionHash"], "success": ok, "shown": sorted(shown | changed),
                    "changed": sorted(changed)})
    return out


def final_native_balances(value):
    """{account: (balance before the ledger or None if it created the account, balance after it or
    None if it removed the account)} for every account whose entry the ledger created, changed or
    removed. stellar-core charges every transaction's fee
    first, then applies the transactions in order, then the post-apply fee refunds, then the upgrades,
    so the last change in that order is the account's state when the ledger closes."""
    body = value["v%d" % value["v"]]
    txs = body["txProcessing"]
    order = [tp.get("feeProcessing") for tp in txs]
    for tp in txs:
        meta = tp["txApplyProcessing"]
        mv = meta.get("v%d" % meta["v"]) or {}
        if "v%d" % meta["v"] not in meta:
            mv = {"operations": meta.get("operations") or []}
        order += [mv.get("txChanges"), mv.get("txChangesBefore")] + [op.get("changes") for op in mv.get("operations") or []] + \
                 [mv.get("txChangesAfter")]
    order += [tp.get("postTxApplyFeeProcessing") for tp in txs]
    order += [u.get("changes") for u in body.get("upgradesProcessing") or []]
    before, after = {}, {}
    for changes in order:
        for ch in changes or []:
            t = ch["type"]
            if t == "LEDGER_ENTRY_STATE" and ch["state"]["data"]["type"] == "ACCOUNT":
                before.setdefault(account_of(ch["state"]["data"]["account"]["accountID"]), ch["state"]["data"]["account"]["balance"])
            elif t in ("LEDGER_ENTRY_CREATED", "LEDGER_ENTRY_UPDATED", "LEDGER_ENTRY_RESTORED"):
                d = ch[t.split("_")[-1].lower()]["data"]
                if d["type"] == "ACCOUNT":
                    a = account_of(d["account"]["accountID"])
                    before.setdefault(a, None if t == "LEDGER_ENTRY_CREATED" else d["account"]["balance"])
                    after[a] = d["account"]["balance"]
            elif t == "LEDGER_ENTRY_REMOVED" and ch["removed"]["type"] == "ACCOUNT":
                after[account_of(ch["removed"]["account"]["accountID"])] = None
    return {a: (before.get(a), b) for a, b in after.items()}


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
            found = []
            for k, pre, post in pairs(chs):
                found += list(diff(k, pre and pre["data"], post and post["data"]))
                found += list(sponsorship(k, pre, post))
            if isinstance(where, int):
                found += list(trades(found, chs, claimed_offers(op_results[where] if where < len(op_results) else {})))
            for c in found:
                c = dict(c, **ctx_base)
                c["where"] = where
                c["op_type"] = op_types[where] if isinstance(where, int) and where < len(op_types) else None
                out.append(c)
    return out


def claimed_offers(op_result):
    """(seller ed25519 hex, offer ID) for every order-book offer an operation's result lists as claimed."""
    out = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("offersClaimed", "offers") and isinstance(v, list):
                    for atom in v:
                        ob = atom.get("orderBook") or atom.get("v0") or {}
                        seller = ob.get("sellerID", {}).get("ed25519") if "sellerID" in ob else ob.get("sellerEd25519")
                        if seller and "offerID" in ob and (ob.get("amountSold") or ob.get("amountBought")):
                            out.add((seller, ob["offerID"]))
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(op_result)
    return out


def trades(found, chs, claimed):
    """A resting offer crossed in this operation: the ledger shows it shrink or go, and the result
    lists it as claimed with a nonzero amount. (The seller's net balance is no test: a maker with
    offers on both sides of one path can end flat. An offer its owner changes is never claimed.)"""
    for c in found:
        if c["what"] != "offer" or c["how"] == "created":
            continue
        if c["how"] == "updated" and c["amount"] >= c["amount_before"]:
            continue
        if (bytes_of(c["account"]), c["offer_id"]) in claimed:
            yield {"what": "trade", "how": "maker", "account": c["account"], "offer_id": c["offer_id"]}


def bytes_of(account):
    """G... -> the ed25519 hex the ledger stores."""
    return base64.b32decode(account + "=" * (-len(account) % 8))[1:33].hex()


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
