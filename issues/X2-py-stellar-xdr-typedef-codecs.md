# Draft, not filed: lightsail-network/py-stellar-xdr

**Title:** No standalone codec for SponsorshipDescriptor and the bare integer types

Following StellarCN/py-stellar-base#1264's invitation for API feedback before 1.0.

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
