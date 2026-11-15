"""Check "pool_pair_accepted" for py-stellar-base. Same contract as order.mjs.

  python order.py pool_pair_accepted <XDR type> <value as base64> <expected pool ID hex>

Prints one JSON line. "map_keys_host_order" has no equivalent here: py-stellar-base builds maps
from the entries it is given and does not sort them, so there is nothing to compare.
"""
import json
import sys

import stellar_sdk
from stellar_sdk import Asset, LiquidityPoolAsset, xdr

check, typ, b64, expected = sys.argv[1:5]
out = {"sdk": f"stellar-sdk {stellar_sdk.__version__}", "check": check}
value = getattr(xdr, typ).from_xdr(b64)
if check == "pool_pair_accepted":
    try:
        lp = LiquidityPoolAsset(Asset.from_xdr_object(value.asset_a), Asset.from_xdr_object(value.asset_b),
                                value.fee.int32)
        out["pool_id"] = lp.liquidity_pool_id
        out["result"] = "pass" if lp.liquidity_pool_id == expected else "mishandled"
        if lp.liquidity_pool_id != expected:
            out["detail"] = f"pool ID {lp.liquidity_pool_id}, the ledger records {expected}"
    except Exception as e:  # noqa: BLE001
        out["result"] = "mishandled"
        out["detail"] = f"rejected an asset pair the network accepted: {e}"
else:
    out["result"] = "not_applicable"
print(json.dumps(out))
