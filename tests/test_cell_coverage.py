"""tools/cell_coverage.py: which cells count, which are reachable, and the repository's report is current."""
import unittest

from tests.helpers import call_main, load_module

coverage = load_module("cell_coverage_under_test", "tools/cell_coverage.py")

INT = {"r": "int"}
SCHEMA = {"types": {
    "LedgerCloseMeta": {"k": "struct", "fields": [["u", {"r": "ref", "name": "U"}], ["v", {"r": "ref", "name": "V"}],
                                                  ["many", {"r": "array", "of": {"r": "ref", "name": "W"}, "max": None}]]},
    "E": {"k": "enum", "members": [["A", 0], ["B", 1]]},               # only a discriminant
    "U": {"k": "union", "disc": {"r": "ref", "name": "E"}, "discName": "type", "default": None,
          "arms": [{"cases": [0], "labels": ["A"], "name": None, "t": None},
                   {"cases": [1], "labels": ["B"], "name": "b", "t": INT}]},
    "V": {"k": "enum", "members": [["X", 0], ["Y", 1]]},               # a value
    "W": {"k": "typedef", "t": {"r": "opt", "of": {"r": "ref", "name": "V"}}},
    "Overlay": {"k": "union", "disc": INT, "discName": "v", "default": None,
                "arms": [{"cases": [0], "labels": ["0"], "name": None, "t": None}]},
}}


class Definitions(unittest.TestCase):
    def test_discriminant_only_enums(self):
        self.assertEqual(coverage.discriminant_only(SCHEMA["types"]), {"E"})

    def test_reachable_types_follow_fields_arms_arrays_and_discriminants(self):
        self.assertEqual(coverage.reachable(SCHEMA["types"]), {"LedgerCloseMeta", "U", "E", "V", "W"})

    def test_cells(self):
        every, reach, _ = coverage.cells(SCHEMA)
        self.assertEqual(every, {"arm:U.A", "arm:U.B", "enum:V.X", "enum:V.Y", "arm:Overlay.0"})
        self.assertEqual(reach, every - {"arm:Overlay.0"})


class Repository(unittest.TestCase):
    def test_report_is_current_and_every_uncovered_cell_is_classified(self):
        rc, out = call_main(coverage.main, "--check")
        self.assertEqual(rc, 0, out[-800:])
        self.assertIn("COVERAGE OK", out)


if __name__ == "__main__":
    unittest.main()
