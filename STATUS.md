# Status

What has changed in this repository, newest first. Generated from the git history and
release tags by `.github/scripts/status_log.py`; each line is a commit subject or a release.
Dates are UTC. The current state is in [`README.md`](README.md); every finding, with its
upstream status, is in [`FINDINGS.md`](FINDINGS.md).

## 16 November 2026

- README first screen: what ShapeCov is, the six deliverables, a 10-second check, results and limits ([`153ded6`](https://github.com/ABS-gmbh/shapecov/commit/153ded672754dc4c765c64354b6e2a2e513096f0))
- Findings as records: FINDINGS.json, with the FINDINGS.md table generated from it ([`3e2026f`](https://github.com/ABS-gmbh/shapecov/commit/3e2026fe8f3dc0ae0de1712a0c4d83760e04d088))
- stellar-etl: flag #450 muxed destinations fabricated for text and hash memos ([`0528458`](https://github.com/ABS-gmbh/shapecov/commit/05284585e9651421c600b705b139b4a96cfae2fe))
- Findings: E1 cites the correction posted on stellar-etl#512 (retitled; v1 to v3 meta only) ([`d35b7d1`](https://github.com/ABS-gmbh/shapecov/commit/d35b7d1b065c8ff26bfd066b03f74b730140269c))
- Release assets with provenance, and an upstream-drift watcher ([`7121d0d`](https://github.com/ABS-gmbh/shapecov/commit/7121d0d0fa064060fd74259da887b5189f6417bb))
- Detection backtest: wallet-backend 4 of 17 in-scope fixes, 2 blind; stellar-etl 1 of 9 ([`3781e4f`](https://github.com/ABS-gmbh/shapecov/commit/3781e4fe8300b856c426ed56b8d636a2416ffa4f))
- Guide: export as a developers.stellar.org page, checked in CI ([`b5050f5`](https://github.com/ABS-gmbh/shapecov/commit/b5050f5c7c2004fb7aebff4b1dcfafd0ac6f2caf))
- Date every schema cell to the stellar-xdr tag that introduced it; check the CAP tags ([`d5b22f2`](https://github.com/ABS-gmbh/shapecov/commit/d5b22f22d2c7a4c9f35facfa3852ecbaeb19c606))
- Packaging for other repositories' CI: a reusable conformance workflow and a linter action ([`e8eced0`](https://github.com/ABS-gmbh/shapecov/commit/e8eced0250bac54413cb1d7a06565bacf20633b2))
- Shape census of real traffic: pattern frequencies and largest sizes over the 611-ledger sweep ([`f25fb93`](https://github.com/ABS-gmbh/shapecov/commit/f25fb9330fbadae97d9aaf9782b18658998e5654))
- Cross-SDK defect matrix, generated from runs ([`acf16b8`](https://github.com/ABS-gmbh/shapecov/commit/acf16b8f9ace587792b68f4500ee8b1189c59c4f))
- ARCHITECTURE.md, a five-minute reviewer path, and one probe count everywhere ([`ee78236`](https://github.com/ABS-gmbh/shapecov/commit/ee782367f7c04adf8cb38ecbcb78de09185cea00))
- README, MAINTENANCE.md and the protocol drill follow the corpus: 88 entries, 85 real ledgers ([`8aa7ade`](https://github.com/ABS-gmbh/shapecov/commit/8aa7adeaf222a555fd19bc6e1f994e4978a79339))
- Corpus: 17 stellar-core goldens bring the 19 cells the protocol drill found missing ([`d03844a`](https://github.com/ABS-gmbh/shapecov/commit/d03844abb4e8f7846c49f90ba7d51b3af2f787be))
- Protocol drill: the upgrade runbook run against the next protocol before it ships ([`a2b3795`](https://github.com/ABS-gmbh/shapecov/commit/a2b379543a57029c3070d1ed667d1ced2a5a42e1))
- Guide: stellar-core's own verdict on every row of the field tables ([`d40ccb5`](https://github.com/ABS-gmbh/shapecov/commit/d40ccb55f3ba6546e743e300b215adfbafe4fae9))
- **Release [v0.1.0](https://github.com/ABS-gmbh/shapecov/releases/tag/v0.1.0)**, at `d50ece4`.
- README and VERIFY.md follow the corpus: 71 entries, 68 real ledgers; 39 CAPs covered, 1 partly ([`d50ece4`](https://github.com/ABS-gmbh/shapecov/commit/d50ece4e8c64094c9da5dc86c3519a9200001411))
- Guide: entry counts follow the corpus (failed-transaction 42, scval-wide-integer 41) ([`44680a1`](https://github.com/ABS-gmbh/shapecov/commit/44680a143a1af9f57b4ca93fae1d4519e56eb4bb))
- Corpus: two stellar-core goldens with frozen-trustline failures; CAP-0077 fully covered ([`630179f`](https://github.com/ABS-gmbh/shapecov/commit/630179f243201aa76b278b84c4b213cc86c8028b))
- VERIFY.md: RFP check 2's new job name; rows for both passphrases, the memory bound, the sightings scoreboard and the per-CAP table ([`d562817`](https://github.com/ABS-gmbh/shapecov/commit/d5628174b0918966f48733c778675caae8611bd0))
- Scoreboard 12 of 18, reproducible local-core corpus on both passphrases, memory bound, per-CAP table ([`fffb183`](https://github.com/ABS-gmbh/shapecov/commit/fffb1832eb554fe288616615404831dbf143abc7))
- CI: name the Maven dependency plugin in full and retry the Java runner build ([`1743295`](https://github.com/ABS-gmbh/shapecov/commit/174329592debb397f215a506a761d6fdd375d368))
- README: the name is ShapeCov, no longer a working name ([`08a2c8b`](https://github.com/ABS-gmbh/shapecov/commit/08a2c8b302593061de05d4158178db08fa2d1e13))
- CODEOWNERS: the three project leads own every path; MAINTENANCE.md names them ([`66c7df6`](https://github.com/ABS-gmbh/shapecov/commit/66c7df6789e6eb8090fbb0d7245fc12db60572ea))
- Findings: J1 closed by the maintainer's fix (java-stellar-sdk#842), checked on all 954 trailing-byte cases ([`ddb0d2e`](https://github.com/ABS-gmbh/shapecov/commit/ddb0d2ebb1b60c737636dbce1978780cd1295197))
- Findings: J1 fixed upstream (java-stellar-sdk#842); E1's impact corrected; SECURITY.md ([`cde8a9f`](https://github.com/ABS-gmbh/shapecov/commit/cde8a9fa8a05712e3a037c1ee3843d8b60d33440))
- CI: one job per RFP acceptance check; VERIFY.md maps each check to its job and command ([`e50d040`](https://github.com/ABS-gmbh/shapecov/commit/e50d04047ab77826d019a673e29b8f639042c467))
- Linter: accepted-findings file for wallet-backend and a check that fails on any finding outside it ([`fd5c07e`](https://github.com/ABS-gmbh/shapecov/commit/fd5c07e5281b496e76ad92605e0bb49583bb2c2c))
- Python's next XDR and strkey packages as a sixth decoder: stellar-xdr 0.2.1, stellar-strkey 0.2.0 ([`1b26316`](https://github.com/ABS-gmbh/shapecov/commit/1b2631660c273dc9bf690d11a7ffb7157faba9b1))
- Credit earlier reports: wallet-backend #804, #805, #806 in known.json; #820 and #677 in the linter triage ([`b401408`](https://github.com/ABS-gmbh/shapecov/commit/b401408a482b9fa96a1b56a6d4d2592d7c4744af))
- Sweep: 611 network ledgers through both indexers, oracle-checked; 9 added to the corpus ([`643a885`](https://github.com/ABS-gmbh/shapecov/commit/643a885ce22bf6aa73b2c59c65ffa93b958b7871))

## 15 November 2026

- E2 and E3 filed as stellar/stellar-etl#513 and #514; label their replay failures ([`16c63e4`](https://github.com/ABS-gmbh/shapecov/commit/16c63e4b3b3baa75c103661c28d197e1af48f9a3))
- Oracle: trades, claimable balances, pools and sponsorship; finds two stellar-etl revocation defects ([`0ede654`](https://github.com/ABS-gmbh/shapecov/commit/0ede65400fa3db43f3ed0123361dc3eb56057520))
- E1 filed as stellar/stellar-etl#512; label its replay failures with the issue ([`b861f20`](https://github.com/ABS-gmbh/shapecov/commit/b861f20b28be5ca86ad07145f9cf6e3d930be795))
- stellar-etl adapter: run the exports as the calling user ([`01850e8`](https://github.com/ABS-gmbh/shapecov/commit/01850e8e09f831fa70dc53f2cafc1c3cbcf77279))
- Replay: stellar-etl adapter, oracle-checked; finds export_token_transfer failing before protocol 23 ([`dc309c7`](https://github.com/ABS-gmbh/shapecov/commit/dc309c73ea1d7d48eec7dd9b7bcbafd8e83ac5f7))
- Oracle: check every account's net balance change ([`51bb98c`](https://github.com/ABS-gmbh/shapecov/commit/51bb98cf960c52d47454b6c440815952d9a0409e))
- Add the ledger-state oracle: every corpus ledger is now a test ([`7deba3a`](https://github.com/ABS-gmbh/shapecov/commit/7deba3a42dd839c6b75db8855468e29f4ca4a3aa))
- Add infrastructure and maintenance documents ([`2707d1b`](https://github.com/ABS-gmbh/shapecov/commit/2707d1bf4afa39ff870a382fe4cc7d5f105907b1))
- Conformance: reproduce js-stellar-sdk#1766 on its pre-fix releases ([`afaedfa`](https://github.com/ABS-gmbh/shapecov/commit/afaedfacd0947916b1921077fadf78081d25f163))
- Findings: mark py-stellar-base#1251 as confirmed, not found blind; replay memo ledger at main ([`51d9732`](https://github.com/ABS-gmbh/shapecov/commit/51d97323dc31613475d6b96a67ea138f889523bc))
- Corpus: record stellar-core and SDK validation for localcore-sac-trust-p28-5 ([`2b81d36`](https://github.com/ABS-gmbh/shapecov/commit/2b81d36b03fd538a8abe87eadd48508ebc0178c4))
- Findings: js-stellar-sdk#1785 reproduced, py-stellar-base#1251 rediscovered ([`23a8569`](https://github.com/ABS-gmbh/shapecov/commit/23a8569a3a6d999f64792ae64b6d4569f6bb8ba4))
- corpus_check: run ids_exact SDK checks instead of crashing on them ([`ff882d6`](https://github.com/ABS-gmbh/shapecov/commit/ff882d64aa9e91ec6879e8ebbfcf979164b57b38))
- Add CI: corpus, guide, linter, five-SDK conformance and replay ([`df53c90`](https://github.com/ABS-gmbh/shapecov/commit/df53c906c8e00e152e9d3065e1dba01bd765ef94))
- Replay harness reproduces the muxed half of wallet-backend#716 ([`7f6b32a`](https://github.com/ABS-gmbh/shapecov/commit/7f6b32a30c6c512022d5d7ec61544d94b5323c2f))
- Replay harness reproduces wallet-backend#731 ([`cdea61c`](https://github.com/ABS-gmbh/shapecov/commit/cdea61c394e4d22b3e026e8208870e5ff3672dc5))
- Corpus: muxed-source contract call from stellar-core 22.2.1 ([`811ea7b`](https://github.com/ABS-gmbh/shapecov/commit/811ea7b65d2322717c90c4be5a0a93279a30354a))
- Add local stellar-core generator; corpus gains memo and offer-ID shapes ([`0e71f6e`](https://github.com/ABS-gmbh/shapecov/commit/0e71f6eb26d6fe3f35fabedfb2ea559da85f248c))
- Add draft indexer-hardening guide, checked against the corpus ([`a8fec24`](https://github.com/ABS-gmbh/shapecov/commit/a8fec24b140f6e0be7e47edfb73978fef63a7f04))
- linter: remove false-positive classes; wallet-backend main now 4 real findings ([`f711234`](https://github.com/ABS-gmbh/shapecov/commit/f711234f33ee6561432d92da09e66a5388b1ecff))
- Add shapecov-lint: Go analyzers for the three ingestion mistakes ([`6cc40d8`](https://github.com/ABS-gmbh/shapecov/commit/6cc40d8e21f0054303f79e8c3607c2b482811f60))
- Add replay harness: real wallet-backend ingest over mock RPC and data lake ([`0acfd8e`](https://github.com/ABS-gmbh/shapecov/commit/0acfd8ed5c9b126346ebefc0f0cdc0ee7e5f2189))
- Grow corpus to 51 entries and add SDK conformance matrix ([`ae16144`](https://github.com/ABS-gmbh/shapecov/commit/ae1614485097ef5a01c4708f72e1ed06744e05c0))

## 14 November 2026

- Add Apache-2.0 licence ([`b29e1e9`](https://github.com/ABS-gmbh/shapecov/commit/b29e1e9999815cefa9c541e1f87a48014dbb769a))
- Initial prototype: schema-driven XDR conformance kit for Stellar ([`b2065c4`](https://github.com/ABS-gmbh/shapecov/commit/b2065c4033a794f5bc4aef06dcab3cbddff52c06))
