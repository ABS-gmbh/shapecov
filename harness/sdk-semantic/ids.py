"""Check "ids_exact" for py-stellar-base. Same contract as ids.mjs.

  python ids.py <entry .xdr.b64> <spec.json>
"""
import json
import sys
from decimal import Decimal
from importlib.metadata import version

from stellar_sdk import Asset, ManageSellOffer, MuxedAccount, Network, TransactionBuilder  # noqa: F401

spec = json.load(open(sys.argv[2]))
b64 = open(sys.argv[1]).read().strip()
out = {"sdk": f"stellar-sdk {version('stellar-sdk')}", "check": "ids_exact", "wrong": [], "accepted": []}
G = "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ"
try:
    tx = TransactionBuilder.from_xdr(b64, Network.TESTNET_NETWORK_PASSPHRASE).transaction
    got = {
        "offer_id": str(tx.operations[0].offer_id),
        "source": tx.source.account_muxed,
        "source_muxed_id": str(tx.source.account_muxed_id),
        "destination": tx.operations[1].destination.account_muxed,
        "destination_muxed_id": str(tx.operations[1].destination.account_muxed_id),
        "memo_id": str(tx.memo.memo_id),
        "amount_stroops": str(int(Decimal(tx.operations[1].amount) * 10**7)),
    }
    for k, v in got.items():
        if spec["ids"][k] != v:
            out["wrong"].append(f"{k}: decoded {v}, expected {spec['ids'][k]}")
except Exception as e:  # noqa: BLE001
    out["wrong"].append(f"decode failed: {type(e).__name__}: {e}")


def as_py(c):
    """Python's builders take integers; a decimal string is given as the integer it denotes."""
    v = c["input"]
    if isinstance(v, str) and v.lstrip("-").isdigit() and not (len(v) > 1 and v.startswith("0")):
        return int(v)
    return v


for kind, cases in spec["must_reject"].items():
    for c in cases:
        v = as_py(c)
        try:
            if kind == "offer_id":
                op = ManageSellOffer(Asset.native(), Asset("USD", G), "1", "1", offer_id=v)
                wire = op.to_xdr_object().to_xdr()          # through real bytes, not just objects
                enc = ManageSellOffer.from_xdr_object(type(op.to_xdr_object()).from_xdr(wire)).offer_id
            else:
                m = MuxedAccount(G, v)
                enc = MuxedAccount.from_account(m.account_muxed).account_muxed_id
            if isinstance(v, int) and 0 <= v < 2**64 and enc == v:
                continue  # a canonical integer in range is fine in an integer-typed API
            out["accepted"].append(f"{kind} {v!r} ({c['why']}) accepted, encodes {enc}")
        except Exception:  # noqa: BLE001
            pass  # rejected, as required
out["result"] = "mishandled" if out["wrong"] or out["accepted"] else "pass"
print(json.dumps(out))
