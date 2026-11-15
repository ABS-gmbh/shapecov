# Replay harness

Runs `LedgerCloseMeta` corpus entries through a real indexer and reports, per entry and commit,
whether the indexer stored them correctly (`pass`), stored something wrong or failed on valid data
(`mishandled`), or silently lost them (`dropped`).

This replaces the earlier `harness/wallet-backend/` adapter, which called `indexer.ProcessLedger`
from a Go test with no database. Here the indexer runs as it does in production: its own binary,
its own `migrate up`, its own `ingest` command, a real TimescaleDB, and a ledger delivered
through one of two inputs that existing pipelines already read from.

Results: [`RESULTS.md`](RESULTS.md). Adapter contract: [`ADAPTER.md`](ADAPTER.md).

## Run it

```sh
harness/replay/run.sh          # sighting matrix (4 commits) + every entry at current main
harness/replay/run.sh quick    # #729 only: pre-fix and fix commits, both inputs (about 1 minute once built)
```

Needs Docker, git and python3 (standard library only). Network access is used to clone
wallet-backend, pull `golang:1.26`, `python:3.14-slim` and `timescale/timescaledb:2.28.2-pg17`,
and download the Go modules each commit pins. Builds are cached per commit in
`harness/replay/.work/` (or `$REPLAY_WORK`).

Lower level:

```sh
python3 harness/replay/replay.py run --refs <ref>[,<ref>…] [--entries ID,…| --all-entries] \
        [--inputs rpc,datalake] [--max-protocol N] [--timeout 120] [--keep]
python3 harness/replay/replay.py report      # rebuild RESULTS.md from out/results.jsonl
```

## How it works

```
corpus/manifest.json ──► feeder (Docker, internal network)
                          ├─ :8000  mock stellar-rpc  (getHealth, getNetwork, getLatestLedger,
                          │                            getVersionInfo, getLedgerEntries, getLedgers)
                          └─ :9000  S3-compatible store with the Galexie data-lake layout
                                         │
replay.py ── adapter prepare ──► go build of the commit, unmodified (Docker)
          ── adapter up ───────► TimescaleDB (Docker, tmpfs)
          ── adapter run ──────► fresh database → `migrate up` → `ingest` fed by rpc or datalake
                                 → read the tables back → observation.json
          ── classify.py ──────► observation vs expected.indexer → pass / mishandled / dropped
          ── report ───────────► RESULTS.md
```

- **Entries are discovered** from the manifest at run time (`xdr_type == LedgerCloseMeta`), so new
  entries are picked up with no code change. The network passphrase is taken per entry.
- **Bounded memory.** The feeder indexes a few header fields per entry and streams ledger bytes from
  disk in 64 KiB chunks for both inputs. Peak RSS is recorded in each run (about 36 MB serving all
  48 entries).
- **No route out.** The feeder, database and indexer share a Docker network created with
  `--internal`.
- **Expectations come only from the manifest.** The indexer's output is never used to decide what
  is correct. Every entry also gets two implicit checks: the ledger is ingested without an error,
  and every stored address reads back as a valid SEP-23 address.

### How the indexer is positioned

The one thing the adapter writes into wallet-backend's database is the ingest cursor:
`latest_ingest_ledger` and `oldest_ingest_ledger` in `ingest_store` are set to `seq - 1` after
the commit's own migrations run. That makes the indexer's own live-ingest loop start at the
entry's ledger without a history-archive checkpoint, which the mock does not serve. Source and
dependencies are not changed (`source_modified: false`, `dependencies_modified: false` in every
run record).

The adapter decides "ingested" when the cursor reaches the entry's ledger. It then stops the
process, saves its log and reads back `transactions`, `transactions_accounts`, `operations`,
`operations_accounts` and `state_changes` for that ledger.

## Reproduced sightings

| Issue | Commit | What the database shows | Result |
|---|---|---|---|
| wallet-backend#716, signed-payload half | `79ea2acd` (protocol 28 upgrade) | Ingestion succeeds, but `state_changes.signer_account_id` holds 33 of the signer's 41 bytes. It reads back as `PBCK2RYY…NSBYVM`, which is not a valid signed-payload address. No error is logged. | mishandled |
| wallet-backend#729 | `6e5a5910` (#693) and `2a0a84ea` (parent of the fix) | Ingestion halts on the ledger: `COPY … converting signer_account_id … has a 40-byte key payload`. The cursor never advances, so every later ledger is lost too. | mishandled |
| fix | `2c873353` (#729) and current `main` | The `SIGNER/ADD` row stores the full key and reads back as `PBCK2RYY…AANMS`. | pass |

All of these were run through both inputs, with the same result. Logs, jobs, observations and
feeder request logs for every cell are under `out/<commit>/<input>/<entry>/`.

## Limits

- **wallet-backend is the only adapter.** A stellar-etl adapter was started but not finished.
- **Older commits can only decode up to protocol 28.** They pin go-stellar-sdk v0.7.3, so protocol 29
  and 30 entries are run at current `main` only. `--max-protocol 28` selects the older-compatible
  entries. Dependencies are never upgraded to work around this.
- **Most entries have no `expected.indexer` yet.** For those, `pass` only means "ingested without an
  error and every stored address is valid", not "every row is right". RESULTS.md lists them
  separately.
- **No ledger state.** `getLedgerEntries` always returns nothing, so code paths that look up ledger
  state through RPC see none.
- **One ledger per run.** The mock RPC window and the data-lake prefix each hold exactly one ledger.
  Cross-ledger behaviour, such as a delete in the next ledger, is not covered yet.

## Next

- **#731** (CAP-0073 `trust()` creates a trustline with no `TRUSTLINE/ADD` state change): the corpus has
  `soroban-created-trustline` ledgers (`testnet-5709224`, `golden-invokehostfunction-4c437318-42`).
  They need a `state_change` expectation with `category: TRUSTLINE`, `reason: ADD`, the account
  and the token, derived from the decoded ledger. They are protocol 30, so the pre-fix commit
  (September 2026, go-stellar-sdk v0.7.3) cannot decode them. A protocol 28 ledger with a SAC
  `trust()` call is needed for a before/after pair.
- **#716, muxed half**: entries with `scaddress-muxed-account` (e.g. `testnet-5711641`) need
  `participant` and `no_participant` expectations for the base `G…` account and the `M…`
  address.
