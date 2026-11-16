# Fact sheet: confirmation of stellar/wallet-backend#677

Notes for an upstream report, not posted as is. This sheet records what was run and what it showed.

**Kind: confirmation of an open issue, not a new finding.** The defect is
[stellar/wallet-backend#677](https://github.com/stellar/wallet-backend/issues/677), "Transaction
meta participants are silently dropped on every modern ledger", filed by JakeUrban on 3 August 2026
and still open, with the same root cause and fix. ErenTopaal added a concrete case on 15 November:
the sponsor of a claimed and of a clawed-back claimable balance, on local stellar-core 30.0.0
ledgers, with a Go test. The Horizon counterpart is
[stellar/stellar-horizon#259](https://github.com/stellar/stellar-horizon/issues/259), filed by
tolgayayci on 14 November, naming the maker of an offer crossed by a path payment. ShapeCov found it independently, from ledger data, with the replay
oracle's participant rule (ShapeCov record C10). What this sheet adds is the measured extent on real
traffic, below. The user posted it on #677 on 16 November:
https://github.com/stellar/wallet-backend/issues/677#issuecomment-6928536393

### What

`GetTransactionParticipants` (internal/indexer/processors/participants.go, at main `3e22515a`)
means to add every account whose account entry an operation of a successful transaction changed:

```go
101	if transaction.Result.Successful() {
102		metaParticipants, metaErr := participantsForMeta(transaction.UnsafeMeta)
```

`participantsForMeta` (line 66) starts with

```go
68	if meta.Operations == nil {
69		return participants, nil
```

In go-stellar-sdk (v0.7.3, v0.8.0 and the pseudo-version main pins), `TransactionMeta.Operations`
is the union's **v0 arm** (`xdr_generated.go`: `V int32; Operations *[]OperationMeta; V1 ...; V4 ...`).
It is nil for TransactionMeta v1 to v4, which is every meta stellar-core has emitted for years, so
the function always returns nothing. The operation changes live in `V1..V4`;
`ingest.LedgerTransaction.GetOperationChanges(i)` reads them for every version.

The participants that survive come from the envelope (`op.Participants()`), from the
Soroban nonce entries, and the source and fee-bump source. An account that a transaction changes
but that no operation names is in none of them.

### Who is missed (measured)

Replayed through wallet-backend at `3e22515a` (unmodified, the harness's reference adapter), then
compared with an indexer-neutral oracle that reads the meta: for each successful transaction, the
accounts whose account entry an operation updated, against `transactions_accounts`.

- **611 ledgers** (every 20,000th ledger of Stellar's public archive: pubnet from 59,000,000 to
  65,480,000, testnet since its December 2025 reset; protocols 23 to 30). A missed participant is
  an account whose account entry a successful transaction's operation changed and that is not in
  that transaction's `transactions_accounts` rows, counted once per transaction:

  | Network | Ledgers | Transactions | With a missed participant | Missed participants | Per 1,000 transactions |
  |---|---|---|---|---|---|
  | pubnet | 325 | 97,973 | 77 | 88 | 0.79 transactions, 0.90 participants |
  | testnet | 286 | 2,703 | 1 | 1 | 0.37, 0.37 |

  By the operation that changed the account (pubnet): `CLAIM_CLAIMABLE_BALANCE` 66,
  `SET_OPTIONS` 17 (a sponsored signer removed), `CLAWBACK_CLAIMABLE_BALANCE` 4, `ACCOUNT_MERGE` 1;
  testnet: `CLAIM_CLAIMABLE_BALANCE` 1. In every case only the sponsorship count changed: these are
  sponsors whose sponsorship ended. None of the 89 reaches wallet-backend by another path: none is
  an operation participant or the account of a state change of that transaction. Pubnet examples:
  ledger 59160000, transaction `0430b0779e47…`, sponsor
  `GDBSXMDBDHVZ3OMNQWV5MMNPMPOJRZAGEAOVRYWXZG5VC5I5B4SOXSBW`; ledger 59280000, transaction
  `74484df641d3…`, sponsor `GAYUSR2YAYWIDOXHJ37IKUOX2MLCBT4EVLXOU2G2VDB34TCWKSL3WC6H`.
- **ShapeCov corpus** (90 entries): the same for sponsors (pubnet ledger 60280000, transaction
  `2aec2a2d5532…`, a ClaimClaimableBalance; sponsor `GCKIK5UO…`), plus **makers of offers that a
  ManageBuyOffer took completely** (`numSubEntries` and liabilities change): stellar-core golden
  ledgers `golden-frozenledgerkeys-1cd53aa0-23` (transaction `28d3cb9ace47…`, maker
  `GABD6YO3WZ74EM4LRWXHLEAE7BSHRIBH3KF7NQHLH4AYXN3SBM3QV55B`) and `-12c04cf7-20`.

In all three examples the account has no participant row and no state-change row for that
transaction, so wallet-backend's history for that account does not contain it.

Even with the v0 read fixed, `participantsForChanges` counts only ACCOUNT entries, so a maker
whose offer is partly taken (only its trustline and offer entries change) would still be missed.
Whether sponsors and makers should be participants is wallet-backend's decision; the code shows the
intent to include accounts whose entry changed, and that path never runs.

### Reproduce

```sh
git clone https://github.com/ABS-gmbh/shapecov && cd shapecov
# replay the corpus at wallet-backend main (Docker); results in harness/replay/out/
python3 harness/replay/replay.py run --refs 3e22515a44979fdc3a558fda3991ca2b48e38cef --all-entries --inputs datalake
python3 harness/replay/replay.py check --oracle
```

Each missing participant is an oracle failure labelled `stellar/wallet-backend#677`
(`harness/replay/adapters/wallet-backend/known.json`); with that rule removed, each is reported as
unexplained.

### The fix

#677 already proposes it: read each operation's changes through `GetOperationChanges`, which handles
every meta version. One thing the measurement adds: `participantsForChanges` counts only ACCOUNT
entries, so even after that fix a maker whose offer is only partly taken (its trustline and offer
change, not its account entry) would still not be a participant.
