# Filed 17 November 2026: https://github.com/stellar/stellar-docs/issues/3165

**Title:** Proposed page for "Build your own indexer": what stellar-core validates, and what an indexer has to check itself

The "Build your own" indexer section explains how to read ledger data, but not which properties of that data stellar-core guarantees. Several indexer bugs this year came from assuming a guarantee that is not there: a signed-payload signer where an account was expected (stellar/wallet-backend#729), muxed and signed-payload addresses cut to the wrong length (stellar/wallet-backend#716).

I have a draft page for that section:

1. Field by field, what stellar-core validates in a transaction and what it passes through untouched (signatures, sequence numbers, fees, time bounds, memos, muxed accounts, asset codes, contract values).
2. Depth and size limits for recursive values.
3. Taking a transaction's participants from the ledger meta, not from the envelope.
4. Muxed and signed-payload addresses, with SEP-23.
5. A 26-item checklist.

Every statement in the first table that a transaction can test was submitted to a local stellar-core 30.0.0 and the answer recorded (51 probes, rerun in CI). Eleven statements rest on a citation of stellar-core's source only; they are listed separately so a reviewer can start with them.

- The page, in this repository's layout and formatted with your prettier configuration: https://github.com/ABS-gmbh/shapecov/blob/v0.2.0/guide/stellar-docs/docs/data/indexers/build-your-own/indexer-hardening.mdx
- The same text as Markdown: https://github.com/ABS-gmbh/shapecov/blob/v0.2.0/guide/INDEXER-HARDENING.md
- What a reviewer is asked to check, and where their judgment is needed: https://github.com/ABS-gmbh/shapecov/blob/v0.2.0/guide/REVIEW.md

I have not run `mint validate` or the link check on it yet.

Two questions before I open a pull request:

1. Is a page like this wanted under `docs/data/indexers/build-your-own/`, or somewhere else, or not at all?
2. It should not be published before someone who knows stellar-core's transaction validation has read it, and it opens with a "Draft, not reviewed" warning until then. Who is the right person to ask?

For context, the page was written for the SCF RFP "XDR/CAP-Coverage Audit Tool and Indexer-Hardening Guide", which asks for a guide ready for developers.stellar.org and gates its publication on that review.
