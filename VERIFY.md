# Verifying the RFP acceptance checks

The RFP gives one "Check:" per deliverable. Each has a CI job named after it, so the
[`ci` workflow](https://github.com/ABS-gmbh/shapecov/actions/workflows/ci.yml?query=branch%3Amain)
and the [`replay` workflow](https://github.com/ABS-gmbh/shapecov/actions/workflows/replay.yml?query=branch%3Amain)
show them as green or red jobs. The commands below run the same checks on your own machine, from
the repository root. Build steps for the SDK runners are in `README.md`, "Run it".

| # | The RFP's check | Job | Command | Status |
|---|---|---|---|---|
| 1 | Corpus: "entries round-trip through rs-stellar-xdr and agree with --check-lcm goldens" | `ci` › RFP check 1, and `ci` › RFP checks 1 and 5 | `python tools/corpus_check.py --goldens <stellar-core checkout>` (the job fetches only `test-lcm-current/` at the commit the manifest names), then `python tools/corpus_check.py --sdks rust,js,python,python-xdr,go,java --core` | **Met.** Every entry round-trips byte for byte through rs-stellar-xdr and five other decoders, and stellar-core 30.0.0 decodes every one. The entries taken from stellar-core's goldens are byte-identical to the golden records. Entries mined from network history are not in core's golden set. |
| 2 | Replay harness: "reference adapter reproduces wallet-backend#729, #731 and #716 on pre-fix commits and passes on the fixed ones" | `replay` › RFP check 2 | `harness/replay/run.sh sightings` | **Met**, through both inputs (mock `getLedgers` and the Galexie layout). Results: `harness/replay/RESULTS.md`. |
| 3 | Linter: "flags seeded violations, runs clean on current wallet-backend" | `ci` › RFP check 3 | `cd linter && go test ./...`, then `scripts/run-wallet-backend.sh <commit>` and `python3 scripts/check_accepted.py results/wallet-backend-<sha12>.json accepted/wallet-backend.json` | **Partly met.** Seeded violations: met. On wallet-backend the linter reports 4 real findings, so it does **not** run clean. CI checks that there is no finding outside [`linter/accepted/wallet-backend.json`](linter/accepted/wallet-backend.json), where each finding has a reason and, where one exists, an upstream issue (#820, #800). See `linter/README.md`. |
| 4 | Guide: "the field-by-field table agrees with the corpus manifest; publication is gated on review by a core or platform engineer" | `ci` › RFP check 4 | `python guide/check_guide.py` | **Table: met. Review: not yet.** The guide is a draft and no stellar-core or platform engineer has reviewed it. |
| 5 | Conformance runner: "reproduces js-stellar-sdk#1766, #1785 and #1789 on pre-fix tags" | `ci` › RFP checks 1 and 5 | `python tools/corpus_check.py --sdk-checks` (after `npm install` in `harness/sdk-semantic`) | **Met.** Each sighting fails on its pre-fix release and passes on the fix. Evidence: `corpus/evidence/js-stellar-sdk-17*.md`. |
| 6 | Findings: "every failure maps to a filed issue" | `ci` › RFP check 6 | `python .github/scripts/check_findings.py` | **Met for the committed replay results.** Every oracle failure is labelled with a filed upstream issue, or is an RFP sighting at its pre-fix commit. The issues are listed in `FINDINGS.md`. The 4 accepted linter findings: 2 cite an issue; the other 2 (one design choice, at one site) have a written reason and no issue. **First finding fixed upstream:** java-stellar-sdk #833 (trailing bytes, filed 14 November) was fixed by the maintainer in #842 on 16 November. |

## Other requirements the RFP states

| The RFP's requirement | Job | Command | Status |
|---|---|---|---|
| "Generation must be reproducible for both testnet and mainnet passphrases" | `replay` › local stellar-core corpus entries regenerate identically on testnet and mainnet passphrases | `python3 tools/localcore_repro.py run --passphrase testnet` (and `pubnet`), then `check` | **Met for the entries a local stellar-core produces.** Entries mined from network history and core's golden files are fixed records, not generated. |
| The harness "handles a full corpus without unbounded memory growth" | `replay` › a 600 MB corpus is served within a 64 MB memory budget | `python3 harness/replay/memcheck.py --corpus-mb 600 --budget-mb 64` | **Met.** Measured locally: 1,389 ledgers at a 38 MB peak. |
| The 18 sightings the RFP cites | `replay` › RFP check 2; rs-stellar-xdr#598 and rs-soroban-sdk#2099 reproduce before their fixes and pass after; and `ci` › RFP checks 1 and 5 | `harness/sightings/run.sh`; scoreboard: [`harness/sightings/README.md`](harness/sightings/README.md) | **12 of 18 reproduced, all in CI.** The other 6 say why they cannot be reproduced. |
| "The corpus covers rare patterns introduced or changed by each CAP" | — | `python3 tools/cap_coverage.py`; table: [`corpus/CAP-COVERAGE.md`](corpus/CAP-COVERAGE.md) | **Every live CAP accounted for:** of 70, 38 covered, 2 partly covered, 1 gap, and 29 with no shape a reader can see. |

## What the checks do not cover

- The guide's review, which only a stellar-core or platform engineer can give.
- Fixes prepared for upstream issues (stellar-etl #512, wallet-backend #820). These are on local branches, awaiting issue acceptance, and are not part of this repository.
