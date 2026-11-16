# Maintenance plan

Who maintains shapecov, for how long, and exactly what keeping it current takes, including the
plan for protocol upgrades.

## Commitment

| | |
|---|---|
| **Maintainer** | ABS - Alternative Bold Solutions UG (haftungsbeschränkt), Göttingen, Germany, through the GitHub organisation `ABS-gmbh`. |
| **Project leads** | Abdallah Abdelnaby (`abdallah-abdelnaby`), Mohamed Basuony (`mohamedbasuony`) and Salaheldin Soliman (`salaheldinsoliman`). They own the repository and review every change (`CODEOWNERS`). |
| **Team** | Six software engineers: Abdallah Abdelnaby (PhD candidate in computer science), Mohamed Basuony (PhD candidate in digital humanities), Salaheldin Soliman (infrastructure and security), Omar ElSayed (blockchain and smart contracts), Ahmed Abdallah (systems and compilers), Islam Imad (compilers). The team is listed at https://absolution-gmbh.com/#team. |
| **Period** | From the production release through the **first Stellar protocol upgrade after delivery**, as the RFP requires. That period ends when the corpus, harness, conformance runner, linter and guide cover the new protocol and CI passes on it. |
| **Contact** | GitHub issues on this repository. Security reports: contact@absolution-gmbh.com. |

## What is maintained

| Deliverable | Where | What CI checks on every change |
|---|---|---|
| Corpus, manifest and generator | `corpus/`, `tools/`, `schema/` | every entry's hashes, decoded values, patterns and CAP tags (`tools/corpus_check.py`), through five SDKs and stellar-core |
| Replay harness and wallet-backend adapter | `harness/replay/` | every sighting fails before its fix and passes after it (`replay.py check`; weekly and on changes) |
| SDK conformance runner | `runners/`, `harness/sdk-semantic/` | all entries round-trip identically in five SDKs; the pinned-SDK checks run |
| Linter | `linter/` | gofmt, `go vet`, `go test` with seeded violations and correct code |
| Indexer-hardening guide | `guide/` | the field tables agree with the corpus (`guide/check_guide.py`) |
| Findings | `FINDINGS.md`, `corpus/evidence/`, `issues/` | evidence files that sightings point to exist |

A failing check is how drift shows up. Routine maintenance means keeping these green as the
things they depend on move.

## Routine work

- **Weekly replay.** `replay.yml` replays every sighting against pinned wallet-backend commits. A
  failure means the harness, an image or a dependency changed. Before each release, run
  `harness/replay/run.sh full` to replay the whole corpus at wallet-backend's current `main`. A new `mishandled` or
  `dropped` result there is a finding to triage and report.
- **New upstream releases** are found by `upstream-drift.yml`, which opens one issue per release
  newer than the pins, with the matching checklist below.
- **New SDK releases.**
  1. Raise the pin (see the list under "Protocol upgrade").
  2. Add the release to `harness/sdk-semantic/package.json`.
  3. Rerun `tools/corpus_check.py --sdks rust,js,python,go,java --core --sdk-checks`.
  4. A defect found in one SDK gets a sibling issue in each other SDK it affects.
- **New sightings.** A public bug report about a rare ledger shape gets:
  1. a corpus entry: mined with `tools/mine.py`, or produced with a `tools/localcore.py` scenario;
  2. its expected indexer rows (`tools/indexer_expect.py`);
  3. a claim in `harness/replay/sightings.json`, or an SDK check in the manifest, so CI keeps it
     reproduced.
- **Images and dependencies.** Every image and SDK is pinned (see `INFRASTRUCTURE.md`). Raise the
  pins deliberately, one change at a time, with CI green before and after.

## Protocol upgrade

The plan for keeping up with protocol upgrades. Because the generator reads the XDR schema, a new
protocol first shows up as schema cells that nothing covers and as checks that fail. The work is
the following steps, done in order, with CI as the measure of done. Start when the stellar-xdr tag
for the new protocol is published, and finish before the mainnet upgrade vote.

**Worked example, before the next upgrade:** [`protocol-drill/REPORT.md`](protocol-drill/REPORT.md),
produced by `protocol-drill/drill.py`, runs steps 1 to 3 and the golden-file part of step 6
against the next protocol as defined on 16 November 2026:
- stellar-xdr's `next` branch;
- a pending XDR change (`lcm_v3`);
- stellar-core's `test-lcm-next` golden files.

It reports:
- the new types and cells;
- that all 15,306 next-protocol golden ledgers, 13,893 of them at protocol 31, decode with today's
  schema;
- the cells those goldens exercise that the corpus does not carry. The first run found 19; the
  corpus has since taken entries from the goldens for all of them, and the report now shows none.

1. **Schema.**
   - Keep the current definitions as the previous protocol: move `schema/x` to `schema/x-v<old>`
     and `schema/schema.json` to `schema/schema-v<old>.json`.
   - Put the new stellar-xdr tag in `schema/x`, and record the tag and commit in `schema/SOURCE`.
   - Rebuild: `python3 tools/xdrschema.py schema/x schema/schema.json`.
   - Point the "previous protocol" reference at the old schema. Today it is
     `schema/schema-v28.0.json` in `tools/corpus_build.py`, `tools/corpus_add.py` and
     `tools/corpus_check.py`. The corpus then reports which of its cells are new.
2. **Generator.** Run `python3 tools/gen.py schema/schema.json out/cases.jsonl`, then
   `python3 tools/run.py out/cases.jsonl` and `python3 tools/diff.py out/cases.jsonl`. New union cases
   and enum values appear in the coverage report as uncovered cells; new divergences go to
   `FINDINGS.md`.
3. **CAP tags.** Map the new cells to the CAPs that introduce them in `corpus/cap-map.json`.
4. **SDK pins.** Raise each runner to a release that supports the protocol:
   - `runners/rust/Cargo.toml` (`stellar-xdr`)
   - `runners/js/package.json`
   - the `stellar-sdk` pin in `.github/workflows/ci.yml` (Python)
   - `runners/go/build.sh`
   - `runners/java/pom.xml`
5. **stellar-core.** Update the image in `tools/corpus_check.py` (`CORE_IMAGE`) and
   `tools/localcore.py` (`IMAGE`).
6. **Corpus.** Add entries for the new shapes:
   - stellar-core's new golden files: `tools/mine.py goldens`;
   - testnet ledgers once testnet has upgraded: `tools/mine.py scan testnet …`;
   - local-ledger scenarios at the new protocol, for shapes history does not have yet.

   Then run `tools/corpus_add.py` and `tools/corpus_check.py --core --sdks … --record`. Existing
   entries are never rewritten.
7. **Replay.** Run the corpus at wallet-backend's `main` once it supports the protocol. If
   wallet-backend changed its configuration, update the adapter. The pinned sighting commits keep
   working unchanged, because they only ever see ledgers from protocols they support.
8. **Linter.** Rebuild against the go-stellar-sdk release for the protocol, run `go test`, and rerun
   it on wallet-backend's `main`.
9. **Guide.** Re-read what stellar-core and the Soroban host validate for anything the protocol
   changed, and update the field tables and their source citations to the new release.
   `guide/check_guide.py` flags new patterns and changed counts.
10. **Release.** Tag a release that names the protocol it covers.

## If maintenance ends

Everything is in this repository under Apache-2.0 and can be reproduced from it: the corpus, the
tools and the recorded results. CI keeps showing what still works. If the maintainers step down,
they will say so in the README and in the issue tracker, and archive the repository rather than
leave it looking maintained.
