# shapecov (working name)

Prototype for the SCF RFP "XDR/CAP-Coverage Audit Tool and Indexer-Hardening Guide".

It generates XDR test cases from the Protocol 30 schema itself, runs each one through five decoders
and stellar-core, and reports where they disagree. Nothing is hand-captured.

Status on 14 November 2026: the SDK conformance half works end to end. For the indexer half there
is a draft manifest schema, three sample corpus entries, and a replay adapter that reproduces one
wallet-backend sighting from a real ledger (see "Corpus" below). The linter, the guide and the
mock RPC endpoint are not started. See "Not built" below.

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
| Go | go-stellar-sdk v0.9.0 | Docker, `golang:1.26` |
| Java | network.lightsail:stellar-sdk 6.0.0 | Docker, `maven:3.9-eclipse-temurin-21` |
| stellar-core | 30.0.0 (0e49751aa) | Docker, `stellar/stellar-core`, amd64 |

## Results so far

- 7,392 cases across all 477 types. The independent encoder and the reference decoder agree
  byte for byte on every valid case (3,808 of 3,808 that the reference has a type for).
- 943 further cases for the seven core-decodable types. stellar-core accepts all 280 valid ones.
- Valid cases exercise 837 of 1,188 schema cells (union arms plus enum members), 70.5%.
- Confirmed disagreements are in `FINDINGS.md`. Full clusters are in `out/REPORT.md`.

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

`corpus/` holds the draft manifest format and three sample entries. `corpus/README.md` describes
every field; `corpus/evidence/` records the two reproduced sightings.

| Entry | Type | Source | Shows |
|---|---|---|---|
| `testnet-4437357-signed-payload-signer` | LedgerCloseMeta | real testnet ledger, protocol 28 | CAP-0040 signer; reproduces wallet-backend #729 |
| `synthetic-scmap-colliding-keys` | TransactionMeta | generated | map keys that print the same; reproduces js-stellar-sdk #1789 |
| `synthetic-muxed-contract-address` | TransactionEnvelope | generated | CAP-0084 address type that is new in protocol 30 |

- `tools/decode.py` and `tools/encode.py` are a strict decoder and an encoder driven by the same
  schema as the generator. The decoder accepts all 3,816 valid generated cases, rejects all 3,576
  faulty ones, and re-encodes every valid case and the real ledger byte for byte.
- `tools/corpus_check.py` re-verifies the manifest and every entry: schema, hashes, expected
  decoded values, source record, CAP and protocol tags, then the five SDKs and stellar-core.
- `harness/wallet-backend/` replays a LedgerCloseMeta entry through wallet-backend's own indexer at
  any commit and reports pass, mishandled or dropped.
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

## Known artefacts in the current numbers

- Go shows 8 "valid" disagreements. All are the root type `SponsorshipDescriptor`, a typedef of an
  optional, which the runner allocates wrongly. It is a runner bug, not an SDK bug.
- JS has no value-level encoder for bare primitive and vector typedefs (`uint32`, `SCVec`, ...).
  Those cases are counted as unsupported, not as disagreements.
- The `bool_not_01` row in `out/REPORT.md` shows every SDK "disagreeing". The reference decoder is
  the odd one out there; see `FINDINGS.md`.

## Not built

- Core in the loop for whole ledgers: submit generated transactions to a local stellar-core and
  capture the `LedgerCloseMeta` it emits. Today core is used only as a decoder.
- Semantic checks above the codec beyond the one in the corpus (map key collisions): issuer
  ordering, ID wrap-around and others.
- Coverage of the 351 schema cells no valid case reaches yet.
- The replay harness knows one kind of expectation (a signer state change) and one indexer. It
  has no mock RPC `getLedgers` endpoint and no Galexie-layout output yet, and it checks the
  indexer's row encoding, not a write to a real database.
- No entry is checked against stellar-core's golden LedgerCloseMeta files. Entries are checked by
  having stellar-core 30.0.0 decode them.
- CAP tags are assigned by hand. Only "new in protocol 30" is computed, from the difference
  between the v28.0 and v30.0 XDR.
- Go linter and hardening guide.
