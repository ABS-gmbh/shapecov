"""Schema-driven strict XDR decoder.

Decodes bytes for any type in schema.json into plain Python values, with no
Stellar SDK involved. It is the counterpart of gen.py's encoder and is used to
produce and re-check the "expected decoded values" in the corpus manifest.

Strict means RFC 4506 strict: padding must be zero, bools and optional flags
must be 0 or 1, enum values and union discriminants must be declared, lengths
must respect declared maxima, and the whole input must be consumed.

Value model:
  int/uint/hyper/uhyper -> int          bool -> bool
  opaque -> lowercase hex string        string -> str, or {"$hex": ...} if not UTF-8
  enum -> member name                   struct -> {field: value}
  union -> {disc: LABEL, field: value}, where disc is the discriminant's own
           name in the XDR ("type", "v", ...) and LABEL is the case name, or
           the number for unions switched on an int. Void arms have only disc.
           This is the layout stellar-core's JSON output uses, so one path
           addresses the same value in both.
  optional -> None or the value         array -> list

Paths (used by the manifest) are dotted field names with [i] for array
elements, e.g. "v2.txProcessing[0].result.result.result.code".

Usage:
  decode.py schema.json TYPE (--b64 STR | --file F [--zstd]) [--cells] [--get PATH ...] [--find CELL]
"""
import argparse
import base64
import json
import re
import struct
import subprocess
import sys


class XdrError(ValueError):
    pass


class Decoder:
    def __init__(self, schema):
        self.types = schema["types"]

    def decode(self, root, data):
        self.b, self.i = data, 0
        self.cells = {}     # cell -> first path where it was seen
        self.path = []
        v = self.named(root)
        if self.i != len(self.b):
            raise XdrError(f"{len(self.b) - self.i} trailing byte(s)")
        return v

    # ---- primitives
    def take(self, n):
        if self.i + n > len(self.b):
            raise XdrError(f"truncated at {self.here() or '<root>'}")
        s = self.b[self.i:self.i + n]
        self.i += n
        return s

    def u32(self):
        return struct.unpack(">I", self.take(4))[0]

    def i32(self):
        return struct.unpack(">i", self.take(4))[0]

    def pad(self, n):
        p = (4 - n % 4) % 4
        if any(self.take(p)):
            raise XdrError(f"non-zero padding at {self.here()}")

    def here(self):
        return "".join(self.path).lstrip(".")

    # ---- type walk
    def t(self, t):
        r = t["r"]
        if r == "int":
            return self.i32()
        if r == "uint":
            return self.u32()
        if r == "hyper":
            return struct.unpack(">q", self.take(8))[0]
        if r == "uhyper":
            return struct.unpack(">Q", self.take(8))[0]
        if r == "bool":
            v = self.u32()
            if v > 1:
                raise XdrError(f"bool is {v} at {self.here()}")
            return bool(v)
        if r in ("opaque", "string"):
            if "fixed" in t:
                n = t["fixed"]
            else:
                n = self.u32()
                if t["max"] is not None and n > t["max"]:
                    raise XdrError(f"length {n} over max {t['max']} at {self.here()}")
            raw = self.take(n)
            self.pad(n)
            if r == "opaque":
                return raw.hex()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return {"$hex": raw.hex()}
        if r == "opt":
            flag = self.u32()
            if flag > 1:
                raise XdrError(f"optional flag is {flag} at {self.here()}")
            return self.t(t["of"]) if flag else None
        if r == "array":
            if "fixed" in t:
                n = t["fixed"]
            else:
                n = self.u32()
                if t["max"] is not None and n > t["max"]:
                    raise XdrError(f"length {n} over max {t['max']} at {self.here()}")
            out = []
            for k in range(n):
                self.path.append(f"[{k}]")
                out.append(self.t(t["of"]))
                self.path.pop()
            return out
        return self.named(t["name"])

    def named(self, name):
        d = self.types[name]
        k = d["k"]
        if k == "typedef":
            return self.t(d["t"])
        if k == "enum":
            v = self.i32()
            for m, mv in d["members"]:
                if mv == v:
                    self.cells.setdefault(f"enum:{name}.{m}", self.here())
                    return m
            raise XdrError(f"unknown {name} value {v} at {self.here()}")
        if k == "struct":
            out = {}
            for fname, ft in d["fields"]:
                self.path.append("." + fname)
                out[fname] = self.t(ft)
                self.path.pop()
            return out
        # union
        case = self.i32()
        arm, label = None, None
        for a in d["arms"]:
            if case in a["cases"]:
                arm, label = a, a["labels"][a["cases"].index(case)]
                break
        if arm is None:
            if d["default"] is None:
                raise XdrError(f"unknown {name} discriminant {case} at {self.here()}")
            arm, label = d["default"], str(case)
        else:
            self.cells.setdefault(f"arm:{name}.{label}", self.here())
        out = {d["discName"]: int(label) if label.lstrip("-").isdigit() else label}
        if arm["t"] is not None:
            self.path.append("." + arm["name"])
            out[arm["name"]] = self.t(arm["t"])
            self.path.pop()
        return out


TOKEN = re.compile(r"\.?([A-Za-z_$][A-Za-z0-9_$]*)|\[(\d+)\]")


def get(value, path):
    """Follow a manifest path into a decoded value."""
    pos = 0
    while pos < len(path):
        m = TOKEN.match(path, pos)
        if not m:
            raise KeyError(f"bad path syntax at {path[pos:]!r}")
        pos = m.end()
        if m.group(1) is not None:
            if not isinstance(value, dict) or m.group(1) not in value:
                raise KeyError(f"no field {m.group(1)!r} in {path!r}")
            value = value[m.group(1)]
        else:
            value = value[int(m.group(2))]
    return value


def read_input(a):
    if a.b64 is not None:
        return base64.b64decode(a.b64, validate=True)
    if a.zstd:
        return subprocess.run(["zstd", "-dc", a.file], check=True, capture_output=True).stdout
    raw = open(a.file, "rb").read()
    if a.file.endswith(".b64"):
        return base64.b64decode(raw.strip(), validate=True)
    return raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("schema"); ap.add_argument("type")
    ap.add_argument("--b64"); ap.add_argument("--file"); ap.add_argument("--zstd", action="store_true")
    ap.add_argument("--cells", action="store_true", help="print the schema cells this value exercises")
    ap.add_argument("--get", action="append", default=[], help="print the value at PATH")
    ap.add_argument("--find", action="append", default=[], help="print the first path where CELL occurs")
    a = ap.parse_args()
    dec = Decoder(json.load(open(a.schema)))
    v = dec.decode(a.type, read_input(a))
    if a.cells:
        for c in sorted(dec.cells):
            print(c)
    for c in a.find:
        print(c, "->", dec.cells.get(c))
    for p in a.get:
        print(p, "=", json.dumps(get(v, p)))
    if not (a.cells or a.get or a.find):
        json.dump(v, sys.stdout, indent=1)
        print()


if __name__ == "__main__":
    main()
