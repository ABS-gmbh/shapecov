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
python3 harness/replay/replay.py run --refs <ref>[,<ref>…] [--entries ID,…| --all-entries | --sequence NAME,…] \
        [--inputs rpc,datalake] [--max-protocol N] [--timeout 120] [--keep]
python3 harness/replay/replay.py report      # rebuild RESULTS.md from out/results.jsonl
python3 harness/replay/replay.py rejudge     # recompute the oracle verdicts from the stored observations
python3 harness/replay/replay.py check       # fail unless out/results.jsonl matches sightings.json
```

Every verb takes `--adapter` (`run`) or `--out` (all): stellar-etl's results live in
`out-stellar-etl/`, one output directory per adapter. `REPLAY_PREFIX=name` gives a run its own
container names, network and feeder folder, so two replays can run at once.

### Sequences: several ledgers into one database

Some defects need state an earlier ledger wrote: a delete is lost only if a row exists to be
deleted. `corpus/sequences.json` names runs of consecutive corpus ledgers, and
`run --sequence NAME` serves one as a single window (the mock RPC's oldest and latest ledgers, and
one data-lake prefix holding all of them). The adapter positions the cursor before the first
ledger and waits for the last, so the indexer ingests them in one process into one database. Each
ledger is then judged as an entry (its result carries `mode: sequence NAME`), and the
sequence gets a result of its own: the current-state tables at the end against the oracle's
`final_trustlines`, the state of every credit trustline the ledgers touched when the last one
closes. Sequences are recorded in `out-sequences/`.

| Sequence | Ledgers | Built for | Blind |
|---|---|---|---|
| `trustline-churn` | `localcore-trustline-add-4`, `localcore-trustline-churn-5` (scenario `trustline-churn-p28`) | wallet-backend#687 | no: built after reading the fix |

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

For current state, the check is `native_balance`: after the ledger, every account whose XLM
balance it changed, in any phase (the fee, the operations, a fee refund), has a row in
wallet-backend's `native_balances` table with its balance when the ledger closes, and an account
the ledger removed has none. An account whose entry changed but whose balance did not is not
checked: the replay starts from an empty database, so its row would have come from an earlier
ledger. Ledgers before protocol 23 are not checked either: wallet-backend's documented contract
(`docs/architecture/state-changes.md`) takes the Soroban fee refund from the post-apply list that
protocol 23 introduced, and before it the refund is in `txChangesAfter`. On the corpus at `main`
the check is clean on every ledger from protocol 23 on, so it is also a standing check of every
balance wallet-backend stores. The sweep observations predate it and are not judged by it.

For participants, the check is the RFP's second rule: who a transaction affected comes from the
meta, not the envelope. Every participant wallet-backend stores for a transaction or one of its
operations, and the account of every state change it stores for it, must be an address the
transaction's meta shows (an entry created, changed or removed, with its key, so a nonce or a token
holder's balance entry names its address; a contract or system event, including an address written
in an asset name), the transaction's own source or fee-bump source, or, in a successful
transaction, an operation's own source (it signed for that operation). A failed transaction's meta
shows only its fee and sequence changes, so a failed payment's destination is outside it. An address
only an authorization entry names, and a contract a declared deploy would have created, are too.
The other direction is checked too: every account whose account entry the transaction changed must
be a transaction participant. wallet-backend misses the ones no operation names (a sponsor whose
sponsorship ends, the maker of an offer taken whole), because its `participantsForMeta` reads
TransactionMeta's v0 arm: stellar/wallet-backend#677, open, labelled in `known.json`.

Each replay then gets a second verdict, `oracle`. A row the indexer did not store is either labelled
with an open upstream issue that explains it (`adapters/wallet-backend/known.json`) or reported as
**unexplained**, a candidate new finding. RESULTS.md lists both.

At wallet-backend `main` (`3e22515a`), for all 63 ledgers through both inputs:

| Check | Rows expected per input | Met | Known open issues | Unexplained |
|---|---|---|---|---|
| State changes | 216 | 205 | 11: wallet-backend#815 (6 contract deploys with no `ACCOUNT CREATE`), #816 (3 accounts created by XLM sent through the native asset contract), #817 (2 pool-share trustlines removed by one revocation) | 0 |
| Net balances | 8714 | 8714 | none | 0 |
| Total | 8930 | 8919 | 11 | 0 |

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

## Sweep: 611 network ledgers

The corpus keeps one ledger per shape. To check the indexers on ordinary traffic too, the sweep
replays a broad sample of real ledgers that is not committed: every 20,000th ledger of pubnet from
59,000,000 (protocol 23) to 65,480,000, and of testnet since its December 2025 reset, from Stellar's
public ledger archive. That is 611 ledgers holding 100,676 transactions, protocols 23 to 30, run
on 16 and 17 November 2026:

| Indexer | Ledgers ingested | Oracle rows checked | Met | Known open issues | Unexplained |
|---|---|---|---|---|---|
| wallet-backend `main` (`3e22515a`), data lake | 611 | 778,927 | 778,796 | 89: wallet-backend#677; 42: wallet-backend#815 | 0 |
| stellar-etl `master` (`2b24ec89`), data lake | 611 | 985,927 | 886,679 | 52,879: stellar-etl#452; 38,959: stellar-etl#450; 7,321: stellar-etl#456; 69: stellar-etl#457; 19: stellar-etl#462; 1: stellar-etl#460 | 0 |

1,764,854 checks on real traffic (611 ledgers, protocols 23 to 30). 99,379 did not meet the
oracle; every one maps to one of eight open upstream issues (two in wallet-backend, six in
stellar-etl). None is unexplained. Every row the oracle derives is checked.

stellar-etl's share is large because two issues are systematic rather than rare shapes: #452
(52,879: contract events exported twice, and `in_successful_contract_call` true on failed
transactions) and #450 (38,959: a muxed destination fabricated for payments carrying a text or hash
memo) account for 92% of its failures.

On the sweep's public-archive ledgers stellar-etl exports 25,844 operation-level contract events
twice (8.7% of 296,278), a share that rises from about 4% in late 2025 to 14% in late 2026. The
issue's 15.6% was measured on SDF's production feed for one hour in July 2026; the sweep's ledgers
nearest that date give 6.8%. The two are not comparable one to one: different input (SDF's
production feed against the public archive) and different windows (one hour against single ledgers
20,000 apart). We have not established which accounts for the difference. It is not the volume of
diagnostic events: the sweep's ledgers carry 3.28 diagnostic events per operation-level event, and
the issue's daily figures give 3.17 (58.7 million diagnostic rows against 18.5 million contract
rows).

stellar-etl also exports 405 rows no meta event matches. All are contract events from the
diagnostic list of failed transactions (a failed call's events appear only there): the loop #452
names (`contract_events.go`, the diagnostic-list append) puts them in the output. No rule checks rows
the meta lacks, so they are not among the failures above.

The first run (16 November 2026) counted 1,015,788 checks, 202 failures and five issues; the rise
comes from checks added since: wallet-backend's current XLM balances on every ledger, and
stellar-etl's muxed destinations, contract events, effects of trades and contract-deploy details.

The wallet-backend checks include the participant rule (both directions); its first sweep found 94
false alarms of the "only what the meta shows" direction (operation-level sources of successful
Soroban operations, which signed but appear only in the envelope), and the rule was corrected to
allow them before these numbers. They also include the duplicate-row rule (a state-change row stored
more than once fails): none of the 611 ledgers has one. Its first version failed any count above the
ledger's and raised 10 false alarms, all rows that record no change (8 thresholds set to their old
value, 2 authorization flags cleared that were not set: wallet-backend writes a row for what the
operation asked for); those now pass.
The 9 sweep ledgers that bring schema cells or patterns the corpus lacked were added to `corpus/`
(`tools/corpus_add.py`), one per protocol era from 23 to 30.

```sh
W=/tmp/sweep
python3 tools/mine.py scan pubnet 59000000 65480000 --stride 20000 --cache $W/lake --index $W/pubnet.jsonl
python3 tools/mine.py scan testnet 20000 5720000 --stride 20000 --cache $W/lake --index $W/testnet.jsonl
python3 harness/replay/sweep.py build --index $W/pubnet.jsonl --index $W/testnet.jsonl --cache $W/lake --out $W/corpus
python3 harness/replay/replay.py run --corpus $W/corpus --all-entries --inputs datalake \
        --refs main --out $W/out-wb
python3 harness/replay/replay.py run --corpus $W/corpus --all-entries --inputs datalake \
        --adapter stellar-etl --refs master --out $W/out-etl
```

The sweep corpus is about 750 MB of base64 and each report is written next to its results.

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

At stellar-etl `master` (`2b24ec89`), all 64 ledgers (results in
[`RESULTS-stellar-etl.md`](RESULTS-stellar-etl.md)); rows checked on the 35 it exports:

| | Rows checked | Met | Known | Unexplained |
|---|---|---|---|---|
| Accounts, signers, thresholds, flags, data, trustlines | 171 | 164 | 5: stellar-etl#460; 2: stellar-etl#514 (E3) | 0 |
| Trades (crossed offers) | 319 | 319 | none | 0 |
| Liquidity pools | 1161 | 1160 | 1: stellar-etl#513 (E2) | 0 |
| Claimable balances | 90 | 90 | none | 0 |
| Sponsorship (entries and signers) | 60 | 60 | none | 0 |
| Net balances (token transfers) | 8650 | 8650 | none | 0 |
| Ledgers not exported | 2 of 37 | | 2: stellar-etl#512 (E1) | 0 |
| Not applicable (stellar-core test network) | 27 ledgers | | | |

- **stellar-etl#460** (open, filed by a maintainer in July): an account created by XLM sent through
  the native asset contract gets no `account_created` effect, and a trustline created by the asset
  contract's `trust()` (CAP-73) gets no `trustline_created`. The oracle found all five rows from
  ledger data alone: `testnet-5709224` (both shapes), `pubnet-65480300`, `pubnet-63920000`,
  `localcore-sac-trust-p28-5`.
- **E1, new, filed as stellar-etl#512:** `export_token_transfer` fails on any ledger whose transaction
  meta is v1 to v3 (`localcore-classic-p22-3`, `localcore-muxed-source-p22-3`, from stellar-core
  22.2.1): stellar-etl builds the token transfer processor in unified-events mode, which requires
  `TransactionMeta` v4. Stellar's public archive serves old ledgers with v4 meta, so SDF's own exports
  from it are not affected. The SDK's
  other constructor handles both ledgers. Evidence: `corpus/evidence/stellar-etl-token-transfer-pre23.md`.

- **E2, new, filed as stellar-etl#513:** a revocation that redeems pool shares in two pools at once gets one
  `liquidity_pool_revoked`, for one pool, and that effect's `reserves_revoked` names the other
  pool's AAA claimable balance. Shown on `localcore-pool-revoke-two-pools-7` (stellar-core 30.0.0);
  Horizon has the same code. Evidence: `corpus/evidence/stellar-etl-pool-revocation.md`.
- **E3, new, filed as stellar-etl#514:** the pool-share trustlines that revocation removes get no
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
- **Sequences are few and checked at the end for trustlines only.** Every corpus entry is still
  replayed alone; the one sequence (`trustline-churn`) was built for #687. The end-state check reads
  `trustline_balances`; accounts, pool shares and contract balances at the end of a sequence are not
  compared yet. A run of consecutive archive ledgers taken without looking would be a blind test.
- **Current balances from protocol 23 only.** The `native_balance` check skips ledgers before
  protocol 23: wallet-backend's documented contract (`docs/architecture/state-changes.md`, and
  `internal/indexer/processors/accounts.go` lines 30–37 at `3e22515a`) folds the Soroban fee refund
  from the post-apply list that protocol 23 introduced, and before 23 the refund is in
  `txChangesAfter`. Its backfill does not write `native_balances` either: backfill persists through
  `insertIntoDB` (`internal/services/ingest.go:265`, called from `ingest_backfill.go:326`), which
  inserts transactions, operations, their participant rows and state changes only. So a pre-23
  ledger's balance never reaches that table, and the skip hides no defect.
- **Trustlines created with no flags** expect a `BALANCE_AUTHORIZATION SET` row with no flags. That is
  what wallet-backend stores: the one such trustline in the corpus (`testnet-5708889`) passes at
  `main`.
- **No pool trades and no liquidity-pool share balances for wallet-backend.** Its state-change
  vocabulary has no trade or pool rows, and the adapter does not read its liquidity-pool share
  tables, so a pool trade is checked only through the balance rows of the accounts it moves.
- **Balances held by contracts are not checked.** The oracle reads account and trustline balances;
  a Stellar Asset Contract balance held by a contract is a `CONTRACT_DATA` balance entry it does not
  read yet, and the adapter does not read wallet-backend's `sac_balances` table. Movements of
  contract-held balances are therefore unchecked, for asset contracts as well as other tokens.

## Next

- **Expectations for more entries.** `tools/indexer_expect.py` has one rule so far
  (`soroban-created-trustline`). Running it on the protocol 30 entries with that shape
  (`testnet-5709224`, `golden-invokehostfunction-4c437318-42`) would check them at `main` too.
- **#716's second muxed producer** (a SEP-41 event naming a muxed `ScAddress`) is not reproduced.
  The corpus entries with `scaddress-muxed-account` are protocol 29 and 30, which the commits before
  #693 cannot decode; it needs a protocol 23 to 28 ledger with such an event.
