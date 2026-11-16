# Security policy

## A vulnerability in this repository

Report it privately to **contact@absolution-gmbh.com**, not in a public issue. Include what you ran, what happened, and the commit. We acknowledge every report within **3 business days**, say what we will do, and credit you when the fix is published, unless you ask us not to.

In scope: anything here that could harm the machine or CI it runs on. The harness and runners execute third-party code (indexers, SDKs, stellar-core) in Docker, with no network or with a network that has no route to the internet (see `INFRASTRUCTURE.md`). An escape from that isolation is in scope, as is a corpus entry or tool input that makes our own tools misbehave.

## A vulnerability this kit finds in Stellar software

The kit is built to find defects in software that reads the Stellar ledger: SDKs, indexers and stellar-core. A defect that only makes data wrong or incomplete is filed as a public issue in the affected project, with a minimal reproduction, as listed in `FINDINGS.md`.

A defect that could be exploited is **not** filed in public. Examples: stellar-core and a decoder disagreeing on whether a transaction is valid, a crash or halt triggered by data anyone can submit, or funds or authorization attributed to the wrong account. We report it privately:
- for SDF projects, through SDF's bug bounty program (https://stellar.org/grants-and-funding/bug-bounty), as SDF's security policy asks;
- for other projects, to their maintainers' security contact.

We publish only after a fix is released or the maintainers agree. Until then, the corpus holds no entry that reproduces it.
