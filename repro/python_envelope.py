# P1 and P2 through the public API: TransactionEnvelope.from_xdr accepts envelopes that
# stellar-core rejects, and reports the same transaction hash for them.
import base64
import stellar_sdk
from stellar_sdk import Account, Asset, Keypair, Network, TransactionBuilder, TransactionEnvelope

print("stellar-sdk", stellar_sdk.__version__)
kp = Keypair.from_raw_ed25519_seed(bytes(range(32)))
tx = (
    TransactionBuilder(Account(kp.public_key, 1), Network.TESTNET_NETWORK_PASSPHRASE, base_fee=100)
    .add_text_memo("a")
    .append_payment_op(kp.public_key, Asset.native(), "1", source=kp.public_key)
    .add_time_bounds(0, 0)
    .build()
)
canonical = base64.b64decode(tx.to_xdr())
print("canonical         :", base64.b64encode(canonical).decode())
print("canonical hash    :", tx.hash_hex())

# P1: the memo "a" is 1 byte followed by 3 padding bytes. Set the first padding byte to 0xff.
i = canonical.index(bytes.fromhex("00000001" "00000001" "61000000")) + 9
bad_pad = canonical[:i] + b"\xff" + canonical[i + 1:]

# P2: the payment has an explicit source account, so its optional flag is 1. Set it to 2.
# The flag is the 4 bytes after the operation count (1).
j = canonical.index(bytes.fromhex("00000001" "00000001" "00000000"), i) + 4
assert canonical[j:j + 4] == b"\x00\x00\x00\x01"
bad_flag = canonical[:j] + b"\x00\x00\x00\x02" + canonical[j + 4:]

for name, raw in [("non-zero padding ", bad_pad), ("optional flag = 2", bad_flag)]:
    b64 = base64.b64encode(raw).decode()
    try:
        te = TransactionEnvelope.from_xdr(b64, Network.TESTNET_NETWORK_PASSPHRASE)
        print(f"{name} : ACCEPTED  hash {te.hash_hex()}  re-encodes to canonical: {base64.b64decode(te.to_xdr()) == canonical}")
    except Exception as e:
        print(f"{name} : rejected  {type(e).__name__}: {e}")
    print(f"   input: {b64}")
