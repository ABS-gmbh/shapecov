# Corpus (draft)

Draft manifest format and three sample entries for the SCF RFP "XDR/CAP-Coverage Audit Tool and
Indexer-Hardening Guide". Status: 14 November 2026.

| File | What it is |
|---|---|
| `manifest.schema.json` | The manifest format, as JSON Schema (draft 2020-12). |
| `manifest.json` | The three sample entries. |
| `entries/*.xdr.b64` | One XDR value per file, one line of base64. |
| `values/*.json` | The readable value each generated entry is encoded from. |
| `evidence/*.md` | Recorded reproductions of two sightings the RFP cites. |

## Entries

| ID | Type | Synthetic | Protocol | CAP | Reproduces |
|---|---|---|---|---|---|
| `testnet-4437357-signed-payload-signer` | LedgerCloseMeta | no (testnet ledger 4437357) | 28 | CAP-0040 | stellar/wallet-backend#729 |
| `synthetic-scmap-colliding-keys` | TransactionMeta | yes | 23 | CAP-0046-01, CAP-0067 | stellar/js-stellar-sdk#1789 |
| `synthetic-muxed-contract-address` | TransactionEnvelope | yes | 30 | CAP-0084 | none; new shape in protocol 30 |

## Manifest fields

Each entry record carries what the RFP lists, plus what a consumer needs to check the entry
without trusting us.

| Field | Meaning |
|---|---|
| `id` | Stable entry ID. |
| `xdr_type`, `file`, `sha256`, `size_bytes` | What the bytes are and how to verify you have them. |
| `protocol_version` | The ledger's protocol for a real ledger; the lowest protocol whose XDR can decode a synthetic entry. |
| `caps` | CAPs the entry exercises, each tied to the schema cells that show it. |
| `synthetic` | `false` only when a Stellar network or stellar-core produced the bytes. |
| `source` | For a real ledger: network, passphrase, sequence, hash, close time, where it was fetched. For a generated entry: the generator and the value file. A third form is reserved for stellar-core golden ledgers. |
| `shape` | Why this entry is in the corpus, in a sentence or two. |
| `cells`, `cells_new_in_protocol` | Every union case and enum value the entry exercises, and which of them are new since the previous XDR version. Computed, not written by hand. |
| `expected.decoded` | Expected decoded values as path and value pairs. |
| `expected.indexer` | What an indexer must produce, derived from the decoded entry. |
| `expected.sdk` | Checks on what an SDK does with the value after decoding it. |
| `validation` | Recorded results of the checks below. |
| `sightings` | Public bug reports the entry reproduces or relates to, with a pointer to the evidence. |

A cell is a union case (`arm:SignerKey.SIGNER_KEY_TYPE_ED25519_SIGNED_PAYLOAD`) or an enum value
(`enum:OperationType.PAYMENT`) of the XDR schema.

A path is dotted XDR field names with `[i]` for array elements. A union is addressed by its
discriminant's own name and its arm's name, for example `v2.ledgerHeader.header.ledgerSeq` or
`v1.tx.operations[0].body.type`. This is the layout of stellar-core's JSON output, so the same
path can be looked up in what stellar-core prints.

## How an entry is checked

`python3 tools/corpus_check.py --sdks rust,js,python,go,java --core --sdk-checks`

1. The manifest validates against the schema.
2. The file matches its hash and size.
3. A strict decoder written from the XDR schema, sharing no code with any SDK, decodes the entry;
   re-encoding gives the same bytes; the cells it finds equal the recorded cells.
4. Every `expected.decoded` value matches.
5. The source record agrees with the bytes: ledger sequence, hash, close time and protocol for a
   real ledger; the value file for a generated one.
6. CAP cells are among the entry's cells. Cells new in protocol 30 are found by comparing the
   v28.0 and v30.0 XDR, and force `protocol_version` to 30.
7. Indexer expectations are recomputed from the decoded entry.
8. rs-stellar-xdr, js-stellar-sdk, py-stellar-base, go-stellar-sdk and java-stellar-sdk each
   decode and re-encode the entry to identical bytes.
9. stellar-core 30.0.0 decodes the entry, and its own JSON output is compared with
   `expected.decoded`.

Result on 14 November 2026: all checks pass for all three entries. stellar-core confirms 13 of 13
expected values for the real ledger, 8 of 8 for the map entry, and 6 of 9 for the muxed-contract
entry; it prints the other 3 in another form (an address as a strkey), so those paths do not line
up.

## Limits of this draft

- Three entries only. They were chosen to show a real ledger, a generated entry, an indexer
  sighting, an SDK sighting, and a shape that is new in protocol 30.
- No entry is compared with stellar-core's golden LedgerCloseMeta files yet. The `source` form and
  the `core_golden` result for that exist in the schema and are unused.
- CAP tags are assigned by hand. Only "new in protocol 30" is computed.
- The two generated entries are decode-level values, not the output of applied transactions.
- `expected.indexer` and `expected.sdk` each know one kind of check.
