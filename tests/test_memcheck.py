"""harness/replay/memcheck.py: the pass/fail rule, and the synthetic corpus it serves. The Docker run
itself is CI's memory job; this needs neither Docker nor a network."""
import json
import os
import tempfile
import unittest

from tests.helpers import load_module

memcheck = load_module("memcheck_under_test", "harness/replay/memcheck.py")


class Verdict(unittest.TestCase):
    def test_within_budget_and_everything_served(self):
        self.assertTrue(memcheck.verdict(41.5, 64, {"rpc": 900, "s3": 900, "gcs": 0}, 900))

    def test_over_budget_fails(self):
        self.assertFalse(memcheck.verdict(64.1, 64, {"rpc": 900, "s3": 900}, 900))

    def test_a_ledger_not_served_fails(self):
        self.assertFalse(memcheck.verdict(10, 64, {"rpc": 899, "s3": 900}, 900))
        self.assertFalse(memcheck.verdict(10, 64, {"rpc": 900}, 900))


class SyntheticCorpus(unittest.TestCase):
    def test_reaches_the_target_with_unique_ids(self):
        with tempfile.TemporaryDirectory() as d:
            n, size = memcheck.build_corpus(d, 3 << 20)
            self.assertGreaterEqual(size, 3 << 20)
            entries = json.load(open(os.path.join(d, "manifest.json")))["entries"]
            self.assertEqual(len(entries), n)
            self.assertEqual(len({e["id"] for e in entries}), n)
            self.assertEqual(sum(os.path.getsize(os.path.join(d, e["file"])) for e in entries), size)


if __name__ == "__main__":
    unittest.main()
