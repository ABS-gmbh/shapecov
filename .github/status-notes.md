# Status notes

Written by hand; `.github/scripts/status_log.py` merges them into STATUS.md. One section per UTC day
(the heading must match STATUS.md's, for example "16 November 2026"): what changed for someone using
ShapeCov, in a few sentences. The "Next" section lists what the repository itself says is open; it
makes no promise of dates.

## Next

- Review of the indexer-hardening guide by a stellar-core or platform engineer, which the RFP
  requires before publication (`VERIFY.md`, check 4).
- The linter's 4 findings on wallet-backend are real and triaged, so RFP check 3 is partly met. The
  fix prepared for wallet-backend #820 waits for the issue to be accepted (`VERIFY.md`, check 3).
- The fix prepared for stellar-etl #512 waits for the issue to be accepted.
- The detection backtest's misses, each with what would catch it (`harness/replay/BACKTEST.md`):
  oracle rules for stellar-etl #456, #457 and #462, whose shapes the corpus already has; for
  wallet-backend, reading its current-state tables and new local stellar-core scenarios.
- Replay adapters beyond wallet-backend and stellar-etl, for example Horizon (`README.md`, Limits).
- Schema cells that no corpus entry carries yet, listed by protocol in `corpus/CAP-COVERAGE.md`.

## 16 November 2026

The repository is now organised around the RFP's acceptance checks: one CI job per check,
`VERIFY.md` mapping each to its command, a ten-second Python-only check, and release v0.1.0. The
java-stellar-sdk maintainer fixed #833 two days after it was filed, py-stellar-base closed #1262 and
#1263 as fixed in its new XDR package, and we corrected the impact stated on stellar-etl #512 (only
sources with TransactionMeta older than v4). Every row of the guide's field tables now carries
stellar-core's own verdict from probes, and the corpus grew to 88 entries. New tools: a sweep and
census of 611 network ledgers, a protocol-upgrade drill, a cross-SDK defect matrix, a detection
backtest, packaging for other repositories' CI, findings kept as checked records, and unit tests.

## 15 November 2026

The indexer half arrived. A replay harness runs wallet-backend's own ingestion against a real
database, fed through a mock stellar-rpc or a Galexie data lake, and reproduces wallet-backend #731
and the muxed half of #716 before their fixes. A ledger-state oracle makes every corpus ledger a
test with no hand-written expectations; run through stellar-etl, it found three defects, filed as
stellar-etl #512, #513 and #514. Also new: the linter for the three ingestion mistakes the RFP
names, the first draft of the hardening guide, a local stellar-core generator for shapes the
networks rarely show, and CI.

## 14 November 2026

The first code: a conformance runner that generates XDR values for every type of the protocol 30
schema and runs them through five decoders and stellar-core. Its first run found three decoding
defects, filed the same day: java-stellar-sdk #833 and py-stellar-base #1262 and #1263. Licensed
Apache-2.0.
