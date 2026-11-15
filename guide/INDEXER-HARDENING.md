# Indexer-hardening guide

**Status: draft for review.** Publication is gated on review by a stellar-core or platform
engineer. Written against protocol 30 and stellar-core 30.0.0.

This guide is for people who write software that reads the Stellar ledger: indexers, explorers,
wallets' history services, analytics pipelines. It covers the shapes of valid ledger data that
have broken such software before, and what to do about each:

1. [What stellar-core validates, field by field](#1-what-stellar-core-validates-field-by-field)
2. [Depth and size caps](#2-depth-and-size-caps)
3. [Participants come from the meta, not the envelope](#3-participants-come-from-the-meta-not-the-envelope)
4. [Muxed and signed-payload addresses](#4-muxed-and-signed-payload-addresses)
5. [Checklist](#5-checklist)

Every shape named here has a **corpus pattern** (for example `memo-text-not-utf8`), defined in
[`corpus/patterns.json`](../corpus/patterns.json). Where the corpus has real ledgers that contain
the shape, the tables give the count, so you can replay them through your own pipeline with the
[replay harness](../harness/replay/README.md). [`check_guide.py`](check_guide.py) keeps the
tables in step with the corpus manifest (see [Appendix](#appendix-how-this-guide-is-checked)).

The one rule behind everything below: **valid is not the same as well-formed for your
database.** stellar-core accepts a transaction if it follows the protocol. The protocol allows
memo text that is not UTF-8, 64-bit IDs that no float can hold, signer keys 100 bytes long, and
contract values nested deeper than most recursive code expects. The corpus holds ledgers with all
of these: network ledgers for most, and a ledger closed by a local stellar-core 30.0.0 for the
memo text (`localcore-memo-and-offer-p30-4`). In that ledger the memo's bytes also appear,
unchanged, in the payment's transfer event.

## 1. What stellar-core validates, field by field

stellar-core decodes every transaction strictly: lengths must not exceed their XDR maximum and
padding must be zero. Beyond that, it checks only what the protocol needs. **We found no UTF-8
check on any string field, in stellar-core or in the Soroban host.** Two fields are stricter and
are limited to printable ASCII: the `ManageData` name and the home domain.

"Checked" below means the transaction is rejected, or the operation fails, if the check fails.
Bracketed numbers point to the [sources](#sources) at the end of this section.

### Classic transactions

| Field | Checked | Not checked | Corpus shape | CAP | Entries |
|---|---|---|---|---|---|
| Memo text | At most 28 bytes (XDR). From protocol 25, a contract-invocation transaction may not carry a memo. [1] | The bytes: no UTF-8, NUL or printable check. For a payment to a plain account, the bytes are also copied as an `SCV_STRING` into the `to_muxed_id` field of the transfer event. [2] | `memo-text-not-utf8` | none | 1 |
| Memo ID, hash, return | XDR shape only. | Any value. | — | — | — |
| Muxed account (source, destination, fee source) | Allowed from protocol 13. [3] | The 64-bit ID: any value, never checked. Ledger state belongs to the base account; the ID survives only in the envelope and in events. [3] | `muxed-account`, `muxed-id-zero`, `muxed-id-beyond-f64`, `muxed-id-max` | CAP-0027 | 4, 2, 3, 1 |
| Muxed source of a contract invocation | Invalid from protocol 25 (`txSOROBAN_INVALID`). [1] Before that, only the transaction queue refuses it: from stellar-core 23.0.0 always, in 22.x only when the call carries non-source-account authorization. [18] | Consensus accepts it before protocol 25, so ledgers closed while validators ran stellar-core 22.x or older can contain it. | `soroban-op-muxed-source` | CAP-0027, CAP-0046 | 1 |
| Signed-payload signer (`SetOptions` signer, `extraSigners`) | Payload not empty, at most 64 bytes, from protocol 19. At most two `extraSigners`, not the same key twice. [4] | The payload's content. | `signed-payload-signer`, `signed-payload-max-length`, `signed-payload-needs-padding` | CAP-0040 | 3, 1, 1 |
| `ManageData` name | 1 to 64 bytes, each printable ASCII (0x20 to 0x7E). [5] | — | — | — | — |
| `ManageData` value | At most 64 bytes (XDR). | Any bytes. [5] | — | — | — |
| Home domain | At most 32 bytes, each printable ASCII (0x20 to 0x7E). [5] | Domain syntax; an empty string is accepted. | — | — | — |
| Asset code | Letters and digits only, with NUL allowed only as trailing padding. 1 to 4 characters (`AlphaNum4`) or 5 to 12 (`AlphaNum12`). [6] | Whether the issuer exists. | — | — | — |
| Liquidity-pool asset pair | `assetA < assetB`, compared as XDR values: asset type, then code bytes, then issuer key bytes. [7] | It is **not** strkey text order. | `pool-issuers-order-differs-strkey-vs-bytes` | CAP-0038 | 1 |
| Claim predicates and claimants | At most 4 levels; `AND`/`OR` have exactly two children; times are not negative; 1 to 10 claimants, no repeated destination. [8] | Whether claimant accounts exist. | — | — | — |
| Path payment path | At most 5 hops (XDR), each a valid asset. [8] | Repeated hops. | — | — | — |
| Operations per transaction | 1 to 100 (the maximum is the XDR limit). [9] | — | `operations-at-max-100`, `operations-50-or-more` | none | 6, 5 |
| Signatures per envelope | At most 20 (XDR). [9] | — | `signatures-at-max-20` | none | 2 |
| Offer ID | Not negative, from protocol 15. [10] | No upper bound: any value up to 2^63-1. | `offer-id-beyond-f64` | none | 1 |
| Destination and operation-source accounts | Checked when the transaction is applied, not when it is accepted. [9] | A transaction that fails then is still in the ledger, with its fee charged. [11] | `failed-transaction` | none | 31 |

### Contract data (Soroban)

| Field | Checked | Not checked | Corpus shape | CAP | Entries |
|---|---|---|---|---|---|
| Nesting of contract values (`ScVal`) | Every value the host reads from arguments or writes to storage, events or return values: at most 100 levels. Host XDR reads and writes: depth 500. Whole envelope from protocol 28: depth 1000. [12] | Arguments of a transaction that fails before the host converts them are bounded only by the envelope limit. Ledgers before protocol 28 had different limits. | `scval-nested-5-deep` | CAP-0046-01 | 16 |
| Contract strings (`ScString`) | Length only. [13] | UTF-8 and NUL, in arguments, storage and events alike. | — | — | — |
| Symbols (`ScSymbol`) | At most 32 bytes from `[_0-9A-Za-z]`, for every value the host converts. [13] | — | — | — | — |
| Maps (`ScMap`) | Keys strictly ascending, so sorted and unique, in the host's order: by value type first, then value. Mixed key types are allowed. [14] | Text order. Keys are not sorted as text, and distinct keys can render as the same text. | `scmap-keys-collide-as-text`, `scmap-mixed-key-types` | CAP-0046-01 | 1, 2 |
| Integers | XDR shape. | Size relative to your language: 64-bit values above 2^53 and 128- or 256-bit values are common. | `scval-int64-beyond-f64`, `scval-wide-integer` | CAP-0046-01 | 8, 27 |
| Authorization entries | Every entry is decoded. An entry a `require_auth` call matches has its signature checked and its nonce consumed, which creates a temporary contract-data entry keyed `LedgerKeyNonce`. [15] | Entries no `require_auth` call matches: they are not verified, and we found no code that rejects them. There is no limit on the number or depth of sub-invocations beyond XDR depth and transaction size. [15] | `auth-nested-invocations`, `auth-tree-4-deep` | CAP-0046-11 | 21, 3 |
| Addresses in contract values | A muxed account (CAP-67) or a muxed contract (protocol 30) may appear as a value but not in a storage key. [16] | — | `scaddress-muxed-account`, `scaddress-muxed-id-beyond-f64`, `scaddress-muxed-contract` | CAP-0067, CAP-0084 | 3, 2, 2 |
| Accounts and trustlines created by a contract | The Stellar Asset Contract's `trust()` creates a trustline and **emits no event**. [17] | No operation names the new entry; only the ledger changes show it. | `soroban-created-trustline`, `soroban-created-account` | CAP-0073 | 3, 3 |
| Failed contract invocation | The fee is charged; no ledger change is applied; transaction-level events and diagnostics are still written. [11] | — | `failed-soroban-transaction` | CAP-0046 | 8 |

### Sources

stellar-core tag `v30.0.0` (commit `0e49751aa9dd`) and rs-soroban-env `6e6c4a87f46c`, the
host stellar-core 30.0.0 builds. Paths are relative to those repositories.

1. `src/transactions/TransactionFrame.cpp` 341-370 (`validateSorobanMemo`), applied from protocol 25 at 1314-1325.
2. `src/transactions/EventManager.cpp` 112-136; `src/transactions/TransactionUtils.cpp` 2253-2266 (`makeClassicMemoSCVal`).
3. `src/transactions/TransactionFrame.cpp` 1256-1260 (before protocol 13: `txNOT_SUPPORTED`); `src/transactions/TransactionUtils.cpp` 1188-1196 (`toAccountID` keeps only the key).
4. `src/transactions/SetOptionsOpFrame.cpp` 306-316; `src/transactions/TransactionFrame.cpp` 1276-1293.
5. `src/transactions/ManageDataOpFrame.cpp` 114-115; `src/transactions/SetOptionsOpFrame.cpp` 318-325; `src/util/types.h` 197-201 (`isAsciiNonControl`); `src/util/types.cpp` 106-116 (`isStringValid`).
6. `src/util/types.cpp` 149-214 (`isAssetValid`).
7. `src/util/types.cpp` 140-143; the comparison is xdrpp's generated ordering of the XDR types.
8. `src/transactions/CreateClaimableBalanceOpFrame.cpp` 74-120, 270-281; path payment `doCheckValid` in `PathPaymentStrictReceiveOpFrame.cpp` 170-177 and `PathPaymentStrictSendOpFrame.cpp` 163-170.
9. XDR `operations<100>` and `signatures<20>` in `Stellar-transaction.x`; `src/transactions/PaymentOpFrame.cpp` 106, 139-151; `src/transactions/OperationFrame.cpp` 241-250.
10. `src/transactions/ManageOfferOpFrameBase.cpp` 621-640.
11. `src/ledger/LedgerManagerImpl.cpp` 2502-2503 (fees), 2862-2866 (every transaction gets a result and meta); `src/transactions/TransactionFrame.cpp` 2426-2430; `src/transactions/TransactionMeta.cpp` 1051.
12. rs-soroban-env `soroban-env-host/src/budget/limits.rs` 12-14 (`depth: 500`), 41 (`DEFAULT_HOST_DEPTH_LIMIT = 100`); `host/conversion.rs` 409-437; stellar-core `src/transactions/TransactionUtils.cpp` 1348-1372 (envelope depth 1000 from protocol 28).
13. rs-stellar-xdr `v30.0.0` `src/generated.rs` 2075-2076, 2477-2501 (`StringM` holds arbitrary bytes); rs-soroban-env `soroban-env-common/src/symbol.rs` 236-245.
14. rs-soroban-env `soroban-env-host/src/host/metered_map.rs` 124-136; `host.rs` 1228-1241.
15. rs-soroban-env `soroban-env-host/src/auth.rs` 945-957 (all entries decoded), 2478-2520 (authenticate and consume the nonce only after a match), 2958-3013 (`consume_nonce`).
16. rs-soroban-env `soroban-env-host/src/host/conversion.rs` 523-531, 629-634.
17. rs-soroban-env `soroban-env-host/src/builtin_contracts/stellar_asset_contract/balance.rs` 951-1086, `contract.rs` 403-412.
18. `src/herder/TransactionQueue.cpp` 498-506 (30.0.0: refused before protocol 25). The same file at tag `v22.0.0` (`validateSorobanMemo`, which returns early when every authorization entry uses source-account credentials) and at `v23.0.0` (no such early return); no check at `v21.0.0`. A local stellar-core 30.0.0 and 29.0.0 at protocol 24 both refused the transaction with this check's message (`tools/localcore.py`).

## 2. Depth and size caps

Recursive structures in the ledger are bounded by the network, but not always by numbers your code
can rely on without thought. Use these bounds to pick caps that never reject valid data:

| Structure | Bound the network enforces | Recommended cap |
|---|---|---|
| Contract values in storage, events and return values | At most 100 levels: the host refuses to convert anything deeper [12] | Walk with a depth counter and stop at 100. *(Inference: every such value passed through the host's conversion, so a cap of 100 should never reject one.)* |
| Contract values in transaction arguments | Only the envelope's XDR depth of 1000 (from protocol 28) when the transaction failed before the host read them [12] | Walk with a depth counter. Past your cap, truncate and record that you did; do not reject the ledger. |
| Soroban authorization trees | No limit of their own; only XDR depth and transaction size [15] | Iterate with an explicit stack and a depth counter, truncating as above. |
| Whole envelopes and `LedgerCloseMeta` | stellar-core parses envelopes with rs-stellar-xdr at depth 1000 (from protocol 28) | Set your decoder's depth limit explicitly. Rust's `Limits::none()` is unbounded; Go's default is 1500. Depth is counted per XDR type, not per contract-value level, and libraries count differently, so test your limit on the corpus's deepest entries. |
| Claim predicates | 4 levels [8] | 4 is safe. |
| Path payment path, operations, signatures, `extraSigners`, claimants | 5, 100, 20, 2, 10 (XDR) | The XDR maxima are exact. Size buffers to them, and test at the maximum (`operations-at-max-100`, `signatures-at-max-20`). |
| Event bytes per transaction, contract data entry size, key size, transaction size | Network configuration settings (`ConfigSettingContractEventsV0`, `CONTRACT_DATA_ENTRY_SIZE_BYTES`, `CONTRACT_DATA_KEY_SIZE_BYTES`, `ConfigSettingContractBandwidthV0.txMaxSizeBytes`), changed by network upgrades | Read them from the ledger's `ConfigSetting` entries; do not hard-code them. |
| Number of contract events per transaction | No limit found other than the total event bytes | Do not assume a small count. |

A cap protects your process. When one is hit, the safe response is to store what you have, flag
the record and keep ingesting. Rejecting the ledger stops your indexer on valid data. That is how
stellar/wallet-backend#729 stopped ingestion: one valid signer it could not store stopped every
later ledger.

## 3. Participants come from the meta, not the envelope

A transaction's **envelope** records what its submitter asked for. Its **meta** records what
stellar-core actually did. The two differ in ways that matter to anyone answering "which accounts
did this transaction affect?":

- **Failed transactions are in the ledger.** The fee is charged and the envelope is stored, but
  no operation took effect. A payment's destination in a failed transaction received nothing.
  (Corpus: `failed-transaction`, `failed-soroban-transaction`.)
- **Contract calls change accounts that no operation names.** A Stellar Asset Contract call can
  create a trustline or an account with no `ChangeTrust` or `CreateAccount` operation (CAP-73).
  Only the meta shows it. Before its fix (#734), stellar/wallet-backend recorded no trustline
  history for such a trustline (#731; reproduced by the replay harness with
  `localcore-sac-trust-p28-5`). (Corpus: `soroban-created-trustline`, `soroban-created-account`.)
- **The Soroban authorization tree is a claim.** The host checks the signature and consumes the
  nonce only for entries a `require_auth` call matched. We found no code that rejects the rest
  (section 1, [15]). An address in an authorization entry proves nothing on its own. A consumed
  nonce in the ledger changes (a temporary contract-data entry keyed `LedgerKeyNonce`) shows the
  entry was used. (Corpus: `auth-nested-invocations`, `auth-tree-4-deep`.)

So derive participants from:

| Source | Gives you | When |
|---|---|---|
| The transaction source and fee source | the accounts that signed and paid | always, even for a failed transaction: stellar-core checks their signatures and charges the fee |
| `LedgerEntryChanges` in the transaction and operation meta | every account, trustline, offer, data entry, claimable balance and contract data entry that was created, updated or removed | successful transactions; fee changes for all |
| Contract events in the meta | token movements (`transfer`, `mint`, `burn`, `clawback`) and their addresses | successful transactions |
| Authorization entries | address-credential entries whose nonce entry the meta shows being created; source-account entries are the transaction source, already counted | successful transactions |

**What goes wrong otherwise.** stellar/wallet-backend took Soroban participants from the declared
authorization tree until commit `9538b3ca` ("derive Soroban participants from executed meta, not
the auth tree"). It still records envelope-derived operation participants for failed
transactions (introduced by #474). In a failed transaction, that lets any submitter put any
account into another account's history at the cost of one fee. The [linter](../linter/README.md)
rule **SC003** reports this pattern in Go code.

## 4. Muxed and signed-payload addresses

### The strkey forms (SEP-23)

A strkey is a version byte, a payload, and a two-byte CRC16-XModem checksum (little-endian),
encoded as unpadded base32. The payload length depends on the version byte:

| Prefix | Kind | Version byte | Payload |
|---|---|---|---|
| `G` | account | `6 << 3` | 32-byte ed25519 key |
| `M` | muxed account | `12 << 3` | 32-byte ed25519 key, then 8-byte ID (big-endian) |
| `P` | signed payload | `15 << 3` | 32-byte ed25519 key, 4-byte payload length (big-endian), payload of 1 to 64 bytes, zero padding to a multiple of 4: **40 to 100 bytes** |
| `C` | contract | `2 << 3` | 32-byte contract ID |
| `T` | pre-authorized transaction | `19 << 3` | 32-byte hash |
| `X` | hash(x) | `23 << 3` | 32-byte hash |
| `L` | liquidity pool | `11 << 3` | 32-byte pool ID |
| `B` | claimable balance | `1 << 3` | 1 type byte, then 32-byte balance ID |

Two traps in that table:

- **A muxed account's byte order differs between XDR and strkey.** In XDR,
  `MuxedAccount.med25519` is `{ uint64 id; uint256 ed25519; }`, ID first. In an `M...` strkey,
  the key comes first and the ID last. Code that copies XDR bytes into a strkey payload produces
  a valid-looking address for the wrong account.
- **Not every address is 32 bytes.** `M` is 40 and `P` is 40 to 100. A column, buffer or type
  that holds "version byte + 32 bytes" silently truncates the rest.

### What happened in wallet-backend

The [replay harness](../harness/replay/RESULTS.md) reproduces both of these from one real testnet
ledger (`testnet-4437357-signed-payload-signer`, a `SetOptions` that adds a `P...` signer):

| wallet-backend commit | What the indexer did with the `P...` signer |
|---|---|
| `79ea2acd` | Stored 33 of its 41 bytes with no error. The stored value reads back as `PBCK2RYY…NSBYVM`, which is not a valid address (stellar/wallet-backend#716). |
| `6e5a5910`, `2a0a84ea` | A length guard turned that into an insert error. The ledger never committed, the cursor never advanced, and ingestion stopped (stellar/wallet-backend#729). |
| `2c873353` and later | Stores the full key in a variable-length column. |

The same loss happened for muxed addresses: storing an `M...` as "version byte + 32 bytes" drops
the ID, and the stored value no longer decodes.

### How to handle them

- **Store the full payload.** Keep the version byte and all payload bytes in a variable-length
  column, or store muxed accounts as two columns: the base `G...` account and the ID.
- **Decide what a muxed account means for each table.** Balances, signers and account state
  belong to the base account: reduce `M...` to `G...` (`MuxedAccount.ToAccountId()` in Go)
  there. Payment history, deposits and anything a customer ID routes should keep the ID. Never
  let one column hold both forms.
- **Hold 64-bit IDs as unsigned 64-bit integers or decimal strings.** Muxed IDs, memo IDs and
  offer IDs use the full `uint64` range. 2^64-1 overflows a signed `BIGINT`; anything above 2^53
  changes value in a JavaScript `number` or a `float64`. (Corpus: `muxed-id-max`,
  `muxed-id-beyond-f64`, `muxed-id-zero`, `scaddress-muxed-id-beyond-f64`, `offer-id-beyond-f64`.)
- **Treat ID 0 as an ID.** `M...` with ID 0 is a different address from the plain `G...`.
  Truthiness checks (`if id:`) treat it as absent.
- **Validate on read, not only on write.** When you read an address back from storage, check that
  its payload length matches its version byte. `harness/replay/strkeyx.py` has a reference check
  (`payload_problem`) written from SEP-23.
- **Expect muxed addresses inside contract data.** Since CAP-67, an `ScAddress` can hold a muxed
  account, and since protocol 30 a muxed contract address. Code that expects only `G...` and
  `C...` from contract values fails on them. (Corpus: `scaddress-muxed-account`,
  `scaddress-muxed-contract`.)

## 5. Checklist

Use this when you review an indexer, in any language. The **Linter** column names the
[shapecov-lint](../linter/README.md) rule that finds the mistake in Go code. **Replay** marks
items that the [replay harness](../harness/replay/README.md) can show against your running
indexer once the corpus has an entry with that shape and expectations for it.

| # | Check | Section | Linter | Replay |
|---|---|---|---|---|
| 1 | Memo text and contract strings are stored as bytes, or checked for UTF-8 and NUL before they reach a text column. | 1 | SC001 | yes |
| 2 | Muxed IDs, memo IDs and offer IDs are held as unsigned 64-bit integers or decimal strings, never as floats or signed 64-bit. | 4 | SC001 | yes |
| 3 | Addresses are stored with their full payload (40 bytes for `M`, up to 100 for `P`) and checked against their version byte when read back. | 4 | — | yes |
| 4 | Each table states whether it holds the base `G...` account or the muxed form, and never mixes them. | 4 | SC001 | yes |
| 5 | Every recursive walk over contract values or authorization trees has a depth counter and a cap, and truncates instead of failing. | 2 | SC002 | — |
| 6 | The XDR decoder's depth limit is set explicitly, not left at an unbounded or untested default. | 2 | — | — |
| 7 | Size limits come from the ledger's network configuration, not constants. | 2 | — | — |
| 8 | Participants come from the meta. A failed transaction contributes only its source and fee source. | 3 | SC003 | yes |
| 9 | Authorization entries count only when the meta shows their nonce consumed. | 1, 3 | SC001, SC003 | yes |
| 10 | Trustlines and accounts are tracked from ledger changes, so contract-created ones appear. | 3 | — | yes |
| 11 | Liquidity-pool asset pairs are ordered by XDR bytes, not by strkey text. | 1 | — | yes |
| 12 | Contract maps are not converted to text-keyed objects, which merges colliding keys and reorders mixed types. | 1 | — | yes |
| 13 | A value the indexer cannot store is flagged and skipped, and ingestion continues; one valid ledger never stops the indexer. | 2 | — | yes |
| 14 | Ledgers older than protocol 25 are handled: contract invocations there can have a muxed source and a memo. | 1 | — | yes |

## Appendix: how this guide is checked

[`check_guide.py`](check_guide.py) checks this guide against the corpus manifest. It is the RFP's
acceptance check for the guide ("the field-by-field table agrees with the corpus manifest"):

```sh
python3 guide/check_guide.py
```

It fails if:

- the guide names a corpus pattern or entry that does not exist;
- a corpus pattern is not mentioned anywhere in the guide;
- in a table with "Corpus shape", "CAP" and "Entries" columns, the CAP column differs from the
  pattern's CAPs in `corpus/patterns.json`, or the Entries column differs from the number of
  manifest entries that carry each pattern.

Every shape the guide describes has at least one corpus entry. Three come from a local
stellar-core, not from network history (`tools/localcore.py`):

- `soroban-op-muxed-source`: `localcore-muxed-source-p22-3`, closed by stellar-core 22.2.1 at
  protocol 22. A contract call whose operation runs as the transaction's muxed source succeeded
  there. Only validators on stellar-core 22.x or older could have closed such a ledger (section
  1, [18]), and those run protocol 22 at most, so expect it when backfilling protocols 20 to 22.
- `memo-text-not-utf8` and `offer-id-beyond-f64`: `localcore-memo-and-offer-p30-4`, closed by
  stellar-core 30.0.0 at protocol 30. Offer IDs come from a sequential counter, so a value above
  2^53 appears on the network only in the envelope of a failed transaction, as it does here.

All three passed the same checks as network entries: the independent decoder, all five SDK round
trips and stellar-core 30.0.0's own decoder.

The claims in section 1 were read from the source cited there. Where the guide says "we found
no code that…", the absence was established by reading and searching that code, not by a
statement in it. Those are the claims a reviewer should check first.
