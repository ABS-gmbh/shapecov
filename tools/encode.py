"""Schema-driven XDR encoder for hand-written values.

Takes the value model that decode.py produces (see its docstring) and writes
canonical XDR. Used to build synthetic corpus entries from a readable value
instead of hand-assembled bytes. Shares no code with any Stellar SDK.

Usage: encode.py schema.json TYPE value.json   -> prints base64
"""
import base64
import json
import struct
import sys


class Encoder:
    def __init__(self, schema):
        self.types = schema["types"]

    def encode(self, root, value):
        self.out = bytearray()
        self.named(root, value, root)
        return bytes(self.out)

    def raw(self, t, v, where):
        if t["r"] == "opaque":
            b = bytes.fromhex(v)
        elif isinstance(v, dict):
            b = bytes.fromhex(v["$hex"])
        else:
            b = v.encode("utf-8")
        if "fixed" in t:
            if len(b) != t["fixed"]:
                raise ValueError(f"{where}: need {t['fixed']} bytes, got {len(b)}")
        else:
            if t["max"] is not None and len(b) > t["max"]:
                raise ValueError(f"{where}: {len(b)} bytes over max {t['max']}")
            self.out += struct.pack(">I", len(b))
        self.out += b + b"\0" * ((4 - len(b) % 4) % 4)

    def t(self, t, v, where):
        r = t["r"]
        if r in ("int", "uint", "hyper", "uhyper"):
            self.out += struct.pack({"int": ">i", "uint": ">I", "hyper": ">q", "uhyper": ">Q"}[r], v)
        elif r == "bool":
            self.out += struct.pack(">I", 1 if v else 0)
        elif r in ("opaque", "string"):
            self.raw(t, v, where)
        elif r == "opt":
            self.out += struct.pack(">I", 0 if v is None else 1)
            if v is not None:
                self.t(t["of"], v, where)
        elif r == "array":
            if "fixed" in t:
                if len(v) != t["fixed"]:
                    raise ValueError(f"{where}: need {t['fixed']} elements")
            else:
                if t["max"] is not None and len(v) > t["max"]:
                    raise ValueError(f"{where}: {len(v)} elements over max {t['max']}")
                self.out += struct.pack(">I", len(v))
            for k, e in enumerate(v):
                self.t(t["of"], e, f"{where}[{k}]")
        else:
            self.named(t["name"], v, where)

    def named(self, name, v, where):
        d = self.types[name]
        k = d["k"]
        if k == "typedef":
            self.t(d["t"], v, where)
        elif k == "enum":
            vals = dict(d["members"])
            if v not in vals:
                raise ValueError(f"{where}: {v!r} is not a member of {name}")
            self.out += struct.pack(">i", vals[v])
        elif k == "struct":
            extra = set(v) - {f for f, _ in d["fields"]}
            if extra:
                raise ValueError(f"{where}: unknown field(s) {sorted(extra)} for {name}")
            for fname, ft in d["fields"]:
                if fname not in v:
                    raise ValueError(f"{where}: missing field {fname} of {name}")
                self.t(ft, v[fname], f"{where}.{fname}")
        else:
            label = str(v[d["discName"]])
            for a in d["arms"]:
                if label in a["labels"]:
                    arm, case = a, a["cases"][a["labels"].index(label)]
                    break
            else:
                if d["default"] is None:
                    raise ValueError(f"{where}: {label!r} is not an arm of {name}")
                arm, case = d["default"], int(label)
            self.out += struct.pack(">i", case)
            if arm["t"] is not None:
                self.t(arm["t"], v[arm["name"]], f"{where}.{arm['name']}")


if __name__ == "__main__":
    enc = Encoder(json.load(open(sys.argv[1])))
    print(base64.b64encode(enc.encode(sys.argv[2], json.load(open(sys.argv[3])))).decode())
