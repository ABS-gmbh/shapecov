# Detection backtest

The RFP's acceptance check for the replay harness is that it "reproduces wallet-backend#729, #731
and #716 on pre-fix commits and passes on the fixed ones". This applies the same check to the
2026 bug history of both SDF pipelines: for every fix that concerns a ledger shape, replay the corpus
at the commit before the fix and at the fix, and judge each replay with the oracle only, never with
a hand-written expectation.

Run on 16 November 2026. Claims are machine-checked: `python3 harness/replay/replay.py backtest`
verifies every row of `backtest.json` against the recorded results.

## Method

- **What counts as a detection.** A fix is detected on a ledger when, at the parent, the ledger has
  failures that bear on the fix, and at the fix it has none. The failures that bear on a fix are
  the indexer's own result (`mishandled` or `dropped`), the oracle failures no known issue
  explains, and the oracle failures of the kind this fix removes. Failures present on both sides
  of a fix and attributed to a different fix (`known.json` `fixed_by`) or to an open issue are
  ignored for that fix. A fix whose parent ingested a ledger that the fix then halts on never
  counts: the failure changed form, and the fix's oracle failures are unknown, not gone. Each
  detecting ledger's counts at the parent and at the fix are recorded in `backtest.json`, shown in
  the table as "parent → fix", and checked by `replay.py backtest`.
- **One record, four kinds.** wallet-backend fixed taking participants from the envelope in three
  commits with no issue (record R11). The participant rule tells four kinds of its failures
  apart, and each belongs to one fix: a failed transaction's addresses and an account only an
  unmatched authorization entry names (9538b3c), a state change for a contract a declared deploy
  would have created (80121f3), and a contract participant the meta never shows (e2da4ca). At
  666a64d, 9538b3c, 80121f3 and e2da4ca the pass-1 corpus counts are: failed transaction
  241, 0, 0, 0; account participant 2, 0, 0, 0; state change 1, 1, 0, 0; contract participant
  128, 128, 127, 0.
- **Blind or not.** A detection is *blind* when the ledger that shows it was not chosen or built
  with knowledge of that fix: network ledgers picked by stride or by schema-cell cover. A detection
  on an entry built or selected after reading the fix or its issue is labelled "confirmed after
  reading the fix".
- **Two corpora.** Pass 1 is `corpus/` itself. The commits before September pin go-stellar-sdk
  v0.7.3 or older, which cannot decode protocol 29 or 30, so for them only the 12 entries of
  protocol 28 or earlier apply. Pass 2 adds 59 blind network ledgers (19,686 transactions, protocols
  23 to 28) from the sweep of Stellar's public archive (`harness/replay/README.md`, "Sweep"): the 35
  that together cover the most schema cells and patterns, and the 4 busiest pubnet ledgers of each
  protocol. Pass 2 ran at 23 of the 27 commits: it was stopped before the two July pairs (#641 and
  #687), whose commits take about 25 seconds per ledger and whose fixes change tables the adapter
  does not read, so pass 2 could not change their result. Their pass-2 column shows "—".
- **One input.** The data lake (`datalake`); both inputs agree on every sighting.
- **The oracle's participant rule** (the RFP's second rule: who a transaction affected comes from the
  meta, not the envelope) was added after the first run. Every recorded replay of both passes was
  judged again with it (`replay.py rejudge`, which does not run the indexer again). The rule:
  every participant and state-change account stored for a transaction is an address its meta shows
  (an entry created, changed or removed, a nonce, a contract or system event), the transaction's
  source or fee-bump source, or an operation source of a successful transaction. A failed transaction's meta shows only its fee and sequence number.
  Failures that wallet-backend later fixed are labelled with record R11 at the commits before the
  fix and still count as failures here.
- **The balance rule** (wallet-backend's `native_balances` after the ledger: every account whose
  XLM balance the ledger changed, the fee phase included, has a row with its final balance; ledgers
  of protocol 23 and later) was added for #641 and needs the table read back, so the corpus was
  replayed again at #641's parent and fix and at `main`. At `main` it is clean on every ledger.
  Ledgers before protocol 23 are skipped because wallet-backend's documented contract does not
  cover them: `docs/architecture/state-changes.md` and `internal/indexer/processors/accounts.go`
  lines 30–37 at `3e22515a` fold the Soroban fee refund from the post-apply list that protocol 23
  introduced (before 23 it is in `txChangesAfter`). Backfill, the only way such ledgers would reach
  the table, does not write `native_balances` (`insertIntoDB`, `internal/services/ingest.go:265`,
  called from `ingest_backfill.go:326`).
- **Built after reading the fix.** `localcore-planted-auth-5` and `localcore-declared-deploy-6`
  (scenario `participants-p28` in `tools/localcore.py`) were built after reading 9538b3c and
  80121f3: an authorization entry no `require_auth` matches, and one declaring a deploy that never
  runs. The sequence `trustline-churn` (scenario `trustline-churn-p28`) and its end-state check of
  `trustline_balances` were both written after reading #687's fix (`bd545417`), so its detection
  is not counted as blind.
- **Sequences.** #687 needs a row an earlier ledger wrote: `replay.py run --sequence` ingests
  consecutive corpus ledgers into one database in one run and then checks the current-state
  tables against the oracle (results in `out-sequences/`, kept slim in `backtest/sequences.jsonl`).
  At `bdb934bc` the trustline that ledger 5 removes, adds again and removes again keeps the row
  ledger 4 wrote; at `bd545417` it is gone. Both inputs, RPC and data lake.

## Scope

A fix is in or out of scope by what it fixes, decided before looking at whether the harness
detects it: in scope when it changes how a ledger's contents become stored rows, or stops
ingestion halting on a valid ledger, and when valid network input can reach it. A fix that only
synthetic input reaches (a ledger no network can produce) is out.

All wallet-backend commits from 1 July to 16 November 2026 whose subject starts with `fix` and that
touch `internal/indexer`, `internal/ingest`, `internal/services` or `internal/data`: 47. In scope: 17.

Out of scope (30): metrics, pool sizing, commit barriers, lock handling, migrations, GraphQL, indexes
and performance; the API-layer fixes `5c780dd8` (#757, an account-history loader bound) and
`bf15e8c2` (a query plan); and four fixes only synthetic input reaches:

- `490aab41` (key the buffer's canonical transactions by ToID, not hash) needs the same transaction
  envelope at two positions. Its own commit message: "Real networks cannot repeat a hash within or
  across ledgers"
  ([`490aab41`](https://github.com/stellar/wallet-backend/commit/490aab41f6caae6479e0a26b8affcf6a934ac875)).
- The checkpoint fixes `1d74900e` and `a3483497` guard a liquidity-pool body that is not constant
  product, which the wire format cannot express; `a3483497`'s message: reaching that branch
  "required hand-building a LiquidityPoolEntryBody the wire format cannot express"
  ([`a3483497`](https://github.com/stellar/wallet-backend/commit/a3483497698f499cfc155425e79773729cc5d6ea)).
- `666a64d4` (skip events whose address kind an account column cannot store) needs an event address
  topic that is a claimable balance or a liquidity pool, in an event wallet-backend decodes: a
  SEP-41 contract's event, or a Stellar Asset Contract's `set_authorized` event or balance key. Its
  own commit message: "The Soroban host does not emit either kind today"
  ([`666a64d4`](https://github.com/stellar/wallet-backend/commit/666a64d426263fa6bd2a0ee61ee8dfb1f4729019)).
  stellar-core's own CAP-67 events do name claimable balances and pools, but under Stellar Asset
  Contracts, and wallet-backend's SEP-41 decoder reads only events of the wasm contracts it has
  classified as SEP-41 (`internal/services/sep41/processor.go`, `processEvent`).

**Scope changes, 16 Nov 2026.** `490aab41` moved out of scope (only reachable on synthetic input):
in-scope fixes for wallet-backend were 17 before it moved. The rule above was then applied to every
other fix of both adapters, detected ones included. None of the detected fixes or flagged
stellar-etl issues is reachable only on synthetic input, so none moved out. Two fixes moved in:
the multi-ledger batch fixes `ee82038d` and `f5b67b07` (a contract rebound from one wasm to
another inside one ingest batch, which a network produces) had been out because the harness
replayed one ledger per run, a reason about detection rather than about what they fix. The
checkpoint fixes stay out, now for the reason above rather than because the harness serves no
history archive. In-scope fixes for wallet-backend: 17 before, 16 after `490aab41` moved out, 18
with the two batch fixes. `backtest.json` records the reason on the out-of-scope fix.
Later the same day, `666a64d4` moved out for the reason above: an earlier reading of this page
said stellar-core's CAP-67 events reach it, which the decoder's contract filter rules out. In-scope
fixes for wallet-backend: 18 before, 17 now.

| Step | Fix moved | Direction | Reason | In scope |
|---|---|---|---|---|
| start | — | — | — | 17 |
| 1 | `490aab41` | out | needs a repeated transaction hash | 16 |
| 2 | `ee82038d`, `f5b67b07` | in | excluded for detection, not content | 18 |
| 3 | `666a64d4` | out | host never emits such addresses | 17 |

## wallet-backend: 17 in-scope fixes

**Detected 13 of 17 in-scope fixes; 5 with a blind ledger.** Each row: the fix, the replays at its parent (pass 1 corpus / pass 2 sweep ledgers), and either the ledgers with a failure at the parent that the fix removes, or what would catch it.

| Fix | Issue | Subject | Replays at parent | Result | Ledgers, or what would catch it |
|---|---|---|---|---|---|
| `666717aa` | wallet-backend#641 | fold fee-phase changes into native balances | 18 / — | **detected, blind** | pass 1: `golden-invokehostfunction-41088f6e-29` (unexplained 2 → none), `golden-invokehostfunction-e0e11e1f-32` (unexplained 2 → none), `localcore-declared-deploy-6` (unexplained 1 → none), `localcore-planted-auth-5` (unexplained 1 → none), `pubnet-60280000` (unexplained 173 → none) |
| `bd545417` | wallet-backend#687 | keep a same-ledger REMOVE so deletes are never lost | 12 / — | **detected, confirmed after reading the fix** | sequence: `trustline-churn` (#687 lost delete 1, mishandled 1 → none; built after reading the fix) |
| `6e5a5910` | wallet-backend#693 | reduce muxed addresses to their base account | 12 / 59 | missed | Not a detection by the rule: on `localcore-muxed-source-p22-3` the failure changes form at the fix (a truncated muxed address becomes a duplicate-key halt) and passes only from `bb0b162b`. On 16 Nov 2026 a ledger whose Soroban operation source is another account's muxed address, named nowhere else in the transaction, was built and replayed: the parent stores it truncated in `transactions_accounts`, and the fix halts on a duplicate `transactions_accounts` key, so the halt is inherent to a muxed Soroban source until `bb0b162b`. The classic paths reduce muxed addresses before storage, so the one other route is a SEP-41 event address, which needs the protocol setup described for `ee82038d` below. |
| `22660cf4` | wallet-backend#695 | verify SAC before recording contract balances | 12 / 59 | **detected, blind** | pass 1: `pubnet-59220000` (mishandled 1, unexplained 1 → none), `pubnet-61240000` (mishandled 1, unexplained 1 → none); pass 2: 31 of 59 sweep ledgers (together mishandled 31, unexplained 31 → none) |
| `2c873353` | wallet-backend#729 | handle CAP-40 signed-payload signers | 12 / 59 | **detected, confirmed after reading the fix** | pass 1: `testnet-4437357-signed-payload-signer` (mishandled 1, unexplained 1 → none; built after reading the fix) |
| `c152783c` | wallet-backend#734 | record SAC-created trustline state changes (#731) | 12 / 59 | **detected, blind** | pass 1: `localcore-sac-trust-p28-5` (dropped 1, unexplained 2 → none; built after reading the fix), `pubnet-63920000` (unexplained 2 → none); pass 2: 1 of 59 sweep ledgers (together unexplained 2 → none) |
| `ce0820d7` | wallet-backend#745 | skip contract deploys from unstorable ScAddress kinds | 13 / 59 | **detected, confirmed after reading the fix** | pass 1: `localcore-deployer-cb-5` (mishandled 1, unexplained 1 → none; built after reading the fix) |
| `ee82038d` | — | claim a contract under the binding each ledger of a batch saw | 0 / — | **detected, confirmed after reading the fix** | sequence: `token-rebind` (mishandled 1, unexplained 1 → none; built after reading the fix). The sequence runs with commit boundaries the harness fixes (README, "Commit boundaries"): a timing control only, the same at the parent and the fix; the indexer's code, configuration and input bytes are untouched. Stable: the parent failed 5 of 5 runs and the fix passed 5 of 5, on both inputs; each failure is the commit of ledgers 6-8 violating fk_sep41_contract_token on sep41_balances, as the fix's message describes. The contract is purpose-built (tools/rebind_token_wasm.py); stellar-core 30.0.0 accepted every transaction and wallet-backend classified it by its own signature check. |
| `f5b67b07` | — | keep a rebound contract classified for every ledger of its batch | 0 / — | missed | Not detected. The sequence `token-rebind-history` (SEP-41 history production only; the upload committed before the deploy, the mint and the rebind, which commit together) was replayed 5 times at the parent and 5 at the fix, on both inputs: the parent recorded the mint every time, so this input does not reach the drop the fix describes. What does is not established. |
| `bb0b162b` | wallet-backend#753 | reduce a Soroban operation's source to its base account | 12 / 59 | **detected, confirmed after reading the fix** | pass 1: `localcore-muxed-source-p22-3` (mishandled 1, unexplained 1 → none; built after reading the fix) |
| `7b7ee5f0` | — | map the three frozen-trustline operation result codes | 13 / 59 | **detected, confirmed after reading the fix** | pass 1: `localcore-frozen-claim-11` (mishandled 1, unexplained 1 → none; built after reading the fix) |
| `ba821579` | — | drop pool-share balances whose pool row is missing | 14 / 59 | **detected, confirmed after reading the fix** | pass 1: `localcore-pool-share-unsponsor-6` (mishandled 1, unexplained 1 → none; built after reading the fix). The ledger is replayed into a database that has no row for that pool, as when live ingestion starts at that ledger, a valid starting state; after a full backfill the pool row exists and the failure does not appear. |
| `9538b3ca` | — | derive Soroban participants from executed meta, not the auth tree | 14 / 59 | **detected, blind** | pass 1: `localcore-declared-deploy-6` (account participant 1 → none; built after reading the fix), `localcore-planted-auth-5` (account participant 1 → none; built after reading the fix), `pubnet-59220000` (failed transaction 20 → none), `pubnet-60280000` (failed transaction 61 → none), `pubnet-61240000` (failed transaction 56 → none), `pubnet-63920000` (failed transaction 103 → none), `testnet-4437357-signed-payload-signer` (failed transaction 1 → none); pass 2: 55 of 59 sweep ledgers (together account participant 8, failed transaction 5583 → none) |
| `80121f3a` | — | record a declared nested deploy only when the meta shows it happened | 14 / 59 | **detected, confirmed after reading the fix** | pass 1: `localcore-declared-deploy-6` (state change 1 → none; built after reading the fix) |
| `e2da4cad` | — | a Soroban participant is an address that authorised the operation | 14 / 59 | **detected, blind** | pass 1: `localcore-sac-trust-p28-5` (contract participant 1 → none), `pubnet-59220000` (contract participant 2 → none), `pubnet-60280000` (contract participant 6 → none), `pubnet-61240000` (contract participant 99 → none), `pubnet-63920000` (contract participant 18 → none), `testnet-4437357-signed-payload-signer` (contract participant 1 → none); pass 2: 51 of 59 sweep ledgers (together contract participant 757 → none) |
| `ff73ff46` | wallet-backend#803 | validate Blend pool name bytes and length on decode | 64 / 59 | missed | What the two Blend misses (`ff73ff46`, `3e22515a`) need. Protocol production now runs in replays (`--protocols`, README "Protocol production"), but wallet-backend classifies only contracts whose wasm is uploaded in the replayed ledgers, and its Blend processor also reads pool and backstop state through RPC (`getLedgerEntries`, `simulateTransaction`), which the mock does not serve. A sequence that uploads Blend's real wasm, taken from the ledger where it was uploaded on the network, and deploys a pool, with those RPC answers recorded from a real stellar-rpc, would reach them. Then, for this fix: a Blend pool whose name is not valid UTF-8 or longer than the cap. |
| `3e22515a` | wallet-backend#802 | cap Blend decimals at 70 | 64 / 59 | missed | What the two Blend misses (`ff73ff46`, `3e22515a`) need. Protocol production now runs in replays (`--protocols`, README "Protocol production"), but wallet-backend classifies only contracts whose wasm is uploaded in the replayed ledgers, and its Blend processor also reads pool and backstop state through RPC (`getLedgerEntries`, `simulateTransaction`), which the mock does not serve. A sequence that uploads Blend's real wasm, taken from the ledger where it was uploaded on the network, and deploys a pool, with those RPC answers recorded from a real stellar-rpc, would reach them. Then, for this fix: a Blend pool whose reserve config has decimals above 70. |

## stellar-etl: the 16 issues of the July audit epic (#448)

stellar-etl has no fix commits for these yet, all 16 are open. The oracle ran at `master`
(`2b24ec89`) over the corpus and over the 611-ledger sweep; "flagged" means it reported the issue's
rows from ledger data.

| Issue | In scope? | Oracle at `master` | What would catch it |
|---|---|---|---|
| #449 trust_lines asset_id hashed from the enum name | no: an identifier derivation in a table the adapter does not export | — | — |
| #450 fabricated muxed destination for text/hash memos | yes | **flagged, confirmed after reading the issue**: 928 rows in 17 ledgers (`localcore-memo-and-offer-p30-4`, 11 pubnet and 5 testnet ledgers). Each is a payment to a G address carrying a text (926) or hash (2) memo that stellar-etl exports with an M address of muxed ID 0. The rule compares the export's `to_muxed` with the CAP-67 transfer event's `to_muxed_id` (an integer gives an M address, a string or bytes gives none); it was written after reading the issue, so the detection is not blind | — |
| #451 rounding_slippage formula for strict-receive pool trades | yes | **flagged, confirmed after reading the issue**: 126 of the 356 strict-receive pool trades in 6 pubnet ledgers export a rounding slippage other than the one Horizon's definition gives (`CalculatePoolExpectation`); the 799 strict-send ones match. The rule ports go-stellar-sdk's two pool formulas and takes the reserves from the pool's state before the operation; the port gives Horizon v30.0.1's stored value on all 1,155 pool trades. The inverted overflow sentinel the issue also names is not exercised: no corpus trade overflows | a pool trade near the int64 limit (a local stellar-core scenario) |
| #452 diagnostic events emitted twice in contract events | yes | **flagged, confirmed after reading the issue**: 1,684 contract events exported twice in 500 transactions on 31 ledgers (the copy from the meta's diagnostic list, which repeats a successful call's events), and 1,692 events of 1,655 failed transactions exported with `in_successful_contract_call` true on 34 ledgers. The rule matches each exported row's event XDR to the meta: every event of the operations and the transaction exactly as often as the meta has it, and the flag equal to the transaction's success. Every other exported contract event matches an event of the meta, except 20 rows in three ledgers: events of failed calls, which only the diagnostic list carries, exported with `in_successful_contract_call` false | — |
| #453 Soroban fee fields (fee-bump undercount, refund zeroed for muxed fee source) | yes | **missed**: the oracle checks fees through token transfers, not the transactions export's fee columns | compare `fee_charged` and `resource_fee_refund` with the oracle's fee bucket, plus a new entry: a fee bump with a muxed fee source around a Soroban transaction (a local-core scenario), and a protocol 20 Soroban fee bump from the public archive |
| #454 amounts as float64 | no: a representation contract, not a ledger shape (the adapter reads `amount_raw`) | — | — |
| #455 path-payment amount JSON type varies with success | no: serialization type stability | — | — |
| #456 trade claims emit spurious offer effects | yes | **flagged, confirmed after reading the issue**: 225 operations in 11 pubnet ledgers export more offer_created/updated/removed effects than the offer entries the operation changed (e.g. 6 for 1 in `pubnet-59220000`). The rule bounds an operation's offer effects by its offer-entry changes and labels the excess #456 only in operations where a trade happened; none occurs elsewhere | — |
| #457 allow_trust effect types | yes | **flagged, confirmed after reading the issue**: 1 row in `testnet-5710719`, an AllowTrust that clears AUTHORIZED; stellar-etl exports two `trustline_flags_updated` effects and no `trustline_deauthorized`. The rule takes the effect type from the flags the operation set and cleared on the trustline (Horizon's model: `trustline_authorized`, `trustline_authorized_to_maintain_liabilities` or `trustline_deauthorized` before `trustline_flags_updated`) | — |
| #458 effect index off by one | no: numbering convention | — | — |
| #459 forked SAC helpers in contract_data | yes | not reachable by a one-ledger replay: `export_ledger_entry_changes`, the export that writes `contract_data`, writes nothing when the range is one ledger (`StreamChanges` in `internal/input/changes.go` loops `for batchStart < batchEnd`, and exits 0); the replay serves one ledger per corpus entry. The shape is there: 22 testnet and pubnet ledgers change a native-XLM asset-contract balance entry, the issue's first point. The adapter now runs the export on sequences (accounts, trustlines, offers, pools, claimable balances); it needs a sequence that changes a native asset-contract balance | a corpus sequence of two or more ledgers that changes a native-XLM asset-contract balance held by a contract, with `contract_data` added to the sequence check |
| #460 CAP-73 effect gaps | yes | **flagged, blind**: 5 rows in 4 ledgers (`testnet-5709224`, `pubnet-65480300`, `pubnet-63920000`, `localcore-sac-trust-p28-5`); the oracle reported them as unexplained before the issue was found | — |
| #461 misnamed hash columns | no: naming | — | — |
| #462 create_contract details omit salt; contract_id heuristic | yes | **flagged, confirmed after reading the issue**: the three deploys from an address preimage in `testnet-5711641` and `testnet-5718650` are exported without their salt. The rule derives each deploy's contract ID and salt from the envelope; every exported contract_id in the corpus matches the derived one, so the footprint heuristic has not misfired yet | a factory deploy (a contract deploying another) would test the contract_id heuristic |
| #463 dead code | no | — | — |
| #464 fee-bump inner signers captured nowhere | no: a schema omission by design | — | — |

**stellar-etl: 7 of 9 in-scope issues flagged (1 blind).** One, #459, is in an export that writes
nothing for the one ledger a replay serves; #453 needs both a rule and a new entry (none of the corpus's 1,005 fee
bumps has a muxed fee source on a Soroban transaction). All three the RFP's background names are
settled: #450 and #457 are flagged from ledger data, and #454 is a precision contract rather than a
ledger shape.

## Reproduce

```sh
# pass 1: the corpus, at each parent and fix
python3 harness/replay/replay.py run --refs <parent>,<fix>,... --all-entries --inputs datalake \
        [--max-protocol 28] --out harness/replay/out-backtest
# pass 2: build the sweep subset (harness/replay/README.md, "Sweep"), then
python3 harness/replay/replay.py run --corpus <sweep subset> --refs ... --all-entries --inputs datalake --out <dir>
python3 harness/replay/replay.py backtest
```
