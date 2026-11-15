# Findings

Run date: 14 November 2026, updated 15 November 2026. Versions are in `README.md`.

Filed upstream on 14 November 2026:

| Finding | Issue |
|---|---|
| J1 | https://github.com/lightsail-network/java-stellar-sdk/issues/833 |
| P1 | https://github.com/StellarCN/py-stellar-base/issues/1262 |
| P2 | https://github.com/StellarCN/py-stellar-base/issues/1263 |

"Confirmed" means: reproduced outside the harness with a short script in `repro/`, root cause
located in the SDK source, and stellar-core 30.0.0 checked on the same class of bytes.
"Apparently unreported" means a search of the SDK's issue tracker on 14 November found no match.
That search can miss things; check again before filing.

## Confirmed, unreported when filed

### J1. Java SDK decodes XDR followed by extra bytes

- Affects: `fromXdrBase64` and `fromXdrByteArray` on every generated XDR class
  (network.lightsail:stellar-sdk 6.0.0).
- Evidence: 952 of 952 trailing-byte cases accepted across all types. stellar-core rejects
  140 of 140 on the types it can decode ("unmarshaling did not consume whole message").
- Cause: `fromXdrByteArray` calls `decode(stream)` and returns without checking that the stream
  is exhausted.
- Effect: different base64 strings decode to the same value, and re-encoding drops the extra
  bytes. Same class as go-stellar-sdk #6039.
- Repro: `repro/JavaTrailing.java`. `AAAAAN6tvu8=` (MEMO_NONE plus `deadbeef`) decodes and
  re-encodes to `AAAAAA==`.

### P1. Python SDK accepts non-zero XDR padding

- Affects: every fixed or variable opaque and string (stellar-sdk 17.0.1, xdrlib3 0.1.1).
- Evidence: 160 of 160 cases accepted. stellar-core rejects 41 of 41
  ("Non-zero padding bytes encountered"). JS, Go, Java and Rust reject all.
- Cause: `xdrlib3.Unpacker.unpack_fstring` skips the padding bytes without checking them.
- Effect: non-canonical bytes decode, and re-encoding yields different bytes than were read.
- Repro: `repro/python_noncanonical.py`.
- Status, 14 November: the maintainer is replacing `stellar_sdk.xdr` with a new package,
  `stellar-xdr` (py-stellar-base #1264). Version 0.2.0 rejects this input. The finding holds for
  the released SDK 17.0.1 only, and our reply on the issue says so.

### P2. Python SDK treats any non-zero optional flag as "present"

- Affects: every optional field (stellar-sdk 17.0.1).
- Evidence: 145 of 145 cases accepted. stellar-core rejects 46 of 46
  ("xdr::pointer size must be 0 or 1"). JS, Go, Java and Rust reject all.
- Cause: generated code reads `X.unpack(...) if unpacker.unpack_uint() else None`.
- Repro: `repro/python_noncanonical.py`. Flag value 2 decodes as present and re-encodes as 1.
- Status, 14 November: the maintainer is replacing `stellar_sdk.xdr` with a new package,
  `stellar-xdr` (py-stellar-base #1264). Version 0.2.0 rejects this input. The finding holds for
  the released SDK 17.0.1 only, and our reply on the issue says so.

## Reproduced sightings from the RFP

Each is reproduced from an entry in `corpus/`. The SDK sightings have their commands and output in
`corpus/evidence/`; the wallet-backend sightings are replayed by `harness/replay/` and checked in
CI against `harness/replay/sightings.json` (see `harness/replay/RESULTS.md`).

- stellar/wallet-backend#729: testnet ledger 4437357, replayed through wallet-backend's own
  indexer, is `mishandled` at the commit before the fix (the signed-payload signer row does not
  encode) and `pass` at the fix.
- stellar/js-stellar-sdk#1789: a map with keys u32 `1` and symbol `"1"` loses one entry in
  `scValToNative` on v17.2.1 and is refused with an error on v17.4.0. Python 17.0.1 keeps both.
- stellar/js-stellar-sdk#1785: entry `synthetic-ids-beyond-f64`. On 16.3.0, 16.4.1, 17.2.0 and
  17.2.1 (the versions tested), `manageSellOffer` and `MuxedAccount` accept IDs that encode a different value: a number
  above 2^53, `"0x10"`, `" 16 "`, `""` (an offer ID of 0, "create a new offer") and a negative
  offer ID. 17.3.0 and 17.4.0 refuse all of them. Evidence: `corpus/evidence/js-stellar-sdk-1785.md`.
- stellar/wallet-backend#731: entry `localcore-sac-trust-p28-5`, a trustline created by the Stellar
  Asset Contract's `trust()`. `dropped` at the commit before the fix (no `TRUSTLINE/ADD` or
  `BALANCE_AUTHORIZATION` row, no error) and `pass` at the fix and at `main`.
- stellar/wallet-backend#716: the signed-payload half from the #729 entry (`mishandled` at
  `79ea2acd`: the signer stored as 33 of 41 bytes) and the muxed half from
  `localcore-muxed-source-p22-3` (`mishandled` at `79ea2acd`: a contract call's muxed source stored
  as a truncated `M...`). Between #693 and `bb0b162b` the same muxed entry stops ingestion on a
  duplicate key instead; `bb0b162b` documents and fixes that.

## Rediscovered (already reported by others)

These validate the method: the generator found each within its first run, with no hint.

- rs-stellar-xdr decodes a bool encoded as 2 as `false`: rs-stellar-xdr #622, filed 13 November.
  In this run JS, Go and Java reject such a bool, Python and stellar-core accept it.
- Go SDK accepts 1 or 2 trailing bytes in `SafeUnmarshalBase64`: go-stellar-sdk #6039, fix in
  PR #6041. Seen here as 222 of 952 trailing cases accepted.
- (Confirmed, not found blind.) Python SDK serializes out-of-range 64-bit IDs modulo 2^64:
  py-stellar-base #1251, filed 13 November by another reporter, the Python counterpart of
  js-stellar-sdk #1785. The corpus entry was built after both issues were known, so this confirms
  #1251 rather than rediscovering it. The `ids_exact` check on
  `synthetic-ids-beyond-f64` finds it in stellar-sdk 17.0.1: an offer ID of 2^64 encodes as **0**
  ("create a new offer"), a muxed ID of 2^64 encodes as **0** (a different sub-account), and an
  offer ID of -1 is accepted. Fixed on `main` by PR #1253 (commit `134c0e11`, 14 November); the
  same check passes there. **Not released:** 17.0.1, the latest on PyPI, still has it, five weeks
  after JavaScript fixed the same defect. Evidence: `corpus/evidence/js-stellar-sdk-1785.md`.

## Issue texts

The text of each filed issue is in `issues/`, one per finding. Each quotes a deterministic repro
through the SDK's public transaction API (`repro/python_envelope.py`, `repro/JavaEnvelope.java`)
and the stellar-core 30.0.0 result on the exact same envelope. The four envelopes are in
`out/envelopes.tsv`; rs-stellar-xdr, js-stellar-sdk and go-stellar-sdk reject all three bad ones.

Checked immediately before filing: both trackers re-searched with no matching report, and the
affected code is unchanged on the latest `main` of each SDK (Java 95bca0b5, Python 91cb0670).
The nearest existing report is py-stellar-base #1258 (non-zero padding in strkey decoding, a
different layer), which P1 links to.
