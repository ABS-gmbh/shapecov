# Filed 16 November 2026: https://github.com/stellar/stellar-etl/issues/513

**Title:** A revocation that redeems pool shares in several pools gets one liquidity_pool_revoked effect, citing another pool's claimable balance

### What

When an issuer clears a trustline's authorization and the trustor holds shares in more than one
pool containing that asset, stellar-core redeems the shares of every such pool in the one
`SetTrustLineFlags` / `AllowTrust` operation (CAP-38). `export_effects` writes a single
`liquidity_pool_revoked`, for the first pool in the operation's changes. The other pools' revoked
shares and reserves, and the claimable balances created for them, appear in no revoked effect,
although each of those pools does get `liquidity_pool_removed` when emptied. The one effect that
is written can also name another pool's claimable balance in `reserves_revoked`.

### Reproduce

A real stellar-core 30.0.0 ledger on the testnet passphrase: the trustor holds the only shares of
AAA/BBB and AAA/CCC, and the issuer clears AAA's authorization. Core removes both pools, removes
both pool-share trustlines and creates four claimable balances in that operation. stellar-etl
`master` `2b24ec89` writes one `liquidity_pool_revoked`, for AAA/CCC; nothing for AAA/BBB. Its
`reserves_revoked` gives AAA/CCC's AAA balance as `00000000e4bbf033…`, which is AAA/BBB's: computed
from the `ENVELOPE_TYPE_POOL_REVOKE_OP_ID` preimage, AAA/BBB's AAA balance is `00000000e4bbf033…`
and AAA/CCC's is `000000008827dfb2…`.

Ledger, effects as exported, and the full list:
https://github.com/ABS-gmbh/shapecov/blob/main/corpus/evidence/stellar-etl-pool-revocation.md

### Why

`addLiquidityPoolRevokedEffect` (`internal/transform/effects.go`) calls
`getLiquidityPoolAndProductDelta(nil)`, which returns the first liquidity pool change and stops.
The new claimable balances are also keyed by asset alone (`assetToCBID`), so two pools that share
the revoked asset overwrite each other's entry in `reserves_revoked`.

stellar-horizon's `effects_processor.go` has the same code.

### Suggested fix

Emit one `liquidity_pool_revoked` per liquidity pool change in the operation, and match each
claimable balance to its pool rather than to its asset alone.
