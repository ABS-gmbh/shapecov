"""tools/rebind_token_wasm.py: the module is deterministic, well formed, and its spec declares the SEP-41
interface wallet-backend's classifier requires (internal/services/sep41/validator.go)."""
import sys
import unittest

from tests.helpers import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import rebind_token_wasm as r  # noqa: E402

SEP41 = ["balance", "allowance", "decimals", "name", "symbol", "approve", "transfer", "transfer_from", "burn",
         "burn_from"]


def sections(b):
    """(id, custom name or None, body) for every section of a wasm module."""
    out, i = [], 8
    while i < len(b):
        sid = b[i]
        n, s, j = 0, 0, i + 1
        while True:
            x = b[j]; j += 1; n |= (x & 0x7F) << s; s += 7
            if x < 0x80:
                break
        body = b[j:j + n]
        name = None
        if sid == 0:
            ln = body[0]
            name, body = body[1:1 + ln].decode(), body[1 + ln:]
        out.append((sid, name, body))
        i = j + n
    return out


class Module(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(r.build(), r.build())
        self.assertNotEqual(r.build(), r.build(sep41=False))

    def test_header_and_sections(self):
        b = r.build()
        self.assertEqual(b[:8], b"\0asm\x01\0\0\0")
        self.assertEqual([s[0] for s in sections(b)], [1, 2, 3, 5, 7, 10, 0, 0])

    def test_spec_declares_sep41_and_the_plain_variant_does_not(self):
        spec = dict((n, body) for sid, n, body in sections(r.build()) if sid == 0)["contractspecv0"]
        plain = dict((n, body) for sid, n, body in sections(r.build(False)) if sid == 0)["contractspecv0"]
        for fn in SEP41 + ["mint", "upgrade"]:
            self.assertIn(r.xstr(fn), spec)
        for fn in SEP41:
            self.assertNotIn(r.xstr(fn), plain)

    def test_symbol_small(self):
        # SymbolSmall packs six bits per character above an 8-bit tag of 14
        self.assertEqual(r.symbol_small("a") & 0xFF, 14)
        self.assertEqual(r.symbol_small("a") >> 8, 38)


if __name__ == "__main__":
    unittest.main()
