"""Cross-SDK defect matrix: sdk-matrix/matrix.py's rendering, without running any SDK."""
import json
import unittest

from tests.helpers import ROOT, load_module

mx = load_module("matrix", "sdk-matrix/matrix.py")


def results(overrides=None):
    """A result per js-stellar-sdk release: 'pass' unless overridden, e.g. {"17.2.0": "mishandled"}."""
    r = {v: "pass" for v in mx.JS_RELEASES}
    r.update(overrides or {})
    return r


class JsCell(unittest.TestCase):
    def test_passes_everywhere(self):
        self.assertEqual(mx.js_cell(results()),
                         "17.x: passes in 17.2.0, 17.2.1, 17.3.0, 17.4.0; 16.x: passes in 16.3.0, 16.4.1")

    def test_fixed_in_a_release(self):
        cell = mx.js_cell(results({"17.2.0": "mishandled", "17.2.1": "mishandled", "16.3.0": "mishandled"}))
        self.assertEqual(cell, "17.x: fixed in 17.3.0; 16.x: fixed in 16.4.1")

    def test_still_present_in_the_latest(self):
        cell = mx.js_cell(results({"17.4.0": "mishandled", "16.4.1": "mishandled"}))
        self.assertIn("17.x: **present in 17.4.0**", cell)
        self.assertIn("16.x: **present in 16.4.1**", cell)

    def test_a_release_that_could_not_run_is_named(self):
        cell = mx.js_cell(results({"17.2.0": "error"}))
        self.assertIn("(could not run on 17.2.0)", cell)

    def test_no_release_of_a_line_could_run(self):
        cell = mx.js_cell(results({"16.3.0": "error", "16.4.1": "error"}))
        self.assertIn("16.x: check could not run (16.3.0, 16.4.1)", cell)


class Render(unittest.TestCase):
    def test_committed_matrix_is_what_its_data_renders(self):
        data = json.loads((ROOT / "sdk-matrix/matrix.json").read_text())
        self.assertEqual(mx.render(data), (ROOT / "sdk-matrix/MATRIX.md").read_text(),
                         "MATRIX.md was edited by hand or matrix.json changed; rerun sdk-matrix/matrix.py")

    def test_one_row_per_class_and_a_column_per_decoder(self):
        data = {"versions": {s: "%s 1.2.3" % s for s in mx.COLUMNS}, "js_releases": mx.JS_RELEASES,
                "codec": [{"class": "Trailing bytes", "core": "0 of 3", "issues": "x#1",
                           "cells": {s: "0 of 3" for s in mx.COLUMNS}}],
                "semantic": [{"class": "Map key order", "entry": "testnet-1", "issues": "y#2",
                              "cells": {s: "not tested" for s in mx.COLUMNS}}]}
        text = mx.render(data)
        rows = [line for line in text.splitlines() if line.startswith("| Trailing bytes") or
                line.startswith("| Map key order")]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row.count("|"), len(mx.COLUMNS) + 4)
        self.assertIn("rs-stellar-xdr 1.2.3", text)


if __name__ == "__main__":
    unittest.main()
