"""RFP check 4: guide/check_guide.py, its helpers and its checks on a small synthetic guide."""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import call_main, load_module, write_tree

cg = load_module("check_guide", "guide/check_guide.py")

GUIDE = """# Guide

**Review:** reviewer: —; role: —; date: —; commit reviewed: —

| Field | Checked | Not checked |
|---|---|---|
| Home domain | its length | its content |

| Corpus shape | CAP | Entries |
|---|---|---|
| `muxed-account` | CAP-27 | 1 |

A muxed source appears in `testnet-1`.

%s
%s
""" % (cg.BEGIN, cg.END)


class Helpers(unittest.TestCase):
    def test_norm_cap_pads_the_number(self):
        self.assertEqual(cg.norm_cap("CAP-27"), "CAP-0027")
        self.assertEqual(cg.norm_cap("CAP-46-11"), "CAP-0046-11")
        self.assertEqual(cg.norm_cap("CAP-0067"), "CAP-0067")

    def test_tables_splits_rows_but_not_escaped_pipes(self):
        t = list(cg.tables("x\n\n| A | B |\n|---|---|\n| 1 | a \\| b |\n| 2 | c |\n\ny"))
        self.assertEqual(len(t), 1)
        head, rows = t[0]
        self.assertEqual(head, ["A", "B"])
        self.assertEqual(rows, [["1", "a \\| b"], ["2", "c"]])

    def test_short_drops_the_fee_amount(self):
        self.assertEqual(cg.short("accepted (fee charged: 128259 stroops)"), "accepted, fee charged")

    def test_side_status(self):
        self.assertEqual(cg.side_status({"nothing_claimed": True}), "none")
        self.assertEqual(cg.side_status({"citation_only": "src/x.cpp"}), "citation")
        self.assertEqual(cg.side_status({"probes": ["p1"]}), "core")
        self.assertEqual(cg.side_status({"corpus": ["muxed-account"]}), "core")
        self.assertEqual(cg.side_status({}), "missing")


class CheckGuide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.paths = {"REPO": str(d), "GUIDE": str(d / "guide.md"), "VERDICTS": str(d / "verdicts.json"),
                      "PROBES": str(d / "probes.json"),
                      "PAGE": str(d / "page.mdx"), "BRIEF": str(d / "REVIEW.md")}
        self.saved = {k: getattr(cg, k) for k in self.paths}
        for k, v in self.paths.items():
            setattr(cg, k, v)
        self.probes = {"stellar_core": "stellar-core 30.0.0 (0e49751aa)", "protocol": 30, "probes": [
            {"id": "home-domain-33", "row": "Home domain", "rule": "33 bytes", "expect": "rejected at submission",
             "outcome": "rejected at submission: txMALFORMED", "agrees": True},
            {"id": "setup", "row": "(setup)", "rule": "deploy", "expect": "accepted",
             "outcome": "accepted (fee charged: 100 stroops)", "agrees": True}]}
        self.verdicts = {"rows": [{"field": "Home domain", "checked": {"probes": ["home-domain-33"]},
                                   "not_checked": {"corpus": ["muxed-account"]}}]}
        write_tree(d, {
            "corpus/patterns.json": {"patterns": {"muxed-account": {"caps": ["CAP-0027"]}}},
            "corpus/manifest.json": {"entries": [{"id": "testnet-1", "patterns": ["muxed-account"]}]},
            "guide.md": GUIDE,
            "page.mdx": "---\n---\n\n" + cg.review.CAUTION + "\nBody.\n",
            "REVIEW.md": "# Brief\n\n%s\n%s\n" % (cg.review.BRIEF_BEGIN, cg.review.BRIEF_END),
        })
        self.save()
        rc, out = call_main(cg.main, "--write")
        self.assertEqual(rc, 0, out)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(cg, k, v)
        self.tmp.cleanup()

    def save(self):
        write_tree(self.paths["REPO"], {"verdicts.json": self.verdicts, "probes.json": self.probes})

    def guide(self, old, new):
        p = Path(self.paths["GUIDE"])
        p.write_text(p.read_text().replace(old, new))

    def assertFails(self, needle):
        rc, out = call_main(cg.main)
        self.assertEqual(rc, 1, out)
        self.assertIn(needle, out)

    def test_agreeing_guide_passes(self):
        rc, out = call_main(cg.main)
        self.assertEqual(rc, 0, out)
        self.assertIn("GUIDE OK", out)
        self.assertIn("1 probes, plus 1 setup transaction", Path(self.paths["GUIDE"]).read_text())

    def test_page_and_review_line_must_agree(self):
        Path(self.paths["PAGE"]).write_text("---\n---\n\nReviewed by someone.\n")
        self.assertFails("review gate: the review line is empty, but the exported page does not open with the not-reviewed caution")

    def test_stale_brief_fails(self):
        Path(self.paths["BRIEF"]).write_text("# Brief\n\n%s\nold list\n%s\n" % (cg.review.BRIEF_BEGIN, cg.review.BRIEF_END))
        self.assertFails("list of citation-only rows is stale")

    def test_wrong_cap_column_fails(self):
        self.guide("| CAP-27 |", "| CAP-40 |")
        self.assertFails("CAP column says ['CAP-0040'], patterns.json says ['CAP-0027']")

    def test_wrong_entry_count_fails(self):
        self.guide("| CAP-27 | 1 |", "| CAP-27 | 2 |")
        self.assertFails("Entries column says '2', the manifest has '1'")

    def test_unknown_entry_fails(self):
        self.guide("`testnet-1`", "`testnet-9`")
        self.assertFails("names corpus entry `testnet-9`, which is not in the manifest")

    def test_probe_that_disagrees_fails(self):
        self.probes["probes"][0]["agrees"] = False
        self.save()
        self.assertFails("probe home-domain-33: stellar-core's outcome")

    def test_side_without_evidence_fails(self):
        self.verdicts["rows"][0]["not_checked"] = {}
        self.save()
        self.assertFails("no probe, no corpus pattern and no citation_only reason")

    def test_stale_verdict_table_fails(self):
        self.verdicts["rows"][0]["not_checked"] = {"citation_only": "src/main.cpp"}
        self.save()
        self.assertFails("the guide's verdict table is out of date")


class RepositoryGuide(unittest.TestCase):
    def test_every_probe_has_an_outcome_that_agrees(self):
        import json
        from tests.helpers import ROOT
        probes = json.loads((ROOT / "guide/probes.json").read_text())["probes"]
        self.assertTrue(probes)
        for p in probes:
            self.assertTrue(p["agrees"], p["id"])


if __name__ == "__main__":
    unittest.main()
