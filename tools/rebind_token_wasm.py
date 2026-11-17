"""A minimal Soroban contract, assembled byte by byte, that a SEP-41 classifier accepts and that can
rebind itself to other wasm. Used by tools/localcore.py (scenario token-rebind-p28).

  rebind_token_wasm.py OUT.wasm [--plain]   write the module (--plain: declare only mint and upgrade)

The module exports two functions:
  mint(to, amount)        publishes the event (["mint", to], amount), as a SEP-41 token's mint does
  upgrade(wasm_hash)      update_current_contract_wasm(wasm_hash): the contract's next wasm
Its contractspecv0 section declares the SEP-41 token interface (balance, allowance, decimals, name,
symbol, approve, transfer, transfer_from, burn, burn_from), plus mint and upgrade. A classifier that
matches the interface by the spec (as wallet-backend's does) claims it; the interface functions
are declared, not implemented. No toolchain is needed, so the bytes are the same on every machine.

This contract is purpose-built for the scenario, not a token anyone uses: it exists so that a replay
can show a contract classified as SEP-41 that then rebinds itself. stellar-core 30.0.0 accepts every
transaction that uploads, deploys and calls it. A contract built from the soroban-sdk token example
(plus an upgrade function) is the planned replacement.

Declaring more in the spec than the module exports is still valid network input: anyone can upload
such a contract, the host never checks the contractspecv0 section against the exports (it only runs
what is called), and wallet-backend classifies a contract by its spec, so a network could carry
this exact contract and wallet-backend would classify it the same way.

Module layout (WebAssembly binary format, sections in order):
  1 type      three signatures, all on i64 (a Soroban Val is an i64): () -> i64, (i64) -> i64,
              (i64, i64) -> i64
  2 import    the four host functions in IMPORTS, as function indices 0-3
  3 function  two defined functions, mint (index 4) and upgrade (index 5)
  5 memory    one page; Soroban expects a module to have a memory
  7 export    mint, upgrade and the memory
  10 code     the two bodies (see build())
  0 custom    contractenvmetav0: the host interface version the module targets
  0 custom    contractspecv0: XDR ScSpecEntry records, the interface a classifier reads
"""
import struct
import sys

# Host functions (soroban-env-common env.json): (module, name, params, results)
IMPORTS = [("v", "_", 0, 1),   # vec_new() -> VecObject
           ("v", "6", 2, 1),   # vec_push_back(VecObject, Val) -> VecObject
           ("x", "1", 2, 1),   # contract_event(VecObject topics, Val data) -> Void
           ("l", "6", 1, 1)]   # update_current_contract_wasm(BytesObject) -> Void
VOID = 2                       # Val tag 2, no body
ENV_INTERFACE_PROTOCOL = 22    # contractenvmetav0: the oldest protocol whose host runs it


def uleb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def sleb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        done = (n == 0 and not b & 0x40) or (n == -1 and b & 0x40)
        out.append(b | (0 if done else 0x80))
        if done:
            return bytes(out)


def vec(items):
    return uleb(len(items)) + b"".join(items)


def name(s):
    return uleb(len(s)) + s.encode()


def section(sid, body):
    return bytes([sid]) + uleb(len(body)) + body


def custom(nm, body):
    return section(0, name(nm) + body)


def symbol_small(s):
    """SymbolSmall Val: six bits per character, tag 14."""
    code = {"_": 1, **{c: 2 + i for i, c in enumerate("0123456789")},
            **{c: 12 + i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
            **{c: 38 + i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}}
    body = 0
    for c in s:
        body = (body << 6) | code[c]
    return (body << 8) | 14


# ---- XDR for the contract spec (Stellar-contract-spec.x)
def xu32(n):
    return struct.pack(">I", n)


def xstr(s):
    b = s.encode()
    return xu32(len(b)) + b + b"\0" * (-len(b) % 4)


TYPES = {"Address": 19, "MuxedAddress": 20, "i128": 11, "u32": 4, "String": 16}


def xtype(t):
    if isinstance(t, tuple):  # ("BytesN", 32)
        return xu32(1006) + xu32(t[1])
    return xu32(TYPES[t])


def spec_fn(fname, inputs, outputs=()):
    return (xu32(0) + xstr("") + xstr(fname)  # SC_SPEC_ENTRY_FUNCTION_V0, doc, name
            + xu32(len(inputs)) + b"".join(xstr("") + xstr(n) + xtype(t) for n, t in inputs)
            + xu32(len(outputs)) + b"".join(xtype(t) for t in outputs))


SPEC = [spec_fn("balance", [("id", "Address")], ["i128"]),
        spec_fn("allowance", [("from", "Address"), ("spender", "Address")], ["i128"]),
        spec_fn("decimals", [], ["u32"]),
        spec_fn("name", [], ["String"]),
        spec_fn("symbol", [], ["String"]),
        spec_fn("approve", [("from", "Address"), ("spender", "Address"), ("amount", "i128"),
                            ("expiration_ledger", "u32")]),
        spec_fn("transfer", [("from", "Address"), ("to_muxed", "MuxedAddress"), ("amount", "i128")]),
        spec_fn("transfer_from", [("spender", "Address"), ("from", "Address"), ("to", "Address"), ("amount", "i128")]),
        spec_fn("burn", [("from", "Address"), ("amount", "i128")]),
        spec_fn("burn_from", [("spender", "Address"), ("from", "Address"), ("amount", "i128")]),
        spec_fn("mint", [("to", "Address"), ("amount", "i128")]),
        spec_fn("upgrade", [("wasm_hash", ("BytesN", 32))])]


def build(sep41=True):
    """sep41=False: the same code, declaring only mint and upgrade, which no SEP-41 classifier claims."""
    I64 = 0x7E
    functype = lambda n_params, n_results: b"\x60" + vec([bytes([I64])] * n_params) + vec([bytes([I64])] * n_results)
    types = [functype(0, 1), functype(1, 1), functype(2, 1)]
    type_of = {0: 0, 1: 1, 2: 2}
    imports = [name(m) + name(n) + b"\x00" + uleb(type_of[p]) for m, n, p, _ in IMPORTS]
    # defined functions: mint (params 2) = index 4, upgrade (params 1) = index 5
    funcs = [uleb(2), uleb(1)]
    exports = [name("mint") + b"\x00" + uleb(4), name("upgrade") + b"\x00" + uleb(5),
               name("memory") + b"\x02" + uleb(0)]
    call = lambda f: b"\x10" + uleb(f)
    get = lambda i: b"\x20" + uleb(i)
    const = lambda v: b"\x42" + sleb(v)
    drop, end = b"\x1a", b"\x0b"
    # mint(to=local 0, amount=local 1): build the topic vector ["mint", to] with vec_new and two
    # vec_push_back calls, publish (topics, amount) with contract_event, drop its Void, return Void.
    mint = (call(0) + const(symbol_small("mint")) + call(1) + get(0) + call(1) + get(1) + call(2) + drop
            + const(VOID) + end)
    # upgrade(wasm_hash=local 0): update_current_contract_wasm(wasm_hash), drop its Void, return Void.
    upgrade = get(0) + call(3) + drop + const(VOID) + end
    code = [vec([]) + mint, vec([]) + upgrade]
    env_meta = xu32(0) + struct.pack(">Q", ENV_INTERFACE_PROTOCOL << 32)  # SC_ENV_META_KIND_INTERFACE_VERSION
    return (b"\0asm" + struct.pack("<I", 1)
            + section(1, vec(types)) + section(2, vec(imports)) + section(3, vec(funcs))
            + section(5, vec([b"\x00" + uleb(1)])) + section(7, vec(exports))
            + section(10, vec([uleb(len(c)) + c for c in code]))
            + custom("contractenvmetav0", env_meta)
            + custom("contractspecv0", b"".join(SPEC if sep41 else SPEC[-2:])))


if __name__ == "__main__":
    open(sys.argv[1], "wb").write(build(sep41="--plain" not in sys.argv))
