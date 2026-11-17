# Filed 17 November 2026: https://github.com/stellar/stellar-etl/issues/515

**Title:** `export_ledger_entry_changes` writes nothing when `--start-ledger` equals `--end-ledger`

At master (`2b24ec8`), a one-ledger range exports nothing:

```bash
stellar-etl export_ledger_entry_changes --start-ledger N --end-ledger N --output out/
```

The command exits 0, logs nothing and writes no file, for a ledger that does change entries. The other export commands export ledger `N` for the same range, and a range of two or more ledgers works and includes the end ledger.

**Cause.** `StreamChanges` in `internal/input/changes.go`:

```go
batchStart := start
batchEnd := uint32(math.Min(float64(batchStart+batchSize), float64(end)))
for batchStart < batchEnd {
```

With `start == end` the condition is false on entry, so no batch is sent. Everything around it treats the range as inclusive: `ExtractBatch` reads `[batchStart, batchEnd]`, the command prepares `BoundedRange(start, end)`, and `TestStreamChangesBatchNumbers` expects 1 to 65 as one batch. That test has no case for `start == end`.

**Impact.** Low. Runs over longer ranges are not affected. A one-ledger backfill or spot check produces nothing and reports success, which is easy to miss. I do not know whether any scheduled job passes equal start and end.

**Expected.** Either ledger `N` is exported, or the command fails with a message that the range is empty.

Found while running stellar-etl on single ledgers in https://github.com/ABS-gmbh/shapecov (`harness/replay/adapters/stellar-etl`), where it means the entry-change exports cannot be checked one ledger at a time.
