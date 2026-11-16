# Findings

Run date: 14 November 2026, updated 16 November 2026. Versions are in `README.md`.

## All findings

<!-- findings-table:begin (generated from FINDINGS.json by .github/scripts/check_findings.py --write; do not edit by hand) -->

39 findings in `FINDINGS.json`, one record each. Severity: **S1** halts or rejects valid data; **S2** wrong or missing data; **S3** accepts non-canonical input; **S4** hardening. Dates are UTC.

**Found by ShapeCov and filed by us** (8)

| ID | Finding | Component | Severity | CAPs | Reproduction | Upstream | First reported | Status |
|---|---|---|---|---|---|---|---|---|
| J1 | Decoding accepts trailing bytes after a value | java-stellar-sdk: XDR decoding (fromXdrBase64, fromXdrByteArray) | S3 | none: codec level, an RFC 4506 rule, not a CAP | case `Memo/trailing0` | [lightsail-network/java-stellar-sdk#833](https://github.com/lightsail-network/java-stellar-sdk/issues/833) | ShapeCov, 2026-11-14 | fixed on master by the maintainer (#842, 2026-11-16), not released; 6.0.0 accepts all 954 trailing-byte cases |
| P1 | Decoding accepts non-zero XDR padding | py-stellar-base 17.0.1: stellar_sdk.xdr | S3 | none: codec level, an RFC 4506 rule, not a CAP | case `string64/pad_nonzero1` | [StellarCN/py-stellar-base#1262](https://github.com/StellarCN/py-stellar-base/issues/1262) | ShapeCov, 2026-11-14 | closed 2026-11-16: fixed in the replacement package stellar-xdr; the released SDK 17.0.1 still has it |
| P2 | Decoding treats any non-zero optional flag as present | py-stellar-base 17.0.1: stellar_sdk.xdr | S3 | none: codec level, an RFC 4506 rule, not a CAP | case `ManageDataOp/opt_flag_not_011` | [StellarCN/py-stellar-base#1263](https://github.com/StellarCN/py-stellar-base/issues/1263) | ShapeCov, 2026-11-14 | closed 2026-11-16: fixed in the replacement package stellar-xdr; the released SDK 17.0.1 still has it |
| E1 | export_token_transfer fails on ledgers whose TransactionMeta is older than v4 | stellar-etl: export_token_transfer (internal/transform/token_transfer.go) | S1; narrow: only sources with v1 to v3 meta (old or never-regenerated data lakes, local networks, older captive core); SDF's datastore serves v4 meta for old ledgers and is not affected | CAP-0067 | entry `localcore-classic-p22-3` | [stellar/stellar-etl#512](https://github.com/stellar/stellar-etl/issues/512) | ShapeCov, 2026-11-15 | open; impact corrected on the issue 2026-11-16; a fix with a regression test is ready on a branch, awaiting issue acceptance |
| E2 | A revocation that redeems pool shares in two pools gets one liquidity_pool_revoked, citing the other pool's balance | stellar-etl: export_effects (addLiquidityPoolRevokedEffect); Horizon has the same code | S2 | CAP-0038 | entry `localcore-pool-revoke-two-pools-7` | [stellar/stellar-etl#513](https://github.com/stellar/stellar-etl/issues/513) | ShapeCov, 2026-11-15 | open |
| E3 | Pool-share trustlines removed by a revocation get no trustline_removed effect | stellar-etl: export_effects; Horizon has the same code | S2 | CAP-0038 | entry `localcore-pool-revoke-two-pools-7` | [stellar/stellar-etl#514](https://github.com/stellar/stellar-etl/issues/514) | ShapeCov, 2026-11-15 | open |
| J3 | A negative offer ID is built and encoded | java-stellar-sdk 6.0.0: ManageSellOfferOperation.builder().offerId | S4; stellar-core rejects such a transaction (MANAGE_SELL_OFFER_MALFORMED, probe offer-id-negative), so it is caught at submission | none: SDK input conversion, not a protocol shape | entry `synthetic-ids-beyond-f64` | [lightsail-network/java-stellar-sdk#843](https://github.com/lightsail-network/java-stellar-sdk/issues/843) | ShapeCov, 2026-11-16 | open; filed on 16 November 2026 with J4 as java-stellar-sdk #843; the same input js-stellar-sdk refuses since 17.3.0 (#1785); go-stellar-sdk refuses it |
| J4 | MemoText.getText() turns memo bytes that are not UTF-8 into U+FFFD | java-stellar-sdk 6.0.0: MemoText | S2; getBytes() keeps the bytes; code that rebuilds or stores the memo from getText() changes it | none: a classic memo; SDK string conversion, not a protocol shape | entry `localcore-memo-and-offer-p30-4` | [lightsail-network/java-stellar-sdk#843](https://github.com/lightsail-network/java-stellar-sdk/issues/843) | ShapeCov, 2026-11-16 | open; filed on 16 November 2026 with J3 as java-stellar-sdk #843; the Java counterpart of js-stellar-sdk #1823, which was closed by documenting the behaviour |

**Reported first by others; ShapeCov's tools reproduce it** (15)

| ID | Finding | Component | Severity | CAPs | Reproduction | Upstream | First reported | Status |
|---|---|---|---|---|---|---|---|---|
| C1 | An account created by XLM sent through the native asset contract gets no ACCOUNT CREATE state change | wallet-backend: state changes (token_transfer processor) | S2 | CAP-0073 | entry `golden-invokehostfunction-692fdd0e-17` | [stellar/wallet-backend#804](https://github.com/stellar/wallet-backend/issues/804), [stellar/wallet-backend#816](https://github.com/stellar/wallet-backend/issues/816) | tolgayayci (#804, 2026-11-13); then ErenTopaal (shapekit project, #816), 2026-11-13 | open |
| C2 | Contract deployments that no auth entry declares get no ACCOUNT CREATE state change | wallet-backend: state changes (ContractDeployProcessor) | S2 | CAP-0046 | entry `localcore-muxed-source-p22-3` | [stellar/wallet-backend#806](https://github.com/stellar/wallet-backend/issues/806), [stellar/wallet-backend#815](https://github.com/stellar/wallet-backend/issues/815) | tolgayayci (#806, factory deploys, 2026-11-13); ErenTopaal (shapekit project, #815, factory and asset-contract deploys), 2026-11-13 | open |
| C3 | A pool-share trustline removed by a revocation gets no TRUSTLINE REMOVE state change | wallet-backend: state changes | S2 | CAP-0038 | entry `localcore-pool-revoke-two-pools-7` | [stellar/wallet-backend#817](https://github.com/stellar/wallet-backend/issues/817) | ErenTopaal (shapekit project), 2026-11-15 | open |
| C4 | Effects export misses account_created and trustline_created made by the asset contract | stellar-etl: export_effects | S2 | CAP-0073 | entry `localcore-sac-trust-p28-5` | [stellar/stellar-etl#460](https://github.com/stellar/stellar-etl/issues/460) | chowbao (stellar-etl maintainer), 2026-07-04 | open |
| C5 | Token transfer export fabricates a muxed destination with ID 0 for memo payments | stellar-etl: export_token_transfer (to_muxed) | S2; confirmed after reading the issue, not found blind | CAP-0067 | entry `localcore-memo-and-offer-p30-4` | [stellar/stellar-etl#450](https://github.com/stellar/stellar-etl/issues/450) | chowbao (stellar-etl maintainer), 2026-07-04 | open |
| C6 | A bool word other than 0 or 1 decodes as false (stellar-core reads it as true) | rs-stellar-xdr: bool decoding | S3 | none: codec level, an RFC 4506 rule, not a CAP | case `EvictionIterator/bool_not_010` | [stellar/rs-stellar-xdr#622](https://github.com/stellar/rs-stellar-xdr/issues/622) | tolgayayci, 2026-11-13 | open |
| C7 | SafeUnmarshalBase64 accepts 1 or 2 trailing bytes | go-stellar-sdk: xdr | S3 | none: codec level, an RFC 4506 rule, not a CAP | case `Value/trailing1` | [stellar/go-stellar-sdk#6039](https://github.com/stellar/go-stellar-sdk/issues/6039) | kasbsquall, 2026-11-13 | open; fix PR #6041 open |
| C8 | Out-of-range offer and muxed IDs are serialized modulo 2^64 | py-stellar-base 17.0.1: transaction building | S2 | none: SDK input conversion, not a protocol shape | entry `synthetic-ids-beyond-f64` | [StellarCN/py-stellar-base#1251](https://github.com/StellarCN/py-stellar-base/issues/1251) | kasbsquall, 2026-11-13 | fixed on main by #1253 (2026-11-14), not released; 17.0.1 still has it |
| C9 | scval.to_native drops map entries whose keys collide (u32 1 and i64 1 in a host-written map) | py-stellar-base 17.0.1: scval | S2 | CAP-0046-01 | entry `testnet-5712621` | [StellarCN/py-stellar-base#1250](https://github.com/StellarCN/py-stellar-base/issues/1250) | kasbsquall, 2026-11-13 | fixed on main by #1252 (2026-11-16), not released; 17.0.1 still has it |
| C10 | Participants from operation meta are never recorded: participantsForMeta reads only the TransactionMeta v0 arm | wallet-backend: participants (participantsForMeta) | S2; data is missing; nothing is stored wrong | none: an indexer rule (participants come from the meta), not a protocol shape | entry `pubnet-60280000` | [stellar/wallet-backend#677](https://github.com/stellar/wallet-backend/issues/677), [stellar/stellar-horizon#259](https://github.com/stellar/stellar-horizon/issues/259) | JakeUrban (SDF, #677); ErenTopaal added a sponsor case on 15 November; tolgayayci filed the Horizon counterpart, stellar-horizon#259, 2026-08-03 | open; the oracle's participant rule flags it at main: 89 missed participants in 78 transactions of the 611-ledger sweep (88 in 77 of 97,973 pubnet transactions), all sponsors whose sponsorship ended; our measured volume is on the issue (comment of 2026-11-16, https://github.com/stellar/wallet-backend/issues/677#issuecomment-6928536393) |
| C11 | allow_trust exports trustline_flags_updated instead of trustline_authorized, deauthorized or authorized_to_maintain_liabilities | stellar-etl: export_effects (allow_trust) | S2; confirmed after reading the issue, not found blind | none: an effect-type contract with Horizon's model, not a protocol shape | entry `testnet-5710719` | [stellar/stellar-etl#457](https://github.com/stellar/stellar-etl/issues/457) | chowbao (stellar-etl maintainer), 2026-07-04 | open; the oracle flags it on testnet-5710719 and on 69 rows of the 611-ledger sweep |
| C12 | Trade claims export offer_created, offer_updated and offer_removed effects the ledger does not show | stellar-etl: export_effects (trade claims) | S2; confirmed after reading the issue, not found blind | none: an effect-model contract with Horizon's, not a protocol shape | entry `pubnet-59220000` | [stellar/stellar-etl#456](https://github.com/stellar/stellar-etl/issues/456) | chowbao (stellar-etl maintainer), 2026-07-04 | open; the oracle flags 225 operations in 11 corpus ledgers |
| C13 | A pre-authorized transaction signer that core removes from a failed transaction gets no SIGNER REMOVE state change | wallet-backend: state changes (signers) | S2 | CAP-0028 | entry `localcore-preauth-failed-6` | [stellar/wallet-backend#805](https://github.com/stellar/wallet-backend/issues/805), [stellar/wallet-backend#818](https://github.com/stellar/wallet-backend/issues/818) | tolgayayci (#805, 2026-11-13); then ErenTopaal (shapekit project, #818), 2026-11-13 | open; the oracle flags it at main on localcore-preauth-failed-6, both inputs |
| C14 | create_contract details omit the salt of an address preimage | stellar-etl: export_operations (create_contract details) | S2; confirmed after reading the issue, not found blind | CAP-0046-02 | entry `testnet-5711641` | [stellar/stellar-etl#462](https://github.com/stellar/stellar-etl/issues/462) | chowbao (stellar-etl maintainer), 2026-07-04 | open; the oracle flags the three address-preimage deploys in the corpus |
| J2 | A liquidity-pool asset pair the network accepted is refused: issuers compared as strkey text | java-stellar-sdk 6.0.0: LiquidityPool and Asset.compareTo | S1 | CAP-0038 | entry `testnet-5708889` | [lightsail-network/java-stellar-sdk#832](https://github.com/lightsail-network/java-stellar-sdk/pull/832) | overcat (java-stellar-sdk maintainer, #832); the same defect as js-stellar-sdk #1766, 2026-11-05 | fixed on master by #832 (2026-11-05), not released; 6.0.0 refuses the pair (harness/sdk-semantic/siblings.py) |

**One of the RFP's sightings, reproduced before its fix and passing after** (10)

| ID | Finding | Component | Severity | CAPs | Reproduction | Upstream | First reported | Status |
|---|---|---|---|---|---|---|---|---|
| R1 | Signed-payload signers halt ingestion | wallet-backend: ingestion | S1 | CAP-0040 | entry `testnet-4437357-signed-payload-signer` | [stellar/wallet-backend#729](https://github.com/stellar/wallet-backend/pull/729) | aditya1702 (wallet-backend maintainer), 2026-09-03 | fixed (2026-09-08) |
| R2 | Trustlines created by the asset contract get no state change | wallet-backend: state changes | S2 | CAP-0073 | entry `localcore-sac-trust-p28-5` | [stellar/wallet-backend#731](https://github.com/stellar/wallet-backend/issues/731) | aristidesstaffieri, 2026-09-04 | fixed (2026-09-17) |
| R3 | Muxed and signed-payload addresses stored truncated | wallet-backend: AddressBytea | S2 | CAP-0027, CAP-0040 | entry `localcore-muxed-source-p22-3` | [stellar/wallet-backend#716](https://github.com/stellar/wallet-backend/issues/716) | aditya1702 (wallet-backend maintainer), 2026-08-27 | fixed (2026-09-18) |
| R4 | A contract call from a muxed source halts ingestion on a duplicate key | wallet-backend: ingestion (participants) | S1 | CAP-0027 | entry `localcore-muxed-source-p22-3` | [stellar/wallet-backend#753](https://github.com/stellar/wallet-backend/pull/753) | aditya1702 (wallet-backend maintainer), 2026-09-25 | fixed (2026-09-25) |
| R5 | A valid liquidity-pool pair rejected: issuers ordered as strkey text, not key bytes | js-stellar-sdk: asset ordering and ScVal map keys | S1 | CAP-0038, CAP-0046-01 | entry `testnet-5708889` | [stellar/js-stellar-sdk#1766](https://github.com/stellar/js-stellar-sdk/pull/1766) | Ryang-21 (js-stellar-sdk maintainer), 2026-10-01 | fixed in 17.2.1; 16.4.1 has the pool half of the fix but still mishandles the map keys |
| R6 | Muxed account and offer IDs accept values that encode a different ID | js-stellar-sdk: transaction building | S2 | none: SDK input conversion, not a protocol shape | entry `synthetic-ids-beyond-f64` | [stellar/js-stellar-sdk#1785](https://github.com/stellar/js-stellar-sdk/issues/1785) | quietbits (js-stellar-sdk maintainer), 2026-10-07 | fixed in 17.3.0; present in 16.4.1 |
| R7 | scValToNative drops map entries whose keys collide | js-stellar-sdk: scValToNative | S2 | CAP-0046-01 | entry `synthetic-scmap-colliding-keys` | [stellar/js-stellar-sdk#1789](https://github.com/stellar/js-stellar-sdk/issues/1789) | quietbits (js-stellar-sdk maintainer), 2026-10-07 | fixed: 17.4.0 refuses a map whose keys collide; 17.2.1 drops one entry with no error |
| R8 | XDR string arms change bytes that are not UTF-8 | js-stellar-sdk: XDR string .value | S2 | none: a classic memo; SDK string conversion, not a protocol shape | entry `localcore-memo-and-offer-p30-4` | [stellar/js-stellar-sdk#1823](https://github.com/stellar/js-stellar-sdk/issues/1823) | quietbits (js-stellar-sdk maintainer), 2026-10-16 | closed 2026-10-20 by documenting the behaviour (#1824); 17.4.0 still changes the bytes |
| R9 | Serde deserialization accepts a VecM over its maximum length | rs-stellar-xdr: serde (JSON) support | S3 | none: codec level, an XDR length limit, not a CAP | `harness/sightings/rs-stellar-xdr-598/acct21.json` | [stellar/rs-stellar-xdr#598](https://github.com/stellar/rs-stellar-xdr/pull/598) | leighmcculloch (SDF), 2026-09-29 | fixed in 28.0.1 and 30.0.0; 28.0.0 accepts 21 signers and emits XDR that 30.0.0 rejects |
| R10 | MuxedAddress panics on a non-address ScVal | rs-soroban-sdk: MuxedAddress conversion | S1 | CAP-0067 | `harness/sightings/rs-soroban-sdk-2099` | [stellar/rs-soroban-sdk#2099](https://github.com/stellar/rs-soroban-sdk/pull/2099) | leighmcculloch (SDF), 2026-09-29 | fixed in 30.0.0-rc.1; the latest stable release, 29.0.1, does not have the fix |

**Fixed upstream before ShapeCov existed; the harness detects it at the commits before the fix** (1)

| ID | Finding | Component | Severity | CAPs | Reproduction | Upstream | First reported | Status |
|---|---|---|---|---|---|---|---|---|
| R11 | Participants taken from the envelope: failed-transaction destinations, unmatched authorization entries, declared-only deploys, invoked contracts | wallet-backend: participants and contract deploys (indexer) | S2; accounts are recorded as participants of transactions whose meta does not show them | none: an indexer rule (participants come from the meta), not a protocol shape | entry `pubnet-61240000` | [stellar/wallet-backend@9538b3c](https://github.com/stellar/wallet-backend/commit/9538b3caeaebfeb3d034146c0ce9643c3066cf8a), [stellar/wallet-backend@80121f3](https://github.com/stellar/wallet-backend/commit/80121f3abe0fcdf6487d123e940de2631c1210b2), [stellar/wallet-backend@e2da4ca](https://github.com/stellar/wallet-backend/commit/e2da4cadf2689380e9fc2dd0e1bce64191f411b8) | aditya1702 (wallet-backend maintainer), who fixed it; no issue was filed, 2026-09-28 | fixed upstream (2026-09-28); the replay oracle flags it at the commits before e2da4ca, blind on pubnet-61240000 |

**A finding of the linter on wallet-backend, accepted with a reason** (5)

| ID | Finding | Component | Severity | CAPs | Reproduction | Upstream | First reported | Status |
|---|---|---|---|---|---|---|---|---|
| L1 | The declared authorization tree is walked with no depth cap of its own | wallet-backend: ContractDeployProcessor (walkInvocation) | S4 | CAP-0046-11 | `linter/results/wallet-backend-3e22515a4497.json` | [stellar/wallet-backend#820](https://github.com/stellar/wallet-backend/issues/820) | ErenTopaal (shapekit project), 2026-11-15 | open; a fix with a test is ready on a branch, awaiting issue acceptance |
| L2 | Participants taken from the envelope for failed transactions | wallet-backend: participants (GetOperationsParticipants) | S2; a documented design choice: an account named only in a failed transaction's envelope is recorded as a participant | none: an indexer design rule (participants from the meta), not a protocol shape | `linter/results/wallet-backend-3e22515a4497.json` | not filed | ShapeCov, 2026-11-15 | accepted in linter/accepted/wallet-backend.json; not filed, because it is a design choice |
| L3 | Memo text used without a UTF-8 check in an uncalled helper | wallet-backend: utils.Memo | S4; not reachable today; becomes live if a memo column is added (wallet-backend #800) | none: a classic memo; an indexer storage rule, not a protocol shape | `linter/results/wallet-backend-3e22515a4497.json` | [stellar/wallet-backend#800](https://github.com/stellar/wallet-backend/issues/800) | ShapeCov, 2026-11-15 | accepted in linter/accepted/wallet-backend.json; not filed, because the code is uncalled |
| L4 | Memo text exported without a UTF-8 check: invalid bytes become U+FFFD | stellar-etl: export_transactions (TransformTransaction, memo column) | S2; live: the exported memo differs from the ledger's for any non-UTF-8 text memo | none: a classic memo; an indexer storage rule, not a protocol shape | `linter/results/stellar-etl-2b24ec89ddce.json` | [stellar/stellar-etl#504](https://github.com/stellar/stellar-etl/issues/504) | tolgayayci (#504), 2026-11-13 | open; SC001 reports the line #504 names, on the linter's first run on stellar-etl |
| L5 | Operation participants taken from the envelope with no success check, in an uncalled copy of Horizon's processor | stellar-etl: transactionOperationWrapper.Participants (internal/transform/operation.go) | S4; not reachable: nothing in stellar-etl calls it | none: an indexer design rule (participants from the meta), not a protocol shape | `linter/results/stellar-etl-2b24ec89ddce.json` | not filed | ShapeCov, 2026-11-16 | accepted in linter/accepted/stellar-etl.json; not filed, because the code is uncalled and stellar-etl#463 already proposes deleting the dead Horizon copy it belongs to |

<!-- findings-table:end -->

The sections below give each finding's evidence in full.

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
- Status: closed 16 November, two days after we filed it. The maintainer fixed it in
  java-stellar-sdk#842 (`d093810`), which closes our issue and also covers item 1 of his own
  audit, java-stellar-sdk #835. The fix is his, not ours. It is not yet released, so 6.0.0 still
  has the defect. Checked against the fix: of the 954 trailing-byte cases the generator makes,
  6.0.0 accepts all and `master` at `d093810` rejects all.

### P1. Python SDK accepts non-zero XDR padding

- Affects: every fixed or variable opaque and string (stellar-sdk 17.0.1, xdrlib3 0.1.1).
- Evidence: 160 of 160 cases accepted. stellar-core rejects 41 of 41
  ("Non-zero padding bytes encountered"). JS, Go, Java and Rust reject all.
- Cause: `xdrlib3.Unpacker.unpack_fstring` skips the padding bytes without checking them.
- Effect: non-canonical bytes decode, and re-encoding yields different bytes than were read.
- Repro: `repro/python_noncanonical.py`.
- Status, 14 November: the maintainer is replacing `stellar_sdk.xdr` with a new package,
  `stellar-xdr` (py-stellar-base #1264). Version 0.2.0 rejects this input. The finding holds for
  the released SDK 17.0.1 only, and our reply on the issue says so. Closed by the maintainer on
  16 November as fixed in the new package.

### P2. Python SDK treats any non-zero optional flag as "present"

- Affects: every optional field (stellar-sdk 17.0.1).
- Evidence: 145 of 145 cases accepted. stellar-core rejects 46 of 46
  ("xdr::pointer size must be 0 or 1"). JS, Go, Java and Rust reject all.
- Cause: generated code reads `X.unpack(...) if unpacker.unpack_uint() else None`.
- Repro: `repro/python_noncanonical.py`. Flag value 2 decodes as present and re-encodes as 1.
- Status, 14 November: the maintainer is replacing `stellar_sdk.xdr` with a new package,
  `stellar-xdr` (py-stellar-base #1264). Version 0.2.0 rejects this input. The finding holds for
  the released SDK 17.0.1 only, and our reply on the issue says so. Closed by the maintainer on
  16 November as fixed in the new package.

## Confirmed, filed 15 November

### E1. stellar-etl `export_token_transfer` fails on any ledger whose transaction meta is older than v4

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
- Effect, corrected 16 November: the failure follows the `TransactionMeta` version, not the
  protocol. Stellar's public ledger archive serves old pubnet ledgers with v4 meta: protocol 13
  ledgers 30,820,015 and 30,822,015 both have v4 meta for every transaction. stellar-etl's own
  integration tests export token transfers from ledgers in that range and pass on `master`, so
  SDF's datastore evidently holds v4 meta for old history too. The export stops only on a source
  whose transactions carry v1 to v3 meta: a data lake written by stellar-core before 23 and never
  regenerated, a local or private network, or captive core of an older release. The issue's first
  "Impact" sentence, a backfill of any range before protocol 23, overstates it for SDF's own
  datastore.
- Corrected on the issue, 16 November: the issue is retitled "export_token_transfer fails on
  ledgers whose TransactionMeta is older than v4". A comment
  (https://github.com/stellar/stellar-etl/issues/512#issuecomment-6923662005) states that the
  failure follows the meta version and that SDF's datastore is not affected. It cites pubnet
  ledgers 30,820,015, 40,000,000, 50,000,000 and 57,000,000 (protocols 13, 18, 19 and 22), with
  v4 meta for every transaction. The text first filed is kept below as history.
- Fix: prepared on a local branch, awaiting issue acceptance. It chooses the processor by meta
  version, so ledgers that already have v4 meta keep today's path and the integration goldens
  are unchanged.
- Searched on 15 November: no report in stellar-etl or go-stellar-sdk. The July 2026 audit (#448)
  lists token transfer classification as consistent without covering older ledgers.
- Filed: stellar/stellar-etl#512. Details: `corpus/evidence/stellar-etl-token-transfer-pre23.md`.
  Issue text: `issues/E1-stellar-etl-token-transfer-pre23.md`.

## Confirmed, filed 16 November

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
- Filed: stellar/stellar-etl#513. Details: `corpus/evidence/stellar-etl-pool-revocation.md`.
  Issue text: `issues/E2-stellar-etl-multi-pool-revocation.md`.

### E3. stellar-etl: pool-share trustlines removed by a revocation get no `trustline_removed`

- Same ledger: the two pool-share trustlines the revocation removes get no effect; only ChangeTrust
  emits `trustline_removed`, in stellar-etl and in Horizon. The effects-model counterpart of
  stellar/wallet-backend#817, which the same ledger also shows in wallet-backend.
- Filed: stellar/stellar-etl#514. Issue text: `issues/E3-stellar-etl-revoked-pool-trustlines.md`.

Searched on 15 November: no report in stellar-etl, stellar-horizon or go-stellar-sdk. stellar-etl
#458 concerns only the order of a revocation's claimable balance effects.

## Across SDKs

[`sdk-matrix/MATRIX.md`](sdk-matrix/MATRIX.md) is generated by `sdk-matrix/matrix.py` from fresh runs. It
shows, for each defect class above and each RFP sighting, which SDK release has it. A cell says
"not tested" when the script could not run it and names no source. From the 16 November run:

- **Trailing bytes:**
  - java-stellar-sdk 6.0.0 accepts all 954 cases (fixed on `master` by #842, not released);
  - go-stellar-sdk v0.9.0 accepts 223 of 954, the 1- and 2-byte ones (#6039, fix PR #6041 open);
  - every other decoder and stellar-core reject them.
- **py-stellar-base 17.0.1, the latest release,** still has four defects that its successor
  package, py-stellar-xdr, or its own `main` branch has fixed:
  - non-zero padding and optional flags (#1262, #1263);
  - offer and muxed IDs beyond 2^53 (#1251);
  - map entries dropped when keys collide, shown on a map the host wrote with keys u32 `1` and
    i64 `1` (#1250).
- **A bool word of 2:**
  - stellar-core and py-stellar-base read it as true;
  - rs-stellar-xdr 30.0.0 reads it as false (#622);
  - the other four decoders reject it.
- **js-stellar-sdk 16.4.1, the current v16 release,** lacks the 17.x fixes for map key order,
  colliding keys and out-of-range IDs. That gap is js-stellar-sdk#1907, reported by others.
- **js-stellar-sdk 17.4.0** still changes non-UTF-8 bytes through a string arm's `.value`.
  js-stellar-sdk#1823 was closed by documenting this (#1824), not by a code change.

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
(`3e22515a`) every missing row matches a defect others had already reported, first by
tolgayayci on 13 November and again, more broadly, by the shapekit project on 15 November; the
oracle derived them from ledger data alone:

- 6 contract deployments (2 Stellar Asset Contract deploys, 4 contracts created by factory calls
  `create_pair` and `launch`) get no `ACCOUNT CREATE` row: stellar/wallet-backend#806 (factory
  deploys, 13 November) and #815 (factory and Stellar Asset Contract deploys, 15 November).
- 3 accounts created by XLM sent through the native asset contract (once directly, twice from
  inside another contract) get no `ACCOUNT CREATE` row: stellar/wallet-backend#804
  (13 November) and #816 (15 November), which describe the same defect.

The harness labels these rows #815 and #816, whose scope covers every case;
`harness/replay/adapters/wallet-backend/known.json` records #804, #805 and #806 as the earlier
reports.

The same oracle, mapped to stellar-etl's effects and token transfer exports, confirms two open
stellar-etl issues at `master` (`2b24ec89`):

- stellar/stellar-etl#460 (filed by a maintainer in July): the effects export emits no
  `account_created` for an account created by XLM sent through the native asset contract, and no
  `trustline_created` for a trustline created by the asset contract's `trust()` (CAP-73). Five
  rows across four ledgers (`testnet-5709224`, `pubnet-65480300`, `pubnet-63920000`,
  `localcore-sac-trust-p28-5`).

- stellar/stellar-etl#450 (filed by a maintainer in July, from the stellar-etl maintainers' own
  audit): `export_token_transfer` exports a payment to a G address that carries a text or hash memo
  with an M address whose muxed ID is 0. The oracle flags 928 rows in 17 ledgers at `master`
  (`localcore-memo-and-offer-p30-4`, 11 pubnet and 5 testnet ledgers). The rule was written after
  reading the issue, so this confirms #450 rather than finding it blind.

Apart from our own findings E2 and E3 (#513, #514), no other effect is missing and every net
balance matches for the 35 ledgers stellar-etl exports.
See `harness/replay/RESULTS-stellar-etl.md`.

stellar/wallet-backend#817 (filed by the shapekit project) is also confirmed on a ledger of our
own, `localcore-pool-revoke-two-pools-7`: the two pool-share trustlines one revocation removes get
no `TRUSTLINE REMOVE`.

A sweep of 611 further network ledgers (100,676 transactions, protocols 23 to 30; see
`harness/replay/README.md`, "Sweep") found no new defect in either indexer: its only failures are
wallet-backend#815 (42 rows) and stellar-etl#460 (1 row).

For wallet-backend, no other row is missing for any of the 63 ledgers: 8,919 of 8,930 checks per
input pass, and the 11 that fail are the rows above. The checks include balances (every account's
XLM and trustline balance per operation, and every net fee), and no balance row is stored where the
ledger shows no change. See `harness/replay/RESULTS.md`,
"Oracle checks".

## The Python packages replacing `stellar_sdk.xdr` and `.strkey`

The py-stellar-base maintainer asks that XDR and strkey problems be tried against `stellar-xdr` and
`stellar-strkey` first, and welcomes API feedback before 1.0 (StellarCN/py-stellar-base#1264).
`runners/python-xdr/` runs them (stellar-xdr 0.2.1, stellar-strkey 0.2.0, 16 November):

- XDR: every one of the 7,392 generated cases matches the reference except 26 `bool` values of 2,
  which stellar-xdr rightly rejects (rs-stellar-xdr #622). P1 and P2 do not occur. All 67 corpus
  entries round-trip identically.
- SEP-51 JSON: round-trips on all 3,808 valid cases and interoperates with rs-stellar-xdr, except in
  15 overlay types where rs-stellar-xdr writes inline fixed-length opaque fields as integer arrays
  instead of SEP-51's hex: rs-stellar-xdr #618 (open), confirmed here; stellar-xdr conforms.
- Strkeys: agrees with SEP-23 1.4.0 on all 172 cases, including CAP-84 muxed contracts. The same
  cases find 8 differences in stellar-sdk 17.0.1's `StrKey`.
- Not defects, API feedback, posted on 16 November 2026 as a comment on
  [StellarCN/py-stellar-base#1264](https://github.com/StellarCN/py-stellar-base/issues/1264#issuecomment-6930257881): the decode depth limit moves with the caller's
  stack, so a valid 240-level envelope argument fails when the caller is more than 501 frames deep
  (`issues/X1-py-stellar-xdr-depth.md`); `SponsorshipDescriptor` and the bare integer types have no
  codec (`issues/X2-py-stellar-xdr-typedef-codecs.md`).

## Detection backtest

Would the harness have caught defects that were already fixed or reported upstream? Replayed at the
commit before and after each in-scope fix, it detects 10 of wallet-backend's 18 in-scope fixes (5 on
ledgers not chosen for the bug) and flags 5 of stellar-etl's 9 in-scope issues (1 blind). The
measurement is incomplete: `harness/replay/BACKTEST.md` lists every fix, and for each miss the
shape, oracle rule or export that would catch it. `python3 harness/replay/replay.py backtest`
checks every claim against the recorded replays.

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

Reported earlier by others, found again by the linter rather than the generator:

- wallet-backend's `walkInvocation` (`internal/indexer/processors/contract_deploy.go:116`) walks
  the declared authorization tree with no depth cap: stellar/wallet-backend#820, filed by the
  shapekit project on 15 November at 00:17 UTC. `shapecov-lint` rule SC002 reports the same
  line; its first recorded run on wallet-backend `main` was committed about ten hours later. See
  `linter/README.md`, "Run on wallet-backend `main`".

## Issue texts

The text of each filed issue is in `issues/`, one per finding. Each quotes a deterministic repro
through the SDK's public transaction API (`repro/python_envelope.py`, `repro/JavaEnvelope.java`)
and the stellar-core 30.0.0 result on the exact same envelope. The four envelopes are in
`out/envelopes.tsv`; rs-stellar-xdr, js-stellar-sdk and go-stellar-sdk reject all three bad ones.

Checked immediately before filing: both trackers re-searched with no matching report, and the
affected code is unchanged on the latest `main` of each SDK (Java 95bca0b5, Python 91cb0670).
The nearest existing report is py-stellar-base #1258 (non-zero padding in strkey decoding, a
different layer), which P1 links to.
