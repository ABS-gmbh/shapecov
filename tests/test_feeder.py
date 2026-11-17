"""harness/replay/feeder/feeder.py: a sequence is served as one window of consecutive ledgers, and
getLedgers returns each ledger's metadata in a well-formed response whose length is announced right."""
import base64
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "harness" / "replay" / "feeder"))
import feeder  # noqa: E402

PASS = "Test SDF Network ; September 2015"


def entry(d, eid, seq, payload):
    path = os.path.join(d, eid + ".b64")
    with open(path, "w") as f:
        f.write(base64.b64encode(payload).decode() + "\n")
    return {"id": eid, "path": path, "b64_len": feeder.b64_payload_len(path), "passphrase": PASS,
            "network_id": "00" * 32, "seq": seq, "hash": "%064x" % seq, "close_time": 1000 + seq,
            "protocol": 30, "header_b64": "SEVBRA=="}


class Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        cls.payloads = {"a": b"first ledger" * 3, "b": b"second ledger" * 5, "c": b"lone"}
        index = {"a": entry(d, "a", 41, cls.payloads["a"]), "b": entry(d, "b", 42, cls.payloads["b"]),
                 "c": entry(d, "c", 90, cls.payloads["c"])}
        with open(os.path.join(d, "sequences.json"), "w") as f:
            json.dump({"sequences": [{"id": "ab", "entries": ["b", "a"]}, {"id": "ac", "entries": ["a", "c"]}]}, f)
        cls.seqs, cls.problems = feeder.build_sequences(d, index)
        index.update(cls.seqs)
        feeder.LOG = io.StringIO()
        feeder.RPCHandler.index = index
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), feeder.RPCHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def call(self, name, method, params=None):
        body = json.dumps({"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}}).encode()
        req = urllib.request.Request("http://127.0.0.1:%d/rpc/%s" % (self.server.server_port, name), data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            self.assertEqual(len(raw), int(resp.headers["Content-Length"]))
            return json.loads(raw)

    def test_consecutive_members_make_a_sequence_and_a_gap_does_not(self):
        self.assertEqual(self.seqs["ab"]["members"], ["a", "b"])  # sorted by ledger
        self.assertNotIn("ac", self.seqs)
        self.assertIn("not consecutive", self.problems[0]["problem"])

    def test_health_spans_the_window(self):
        h = self.call("ab", "getHealth")["result"]
        self.assertEqual((h["oldestLedger"], h["latestLedger"]), (41, 42))

    def test_get_ledgers_serves_every_ledger_from_the_start(self):
        r = self.call("ab", "getLedgers", {"startLedger": 41, "pagination": {"limit": 10}})["result"]
        self.assertEqual([x["sequence"] for x in r["ledgers"]], [41, 42])
        self.assertEqual([base64.b64decode(x["metadataXdr"]) for x in r["ledgers"]],
                         [self.payloads["a"], self.payloads["b"]])
        self.assertEqual(r["cursor"], "42")

    def test_limit_and_cursor_page_through(self):
        r = self.call("ab", "getLedgers", {"startLedger": 41, "pagination": {"limit": 1}})["result"]
        self.assertEqual([x["sequence"] for x in r["ledgers"]], [41])
        r = self.call("ab", "getLedgers", {"pagination": {"cursor": r["cursor"], "limit": 1}})["result"]
        self.assertEqual([x["sequence"] for x in r["ledgers"]], [42])

    def test_a_start_outside_the_window_is_refused(self):
        self.assertIn("error", self.call("ab", "getLedgers", {"startLedger": 43}))
        self.assertIn("error", self.call("c", "getLedgers", {"startLedger": 89}))

    def test_a_sequence_released_in_steps(self):
        """POST /__release limits the window to the released ledgers; raising it serves the rest."""
        def release(last):
            req = urllib.request.Request("http://127.0.0.1:%d/__release?name=ab&last=%d" % (self.server.server_port, last),
                                         data=b"", method="POST")
            urllib.request.urlopen(req).read()
        try:
            release(41)
            self.assertEqual(self.call("ab", "getHealth")["result"]["latestLedger"], 41)
            self.assertIn("error", self.call("ab", "getLedgers", {"startLedger": 42}))
            release(42)
            r = self.call("ab", "getLedgers", {"startLedger": 42})["result"]
            self.assertEqual([x["sequence"] for x in r["ledgers"]], [42])
        finally:
            feeder.RELEASED.clear()

    def test_unreleased_lake_objects_are_hidden(self):
        feeder.RELEASED["ab"] = 41
        try:
            self.assertTrue(feeder.hidden(*feeder.key_seq("ab/FFFFFFFF--0-63999/FFFFFFD5--42.xdr.zst")))
            self.assertFalse(feeder.hidden(*feeder.key_seq("ab/FFFFFFFF--0-63999/FFFFFFD6--41.xdr.zst")))
            self.assertFalse(feeder.hidden(*feeder.key_seq("ab/.config.json")))
            self.assertFalse(feeder.hidden(*feeder.key_seq("c/FFFFFFFF--0-63999/FFFFFFA5--90.xdr.zst")))
        finally:
            feeder.RELEASED.clear()

    def test_a_single_entry_is_still_a_one_ledger_window(self):
        r = self.call("c", "getLedgers", {"startLedger": 90})["result"]
        self.assertEqual([base64.b64decode(x["metadataXdr"]) for x in r["ledgers"]], [self.payloads["c"]])


if __name__ == "__main__":
    unittest.main()
