# The indexer-hardening guide

| File | What it is |
|---|---|
| [`INDEXER-HARDENING.md`](INDEXER-HARDENING.md) | The guide, the source to edit. |
| [`check_guide.py`](check_guide.py) | Checks the guide's tables against the corpus manifest, the probe records and `verdicts.json`, and renders the verdict table (`--write`). |
| [`probe_core.py`](probe_core.py), [`probes.json`](probes.json), [`verdicts.json`](verdicts.json) | stellar-core's own answer for each row: probes sent to a local stellar-core 30.0.0, and which probe or corpus ledger backs which row. |
| [`export_docs.py`](export_docs.py) | Writes the guide as a developers.stellar.org page. |
| [`stellar-docs/docs/data/indexers/build-your-own/indexer-hardening.mdx`](stellar-docs/docs/data/indexers/build-your-own/indexer-hardening.mdx) | That page, generated; do not edit it. |

## The developers.stellar.org page

developers.stellar.org is built by Mintlify from
[stellar/stellar-docs](https://github.com/stellar/stellar-docs). The exported page follows that
repository as read on 16 November 2026, at commit `62f29bbbfef7`:
- an `.mdx` file with `title` and `description` front matter;
- formatted by prettier 3.9.10 with `@stellar/prettier-config` 1.2.0, using the repository's own
  `.prettierrc.js` (copied here as `stellar-docs/prettierrc.cjs`);
- placed where it would sit in that repository, under "Build your own" beside the Galexie, ingest
  SDK and processor guides.

The export:
- drops the draft-status line, because the page is the form meant for publication;
- removes the HTML comments that MDX rejects;
- turns links into this repository into absolute GitHub links.

To publish it, one would copy the file into a stellar-docs checkout and add
`docs/data/indexers/build-your-own/indexer-hardening` to the "Build your own" group's `pages` in
`docs.json`. Nothing has been sent to stellar-docs. The RFP gates publication on review by a
stellar-core or platform engineer, which has not happened.

```sh
npm install --prefix /tmp/prettier prettier@3.9.10 @stellar/prettier-config@1.2.0
python3 guide/export_docs.py --prettier /tmp/prettier            # regenerate
python3 guide/export_docs.py --prettier /tmp/prettier --check    # what CI runs
```

**Checks run on the page (16 November 2026):**
- stellar-docs' `check:mdx`: prettier with the repository's config, `-c`. Passes; CI reruns it
  through `--check`.
- stellar-docs' `check:pad` (`scripts/pad-component-tags.mjs --check`), run with a copy of the
  script. Passes; not in CI.
- An MDX v3 compile with GitHub-flavoured Markdown (`@mdx-js/mdx` 3, `remark-gfm` 4), the parser
  family Mintlify builds with. Compiles; not in CI.

**Not run:**
- stellar-docs' `mint validate` and `mint broken-links --check-anchors`. They need the whole docs
  site and the Mintlify CLI. The page's links are external GitHub links and in-page anchors; the
  anchors are not checked against Mintlify's heading slugs.
- `rpcspec:docs`, which concerns other pages.
