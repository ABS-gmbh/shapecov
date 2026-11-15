<!-- POSTED 14 Nov 2026:
     https://github.com/StellarCN/py-stellar-base/issues/1263#issuecomment-6880903967
     https://github.com/StellarCN/py-stellar-base/issues/1262#issuecomment-6880904327 -->

# Reply on StellarCN/py-stellar-base#1263 (optional flag)

Thanks, I re-ran it with the new package as #1264 asks.

`stellar-xdr` 0.2.0 handles it correctly. The modified envelope from this issue is rejected:

```python
import stellar_xdr as xdr

xdr.TransactionEnvelope.from_xdr_base64(bad)  # the "modified envelope" above
```

```
stellar_xdr._runtime._errors.XdrDecodeError: invalid optional flag 2 at offset 88
```

So this only happens in `stellar_sdk.xdr` (stellar-sdk 17.0.1), and the move to `stellar-xdr` fixes it. Nothing to report against py-stellar-xdr.

If the 17.x line will not get XDR fixes, feel free to close this as resolved by the migration.

---

# Reply on StellarCN/py-stellar-base#1262 (non-zero padding)

Following #1264, I re-ran this with the new package.

`stellar-xdr` 0.2.0 handles it correctly. The modified envelope from this issue is rejected:

```python
import stellar_xdr as xdr

xdr.TransactionEnvelope.from_xdr_base64(bad)  # the "modified envelope" above
```

```
stellar_xdr._runtime._errors.XdrDecodeError: non-zero padding at offset 81
```

The smallest case, `xdr.Memo.from_xdr_base64("AAAAAQAAAAFh/wAA")`, is rejected too (`non-zero padding at offset 9`).

So this only happens in `stellar_sdk.xdr` (stellar-sdk 17.0.1 with xdrlib3 0.1.1), and the move to `stellar-xdr` fixes it. Nothing to report against py-stellar-xdr.

If the 17.x line will not get XDR fixes, feel free to close this as resolved by the migration.
