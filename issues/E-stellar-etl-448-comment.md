# Posted 17 November 2026 on stellar/stellar-etl#448: https://github.com/stellar/stellar-etl/issues/448#issuecomment-6946156859

I replayed real ledgers through stellar-etl at `master` (`2b24ec8`) and compared every exported row with what the ledger itself shows. This is what that gives for the members of this epic, in case it helps with ordering them. Nothing here is a new finding: each line confirms an issue above with a count.

**Sample A:** 611 ledgers, every 20,000th pubnet ledger from 59,000,000 to 65,480,000 and testnet since its December 2025 reset (100,676 transactions, protocols 23 to 30). **Sample B:** 114 ledgers picked for rare shapes.

| Issue | What the replay shows | Sample A, rows | Sample B |
|---|---|---|---|
| #452 | contract events exported twice, and `in_successful_contract_call` true on failed transactions | 52,879 | 1,692 events twice in 508 transactions; 1,730 events of 1,692 failed transactions |
| #450 | an M address with ID 0 for a G destination when the transaction has a text or hash memo | 38,959 | 938 rows in 19 ledgers |
| #456 | more offer effects than offer entries the operation changed | 7,321 | 228 operations in 14 ledgers |
| #457 | `trustline_flags_updated` where Horizon's model has authorized or deauthorized | 69 | 1 |
| #462 | deploys from an address exported without their salt; the exported `contract_id` matched the derived one every time | 19 | 5 deploys |
| #460 | missing CAP-73 effects | 1 | 5 rows in 4 ledgers |
| #451 | rounding slippage of strict-receive pool trades differs from Horizon's definition | not counted | 126 of 356; all 799 strict-send trades match; Horizon v30.0.1 stores the SDK formula's value on all 1,155 |
| #459 | a contract's balance in the native asset contract exported with `balance_holder` and `balance` | not counted | shown on two consecutive ledgers, since a one-ledger range exports nothing (#515); the same entry for a credit asset is as expected |
| #454 | `token_transfer.amount` one stroop short for amounts above 2^53 stroops; the operation detail and the effects are exact | not counted | 2 transfers |

Not exercised: #453 (no ledger in either sample has a Soroban fee bump with a muxed fee source), the overflow sentinel in #451, the durability point in #459, and the members about naming, numbering and schema (#449, #455, #458, #461, #463, #464, #465).

One note on #452. In sample A, 25,844 of 296,278 operation-level contract events are exported twice, 8.7%, against the 15.6% in the issue. I would not read the two as disagreeing: the samples differ (single ledgers 20,000 apart from the public archive, against one hour of the production feed), and the volume of diagnostic events is about the same in both (3.3 and 3.2 per operation-level event).

The rows, the rules and the commands are in https://github.com/ABS-gmbh/shapecov (`harness/replay/RESULTS-stellar-etl.md` and `harness/replay/BACKTEST.md`). I can rerun against a branch if that is useful.
