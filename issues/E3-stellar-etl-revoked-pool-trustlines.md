# Draft, not filed: stellar/stellar-etl

**Title:** Pool-share trustlines removed by an authorization revocation get no trustline_removed effect

### What

Clearing a trustline's authorization with `SetTrustLineFlags` or `AllowTrust` makes stellar-core
redeem the trustor's pool shares in every pool holding that asset and remove those pool-share
trustlines (CAP-38). `export_effects` writes no `trustline_removed` for them. Only
`addChangeTrustEffects` emits `EffectTrustlineRemoved`, so a consumer tracking an account's
trustlines from effects keeps two trustlines the ledger no longer has.

### Reproduce

The same ledger as the multi-pool revocation report: one `SetTrustLineFlags` removes two pool-share
trustlines; stellar-etl `master` `2b24ec89` writes `liquidity_pool_removed` for both pools and no
`trustline_removed`.
https://github.com/ABS-gmbh/shapecov/blob/main/corpus/evidence/stellar-etl-pool-revocation.md

### Context

stellar-horizon's effects processor behaves the same way. wallet-backend has the matching gap in
its state changes (stellar/wallet-backend#817).
