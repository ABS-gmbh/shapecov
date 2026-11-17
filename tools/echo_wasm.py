"""A minimal Soroban contract, assembled byte by byte, that publishes what it is given. Used by
tools/localcore.py (scenario scval-values-p30) to put Soroban values into a ledger on purpose.

  echo_wasm.py OUT.wasm

The module exports one function:
  echo(topic, data)   publishes the event (["echo", topic], data) and returns Void
The host converts the invocation's arguments to values without a contract spec to check them
against, so any value the host accepts as a topic (not a Vec or a Map) and as data reaches the
event. Built with the helpers of tools/rebind_token_wasm.py; no toolchain is needed.

Module layout: a type section (() -> i64, (i64) -> i64, (i64, i64) -> i64), three host imports
(vec_new, vec_push_back, contract_event), one defined function (index 3), one memory page, the
exports echo and memory, and the custom section contractenvmetav0. There is no contractspecv0.
"""
import struct
import sys

import rebind_token_wasm as rt

IMPORTS = rt.IMPORTS[:3]  # vec_new, vec_push_back, contract_event


def build():
    I64 = 0x7E
    functype = lambda n_params, n_results: b"\x60" + rt.vec([bytes([I64])] * n_params) + rt.vec([bytes([I64])] * n_results)
    types = [functype(0, 1), functype(1, 1), functype(2, 1)]
    imports = [rt.name(m) + rt.name(n) + b"\x00" + rt.uleb(p) for m, n, p, _ in IMPORTS]
    call = lambda f: b"\x10" + rt.uleb(f)
    get = lambda i: b"\x20" + rt.uleb(i)
    const = lambda v: b"\x42" + rt.sleb(v)
    drop, end = b"\x1a", b"\x0b"
    # echo(topic=local 0, data=local 1): topics ["echo", topic], publish (topics, data), return Void.
    echo = (call(0) + const(rt.symbol_small("echo")) + call(1) + get(0) + call(1) + get(1) + call(2) + drop
            + const(rt.VOID) + end)
    env_meta = rt.xu32(0) + struct.pack(">Q", rt.ENV_INTERFACE_PROTOCOL << 32)
    return (b"\0asm" + struct.pack("<I", 1)
            + rt.section(1, rt.vec(types)) + rt.section(2, rt.vec(imports)) + rt.section(3, rt.vec([rt.uleb(2)]))
            + rt.section(5, rt.vec([b"\x00" + rt.uleb(1)]))
            + rt.section(7, rt.vec([rt.name("echo") + b"\x00" + rt.uleb(3), rt.name("memory") + b"\x02" + rt.uleb(0)]))
            + rt.section(10, rt.vec([rt.uleb(len(rt.vec([]) + echo)) + rt.vec([]) + echo]))
            + rt.custom("contractenvmetav0", env_meta))


if __name__ == "__main__":
    open(sys.argv[1], "wb").write(build())
