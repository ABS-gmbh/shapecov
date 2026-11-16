"""quickcheck.py: the Python-only path through the RFP checks."""
import sys
import unittest

from tests.helpers import ROOT, call_main, load_module

qc = load_module("quickcheck", "quickcheck.py")
try:
    import jsonschema  # noqa: F401  quickcheck.main() needs it
    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False


class Quickcheck(unittest.TestCase):
    def test_every_check_names_a_script_that_exists(self):
        for check, what, cmd in qc.CHECKS:
            self.assertEqual(cmd[0], qc.PY, check)
            if cmd[1] == "-m":
                self.assertEqual(cmd[2], "unittest", check)
            else:
                self.assertTrue((ROOT / cmd[1]).is_file(), "%s: %s does not exist" % (check, cmd[1]))
            self.assertTrue(what, check)

    def test_every_check_needs_no_docker_or_network(self):
        for check, _, cmd in qc.CHECKS:
            joined = " ".join(cmd)
            for flag in ("--core", "--sdks", "--goldens", "--sdk-checks", "docker"):
                self.assertNotIn(flag, joined, check)

    def test_checks_it_does_not_rerun_name_a_ci_job(self):
        self.assertTrue(qc.NOT_RERUN)
        for check, what, job in qc.NOT_RERUN:
            self.assertRegex(job, r"\b(ci|replay)\b", check)

    @unittest.skipUnless(HAVE_JSONSCHEMA, "quickcheck needs jsonschema (pip install jsonschema)")
    def test_all_passing_returns_0(self):
        old = qc.CHECKS
        qc.CHECKS = [("A", "always passes", [sys.executable, "-c", "pass"])]
        try:
            rc, out = call_main(qc.main)
        finally:
            qc.CHECKS = old
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS  A", out)
        self.assertIn("1 of 1 checks passed", out)

    @unittest.skipUnless(HAVE_JSONSCHEMA, "quickcheck needs jsonschema (pip install jsonschema)")
    def test_one_failing_check_returns_1_and_shows_its_error(self):
        old = qc.CHECKS
        qc.CHECKS = [("A", "passes", [sys.executable, "-c", "pass"]),
                     ("B", "fails", [sys.executable, "-c", "import sys; print('ERROR: row 3 differs'); sys.exit(1)"])]
        try:
            rc, out = call_main(qc.main)
        finally:
            qc.CHECKS = old
        self.assertEqual(rc, 1, out)
        self.assertIn("FAIL  B", out)
        self.assertIn("ERROR: row 3 differs", out)
        self.assertIn("1 of 2 checks passed", out)


if __name__ == "__main__":
    unittest.main()
