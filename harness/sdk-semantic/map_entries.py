"""Semantic check "map_entries_preserved" for py-stellar-base.

  python map_entries.py <XDR type> <entry .xdr.b64> <path to an ScVal map> <expected entries>

Same check as map_entries.mjs: decode the corpus entry, walk to the ScVal at
<path>, convert it with scval.to_native and count the entries that survive.
"""
import json
import re
import sys
from importlib.metadata import version

from stellar_sdk import scval, xdr

type_, file, path, expected = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
node = getattr(xdr, type_).from_xdr(open(file).read().strip())
for name, idx in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]", path):
    if name:
        node = getattr(node, re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower())
    else:
        node = node[int(idx)]
out = {"sdk": f"stellar-sdk {version('stellar-sdk')}", "check": "map_entries_preserved",
       "entries_in_xdr": len(node.map.sc_map)}
try:
    native = scval.to_native(node)
    out["entries_after_conversion"] = len(native)
    out["converted"] = {repr(k): v for k, v in native.items()}
    out["result"] = "pass" if len(native) == expected else "mishandled"
    if len(native) != expected:
        out["detail"] = f"{expected - len(native)} entry(ies) dropped without an error"
except Exception as e:  # a refusal is acceptable; silent loss is not
    out["result"] = "pass"
    out["detail"] = f"conversion refused with an error instead of dropping entries: {e}"
print(json.dumps(out))
