# Python runner for stellar-xdr (lightsail-network/py-stellar-xdr), the package that replaces
# stellar_sdk.xdr in py-stellar-base's next major release (StellarCN/py-stellar-base#1264).
# Reads "id\ttype\tpayload", writes "id\tstatus\tpayload", like the other runners.
#
#   run.py            payload = base64 XDR -> ok payload = the value re-encoded as base64 XDR
#   run.py tojson     payload = base64 XDR -> ok payload = SEP-51 JSON of the value (one line)
#   run.py fromjson   payload = SEP-51 JSON -> ok payload = base64 XDR
import json
import sys

import stellar_xdr as X

MODE = sys.argv[1] if len(sys.argv) > 1 else "xdr"
by_name = {}
for k in dir(X):
    v = getattr(X, k)
    if isinstance(v, type) and hasattr(v, "from_xdr_base64"):
        by_name[k.lower()] = v

for line in sys.stdin:
    id_, ty, payload = line.rstrip("\n").split("\t", 2)
    T = by_name.get(ty.lower())
    if T is None:
        print(f"{id_}\tnotype\t", flush=True)
        continue
    try:
        if MODE == "tojson":
            out = json.dumps(T.from_xdr_base64(payload).to_json_value(), separators=(",", ":"), sort_keys=True)
        elif MODE == "fromjson":
            out = T.from_json_value(json.loads(payload)).to_xdr_base64()
        else:
            out = T.from_xdr_base64(payload).to_xdr_base64()
        print(f"{id_}\tok\t{out}", flush=True)
    except RecursionError as e:  # report it; a decoder must never take the process down
        print(f"{id_}\terr\tRecursionError: {str(e)[:200]}", flush=True)
    except BaseException as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}".replace("\t", " ").replace("\n", " ")[:300]
        print(f"{id_}\terr\t{msg}", flush=True)
