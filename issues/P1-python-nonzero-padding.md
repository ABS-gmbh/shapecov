<!-- FILED 14 Nov 2026: https://github.com/StellarCN/py-stellar-base/issues/1262 -->

# XDR decoding accepts non-zero padding bytes, which stellar-core rejects

**Describe the bug**

When an XDR `opaque` or `string` has a length that is not a multiple of 4, it is followed by 1 to 3 padding bytes that must be zero (RFC 4506, sections 4.9 to 4.11). The SDK skips those bytes without looking at them, so it decodes input in which they are not zero.

`TransactionEnvelope.from_xdr` therefore accepts an envelope that stellar-core refuses to decode, and reports the same transaction hash as for the canonical envelope. Re-encoding writes zero padding, so the bytes that come out differ from the bytes that went in.

rs-stellar-xdr, js-stellar-sdk, go-stellar-sdk and java-stellar-sdk all reject the same input.

**What version of dependencies are you using?**

```
stellar-sdk==17.0.1
xdrlib3==0.1.1
```

Python 3.12. `main` at 91cb0670 still depends on `xdrlib3>=0.1.1`, and xdrlib3 `main` (f9b20fc2) has the same `unpack_fstring`.

**To Reproduce**

```python
import base64
from stellar_sdk import Account, Asset, Keypair, Network, TransactionBuilder, TransactionEnvelope

kp = Keypair.from_raw_ed25519_seed(bytes(range(32)))
tx = (
    TransactionBuilder(Account(kp.public_key, 1), Network.TESTNET_NETWORK_PASSPHRASE, base_fee=100)
    .add_text_memo("a")
    .append_payment_op(kp.public_key, Asset.native(), "1", source=kp.public_key)
    .add_time_bounds(0, 0)
    .build()
)
canonical = base64.b64decode(tx.to_xdr())
print("canonical hash:", tx.hash_hex())

# The memo "a" is 1 byte followed by 3 padding bytes. Set the first padding byte to 0xff.
i = canonical.index(bytes.fromhex("00000001" "00000001" "61000000")) + 9
bad = canonical[:i] + b"\xff" + canonical[i + 1:]

te = TransactionEnvelope.from_xdr(base64.b64encode(bad).decode(), Network.TESTNET_NETWORK_PASSPHRASE)
print("accepted, hash:", te.hash_hex())
print("re-encodes to canonical:", base64.b64decode(te.to_xdr()) == canonical)
```

Output:

```
canonical hash: 5429108abda98db8d3a6b2b73cc078a3898b74bb6f958aa0f14249a81287d0c0
accepted, hash: 5429108abda98db8d3a6b2b73cc078a3898b74bb6f958aa0f14249a81287d0c0
re-encodes to canonical: True
```

The modified envelope:

```
AAAAAgAAAAADoQe/884Qvh1w3RjnS8CZZ+TWMJulDV8d3IZkElUxuAAAAGQAAAAAAAAAAgAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAFh/wAAAAAAAQAAAAEAAAAAA6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbgAAAABAAAAAAOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4AAAAAAAAAAAAmJaAAAAAAAAAAAA=
```

stellar-core 30.0.0 on that envelope:

```
$ stellar-core print-xdr bad.b64 --filetype tx --base64
Could not decode with type 'tx' : Non-zero padding bytes encountered
```

The smallest case is `xdr.Memo.from_xdr("AAAAAQAAAAFh/wAA")`, which decodes and re-encodes to `AAAAAQAAAAFhAAAA`.

**Expected behavior**

Decoding raises an error when a padding byte is not zero.

**Additional context**

- Impact: different XDR strings decode to the same value and the same transaction hash, so anything keyed on the XDR string can hold several entries for one transaction, and an application can accept an envelope string that the network will not decode.
- Scope: every fixed or variable `opaque` and `string`. In a differential run over all types in the Protocol 30 XDR, the SDK accepted 160 of 160 inputs with one non-zero padding byte. On the types `stellar-core print-xdr` can decode, stellar-core rejected 41 of 41.
- Cause: `xdrlib3.Unpacker.unpack_fstring` (also used as `unpack_fopaque`) advances past the padding and returns `self.__buf[i : i + n]` without checking `self.__buf[i + n : j]`. The standard library's old `xdrlib` behaved the same way. The check could go in xdrlib3 or in the SDK's own `Opaque` and `String` unpacking.
- Compatibility: a behaviour change only for input that is not valid XDR.
- Related: #1258 is the same class of problem in strkey decoding. #1263 covers optional flags.
- Found with a schema-driven differential test across rs-stellar-xdr, js-stellar-sdk, py-stellar-base, go-stellar-sdk, java-stellar-sdk and stellar-core 30.0.0.
