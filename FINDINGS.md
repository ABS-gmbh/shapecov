# Findings

Run date: 14 November 2026, updated 15 November 2026. Versions are in `README.md`.

Filed upstream:

| Finding | Issue | Filed |
|---|---|---|
| J1 | https://github.com/lightsail-network/java-stellar-sdk/issues/833 | 14 November 2026 |
| P1 | https://github.com/StellarCN/py-stellar-base/issues/1262 | 14 November 2026 |
| P2 | https://github.com/StellarCN/py-stellar-base/issues/1263 | 14 November 2026 |
| E1 | https://github.com/stellar/stellar-etl/issues/512 | 15 November 2026 |

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

## Confirmed, filed 15 November

### E1. stellar-etl `export_token_transfer` fails on every ledger before protocol 23

- Affects: stellar-etl `master` (`2b24ec89`, 11 November 2026) and every release since #340
  (September 2025).
- Evidence: the replay harness's stellar-etl adapter. On `localcore-classic-p22-3` (one
  `CreateAccount`) and `localcore-muxed-source-p22-3` (one contract call), both protocol 22 ledgers
  from stellar-core 22.2.1, `export_token_transfer` exits with `error reading from unified events
  stream, expected version 4 got 3`. The other three exports take the same ledgers.
- Cause: stellar-etl builds go-stellar-sdk's token transfer processor with
  `NewEventsProcessorForUnifiedEvents`, which requires `TransactionMeta` v4 for every transaction.
  #340 replaced `NewEventsProcessor` with it and added no protocol check.
- Check: with the same pinned SDK, `NewEventsProcessor` returns the right events for both ledgers
  and the SDK's `VerifyEvents` passes (`repro/stellar-etl-ttp/`).
- Effect: a token transfer export over any range that starts before protocol 23 stops at the
  first ledger with a transaction, for example a backfill after a fix to the token transfer path.
- Searched on 15 November: no report in stellar-etl or go-stellar-sdk. The July 2026 audit (#448)
  lists token transfer classification as consistent without covering older ledgers.
- Filed: stellar/stellar-etl#512. Details: `corpus/evidence/stellar-etl-token-transfer-pre23.md`.
  Issue text: `issues/E1-stellar-etl-token-transfer-pre23.md`.

## Confirmed, not filed yet

### E2. stellar-etl: a revocation that redeems pool shares in several pools gets one `liquidity_pool_revoked`, citing another pool's balance

- Affects: stellar-etl `master` (`2b24ec89`). stellar-horizon `main` has the same code (not run).
- Evidence: `localcore-pool-revoke-two-pools-7`, from stellar-core 30.0.0 (scenario
  `pools-sponsorship-p30`). One `SetTrustLineFlags` redeems a trustor's shares in AAA/BBB and
  AAA/CCC: both pools removed, four claimable balances created. `export_effects` writes one
  `liquidity_pool_revoked`, for AAA/CCC, and its `reserves_revoked` gives AAA/BBB's AAA balance
  (`00000000e4bbf033…`, computed from the `ENVELOPE_TYPE_POOL_REVOKE_OP_ID` preimage) as AAA/CCC's.
  AAA/BBB gets no revoked effect.
- Found by: the oracle, with no hand-written expectation; predicted from the code first.
- Cause: `addLiquidityPoolRevokedEffect` reads only the first pool change
  (`getLiquidityPoolAndProductDelta(nil)`) and maps the new claimable balances by asset alone.
- Details: `corpus/evidence/stellar-etl-pool-revocation.md`. Draft:
  `issues/E2-stellar-etl-multi-pool-revocation.md`.

### E3. stellar-etl: pool-share trustlines removed by a revocation get no `trustline_removed`

- Same ledger: the two pool-share trustlines the revocation removes get no effect; only ChangeTrust
  emits `trustline_removed`, in stellar-etl and in Horizon. The effects-model counterpart of
  stellar/wallet-backend#817, which the same ledger also shows in wallet-backend.
- Draft: `issues/E3-stellar-etl-revoked-pool-trustlines.md`.

Searched on 15 November: no report in stellar-etl, stellar-horizon or go-stellar-sdk. stellar-etl
#458 concerns only the order of a revocation's claimable balance effects.

## Reproduced sightings from the RFP

Each is reproduced from an entry in `corpus/`. The SDK sightings have their commands and output in
`corpus/evidence/`; the wallet-backend sightings are replayed by `harness/replay/` and checked in
CI against `harness/replay/sightings.json` (see `harness/replay/RESULTS.md`).

- stellar/wallet-backend#729: testnet ledger 4437357, replayed through wallet-backend's own
  indexer, is `mishandled` at the commit before the fix (the signed-payload signer row does not
  encode) and `pass` at the fix.
- stellar/js-stellar-sdk#1789: a map with keys u32 `1` and symbol `"1"` loses one entry in
  `scValToNative` on v17.2.1 and is refused with an error on v17.4.0. Python 17.0.1 keeps both.
- stellar/js-stellar-sdk#1766: two real testnet ledgers. `testnet-5708889` holds a pool-share
  `ChangeTrust` whose issuers sort one way as key bytes and the other way as `G...` text: 16.3.0
  and 17.2.0 reject the pair ("Assets are not in lexicographic order"), and 17.2.1 onward accept it
  and compute the pool ID the ledger records. `testnet-5712621` holds a host-written map with keys
  u32 `1` and i64 `1`: `scvSortedMap` puts them in host order from 17.2.1 and reversed before.
  16.4.1, the current v16 release, has the issuer half (backported in #1768) but not the map half;
  js-stellar-sdk#1907, opened by another reporter on 15 November, already lists that gap, which
  this run confirms. Evidence: `corpus/evidence/js-stellar-sdk-1766.md`.
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

## Confirmed by the oracle (reported by others)

`tools/oracle.py` checks every row wallet-backend should store for each corpus ledger. At `main`
(`3e22515a`) every missing row matches one of two issues filed by the shapekit project on
15 November; the oracle derived them from ledger data alone:

- stellar/wallet-backend#815: 6 contract deployments (2 Stellar Asset Contract deploys, 4 contracts
  created by factory calls `create_pair` and `launch`) get no `ACCOUNT CREATE` row.
- stellar/wallet-backend#816: 3 accounts created by XLM sent through the native asset contract (once
  directly, twice from inside another contract) get no `ACCOUNT CREATE` row.

The same oracle, mapped to stellar-etl's effects and token transfer exports, confirms an open
stellar-etl issue at `master` (`2b24ec89`):

- stellar/stellar-etl#460 (filed by a maintainer in July): the effects export emits no
  `account_created` for an account created by XLM sent through the native asset contract, and no
  `trustline_created` for a trustline created by the asset contract's `trust()` (CAP-73). Four
  rows across three ledgers (`testnet-5709224`, `pubnet-65480300`, `localcore-sac-trust-p28-5`).

No other effect is missing and every net balance matches for the 25 ledgers stellar-etl can read.
See `harness/replay/RESULTS-stellar-etl.md`.

stellar/wallet-backend#817 (filed by the shapekit project) is also confirmed on a ledger of our
own, `localcore-pool-revoke-two-pools-7`: the two pool-share trustlines one revocation removes get
no `TRUSTLINE REMOVE`.

For wallet-backend, no other row is missing for any of the 54 ledgers. That now includes balances: all 4057 net balance
checks per input (every account's XLM and trustline balance per operation, and every net fee) match,
and no balance row is stored where the ledger shows no change. See `harness/replay/RESULTS.md`,
"Oracle checks".

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
