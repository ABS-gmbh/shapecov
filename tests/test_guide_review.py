"""RFP check 4's publication gate: guide/review.py, as guide/export_docs.py and guide/check_guide.py use it.

The guide's review line is empty until a reviewer's own commit fills it. While it is empty the page
for developers.stellar.org opens with a not-reviewed caution; once it is filled, with a "Reviewed by"
line. check_guide fails when the committed page and the line disagree."""
import unittest

from tests.helpers import load_module

rv = load_module("guide_review", "guide/review.py")
ex = load_module("guide_export", "guide/export_docs.py")
cg = load_module("guide_check", "guide/check_guide.py")

EMPTY = "**Review:** reviewer: —; role: —; date: —; commit reviewed: —"
FILLED = "**Review:** reviewer: A. Reviewer; role: stellar-core engineer; date: 2026-12-01; commit reviewed: 0123456789ab"


def guide(review_line, status="**Status: draft for review.** Publication is gated on review.\n\n"):
    return "# Guide\n\n%s%s\n\nBody text.\n" % (status, review_line)


class Parse(unittest.TestCase):
    def test_empty_and_filled(self):
        self.assertIsNone(rv.parse(guide(EMPTY)))
        self.assertEqual(rv.parse(guide(FILLED))["reviewer"], "A. Reviewer")

    def test_refuses_a_missing_partial_or_malformed_line(self):
        for text in (guide(""), guide(EMPTY.replace("role: —", "role: engineer")),
                     guide(FILLED.replace("2026-12-01", "1 Dec 2026")), guide(FILLED.replace("0123456789ab", "main")),
                     guide(EMPTY + "\n" + EMPTY)):
            with self.assertRaises(ValueError):
                rv.parse(text)


class Export(unittest.TestCase):
    def test_unreviewed_page_opens_with_the_caution(self):
        page = ex.raw(guide(EMPTY))
        self.assertIn(rv.CAUTION_MARK, page)
        self.assertNotIn(rv.REVIEWED_MARK, page)
        self.assertNotIn("**Review:**", page)
        self.assertNotIn("**Status:", page)

    def test_reviewed_page_names_the_review(self):
        page = ex.raw(guide(FILLED, status="**Status: reviewed.**\n\n"))
        self.assertNotIn(rv.CAUTION_MARK, page)
        self.assertIn("Reviewed by A. Reviewer (stellar-core engineer) on 2026-12-01", page)

    def test_a_partial_line_stops_the_export(self):
        with self.assertRaises(ValueError):
            ex.raw(guide(EMPTY.replace("date: —", "date: 2026-12-01")))


class Gate(unittest.TestCase):
    def test_agreeing_states_pass(self):
        self.assertEqual(rv.gate_errors(guide(EMPTY), ex.raw(guide(EMPTY))), [])
        reviewed = guide(FILLED, status="**Status: reviewed.**\n\n")
        self.assertEqual(rv.gate_errors(reviewed, ex.raw(reviewed)), [])

    def test_disagreeing_states_fail(self):
        unreviewed_page = ex.raw(guide(EMPTY))
        reviewed = guide(FILLED, status="**Status: reviewed.**\n\n")
        self.assertTrue(rv.gate_errors(guide(EMPTY), ex.raw(reviewed)))       # page claims a review
        self.assertTrue(rv.gate_errors(reviewed, unreviewed_page))             # page not regenerated
        self.assertTrue(rv.gate_errors(guide(FILLED), ex.raw(guide(FILLED))))  # status still says draft


class Brief(unittest.TestCase):
    def test_lists_citation_only_sides_with_their_statement_and_source(self):
        text = ("# G\n\n| Field | Checked | Not checked |\n|---|---|---|\n| Fee | at least the base fee [2] | the inner fee |\n\n"
                "### Sources\n\n1. a.cpp\n2. `b.cpp` 10-20\n\n## 2. Next\n")
        verdicts = {"rows": [{"field": "Fee", "checked": {"citation_only": "not probed"}, "not_checked": {"probes": ["p"]}}]}
        out = rv.render_brief(verdicts, text, cg.tables, cg.side_status)
        self.assertIn("1 have a verdict from stellar-core itself", out)
        self.assertIn("**Fee**, what stellar-core checks. The guide says: at least the base fee [2]", out)
        self.assertIn("Why there is no probe: not probed.", out)
        self.assertIn("Source [2]: `b.cpp` 10-20", out)


if __name__ == "__main__":
    unittest.main()
