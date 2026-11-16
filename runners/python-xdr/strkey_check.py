#!/usr/bin/env python3
"""stellar-strkey (lightsail-network/py-stellar-strkey) against SEP-23.

  strkey_check.py SEP23_MARKDOWN          run with the Python that has stellar-strkey installed

Two sets of cases:
  sep23      every strkey in SEP-23's "Valid test cases" and "Invalid test cases" sections
  generated  for every strkey type: a valid key, then mutations of it built from raw bytes with a
             correct checksum, so only the property under test is wrong: payload one byte short or
             long, each non-zero algorithm value, non-zero unused bits in the last symbol, lower
             case, `=` padding; for signed payloads, length fields that disagree with the payload,
             zero and over-long payloads and non-zero padding; for claimable balances, a type byte
             other than 0.

The expected verdict comes from harness/replay/strkeyx.py, written from SEP-23 with no Stellar SDK.
A case passes when stellar-strkey accepts exactly the valid strkeys and, for those, re-encodes the
decoded value to the same string. Prints one line per disagreement and a summary.
"""
import base64
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "harness", "replay"))
import stellar_strkey as S  # noqa: E402
import strkeyx  # noqa: E402

BASE = {"G": 6, "M": 12, "S": 18, "T": 19, "X": 23, "P": 15, "C": 2, "L": 11, "B": 1, "W": 22}


def encode(version, payload):
    return strkeyx.from_raw(bytes([version]) + payload)


def expected_ok(text):
    try:
        strkeyx.to_raw(text)
        return True
    except ValueError:
        return False


def py_decode(text):
    """(accepted, re-encoded string or error). Private keys go through their own class."""
    try:
        v = S.Ed25519PrivateKey.from_string(text) if text[:1] == "S" else S.parse(text)
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)
    try:
        # A private key's str() is "<redacted>" by design; reveal() is its explicit encoder.
        return True, v.reveal() if isinstance(v, S.Ed25519PrivateKey) else str(v)
    except Exception as e:  # noqa: BLE001
        return True, "re-encode failed: %s: %s" % (type(e).__name__, e)


def sep23_cases(path):
    text = open(path).read()
    valid = text[text.index("### Valid test cases"):text.index("### Invalid test cases")]
    invalid = text[text.index("### Invalid test cases"):]
    invalid = invalid[:invalid.index("```")] if "```" in invalid else invalid
    pick = lambda s: re.findall(r"`([GMSTXPCLBW][A-Z2-7=]{10,})`", s)
    return [("sep23 valid", s) for s in pick(valid)] + [("sep23 invalid", s) for s in pick(invalid)]


def generated_cases():
    key = bytes(range(1, 33))
    out = []
    for letter, base in BASE.items():
        v = base << 3
        if letter in ("M", "W"):
            payloads = {"valid": key + struct.pack(">Q", 0), "valid id max": key + b"\xff" * 8}
        elif letter == "P":
            payloads = {"valid 1-byte payload": key + struct.pack(">I", 1) + b"\x01\0\0\0",
                        "valid 64-byte payload": key + struct.pack(">I", 64) + bytes(64),
                        "length 0": key + struct.pack(">I", 0),
                        "length 65": key + struct.pack(">I", 65) + bytes(68),
                        "length says 4, 8 bytes follow": key + struct.pack(">I", 4) + bytes(8),
                        "length says 8, 4 bytes follow": key + struct.pack(">I", 8) + bytes(4),
                        "non-zero padding": key + struct.pack(">I", 1) + b"\x01\0\0\x01",
                        "no padding": key + struct.pack(">I", 1) + b"\x01"}
        elif letter == "B":
            payloads = {"valid": b"\0" + key, "type byte 1": b"\1" + key, "type byte 255": b"\xff" + key}
        else:
            payloads = {"valid": key}
        for name, p in payloads.items():
            out.append(("%s %s" % (letter, name), encode(v, p)))
        good = next(p for n, p in payloads.items() if n.startswith("valid"))
        out.append(("%s one byte short" % letter, encode(v, good[:-1])))
        out.append(("%s one byte long" % letter, encode(v, good + b"\0")))
        for alg in range(1, 8):
            out.append(("%s algorithm %d" % (letter, alg), encode(v | alg, good)))
        s = encode(v, good)
        out.append(("%s lower case" % letter, s.lower()))
        out.append(("%s with = padding" % letter, s + "=" * ((-len(s) % 8) or 8)))
        # Non-zero unused bits: same bytes and checksum, last symbol changed in its unused bits.
        raw = base64.b32decode(s + "=" * (-len(s) % 8))
        nbits = len(raw) * 8
        unused = len(s) * 5 - nbits
        if unused:
            alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
            last = alphabet.index(s[-1])
            out.append(("%s non-zero unused bits" % letter, s[:-1] + alphabet[last | 1]))
    out.append(("unknown version byte 0x50", encode(0x50, key)))
    return out


def main():
    cases = sep23_cases(sys.argv[1]) + generated_cases()
    stats = {"cases": 0, "agree": 0}
    bad = []
    for label, text in cases:
        stats["cases"] += 1
        want = expected_ok(text) if not label.startswith("sep23") else label == "sep23 valid"
        got, detail = py_decode(text)
        ok = got == want and (not got or detail == text)
        if ok:
            stats["agree"] += 1
        else:
            bad.append({"case": label, "strkey": text, "expected": "accept" if want else "reject",
                        "stellar_strkey": ("accepts" if got else "rejects"), "detail": detail})
    for b in bad:
        print(json.dumps(b))
    print(json.dumps(dict(stats, disagree=len(bad))))


if __name__ == "__main__":
    main()
