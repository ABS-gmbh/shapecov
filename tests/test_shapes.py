"""Per-shape roll-up: harness/replay/shapes.py, on synthetic replay results."""
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import load_module, write_jsonl, write_tree

sh = load_module("shapes", "harness/replay/shapes.py")


def row(entry, commit="a" * 40, inp="rpc", result="pass", oracle=None):
    return {"entry_id": entry, "commit": commit, "input": inp, "result": result, "oracle": oracle}


class Verdict(unittest.TestCase):
    def test_pass_needs_the_oracle_to_pass_too(self):
        self.assertEqual(sh.verdict(row("e", oracle={"verdict": "pass", "known": {}, "unexplained": []})), ("pass", []))
        self.assertEqual(sh.verdict(row("e", oracle={"verdict": "known issues only", "known": {"o/r#1": 2},
                                                     "unexplained": []})), ("oracle", ["o/r#1"]))

    def test_harness_result_wins_and_keeps_labels(self):
        v = sh.verdict(row("e", result="mishandled", oracle={"verdict": "mishandled", "known": {},
                                                             "unexplained": ["x"]}))
        self.assertEqual(v, ("mishandled", ["unexplained"]))

    def test_not_applicable(self):
        self.assertEqual(sh.verdict(row("e", result="not applicable")), ("not applicable", []))

    def test_cell_names_inputs_only_when_they_differ(self):
        self.assertEqual(sh.cell({"rpc": ("oracle", ["o/r#1"]), "datalake": ("oracle", ["o/r#1"])}), "oracle: o/r#1")
        self.assertEqual(sh.cell({"rpc": ("pass", []), "datalake": ("dropped", [])}), "datalake dropped; rpc pass")


class Render(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.saved = (sh.REPO, sh.HERE, sh.INDEXERS)
        sh.REPO, sh.HERE = str(d), str(d / "harness/replay")
        sh.INDEXERS = [("toy", "out/results.jsonl")]
        write_tree(d, {
            "corpus/patterns.json": {"patterns": {"muxed-account": {}, "signed-payload-signer": {}, "unseen": {}}},
            "corpus/manifest.json": {"entries": [
                {"id": "e1", "patterns": ["muxed-account"]},
                {"id": "e2", "patterns": ["muxed-account", {"pattern": "signed-payload-signer"}]}]},
        })
        old, new = "0" * 40, "1" * 40
        write_jsonl(d, "harness/replay/out/results.jsonl", [
            row("e1", commit=old, result="dropped"),
            row("e1", commit=new), row("e2", commit=new, result="mishandled",
                                       oracle={"verdict": "mishandled", "known": {"o/r#7": 1}, "unexplained": []}),
        ])

    def tearDown(self):
        sh.REPO, sh.HERE, sh.INDEXERS = self.saved
        self.tmp.cleanup()

    def test_one_row_per_shape_at_the_current_commit(self):
        text = sh.render()
        self.assertIn("## toy at `111111111111`", text)
        self.assertIn("| `muxed-account` | 2 | 2 | 1 | mishandled: o/r#7 (1): `e2` |", text)
        self.assertIn("| `signed-payload-signer` | 1 | 1 | 0 | mishandled: o/r#7 (1): `e2` |", text)
        self.assertIn("| `unseen` | 0 | 0 | 0 | no corpus entry yet |", text)
        self.assertIn("0 of the 2 shapes replayed pass", text)
        self.assertIn("by issue: o/r#7 on 1", text)


if __name__ == "__main__":
    unittest.main()
