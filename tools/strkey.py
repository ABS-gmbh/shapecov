"""Minimal SEP-23 strkey encoding, written from the spec with no Stellar SDK.

Used to turn decoded XDR keys into the address strings an indexer is expected
to store, so that expectations in the corpus manifest do not come from the
software under test.
"""
import base64
import struct

VERSION = {"account": 6 << 3, "muxed": 12 << 3, "pre_auth_tx": 19 << 3, "hash_x": 23 << 3,
           "signed_payload": 15 << 3, "contract": 2 << 3}


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode(kind: str, payload: bytes) -> str:
    body = bytes([VERSION[kind]]) + payload
    return base64.b32encode(body + struct.pack("<H", crc16_xmodem(body))).decode().rstrip("=")


def signed_payload(ed25519_hex: str, payload_hex: str) -> str:
    """P... key: 32-byte key, 4-byte length, payload, zero padding to a multiple of 4."""
    p = bytes.fromhex(payload_hex)
    return encode("signed_payload",
                  bytes.fromhex(ed25519_hex) + struct.pack(">I", len(p)) + p + b"\0" * ((4 - len(p) % 4) % 4))


def account(ed25519_hex: str) -> str:
    return encode("account", bytes.fromhex(ed25519_hex))


def muxed(ed25519_hex: str, mux_id: int) -> str:
    """M... address: 32-byte key followed by the 8-byte ID."""
    return encode("muxed", bytes.fromhex(ed25519_hex) + struct.pack(">Q", mux_id))


def contract(hash_hex: str) -> str:
    return encode("contract", bytes.fromhex(hash_hex))


if __name__ == "__main__":
    # SEP-23 test vectors
    assert account("3f0c34bf93ad0d9971d04ccc90f705511c838aad9734a4a2fb0d7a03fc7fe89a") == \
        "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ"
    assert signed_payload("3f0c34bf93ad0d9971d04ccc90f705511c838aad9734a4a2fb0d7a03fc7fe89a",
                          "0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d") == \
        "PA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJUAAAAAOQCAQDAQCQMBYIBEFAWDANBYHRAEISCMKBKFQXDAMRUGY4DUAAAAFGBU"
    assert muxed("3f0c34bf93ad0d9971d04ccc90f705511c838aad9734a4a2fb0d7a03fc7fe89a", 9223372036854775808) == \
        "MA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVAAAAAAAAAAAAAJLK"
    print("strkey vectors ok")
