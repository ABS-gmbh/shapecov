#!/usr/bin/env python3
"""Derive `expected.indexer` for corpus entries from their decoded ledgers.

  indexer_expect.py ENTRY_ID [ENTRY_ID ...] [--write]

Prints the expectations each entry gets, and with --write stores them in corpus/manifest.json.
Everything comes from the entry's bytes and its network passphrase; nothing comes from an indexer.

Rules (one per corpus pattern that has one):

  soroban-created-trustline  For every trustline a contract call created (LEDGER_ENTRY_CREATED of a
                             TRUSTLINE in an INVOKE_HOST_FUNCTION operation's changes, pool shares
                             excepted): a TRUSTLINE/ADD state change and a BALANCE_AUTHORIZATION state
                             change for the trustline's account, whose token is the asset's Stellar
                             Asset Contract ID (sha256 of the HashIDPreimage CONTRACT_ID for the asset
                             under the entry's network passphrase, CAP-46).

  soroban-op-muxed-source    For every transaction with a contract-invocation operation that runs as a
                             muxed account (its own source, or the transaction's when it has none): the
                             base account (the muxed account's ed25519 key as a G... address) is a
                             participant of that transaction, identified by its hash (sha256 of the
                             TransactionSignaturePayload under the entry's network passphrase).
"""
import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import strkey  # noqa: E402
from decode import Decoder  # noqa: E402
from encode import Encoder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def tx_list(body):
    """Envelopes in apply order are not needed here; we only pair meta with operation types."""
    out = []
    ts = body["txSet"]
    phases = ts["v1TxSet"]["phases"] if "v1TxSet" in ts else [{"v0Components": [{"txsMaybeDiscountedFee": {"txs": ts["txs"]}}]}]
    for ph in phases:
        for c in ph.get("v0Components") or []:
            out += c["txsMaybeDiscountedFee"]["txs"]
        for stage in (ph.get("parallelTxsComponent") or {}).get("executionStages") or []:
            for cluster in stage:
                out += cluster
    return out


def created_trustlines_by_contract(value):
    """Yield (path, TrustLineEntry) for trustlines created inside INVOKE_HOST_FUNCTION operations."""
    body = value["v%d" % value["v"]]
    for i, tp in enumerate(body["txProcessing"]):
        res = tp["result"]["result"]["result"]
        meta = tp["txApplyProcessing"]
        mv = meta["v%d" % meta["v"]]
        for k, op in enumerate(mv.get("operations") or []):
            kind = (res.get("results") or [{}])[k].get("tr", {}).get("type") if res.get("results") else None
            if kind != "INVOKE_HOST_FUNCTION":
                continue
            for j, ch in enumerate(op["changes"]):
                if ch["type"] != "LEDGER_ENTRY_CREATED":
                    continue
                data = ch["created"]["data"]
                if data["type"] == "TRUSTLINE" and data["trustLine"]["asset"]["type"] != "ASSET_TYPE_POOL_SHARE":
                    path = "v%d.txProcessing[%d].txApplyProcessing.v%d.operations[%d].changes[%d].created.data" % (
                        value["v"], i, meta["v"], k, j)
                    yield path, data["trustLine"]


def muxed_soroban_sources(value):
    """Yield (path, envelope, ed25519 hex) for contract invocations that run as a muxed account."""
    body = value["v%d" % value["v"]]
    for k, env in enumerate(tx_list(body)):
        if env.get("type") != "ENVELOPE_TYPE_TX":
            continue
        tx = env["v1"]["tx"]
        for j, op in enumerate(tx["operations"]):
            if op["body"]["type"] != "INVOKE_HOST_FUNCTION":
                continue
            src = op.get("sourceAccount") or tx["sourceAccount"]
            if "med25519" in src:
                yield "tx %d, operation %d" % (k, j), env, src["med25519"]["ed25519"]


def tx_hash(enc, env, passphrase):
    payload = enc.encode("TransactionSignaturePayload", {
        "networkId": hashlib.sha256(passphrase.encode()).hexdigest(),
        "taggedTransaction": {"type": "ENVELOPE_TYPE_TX", "tx": env["v1"]["tx"]}})
    return hashlib.sha256(payload).hexdigest()


def sac_contract_id(enc, asset, passphrase):
    preimage = {"type": "ENVELOPE_TYPE_CONTRACT_ID", "contractID": {
        "networkID": hashlib.sha256(passphrase.encode()).hexdigest(),
        "contractIDPreimage": {"type": "CONTRACT_ID_PREIMAGE_FROM_ASSET", "fromAsset": asset}}}
    return strkey.contract(hashlib.sha256(enc.encode("HashIDPreimage", preimage)).hexdigest())


def expectations(entry, dec, enc):
    raw = base64.b64decode((ROOT / "corpus" / entry["file"]).read_text())
    value = dec.decode("LedgerCloseMeta", raw)
    passphrase = entry["source"]["network_passphrase"]
    out = []
    for path, tl in created_trustlines_by_contract(value):
        account = strkey.account(tl["accountID"]["ed25519"])
        token = sac_contract_id(enc, tl["asset"], passphrase)  # TrustLineAsset credit arms match Asset
        for cat, reason in (("TRUSTLINE", "ADD"), ("BALANCE_AUTHORIZATION", None)):
            e = {"expect": "state_change", "category": cat, "account": account, "token": token,
                 "derived_from": path}
            if reason:
                e["reason"] = reason
            out.append(e)
    for where, env, key in muxed_soroban_sources(value):
        out.append({"expect": "participant", "account": strkey.account(key),
                    "tx_hash": tx_hash(enc, env, passphrase),
                    "note": "base account of the muxed source (%s)" % where})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entries", nargs="+")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    schema = json.load(open(ROOT / "schema/schema.json"))
    dec, enc = Decoder(schema), Encoder(schema)
    path = ROOT / "corpus" / "manifest.json"
    manifest = json.load(open(path))
    by_id = {e["id"]: e for e in manifest["entries"]}
    for eid in a.entries:
        e = by_id[eid]
        exp = expectations(e, dec, enc)
        print(eid, json.dumps(exp, indent=1))
        if a.write and exp:
            e.setdefault("expected", {})["indexer"] = exp
    if a.write:
        path.write_text(json.dumps(manifest, indent=1) + "\n")


if __name__ == "__main__":
    main()
