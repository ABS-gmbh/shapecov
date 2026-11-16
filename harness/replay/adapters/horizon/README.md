# Horizon adapter

Runs stellar/stellar-horizon, unmodified, at a release tag, against one corpus ledger at a time.

| File | What it is |
|---|---|
| [`adapter.py`](adapter.py) | The four verbs of [`../../ADAPTER.md`](../../ADAPTER.md). `prepare` builds the tag's own `main` package in the Go image its `docker/Dockerfile.dev` names and reads the effect type names from the tag's source. `up` starts PostgreSQL 16. `run` creates a fresh database, runs the tag's own `horizon db migrate up`, then `horizon db reingest range <seq> <seq> --ledgerbackend datastore`, and reads Horizon's history tables back. |
| [`expect.py`](expect.py) | The oracle mapping. Effects: the stellar-etl adapter's, because stellar-etl's `export_effects` is a copy of Horizon's effects processor. Participants: every account whose entry a successful transaction changed must be a transaction participant, and nothing the meta does not show may be one. |
| [`known.json`](known.json) | The upstream issues that explain a failing check. |

## How Horizon reads the ledger

`db reingest range` with `--ledgerbackend datastore` is Horizon's own way to backfill history from a
data lake. It needs no captive core and no history archive. The datastore is the harness's feeder:
the Galexie layout on S3 (`config/datastore.toml` in each run's evidence), one ledger per file.
The S3 client is given placeholder credentials, which the feeder ignores. Horizon accepts any
network passphrase, so entries from stellar-core's test data run too.

A reingest fills the history tables live ingestion fills: `history_transactions`,
`history_operations`, `history_effects`, `history_transaction_participants`,
`history_operation_participants`. It does not build the current-state tables (accounts, offers,
trustlines), which start from a checkpoint; those are not read.

## Run it

Needs Docker, like every replay.

```sh
python3 harness/replay/replay.py run --adapter horizon --refs v30.0.1 --inputs datalake --all-entries \
        --out harness/replay/out-horizon
python3 harness/replay/replay.py report --out harness/replay/out-horizon
```

The first `prepare` downloads Horizon's Go modules and builds it (about nine minutes on a laptop);
later runs reuse the build.
