"""Schema-driven XDR generator.

Walks the parsed Stellar XDR schema and emits, for every root type:
  * valid values, biased toward boundaries (extreme integers, empty and
    maximum-length vectors, non-UTF-8 strings, every union arm);
  * invalid values, each carrying exactly one named fault that RFC 4506
    decoders must reject (bad bool, bad optional flag, unknown enum value,
    non-zero padding, length over the declared maximum, trailing bytes,
    truncation, absurd length prefix).

Encoding is done here, from the schema, with no Stellar SDK involved, so the
generator shares no code with any decoder under test.

Usage: gen.py schema.json out.jsonl [--valid N] [--faulty M] [--seed S] [--roots A,B]
"""
import argparse
import base64
import json
import random
import struct

FAULTS = ["bool_not_01", "opt_flag_not_01", "enum_unknown", "pad_nonzero",
          "len_over_max", "len_huge", "trailing", "truncated"]

I32 = [0, 1, -1, 2**31 - 1, -2**31]
U32 = [0, 1, 2**32 - 1, 2**31]
I64 = [0, 1, -1, 2**63 - 1, -2**63, 2**53, 2**53 + 1, -(2**53) - 1]
U64 = [0, 1, 2**64 - 1, 2**63, 2**53 + 1]


class Gen:
    def __init__(self, schema, seed, max_depth=14, max_nodes=300):
        self.s, self.types = schema, schema["types"]
        self.max_depth, self.max_nodes = max_depth, max_nodes
        self.mind = self._min_depths()
        self.seed = seed

    # ---- termination analysis: minimal nesting needed to finish a value
    def _min_depths(self):
        INF = 10**6
        mind = {n: INF for n in self.types}

        def ref(t):
            r = t["r"]
            if r == "ref":
                return mind[t["name"]]
            if r == "array":
                return ref(t["of"]) if t.get("fixed") else 0
            return 0

        changed = True
        while changed:
            changed = False
            for n, d in self.types.items():
                k = d["k"]
                if k == "enum":
                    v = 0
                elif k == "typedef":
                    v = ref(d["t"])
                elif k == "struct":
                    v = 1 + max([ref(t) for _, t in d["fields"]] or [0])
                else:
                    arms = [0 if a["t"] is None else ref(a["t"]) for a in d["arms"]]
                    if d["default"] is not None:
                        arms.append(0 if d["default"]["t"] is None else ref(d["default"]["t"]))
                    v = 1 + min(arms)
                if v < mind[n]:
                    mind[n] = v
                    changed = True
        self._ref_mind = ref
        return mind

    # ---- one case
    def make(self, root, case_seed, fault=None, fault_index=None):
        self.rng = random.Random(f"{self.seed}:{root}:{case_seed}")
        self.out = bytearray()
        self.nodes = 0
        self.cells, self.tags = set(), set()
        self.path = [root]
        self.fault, self.fault_index = fault, fault_index
        self.opps = 0          # opportunities seen for the requested fault kind
        self.injected = None   # {"kind","path","site"}
        self.t_ref({"r": "ref", "name": root}, 0)
        if fault == "trailing":
            n = self.rng.choice([1, 2, 3, 4, 4, 8])
            self.out += bytes(self.rng.randrange(256) for _ in range(n))
            self.injected = {"kind": "trailing", "path": root, "site": f"+{n} bytes"}
        elif fault == "truncated" and len(self.out) > 0:
            n = self.rng.choice([1, 2, 3, 4])
            n = min(n, len(self.out))
            del self.out[-n:]
            self.injected = {"kind": "truncated", "path": root, "site": f"-{n} bytes"}
        return bytes(self.out)

    def want(self, kind):
        """True exactly once: at the chosen opportunity for the requested fault kind."""
        if self.fault != kind or self.injected is not None:
            return False
        hit = self.opps == self.fault_index
        self.opps += 1
        return hit

    def mark(self, kind, site):
        self.injected = {"kind": kind, "path": ".".join(self.path), "site": site}

    def tight(self, depth):
        return depth >= self.max_depth or self.nodes >= self.max_nodes

    # ---- primitives
    def u32(self, v):
        self.out += struct.pack(">I", v & 0xFFFFFFFF)

    def pad(self, n):
        p = (4 - n % 4) % 4
        if p and self.want("pad_nonzero"):
            self.out += bytes([self.rng.randrange(1, 256)] + [0] * (p - 1))
            self.mark("pad_nonzero", f"{p} pad byte(s)")
        else:
            self.out += b"\0" * p

    def length(self, n, mx, what):
        """Write a length prefix; may inject len_huge. Returns False if the body must be skipped."""
        if self.want("len_huge"):
            v = self.rng.choice([0xFFFFFFFF, 0x7FFFFFFF, 0x80000000, 0xFFFFFFF0])
            self.u32(v)
            self.mark("len_huge", f"{what} length {v:#x}")
            return False
        self.u32(n)
        return True

    def bytes_body(self, kind, t, depth):
        if "fixed" in t:
            n = t["fixed"]
            self.out += self.rand_bytes(n, kind)
            self.pad(n)
            return
        mx = t["max"]
        cap = mx if mx is not None else 2**32 - 1
        over = mx is not None and mx + 1 <= 4096 and self.want("len_over_max")
        if over:
            n = mx + 1
            self.mark("len_over_max", f"{kind}<{mx}> with {n}")
        else:
            choices = [0, 1, 2, 3, 4, 5, 7, 8, 12, 32]
            if mx is not None and mx <= 4096:
                choices += [mx, mx, mx - 1]
            n = min(self.rng.choice(choices), cap)
            n = max(n, 0)
            if mx is not None and n == mx:
                self.cells.add(f"len:{'.'.join(self.path[-2:])}=max")
        self.cells.add(f"len:{'.'.join(self.path[-2:])}={'0' if n == 0 else 'n'}")
        if not self.length(n, mx, kind):
            return
        self.out += self.rand_bytes(n, kind)
        self.pad(n)

    def rand_bytes(self, n, kind):
        if kind == "string":
            if n and self.rng.random() < 0.2:
                self.tags.add("non_utf8_string")
                b = bytearray(self.rng.randrange(256) for _ in range(n))
                b[self.rng.randrange(n)] = self.rng.choice([0xFF, 0xC0, 0x80, 0xED, 0x00])
                return bytes(b)
            return bytes(self.rng.choice(b"abcXYZ019_ -") for _ in range(n))
        return bytes(self.rng.randrange(256) for _ in range(n))

    # ---- type walk
    def t_ref(self, t, depth):
        self.nodes += 1
        r = t["r"]
        if r == "int":
            v = self.rng.choice(I32 + [self.rng.randrange(-2**31, 2**31)])
            self.out += struct.pack(">i", v)
        elif r == "uint":
            v = self.rng.choice(U32 + [self.rng.randrange(2**32)])
            self.out += struct.pack(">I", v)
        elif r == "hyper":
            v = self.rng.choice(I64 + [self.rng.randrange(-2**63, 2**63)])
            if abs(v) > 2**53:
                self.tags.add("int_beyond_f64")
            self.out += struct.pack(">q", v)
        elif r == "uhyper":
            v = self.rng.choice(U64 + [self.rng.randrange(2**64)])
            if v > 2**53:
                self.tags.add("int_beyond_f64")
            self.out += struct.pack(">Q", v)
        elif r == "bool":
            if self.want("bool_not_01"):
                v = self.rng.choice([2, 0x100, 0xFFFFFFFF, 0x01000000])
                self.u32(v)
                self.mark("bool_not_01", f"bool={v:#x}")
            else:
                self.u32(self.rng.randrange(2))
        elif r in ("opaque", "string"):
            self.bytes_body(r, t, depth)
        elif r == "opt":
            present = (not self.tight(depth) and self.rng.random() < 0.5
                       and self._ref_mind(t["of"]) + depth <= self.max_depth)
            self.cells.add(f"opt:{'.'.join(self.path[-2:])}={'some' if present else 'none'}")
            if self.want("opt_flag_not_01"):
                v = self.rng.choice([2, 0x100, 0xFFFFFFFF])
                self.u32(v)
                self.mark("opt_flag_not_01", f"flag={v:#x}")
                present = True
            else:
                self.u32(1 if present else 0)
            if present:
                self.t_ref(t["of"], depth)
        elif r == "array":
            self.array(t, depth)
        else:
            self.named(t["name"], depth)

    def array(self, t, depth):
        of = t["of"]
        if "fixed" in t:
            for i in range(t["fixed"]):
                self.t_ref(of, depth)
            return
        mx = t["max"]
        fits = self._ref_mind(of) + depth <= self.max_depth
        over = (mx is not None and mx + 1 <= 120 and fits and self.want("len_over_max"))
        if over:
            n = mx + 1
            self.mark("len_over_max", f"array<{mx}> with {n}")
        elif self.tight(depth) or not fits:
            n = 0
        else:
            n = self.rng.choice([0, 0, 1, 1, 1, 2, 2, 3])
            if mx is not None and mx <= 24 and self.rng.random() < 0.08:
                n = mx
                self.cells.add(f"len:{'.'.join(self.path[-2:])}=max")
            if mx is not None:
                n = min(n, mx)
        self.cells.add(f"len:{'.'.join(self.path[-2:])}={'0' if n == 0 else 'n'}")
        if not self.length(n, mx, "array"):
            return
        save_nodes = self.max_nodes
        if over:
            self.max_nodes = 0  # keep the oversized vector's elements minimal
        for i in range(n):
            self.path.append(f"[{i}]")
            self.t_ref(of, depth)
            self.path.pop()
        self.max_nodes = save_nodes

    def enum_value(self, name, d, allowed=None):
        members = d["members"]
        if self.want("enum_unknown"):
            known = {v for _, v in members}
            v = self.rng.choice([x for x in [max(known) + 1, 2**31 - 1, -1, 0x7F000000, max(known) + 1000]
                                 if x not in known])
            self.out += struct.pack(">i", v)
            self.mark("enum_unknown", f"{name}={v}")
            return None
        pool = [m for m in members if allowed is None or m[1] in allowed]
        m = self.rng.choice(pool)
        self.cells.add(f"enum:{name}.{m[0]}")
        self.out += struct.pack(">i", m[1])
        return m[1]

    def named(self, name, depth):
        d = self.types[name]
        k = d["k"]
        if k == "typedef":
            self.t_ref(d["t"], depth)
        elif k == "enum":
            self.enum_value(name, d)
        elif k == "struct":
            for fname, ft in d["fields"]:
                self.path.append(fname)
                self.t_ref(ft, depth + 1)
                self.path.pop()
        else:
            self.union(name, d, depth)

    def union(self, name, d, depth):
        budget = self.max_depth - depth - 1
        arms = []
        for a in d["arms"]:
            need = 0 if a["t"] is None else self._ref_mind(a["t"])
            arms.append((need, a))
        ok = [x for x in arms if x[0] <= budget]
        if self.tight(depth) or not ok:
            lo = min(x[0] for x in arms)
            ok = [x for x in arms if x[0] == lo]
        need, arm = self.rng.choice(ok)
        idx = self.rng.randrange(len(arm["cases"]))
        case, label = arm["cases"][idx], arm["labels"][idx]
        disc = d["disc"]
        dd = self.types[disc["name"]] if disc["r"] == "ref" else None
        while dd is not None and dd["k"] == "typedef":
            disc = dd["t"]
            dd = self.types[disc["name"]] if disc["r"] == "ref" else None
        if dd is not None and dd["k"] == "enum":
            if d["default"] is None and self.want("enum_unknown"):
                known = {c for a in d["arms"] for c in a["cases"]}
                v = max(known) + self.rng.choice([1, 7, 1000])
                self.out += struct.pack(">i", v)
                self.mark("enum_unknown", f"{name} discriminant={v}")
                return
            self.out += struct.pack(">i", case)
        else:
            if d["default"] is None and self.want("enum_unknown"):
                known = {c for a in d["arms"] for c in a["cases"]}
                v = max(known) + self.rng.choice([1, 7, 1000])
                self.out += struct.pack(">i", v)
                self.mark("enum_unknown", f"{name} discriminant={v}")
                return
            self.out += struct.pack(">i", case)
        self.cells.add(f"arm:{name}.{label}")
        if arm["t"] is not None:
            self.path.append(arm["name"])
            self.t_ref(arm["t"], depth + 1)
            self.path.pop()


def all_cells(schema):
    cells = set()
    for n, d in schema["types"].items():
        if d["k"] == "union":
            for a in d["arms"]:
                for lab in a["labels"]:
                    cells.add(f"arm:{n}.{lab}")
        elif d["k"] == "enum":
            for m, _ in d["members"]:
                cells.add(f"enum:{n}.{m}")
    return cells


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("schema"); ap.add_argument("out")
    ap.add_argument("--valid", type=int, default=6)
    ap.add_argument("--faulty", type=int, default=2, help="cases per fault kind per root")
    ap.add_argument("--seed", default="shapecov-0")
    ap.add_argument("--roots", default="")
    ap.add_argument("--max-bytes", type=int, default=24000)
    a = ap.parse_args()
    schema = json.load(open(a.schema))
    g = Gen(schema, a.seed)
    roots = a.roots.split(",") if a.roots else [n for n in schema["order"] if schema["types"][n]["k"] != "typedef" or True]
    n_out, hit = 0, set()
    with open(a.out, "w") as f:
        def emit(root, tag, data, valid, inj):
            nonlocal n_out
            if len(data) > a.max_bytes:
                return
            rec = {"id": f"{root}/{tag}", "type": root, "valid": valid,
                   "b64": base64.b64encode(data).decode(), "tags": sorted(g.tags)}
            if inj:
                rec["fault"] = inj
            f.write(json.dumps(rec) + "\n")
            n_out += 1

        for root in roots:
            for i in range(a.valid):
                data = g.make(root, f"v{i}")
                hit |= g.cells
                emit(root, f"v{i}", data, True, None)
            for kind in FAULTS:
                for i in range(a.faulty):
                    cs = f"f{i}"
                    if kind in ("trailing", "truncated"):
                        data = g.make(root, cs, kind, 0)
                    else:
                        g.make(root, cs, kind, -1)       # dry run: count opportunities
                        if g.opps == 0:
                            continue
                        j = random.Random(f"{a.seed}:{root}:{kind}:{i}").randrange(g.opps)
                        data = g.make(root, cs, kind, j)
                    if g.injected is None:
                        continue
                    emit(root, f"{kind}{i}", data, False, g.injected)
    total = all_cells(schema)
    got = {c for c in hit if c in total}
    print(json.dumps({"cases": n_out, "roots": len(roots), "schema_cells": len(total),
                      "cells_hit": len(got), "pct": round(100 * len(got) / len(total), 1)}))
    json.dump({"total": sorted(total), "hit": sorted(got)}, open(a.out + ".cells.json", "w"))


if __name__ == "__main__":
    main()
