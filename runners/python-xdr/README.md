# stellar-xdr and stellar-strkey (Python)

py-stellar-base's next major release replaces `stellar_sdk.xdr` and `stellar_sdk.strkey` with two
standalone packages from lightsail-network: `stellar-xdr` and `stellar-strkey`. Its maintainer
asks that XDR and strkey problems be tried against them, and welcomes API feedback before 1.0
(StellarCN/py-stellar-base#1264). This runner points the generator and the corpus at them.

Pinned in `requirements.txt`: stellar-xdr 0.2.1, stellar-strkey 0.2.0. Run on 16 November 2026.

| File | What it does |
|---|---|
| `run.py` | The runner, in the same tab-separated protocol as the other SDK runners: XDR round trip, or `tojson` / `fromjson` for SEP-51 XDR-JSON. `tools/run.py` and `tools/corpus_check.py` know it as `python-xdr`. |
| `ref-json/` | rs-stellar-xdr 30.0.0 with its serde JSON, the reference for the JSON check. `cargo build --release`. |
| `json_check.py` | SEP-51 differential check against `ref-json`. |
| `strkey_check.py` | stellar-strkey against SEP-23's own test vectors and generated mutations. |

```sh
python3 -m venv runners/python-xdr/.venv && runners/python-xdr/.venv/bin/pip install -r runners/python-xdr/requirements.txt
python3 tools/run.py out/cases.jsonl python-xdr && python3 tools/diff.py out/cases.jsonl
python3 tools/corpus_check.py --sdks rust,python-xdr
python3 runners/python-xdr/json_check.py out runners/python-xdr/.venv/bin/python
runners/python-xdr/.venv/bin/python runners/python-xdr/strkey_check.py sep-0023.md
```

## Results

**XDR.** All 7,392 generated cases (`out/REPORT.md`, column `python-xdr`): every valid value
decodes and re-encodes byte for byte, and every injected fault is rejected. The only differences
from the Rust reference are the 26 `bool` values of 2, which stellar-xdr rejects and rs-stellar-xdr
accepts (rs-stellar-xdr #622). The faults that stellar-sdk 17.0.1 accepts, non-zero padding
(160 cases, our P1) and optional flags other than 0 or 1 (145 cases, P2), are all rejected. All 67
corpus entries, including the 64 real ledgers, round-trip identically.

**SEP-51 JSON.** On the 3,808 valid cases: stellar-xdr reads its own JSON back to the original bytes
every time, and it reads rs-stellar-xdr's JSON and vice versa, except for 120 cases in 15 overlay
types (`Hello`, `AuthCert`, `PeerAddress`, `Curve25519Secret`, …). There stellar-xdr writes inline
fixed-length opaque fields as hex strings, as SEP-51 2.0.1 requires ("represented as a hexadecimal
string"), and rs-stellar-xdr 30.0.0 writes integer arrays. That is rs-stellar-xdr #618, open, with
a fix in #619; stellar-xdr is the conforming side.

**Strkeys.** 172 cases: all 36 valid and invalid vectors in SEP-23 1.4.0 (including the CAP-84 muxed
contract `W...` vectors), and for each of the ten strkey types a valid key plus mutations: payload
a byte short or long, algorithm values 1 to 7, non-zero unused bits under a correct checksum, lower
case, `=` padding, signed payloads whose length field disagrees with the payload or whose padding
is not zero, claimable balances with a type byte other than 0. stellar-strkey 0.2.0 agrees on all
172 and re-encodes every valid key to the same string. The same cases against stellar-sdk
17.0.1's `StrKey` find 8 differences (it accepts `=` padding on M, P and B keys and a signed
payload with non-zero padding, and has no `W` type), so the check does detect a wrong library.

**API feedback, not defects:**

- **Decode depth follows Python's remaining recursion budget.** A depth error is clean
  (`XdrDepthError`), but where it starts depends on the caller's stack, not on the data. A
  `TransactionEnvelope` whose contract argument is nested 240 levels, inside what stellar-core's
  decoder accepts (rs-stellar-xdr depth 1000 rejects from 250 levels), decodes only when the caller
  is at most 501 frames deep; a 100-level argument, the most the Soroban host writes, at most 781
  frames (default recursion limit 1000). rs-stellar-xdr takes the limit as an argument (`Limits`).
  Fact sheet (design question): `issues/X1-py-stellar-xdr-depth.md`; posted as a
  [comment on StellarCN/py-stellar-base#1264](https://github.com/StellarCN/py-stellar-base/issues/1264#issuecomment-6930257881).
  Answered the next morning: the guide now explains the limit and how to raise it
  ([py-stellar-xdr#24](https://github.com/lightsail-network/py-stellar-xdr/pull/24), merged); the library leaves the recursion limit to the caller.
- **No codec for `SponsorshipDescriptor` and the bare integer types.** `SponsorshipDescriptor`
  (`typedef AccountID* SponsorshipDescriptor`) is a type alias without `from_xdr_base64`, and
  `uint32`, `int32`, `uint64`, `int64` have no class. stellar-sdk 17.0.1, rs-stellar-xdr, Go and
  Java decode all five on their own. Fact sheet (API question): `issues/X2-py-stellar-xdr-typedef-codecs.md`; posted in the same comment.
  Answered in the same change ([py-stellar-xdr#24](https://github.com/lightsail-network/py-stellar-xdr/pull/24)): a deliberate choice the maintainer keeps for
  now, now stated in the guide with how to read an integer with `struct.unpack`.
