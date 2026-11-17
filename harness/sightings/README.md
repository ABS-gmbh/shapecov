# The RFP's 18 sightings

The RFP ("XDR/CAP-Coverage Audit Tool and Indexer-Hardening Guide", section 7) lists 18 public
sightings. This is each one's status: reproduced (and where it runs in CI), or why it cannot be.
Status as of 17 November 2026.

**14 of 18 reproduced, all 14 in CI.**

| # | Sighting | Status | How | CI job |
|---|---|---|---|---|
| 1 | stellar-core#5435: `--check-lcm` golden LedgerCloseMeta | reproduced | 46 corpus entries are stellar-core's golden ledgers; CI compares each byte for byte with the golden files in a stellar-core checkout, and each decodes and re-encodes identically through the independent decoder, rs-stellar-xdr and stellar-core 30.0.0 | ci: "RFP check 1" |
| 2 | wallet-backend#731: SAC-created trustlines get no state change | reproduced | `dropped` at `764a4f5b`, `pass` at the fix (`localcore-sac-trust-p28-5`); the oracle also finds it blind in a pubnet ledger (`pubnet-63920000`, see `harness/replay/BACKTEST.md`) | replay: sightings |
| 3 | wallet-backend#729: CAP-40 signed-payload signers | reproduced | `mishandled` (ingestion halts) at `2a0a84ea` and `6e5a5910`, `pass` at the fix | replay: sightings |
| 4 | henyey#3941: validator dies during catchup on a bucket-entry parse failure | not reproduced | needs henyey and history-archive buckets during catchup; the corpus holds ledger-close meta, not buckets | — |
| 5 | rs-stellar-xdr#581: capacity reserved when decoding `VecM` | mapped, not observable | decoding a 2^20+1-element `ScVal` vector peaks at 122 MB with 28.0.1 (before) and 30.0.0 (after) alike: the extra capacity is reserved but never touched, as the PR itself says it may not be measurable | — |
| 6 | stellar-etl#454: lossy float amounts | reproduced | at `master` (open issue), for amounts above 2^53 stroops: in `localcore-big-merge-4` both transfers read back one stroop short in `token_transfer.amount` (2^53+1 is exported as 900719925.4740992); the payment's operation detail and the effects read back exact (`harness/replay/adapters/stellar-etl/amounts_check.py`). Limited to amounts above 2^53 on purpose: the issue's other half, the ×1e-7 scaling being inexact for small values, would flag a large share of every export and bury the rest | replay: stellar-etl |
| 7 | stellar-etl#470: Protocol 28 epic | mapped | an epic, not a defect; the stellar-etl adapter replays protocol 28 to 30 ledgers at `master` | replay: stellar-etl |
| 8 | wallet-backend#716: muxed and signed-payload addresses truncated | reproduced | both halves `mishandled` at `79ea2acd`, `pass` at the fixes | replay: sightings |
| 9 | stellar-etl#460: CAP-73 effect gaps | reproduced | the oracle reports the missing `account_created` and `trustline_created` effects at `master` from ledger data alone (5 rows in 4 ledgers) | replay: stellar-etl |
| 10 | wallet-backend#753: indexer fixes from an ingestion-halt audit | reproduced | #753 is `bb0b162b`: `localcore-muxed-source-p22-3` halts on a duplicate key at its parent `f8e5786d` and passes at `bb0b162b` | replay: sightings |
| 11 | rs-soroban-sdk#2099: `MuxedAddress` panics on a non-address `ScVal` | reproduced | the topic symbol `transfer` from the corpus: 28.0.0 and 29.0.1 panic ("incorrect scval type"), 30.0.0-rc.1 returns `ConversionError`; the latest stable release, 29.0.1, does not carry the fix | replay: sightings-rust |
| 12 | rs-stellar-xdr#598: `VecM` max length on serde deserialize | reproduced | JSON for an `AccountEntry` with 21 signers (max 20): 28.0.0 accepts it and emits XDR that 30.0.0 rejects (`LengthExceedsMax`); 28.0.1 and 30.0.0 refuse it; 20 signers work everywhere | replay: sightings-rust |
| 13 | js-stellar-sdk#1766: asset issuer and map key order | reproduced | a real testnet pool pair and a host-ordered map: 17.2.0 mishandles both, 17.2.1 passes | ci: pinned-SDK checks |
| 14 | rs-stellar-xdr#604: xdr-json schemas omit feature-gated types | not reproduced | concerns the generated JSON Schema files, not decoding or encoding values | — |
| 15 | js-stellar-sdk#1789: colliding map keys dropped | reproduced | `synthetic-scmap-colliding-keys`: 17.2.1 keeps one entry of two | ci: pinned-SDK checks |
| 16 | js-stellar-sdk#1785: muxed and offer IDs beyond 2^53 | reproduced | `synthetic-ids-beyond-f64`: 17.2.1 encodes different IDs | ci: pinned-SDK checks |
| 17 | js-xdr#165: nine XDR validation issues | reproduced | #165 only. The nine are js-xdr #162 to #170, filed on 12 October from one external audit; the RFP links #165, and this row reproduces #165's own cases, not the other eight issues. On 5.0.0, the latest release, all seven of #165's cases are silently coerced as the issue shows (out-of-range, negative, fractional and NaN integers written as wrapped or truncated words, `writePadding(1.5)` leaving the offset at 2.5, a forged `{ length: -4 }` rewinding the writer so the next word overwrites the second). The fix (PR #173, merged 16 October) is not in a published release; a weekly run installs the newest published js-xdr and fails once it rejects the cases (`harness/sightings/js-xdr-165/`) | ci: RFP checks 1 and 5 |
| 18 | js-stellar-sdk#1823: XDR string arms change non-UTF-8 bytes | reproduced | the memo of `localcore-memo-and-offer-p30-4` (bytes `ff fe`): rebuilt from `.value` it becomes 26 bytes with two U+FFFD in 17.2.1 and in 17.4.0, the latest; `Memo.fromXDRObject()` keeps the bytes. #1823 was closed with documentation (#1824), so the behaviour remains | ci: pinned-SDK checks |

Rows 2, 3, 8 and 10 are checked against `harness/replay/sightings.json` by `replay.py check`.
Rows 11 and 12: `harness/sightings/run.sh` builds each probe against the releases before and with the
fix (`--locked`, from the committed `Cargo.lock`) and fails if any outcome changes.
