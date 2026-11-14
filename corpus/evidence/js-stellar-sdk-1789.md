# Reproduction: stellar/js-stellar-sdk#1789

Sighting: "scValToNative silently drops scvMap entries whose keys convert to the same property".
Reported against v17.2.1 and earlier.

Corpus entry: `synthetic-scmap-colliding-keys`, a TransactionMeta v4 whose Soroban return value
is a map with the keys u32 `1` and symbol `"1"`. Run on 14 November 2026.

## What was run

The manifest attaches the check `map_entries_preserved` to the entry: converting the map at
`v4.sorobanMeta.returnValue` to a native value must keep 2 entries or fail with an error.
`tools/corpus_check.py --sdk-checks` runs it against pinned SDK versions.

```bash
(cd harness/sdk-semantic && npm install)
python3 tools/corpus_check.py --sdk-checks
```

## Result

| SDK | Result | Detail |
|---|---|---|
| @stellar/stellar-sdk 17.2.1 | **mishandled** | 2 entries in the XDR, 1 after `scValToNative`: `{"1": 20}`. No error. |
| @stellar/stellar-sdk 17.4.0 | pass | Refuses with an error: `scvMap has more than one key that converts to "1"; read the raw map entries instead` |
| stellar-sdk (Python) 17.0.1 | pass | Keeps both: `{1: 10, '1': 20}` |

Raw output for 17.2.1:

```
{"sdk":"@stellar/stellar-sdk 17.2.1","check":"map_entries_preserved","entries_in_xdr":2,"entries_after_conversion":1,"converted":{"1":20},"result":"mishandled","detail":"1 entry(ies) dropped without an error"}
```

All five decoders and stellar-core 30.0.0 decode the entry itself identically, so the loss is in
the conversion, not in XDR decoding.

## Note on the Python sibling

py-stellar-base #1250 reports the same class of loss in `scval.to_native`. This entry does not
trigger it, because Python keeps an integer key and a string key apart. A second entry with keys
that collide in Python (for example string `"1"` and symbol `"1"`) would be needed to reproduce
that one; it is not in the sample corpus.
