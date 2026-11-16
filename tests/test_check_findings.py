"""RFP check 6: .github/scripts/check_findings.py, on a small synthetic repository."""
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import run_script, write_jsonl, write_tree

SCRIPT = ".github/scripts/check_findings.py"
BEGIN = ("<!-- findings-table:begin (generated from FINDINGS.json by .github/scripts/check_findings.py "
         "--write; do not edit by hand) -->")
END = "<!-- findings-table:end -->"
C = "c" * 40   # a pre-fix commit with a claimed sighting
D = "d" * 40   # a commit where a failure is labelled with an issue


def record(**kw):
    r = {"id": "F1", "kind": "found", "title": "Decoder accepts trailing bytes", "component": "sdk: decode",
         "severity": "S3", "caps": [], "caps_none_reason": "codec level",
         "reproduction": {"generated_case": "T/trailing0", "runner": "java"},
         "upstream": ["https://github.com/o/r/issues/1"], "first_reported_by": "ShapeCov",
         "reported": "2026-11-14", "status": "open", "labels": ["o/r#1"]}
    r.update(kw)
    return r


def records():
    return [
        record(),
        record(id="S1", kind="sighting", title="Indexer halts", severity="S1", caps=["CAP-0040"],
               reproduction={"corpus_entry": "e1"}, upstream=["https://github.com/o/r/pull/2"],
               first_reported_by="maintainer", labels=["o/r#2 (half)"], rfp_sighting=2),
        record(id="L1", kind="linter", title="Unbounded walk", severity="S4",
               reproduction={"linter_report": "linter/results/wallet-backend-000000000000.json",
                             "accepted": ["walks without a cap"]},
               upstream=[], labels=[]),
    ]


class CheckFindings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.doc = {
            "severity_scale": [{"level": s, "name": s.lower(), "meaning": ""} for s in ("S1", "S2", "S3", "S4")],
            "kinds": {"found": "found by us", "sighting": "an RFP sighting", "linter": "a linter finding"},
            "findings": records(),
        }
        write_tree(self.dir, {
            "FINDINGS.md": "# Findings\n\n%s\n%s\n\nMore text.\n" % (BEGIN, END),
            "corpus/manifest.json": {"entries": [{"id": "e1"}]},
            "harness/replay/sightings.json": {"sightings": [
                {"entry": "e1", "commit": C, "adapter": "a", "expect": "mishandled", "issue": "o/r#2 (half)"}]},
            "harness/replay/adapters/a/known.json": {"rules": [{"issue": "o/r#1"}]},
            "harness/sightings/README.md": "| # | Sighting | Status | How |\n|---|---|---|---|\n"
                                           "| 2 | o/r#2 | reproduced | replay |\n| 3 | o/r#3 | not reproduced | - |\n",
            "linter/accepted/wallet-backend.json": {"accepted": [
                {"rule": "SC2", "file": "w.go", "message_contains": "walks without a cap", "upstream": None,
                 "reason": "real, low"}]},
            "linter/results/wallet-backend-000000000000.json": {"findings": []},
            "harness/replay/out-stellar-etl/results.jsonl": "",
        })
        write_jsonl(self.dir, "out/cases.jsonl", [{"id": "T/trailing0", "valid": False}])
        write_jsonl(self.dir, "out/divergences.jsonl", [
            {"id": "T/trailing0", "sdk": "java", "sdk_result": {"status": "ok"}, "reference": {"status": "err"}}])
        self.results = [
            {"entry_id": "e1", "commit": D, "adapter": "a", "input": "rpc",
             "oracle": {"known": {"o/r#1": 2}, "unexplained": []}},
            {"entry_id": "e1", "commit": C, "adapter": "a", "input": "rpc",
             "oracle": {"known": {}, "unexplained": ["a row is missing"]}},
        ]
        self.save()
        rc, out = self.run_check("--write")
        self.assertEqual(rc, 0, out)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        write_tree(self.dir, {"FINDINGS.json": self.doc})
        write_jsonl(self.dir, "harness/replay/out/results.jsonl", self.results)

    def run_check(self, *args):
        return run_script(SCRIPT, *args, cwd=self.dir)

    def assertFails(self, needle):
        rc, out = self.run_check()
        self.assertEqual(rc, 1, out)
        self.assertIn(needle, out)

    def test_complete_records_pass(self):
        rc, out = self.run_check()
        self.assertEqual(rc, 0, out)
        self.assertIn("oracle failures labelled with a filed issue that a record claims: 2", out)
        self.assertIn("failures that are a claimed RFP sighting at its pre-fix commit: 1", out)
        table = (self.dir / "FINDINGS.md").read_text()
        self.assertIn("| F1 | Decoder accepts trailing bytes |", table)
        self.assertIn("[o/r#1](https://github.com/o/r/issues/1)", table)
        self.assertTrue(table.endswith("More text.\n"))

    def test_missing_field_fails(self):
        del self.doc["findings"][0]["severity"]
        self.save()
        self.assertFails("F1: missing field 'severity'")

    def test_no_cap_and_no_reason_fails(self):
        del self.doc["findings"][0]["caps_none_reason"]
        self.save()
        self.assertFails("F1: no CAP and no caps_none_reason")

    def test_bad_cap_number_fails(self):
        self.doc["findings"][1]["caps"] = ["CAP-40"]
        self.save()
        self.assertFails("is not a CAP number")

    def test_reproduction_that_does_not_exist_fails(self):
        self.doc["findings"][1]["reproduction"] = {"corpus_entry": "e2"}
        self.save()
        self.assertFails("corpus entry 'e2' is not in corpus/manifest.json")

    def test_case_the_runner_rejects_fails(self):
        self.doc["findings"][0]["reproduction"]["runner"] = "go"
        self.save()
        self.assertFails("T/trailing0 does not reproduce")

    def test_label_no_record_claims_fails(self):
        self.results[0]["oracle"]["known"] = {"o/r#9": 1}
        self.save()
        self.assertFails("labelled 'o/r#9', which no record in FINDINGS.json claims")

    def test_unexplained_failure_fails(self):
        self.results[0]["oracle"]["unexplained"] = ["a balance differs"]
        self.save()
        self.assertFails("a balance differs")

    def test_label_must_be_among_upstream_links(self):
        self.doc["findings"][0]["upstream"] = ["https://github.com/o/r/issues/7"]
        self.save()
        self.assertFails("names an issue that is not among its upstream links")

    def test_reproduced_sighting_needs_a_record(self):
        del self.doc["findings"][1]["rfp_sighting"]
        self.save()
        self.assertFails("RFP sighting 2 is reproduced")

    def test_accepted_linter_finding_needs_a_record(self):
        self.doc["findings"][2]["reproduction"]["accepted"] = []
        self.save()
        self.assertFails("accepted wallet-backend linter finding SC2 'walks without a cap' maps to no record")

    def test_record_label_maps_an_unfiled_finding(self):
        self.results[0]["oracle"]["known"] = {"record:L1": 3}
        write_tree(self.dir, {"harness/replay/adapters/a/known.json": {"rules": [{"issue": "o/r#1"},
                                                                                 {"issue": "record:L1"}]}})
        self.save()
        rc, out = self.run_check()
        self.assertEqual(rc, 0, out)
        self.assertIn("failures mapped to a record with no filed issue (label record:<ID>): 3", out)
        self.results[0]["oracle"]["known"] = {"record:L9": 1}
        self.save()
        self.assertFails("label 'record:L9' names no record")

    def test_commit_links_are_accepted_but_short_shas_are_not(self):
        self.doc["kinds"]["fixed_upstream"] = "fixed upstream before ShapeCov"
        sha = "e2da4cadf2689380e9fc2dd0e1bce64191f411b8"
        self.doc["findings"].append(record(id="R1", kind="fixed_upstream", labels=[],
                                           upstream=["https://github.com/o/r/commit/" + sha]))
        self.save()
        rc, out = self.run_check("--write")
        self.assertEqual(rc, 0, out)
        self.assertIn("[o/r@e2da4ca](https://github.com/o/r/commit/%s)" % sha, (self.dir / "FINDINGS.md").read_text())
        self.doc["findings"][-1]["upstream"] = ["https://github.com/o/r/commit/e2da4ca"]
        self.save()
        self.assertFails("is not a GitHub issue, pull request or full-SHA commit URL")

    def test_stale_table_fails_and_write_fixes_it(self):
        self.doc["findings"][0]["status"] = "fixed"
        self.save()
        self.assertFails("the table differs from FINDINGS.json")
        rc, out = self.run_check("--write")
        self.assertEqual(rc, 0, out)
        self.assertIn("| fixed |", (self.dir / "FINDINGS.md").read_text())


class RepositoryRecords(unittest.TestCase):
    """The committed FINDINGS.json, without the replay results (those are check 6 in CI)."""

    def test_every_record_has_the_rfp_fields(self):
        from tests.helpers import ROOT
        doc = json.loads((ROOT / "FINDINGS.json").read_text())
        ids = [r["id"] for r in doc["findings"]]
        self.assertEqual(len(ids), len(set(ids)))
        for r in doc["findings"]:
            for k in ("id", "title", "component", "severity", "reproduction", "first_reported_by", "status"):
                self.assertTrue(r.get(k), "%s lacks %s" % (r.get("id"), k))
            self.assertTrue(r["caps"] or r.get("caps_none_reason"), r["id"])


if __name__ == "__main__":
    unittest.main()
