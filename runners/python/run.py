# Python runner: stellar-sdk (py-stellar-base). Reads "id\ttype\tb64", writes "id\tstatus\tpayload".
import sys
import stellar_sdk.xdr as X

by_name = {}
for k in dir(X):
    v = getattr(X, k)
    if isinstance(v, type) and hasattr(v, "from_xdr"):
        by_name.setdefault(k.lower(), v)
        by_name[k] = v
for line in sys.stdin:
    id_, ty, b64 = line.rstrip("\n").split("\t")
    T = by_name.get(ty) or by_name.get(ty.lower())
    if T is None or not hasattr(T, "from_xdr"):
        print(f"{id_}\tnotype\t")
        continue
    try:
        v = T.from_xdr(b64)
        print(f"{id_}\tok\t{v.to_xdr()}")
    except BaseException as e:  # noqa: a decoder must never take the process down
        msg = f"{type(e).__name__}: {e}".replace("\t", " ").replace("\n", " ")[:300]
        print(f"{id_}\terr\t{msg}")
    sys.stdout.flush()
