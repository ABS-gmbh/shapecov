# Reproduction: stellar/js-stellar-sdk#1785

Sighting: "Muxed account IDs and offer IDs accept values that encode a different ID". Closed on
8 October 2026; the first release after that is @stellar/stellar-sdk 17.3.0 (21 October).

Corpus entry: `synthetic-ids-beyond-f64`, a TransactionEnvelope whose 64-bit identifiers sit at
the extremes: offer ID and source muxed ID 2^53+1, destination muxed ID and memo ID 2^64-1,
amount 2^63-1. Run on 15 November 2026.

## What was run

The manifest attaches the check `ids_exact` to the entry. It has two halves:

- **Decode:** every 64-bit identifier in the entry must decode to its exact decimal text.
- **Build:** the SDK's own builders must refuse inputs that would encode a different ID: an offer
  ID given as a JavaScript number above 2^53 (it has already lost precision), non-canonical
  strings (`"0x10"`, `" 16 "`), an empty string (an offer ID of 0 means "create a new offer"),
  a negative offer ID, and 2^64 (out of range). The same for muxed account IDs where they apply.

`harness/sdk-semantic/ids.mjs` runs it for js-stellar-sdk and `ids.py` for py-stellar-base.
Python's builders take integers, so its string-format cases are expected to be refused by type.
`tools/corpus_check.py --sdk-checks` runs both, and the `conformance` job in CI runs that on every
push.

```bash
(cd harness/sdk-semantic && npm install)
python3 tools/corpus_check.py --sdk-checks --quiet
```

## Result

Every SDK decodes all identifiers exactly. The difference is in what the builders accept.

| SDK | Result | Accepted inputs that encode a different ID |
|---|---|---|
| @stellar/stellar-sdk 16.3.0, 16.4.1, 17.2.0, 17.2.1 | **mishandled** | offer ID: the number 2^53+1 (arrives as 2^53), `"0x10"`, `" 16 "`, `""` (encodes 0), `"-1"`. Muxed ID: `"0x10"`, `" 16 "`, `""`; the M-address encodes the parsed value but `id()` returns the string as typed. |
| @stellar/stellar-sdk 17.3.0, 17.4.0 | pass | all refused |
| stellar-sdk (Python) 17.0.1, the latest release | **mishandled** | offer ID -1 (encodes -1); offer ID 2^64 (encodes **0**: "create a new offer"); muxed ID 2^64 (encodes **0**: a different sub-account) |
| py-stellar-base at `134c0e11` (unreleased; still reports version 17.0.1) | pass | all refused |

Raw output, one line per run:

```
{"sdk":"@stellar/stellar-sdk 17.2.1","check":"ids_exact","wrong":[],"accepted":["offer_id 9007199254740992 (a number above 2^53 has already lost precision) accepted, encodes 9007199254740992","offer_id \"0x10\" (not canonical decimal) accepted, encodes 16","offer_id \" 16 \" (whitespace) accepted, encodes 16","offer_id \"\" (empty; 0 means create a new offer) accepted, encodes 0","offer_id \"-1\" (negative) accepted, encodes -1","muxed_id \"0x10\" (not canonical decimal) accepted, encodes MA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJUAAAAAAAAAAACCRFU (id() returns \"0x10\")","muxed_id \" 16 \" (whitespace) accepted, encodes MA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJUAAAAAAAAAAACCRFU (id() returns \" 16 \")","muxed_id \"\" (empty) accepted, encodes MA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJUAAAAAAAAAAAACJUQ (id() returns \"\")"],"result":"mishandled"}
{"sdk":"@stellar/stellar-sdk 17.3.0","check":"ids_exact","wrong":[],"accepted":[],"result":"pass"}
{"sdk": "stellar-sdk 17.0.1", "check": "ids_exact", "wrong": [], "accepted": ["offer_id -1 (negative) accepted, encodes -1", "offer_id 18446744073709551616 (2^64, out of range) accepted, encodes 0", "muxed_id 18446744073709551616 (2^64, out of range) accepted, encodes 0"], "result": "mishandled"}
{"sdk": "stellar-sdk 17.0.1", "check": "ids_exact", "wrong": [], "accepted": [], "result": "pass"}
```

The last line is py-stellar-base installed from commit `134c0e11` into a separate environment.

## The Python sibling

py-stellar-base#1251 reports the Python counterpart of #1785 ("out-of-range 64-bit integers are
serialized modulo 2^64"), filed on 13 November 2026, with the negative offer ID added in a comment.
PR #1253 fixed it on `main` (commit `134c0e11`, 14 November), and the check above passes there.
No release has it yet: stellar-sdk 17.0.1 on PyPI still turns an offer ID of 2^64 into 0.

So the same defect was fixed in JavaScript on 8 October and in Python's `main` five weeks later,
and Python users are still exposed. That is the gap between SDKs this RFP's conformance runner is
meant to close.
