# Reproduction: stellar/js-stellar-sdk#1766

Sighting: "fix: order asset issuers and ScVal map keys the way the network does" (PR, merged
1 October 2026). Before it, the JavaScript SDK compared two assets' issuers as `G...` text and
sorted ScVal map keys by their native string forms. The network orders issuers by key bytes and
map keys by ScVal type, then value. The fix commit (`c103c9b3`) is not in tag v17.2.0 and is in
v17.2.1, the first release with it.

Two corpus entries, both real testnet ledgers. Run on 15 November 2026.

## The two halves

**Asset issuers.** `testnet-5708889`, transaction 9, operation 5: a `ChangeTrust` to a
liquidity-pool share whose two assets (`LPO`) have issuers that sort one way as bytes and the
other way as text:

| | Issuer | Key bytes start |
|---|---|---|
| assetA | `GAVUNFI2Z3HWJRIFJ4VVUVZOY4SBV6QPWG6PQO4SYPWKAXPFF467RMZY` | `2b46…` |
| assetB | `GA3WRUVVM6SEAX74PYYCS6W3EPAPXJIPLEMANI27WSIFZ3U6CRI5RPSN` | `3768…` |

By bytes A < B, the network's order. As text B < A, because base32 puts `3` before `V`. The
network accepted the operation, and the ledger records the pool ID
`3923cd1db642f1dd75797dd3fb79112ab5704767d7dc084ced8cf2938f186daf`. That is also SHA-256 of the
pair's XDR `LiquidityPoolParameters`, computed with this repository's own encoder, so the
expected value does not depend on any SDK.

Check `pool_pair_accepted`: `new LiquidityPoolAsset(assetA, assetB, fee)` must accept the pair in
the network's order, and `getLiquidityPoolId()` must give the ledger's pool ID.

**Map keys.** `testnet-5712621`, transaction 15's return value: a map the Soroban host wrote, with
keys u32 `1` and i64 `1`, in host order (u32 before i64, by type).

Check `map_keys_host_order`: `scvSortedMap()`, given the entries in reverse, must reproduce the
host's exact bytes. Both keys render as `"1"`, so an SDK that sorts by native string form leaves
them reversed.

## What was run

`tools/corpus_check.py` extracts the value at each path with the independent decoder and hands its
XDR to `harness/sdk-semantic/order.mjs` (and `order.py` for the pool half), so releases that cannot
decode a whole protocol 30 ledger are still tested on this behaviour. CI runs it on 16.4.1, 17.2.0
and 17.2.1 on every push; the table below covers every pinned release.

```bash
(cd harness/sdk-semantic && npm install)
python3 tools/corpus_check.py --sdk-checks --quiet
```

## Result

| SDK | Asset issuers | Map keys |
|---|---|---|
| @stellar/stellar-sdk 16.3.0 | **mishandled**: "Assets are not in lexicographic order" | **mishandled**: keys come out [i64, u32] |
| @stellar/stellar-sdk 16.4.1 | pass | **mishandled**: keys come out [i64, u32] |
| @stellar/stellar-sdk 17.2.0 | **mishandled**: "Assets are not in lexicographic order" | **mishandled**: keys come out [i64, u32] |
| @stellar/stellar-sdk 17.2.1, 17.3.0, 17.4.0 | pass (pool ID matches the ledger) | pass (host bytes reproduced) |
| stellar-sdk (Python) 17.0.1 | pass (pool ID matches the ledger) | not applicable: it does not sort map entries |

Raw output for the releases on either side of the fix, and for 16.4.1:

```
{"sdk":"@stellar/stellar-sdk 16.3.0","check":"pool_pair_accepted","result":"mishandled","detail":"rejected an asset pair the network accepted: Assets are not in lexicographic order"}
{"sdk":"@stellar/stellar-sdk 17.2.0","check":"pool_pair_accepted","result":"mishandled","detail":"rejected an asset pair the network accepted: Assets are not in lexicographic order"}
{"sdk":"@stellar/stellar-sdk 17.2.1","check":"pool_pair_accepted","pool_id":"3923cd1db642f1dd75797dd3fb79112ab5704767d7dc084ced8cf2938f186daf","result":"pass"}
{"sdk":"@stellar/stellar-sdk 16.3.0","check":"map_keys_host_order","result":"mishandled","detail":"scvSortedMap gives keys in the order [scvI64, scvU32]; the host wrote [scvU32, scvI64]"}
{"sdk":"@stellar/stellar-sdk 16.4.1","check":"map_keys_host_order","result":"mishandled","detail":"scvSortedMap gives keys in the order [scvI64, scvU32]; the host wrote [scvU32, scvI64]"}
{"sdk":"@stellar/stellar-sdk 17.2.1","check":"map_keys_host_order","result":"pass"}
{"sdk": "stellar-sdk 17.0.1", "check": "pool_pair_accepted", "pool_id": "3923cd1db642f1dd75797dd3fb79112ab5704767d7dc084ced8cf2938f186daf", "result": "pass"}
```

## The v16 line

16.4.1 passes the issuer half because PR #1768 backported the issuer byte order to v16 (as
16.3.1), but not the map half: in 16.4.1's `Asset.compare` the issuers are compared with
`Buffer.compare` on the decoded keys, while its `scvSortedMap` still sorts by native form. 16.4.1 is
the current v16 release (22 October 2026). js-stellar-sdk#1907, opened on 15 November by another
reporter, lists this map-key gap among six fixes that 17.x has and 16.x lacks. This run confirms
that report; it did not find it first.
