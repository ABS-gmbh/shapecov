# ShapeCov

[![ci](https://github.com/ABS-gmbh/shapecov/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ABS-gmbh/shapecov/actions/workflows/ci.yml?query=branch%3Amain)
[![replay](https://github.com/ABS-gmbh/shapecov/actions/workflows/replay.yml/badge.svg?branch=main)](https://github.com/ABS-gmbh/shapecov/actions/workflows/replay.yml?query=branch%3Amain)
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
| Corpus: 90 entries, 87 of them real ledgers, with per-CAP coverage | [`corpus/`](corpus/), [`CAP-COVERAGE.md`](corpus/CAP-COVERAGE.md) | 1: entries round-trip through rs-stellar-xdr and match stellar-core's `--check-lcm` goldens | Met |
| Replay harness: wallet-backend (reference adapter) and stellar-etl | [`harness/replay/`](harness/replay/); shapes each indexer mishandles or drops: [`SHAPES.md`](harness/replay/SHAPES.md) | 2: wallet-backend #729, #731 and #716 fail before their fixes and pass after | Met |
| Linter for the three ingestion mistakes | [`linter/`](linter/) | 3: flags seeded violations, runs clean on wallet-backend | Partly met: 4 real findings on wallet-backend, each triaged with a reason; also run on stellar-etl |
| Indexer-hardening guide | [`guide/`](guide/) | 4: tables agree with the manifest; publication gated on review | Tables met and probed against stellar-core 30.0.0; **unreviewed** |
| Conformance runner: six SDK decoders and stellar-core | [`runners/`](runners/), [`sdk-matrix/`](sdk-matrix/MATRIX.md) | 5: js-stellar-sdk #1766, #1785 and #1789 fail on pre-fix tags | Met |
| Findings | [`FINDINGS.md`](FINDINGS.md), [`FINDINGS.json`](FINDINGS.json) | 6: every failure maps to a filed issue | Met for the committed results |

Each check is a CI job of the same name. [`VERIFY.md`](VERIFY.md) gives every job and the command
that runs it on your machine.

## Check it in 10 seconds

```bash
pip install jsonschema
python3 quickcheck.py
```

Python only, with no Docker and no network. It reruns the 11 checks that work from the repository
alone and checks the recorded results of the rest against their verdicts. It took 10 seconds on a
laptop. CI reruns everything else.

## Results

- **6 defects found and filed** in java-stellar-sdk, py-stellar-base and stellar-etl. The Java
  maintainer fixed #833 two days after it was filed; py-stellar-base closed #1262 and #1263 as
  fixed in its replacement XDR package. All 33 findings, with severity, CAPs and a reproducing
  entry each: [`FINDINGS.md`](FINDINGS.md).
- **12 of the RFP's 18 sightings reproduced**, all in CI, each failing before its fix and passing
  after ([`harness/sightings/README.md`](harness/sightings/README.md)).
- **Every corpus ledger is an indexer test.** The oracle derives the expected rows from the ledger;
  every failure in wallet-backend and stellar-etl maps to a filed issue. A sweep of 611 further
  network ledgers (100,676 transactions) found no new defect.
- **Backtest on past fixes**, measured and incomplete: the harness detects 7 of wallet-backend's 17
  in-scope fixes (4 on ledgers not chosen for the bug) and flags 3 of stellar-etl's 9 in-scope issues
  (1 blind). Every miss names the shape, oracle rule or export that would catch it
  ([`BACKTEST.md`](harness/replay/BACKTEST.md)).
- **7,392 generated cases across all 477 types**, run through six decoders and stellar-core
  30.0.0; valid cases reach 549 of the 659 schema cells (83.3%).
- **Usable from other repositories**: a reusable conformance workflow and a linter action
  ([`ADOPT.md`](ADOPT.md)), and release assets with build provenance.

## Limits

- The hardening guide is **unreviewed**. The RFP requires review by a stellar-core or platform
  engineer before publication, and that has not happened.
- Two replay adapters exist, wallet-backend and stellar-etl. Others, such as Horizon, are not
  built.
- Whole ledgers are not generated. They come from network history, stellar-core's golden files and
  fixed local stellar-core scenarios, so 352 of the 538 cells a ledger reader can meet (65.4%)
  appear in a corpus entry. Each of the other 186 is classified in
  [`corpus/COVERAGE.md`](corpus/COVERAGE.md): 36 can never be in a closed ledger, 14 predate
  protocol 20, 30 need a network or configuration upgrade, 79 are failures a local stellar-core
  scenario can produce, 6 need a purpose-written contract, 5 appear only in recorded consensus
  messages, 1 is impractical, and 15 are not yet classified.

More: [`ARCHITECTURE.md`](ARCHITECTURE.md) (how the parts fit, the adapter interface, isolation),
[`STATUS.md`](STATUS.md) (dated log), [`MAINTENANCE.md`](MAINTENANCE.md) and
[`INFRASTRUCTURE.md`](INFRASTRUCTURE.md).

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

## Results so far

- 7,392 cases across all 477 types. The independent encoder and the reference decoder agree
  byte for byte on every valid case (3,808 of 3,808 that the reference has a type for).
- 943 further cases for the seven core-decodable types. stellar-core accepts all 280 valid ones.
- Valid cases exercise 549 of 659 schema cells (83.3%), and 448 of the 538 a ledger reader can
  meet. A cell is a union arm, or a member of an enum used as a value; the members of the 73 enums
  used only as union discriminants are covered exactly when their arm is (`corpus/coverage.json`).
- Confirmed disagreements are in `FINDINGS.md`. Full clusters are in `out/REPORT.md`.
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

`corpus/` holds 90 entries and their manifest. `corpus/README.md` describes every field;
`corpus/evidence/` records the reproduced sightings and our findings. Three examples:

| Entry | Type | Source | Shows |
|---|---|---|---|
| `testnet-4437357-signed-payload-signer` | LedgerCloseMeta | real testnet ledger, protocol 28 | CAP-0040 signer; reproduces wallet-backend #729 |
| `synthetic-scmap-colliding-keys` | TransactionMeta | generated | map keys that print the same; reproduces js-stellar-sdk #1789 |
| `synthetic-muxed-contract-address` | TransactionEnvelope | generated | CAP-0084 address type that is new in protocol 30 |

- `tools/decode.py` and `tools/encode.py` are a strict decoder and an encoder driven by the same
  schema as the generator. The decoder accepts all 3,816 valid generated cases, rejects all 3,576
  faulty ones, and re-encodes every valid case and the real ledger byte for byte.
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
  transfers against the same oracle. It found E1 to E3 in `FINDINGS.md`.
- `harness/wallet-backend/` is the earlier, database-free version: it calls wallet-backend's
  `indexer.ProcessLedger` from a Go test.
- `harness/sdk-semantic/` runs the manifest's SDK checks against pinned SDK versions.

```bash
python3 tools/corpus_build.py
python3 tools/corpus_check.py --sdks rust,js,python,go,java --core --sdk-checks
```

## Run it

```bash
python3 tools/xdrschema.py schema/x schema/schema.json
python3 tools/gen.py schema/schema.json out/cases.jsonl --valid 8 --faulty 2
python3 tools/run.py out/cases.jsonl
python3 tools/diff.py out/cases.jsonl
```

Build steps for the runners (one time): `cargo build --release` in `runners/rust`, `npm install`
in `runners/js`, a venv with `stellar-sdk==17.0.1` in `runners/python`, `runners/go/build.sh`
inside `golang:1.26`, and `mvn dependency:copy-dependencies -DoutputDirectory=lib` plus
`javac -cp 'lib/*' Runner.java` inside the Maven image.

## CI

Two GitHub Actions workflows in `.github/workflows/`. RFP check 2, the replay harness, is `replay.yml`:

| Workflow | When | What |
|---|---|---|
| `ci.yml` | every push and pull request, and weekly | One job per RFP acceptance check; [`VERIFY.md`](VERIFY.md) maps each check to its job and command. **RFP check 1**: self-tests, every entry through `tools/corpus_check.py`, and the golden entries compared byte for byte with stellar-core's `test-lcm-current` files. **RFP check 4**: `guide/check_guide.py`. **RFP check 3**: gofmt, `go vet`, `go test` with seeded violations, then the linter on wallet-backend (the pinned commit; `main` in the weekly run), failing on any finding outside `linter/accepted/wallet-backend.json`. **RFP checks 1 and 5**: builds the six decoder runners and runs every entry through them, through stellar-core 30.0.0 (`--core`) and through the pinned-SDK checks. **RFP check 6**: `.github/scripts/check_findings.py`: every failure in the committed replay results maps to a complete record in `FINDINGS.json`. |
| `replay.yml` | weekly, on demand, and on pushes and pull requests that touch the harness or the corpus | `harness/replay/run.sh sightings`: replays every sighting in `harness/replay/sightings.json` against real wallet-backend commits and fails unless each fails before its fix and passes after it. Results are uploaded as an artifact. |

## Infrastructure and maintenance

- [`INFRASTRUCTURE.md`](INFRASTRUCTURE.md): what the tools run on, every network connection they
  make, the Docker images and disk they need, and user tracking (there is none).
- [`MAINTENANCE.md`](MAINTENANCE.md): who maintains shapecov and for how long, routine work, and the
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
- Semantic checks above the codec beyond those in `harness/sdk-semantic/`, which cover issuer
  ordering, out-of-range IDs, colliding map keys and transaction decoding.
- Coverage of the 110 schema cells no valid case reaches yet.
- Replay adapters beyond wallet-backend and stellar-etl. Three corpus entries have hand-written
  `expected.indexer` rows; the oracle checks every ledger. See `harness/replay/README.md`, "Limits".
- CAP tags are assigned by hand from the CAP texts, then checked against the XDR history.
  stellar-xdr has no v29 tag, so cells added in protocols 29 and 30 are dated together.
- Review of the hardening guide by a stellar-core or platform engineer, which the RFP requires
  before publication. Every shape it describes has a corpus entry; three come from a local
  stellar-core (see the guide's appendix).
- The linter does not run clean on wallet-backend `main`: it reports 4 findings, all real and none
  of them a bug to file as is. CI fails on any finding outside `linter/accepted/wallet-backend.json`
  (see `linter/README.md`).

## Licence

Apache-2.0, see `LICENSE`.

Files from other projects keep their own terms:

- `schema/x/` and `schema/x-v28.0/` are the XDR definitions from `stellar/stellar-xdr` (tags v30.0
  and v28.0), which is also Apache-2.0. The exact commits are in `schema/SOURCE`.
- `corpus/entries/testnet-4437357.LedgerCloseMeta.xdr.b64` is a ledger from the public Stellar
  testnet, fetched from Stellar's public ledger archive.
