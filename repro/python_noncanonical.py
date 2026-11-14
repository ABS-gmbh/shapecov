# Lead P1/P2: py-stellar-base accepts XDR that RFC 4506 and rs-stellar-xdr reject.
import base64
import stellar_sdk
from stellar_sdk import xdr

print("stellar-sdk", stellar_sdk.__version__)

# Memo MEMO_TEXT "a": discriminant 1, length 1, 'a', then 3 padding bytes that must be zero.
canonical = bytes.fromhex("00000001" "00000001" "61000000")
bad_pad = bytes.fromhex("00000001" "00000001" "61ff0000")
for name, raw in [("canonical", canonical), ("non-zero padding", bad_pad)]:
    try:
        m = xdr.Memo.from_xdr(base64.b64encode(raw).decode())
        out = base64.b64decode(m.to_xdr())
        print(f"Memo {name}: ACCEPTED, re-encodes to {out.hex()} (same bytes: {out == raw})")
    except Exception as e:
        print(f"Memo {name}: rejected: {type(e).__name__}: {e}")

# TimeBounds* inside Preconditions is awkward to hand-build; use SCContractInstance:
# ContractExecutable STELLAR_ASSET (1), then `SCMap* storage` optional flag.
canonical = bytes.fromhex("00000001" "00000000")
bad_flag = bytes.fromhex("00000001" "00000002" "00000000")  # flag 2, then an empty map
for name, raw in [("canonical (absent)", canonical), ("optional flag = 2", bad_flag)]:
    try:
        v = xdr.SCContractInstance.from_xdr(base64.b64encode(raw).decode())
        out = base64.b64decode(v.to_xdr())
        print(f"SCContractInstance {name}: ACCEPTED, storage={'present' if v.storage is not None else 'absent'}, "
              f"re-encodes to {out.hex()} (same bytes: {out == raw})")
    except Exception as e:
        print(f"SCContractInstance {name}: rejected: {type(e).__name__}: {e}")
