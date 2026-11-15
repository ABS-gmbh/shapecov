"""Mine real network ledgers for rare shapes.

  mine.py scan  <testnet|pubnet> <first-seq> <last-seq> [--stride N] [--cache DIR] [--index FILE] [--jobs N]
  mine.py goldens <stellar-core checkout> [--index FILE] [--jobs N]
  mine.py pick  <index.jsonl> [<index.jsonl> ...] [--max N] [--require PATTERN,...]

`scan` downloads ledgers from Stellar's public ledger archive (Galexie layout), decodes each with
the independent decoder, and appends one line per ledger to the index: its schema cells (union
cases and enum values) and the named patterns below. Nothing is kept from a ledger but that line.

`goldens` does the same for stellar-core's golden LedgerCloseMeta (the `test-lcm-current/` tree that
`stellar-core test --check-lcm` verifies in core's CI). Each file is a record-marked stream of
ledgers; every ledger must decode strictly and re-encode to the same bytes, or the run fails.

`pick` chooses a small set of ledgers by greedy set cover: at each step the ledger that adds the
most not-yet-covered patterns (rare, named shapes) and then cells, smallest ledger first on ties.
Each chosen ledger is reported with the patterns and cells it is the designated entry for.

Patterns are shapes the XDR schema cannot express as a single union case: they are found by
walking the decoded value. Each has a stable name used in the corpus manifest.
"""
import argparse
import base64
import concurrent.futures as cf
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import strkey  # noqa: E402
from decode import Decoder, XdrError  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUCKET = "https://aws-public-blockchain.s3.us-east-2.amazonaws.com/v1.1/stellar/ledgers"
DATASET = {"testnet": "testnet/2025-12-18", "pubnet": "pubnet"}
PASSPHRASE = {"testnet": "Test SDF Network ; September 2015",
              "pubnet": "Public Global Stellar Network ; September 2015"}
F64 = 2 ** 53


def ledger_url(net, seq):
    start = seq // 64000 * 64000
    return (f"{BUCKET}/{DATASET[net]}/{0xFFFFFFFF - start:08X}--{start}-{start + 63999}/"
            f"{0xFFFFFFFF - seq:08X}--{seq}.xdr.zst")


def fetch(net, seq, cache):
    """Return the raw LedgerCloseMeta bytes of one ledger, or None if the archive has no such file."""
    f = Path(cache) / net / f"{seq}.xdr.zst"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(ledger_url(net, seq), timeout=60) as r:
                data = r.read()
        except Exception:
            return None
        tmp = f.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.rename(f)
    batch = subprocess.run(["zstd", "-dc", str(f)], check=True, capture_output=True).stdout
    return batch[12:]  # LedgerCloseMetaBatch = startSequence, endSequence, array length, then the ledger


# ---- patterns

def native_key(k):
    """The text a naive ScVal -> native conversion would use as a map key, or None."""
    t = k.get("type")
    for arm, field in (("SCV_U32", "u32"), ("SCV_I32", "i32"), ("SCV_U64", "u64"), ("SCV_I64", "i64"),
                       ("SCV_TIMEPOINT", "timepoint"), ("SCV_DURATION", "duration")):
        if t == arm:
            return str(k[field])
    if t in ("SCV_SYMBOL", "SCV_STRING"):
        v = k["sym" if t == "SCV_SYMBOL" else "str"]
        return v if isinstance(v, str) else None
    if t == "SCV_BOOL":
        return "true" if k["b"] else "false"
    return None


def auth_depth(inv):
    return 1 + max([auth_depth(s) for s in inv.get("subInvocations", [])] or [0])


def scval_depth(v):
    if not isinstance(v, dict):
        return 0
    if v.get("type") == "SCV_VEC" and v.get("vec"):
        return 1 + max([scval_depth(x) for x in v["vec"]] or [0])
    if v.get("type") == "SCV_MAP" and v.get("map"):
        return 1 + max([max(scval_depth(e["key"]), scval_depth(e["val"])) for e in v["map"]] or [0])
    return 0


def patterns(lcm, with_paths=False):
    """Named rare shapes present in one decoded LedgerCloseMeta.

    Returns the set of names, or with_paths=True a dict name -> path of the first occurrence.
    """
    out = {}

    def hit(name, path):
        out.setdefault(name, path)

    def walk(v, path):
        if isinstance(v, list):
            for k, x in enumerate(v):
                walk(x, f"{path}[{k}]")
            return
        if not isinstance(v, dict):
            return
        t = v.get("type")
        if "med25519" in v:
            hit("muxed-account", path)
            mid = v["med25519"]["id"]
            if mid == 0:
                hit("muxed-id-zero", f"{path}.med25519.id")
            if mid > F64:
                hit("muxed-id-beyond-f64", f"{path}.med25519.id")
            if mid == 2 ** 64 - 1:
                hit("muxed-id-max", f"{path}.med25519.id")
        if t == "SC_ADDRESS_TYPE_MUXED_ACCOUNT":
            hit("scaddress-muxed-account", path)
            if v["muxedAccount"]["id"] > F64:
                hit("scaddress-muxed-id-beyond-f64", f"{path}.muxedAccount.id")
        if t == "SC_ADDRESS_TYPE_MUXED_CONTRACT":
            hit("scaddress-muxed-contract", path)
        if t == "SIGNER_KEY_TYPE_ED25519_SIGNED_PAYLOAD":
            hit("signed-payload-signer", path)
            n = len(v["ed25519SignedPayload"]["payload"]) // 2
            if n == 64:
                hit("signed-payload-max-length", f"{path}.ed25519SignedPayload.payload")
            if n % 4:
                hit("signed-payload-needs-padding", f"{path}.ed25519SignedPayload.payload")
        if t == "MEMO_TEXT" and isinstance(v.get("text"), dict):
            hit("memo-text-not-utf8", f"{path}.text")
        if t == "SCV_MAP" and v.get("map"):
            keys = [native_key(e["key"]) for e in v["map"]]
            real = [k for k in keys if k is not None]
            if len(real) != len(set(real)):
                hit("scmap-keys-collide-as-text", path)
            if len({e["key"].get("type") for e in v["map"]}) > 1:
                hit("scmap-mixed-key-types", path)
        if t in ("SCV_VEC", "SCV_MAP") and scval_depth(v) >= 5:
            hit("scval-nested-5-deep", path)
        if t in ("SCV_U64", "SCV_I64"):
            f = "u64" if t == "SCV_U64" else "i64"
            if abs(v[f]) > F64:
                hit("scval-int64-beyond-f64", f"{path}.{f}")
        if t in ("SCV_U128", "SCV_I128", "SCV_U256", "SCV_I256"):
            hit("scval-wide-integer", path)
        if "rootInvocation" in v:
            d = auth_depth(v["rootInvocation"])
            if d >= 2:
                hit("auth-nested-invocations", f"{path}.rootInvocation")
            if d >= 4:
                hit("auth-tree-4-deep", f"{path}.rootInvocation")
        for f in ("offerID", "offerId"):
            if f in v and isinstance(v[f], int) and v[f] > F64:
                hit("offer-id-beyond-f64", f"{path}.{f}")
        if t == "ASSET_TYPE_POOL_SHARE" and "liquidityPool" in v:
            cp = v["liquidityPool"].get("constantProduct", {})
            a, b = cp.get("assetA", {}), cp.get("assetB", {})
            xa = a.get("alphaNum4") or a.get("alphaNum12") or {}
            xb = b.get("alphaNum4") or b.get("alphaNum12") or {}
            if xa.get("issuer") and xb.get("issuer") and xa.get("assetCode") == xb.get("assetCode") \
                    and a.get("type") == b.get("type"):
                ka, kb = xa["issuer"].get("ed25519"), xb["issuer"].get("ed25519")
                if ka and kb and (ka < kb) != (strkey.account(ka) < strkey.account(kb)):
                    hit("pool-issuers-order-differs-strkey-vs-bytes", f"{path}.liquidityPool.constantProduct")
        if "operations" in v and isinstance(v["operations"], list) and v["operations"] \
                and isinstance(v["operations"][0], dict) and "body" in v["operations"][0]:
            n = len(v["operations"])
            if n == 100:
                hit("operations-at-max-100", f"{path}.operations")
            elif n >= 50:
                hit("operations-50-or-more", f"{path}.operations")
            for k, o in enumerate(v["operations"]):
                if o.get("sourceAccount") and "med25519" in o["sourceAccount"] \
                        and o["body"].get("type") == "INVOKE_HOST_FUNCTION":
                    hit("soroban-op-muxed-source", f"{path}.operations[{k}].sourceAccount")
        if "signatures" in v and isinstance(v["signatures"], list) and len(v["signatures"]) == 20:
            hit("signatures-at-max-20", f"{path}.signatures")
        for name, x in v.items():
            walk(x, f"{path}.{name}" if path else name)

    walk(lcm, "")
    ver = f"v{lcm['v']}"
    body = lcm[ver]
    for i, tp in enumerate(body.get("txProcessing", [])):
        meta = tp["txApplyProcessing"]
        mv = meta.get(f"v{meta['v']}") if meta["v"] else None
        base = f"{ver}.txProcessing[{i}]"
        if isinstance(mv, dict):
            soroban = mv.get("sorobanMeta") is not None
            for j, op in enumerate(mv.get("operations", [])):
                for c, ch in enumerate(op.get("changes", [])):
                    if ch.get("type") != "LEDGER_ENTRY_CREATED" or not soroban:
                        continue
                    kind = ch["created"]["data"]["type"]
                    where = f"{base}.txApplyProcessing.v{meta['v']}.operations[{j}].changes[{c}].created.data"
                    if kind == "TRUSTLINE":
                        hit("soroban-created-trustline", where)
                    if kind == "ACCOUNT":
                        hit("soroban-created-account", where)
        else:
            soroban = False
        if tp["result"]["result"]["result"]["code"] not in ("txSUCCESS", "txFEE_BUMP_INNER_SUCCESS"):
            hit("failed-transaction", f"{base}.result.result.result")
            if soroban:
                hit("failed-soroban-transaction", f"{base}.result.result.result")
    return out if with_paths else set(out)

def scan_one(args):
    net, seq, cache = args
    raw = fetch(net, seq, cache)
    if raw is None:
        return None
    dec = scan_one.dec
    try:
        v = dec.decode("LedgerCloseMeta", raw)
    except XdrError as e:
        return {"net": net, "seq": seq, "error": str(e), "size": len(raw)}
    body = v[f"v{v['v']}"]
    hdr = body["ledgerHeader"]["header"]
    return {"net": net, "seq": seq, "size": len(raw), "protocol": hdr["ledgerVersion"],
            "txs": len(body.get("txProcessing", [])), "cells": sorted(dec.cells),
            "patterns": sorted(patterns(v))}


def _init():
    scan_one.dec = Decoder(json.load(open(ROOT / "schema/schema.json")))


def scan(a):
    seqs = list(range(a.first, a.last + 1, a.stride))
    done = set()
    if os.path.exists(a.index):
        done = {(r["net"], r["seq"]) for r in map(json.loads, open(a.index))}
    todo = [(a.net, s, a.cache) for s in seqs if (a.net, s) not in done]
    n = miss = 0
    with open(a.index, "a") as out, cf.ProcessPoolExecutor(a.jobs, initializer=_init) as ex:
        for r in ex.map(scan_one, todo, chunksize=4):
            if r is None:
                miss += 1
                continue
            out.write(json.dumps(r) + "\n")
            n += 1
            if n % 500 == 0:
                out.flush()
                print(f"  {n} of {len(todo)}", flush=True)
    print(json.dumps({"scanned": n, "not_in_archive": miss, "already_indexed": len(seqs) - len(todo)}))


def golden_records(path):
    data = Path(path).read_bytes()
    i, out = 0, []
    while i < len(data):
        n = int.from_bytes(data[i:i + 4], "big") & 0x7FFFFFFF
        out.append(data[i + 4:i + 4 + n])
        i += 4 + n
    return out


def golden_one(args):
    root, rel = args
    from encode import Encoder
    dec = golden_one.dec
    enc = Encoder({"types": dec.types})
    rows = []
    for k, raw in enumerate(golden_records(Path(root) / rel)):
        v = dec.decode("LedgerCloseMeta", raw)          # strict: raises on any deviation
        if enc.encode("LedgerCloseMeta", v) != raw:
            raise XdrError(f"{rel}#{k}: re-encoding differs")
        body = v[f"v{v['v']}"]
        rows.append({"net": "core-golden", "seq": f"{rel}#{k}", "size": len(raw),
                     "protocol": body["ledgerHeader"]["header"]["ledgerVersion"],
                     "txs": len(body.get("txProcessing", [])), "cells": sorted(dec.cells),
                     "patterns": sorted(patterns(v))})
    return rows


def _init_golden():
    golden_one.dec = Decoder(json.load(open(ROOT / "schema/schema.json")))


def goldens(a):
    root = Path(a.checkout)
    files = sorted(str(f.relative_to(root)) for f in (root / "test-lcm-current").rglob("*.xdr"))
    n = 0
    with open(a.index, "w") as out, cf.ProcessPoolExecutor(a.jobs, initializer=_init_golden) as ex:
        for rows in ex.map(golden_one, [(str(root), f) for f in files], chunksize=8):
            for r in rows:
                out.write(json.dumps(r) + "\n")
                n += 1
    print(json.dumps({"golden_files": len(files), "ledgers_decoded_and_reencoded_identically": n}))


def pick(a):
    rows = [r for f in a.index for r in map(json.loads, open(f)) if "error" not in r]
    require = set(a.require.split(",")) if a.require else set()
    covered_p, covered_c, chosen = set(), set(), []
    all_p = {p for r in rows for p in r["patterns"]}
    while len(chosen) < a.max:
        best, key = None, None
        for r in rows:
            np_ = set(r["patterns"]) - covered_p
            nc = set(r["cells"]) - covered_c
            k = (len(np_ & require), len(np_), len(nc), -r["size"])
            if key is None or k > key:
                best, key = r, k
        if best is None or (key[1] == 0 and key[2] == 0):
            break
        if key[1] == 0 and key[2] < a.min_cells:
            break
        chosen.append({"net": best["net"], "seq": best["seq"], "size": best["size"], "txs": best["txs"],
                       "protocol": best["protocol"],
                       "new_patterns": sorted(set(best["patterns"]) - covered_p),
                       "new_cells": sorted(set(best["cells"]) - covered_c)})
        covered_p |= set(best["patterns"])
        covered_c |= set(best["cells"])
    print(json.dumps({"ledgers_indexed": len(rows), "patterns_seen": sorted(all_p),
                      "patterns_covered": len(covered_p), "cells_covered": len(covered_c),
                      "chosen": chosen}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("net", choices=list(DATASET)); s.add_argument("first", type=int); s.add_argument("last", type=int)
    s.add_argument("--stride", type=int, default=1); s.add_argument("--cache", default="lake-cache")
    s.add_argument("--index", default="mine-index.jsonl"); s.add_argument("--jobs", type=int, default=8)
    p = sub.add_parser("pick")
    p.add_argument("index", nargs="+"); p.add_argument("--max", type=int, default=20)
    p.add_argument("--min-cells", type=int, default=3); p.add_argument("--require", default="")
    g = sub.add_parser("goldens")
    g.add_argument("checkout"); g.add_argument("--index", default="goldens-index.jsonl")
    g.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    {"scan": scan, "pick": pick, "goldens": goldens}[a.cmd](a)


if __name__ == "__main__":
    main()
