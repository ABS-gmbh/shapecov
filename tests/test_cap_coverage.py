"""tools/cap_coverage.py --check: passes on the repository; fails when the evidence names a cell the
schema does not have, or when the generated table is stale."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT, call_main, load_module


def module():
    return load_module("cap_coverage_under_test", "tools/cap_coverage.py")


class CapCoverage(unittest.TestCase):
    def test_repository_passes(self):
        rc, out = call_main(module().main, "--check")
        self.assertEqual(rc, 0, out[-500:])
        self.assertIn("CAP COVERAGE OK", out)

    def corpus_copy(self, d):
        for name in ("manifest.json", "CAP-COVERAGE.md", "cell-protocols.json", "cap-coverage.json"):
            shutil.copyfile(ROOT / "corpus" / name, Path(d) / name)

    def run_on(self, d):
        m = module()
        m.CORPUS = Path(d)
        m.probe_hits = lambda manifest: {"trustline_authorized_to_maintain_liabilities": ["x"],
                                         "preauth_signer_removed_in_failed_tx": ["x"]}
        return call_main(m.main, "--check")

    def test_unknown_cell_fails(self):
        with tempfile.TemporaryDirectory() as d:
            self.corpus_copy(d)
            spec = json.load(open(os.path.join(d, "cap-coverage.json")))
            cap = next(c for c in spec["caps"] if "evidence" in c and c["evidence"].get("cells"))
            cap["evidence"]["cells"].append("arm:NoSuchUnion.NO_SUCH_ARM")
            json.dump(spec, open(os.path.join(d, "cap-coverage.json"), "w"))
            rc, out = self.run_on(d)
            self.assertEqual(rc, 1)
            self.assertIn("arm:NoSuchUnion.NO_SUCH_ARM is not a schema cell", out)

    def test_stale_table_fails(self):
        with tempfile.TemporaryDirectory() as d:
            self.corpus_copy(d)
            with open(os.path.join(d, "CAP-COVERAGE.md"), "a") as f:
                f.write("edited by hand\n")
            rc, out = self.run_on(d)
            self.assertEqual(rc, 1)
            self.assertIn("out of date", out)


if __name__ == "__main__":
    unittest.main()
