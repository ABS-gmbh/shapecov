<!-- FILED 14 Nov 2026: https://github.com/StellarCN/py-stellar-base/issues/1263 -->

# XDR decoding treats any non-zero optional flag as "present"; stellar-core accepts only 0 or 1

**Describe the bug**

An XDR optional (`T*`) is encoded as a 4-byte flag, 0 for absent or 1 for present, followed by the value when present (RFC 4506, section 4.19). The generated `unpack` code tests the flag for truthiness, so any non-zero value, such as 2 or 0xffffffff, is read as "present".

`TransactionEnvelope.from_xdr` therefore accepts an envelope that stellar-core refuses to decode, and reports the same transaction hash as for the canonical envelope. Re-encoding writes the flag as 1, so the bytes that come out differ from the bytes that went in.

rs-stellar-xdr, js-stellar-sdk, go-stellar-sdk and java-stellar-sdk all reject the same input.

**What version of dependencies are you using?**

```
stellar-sdk==17.0.1
xdrlib3==0.1.1
```

Python 3.12. `main` at 91cb0670 has the same generated code.

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

# The payment has an explicit source account, so the operation's optional flag is 1.
# It is the 4 bytes after the operation count. Set it to 2.
i = canonical.index(bytes.fromhex("00000001" "00000001" "61000000")) + 9
j = canonical.index(bytes.fromhex("00000001" "00000001" "00000000"), i) + 4
bad = canonical[:j] + b"\x00\x00\x00\x02" + canonical[j + 4:]

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
AAAAAgAAAAADoQe/884Qvh1w3RjnS8CZZ+TWMJulDV8d3IZkElUxuAAAAGQAAAAAAAAAAgAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAFhAAAAAAAAAQAAAAIAAAAAA6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbgAAAABAAAAAAOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4AAAAAAAAAAAAmJaAAAAAAAAAAAA=
```

stellar-core 30.0.0 on that envelope:

```
$ stellar-core print-xdr bad.b64 --filetype tx --base64
Could not decode with type 'tx' : xdr::pointer size must be 0 or 1
```

**Expected behavior**

Decoding raises an error when an optional flag is neither 0 nor 1.

**Additional context**

- Impact: different XDR strings decode to the same value and the same transaction hash, so anything keyed on the XDR string can hold several entries for one transaction, and an application can accept an envelope string that the network will not decode.
- Scope: every optional field in the generated XDR classes. In a differential run over all types in the Protocol 30 XDR, the SDK accepted 145 of 145 inputs with a flag other than 0 or 1. On the types `stellar-core print-xdr` can decode, stellar-core rejected 46 of 46.
- Cause: the generated code has the form

  ```python
  storage = (
      SCMap.unpack(unpacker, depth_limit - 1) if unpacker.unpack_uint() else None
  )
  ```

  (from `stellar_sdk/xdr/sc_contract_instance.py`). Reading the flag into a variable and raising unless it is 0 or 1 would fix every optional at once in the generator template.
- Compatibility: a behaviour change only for input that is not valid XDR.
- Related: #1262 covers non-zero padding bytes.
- Found with a schema-driven differential test across rs-stellar-xdr, js-stellar-sdk, py-stellar-base, go-stellar-sdk, java-stellar-sdk and stellar-core 30.0.0.
