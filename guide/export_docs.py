#!/usr/bin/env python3
"""Export the indexer-hardening guide as a developers.stellar.org page.

  python3 guide/export_docs.py --prettier DIR            write the page
  python3 guide/export_docs.py --prettier DIR --check    exit 1 if the committed page is stale

developers.stellar.org is built by Mintlify from the stellar/stellar-docs repository: `.mdx` pages
with `title` and `description` front matter, absolute `/docs/...` links, and prettier with
`@stellar/prettier-config` (`proseWrap: never` for `.mdx`). This script turns INDEXER-HARDENING.md
into that form:
- front matter in place of the H1 and the draft-status paragraph;
- HTML comments (which MDX rejects) removed;
- links into this repository made absolute GitHub links;
- the result formatted with stellar-docs' own prettier config (guide/stellar-docs/prettierrc.cjs,
  copied from stellar-docs) and the prettier version its lockfile pins.

The page is written where it would sit in stellar-docs, next to the Galexie, ingest SDK and
processor guides: guide/stellar-docs/docs/data/indexers/build-your-own/indexer-hardening.mdx.

--prettier DIR is a directory whose node_modules holds prettier 3.9.10 and @stellar/prettier-config
1.2.0 (`npm install --prefix DIR prettier@3.9.10 @stellar/prettier-config@1.2.0`).
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "INDEXER-HARDENING.md"
OUT = HERE / "stellar-docs/docs/data/indexers/build-your-own/indexer-hardening.mdx"
CONFIG = HERE / "stellar-docs/prettierrc.cjs"
REPO_URL = "https://github.com/ABS-gmbh/shapecov/blob/main/"
TITLE = "Indexer hardening"
DESCRIPTION = ("Which transaction fields stellar-core validates and which it does not, caps for recursive values, "
               "participants from the meta, and muxed and signed-payload addresses, for anyone who reads the ledger.")


def raw():
    text = SRC.read_text()
    text = re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)
    lines = text.split("\n")
    assert lines[0].startswith("# "), "the guide must start with its H1"
    body = "\n".join(lines[1:]).lstrip("\n")
    # Drop the draft-status paragraph: the exported page is the form meant for publication.
    body = re.sub(r"^\*\*Status: draft for review\.\*\*.*?\n\n", "", body, count=1, flags=re.S)

    def link(m):
        target = m.group(2)
        if target.startswith(("http://", "https://", "#", "/")):
            return m.group(0)
        path, _, anchor = target.partition("#")
        resolved = os.path.normpath(os.path.join("guide", path))
        return "%s(%s%s%s)" % (m.group(1), REPO_URL, resolved, "#" + anchor if anchor else "")
    body = re.sub(r"(\[[^\]]*\])\(([^)\s]+)\)", link, body)
    head = ("---\ntitle: %s\ndescription: %s\n---\n\n"
            "{/* Generated from %sguide/INDEXER-HARDENING.md by guide/export_docs.py. Edit the source, not this page. */}\n\n"
            % (TITLE, DESCRIPTION, REPO_URL))
    return head + body


def formatted(prettier_dir):
    prettier = Path(prettier_dir) / "node_modules/.bin/prettier"
    env = dict(os.environ, NODE_PATH=str(Path(prettier_dir) / "node_modules"))
    p = subprocess.run([str(prettier), "--config", str(CONFIG), "--stdin-filepath", "indexer-hardening.mdx"],
                       input=raw(), capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise SystemExit("prettier failed:\n" + p.stderr)
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prettier", required=True)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    page = formatted(a.prettier)
    if a.check:
        if not OUT.exists() or OUT.read_text() != page:
            print("STALE: %s does not match guide/INDEXER-HARDENING.md; run guide/export_docs.py" % OUT.relative_to(HERE.parent))
            return 1
        print("EXPORT OK: %s is current" % OUT.relative_to(HERE.parent))
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page)
    print("wrote %s" % OUT.relative_to(HERE.parent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
