"""tools/xdrschema.py: a small .x file parses into the schema written out below; the committed
protocol 30 schema is what the parser makes of schema/x, and the coverage report counts its cells."""
import json
import sys
import unittest

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import xdrschema  # noqa: E402
from gen import all_cells  # noqa: E402

EXPECTED = {
    "consts": {"MAX_NAMES": 4},
    "order": ["Hash", "TimePoint", "Color", "Thing", "ThingExt", "Choice"],
    "types": {
        "Hash": {"k": "typedef", "t": {"r": "opaque", "fixed": 32}},
        "TimePoint": {"k": "typedef", "t": {"r": "uhyper"}},
        "Color": {"k": "enum", "members": [["RED", 0], ["GREEN", 1], ["BLUE", 16]]},
        "Thing": {"k": "struct", "fields": [
            ["a", {"r": "int"}], ["b", {"r": "uint"}], ["c", {"r": "hyper"}], ["d", {"r": "bool"}],
            ["h", {"r": "ref", "name": "Hash"}],
            ["blob", {"r": "opaque", "max": None}],
            ["name", {"r": "string", "max": 4}],
            ["colors", {"r": "array", "of": {"r": "ref", "name": "Color"}, "max": 4}],
            ["maybe", {"r": "opt", "of": {"r": "ref", "name": "TimePoint"}}],
            ["pair", {"r": "array", "of": {"r": "int"}, "fixed": 2}],
            ["ext", {"r": "ref", "name": "ThingExt"}]]},
        # an anonymous union is hoisted and named Parent + UpperCamel(field), as xdrgen does
        "ThingExt": {"k": "union", "disc": {"r": "int"}, "discName": "v", "default": None, "arms": [
            {"cases": [0], "labels": ["0"], "name": None, "t": None},
            {"cases": [1], "labels": ["1"], "name": "one", "t": {"r": "int"}}]},
        "Choice": {"k": "union", "disc": {"r": "ref", "name": "Color"}, "discName": "c",
                   "default": {"name": "other", "t": {"r": "int"}}, "arms": [
                       {"cases": [0, 1], "labels": ["RED", "GREEN"], "name": "thing", "t": {"r": "ref", "name": "Thing"}},
                       {"cases": [16], "labels": ["BLUE"], "name": None, "t": None}]},
    },
}


class Fixture(unittest.TestCase):
    def test_parses_into_the_expected_schema(self):
        got = xdrschema.load(ROOT / "tests" / "fixtures" / "xdrschema")
        self.assertEqual(got, EXPECTED)

    def test_cells_are_union_arms_and_enum_members(self):
        self.assertEqual(all_cells(EXPECTED), {
            "arm:ThingExt.0", "arm:ThingExt.1", "arm:Choice.RED", "arm:Choice.GREEN", "arm:Choice.BLUE",
            "enum:Color.RED", "enum:Color.GREEN", "enum:Color.BLUE"})

    def test_unknown_constant_is_an_error(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            Path(d, "bad.x").write_text("struct S { int x<NOPE>; };\n")
            with self.assertRaises(SyntaxError):
                xdrschema.load(d)


class Protocol30(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = xdrschema.load(ROOT / "schema" / "x")
        cls.committed = json.load(open(ROOT / "schema" / "schema.json"))

    def test_committed_schema_is_the_parse_of_schema_x(self):
        self.assertEqual(self.parsed["types"], self.committed["types"])
        self.assertEqual(self.parsed["consts"], self.committed["consts"])

    def test_cell_counts_match_the_coverage_report(self):
        """corpus/coverage.json states the cell counts that the documents quote (check_counts.py
        compares them); here they must follow from the schema the parser makes."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("cell_coverage", ROOT / "tools" / "cell_coverage.py")
        cc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cc)
        every, reach, _ = cc.cells(self.committed)
        report = json.load(open(ROOT / "corpus" / "coverage.json"))
        self.assertEqual(report["schema_cells_old_definition"], len(all_cells(self.committed)))
        self.assertEqual((report["schema_cells"], report["reachable_cells"]), (len(every), len(reach)))


if __name__ == "__main__":
    unittest.main()
