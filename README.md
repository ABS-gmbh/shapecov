# ShapeCov

[![ci](https://github.com/ABS-gmbh/shapecov/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ABS-gmbh/shapecov/actions/workflows/ci.yml?query=branch%3Amain)
[![release](https://img.shields.io/github/v/release/ABS-gmbh/shapecov)](https://github.com/ABS-gmbh/shapecov/releases/latest)

ShapeCov tests software that reads the Stellar ledger against the rare but valid shapes the
protocol allows. It is for maintainers of indexers and SDKs. It has a corpus of real ledgers that
exercise those shapes, tagged by CAP, and a harness that replays them through an unmodified
indexer and checks every stored row against an oracle derived from the ledger itself. A
conformance runner feeds XDR generated from the protocol 30 schema to six SDK decoders and to
stellar-core. A linter catches the three ingestion mistakes the RFP names, and an
indexer-hardening guide has each rule checked against stellar-core. Built for the SCF RFP
"XDR/CAP-Coverage Audit Tool and Indexer-Hardening Guide".

| Deliverable | Where | The RFP's acceptance check | Status |
|---|---|---|---|
| Corpus: 105 entries, 102 of them real ledgers, with per-CAP coverage | [`corpus/`](corpus/), [`CAP-COVERAGE.md`](corpus/CAP-COVERAGE.md) | 1: entries round-trip through rs-stellar-xdr and match stellar-core's `--check-lcm` goldens | Met |
| Replay harness: wallet-backend (reference adapter), stellar-etl and Horizon | [`harness/replay/`](harness/replay/); shapes each indexer mishandles or drops: [`SHAPES.md`](harness/replay/SHAPES.md) | 2: wallet-backend #729, #731 and #716 fail before their fixes and pass after | Met |
| Linter for the three ingestion mistakes | [`linter/`](linter/) | 3: flags seeded violations, runs clean on wallet-backend | Partly met: 2 findings on wallet-backend, both real, each with an open upstream issue; also run on stellar-etl |
| Indexer-hardening guide | [`guide/`](guide/) | 4: tables agree with the manifest; publication gated on review | Tables met and probed against stellar-core 30.0.0; publication gate enforced by the export; **unreviewed** |
| Conformance runner: six SDK decoders and stellar-core | [`runners/`](runners/), [`sdk-matrix/`](sdk-matrix/MATRIX.md) | 5: js-stellar-sdk #1766, #1785 and #1789 fail on pre-fix tags | Met; the same behaviour checks run in Go, Java, Rust and both Python SDKs, and java-stellar-sdk 6.0.0 shares three of the JavaScript defects |
| Findings | [`FINDINGS.md`](FINDINGS.md), [`FINDINGS.json`](FINDINGS.json) | 6: every failure maps to a filed issue | Met for the committed results |

Each check is a CI job of the same name. [`VERIFY.md`](VERIFY.md) gives every job and the command
that runs it on your machine.

## Check it in under 15 seconds

```bash
pip install jsonschema
python3 quickcheck.py
```

Python only, with no Docker and no network. It reruns, in parallel, the 16 fast checks that work from
the repository alone, and checks the recorded results of the rest against their verdicts, in about
6 seconds on an idle laptop. `python3 quickcheck.py --full` adds the unit tests and the mutation
testing, 18 checks in about 20 seconds on an idle laptop; CI runs it on every push, and reruns everything else.

## Results

- **8 defects found, filed in 7 issues** in java-stellar-sdk, py-stellar-base and stellar-etl. The Java
  maintainer fixed #833 two days after it was filed; py-stellar-base closed #1262 and #1263 as
  fixed in its replacement XDR package, and feedback on that package's API led to a documentation
  change about five hours later ([py-stellar-xdr#24](https://github.com/lightsail-network/py-stellar-xdr/pull/24)). All 42 findings, with severity, CAPs and a reproducing
  entry each: [`FINDINGS.md`](FINDINGS.md).
- **13 of the RFP's 18 sightings reproduced**, all in CI, each failing before its fix and passing
  after ([`harness/sightings/README.md`](harness/sightings/README.md)).
- **Every corpus ledger is an indexer test.** The oracle derives the expected rows from the ledger;
  every failure in wallet-backend, stellar-etl and Horizon maps to a filed issue or, for one defect
  wallet-backend fixed without an issue, to its finding record (R11). A sweep of 611 further
  network ledgers (100,676 transactions) made 1,764,854 checks on real traffic: the 99,379 that did
  not meet the oracle map to eight open upstream issues, and none is unexplained.
- **Backtest on past fixes**, measured and incomplete: the harness detects 13 of wallet-backend's 17
  in-scope fixes (5 on ledgers not chosen for the bug) and flags 7 of stellar-etl's 9 in-scope issues
  (1 blind). Every miss names the shape, oracle rule or export that would catch it
  ([`BACKTEST.md`](harness/replay/BACKTEST.md)).
- **7,392 generated cases across all 477 types**, run through six decoders and stellar-core
  30.0.0; valid cases reach 549 of the 659 schema cells (83.3%).
- **Usable from other repositories**: a reusable conformance workflow and a linter action
  ([`ADOPT.md`](ADOPT.md)), and release assets with build provenance.

## Limits

- The hardening guide is **unreviewed**. The RFP requires review by a stellar-core or platform
  engineer before publication, and that has not happened. What the reviewer is asked to do, and the
  11 statements (sides of 10 rows) that rest on a source citation alone: [`guide/REVIEW.md`](guide/REVIEW.md). Until the
  guide's review line is filled, the page exported for developers.stellar.org opens with a caution
  that it is unreviewed, and the guide check fails if the two disagree.
- Three replay adapters exist: wallet-backend, stellar-etl and Horizon
  ([`RESULTS-horizon.md`](harness/replay/RESULTS-horizon.md)). Other indexers are not built. A toy one, [`adapters/example/`](harness/replay/adapters/example/), shows the interface in
  about 100 lines and the participant rule on two variants of the same indexer.
- Whole ledgers are not generated. They come from network history, stellar-core's golden files and
  fixed local stellar-core scenarios, so 422 of the 538 cells a ledger reader can meet (78.4%)
  appear in a corpus entry, and 422 of the 502 that can occur in a closed ledger (84.1%).
  Each of the other 116 is classified in [`corpus/COVERAGE.md`](corpus/COVERAGE.md): 36 can never be in a
  closed ledger, 17 predate protocol 20, 24 need a configuration upgrade, 12 are failures a local
  stellar-core scenario can produce, 6 need a purpose-written contract, 5 appear only in recorded
  consensus messages, 1 is impractical, and 15 are not yet classified.

More: [`ARCHITECTURE.md`](ARCHITECTURE.md) (how the parts fit, the adapter interface, isolation),
[`STATUS.md`](STATUS.md) (dated log), [`MAINTENANCE.md`](MAINTENANCE.md),
[`INFRASTRUCTURE.md`](INFRASTRUCTURE.md) and [`THREAT-MODEL.md`](THREAT-MODEL.md).

## What it does

1. `tools/xdrschema.py` parses the `.x` files from `stellar/stellar-xdr` tag v30.0 into a plain
   schema: 477 types, 392 union arms, 605 enum members.
2. `tools/gen.py` walks that schema and encodes values directly, sharing no code with any SDK.
   - Valid cases are biased toward boundaries: extreme integers, empty and maximum-length vectors,
     non-UTF-8 strings, every union arm.
   - Faulty cases carry exactly one named fault that RFC 4506 says a decoder must reject:
     non-zero padding, an optional flag other than 0 or 1, a length over the declared maximum,
     an absurd length prefix, trailing bytes, truncation, and two more (see `FINDINGS.md`).
3. `tools/run.py` feeds the cases to one small runner per SDK. A runner that crashes or hangs
   loses only the case it was on.
4. `tools/diff.py` compares each SDK with the reference decoder and clusters disagreements into
   `out/REPORT.md`.
5. `tools/core_oracle.sh` runs the cases for the seven types `stellar-core print-xdr` can decode
   through stellar-core 30.0.0 itself, so "valid" and "invalid" are checked against the network's
   own decoder and not only against another library.

## Decoders under test

| Decoder | Version | How it runs |
|---|---|---|
| rs-stellar-xdr (reference) | stellar-xdr 30.0.0 | local cargo build |
| JavaScript | @stellar/stellar-sdk 17.4.0 | local node |
| Python | stellar-sdk 17.0.1 | local venv |
| Python, next major | stellar-xdr 0.2.1, stellar-strkey 0.2.0 (replacing `stellar_sdk.xdr` and `.strkey`) | local venv; see `runners/python-xdr/` |
| Go | go-stellar-sdk v0.9.0 | Docker, `golang:1.26` |
| Java | network.lightsail:stellar-sdk 6.0.0 | Docker, `maven:3.9-eclipse-temurin-21` |
| stellar-core | 30.0.0 (0e49751aa) | Docker, `stellar/stellar-core`, amd64 |

## Conformance results in detail

The headline results are at the top of this file. The detail behind the conformance half:

- The independent encoder and the reference decoder agree byte for byte on every valid generated
  case the reference has a type for (3,808 of them).
- 943 further cases for the seven types stellar-core's `print-xdr` can decode. stellar-core accepts
  all 280 valid ones.
- Valid cases exercise 549 of 659 schema cells (83.3%), and 448 of the 538 a ledger reader can
  meet. A cell is a union arm, or a member of an enum used as a value; the members of the 73 enums
  used only as union discriminants are covered exactly when their arm is (`corpus/coverage.json`).
- Confirmed disagreements are in `FINDINGS.md`. Full clusters are in `out/REPORT.md`. Which SDK
  release has which defect, codec faults and behaviour above the codec alike, is in
  [`sdk-matrix/MATRIX.md`](sdk-matrix/MATRIX.md).
- stellar-xdr 0.2.1, the package replacing `stellar_sdk.xdr`, agrees with the reference on every
  generated case and every corpus entry, and fixes P1 and P2; stellar-strkey 0.2.0 passes all of
  SEP-23 1.4.0's 36 vectors and 136 generated mutations. Two API points for before 1.0 are drafted in
  `issues/` (see `runners/python-xdr/README.md`).

Accepted cases per decoder, core-decodable types only (from the stellar-core run; its raw
results are not in the repository):

| Case kind | Cases | stellar-core | rs-stellar-xdr | JS | Python | Go | Java |
|---|---|---|---|---|---|---|---|
| valid | 280 | 280 | 280 | 280 | 280 | 280 | 280 |
| non-zero padding | 41 | 0 | 0 | 0 | 41 | 0 | 0 |
| optional flag not 0/1 | 46 | 0 | 0 | 0 | 46 | 0 | 0 |
| trailing bytes | 140 | 0 | 0 | 0 | 0 | 27 | 140 |
| truncated | 140 | 0 | 0 | 0 | 0 | 0 | 0 |
| length over maximum | 61 | 0 | 0 | 0 | 0 | 0 | 0 |
| absurd length prefix | 91 | 0 | 0 | 0 | 0 | 0 | 0 |

## Corpus

`corpus/` holds 105 entries and their manifest. `corpus/README.md` describes every field;
`corpus/evidence/` records the reproduced sightings and our findings. Three examples:

| Entry | Type | Source | Shows |
|---|---|---|---|
| `testnet-4437357-signed-payload-signer` | LedgerCloseMeta | real testnet ledger, protocol 28 | CAP-0040 signer; reproduces wallet-backend #729 |
| `synthetic-scmap-colliding-keys` | TransactionMeta | generated | map keys that print the same; reproduces js-stellar-sdk #1789 |
| `synthetic-muxed-contract-address` | TransactionEnvelope | generated | CAP-0084 address type that is new in protocol 30 |

- `tools/decode.py` and `tools/encode.py` are a strict decoder and an encoder driven by the same
  schema as the generator. The decoder accepts all 3,816 valid generated cases, rejects all 3,576
  faulty ones, and re-encodes every valid case and every corpus entry byte for byte.
- Every schema cell is dated to the stellar-xdr release that introduced it: `tools/cell_protocols.py`
  parses each tag from v19 to v30.0 with ShapeCov's own schema parser (`corpus/cell-protocols.json`).
  The hand-assigned CAP tags are checked against those dates, and all 40 agree.
  `corpus/CAP-COVERAGE.md` shows, per protocol, how many of the cells it introduced are in the
  corpus.
- `tools/corpus_check.py` re-verifies the manifest and every entry: schema, hashes, expected
  decoded values, source record, CAP and protocol tags, then the six SDKs and stellar-core.
- `harness/replay/` replays LedgerCloseMeta entries through a real indexer and its database, over
  a mock stellar-rpc `getLedgers` or the Galexie data-lake layout, and reports pass, mishandled or
  dropped per entry and commit. The adapter contract is in `harness/replay/ADAPTER.md`.
- `tools/oracle.py` derives from any ledger what changed in ledger state, including every account's
  net balance change, so every corpus ledger is a test of the indexer, not only the ones with
  hand-written expectations.
- `harness/replay/adapters/stellar-etl/` runs the same ledgers through stellar-etl's own export
  commands, reading the data lake through its GCS client, and checks its effects and token
  transfers against the same oracle. It found E1 to E3 in `FINDINGS.md`. Its entry-change export
  (accounts, trustlines, offers, pools, claimable balances) is checked on sequences of consecutive
  ledgers only: given one ledger it writes nothing (`harness/replay/README.md`, "stellar-etl").
- `harness/wallet-backend/` is the earlier, database-free version: it calls wallet-backend's
  `indexer.ProcessLedger` from a Go test.
- `harness/sdk-semantic/` runs the manifest's SDK checks against pinned SDK versions: every
  js-stellar-sdk release from 16.3.0 to 17.4.0, and the same behaviour checks in Go, Java, Rust and
  both Python SDKs (`siblings.py`).

```bash
python3 tools/corpus_build.py
python3 tools/corpus_check.py --sdks rust,js,python,python-xdr,go,java --core --sdk-checks
```

## Run it

```bash
python3 tools/xdrschema.py schema/x schema/schema.json
python3 tools/gen.py schema/schema.json out/cases.jsonl --valid 8 --faulty 2
python3 tools/run.py out/cases.jsonl
python3 tools/diff.py out/cases.jsonl
```

Build steps for the runners (one time): `cargo build --release` in `runners/rust`, `npm install`
in `runners/js`, a venv with `stellar-sdk==17.0.1` in `runners/python`, a venv with
`runners/python-xdr/requirements.txt` in `runners/python-xdr`, `runners/go/build.sh`
inside `golang:1.26`, and `mvn dependency:copy-dependencies -DoutputDirectory=lib` plus
`javac -cp 'lib/*' Runner.java` inside the Maven image.

## CI

Five GitHub Actions workflows in `.github/workflows/`; [`VERIFY.md`](VERIFY.md) maps each RFP check
to its job and command. The check to look at is `green`, the last job of `ci.yml`: it passes only if
every other job passed, or was skipped on purpose.

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every push and pull request, and weekly | `green`, which needs every job below. One job per RFP acceptance check: the corpus against stellar-core's goldens (check 1), the linter on wallet-backend and on stellar-etl (check 3), the guide and its probes against stellar-core (check 4), every entry through six SDKs, stellar-core and the pinned-SDK and sibling behaviour checks (checks 1 and 5), the findings records (check 6). Also: the count check, the unit tests with coverage and `quickcheck.py --full` (which includes the mutation test), the security checks and the network isolation test, and the reusable workflow and linter action as other repositories call them; `python3 quickcheck.py` as the README runs it; and `replay.yml`, on every push to main and on changes to a replay path. |
| `replay.yml` | called by `ci.yml` (every push to main; pull requests and branch pushes that touch the harness or the corpus), weekly, and on demand | Six jobs: the RFP's wallet-backend sightings before and after their fixes (check 2), every ledger through stellar-etl, the memory budget, the local stellar-core entries regenerated on both passphrases, the Rust sightings, and the detection backtest's claims. |
| `sdk-conformance.yml` | called by `ci.yml`, or by another repository | The corpus through one SDK at the caller's version ([`ADOPT.md`](ADOPT.md)). |
| `release.yml` | on a version tag | The corpus archive and linter binaries, with `SHA256SUMS` and build provenance; refuses a tag whose commit is not on main or has no passing `green` check. |
| `upstream-drift.yml` | weekly | One issue per upstream release newer than the pinned one, and image tags that moved. |

## Infrastructure and maintenance

- [`INFRASTRUCTURE.md`](INFRASTRUCTURE.md): what the tools run on, every network connection they
  make, the Docker images and disk they need, and user tracking (there is none).
- [`MAINTENANCE.md`](MAINTENANCE.md): who maintains ShapeCov and for how long, routine work, and the
  step-by-step plan for each protocol upgrade.

## Known artefacts in the current numbers

- Go shows 8 "valid" disagreements. All are the root type `SponsorshipDescriptor`, a typedef of an
  optional, which the runner allocates wrongly. It is a runner bug, not an SDK bug.
- JS has no value-level encoder for bare primitive and vector typedefs (`uint32`, `SCVec`, ...).
  Those cases are counted as unsupported, not as disagreements.
- The `bool_not_01` row in `out/REPORT.md` shows every SDK "disagreeing". The reference decoder is
  the odd one out there; see `FINDINGS.md`.

## Not built

- Whole ledgers from the generator's cases. Generated cases are checked by the decoders and by
  stellar-core as a decoder. Whole ledgers come from fixed local stellar-core scenarios
  (`tools/localcore.py`), and the guide's probes submit transactions to a local stellar-core
  (`guide/probe_core.py`).
- Behaviour checks above the codec beyond the six in the SDK matrix (issuer ordering, map key order,
  colliding map keys twice, out-of-range IDs, string bytes) and transaction decoding. Those run in
  every SDK that has the helper.
- Coverage of the 110 schema cells no valid case reaches yet.
- Replay adapters beyond wallet-backend, stellar-etl and Horizon. Three corpus entries have hand-written
  `expected.indexer` rows; the oracle checks every ledger. See `harness/replay/README.md`, "Limits".
- CAP tags are assigned by hand from the CAP texts, then checked against the XDR history.
  stellar-xdr has no v29 tag, so cells added in protocols 29 and 30 are dated together.
- Review of the hardening guide by a stellar-core or platform engineer, which the RFP requires
  before publication.
- The linter does not run clean on wallet-backend `main` (2 findings, both real, both with an open
  upstream issue) or on stellar-etl
  (13, all real, 12 of them in uncalled code). CI fails on any finding outside the accepted lists
  in `linter/accepted/` (see `linter/README.md`).

## Licence

Apache-2.0, see `LICENSE`. Material from other projects keeps its own terms:
[`NOTICE`](NOTICE) lists each source, its licence and the commit or location it came from: the
stellar-xdr definitions in `schema/`, the 46 corpus entries copied from stellar-core's golden files,
the 30 ledgers from Stellar's public archive, and the prettier configuration from stellar-docs. It
is generated from `corpus/manifest.json` and `schema/SOURCE` by `.github/scripts/notice.py`, and the
quick check fails if it is out of date.
