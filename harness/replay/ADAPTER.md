# Replay adapter interface

An adapter lets the replay harness run the corpus against one indexer. The harness
(`replay.py`) owns the corpus, the ledger inputs and the verdict. The adapter owns only the
indexer: building it, starting it, pointing it at a ledger, and reading back what it stored.

The reference adapter is `adapters/wallet-backend/adapter.py`. A new adapter goes in
`adapters/<name>/adapter.py` and is selected with `replay.py run --adapter <name>`.

## Rules

1. Run the indexer **unmodified** at the commit asked for. Build it with its own build files and
   its own pinned dependencies. If you ever have to change source or a dependency, report it in
   `prepare` (`source_modified`, `dependencies_modified`); `RESULTS.md` then marks that commit.
2. Expectations never come from the indexer. The adapter reports what was stored; the harness
   compares it with `expected.indexer` from `corpus/manifest.json`.
3. Third-party code runs in Docker, on the network the harness names. That network is created
   with `--internal`, so the indexer has no route to the internet during a run.
4. Container and volume names start with `shapecov-replay-`.

## Calling convention

The adapter is an executable called with a verb. It prints exactly one JSON object as the last
line of stdout and exits 0. Any non-zero exit is an adapter failure. A non-zero exit is not a
verdict about the entry.

```
adapter.py prepare --ref <git ref> --work <dir>
adapter.py up      --commit <sha> --work <dir> --network <docker network>
adapter.py run     --job <job.json> --out <dir>
adapter.py down    --work <dir>
```

The harness calls them in this order for each commit:

```
prepare(ref) -> up(commit) -> run(job) for every entry and input -> down
```

| Verb | Must do | Prints |
|---|---|---|
| `prepare` | Resolve the ref to a commit and build the indexer. Cache by commit. | the commit record (below) |
| `up` | Start long-lived services the indexer needs, such as its database. | any object, e.g. versions used |
| `run` | Give the indexer a clean state, feed it the one ledger in the job, stop it, read back what it stored, and write `observation.json` into `--out`. | `{"observation": path, "ingested": bool, "error": str or null}` |
| `down` | Remove every container `up` and `run` started. | `{}` |

### Commit record (`prepare`)

```json
{
  "adapter": "wallet-backend",
  "ref": "2a0a84ea12",
  "commit": "2a0a84ea12523b6c92e278c0c84b443041240095",
  "commit_date": "2026-09-04T15:07:54-04:00",
  "subject": "ci: make deploying a dev image to shared dev opt-in (#725)",
  "source_modified": false,
  "dependency_pins": {"github.com/stellar/go-stellar-sdk": "v0.7.3"},
  "dependencies_modified": false
}
```

Required: `commit`, `commit_date`, `subject`, `source_modified`, `dependency_pins`,
`dependencies_modified`. Extra fields are kept and shown in `out/runs.jsonl`.

## The job (`run --job`)

The harness writes one job per entry, commit and input:

```json
{
  "job_version": 1,
  "entry_id": "testnet-4437357-signed-payload-signer",
  "commit": "2a0a84ea12523b6c92e278c0c84b443041240095",
  "input": "rpc",
  "network_passphrase": "Test SDF Network ; September 2015",
  "ledger": {"seq": 4437357, "hash": "0984e2…", "close_time": 1788210372, "protocol": 28},
  "rpc": {"url": "http://shapecov-replay-feeder:8000/rpc/<entry-id>"},
  "datalake": {"s3_endpoint": "http://shapecov-replay-feeder:9000",
               "bucket_path": "shapecov-lake/<entry-id>", "region": "us-east-1"},
  "history_archive": {"url": "http://shapecov-replay-feeder:8000/archive/<entry-id>"},
  "docker_network": "shapecov-replay-net",
  "timeout_seconds": 120,
  "work_dir": "<the --work dir given to prepare>"
}
```

- `input` is `rpc` or `datalake`. Use the matching block and nothing else.
- `rpc` is a mock stellar-rpc that serves `getHealth`, `getNetwork`, `getLatestLedger`,
  `getVersionInfo`, `getLedgerEntries` (always empty) and `getLedgers`, with the real JSON-RPC
  shapes. Its window is exactly the one ledger in the job.
- `datalake` is the Galexie layout (`.config.json`, `<partition>/<file>.xdr.zst`, zstd
  `LedgerCloseMetaBatch`, one ledger per file) on an S3-compatible store: GET, HEAD and
  ListObjectsV2, path style. Any credentials are accepted.
- `network_passphrase` comes from the entry, not from a default. Entries from stellar-core's
  own test data use `(V) (;,,;) (V)`.
- The history archive is not served. Position the indexer so that it does not need a
  checkpoint (the wallet-backend adapter writes its ingest cursor to `seq - 1`).

## The observation (`run` output)

`<out>/observation.json`. Addresses are SEP-23 strkeys. Where the indexer stores raw bytes, also
give the stored bytes as hex, so that a damaged value can be shown exactly.

```json
{
  "observation_version": 1,
  "adapter": "wallet-backend",
  "commit": "…",
  "input": "rpc",
  "entry_id": "…",
  "ledger_seq": 4437357,
  "ingested": true,
  "error": null,
  "adapter_failure": false,
  "transactions": [
    {"hash": "…", "tx_order": 1, "result_code": "…", "participants": ["G…"]}
  ],
  "operations": [
    {"tx_hash": "…", "tx_order": 1, "op_order": 1, "type": "SET_OPTIONS", "participants": ["G…"]}
  ],
  "state_changes": [
    {"tx_hash": "…", "tx_order": 1, "op_order": 1,
     "category": "SIGNER", "reason": "ADD",
     "account": "G…", "signer_key": "P…", "token": null, "spender": null,
     "creator": null, "destination": null,
     "stored": {"account": "<hex>", "signer_key": "<hex>"},
     "fields": {"signer_weight_new": 1}}
  ],
  "unreadable": [
    {"table": "state_changes", "column": "signer_account_id", "stored_hex": "…",
     "reads_back_as": "P…", "problem": "signed payload must be …, has 32 bytes"}
  ],
  "row_counts": {"transactions": 12, "state_changes": 17}
}
```

| Field | Meaning |
|---|---|
| `ingested` | The indexer finished this ledger: for wallet-backend, its cursor reached `seq`. |
| `error` | The indexer's own error when it did not finish the ledger, else `null`. |
| `adapter_failure` | `true` when the adapter, not the indexer, failed, for example the indexer's migrations did not run. The harness then reports `error`, not a verdict. |
| `unreadable` | Every stored address that does not decode as a valid SEP-23 address. |
| `transactions`, `operations`, `state_changes` | What the indexer stored for this ledger, read back from its own storage. An indexer without one of these concepts leaves the list empty. |

Write any logs you have (`ingest.log`, `migrate.log`, …) next to `observation.json`. The
harness keeps the whole directory as evidence.

## Optional: the oracle mapping (`expect.py`, `known.json`)

`tools/oracle.py` reads a ledger's meta and lists what changed in ledger state, independently of any
indexer: accounts created or removed; signers added, removed or reweighted; thresholds, flags and
home domain; data entries; trustlines added, removed or re-limited; trustline authorization; and
contract instances created. `oracle.balances()` adds the net change of every account's XLM and
credit-asset trustline balance per operation, plus each transaction's net fee.

An adapter can opt in to having every such change checked, not only the manifest's expectations,
by providing two files next to `adapter.py`:

| File | Contains |
|---|---|
| `expect.py` | `expectations(changes, network_passphrase)`: the row the indexer should store for each oracle change, as expectations in the format below (`state_change`, `participant`, …), each with a `via` field saying where the oracle saw the change. Also `known_issue(expectation)`. |
| `known.json` | Open upstream issues that explain a failing oracle expectation, as match rules on the row and on where the change happened. |
| `expect.py` (optional) | `balance_expectations(records, network_passphrase)`: one `balance_net` expectation per balance record, naming the indexer's token and operation position. The harness then also reports stored balance movements for an account where the ledger shows none. |

`expect.py` only names rows in the indexer's own vocabulary; whether a row is expected always comes
from the ledger. The harness then gives every replay a second verdict, `oracle`, beside the
`result` below. Each failing oracle check is either labelled with a known issue or listed as
**unexplained**: a candidate new finding. The `result` used by `sightings.json` is unaffected.

## The verdict (harness side, `classify.py`)

Each run gets exactly one result:

| Result | When |
|---|---|
| `pass` | Ingested, every stored address reads back, and every expectation is met. |
| `mishandled` | The indexer raised an error on this valid ledger, or stored a wrong or unreadable value. |
| `dropped` | The ledger, or a row the manifest expects, is missing, and no error was raised. |
| `error` | The adapter or the feeder failed. This says nothing about the indexer. |

If `mishandled` and `dropped` both apply, the result is `mishandled` and both lists are kept.

Expectation kinds the classifier understands (`expected.indexer[].expect` in the manifest):

| Kind | Fields | Met when |
|---|---|---|
| `signer_state_change` | `signer_key` | a `SIGNER` state change with exactly that key is stored |
| `state_change` | `category`, optional `reason`, `account`, `token`, `signer_key`, `spender`, `creator`, `destination`, `tx_hash`, `fields`, `count` | at least `count` (default 1) matching rows are stored |
| `no_state_change` | same selectors | no matching row is stored |
| `participant` | `account`, optional `tx_hash` | the account is recorded on the transaction, or on any transaction of the ledger |
| `no_participant` | `account`, optional `tx_hash` | it is not |
| `transaction` | `hash` | the transaction is stored |
| `balance_net` | `account`, `token`, `tx_hash`, `op_order`, `delta` | the account's stored BALANCE rows for that token, transaction and operation (`op_order` 0: the fee row) add up to `delta`: CREDIT +amount, DEBIT −amount; MINT and BURN rows mark the issuer's side and do not count |

A stored address that is a byte prefix of the expected one is reported as truncated, with both
values. That is how the #716 truncation shows up.
