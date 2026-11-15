# Filed 15 November 2026: https://github.com/stellar/stellar-etl/issues/512

The filed text links the two ledger files and the evidence note directly; otherwise it is this.

**Title:** export_token_transfer fails on every ledger before protocol 23 (unified-events processor requires TransactionMeta v4)

### What

`export_token_transfer` exits with a fatal error on any ledger before protocol 23 that contains a
transaction:

```
level=fatal msg="could not transform token transfers for ledger 3: error reading from unified events stream, expected version 4 got 3"
```

`export_transactions`, `export_operations` and `export_effects` process the same ledgers without
error.

### Why

`internal/transform/token_transfer.go` uses
`token_transfer.NewEventsProcessorForUnifiedEvents(networkPassphrase)`. In that mode
go-stellar-sdk's `generateFeeEvents` requires `TransactionMeta` v4, and fee events are generated
for every transaction, so no transaction in a v3 (pre-protocol 23) ledger gets through. Before
#340 the call was `NewEventsProcessor(networkPassphrase)`, which handles these ledgers. #340
changed the constructor without a protocol check.

### Reproduce

Two protocol 22 ledgers produced by stellar-core 22.2.1 on the testnet passphrase, one with only a
`CreateAccount`, one with an `InvokeHostFunction`:
https://github.com/ABS-gmbh/shapecov/tree/main/corpus/entries (`localcore-classic-p22-3`,
`localcore-muxed-source-p22-3`). Served as a Galexie data lake and run with stellar-etl `master`
`2b24ec89`: `export_token_transfer --testnet --start-ledger 3 --end-ledger 3` fails as above on
both.

With the same pinned go-stellar-sdk, `NewEventsProcessor` returns the expected events for both
ledgers (fee and transfer; fee and refund), and `VerifyEvents(lcm, passphrase, false)` passes:
https://github.com/ABS-gmbh/shapecov/tree/main/repro/stellar-etl-ttp

### Impact

Re-exporting token transfers for any range that starts before protocol 23 stops at the first
ledger with a transaction, for example a backfill after a fix such as #450.

### Suggested fix

Pick the constructor by protocol version: `NewEventsProcessorForUnifiedEvents` from protocol 23,
`NewEventsProcessor` before it. `VerifyEvents` in the same function already takes the mode as its
third argument.
