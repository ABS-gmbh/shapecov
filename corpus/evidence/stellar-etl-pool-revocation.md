# Evidence: effects for a revocation that redeems pool shares in two pools

Found by the oracle through the replay harness's stellar-etl adapter on 15 November 2026, at
stellar-etl `master` `2b24ec89`. Not filed upstream yet; draft texts in
`issues/E2-stellar-etl-multi-pool-revocation.md` and `issues/E3-stellar-etl-revoked-pool-trustlines.md`.

## The ledger

`localcore-pool-revoke-two-pools-7`, a real ledger from stellar-core 30.0.0 on the testnet passphrase
(`tools/localcore.py`, scenario `pools-sponsorship-p30`). An issuer with `AUTH_REVOCABLE` issues AAA,
BBB and CCC. A trustor holds the only shares of two pools that share AAA: AAA/BBB
(`ca2932b7…`) and AAA/CCC (`aaef7e29…`). In this ledger the issuer's one `SetTrustLineFlags` clears
AAA's `AUTHORIZED` flag on the trustor. Per CAP-38, core then redeems the trustor's shares in every
pool that holds AAA, in that one operation. The meta records:

| Change | Count |
|---|---|
| liquidity pool removed (`ca2932b7…`, `aaef7e29…`) | 2 |
| pool-share trustline removed (one per pool) | 2 |
| claimable balance created for the trustor, sponsored (AAA and BBB from one pool, AAA and CCC from the other) | 4 |
| AAA trustline `AUTHORIZED` cleared | 1 |

## What stellar-etl's `export_effects` writes

```
 0 trustline_flags_updated               (issuer)
 1-8 claimable_balance_created / claimant_created, for all 4 balances
 9 liquidity_pool_revoked                pool aaef7e29… only; reserves_revoked: AAA and CCC
10-13 claimable_balance_sponsorship_created, for all 4 balances
14 liquidity_pool_removed                aaef7e29…
15 liquidity_pool_removed                ca2932b7…
```

The raw rows are in
`harness/replay/out-stellar-etl/2b24ec89ddce/datalake/localcore-pool-revoke-two-pools-7/exports/effects/`.

**E2.** Pool `ca2932b7…` (AAA/BBB) was revoked in the same operation and gets no
`liquidity_pool_revoked`. Its two claimable balances (AAA and BBB) appear in no `reserves_revoked`
list, so its revoked shares and reserves are nowhere in the effects. One of those balances, the
BBB one, is claimed by the trustor in the next corpus ledger (`localcore-claim-and-sponsor-8`).

The one `liquidity_pool_revoked` it does write names the wrong balance. Its `reserves_revoked`
gives AAA/CCC's AAA as claimable balance `00000000e4bbf033…`. A revocation's balance ID is
SHA-256 of `HashIDPreimage` `ENVELOPE_TYPE_POOL_REVOKE_OP_ID` (source, sequence number, operation
number, pool ID, asset), and computing it for this operation (issuer, sequence `(3 << 32) + 3`,
operation 0) gives:

| Pool | Its AAA claimable balance |
|---|---|
| AAA/BBB `ca2932b7…` | `00000000e4bbf033f497…` |
| AAA/CCC `aaef7e29…` | `000000008827dfb22d87…` |

So the AAA/CCC effect points at AAA/BBB's balance.

Cause: `addLiquidityPoolRevokedEffect` (`internal/transform/effects.go:1154`) calls
`getLiquidityPoolAndProductDelta(nil)`, which returns the first liquidity pool change of the
operation and stops. It then maps the new claimable balances by asset alone (`assetToCBID`), so
with two pools that share AAA one AAA balance overwrites the other, and the surviving one need not
be this pool's.

**E3.** Neither pool-share trustline the revocation removed gets a `trustline_removed` effect. In
stellar-etl only `addChangeTrustEffects` emits `EffectTrustlineRemoved` (`effects.go:673`). This is
the effects-model counterpart of stellar/wallet-backend#817 (no `TRUSTLINE REMOVE` state change for
the same shape).

## wallet-backend

The same ledger through wallet-backend `main` (`3e22515a`), both inputs: the two pool-share
trustlines the revocation removed get no `TRUSTLINE REMOVE` state change, which is
stellar/wallet-backend#817 (filed by the shapekit project), confirmed here on a ledger of our own.

## Horizon

Not run here. stellar-horizon `main` (`c16ac6b5`, 10 November 2026) has the same code:
`internal/ingest/processors/effects_processor.go:1367` calls `getLiquidityPoolAndProductDelta(nil)`
in `addLiquidityPoolRevokedEffect`, and `EffectTrustlineRemoved` is emitted only from
`addChangeTrustEffects` (line 807).

## Reproduce

```sh
harness/replay/run.sh etl      # or: replay.py run --adapter stellar-etl --entries localcore-pool-revoke-two-pools-7 ...
python3 tools/oracle.py localcore-pool-revoke-two-pools-7
```

## Searched before writing this

stellar/stellar-etl, stellar/stellar-horizon and stellar/go-stellar-sdk issues, 15 November 2026.
The nearest is stellar-etl #458, which is about the order of the claimable balance effects a
revocation emits, not about pools or trustlines that get no effect.
