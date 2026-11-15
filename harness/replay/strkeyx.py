"""SEP-23 strkey helpers for the replay harness: raw bytes <-> strkey, with validation.

Builds on tools/strkey.py (CRC and encoding written from the spec, no Stellar SDK).
"raw" here means version byte followed by the key payload, which is also how
wallet-backend stores addresses in BYTEA columns.
"""
import base64
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
from strkey import crc16_xmodem  # noqa: E402

# version byte -> (letter, name)
KINDS = {6 << 3: ("G", "account"), 12 << 3: ("M", "muxed_account"), 19 << 3: ("T", "pre_auth_tx"),
         23 << 3: ("X", "hash_x"), 15 << 3: ("P", "signed_payload"), 2 << 3: ("C", "contract"),
         11 << 3: ("L", "liquidity_pool"), 1 << 3: ("B", "claimable_balance")}


def payload_problem(version, payload):
    """None if the payload is a legal one for this version byte, else why not."""
    if version not in KINDS:
        return "unknown version byte 0x%02x" % version
    name, n = KINDS[version][1], len(payload)
    if name in ("account", "pre_auth_tx", "hash_x", "contract", "liquidity_pool"):
        return None if n == 32 else "%s key must be 32 bytes, has %d" % (name, n)
    if name == "muxed_account":
        return None if n == 40 else "muxed account must be 32-byte key + 8-byte id, has %d bytes" % n
    if name == "claimable_balance":
        return None if n == 33 else "claimable balance must be 1 + 32 bytes, has %d" % n
    # signed payload: ed25519 (32) + length (4) + payload (1..64) padded to 4
    if n < 32 + 4 + 4:
        return "signed payload must be 32-byte key + 4-byte length + padded payload, has %d bytes" % n
    plen = struct.unpack(">I", payload[32:36])[0]
    if not 1 <= plen <= 64:
        return "signed payload length field is %d, must be 1..64" % plen
    if n != 36 + ((plen + 3) & ~3):
        return "signed payload is %d bytes, length field says %d" % (n, 36 + ((plen + 3) & ~3))
    if any(payload[36 + plen:]):
        return "signed payload padding is not zero"
    return None


def from_raw(raw):
    """Encode version byte + payload as a strkey, without judging validity."""
    return base64.b32encode(raw + struct.pack("<H", crc16_xmodem(raw))).decode().rstrip("=")


def to_raw(text):
    """Decode a strkey to version byte + payload. Raises ValueError if it is not a valid strkey."""
    pad = "=" * (-len(text) % 8)
    try:
        body = base64.b32decode(text + pad)
    except Exception as err:
        raise ValueError("not base32: %s" % err)
    if len(body) < 3:
        raise ValueError("too short")
    raw, crc = body[:-2], struct.unpack("<H", body[-2:])[0]
    if crc16_xmodem(raw) != crc:
        raise ValueError("checksum mismatch")
    if from_raw(raw) != text:
        raise ValueError("not in canonical form")
    problem = payload_problem(raw[0], raw[1:])
    if problem:
        raise ValueError(problem)
    return raw


def describe_stored(raw):
    """How a stored version-byte + payload value reads back.

    Returns (strkey_or_None, problem_or_None). `strkey` is what a reader that
    re-encodes the stored bytes gets; `problem` says why that string is not a
    valid address, if it is not.
    """
    if len(raw) < 2:
        return None, "stored value is %d byte(s)" % len(raw)
    text = from_raw(raw)
    return text, payload_problem(raw[0], raw[1:])
