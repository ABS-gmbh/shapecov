# Draft, not filed: lightsail-network/py-stellar-xdr

**Title:** Decode depth limit depends on the caller's stack, so valid envelopes can fail with XdrDepthError

Following StellarCN/py-stellar-base#1264's invitation for API feedback before 1.0.

### What

`from_xdr_base64` raises `XdrDepthError: nesting deeper than Python's recursion limit` when it
runs out of recursion budget. The point where that happens depends on how deep the caller's stack
already is, not on the data, so the same bytes decode in one place and fail in another.

### Reproduce (stellar-xdr 0.2.1, CPython 3.12, default recursion limit 1000)

A `TransactionEnvelope` with one `InvokeHostFunction` whose single argument is an `SCVal` vector
nested N levels deep (each level `SCV_VEC`, present, one element; innermost `SCV_VOID`):

| N | rs-stellar-xdr 30.0.0 at depth 1000 (what stellar-core uses for envelopes from protocol 28) | stellar-xdr, called at the top level | stellar-xdr, deepest caller stack that still decodes |
|---|---|---|---|
| 100 | decodes | decodes | 781 frames |
| 240 | decodes | decodes | 501 frames |
| 250 | rejects | decodes | — |

A 100-level value is the most the Soroban host writes into storage, events or return values; a
failed transaction's arguments are limited only by the envelope's XDR depth. Inside a
`LedgerCloseMeta` the envelope sits several levels deeper, which leaves less room.

```python
import base64, struct, stellar_xdr as xdr

def nested(n):
    b = struct.pack(">I", 1)                      # SCV_VOID
    for _ in range(n):
        b = struct.pack(">III", 16, 1, 1) + b     # SCV_VEC, present, one element
    return b

def at(frames, f):
    return f() if frames == 0 else at(frames - 1, f)

s = base64.b64encode(nested(100)).decode()
xdr.SCVal.from_xdr_base64(s)                      # ok
at(850, lambda: xdr.SCVal.from_xdr_base64(s))     # XdrDepthError
```

### Suggestion

An explicit, documented depth limit (like rs-stellar-xdr's `Limits { depth, len }`) that does not
move with the caller's stack: for example an iterative decoder, or temporarily raising the
recursion limit by the configured depth for the duration of a decode.
