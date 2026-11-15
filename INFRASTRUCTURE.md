# Infrastructure and user tracking

What shapecov runs on, what it connects to, and what it records about anyone.

## Summary

- **No hosted service.** shapecov is a repository of tools. Nothing runs on servers we operate: every
  part runs on a developer's machine or in GitHub Actions.
- **No user tracking.** There is no telemetry, analytics, crash reporting or update check. The tools
  record nothing about who runs them. The complete list of network connections is below.
- **No keys or funds.** Nothing needs a secret, a funded account or mainnet access. The CI
  workflows run with read-only repository permissions and no secrets.
- **Third-party code runs isolated.** Indexers, SDKs and stellar-core run in Docker. During a run
  they have either no network at all or a Docker network with no route to the internet.

## Where it runs

| Part | Runs on | Needs |
|---|---|---|
| Generator, decoder, corpus and guide checks (`tools/`, `guide/`) | any machine, or the `ci` workflow | Python 3.12 or later, and `jsonschema` for `tools/corpus_check.py` |
| SDK conformance runners (`runners/`) | the same, plus Docker | Rust (stable), Node.js 22, a Python venv with stellar-sdk 17.0.1, Docker for Go and Java |
| stellar-core checks (`corpus_check.py --core`), local ledgers (`tools/localcore.py`) | Docker | the `linux/amd64` stellar-core image; on Apple silicon it runs under emulation |
| Replay harness (`harness/replay/`) | Docker, or the `replay` workflow | about 5 minutes for all sightings in CI |
| Linter (`linter/`) | Go 1.26, or Docker | |

GitHub Actions runs two workflows (`.github/workflows/`, both `permissions: contents: read`):

| Workflow | When | Typical duration |
|---|---|---|
| `ci.yml` | every push and pull request | about 3 minutes |
| `replay.yml` | weekly, on demand, and on pushes and pull requests that change the harness or the corpus | about 5 minutes |

## Network connections

This is every connection the tools make. It was compiled by searching all tracked source for
network use.

| Destination | Made by | When | Why |
|---|---|---|---|
| `aws-public-blockchain.s3.us-east-2.amazonaws.com` (Stellar's public ledger archive, Galexie layout) | `tools/mine.py` | only when mining new ledgers for the corpus | download public testnet and mainnet `LedgerCloseMeta` |
| `github.com/stellar/wallet-backend` | the replay adapter and `linter/scripts/run-wallet-backend.sh` | when a wallet-backend commit is not cached locally | clone the indexer under test |
| Go module proxy, npm, PyPI, crates.io, Maven Central | build steps (`go mod download`, `npm ci`, `pip install`, `cargo build`, `mvn`) | when building runners, the linter or a wallet-backend commit | fetch pinned dependencies |
| Docker Hub | `docker pull` | when an image is missing | fetch the images below |

**Nothing else.** Every other address in the code is local:
- the replay feeder's mock stellar-rpc (port 8000) and S3-compatible store (port 9000), reachable
  only on the harness's internal Docker network;
- a local stellar-core's HTTP port (11626), reached with `docker exec` inside its own container.

Once dependencies, images and the wallet-backend clone are cached, these run fully offline:
- the corpus check
- the guide check
- the generator
- the linter tests
- every replay

### Isolation during runs

| What runs | Network it gets |
|---|---|
| Go and Java SDK runners (`tools/run.py`) | `--network none`, 2 GB of memory, 2 CPUs |
| stellar-core checks (`tools/corpus_check.py --core`) | `--network none` |
| Local stellar-core (`tools/localcore.py`) | `--network none` |
| Linter tests and linter runs on wallet-backend | `--network none` |
| Replay: feeder, TimescaleDB and the indexer | a Docker network created with `--internal`, which has no route to the internet |

## Docker images

Pinned in the code, with their sizes on 15 November 2026:

| Image | Used for | Size |
|---|---|---|
| `stellar/stellar-core:30.0.0-3642.0e49751aa.noble` | stellar-core checks, local ledgers | 789 MB |
| `stellar/stellar-core:22.2.1-2429.e70f0aed8.focal` | one local-ledger scenario (`muxed-source-p22`) | 522 MB |
| `golang:1.26` | the Go runner, wallet-backend builds, the linter | 1.3 GB |
| `maven:3.9-eclipse-temurin-21` | the Java runner | 847 MB |
| `timescale/timescaledb:2.28.2-pg17` | the replay database (the image the wallet-backend commit's own `docker-compose.yaml` names, if it names one) | 1.8 GB |
| `python:3.14-slim` | the replay feeder | 206 MB |

## Disk and memory

Measured on 15 November 2026:

- **Images:** about 5.5 GB for all of the above.
- **Replay work directory** (`harness/replay/.work/`, git-ignored): about 1.1 GB after building the
  nine wallet-backend commits the sightings use, at roughly 95 MB per commit. Set `REPLAY_WORK` to
  put it elsewhere.
- **Mining cache:** grows with the number of ledgers scanned. About 1.5 GB after scanning about
  53,500 testnet and mainnet ledgers.
- **Memory caps:** the replay feeder is limited to 256 MB and peaks at about 36 MB serving all 51
  ledgers. Each indexer run is limited to 2 GB.

**Leave headroom.** Docker's virtual disk cannot grow when the host disk is full. If it fills
mid-run, Docker's storage reports I/O errors and can need a restart, or a purge, to recover.

## Data

- **Inputs are public ledger data:** testnet and mainnet ledgers from the public archive, and
  stellar-core's golden test files.
- **Generated ledgers use test keys only.** Ledgers from `tools/localcore.py` come from a private
  standalone network whose keys are derived from fixed strings. Those keys never touch a public
  network.
- **No personal data.** The tools do not handle any.
- **Outputs are files in the repository:** corpus entries, the manifest, recorded results and
  reports.
- **Recorded runs carry no local paths.** Replay jobs store their work directory as `$REPLAY_WORK`.
