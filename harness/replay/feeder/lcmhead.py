"""Locate and decode the ledger header inside a LedgerCloseMeta without decoding the ledger.

Only the start of the entry is read, so the feeder never holds a whole ledger
in memory. The header is decoded with the repository's own schema-driven
decoder (tools/decode.py + schema/schema.json), so a protocol upgrade that
changes the header layout (as protocol 30 did with STELLAR_VALUE_SIGNED_MS) is
followed by regenerating the schema, not by editing this file. No Stellar SDK.

  head_of_b64_file(path) -> dict(v, seq, hash, close_time, protocol, header_b64)

`header_b64` is the LedgerHeaderHistoryEntry, which stellar-rpc returns as `headerXdr`.
"""
import base64
import json
import os
import struct
import sys

REPO = os.environ.get("SHAPECOV_REPO") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
import decode as xdrdecode  # noqa: E402

PREFIX_B64_CHARS = 8192  # 6144 bytes; a header is under 1500 even with 6 upgrades
_DECODER = None


class HeaderError(ValueError):
    pass


def _decoder():
    global _DECODER
    if _DECODER is None:
        with open(os.path.join(REPO, "schema", "schema.json")) as f:
            _DECODER = xdrdecode.Decoder(json.load(f))
    return _DECODER


def head(buf):
    d = _decoder()
    if len(buf) < 4:
        raise HeaderError("entry is shorter than 4 bytes")
    v = struct.unpack_from(">i", buf, 0)[0]
    if v not in (0, 1, 2):
        raise HeaderError("unknown LedgerCloseMeta case %d" % v)
    d.b, d.i, d.cells, d.path = buf, 4, {}, []
    try:
        if v != 0:
            d.named("LedgerCloseMetaExt")
        start = d.i
        entry = d.named("LedgerHeaderHistoryEntry")
        end = d.i
    except xdrdecode.XdrError as err:
        raise HeaderError("ledger header does not decode: %s" % err)
    h = entry["header"]
    return {"v": v, "seq": h["ledgerSeq"], "hash": entry["hash"], "close_time": h["scpValue"]["closeTime"],
            "protocol": h["ledgerVersion"], "header_start": start, "header_end": end}


def head_of_b64_file(path):
    """Read only the start of a one-line base64 file."""
    with open(path, "rb") as f:
        chunk = f.read(PREFIX_B64_CHARS).strip()
    chunk = chunk[:len(chunk) // 4 * 4]
    raw = base64.b64decode(chunk)
    h = head(raw)
    h["header_b64"] = base64.b64encode(raw[h["header_start"]:h["header_end"]]).decode()
    return h
