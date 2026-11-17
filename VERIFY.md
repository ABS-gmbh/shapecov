# Verifying the RFP acceptance checks

## In five minutes, with Python only

```sh
git clone https://github.com/ABS-gmbh/shapecov && cd shapecov
pip install jsonschema
python3 quickcheck.py
```

Python 3.9 to 3.14 (CI runs both ends); no Docker, no SDK toolchain and no network after the clone. It prints one line per check, PASS or
FAIL, and the time it took. On a clean clone on an idle laptop the 16 fast checks took about **6 seconds**, run
in parallel. `python3 quickcheck.py --full` adds the unit tests and the mutation testing: 18 checks in
about **20 seconds** (measured 16 and 17 November 2026). CI runs `--full` on every push (`ci` › Unit tests).

What it reruns:
- every corpus entry decoded strictly, re-encoded to the same bytes, and checked against its
  manifest record, its hashes and the manifest's JSON Schema;
- the guide's tables against the corpus manifest, including the recorded stellar-core verdict for
  every row;
- the per-CAP table against the corpus;
- the headline numbers in the documentation against the repository;
- the unit tests of the checking scripts themselves (`tests/`).

What it checks from recorded results, against their expected verdicts:
- the wallet-backend, stellar-etl and Horizon replays: each sighting fails before its fix and passes
  after, and every oracle failure maps to a filed issue;
- the linter's report on wallet-backend;
- the detection backtest's claims (below, "Beyond the RFP's checks").

**What it does not rerun**, because it needs Docker, an SDK toolchain or the network:
- the comparison with stellar-core's golden files and the SDK round trips (`ci` › RFP check 1,
  and RFP checks 1 and 5);
- the replays themselves (`replay` › RFP check 2);
- the linter's own tests (`ci` › RFP check 3);
- the probes against a live stellar-core (`ci` › RFP check 4);
- the JavaScript sightings (`ci` › RFP checks 1 and 5);
- the memory budget, both passphrases and the Rust sightings (the `replay` workflow).

The script prints the same list.

## Every check, with its CI job

The RFP gives one "Check:" per deliverable. Each has a CI job named after it, so the
[`ci` workflow](https://github.com/ABS-gmbh/shapecov/actions/workflows/ci.yml?query=branch%3Amain)
and the [`replay` workflow](https://github.com/ABS-gmbh/shapecov/actions/workflows/replay.yml?query=branch%3Amain)
show them as green or red jobs. The commands below run the same checks on your own machine, from
the repository root. Build steps for the SDK runners are in `README.md`, "Run it".

| # | The RFP's check | Job | Command | Status |
|---|---|---|---|---|
| 1 | Corpus: "entries round-trip through rs-stellar-xdr and agree with --check-lcm goldens" | `ci` › RFP check 1, and `ci` › RFP checks 1 and 5 | `python tools/corpus_check.py --goldens <stellar-core checkout>` (the job fetches only `test-lcm-current/` at the commit the manifest names), then `python tools/corpus_check.py --sdks rust,js,python,python-xdr,go,java --core` | **Met.** Every entry round-trips byte for byte through rs-stellar-xdr and five other decoders, and stellar-core 30.0.0 decodes every one. The entries taken from stellar-core's goldens are byte-identical to the golden records. Entries mined from network history are not in core's golden set. |
| 2 | Replay harness: "reference adapter reproduces wallet-backend#729, #731 and #716 on pre-fix commits and passes on the fixed ones" | `replay` › RFP check 2 | `harness/replay/run.sh sightings` | **Met**, through both inputs (mock `getLedgers` and the Galexie layout). Results: `harness/replay/RESULTS.md`. The shapes each indexer mishandles or drops, one row per corpus shape with the issue that explains each failure: [`harness/replay/SHAPES.md`](harness/replay/SHAPES.md) (`python3 harness/replay/shapes.py`). The harness runs any indexer with an adapter: a toy one, [`harness/replay/adapters/example/`](harness/replay/adapters/example/), runs two variants of a 100-line indexer through the same interface; participants from the envelope fail the oracle's participant rule on all four recorded ledgers, participants from the meta pass (`python3 harness/replay/adapters/example/check.py`). |
| 3 | Linter: "flags seeded violations, runs clean on current wallet-backend" | `ci` › RFP check 3 | `cd linter && go test ./...`, then `scripts/run-wallet-backend.sh <commit>` and `python3 scripts/check_accepted.py results/wallet-backend-<sha12>.json accepted/wallet-backend.json` | **Partly met.** Seeded violations: met. On wallet-backend the linter reports 2 findings, both real, so it does **not** run clean; a false positive at a third site (a success check in the function called) was removed from the rule, with fixtures in both directions. CI checks that there is no finding outside [`linter/accepted/wallet-backend.json`](linter/accepted/wallet-backend.json), where each finding has a reason and, where one exists, an upstream issue (#820, #800). A second indexer, stellar-etl, is linted the same way (`ci` › linter on a second indexer, [`linter/accepted/stellar-etl.json`](linter/accepted/stellar-etl.json)): 13 findings, all real, 1 of them live (stellar-etl#504); its one false-positive class was fixed in the rule. See `linter/README.md`. |
| 4 | Guide: "the field-by-field table agrees with the corpus manifest; publication is gated on review by a core or platform engineer" | `ci` › RFP check 4 | `python guide/check_guide.py`, then `python guide/probe_core.py check` (Docker, stellar-core 30.0.0) | **Table: met, and checked against stellar-core itself.** 50 probes, plus one setup transaction (51 records in `guide/probes.json`), submit transactions that break, or sit just inside, the guide's rules to a local stellar-core 30.0.0, including the four fields the RFP's first rule names: signatures, sequence numbers, fees and time bounds. CI reruns them and fails if any answer changes. 19 of the 29 rows have a verdict from core on every side they make a claim about, 8 on one side, and 2 rows have no stellar-core verdict on either side; the guide lists which (section 1, "What stellar-core itself does with each row"). **Review: not yet.** The guide is unreviewed: no stellar-core or platform engineer has reviewed it. The gate is enforced: until the guide's review line is filled by the reviewer's own commit, the exported page opens with a not-reviewed caution, and `check_guide.py` fails if the page and the line disagree. [`guide/REVIEW.md`](guide/REVIEW.md) is the reviewer's brief. |
| 5 | Conformance runner: "reproduces js-stellar-sdk#1766, #1785 and #1789 on pre-fix tags" | `ci` › RFP checks 1 and 5 | `python tools/corpus_check.py --sdk-checks` (after `npm install` in `harness/sdk-semantic`) | **Met.** Each sighting fails on its pre-fix release and passes on the fix. Evidence: `corpus/evidence/js-stellar-sdk-17*.md`. |
| 6 | Findings: "every failure maps to a filed issue" | `ci` › RFP check 6 | `python .github/scripts/check_findings.py` | **Met for the committed replay results.** Every oracle failure is labelled with a filed upstream issue, or is an RFP sighting at its pre-fix commit, and each maps to a record in `FINDINGS.json`: 45 findings, each with issue link, component, severity (S1 to S4), CAPs (or why none), a reproducing corpus entry or generated case, first reporter, date and status. The table at the top of `FINDINGS.md` is generated from it. The job fails if a record lacks a field, a reproduction does not exist or does not fail on the named SDK, a failure, claimed sighting, reproduced RFP sighting or accepted linter finding maps to no record, or the table is stale. One exception to "a filed issue": a defect the maintainers fixed with no issue (R11, fixed in three commits) maps to its record through a `record:<ID>` label, and the job prints those failures apart from the ones with a filed issue. The 2 accepted linter findings on wallet-backend both cite an open issue (#820, #800); stellar-etl's accepted findings have their own reasons in `linter/accepted/stellar-etl.json`. **First finding fixed upstream:** java-stellar-sdk #833 (trailing bytes, filed 14 November) was fixed by the maintainer in #842 on 16 November. |

## Other requirements the RFP states

| The RFP's requirement | Job | Command | Status |
|---|---|---|---|
| "Generation must be reproducible for both testnet and mainnet passphrases" | `replay` › local stellar-core corpus entries regenerate identically on testnet and mainnet passphrases | `python3 tools/localcore_repro.py run --passphrase testnet` (and `pubnet`), then `check` | **Met for the entries a local stellar-core produces.** Entries mined from network history and core's golden files are fixed records, not generated. |
| The harness "handles a full corpus without unbounded memory growth" | `replay` › a 600 MB corpus is served within a 64 MB memory budget | `python3 harness/replay/memcheck.py --corpus-mb 600 --budget-mb 64` | **Met.** Measured locally: 1,389 ledgers at a 38 MB peak. |
| The 18 sightings the RFP cites | `replay` › RFP check 2; rs-stellar-xdr#598 and rs-soroban-sdk#2099 reproduce before their fixes and pass after; and `ci` › RFP checks 1 and 5 | `harness/sightings/run.sh`; scoreboard: [`harness/sightings/README.md`](harness/sightings/README.md) | **14 of 18 reproduced, all in CI.** The other 4 say why they cannot be reproduced. |
| "A conformance runner executes the corpus through at least the JS, Go and Rust SDKs in CI" | `ci` › Reusable sdk-conformance workflow (js, go); `ci` › Linter action | `.github/workflows/sdk-conformance.yml` (`workflow_call`), `linter/action.yml`; how to adopt: [`ADOPT.md`](ADOPT.md) | **Packaged for each SDK's own CI.** Any SDK repository can call the reusable workflow at its own version or commit, with its own known-failures file. Any Go indexer can run the linter action with an accepted-findings file. ShapeCov's CI calls both on every push: for js-stellar-sdk 17.4.0 (no known failures), for go-stellar-sdk v0.9.0 (its known trailing-byte defect listed), and for the linter on wallet-backend. |
| "The corpus covers rare patterns introduced or changed by each CAP" | — | `python3 tools/cap_coverage.py`; table: [`corpus/CAP-COVERAGE.md`](corpus/CAP-COVERAGE.md) | **Every live CAP accounted for:** of 70, 39 covered, 1 partly covered, 1 gap, and 29 with no shape a reader can see (on 16 November; the table is regenerated with the corpus). |
| "Built against the most recent stable Stellar tech stack, with a plan to track protocol upgrades" | — | `python3 protocol-drill/drill.py --next-xdr <stellar-xdr next> --core <stellar-core checkout>`; report: [`protocol-drill/REPORT.md`](protocol-drill/REPORT.md) | **Rehearsed.** Protocol 30 throughout; the upgrade runbook is in `MAINTENANCE.md`. The drill runs it against the next protocol: stellar-xdr's `next` branch adds no new cell, all 15,306 of stellar-core's `test-lcm-next` golden ledgers (13,893 at protocol 31) decode with today's schema, and a pending change (`lcm_v3`) would add one cell. Not in CI: it needs the two upstream checkouts. |

## Beyond the RFP's checks

| Question | Job | Command | Status |
|---|---|---|---|
| Detection backtest: would the harness have caught defects already fixed or reported upstream? | `replay` › detection backtest claims hold against the recorded replays | `python3 harness/replay/replay.py backtest` | **Measured, incomplete.** The harness detects 14 of wallet-backend's 17 in-scope fixes (5 on ledgers not chosen for the bug) and flags 8 of stellar-etl's 9 in-scope issues (1 blind). A wallet-backend fix counts as detected when a ledger fails at the commit before it and passes at the fix; an open stellar-etl issue, when the oracle flags its rows at `master`. The job fails if any claim, detected or missed, does not hold against the recorded replays. [`harness/replay/BACKTEST.md`](harness/replay/BACKTEST.md) names, for every miss, the shape, oracle rule or export that would catch it. |
| Mutation testing: does the oracle catch an indexer's mistakes, under control? | `ci` › Unit tests (`quickcheck.py --full`) | `python3 harness/replay/adapters/example/mutants.py` | **23 of the 23 mutants the corpus exercises are killed** on 17 ledgers: a toy indexer storing what the oracle checks is changed one bug at a time (the fee ignored, payments swapped, amounts from the envelope, amounts above 2^53 through float64, an account merge dropped, addresses truncated, participants from the envelope, every state change stored twice, and so on). Each mutant and the check that catches it are in [`MUTANTS.md`](harness/replay/adapters/example/MUTANTS.md). |

## What the checks do not cover

- The guide's review, which only a stellar-core or platform engineer can give.
- Fixes prepared for upstream issues (stellar-etl #512, wallet-backend #820). These are on local branches, awaiting issue acceptance, and are not part of this repository.
