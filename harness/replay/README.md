# Replay harness

Runs `LedgerCloseMeta` corpus entries through a real indexer (stellar/wallet-backend or
stellar/stellar-etl) and reports, per entry and commit,
whether the indexer stored them correctly (`pass`), stored something wrong or failed on valid data
(`mishandled`), or silently lost them (`dropped`).

This replaces the earlier `harness/wallet-backend/` adapter, which called `indexer.ProcessLedger`
from a Go test with no database. Here the indexer runs as it does in production: its own binary,
its own `migrate up`, its own `ingest` command, a real TimescaleDB, and a ledger delivered
through one of two inputs that existing pipelines already read from.

Results: [`RESULTS.md`](RESULTS.md) (wallet-backend), [`RESULTS-stellar-etl.md`](RESULTS-stellar-etl.md).
Adapter contract: [`ADAPTER.md`](ADAPTER.md).

## Run it

```sh
harness/replay/run.sh            # sightings + every entry at current main
harness/replay/run.sh sightings  # every pair in sightings.json, then `replay.py check`
harness/replay/run.sh quick      # #729 only: pre-fix and fix commits, both inputs (about 1 minute once built)
harness/replay/run.sh etl        # every entry through stellar-etl's current master (about 3 minutes with the build)
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
python3 harness/replay/replay.py rejudge     # recompute the oracle verdicts from the stored observations
python3 harness/replay/replay.py check       # fail unless out/results.jsonl matches sightings.json
```

Every verb takes `--adapter` (`run`) or `--out` (all): stellar-etl's results live in
`out-stellar-etl/`, one output directory per adapter.

## How it works

```
corpus/manifest.json ──► feeder (Docker, internal network)
                          ├─ :8000  mock stellar-rpc  (getHealth, getNetwork, getLatestLedger,
                          │                            getVersionInfo, getLedgerEntries, getLedgers)
                          ├─ :9000  S3-compatible store with the Galexie data-lake layout
                          └─ :9100  the same lake through the GCS JSON and XML APIs
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
  52 entries).
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

## The oracle: every ledger is a test

The manifest's hand-written expectations cover only the entries tied to a sighting. To check every
ledger, `tools/oracle.py` reads its meta and lists what changed in ledger state, independently of
any indexer and any SDK:
- accounts created or removed;
- signers added, removed or reweighted;
- thresholds, flags, home domain and data entries;
- trustlines added, removed or re-limited, and trustline authorization;
- contract instances created;
- offers placed, changed or removed, and **trades**: a resting offer crossed in an operation (it
  shrank or went, and the operation's result lists it as claimed with a nonzero amount);
- claimable balances created (with their claimants) and removed;
- liquidity pools created, removed, or with reserves changed;
- sponsorship created, transferred or ended, for accounts, trustlines, data entries, claimable
  balances, offers and individual signers (CAP-33);
- balances: the net change of every account's XLM and credit-asset trustline balance per operation,
  and each transaction's net fee (fee charged, minus any refund).

`adapters/wallet-backend/expect.py` names the state-change row wallet-backend stores for each change,
in wallet-backend's own vocabulary (categories and reasons from its `types.go`, producers from its
`processors/`). Whether a row is expected always comes from the ledger.

For balances, the check is `balance_net`: an account's stored `BALANCE` rows for one token,
transaction and operation must add up to the ledger's net change (CREDIT counts +amount, DEBIT
−amount; the issuer's MINT and BURN rows do not count). The token is the asset's contract ID, the
native one for XLM. The fee goes at operation position 0. The harness also reports stored balance
movements for an account where the ledger shows none.

Each replay then gets a second verdict, `oracle`. A row the indexer did not store is either labelled
with an open upstream issue that explains it (`adapters/wallet-backend/known.json`) or reported as
**unexplained**, a candidate new finding. RESULTS.md lists both.

At wallet-backend `main` (`3e22515a`), for all 54 ledgers through both inputs:

| Check | Rows expected per input | Met | Known open issues | Unexplained |
|---|---|---|---|---|
| State changes | 134 | 123 | 11: wallet-backend#815 (6 contract deploys with no `ACCOUNT CREATE`), #816 (3 accounts created by XLM sent through the native asset contract), #817 (2 pool-share trustlines removed by one revocation) | 0 |
| Net balances | 4062 | 4062 | none | 0 |
| Total | 4196 | 4185 | 11 | 0 |

wallet-backend has no state-change categories for offers, claimable balances, pools or
sponsorship, so those facts are checked for stellar-etl, whose effects model has them. They still
reach wallet-backend through the balance check.

No stored balance movement appears for an account whose balance the ledger leaves unchanged.

The balance check was tested by corrupting observations: an amount off by one stroop, a deleted
`BALANCE` row and an added one each fail it as unexplained.

The oracle also re-finds the claimed sightings on their own: at `764a4f5b` it reports #731's missing
`TRUSTLINE/ADD` and `BALANCE_AUTHORIZATION` rows, and at `79ea2acd` #716's truncated signer, without
the manifest's expectations.

**Not covered yet:** contract (`C...`) balances, which live in contract storage, and liquidity pool
share balances; the master key's weight, the taking side of a trade, and contract storage other
than instances. A row the indexer writes that the oracle does not predict
is not reported.

## Reproduced sightings

| Issue | Commit | What the database shows | Result |
|---|---|---|---|
| wallet-backend#716, signed-payload half | `79ea2acd` (protocol 28 upgrade) | Ingestion succeeds, but `state_changes.signer_account_id` holds 33 of the signer's 41 bytes. It reads back as `PBCK2RYY…NSBYVM`, which is not a valid signed-payload address. No error is logged. | mishandled |
| wallet-backend#729 | `6e5a5910` (#693) and `2a0a84ea` (parent of the fix) | Ingestion halts on the ledger: `COPY … converting signer_account_id … has a 40-byte key payload`. The cursor never advances, so every later ledger is lost too. | mishandled |
| fix | `2c873353` (#729) and current `main` | The `SIGNER/ADD` row stores the full key and reads back as `PBCK2RYY…AANMS`. | pass |
| wallet-backend#731 | `764a4f5b` (parent of the fix) | Entry `localcore-sac-trust-p28-5`: a Stellar Asset Contract `trust()` call creates a trustline with no `ChangeTrust` operation and no event. Ingestion succeeds and stores only the fee's `BALANCE/DEBIT` row; there is no `TRUSTLINE/ADD` and no `BALANCE_AUTHORIZATION` row. No error is logged. | dropped |
| fix | `c152783c` (#734) and current `main` | `TRUSTLINE/ADD` and `BALANCE_AUTHORIZATION/SET` rows for the trustor, with the asset's contract ID as token. | pass |
| wallet-backend#716, muxed half | `79ea2acd` | Entry `localcore-muxed-source-p22-3`: a contract call that runs as a muxed account. The source is recorded as a participant twice, as `GBRPYHIL…OX2H` and as a truncated `MBRPYHIL…PFTY` that does not read back as a valid address (33 of its 41 bytes). | mishandled |
| (#693's side effect) | `6e5a5910` (#693) to `f8e5786d` | #693 encodes every `M…` as its base `G…`, so the two participant strings become one key and the insert fails with a duplicate primary key on `transactions_accounts`; ingestion stops at the ledger. `bb0b162b` describes and fixes this. | mishandled |
| fix | `bb0b162b` and current `main` | The participant is the base account only. | pass |

The #716 muxed-half entry is a protocol 22 ledger from a local stellar-core 22.2.1 (scenario
`muxed-source-p22`); its expectation (the base account is a participant of that transaction) is
derived the same way. The harness's own check that every stored address reads back as a valid
address is what catches the truncation.

The #731 entry is a protocol 28 ledger from a local stellar-core 30.0.0 (`tools/localcore.py`,
scenario `sac-trust-p28`), because the corpus's network ledgers with this shape are protocol 30 and
the pre-fix commit cannot decode them. Its expectations come from `tools/indexer_expect.py`: the
account from the created trustline, and the token from the asset's contract ID under the entry's
network passphrase.

All of these were run through both inputs, with the same result. Logs, jobs, observations and
feeder request logs for every cell are under `out/<commit>/<input>/<entry>/`.

## stellar-etl

`adapters/stellar-etl/` runs stellar-etl unmodified at a given commit: built with cgo in the Go image
its own `docker/Dockerfile` names, then `export_transactions`, `export_operations`, `export_effects`
and `export_token_transfer` for the one ledger. stellar-etl's datastore type is fixed to Google
Cloud Storage, so the feeder also serves the lake through the GCS JSON and XML APIs, and the
exporter's own GCS client is pointed at it with `STORAGE_EMULATOR_HOST`, the client library's
standard setting. No flag, source line or dependency is changed.

The oracle maps onto stellar-etl's own vocabulary (`adapters/stellar-etl/expect.py`): each change
in ledger state should produce the matching Horizon-model effect (`account_created`,
`signer_created`, `trustline_flags_updated` naming the trustor, `trade` for each crossed offer's
seller, `claimable_balance_created` and one `claimable_balance_claimant_created` per claimant,
`liquidity_pool_deposited`/`withdrew`/`trade`/`revoked` by operation, the `*_sponsorship_*` family,
…), and each account's net balance
change should equal the net of its CAP-67 token transfer events (fees at position 0, refunds as
negative fee events). The manifest's hand-written expectations name wallet-backend rows, so only
their `transaction` checks apply here.

At stellar-etl `master` (`2b24ec89`), all 55 ledgers (results in
[`RESULTS-stellar-etl.md`](RESULTS-stellar-etl.md)); rows checked on the 26 it exports:

| | Rows checked | Met | Known | Unexplained |
|---|---|---|---|---|
| Accounts, signers, thresholds, flags, data, trustlines | 102 | 96 | 4: stellar-etl#460; 2: E3 | 0 |
| Trades (crossed offers) | 151 | 151 | none | 0 |
| Liquidity pools | 705 | 704 | 1: E2 | 0 |
| Claimable balances | 18 | 18 | none | 0 |
| Sponsorship (entries and signers) | 21 | 21 | none | 0 |
| Net balances (token transfers) | 3998 | 3998 | none | 0 |
| Ledgers not exported | 2 of 28 | | 2: stellar-etl#512 (E1) | 0 |
| Not applicable (stellar-core test network) | 27 ledgers | | | |

- **stellar-etl#460** (open, filed by a maintainer in July): an account created by XLM sent through
  the native asset contract gets no `account_created` effect, and a trustline created by the asset
  contract's `trust()` (CAP-73) gets no `trustline_created`. The oracle found all four rows from
  ledger data alone: `testnet-5709224` (both shapes), `pubnet-65480300`, `localcore-sac-trust-p28-5`.
- **E1, new, filed as stellar-etl#512:** `export_token_transfer` fails on every ledger before protocol 23 that holds a
  transaction (`localcore-classic-p22-3`, `localcore-muxed-source-p22-3`): stellar-etl builds the
  token transfer processor in unified-events mode, which requires `TransactionMeta` v4. The SDK's
  other constructor handles both ledgers. Evidence: `corpus/evidence/stellar-etl-token-transfer-pre23.md`.

- **E2, new, not filed:** a revocation that redeems pool shares in two pools at once gets one
  `liquidity_pool_revoked`, for one pool, and that effect's `reserves_revoked` names the other
  pool's AAA claimable balance. Shown on `localcore-pool-revoke-two-pools-7` (stellar-core 30.0.0);
  Horizon has the same code. Evidence: `corpus/evidence/stellar-etl-pool-revocation.md`.
- **E3, new, not filed:** the pool-share trustlines that revocation removes get no
  `trustline_removed` effect; only ChangeTrust emits one. The effects-model counterpart of
  wallet-backend#817.

Custom token contracts (SEP-41 tokens other than asset contracts) keep balances in contract
storage, which the oracle does not read, so their token transfer events are not compared.

## Limits

- **stellar-etl reads only pubnet, testnet and futurenet** from a GCS data lake, so the 27 entries
  from stellar-core's own test data (passphrase `(V) (;,,;) (V)`) are `n/a` for it, and its one input
  is `datalake`.
- **Older commits can only decode up to protocol 28.** They pin go-stellar-sdk v0.7.3, so protocol 29
  and 30 entries are run at current `main` only. `--max-protocol 28` selects the older-compatible
  entries. Dependencies are never upgraded to work around this.
- **Only three entries have `expected.indexer` so far** (#729 and #716's signed-payload half, #731,
  #716's muxed half). For those, `pass` only means "ingested without an
  error and every stored address is valid", not "every row is right". RESULTS.md lists them
  separately.
- **No ledger state.** `getLedgerEntries` always returns nothing, so code paths that look up ledger
  state through RPC see none.
- **One ledger per run.** The mock RPC window and the data-lake prefix each hold exactly one ledger.
  Cross-ledger behaviour, such as a delete in the next ledger, is not covered yet.

## Next

- **Expectations for more entries.** `tools/indexer_expect.py` has one rule so far
  (`soroban-created-trustline`). Running it on the protocol 30 entries with that shape
  (`testnet-5709224`, `golden-invokehostfunction-4c437318-42`) would check them at `main` too.
- **#716's second muxed producer** (a SEP-41 event naming a muxed `ScAddress`) is not reproduced.
  The corpus entries with `scaddress-muxed-account` are protocol 29 and 30, which the commits before
  #693 cannot decode; it needs a protocol 23 to 28 ledger with such an event.
