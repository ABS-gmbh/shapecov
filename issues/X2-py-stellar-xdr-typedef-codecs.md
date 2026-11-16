# Fact sheet: lightsail-network/py-stellar-xdr

Notes for an upstream report, not posted as is. This sheet records what was run and what it showed.

**Kind: API completeness question, not a defect.** Every value that has a codec round-trips
correctly; five schema types have no standalone codec. A fit for a comment on StellarCN/py-stellar-base#1264
(which invites API feedback before 1.0) rather than a new issue.

**Suggested subject:** No standalone codec for SponsorshipDescriptor and the bare integer types

### What

Every other type in the Protocol 30 XDR has a class with `from_xdr_base64` / `to_xdr_base64`.
Five do not:

- `SponsorshipDescriptor` (`typedef AccountID* SponsorshipDescriptor;`) is a type alias,
  `PublicKey.Ed25519 | None`, so it cannot be decoded or encoded on its own.
- `uint32`, `int32`, `uint64`, `int64` have no class.

`stellar_sdk.xdr` (17.0.1) has all five, as do rs-stellar-xdr, go-stellar-sdk and the Java SDK, so
code that decodes, for example, a bare `SponsorshipDescriptor` or `Uint64` loses that on migration.

Found by running a schema-generated corpus of 7,392 cases through stellar-xdr 0.2.1; everything
else round-trips identically to rs-stellar-xdr.
