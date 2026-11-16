# Detection backtest

The RFP's acceptance check for the replay harness is that it "reproduces wallet-backend#729, #731
and #716 on pre-fix commits and passes on the fixed ones". This applies the same check to the
2026 bug history of both SDF pipelines: for every fix that concerns a ledger shape, replay the corpus
at the commit before the fix and at the fix, and judge each replay with the oracle only, never with
a hand-written expectation.

Run on 16 November 2026. Claims are machine-checked: `python3 harness/replay/replay.py backtest`
verifies every row of `backtest.json` against the recorded results.

## Method

- **What counts as a detection.** A fix is detected when at least one ledger fails at the parent
  (the indexer mishandles or drops it, or the oracle reports a failure no known issue explains) and
  passes at the fix. A fix whose failure changes form but persists is not a detection.
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

## Scope

All wallet-backend commits from 1 July to 16 November 2026 whose subject starts with `fix` and that
touch `internal/indexer`, `internal/ingest`, `internal/services` or `internal/data`: 47. A fix is in
scope when it changes how a ledger's contents become stored rows, or stops ingestion halting on a
valid ledger.

Out of scope (30): metrics, pool sizing, commit barriers, lock handling, migrations, GraphQL, indexes
and performance; checkpoint fixes (`a3483497`, `1d74900e`; the harness serves no history archive);
the API-layer fixes `5c780dd8` (#757, an account-history loader bound) and `bf15e8c2` (a query
plan); and the multi-ledger batch fixes `ee82038d` and `f5b67b07` (the harness replays one ledger
per run).

## wallet-backend: 17 in-scope fixes

**Detected 4 of 17 in-scope fixes; 2 with a blind ledger.** Each row: the fix, the replays at its parent (pass 1 corpus / pass 2 sweep ledgers), and either the ledgers that fail at the parent and pass at the fix, or what would catch it.

| Fix | Issue | Subject | Replays at parent | Result | Ledgers, or what would catch it |
|---|---|---|---|---|---|
| `666717aa` | wallet-backend#641 | fold fee-phase changes into native balances | 12 / — | missed | Read account balances (the accounts table), which the adapter does not, plus a ledger where an account's XLM moves only in the fee phase: a fee bump whose fee source does nothing else (1,005 fee bumps are in the corpus). |
| `bd545417` | wallet-backend#687 | keep a same-ledger REMOVE so deletes are never lost | 12 / — | missed | Read the current-state tables (trustlines, pool shares, SAC balances), plus a ledger that creates and removes the same entry: a local-core scenario adding and removing one trustline in one ledger. |
| `6e5a5910` | wallet-backend#693 | reduce muxed addresses to their base account | 12 / 59 | missed | Not a detection by the rule: on `localcore-muxed-source-p22-3` the failure changes form at the fix (a truncated muxed address becomes a duplicate-key halt) and passes only from `bb0b162b`. |
| `22660cf4` | wallet-backend#695 | verify SAC before recording contract balances | 12 / 59 | **detected, blind** | pass 1: `pubnet-59220000`, `pubnet-61240000`; pass 2: 31 of 59 sweep ledgers |
| `2c873353` | wallet-backend#729 | handle CAP-40 signed-payload signers | 12 / 59 | **detected, confirmed after reading the fix** | pass 1: `testnet-4437357-signed-payload-signer` (chosen or built after reading the fix) |
| `c152783c` | wallet-backend#734 | record SAC-created trustline state changes (#731) | 12 / 59 | **detected, blind** | pass 1: `localcore-sac-trust-p28-5` (chosen or built after reading the fix), `pubnet-63920000`; pass 2: 1 of 59 sweep ledgers |
| `ce0820d7` | wallet-backend#745 | skip contract deploys from unstorable ScAddress kinds | 12 / 59 | missed | A create-contract whose deployer address is a claimable balance or a liquidity pool (protocol 23 or later), as the root host function and inside an auth entry: a local-core scenario at protocol 23 to 28. |
| `490aab41` | — | key the buffer's canonical transactions by ToID, not hash | 12 / 59 | missed | The same envelope at two positions of one ingest batch. The harness replays one ledger per run, so this needs multi-ledger replay. |
| `bb0b162b` | wallet-backend#753 | reduce a Soroban operation's source to its base account | 12 / 59 | **detected, confirmed after reading the fix** | pass 1: `localcore-muxed-source-p22-3` (chosen or built after reading the fix) |
| `7b7ee5f0` | — | map the three frozen-trustline operation result codes | 12 / 59 | missed | A claim, deposit or withdraw failing on a frozen trustline at protocol 26 to 28. The corpus has them only at protocol 30 (`golden-frozenledgerkeys-a0fb94c3-15`, `-d637d647-16`), which the commits before the fix cannot decode: a local-core scenario that freezes a trustline at protocol 26 to 28. |
| `ba821579` | — | drop pool-share balances whose pool row is missing | 12 / 59 | missed | A ledger that changes a pool-share balance whose pool entry the ledger does not touch, replayed into an empty database (no such pass-2 ledger halted the parent). |
| `666a64d4` | — | skip events whose address kind an account column cannot store | 12 / 59 | missed | A SEP-41 or SAC event whose address topic is a claimable balance or a liquidity pool (protocol 23 or later): a local-core scenario with a token contract that emits one. |
| `9538b3ca` | — | derive Soroban participants from executed meta, not the auth tree | 12 / 59 | missed | An auth entry naming an account that no require_auth matched, plus an oracle rule: every participant is the source, an account whose nonce entry the host created, or an account whose ledger state changed. |
| `80121f3a` | — | record a declared nested deploy only when the meta shows it happened | 12 / 59 | missed | An auth tree declaring a CreateContract that never runs, plus an oracle rule that reports a stored ACCOUNT CREATE for a contract the meta does not create. |
| `e2da4cad` | — | a Soroban participant is an address that authorised the operation | 12 / 59 | missed | The participant rule above, on any contract invocation: the invoked contract and event emitters stop being participants. Soroban invocations are in the corpus; the rule is what is missing. |
| `ff73ff46` | wallet-backend#803 | validate Blend pool name bytes and length on decode | 64 / 59 | missed | A Blend pool whose name is not valid UTF-8 or longer than the cap. Blend state is outside the oracle's model; needs a Blend deployment in a local-core scenario. |
| `3e22515a` | wallet-backend#802 | cap Blend decimals at 70 | 64 / 59 | missed | A Blend pool whose reserve config has decimals above 70; same as above. |

## stellar-etl: the 16 issues of the July audit epic (#448)

stellar-etl has no fix commits for these yet, all 16 are open. The oracle ran at `master`
(`2b24ec89`) over the corpus and over the 611-ledger sweep; "flagged" means it reported the issue's
rows from ledger data.

| Issue | In scope? | Oracle at `master` | What would catch it |
|---|---|---|---|
| #449 trust_lines asset_id hashed from the enum name | no: an identifier derivation in a table the adapter does not export | — | — |
| #450 fabricated muxed destination for text/hash memos | yes | **missed**: the oracle does not model muxed destinations. The evidence already shows it: in `localcore-memo-and-offer-p30-4` a payment to a G address with a text memo is exported with `to_muxed` = `MBYOSWSK…` and `to_muxed_id` 0 | an oracle rule from the CAP-67 transfer event's `to_muxed_id` (an integer gives an M address, a string or bytes gives none); the corpus entry exists |
| #451 rounding_slippage formula for strict-receive pool trades | yes | not run: the adapter does not run `export_trades` | `export_trades` in the adapter, and the pool trades already in the pubnet corpus ledgers |
| #452 diagnostic events emitted twice in contract events | yes | not run: the adapter does not run `export_contract_events` | `export_contract_events` in the adapter; every Soroban corpus ledger has diagnostic events |
| #453 Soroban fee fields (fee-bump undercount, refund zeroed for muxed fee source) | yes | **missed**: the oracle checks fees through token transfers, not the transactions export's fee columns | compare `fee_charged` and `resource_fee_refund` with the oracle's fee bucket, plus a new entry: a fee bump with a muxed fee source around a Soroban transaction (a local-core scenario), and a protocol 20 Soroban fee bump from the public archive |
| #454 amounts as float64 | no: a representation contract, not a ledger shape (the adapter reads `amount_raw`) | — | — |
| #455 path-payment amount JSON type varies with success | no: serialization type stability | — | — |
| #456 trade claims emit spurious offer effects | yes | **missed**: the oracle does not report extra effects | report effects with no matching ledger change; the 319 crossed offers in the corpus already show it |
| #457 allow_trust effect types | yes | **missed**: the oracle's effect vocabulary was taken from stellar-etl's own output, so it cannot flag that choice | map `AllowTrust` to Horizon's `trustline_authorized` / `deauthorized` types; `ALLOW_TRUST` ledgers exist in the corpus (`testnet-5710719`) |
| #458 effect index off by one | no: numbering convention | — | — |
| #459 forked SAC helpers in contract_data | yes | not run: the adapter does not run `export_ledger_entry_changes` | that export in the adapter; native-asset balance entries are in the Soroban corpus ledgers |
| #460 CAP-73 effect gaps | yes | **flagged, blind**: 5 rows in 4 ledgers (`testnet-5709224`, `pubnet-65480300`, `pubnet-63920000`, `localcore-sac-trust-p28-5`); the oracle reported them as unexplained before the issue was found | — |
| #461 misnamed hash columns | no: naming | — | — |
| #462 create_contract details omit salt; contract_id heuristic | yes | **missed**: the oracle does not check operation details | check `create_contract` details against the envelope; deploys are in the corpus |
| #463 dead code | no | — | — |
| #464 fee-bump inner signers captured nowhere | no: a schema omission by design | — | — |

**stellar-etl: 1 of 9 in-scope issues flagged (blind).** Three are in exports the adapter does not
run yet (#451, #452, #459). Of the other five, four (#450, #456, #457, #462) are misses whose shapes
the corpus already has, so each needs an oracle rule, not a new ledger; #453 needs both a rule and
a new entry (none of the corpus's 1,005 fee bumps has a muxed fee source on a Soroban transaction). The three the RFP's background names: #450 is in the corpus and needs the
muxed-destination rule; #454 is a precision contract, not a ledger shape; #457 needs the oracle to
use Horizon's effect vocabulary instead of stellar-etl's.

## Reproduce

```sh
# pass 1: the corpus, at each parent and fix
python3 harness/replay/replay.py run --refs <parent>,<fix>,... --all-entries --inputs datalake \
        [--max-protocol 28] --out harness/replay/out-backtest
# pass 2: build the sweep subset (harness/replay/README.md, "Sweep"), then
python3 harness/replay/replay.py run --corpus <sweep subset> --refs ... --all-entries --inputs datalake --out <dir>
python3 harness/replay/replay.py backtest
```
