"""tools/corpus_check.py: an entry as committed passes the static checks; the same entry with one
thing wrong fails the check that covers it."""
import base64
import copy
import contextlib
import io
import json
import sys
import unittest

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import corpus_check  # noqa: E402
from decode import Decoder  # noqa: E402
from encode import Encoder  # noqa: E402
from gen import all_cells  # noqa: E402

SCHEMA = json.load(open(ROOT / "schema" / "schema.json"))
NEW_CELLS = all_cells(SCHEMA) - all_cells(json.load(open(ROOT / "schema" / "schema-v28.0.json")))
MANIFEST = json.load(open(ROOT / "corpus" / "manifest.json"))
CAPS = json.load(open(ROOT / "corpus" / "caps.json"))["caps"]


def run(entry, raw):
    """-> (failures, printed lines) of the static checks on one entry."""
    rep, out = corpus_check.Report(), io.StringIO()
    with contextlib.redirect_stdout(out):
        corpus_check.static_checks(entry, raw, Decoder(SCHEMA), Encoder(SCHEMA), NEW_CELLS,
                                   MANIFEST["xdr_schema"]["protocol_version"], rep, {"caps": CAPS})
    return rep.failures, [ln.strip() for ln in out.getvalue().splitlines() if ln.strip().startswith("FAIL")]


class StaticChecks(unittest.TestCase):
    def entry(self, eid):
        e = next(x for x in MANIFEST["entries"] if x["id"] == eid)
        return copy.deepcopy(e), base64.b64decode((ROOT / "corpus" / e["file"]).read_text().strip())

    def test_committed_entries_pass(self):
        for eid in ("localcore-classic-p22-3", "testnet-4437357-signed-payload-signer",
                    "localcore-planted-auth-5"):
            with self.subTest(eid):
                e, raw = self.entry(eid)
                self.assertEqual(run(e, raw), (0, []))

    def test_a_changed_byte_fails_the_hash(self):
        e, raw = self.entry("localcore-classic-p22-3")
        bad = bytearray(raw)
        bad[-1] ^= 1
        failures, lines = run(e, bytes(bad))
        self.assertGreater(failures, 0)
        self.assertTrue(any("sha256" in ln for ln in lines), lines)

    def test_a_wrong_expected_value_fails(self):
        e, raw = self.entry("localcore-classic-p22-3")
        e["expected"]["decoded"][0]["value"] = "not what the bytes say"
        failures, lines = run(e, raw)
        self.assertEqual(failures, 1)
        self.assertIn("expected decoded values", lines[0])

    def test_a_wrong_source_record_fails(self):
        e, raw = self.entry("testnet-4437357-signed-payload-signer")
        e["source"]["ledger_seq"] += 1
        failures, lines = run(e, raw)
        self.assertEqual(failures, 1)
        self.assertIn("source record", lines[0])

    def test_a_missing_cell_fails(self):
        e, raw = self.entry("localcore-classic-p22-3")
        e["cells"] = e["cells"][1:]
        self.assertGreater(run(e, raw)[0], 0)


if __name__ == "__main__":
    unittest.main()
