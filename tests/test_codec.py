"""tools/gen.py, tools/decode.py and tools/encode.py: generated valid cases round-trip byte for byte
through the strict decoder and the encoder; each fault class gen.py injects is rejected with its error."""
import json
import re
import sys
import unittest

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "tools"))
from decode import Decoder, XdrError  # noqa: E402
from encode import Encoder  # noqa: E402
from gen import FAULTS, Gen  # noqa: E402

SCHEMA = json.load(open(ROOT / "schema" / "schema.json"))
ROOTS = ["TransactionEnvelope", "TransactionResult", "LedgerEntry", "LedgerKey", "SCVal", "Asset",
         "MuxedAccount", "SorobanAuthorizationEntry", "TransactionMeta", "ContractEvent"]
ERROR = {  # fault -> what tools/decode.py says
    "bool_not_01": r"^bool is \d+",
    "opt_flag_not_01": r"^optional flag is \d+",
    "enum_unknown": r"^unknown \w+ (value|discriminant)",
    "pad_nonzero": r"^non-zero padding",
    "len_over_max": r"over max",
    # An absurd length on an unbounded vector: the decoder reads element by element, so it stops at
    # the first element that runs out of bytes or reads as garbage. Any strict error will do.
    "len_huge": r".",
    "trailing": r"trailing byte",
    "truncated": r"^truncated",
}


class RoundTrip(unittest.TestCase):
    def test_valid_cases_round_trip(self):
        g, dec, enc = Gen(SCHEMA, "unit-tests"), Decoder(SCHEMA), Encoder(SCHEMA)
        n = 0
        for root in ROOTS:
            for i in range(4):
                data = g.make(root, "v%d" % i)
                with self.subTest(root=root, case=i):
                    value = dec.decode(root, data)
                    self.assertEqual(enc.encode(root, value), data)
                    n += 1
        self.assertEqual(n, len(ROOTS) * 4)

    def test_committed_cases_round_trip(self):
        """A fixed sample of out/cases.jsonl, the cases the conformance runners are given."""
        import base64
        dec, enc = Decoder(SCHEMA), Encoder(SCHEMA)
        seen = 0
        with open(ROOT / "out" / "cases.jsonl") as f:
            for i, line in enumerate(f):
                if i % 97:
                    continue
                c = json.loads(line)
                if not c["valid"]:
                    continue
                data = base64.b64decode(c["b64"])
                with self.subTest(c["id"]):
                    self.assertEqual(enc.encode(c["type"], dec.decode(c["type"], data)), data)
                seen += 1
        self.assertGreater(seen, 20)


class Faults(unittest.TestCase):
    def test_each_fault_class_is_rejected_with_its_error(self):
        import random
        g, dec = Gen(SCHEMA, "unit-tests"), Decoder(SCHEMA)
        for kind in FAULTS:
            with self.subTest(kind):
                hits = 0
                for root in ROOTS:
                    if kind in ("trailing", "truncated"):
                        data = g.make(root, "f0", kind, 0)
                    else:
                        g.make(root, "f0", kind, -1)
                        if g.opps == 0:
                            continue
                        data = g.make(root, "f0", kind, random.Random(kind + root).randrange(g.opps))
                    if g.injected is None:
                        continue
                    with self.assertRaises(XdrError) as cm:
                        dec.decode(root, data)
                    self.assertRegex(str(cm.exception), ERROR[kind])
                    hits += 1
                self.assertGreater(hits, 0, "no root offered a place for %s" % kind)

    def test_errors_name_where(self):
        dec = Decoder(SCHEMA)
        with self.assertRaises(XdrError) as cm:
            dec.decode("Asset", bytes.fromhex("00000009"))
        self.assertTrue(re.search(r"unknown \w+ discriminant 9", str(cm.exception)), str(cm.exception))
        with self.assertRaises(XdrError) as cm:
            dec.decode("Asset", bytes.fromhex("0000000000"))
        self.assertIn("trailing", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
