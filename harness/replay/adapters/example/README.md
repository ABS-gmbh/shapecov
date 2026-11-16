# Example adapter: a toy indexer, two ways

The harness runs against any indexer that has an adapter ([`../../ADAPTER.md`](../../ADAPTER.md)).
This directory is the smallest complete one, to read in a few minutes:

| File | What it is |
|---|---|
| [`toy.py`](toy.py) | A toy indexer, about 100 lines of standard-library Python. It reads one ledger from stellar-rpc's `getLedgers`, decodes it, and stores each transaction's and each operation's participants in SQLite. |
| [`adapter.py`](adapter.py) | The four verbs ADAPTER.md defines. `prepare --ref envelope` or `--ref meta` picks the variant; `run` starts `toy.py` in the pinned Python image on the harness's internal network and reads the SQLite file back into `observation.json`. |
| [`expect.py`](expect.py) | The oracle mapping. The toy stores only participants, so the only check is the participant rule: everything stored must be an address the transaction's meta shows. |
| [`check.py`](check.py) | Checks the recorded runs, with no Docker. In the quick check. |

The two variants differ in one function, and show the RFP's second rule, "derive participants from
the meta, not the envelope":
- **`envelope`** records every address the envelope names: its source, each operation's source,
  destinations and authorization entries.
- **`meta`** records the source and fee-bump source, which signed, and the owner of every account,
  trustline, offer or data entry the transaction changed.

## Result

Run on four ledgers whose envelopes name addresses their meta does not show
([`../../RESULTS-example.md`](../../RESULTS-example.md), [`../../out-example/`](../../out-example/)):

| Ledger | What the envelope names that the meta does not show | `envelope` | `meta` |
|---|---|---|---|
| `localcore-preauth-failed-6` | the destination of a payment in a failed transaction | **fails** | passes |
| `localcore-planted-auth-5` | an account in an authorization entry no `require_auth` matched | **fails** | passes |
| `localcore-declared-deploy-6` | the deployer of a contract an authorization entry declares, which never runs | **fails** | passes |
| `testnet-4437357-signed-payload-signer` | two accounts in a failed transaction, and the contract a transaction invokes | **fails** (10 of 12 checks pass) | passes |

The same rule found the same mistake in wallet-backend: before three fixes in September 2026 it
recorded these addresses as participants (finding R11 in [`FINDINGS.md`](../../../../FINDINGS.md)).

## Run it

Needs Docker, like every replay.

```sh
python3 harness/replay/replay.py run --adapter example --refs envelope,meta --inputs rpc \
        --entries localcore-preauth-failed-6,testnet-4437357-signed-payload-signer,localcore-planted-auth-5,localcore-declared-deploy-6 \
        --out harness/replay/out-example
python3 harness/replay/adapters/example/check.py
```

The "commit" of a variant is a digest of the variant's name and `toy.py`, so a change to the toy
shows up as a new commit and `check.py` asks for a rerun.

## Writing an adapter for a real indexer

Start from this one and replace `toy.py` with the indexer:
- `prepare` builds the indexer at the commit asked for, unmodified, in Docker;
- `up` starts the services it needs (its database);
- `run` points it at the job's `rpc` URL or data-lake bucket, waits for it to finish the one ledger,
  and reads back what it stored;
- `expect.py` names, in the indexer's own vocabulary, the rows the oracle expects. Define
  `manifest_expectations` to return `[]` if the indexer has no state-change rows: the manifest's
  hand-written expectations are wallet-backend's.

The two real adapters, [`../wallet-backend/`](../wallet-backend/) and
[`../stellar-etl/`](../stellar-etl/), follow the same shape.
