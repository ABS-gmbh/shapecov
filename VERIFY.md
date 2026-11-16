# Verifying the RFP acceptance checks

The RFP gives one "Check:" per deliverable. Each has a CI job named after it, so the
[`ci` workflow](https://github.com/ABS-gmbh/shapecov/actions/workflows/ci.yml?query=branch%3Amain)
and the [`replay` workflow](https://github.com/ABS-gmbh/shapecov/actions/workflows/replay.yml?query=branch%3Amain)
show them as green or red jobs. The commands below run the same checks on your own machine, from
the repository root. Build steps for the SDK runners are in `README.md`, "Run it".

| # | The RFP's check | Job | Command | Status |
|---|---|---|---|---|
| 1 | Corpus: "entries round-trip through rs-stellar-xdr and agree with --check-lcm goldens" | `ci` › RFP check 1, and `ci` › RFP checks 1 and 5 | `python tools/corpus_check.py --goldens <stellar-core checkout>` (the job fetches only `test-lcm-current/` at the commit the manifest names), then `python tools/corpus_check.py --sdks rust,js,python,python-xdr,go,java --core` | **Met.** Every entry round-trips byte for byte through rs-stellar-xdr and five other decoders, and stellar-core 30.0.0 decodes every one. The entries taken from stellar-core's goldens are byte-identical to the golden records. Entries mined from network history are not in core's golden set. |
| 2 | Replay harness: "reference adapter reproduces wallet-backend#729, #731 and #716 on pre-fix commits and passes on the fixed ones" | `replay` › sightings reproduce before their fixes and pass after | `harness/replay/run.sh sightings` | **Met**, through both inputs (mock `getLedgers` and the Galexie layout). Results: `harness/replay/RESULTS.md`. |
| 3 | Linter: "flags seeded violations, runs clean on current wallet-backend" | `ci` › RFP check 3 | `cd linter && go test ./...`, then `scripts/run-wallet-backend.sh <commit>` and `python3 scripts/check_accepted.py results/wallet-backend-<sha12>.json accepted/wallet-backend.json` | **Partly met.** Seeded violations: met. On wallet-backend the linter reports 4 real findings, so it does **not** run clean. CI checks that there is no finding outside [`linter/accepted/wallet-backend.json`](linter/accepted/wallet-backend.json), where each finding has a reason and, where one exists, an upstream issue (#820, #800). See `linter/README.md`. |
| 4 | Guide: "the field-by-field table agrees with the corpus manifest; publication is gated on review by a core or platform engineer" | `ci` › RFP check 4 | `python guide/check_guide.py` | **Table: met. Review: not yet.** The guide is a draft and no stellar-core or platform engineer has reviewed it. |
| 5 | Conformance runner: "reproduces js-stellar-sdk#1766, #1785 and #1789 on pre-fix tags" | `ci` › RFP checks 1 and 5 | `python tools/corpus_check.py --sdk-checks` (after `npm install` in `harness/sdk-semantic`) | **Met.** Each sighting fails on its pre-fix release and passes on the fix. Evidence: `corpus/evidence/js-stellar-sdk-17*.md`. |
| 6 | Findings: "every failure maps to a filed issue" | `ci` › RFP check 6 | `python .github/scripts/check_findings.py` | **Met for the committed replay results.** Every oracle failure is labelled with a filed upstream issue, or is an RFP sighting at its pre-fix commit. The issues are listed in `FINDINGS.md`. The 4 accepted linter findings: 2 cite an issue; the other 2 (one design choice, at one site) have a written reason and no issue. |

## What the checks do not cover

- The guide's review, which only a stellar-core or platform engineer can give.
- Reproducibility of generated entries on the mainnet passphrase.
- A measured memory bound for the harness.
- Fixes prepared for upstream issues (stellar-etl #512, wallet-backend #820). These are on local branches, awaiting issue acceptance, and are not part of this repository.
