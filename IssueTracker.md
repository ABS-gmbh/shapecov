# Issue tracker

Every issue ShapeCov has filed in an upstream repository, and every comment it has posted on one.
States were read from GitHub on 17 November 2026. Dates are UTC.

This repository has no issues of its own. The full list of findings, including the 34 that others
reported first and ShapeCov reproduces, is in [`FINDINGS.md`](FINDINGS.md). The text of each report
as filed is in [`issues/`](issues/).

## Summary

| | Count |
|---|---|
| Issues filed | 8 (5 open, 3 closed) |
| Findings those issues cover | 9 (J3 and J4 share one issue) |
| Comments posted | 6, on 6 issues |
| Other requests filed | 1 (open): review of the indexer-hardening guide |

## Issues filed

### Open

| ID | Issue | Filed | Description | Status |
|---|---|---|---|---|
| E1 | [stellar/stellar-etl#512](https://github.com/stellar/stellar-etl/issues/512) | 2026-11-15 | `export_token_transfer` fails on ledgers whose `TransactionMeta` is older than v4. Only sources with v1 to v3 meta are affected: old or never-regenerated data lakes, local networks, older captive core. SDF's datastore serves v4 meta for old ledgers and is not affected. | Open. Impact corrected in a comment on 16 November. A fix with a regression test is ready on a branch, awaiting acceptance of the issue. |
| E2 | [stellar/stellar-etl#513](https://github.com/stellar/stellar-etl/issues/513) | 2026-11-15 | A revocation that redeems pool shares in several pools gets one `liquidity_pool_revoked` effect, and that effect cites another pool's claimable balance. Reproduced in stellar-horizon v30.0.1 as well. | Open, no reply yet. |
| E3 | [stellar/stellar-etl#514](https://github.com/stellar/stellar-etl/issues/514) | 2026-11-15 | Pool-share trustlines removed by an authorization revocation get no `trustline_removed` effect. Reproduced in stellar-horizon v30.0.1 as well. | Open, no reply yet. |
| E4 | [stellar/stellar-etl#515](https://github.com/stellar/stellar-etl/issues/515) | 2026-11-17 | `export_ledger_entry_changes` writes nothing when `--start-ledger` equals `--end-ledger`: the command exits 0, logs nothing and writes no file. Ranges of two or more ledgers are not affected. Impact low. | Open, no reply yet. |
| J3, J4 | [lightsail-network/java-stellar-sdk#843](https://github.com/lightsail-network/java-stellar-sdk/issues/843) | 2026-11-16 | Two behaviours that js-stellar-sdk has already dealt with. J3: a negative offer ID is built and encoded; stellar-core rejects the transaction at submission. J4: `MemoText.getText()` turns memo bytes that are not UTF-8 into U+FFFD, so code that rebuilds the memo from the text changes it. | Open, no reply yet. |

### Closed

| ID | Issue | Filed | Closed | Description | Outcome |
|---|---|---|---|---|---|
| J1 | [lightsail-network/java-stellar-sdk#833](https://github.com/lightsail-network/java-stellar-sdk/issues/833) | 2026-11-14 | 2026-11-16 | XDR decoding accepts trailing bytes: `fromXdrBase64` and `fromXdrByteArray` do not check that the input is fully consumed. | Fixed on master by the maintainer in #842. Not released; 6.0.0 still accepts all 954 trailing-byte cases. |
| P1 | [StellarCN/py-stellar-base#1262](https://github.com/StellarCN/py-stellar-base/issues/1262) | 2026-11-14 | 2026-11-16 | XDR decoding accepts non-zero padding bytes, which stellar-core rejects. | Fixed in the replacement package stellar-xdr. The released SDK 17.0.1 still has it. |
| P2 | [StellarCN/py-stellar-base#1263](https://github.com/StellarCN/py-stellar-base/issues/1263) | 2026-11-14 | 2026-11-16 | XDR decoding treats any non-zero optional flag as "present"; stellar-core accepts only 0 or 1. | Fixed in the replacement package stellar-xdr. The released SDK 17.0.1 still has it. |

## Other upstream requests

Not defects: requests to an upstream project.

| Issue | Filed | What it asks | Status |
|---|---|---|---|
| [stellar/stellar-docs#3165](https://github.com/stellar/stellar-docs/issues/3165) | 2026-11-17 | Proposes the indexer-hardening guide as a page under "Build your own indexer" on developers.stellar.org, linking the exported page, the Markdown guide and `guide/REVIEW.md` at `v0.2.0`. Asks whether the page is wanted there, and who should review it before publication, which the RFP requires. | Open, no reply yet. stellar-docs promises a first response within a week. |

## Comments posted

| Issue | Issue by | Posted | Comment | What it says |
|---|---|---|---|---|
| [stellar/stellar-etl#448](https://github.com/stellar/stellar-etl/issues/448) | chowbao (SDF) | 2026-11-17 | [comment](https://github.com/stellar/stellar-etl/issues/448#issuecomment-6946156859) | Counts for the members of stellar-etl's correctness audit epic, from replays at `master` on the 611-ledger sweep and the 114 corpus ledgers: #452, #450, #456, #457, #462 and #460 on both, #451, #459 and #454 on the corpus only (records C4, C5, C11, C12 and C14 to C18). Names what was not exercised (#453, #451's overflow sentinel, #459's durability point, the naming and schema members) and why the #452 rate (8.7%) is not comparable one to one with the issue's 15.6%. No new finding; its #459 row cites #515. |
| [stellar/stellar-etl#512](https://github.com/stellar/stellar-etl/issues/512) | ShapeCov | 2026-11-16 | [comment](https://github.com/stellar/stellar-etl/issues/512#issuecomment-6923662005) | Correction to our own report. The failure follows the `TransactionMeta` version, not the protocol, so the impact is narrower than first written. The title was changed to match. |
| [stellar/wallet-backend#677](https://github.com/stellar/wallet-backend/issues/677) | JakeUrban (SDF) | 2026-11-16 | [comment](https://github.com/stellar/wallet-backend/issues/677#issuecomment-6928536393) | Measured volume for an open issue: transaction meta participants are dropped on every modern ledger. 89 missed participants in 78 transactions of the 611-ledger sweep, all sponsors whose sponsorship ended. Record C10 in `FINDINGS.md`. |
| [StellarCN/py-stellar-base#1264](https://github.com/StellarCN/py-stellar-base/issues/1264) | overcat (maintainer) | 2026-11-16 | [comment](https://github.com/StellarCN/py-stellar-base/issues/1264#issuecomment-6930257881) | Test results for stellar-xdr 0.2.1 and stellar-strkey 0.2.0, as the maintainer asked. Both agree with the reference on every case. Two API questions raised: the effective depth limit, and five typedefs with no codec of their own. Both were answered by documentation in [lightsail-network/py-stellar-xdr#24](https://github.com/lightsail-network/py-stellar-xdr/pull/24), merged 17 November. |
| [StellarCN/py-stellar-base#1262](https://github.com/StellarCN/py-stellar-base/issues/1262) | ShapeCov | 2026-11-14 | [comment](https://github.com/StellarCN/py-stellar-base/issues/1262#issuecomment-6880904327) | Re-run on the new package: stellar-xdr 0.2.0 rejects the modified envelope from the issue. |
| [StellarCN/py-stellar-base#1263](https://github.com/StellarCN/py-stellar-base/issues/1263) | ShapeCov | 2026-11-14 | [comment](https://github.com/StellarCN/py-stellar-base/issues/1263#issuecomment-6880903967) | Re-run on the new package: stellar-xdr 0.2.0 rejects the modified envelope from the issue. |

## Where the text of each report is kept

| ID | File |
|---|---|
| E1 | [`issues/E1-stellar-etl-token-transfer-pre23.md`](issues/E1-stellar-etl-token-transfer-pre23.md) |
| E2 | [`issues/E2-stellar-etl-multi-pool-revocation.md`](issues/E2-stellar-etl-multi-pool-revocation.md) |
| E3 | [`issues/E3-stellar-etl-revoked-pool-trustlines.md`](issues/E3-stellar-etl-revoked-pool-trustlines.md) |
| E4 | [`issues/E4-stellar-etl-one-ledger-range.md`](issues/E4-stellar-etl-one-ledger-range.md) |
| J1 | [`issues/J1-java-trailing-bytes.md`](issues/J1-java-trailing-bytes.md) |
| P1 | [`issues/P1-python-nonzero-padding.md`](issues/P1-python-nonzero-padding.md) |
| P2 | [`issues/P2-python-optional-flag.md`](issues/P2-python-optional-flag.md) |
| P1, P2 replies | [`issues/P-python-replies-draft.md`](issues/P-python-replies-draft.md) |
| stellar-docs#3165 | [`issues/D1-stellar-docs-indexer-hardening-page.md`](issues/D1-stellar-docs-indexer-hardening-page.md) |
| stellar-etl#448 | [`issues/E-stellar-etl-448-comment.md`](issues/E-stellar-etl-448-comment.md) |
| wallet-backend#677 | [`issues/W1-wallet-backend-meta-participants.md`](issues/W1-wallet-backend-meta-participants.md) |
| py-stellar-base#1264 | [`issues/X1-py-stellar-xdr-depth.md`](issues/X1-py-stellar-xdr-depth.md), [`issues/X2-py-stellar-xdr-typedef-codecs.md`](issues/X2-py-stellar-xdr-typedef-codecs.md) |
