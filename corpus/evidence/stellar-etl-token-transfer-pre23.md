# Evidence: stellar-etl `export_token_transfer` rejects every ledger before protocol 23

Found by the replay harness's stellar-etl adapter on 15 November 2026, at stellar-etl `master`
`2b24ec89` (go-stellar-sdk `v0.8.1-0.20261106081502-e31e3b146d00`). Not filed upstream yet. The
draft issue text is `issues/E1-stellar-etl-token-transfer-pre23.md`.

## What happens

`export_token_transfer` exits with a fatal error on a ledger before protocol 23 that holds any
transaction. The other exports (`export_transactions`, `export_operations`, `export_effects`) take
the same ledger without error.

```
level=fatal msg="could not transform token transfers for ledger 3: error reading from unified events stream, expected version 4 got 3"
```

Two corpus entries show it, both real ledgers from a local stellar-core 22.2.1 on the testnet
passphrase (`tools/localcore.py`):

| Entry | Protocol | Transactions | `export_token_transfer` |
|---|---|---|---|
| `localcore-classic-p22-3` | 22 | one `CreateAccount` (classic only) | exit 1, the error above |
| `localcore-muxed-source-p22-3` | 22 | one `InvokeHostFunction` | exit 1, the error above |

The classic-only ledger rules out anything Soroban-specific: every transaction in a
protocol 22 ledger has `TransactionMeta` v3.

## Cause

`internal/transform/token_transfer.go` builds the processor with
`token_transfer.NewEventsProcessorForUnifiedEvents(networkPassphrase)`. In that mode the SDK's
`generateFeeEvents` requires `TransactionMeta` v4 and returns the error above for anything else
(`processors/token_transfer/token_transfer_processor.go`, "If processor is configured to read from
unified events, then txMeta version MUST BE 4"). Fee events are generated for every transaction,
so no transaction in a v3 ledger gets through.

Until stellar-etl #340 ("Protocol 23", commit `2c9ee7c`, September 2025) the same line was
`token_transfer.NewEventsProcessor(networkPassphrase)`, which derives events from ledger entry
changes and handles older ledgers. #340 swapped the constructor and added no protocol check.

## The SDK's other constructor handles these ledgers

`repro/stellar-etl-ttp/` runs the pinned go-stellar-sdk's processor on one ledger in both modes and
then the SDK's own `VerifyEvents` (which checks the events against the ledger's balance changes):

```
cd repro/stellar-etl-ttp
go run . ../../corpus/entries/localcore-classic-p22-3.LedgerCloseMeta.xdr.b64 "Test SDF Network ; September 2015"
```

Output for both entries (event bodies shortened):

```
ledger 3 protocol 22
NewEventsProcessorForUnifiedEvents: 0 events, error: error reading from unified events stream, expected version 4 got 3
NewEventsProcessor: 2 events, error: <nil>
  fee ...       (localcore-classic-p22-3: the fee, then the CreateAccount's transfer)
  transfer ...
VerifyEvents(unified=false): <nil>

ledger 3 protocol 22
NewEventsProcessorForUnifiedEvents: 0 events, error: error reading from unified events stream, expected version 4 got 3
NewEventsProcessor: 2 events, error: <nil>
  fee ...       (localcore-muxed-source-p22-3: the fee and its refund)
  fee ...
VerifyEvents(unified=false): <nil>
```

Built with `golang:1.27.3` and `CGO_ENABLED=1`, the toolchain stellar-etl's own
`docker/Dockerfile` uses.

## Impact

Any re-export of token transfers for a range that starts before protocol 23 stops at the first
ledger with a transaction. That covers backfills after a fix to the token transfer path, such as
the one stellar-etl #450 (fabricated muxed destinations) would need. With the default
`--strict-export` the run is fatal; without it, the batch's token transfers are logged as failures
and skipped.

## Suggested fix

Choose the constructor by the ledger's protocol: `NewEventsProcessorForUnifiedEvents` from protocol
23, `NewEventsProcessor` before it. The `VerifyEvents` call in the same function already takes the
mode as its third argument.

## Searched before writing this

stellar/stellar-etl issues (all states) and stellar/go-stellar-sdk issues, 15 November 2026:
nothing on token transfers failing before protocol 23. The nearest are stellar-etl #438 (a
consistent `--strict-export` error strategy, general) and #448, the July 2026 transform audit,
which lists the token transfer classification as "verified consistent" without covering
older ledgers.
