#!/usr/bin/env python3
"""Export the indexer-hardening guide as a developers.stellar.org page.

  python3 guide/export_docs.py --prettier DIR            write the page
  python3 guide/export_docs.py --prettier DIR --check    exit 1 if the committed page is stale

developers.stellar.org is built by Mintlify from the stellar/stellar-docs repository: `.mdx` pages
with `title` and `description` front matter, absolute `/docs/...` links, and prettier with
`@stellar/prettier-config` (`proseWrap: never` for `.mdx`). This script turns INDEXER-HARDENING.md
into that form:
- front matter in place of the H1; the status paragraph and the review line become the page's opening,
  a not-reviewed caution until the review line is filled, then a "Reviewed by" line (guide/review.py);
- HTML comments (which MDX rejects) removed;
- links into this repository made absolute GitHub links;
- the result formatted with stellar-docs' own prettier config (guide/stellar-docs/prettierrc.cjs,
  copied from stellar-docs) and the prettier version its lockfile pins.

The page is written where it would sit in stellar-docs, next to the Galexie, ingest SDK and
processor guides: guide/stellar-docs/docs/data/indexers/build-your-own/indexer-hardening.mdx.

--prettier DIR is a directory whose node_modules holds prettier 3.9.10 and @stellar/prettier-config
1.2.0 (`npm install --prefix DIR prettier@3.9.10 @stellar/prettier-config@1.2.0`).

The page's generated-from comment records a SHA-256 of everything the page is made from: the page text
before formatting (which takes in the guide, its review line and the evidence table it carries, and
this script's own transformation), stellar-docs' prettier config and the pinned prettier versions.
guide/check_guide.py, which the quick check runs, recomputes it without node and fails when the
committed page was generated from other inputs (stale_errors below). The formatting itself is
compared with prettier by --check, in CI.
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC = HERE / "INDEXER-HARDENING.md"
OUT = HERE / "stellar-docs/docs/data/indexers/build-your-own/indexer-hardening.mdx"
CONFIG = HERE / "stellar-docs/prettierrc.cjs"
REPO_URL = "https://github.com/ABS-gmbh/shapecov/blob/main/"
TITLE = "Indexer hardening"
PRETTIER_PINS = "prettier@3.9.10 @stellar/prettier-config@1.2.0"
DIGEST_RE = re.compile(r"from inputs sha256 ([0-9a-f]{64})")
DESCRIPTION = ("Which transaction fields stellar-core validates and which it does not, caps for recursive values, "
               "participants from the meta, and muxed and signed-payload addresses, for anyone who reads the ledger.")


def _content(text):
    """The front matter, then the page's opening and body, before formatting."""
    opening = review.page_opening(review.parse(text))  # raises on a review line filled in part
    text = re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)
    lines = text.split("\n")
    assert lines[0].startswith("# "), "the guide must start with its H1"
    body = "\n".join(lines[1:]).lstrip("\n")
    # The status paragraph and the review line become the page's opening: a caution that the page has
    # not been reviewed, or the reviewed-by line once the review line is filled (guide/review.py).
    body = re.sub(r"^\*\*Status: .*?\n\n", "", body, count=1, flags=re.S)
    body = review.REVIEW_RE.sub("", body, count=1).lstrip("\n")

    def link(m):
        target = m.group(2)
        if target.startswith(("http://", "https://", "#", "/")):
            return m.group(0)
        path, _, anchor = target.partition("#")
        resolved = os.path.normpath(os.path.join("guide", path))
        return "%s(%s%s%s)" % (m.group(1), REPO_URL, resolved, "#" + anchor if anchor else "")
    body = re.sub(r"(\[[^\]]*\])\(([^)\s]+)\)", link, body)
    return "---\ntitle: %s\ndescription: %s\n---\n\n" % (TITLE, DESCRIPTION), opening + "\n" + body


def inputs_digest(text=None):
    """SHA-256 of what the page is made from: its content before formatting, the prettier config and the
    pinned prettier versions."""
    text = SRC.read_text() if text is None else text
    front, page = _content(text)
    h = hashlib.sha256()
    for part in (front.encode(), page.encode(), CONFIG.read_bytes(), PRETTIER_PINS.encode()):
        h.update(hashlib.sha256(part).digest())
    return h.hexdigest()


def raw(text=None):
    text = SRC.read_text() if text is None else text
    front, page = _content(text)
    head = ("{/* Generated from %sguide/INDEXER-HARDENING.md by guide/export_docs.py from inputs sha256 %s. "
            "Edit the source, not this page. */}\n\n" % (REPO_URL, inputs_digest(text)))
    return front + head + page


def stale_errors(guide_text, page_text):
    """Why the committed page was not generated from the guide as it is now, without running prettier."""
    m = DIGEST_RE.search(page_text)
    want = inputs_digest(guide_text)
    if not m:
        return ["the page records no inputs digest; run guide/export_docs.py"]
    if m.group(1) != want:
        return ["the page was generated from other inputs than the guide as it is now (recorded sha256 %s, "
                "now %s); run guide/export_docs.py" % (m.group(1)[:12], want[:12])]
    return []


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
