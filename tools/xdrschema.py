"""Parse Stellar's XDR IDL (.x files, RFC 4506 language) into a plain schema.

Output model (all JSON-serialisable):
  consts: {NAME: int}
  types:  {Name: decl} where decl is one of
    {"k":"enum","members":[[NAME,int],...]}
    {"k":"struct","fields":[[fname, tref],...]}
    {"k":"union","disc":tref,"discName":fname,"arms":[{"cases":[int|NAME...],"name":fname|None,"t":tref|None}],
                 "default":{"name":..,"t":..}|None}
    {"k":"typedef","t":tref}
  tref is one of
    {"r":"int"|"uint"|"hyper"|"uhyper"|"bool"}
    {"r":"opaque","fixed":N} | {"r":"opaque","max":N|None} | {"r":"string","max":N|None}
    {"r":"ref","name":Name}
    {"r":"array","of":tref,"fixed":N} | {"r":"array","of":tref,"max":N|None}
    {"r":"opt","of":tref}
Anonymous nested struct/union/enum declarations are hoisted and named the way
xdrgen names them: Parent + UpperCamel(fieldName).
"""
import json
import re
import sys
from pathlib import Path

TOKEN = re.compile(r"\s*(?:(0x[0-9a-fA-F]+|-?\d+)|([A-Za-z_][A-Za-z0-9_]*)|(.))", re.S)
PRIMS = {"int": "int", "hyper": "hyper", "bool": "bool", "uint32": "uint", "int32": "int",
         "uint64": "uhyper", "int64": "hyper"}


def strip(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    out, skip = [], 0
    for line in src.split("\n"):
        s = line.strip()
        if s.startswith("#ifdef") or s.startswith("#ifndef") or s.startswith("#if "):
            skip += 1
            continue
        if s.startswith("#endif"):
            skip -= 1
            continue
        if skip or s.startswith("%") or s.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def tokenize(src: str):
    toks, pos = [], 0
    src = src.rstrip()
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m:
            break
        pos = m.end()
        if m.group(1) is not None:
            toks.append(("num", int(m.group(1), 0)))
        elif m.group(2) is not None:
            toks.append(("id", m.group(2)))
        elif m.group(3).strip():
            toks.append(("p", m.group(3)))
    return toks


def upper_camel(name: str) -> str:
    return name[0].upper() + name[1:]


class Parser:
    def __init__(self):
        self.consts, self.types, self.order = {}, {}, []
        self.enum_vals = {}

    def feed(self, src: str):
        self.t, self.i = tokenize(strip(src)), 0
        while self.i < len(self.t):
            self.top()

    # -- token helpers
    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else ("eof", None)

    def nxt(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, val):
        tok = self.nxt()
        if tok[1] != val:
            ctx = " ".join(str(x[1]) for x in self.t[max(0, self.i - 8):self.i + 4])
            raise SyntaxError(f"expected {val!r}, got {tok!r} near: {ctx}")

    def accept(self, val):
        if self.peek()[1] == val:
            self.i += 1
            return True
        return False

    def value(self):
        kind, v = self.nxt()
        if kind == "num":
            return v
        if v in self.consts:
            return self.consts[v]
        if v in self.enum_vals:
            return self.enum_vals[v]
        raise SyntaxError(f"unknown constant {v}")

    def define(self, name, decl):
        self.types[name] = decl
        self.order.append(name)

    # -- grammar
    def top(self):
        kind, v = self.peek()
        if v == "namespace":
            self.nxt(); self.nxt(); self.expect("{")
            while not self.accept("}"):
                self.top()
            return
        if v == "const":
            self.nxt(); name = self.nxt()[1]; self.expect("="); self.consts[name] = self.value(); self.expect(";")
            return
        if v == "typedef":
            self.nxt()
            name, tref = self.declaration(None)
            self.define(name, {"k": "typedef", "t": tref})
            self.expect(";")
            return
        if v in ("enum", "struct", "union"):
            self.nxt(); name = self.nxt()[1]
            self.define(name, None)
            self.types[name] = self.body(v, name, name)
            self.expect(";")
            return
        if v == ";":
            self.nxt(); return
        raise SyntaxError(f"unexpected top-level token {self.peek()!r}")

    def body(self, kind, name, ctx):
        # ctx names nested anonymous declarations: xdrgen names the children of an
        # anonymous union after the union's parent, not after the union itself.
        if kind == "enum":
            self.expect("{"); members = []
            while True:
                m = self.nxt()[1]; self.expect("="); val = self.value()
                members.append([m, val]); self.enum_vals[m] = val
                if not self.accept(","):
                    break
            self.expect("}")
            return {"k": "enum", "members": members}
        if kind == "struct":
            self.expect("{"); fields = []
            while not self.accept("}"):
                fname, tref = self.declaration(ctx)
                fields.append([fname, tref]); self.expect(";")
            return {"k": "struct", "fields": fields}
        # union
        self.expect("switch"); self.expect("(")
        disc = self.typespec(name, "disc"); disc_name = self.nxt()[1]
        self.expect(")"); self.expect("{")
        arms, default = [], None
        while not self.accept("}"):
            cases, is_default = [], False
            while True:
                if self.accept("case"):
                    kind_, v = self.nxt()
                    cases.append(v); self.expect(":")
                elif self.accept("default"):
                    is_default = True; self.expect(":")
                else:
                    break
            if self.accept("void"):
                arm = {"name": None, "t": None}
            else:
                fname, tref = self.declaration(ctx)
                arm = {"name": fname, "t": tref}
            self.expect(";")
            if cases:
                arms.append({"cases": cases, **arm})
            if is_default:
                default = arm
        return {"k": "union", "disc": disc, "discName": disc_name, "arms": arms, "default": default}

    def typespec(self, parent, hint):
        kind, v = self.nxt()
        if v == "unsigned":
            w = self.nxt()[1]
            return {"r": "uint" if w == "int" else "uhyper"}
        if v in PRIMS:
            return {"r": PRIMS[v]}
        if v in ("struct", "union", "enum"):
            return ("anon", v)
        return {"r": "ref", "name": v}

    def declaration(self, parent):
        kind, v = self.peek()
        if v in ("opaque", "string"):
            self.nxt(); name = self.nxt()[1]
            if self.accept("["):
                n = self.value(); self.expect("]")
                return name, {"r": v, "fixed": n}
            self.expect("<")
            mx = None if self.peek()[1] == ">" else self.value()
            self.expect(">")
            return name, {"r": v, "max": mx}
        ts = self.typespec(parent, None)
        if isinstance(ts, tuple):  # anonymous nested declaration: body comes before the field name
            start = self.i
            depth = 0
            # find the field name that follows the matching close brace
            j = self.i
            while True:
                tok = self.t[j][1]
                if tok == "{":
                    depth += 1
                elif tok == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            fname = self.t[j + 1][1]
            tname = (parent or "") + upper_camel(fname)
            self.define(tname, None)
            self.types[tname] = self.body(ts[1], tname, parent if ts[1] == "union" else tname)
            ts = {"r": "ref", "name": tname}
        opt = self.accept("*")
        name = self.nxt()[1]
        if self.accept("["):
            n = self.value(); self.expect("]")
            ts = {"r": "array", "of": ts, "fixed": n}
        elif self.accept("<"):
            mx = None if self.peek()[1] == ">" else self.value()
            self.expect(">")
            ts = {"r": "array", "of": ts, "max": mx}
        if opt:
            ts = {"r": "opt", "of": ts}
        return name, ts


def load(xdir) -> dict:
    p = Parser()
    files = sorted(Path(xdir).glob("*.x"))
    # constants and enums can be referenced across files; parse in dependency-friendly order, retry on failure
    pending, last = files, None
    while pending:
        failed = []
        for f in pending:
            snap = (dict(p.consts), dict(p.types), list(p.order), dict(p.enum_vals))
            try:
                p.feed(f.read_text())
            except SyntaxError as e:
                if "unknown constant" not in str(e):
                    raise SyntaxError(f"{f.name}: {e}")
                p.consts, p.types, p.order, p.enum_vals = snap
                failed.append(f)
        if failed == last:
            raise SyntaxError(f"cannot resolve: {[f.name for f in failed]}")
        pending, last = failed, failed
    # resolve case labels to ints
    for name, d in p.types.items():
        if d["k"] == "union":
            for arm in d["arms"]:
                arm["labels"] = [c if isinstance(c, str) else str(c) for c in arm["cases"]]
                arm["cases"] = [c if isinstance(c, int) else p.enum_vals[c] for c in arm["cases"]]
    return {"consts": p.consts, "types": p.types, "order": p.order}


if __name__ == "__main__":
    s = load(sys.argv[1])
    kinds = {}
    for d in s["types"].values():
        kinds[d["k"]] = kinds.get(d["k"], 0) + 1
    print(json.dumps({"types": len(s["types"]), "consts": len(s["consts"]), **kinds}))
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(s, indent=1))
