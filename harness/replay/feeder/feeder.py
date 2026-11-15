#!/usr/bin/env python3
"""Ledger feeder: serves LedgerCloseMeta corpus entries through two inputs that
existing Stellar pipelines already consume.

  port 8000  mock stellar-rpc (JSON-RPC 2.0 over HTTP POST)
             POST /rpc/<entry-id>      getHealth, getNetwork, getLatestLedger,
                                       getVersionInfo, getLedgers, getLedgerEntries
             GET  /__stats             feeder counters and peak memory
             anything else             404, logged (shows what else an indexer asks for)
  port 9000  S3-compatible object store holding the Galexie data-lake layout
             bucket `shapecov-lake`, one prefix per entry:
               <entry-id>/.config.json
               <entry-id>/<partition>/<file>.xdr.zst
             GET object, HEAD object, ListObjectsV2 (path style)

Entries are discovered from corpus/manifest.json at start (xdr_type == LedgerCloseMeta).
Memory is bounded: the index keeps a few fields per entry, ledger bytes are
streamed from disk in 64 KiB chunks for both inputs, and data-lake files are
built by streaming base64 -> zstd.

Python 3.14 standard library only (compression.zstd).

  feeder.py --corpus <dir> --work <dir> [--build-only] [--rpc-port 8000] [--s3-port 9000]
"""
import argparse
import base64
import hashlib
import json
import os
import resource
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lcmhead  # noqa: E402

CHUNK = 64 * 1024
BUCKET = "shapecov-lake"
LEDGERS_PER_BATCH = 1
BATCHES_PER_PARTITION = 64000
RETENTION_WINDOW = 120960

STATS = {"rpc_requests": 0, "s3_requests": 0, "other_requests": 0, "bytes_served": 0,
         "ledgers_served_rpc": 0, "objects_served_s3": 0}
LOCK = threading.Lock()
LOG = None


def log_request(rec):
    rec["t"] = round(time.time(), 3)
    with LOCK:
        LOG.write(json.dumps(rec, sort_keys=True) + "\n")
        LOG.flush()


def bump(key, n=1):
    with LOCK:
        STATS[key] += n


# ---------------------------------------------------------------- index

def b64_payload_len(path):
    """Length of the base64 text in a one-line file, without trailing whitespace."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, size - 8))
        tail = f.read()
    return size - (len(tail) - len(tail.rstrip()))


def build_index(corpus_dir):
    """One small record per LedgerCloseMeta entry. Never loads ledger bytes."""
    with open(os.path.join(corpus_dir, "manifest.json")) as f:
        manifest = json.load(f)
    index, problems = {}, []
    for e in manifest["entries"]:
        if e.get("xdr_type") != "LedgerCloseMeta":
            continue
        path = os.path.join(corpus_dir, e["file"])
        passphrase = (e.get("source") or {}).get("network_passphrase")
        try:
            if not passphrase:
                raise ValueError("entry has no source.network_passphrase")
            h = lcmhead.head_of_b64_file(path)
        except (OSError, ValueError) as err:
            problems.append({"id": e["id"], "problem": str(err)})
            continue
        index[e["id"]] = {
            "id": e["id"], "path": path, "b64_len": b64_payload_len(path),
            "passphrase": passphrase,
            "network_id": hashlib.sha256(passphrase.encode()).hexdigest(),
            "seq": h["seq"], "hash": h["hash"], "close_time": h["close_time"],
            "protocol": h["protocol"], "header_b64": h["header_b64"],
        }
    return index, problems


# ---------------------------------------------------------------- data lake

def partition_name(seq):
    start = seq // (LEDGERS_PER_BATCH * BATCHES_PER_PARTITION) * (LEDGERS_PER_BATCH * BATCHES_PER_PARTITION)
    end = start + LEDGERS_PER_BATCH * BATCHES_PER_PARTITION - 1
    return "%08X--%d-%d" % (0xFFFFFFFF - start, start, end)


def file_name(seq):
    return "%08X--%d.xdr.zst" % (0xFFFFFFFF - seq, seq)


def build_lake(index, lake_dir):
    """Write the Galexie layout for every entry, streaming base64 -> zstd.

    A batch file is a zstd-compressed XDR LedgerCloseMetaBatch:
      uint32 startSequence, uint32 endSequence, LedgerCloseMeta ledgerCloseMetas<>
    With one ledger per file that is 12 bytes followed by the LedgerCloseMeta.
    """
    from compression import zstd
    built = []
    for e in index.values():
        root = os.path.join(lake_dir, "data", e["id"])
        meta_root = os.path.join(lake_dir, "meta", e["id"])
        key = partition_name(e["seq"]) + "/" + file_name(e["seq"])
        os.makedirs(os.path.dirname(os.path.join(root, key)), exist_ok=True)
        os.makedirs(os.path.dirname(os.path.join(meta_root, key)), exist_ok=True)
        with open(os.path.join(root, ".config.json"), "w") as f:
            json.dump({"networkPassphrase": e["passphrase"], "version": "1.0", "compression": "zstd",
                       "ledgersPerBatch": LEDGERS_PER_BATCH, "batchesPerPartition": BATCHES_PER_PARTITION},
                      f, separators=(",", ":"))
        sha = hashlib.sha256()
        comp = zstd.ZstdCompressor()
        out_path = os.path.join(root, key)
        with open(e["path"], "rb") as src, open(out_path + ".tmp", "wb") as dst:
            head = e["seq"].to_bytes(4, "big") * 2 + (1).to_bytes(4, "big")
            sha.update(head)
            dst.write(comp.compress(head))
            remaining = e["b64_len"]
            while remaining > 0:
                text = src.read(min(CHUNK, remaining))  # CHUNK is a multiple of 4
                if not text:
                    break
                remaining -= len(text)
                raw = base64.b64decode(text, validate=True)
                sha.update(raw)
                dst.write(comp.compress(raw))
            dst.write(comp.flush())
        os.replace(out_path + ".tmp", out_path)
        meta = {"start-ledger": str(e["seq"]), "end-ledger": str(e["seq"]),
                "start-ledger-close-time": str(e["close_time"]), "end-ledger-close-time": str(e["close_time"]),
                "protocol-version": str(e["protocol"]), "network-passphrase": e["passphrase"],
                "compression-type": "zst", "core-version": "shapecov-replay", "version": "shapecov-replay"}
        with open(os.path.join(meta_root, key + ".json"), "w") as f:
            json.dump(meta, f)
        built.append({"id": e["id"], "key": e["id"] + "/" + key, "size": os.path.getsize(out_path),
                      "batch_sha256": sha.hexdigest()})
    return built


# ---------------------------------------------------------------- mock stellar-rpc

class RPCError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class RPCHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    index = {}

    def log_message(self, *a):
        pass

    def _send(self, status, body, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        bump("bytes_served", len(body))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/__stats":
            with LOCK:
                s = dict(STATS)
            s["maxrss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            s["entries"] = len(self.index)
            self._send(200, json.dumps(s).encode())
            return
        if path == "/__index":
            self._send(200, json.dumps({k: {f: v[f] for f in ("seq", "hash", "close_time", "protocol", "passphrase")}
                                        for k, v in self.index.items()}).encode())
            return
        bump("other_requests")
        log_request({"port": "rpc", "http": "GET", "path": self.path, "status": 404})
        self._send(404, b"not found\n", "text/plain")

    do_HEAD = do_GET

    def do_POST(self):
        path = urlsplit(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        parts = [p for p in path.split("/") if p]
        if len(parts) != 2 or parts[0] != "rpc" or parts[1] not in self.index:
            bump("other_requests")
            log_request({"port": "rpc", "http": "POST", "path": self.path, "status": 404})
            self._send(404, b"no such entry\n", "text/plain")
            return
        entry = self.index[parts[1]]
        try:
            req = json.loads(body)
        except ValueError:
            self._send(200, json.dumps({"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32700, "message": "parse error"}}).encode())
            return
        if isinstance(req, list):  # batch: answered one by one, small methods only
            out = []
            for r in req:
                out.append(self._small(entry, r))
            self._send(200, json.dumps(out).encode())
            return
        bump("rpc_requests")
        if req.get("method") == "getLedgers":
            self._get_ledgers(entry, req)
        else:
            self._send(200, json.dumps(self._small(entry, req)).encode())

    def _small(self, e, req):
        method, rid = req.get("method"), req.get("id")
        rec = {"port": "rpc", "entry": e["id"], "method": method, "params": req.get("params")}
        try:
            if method == "getHealth":
                result = {"status": "healthy", "latestLedger": e["seq"],
                          "latestLedgerCloseTime": str(e["close_time"]), "oldestLedger": e["seq"],
                          "oldestLedgerCloseTime": str(e["close_time"]),
                          "ledgerRetentionWindow": RETENTION_WINDOW}
            elif method == "getNetwork":
                result = {"passphrase": e["passphrase"], "protocolVersion": e["protocol"]}
            elif method == "getLatestLedger":
                result = {"id": e["hash"], "protocolVersion": e["protocol"], "sequence": e["seq"],
                          "closeTime": str(e["close_time"]), "headerXdr": e["header_b64"]}
            elif method == "getVersionInfo":
                result = {"version": "shapecov-replay-mock", "commitHash": "0" * 40,
                          "buildTimestamp": "1970-01-01T00:00:00", "captiveCoreVersion": "none (mock)",
                          "protocolVersion": e["protocol"]}
            elif method == "getLedgerEntries":
                # The mock holds no ledger state: every key is reported as not found.
                result = {"entries": [], "latestLedger": e["seq"]}
            elif method == "getLedgers":
                raise RPCError(-32600, "getLedgers is not served inside a batch by this mock")
            else:
                raise RPCError(-32601, "method not found")
            rec["status"] = "ok"
            log_request(rec)
            return {"jsonrpc": "2.0", "id": rid, "result": result}
        except RPCError as err:
            rec["status"] = "error %d %s" % (err.code, err.message)
            log_request(rec)
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": err.code, "message": err.message}}

    def _get_ledgers(self, e, req):
        """Real response shape of stellar-rpc getLedgers; metadataXdr is streamed from disk."""
        params = req.get("params") or {}
        rec = {"port": "rpc", "entry": e["id"], "method": "getLedgers", "params": params}
        pag = params.get("pagination") or {}
        fmt = params.get("xdrFormat") or "base64"
        try:
            if fmt != "base64":
                raise RPCError(-32602, "this mock serves xdrFormat base64 only")
            limit = int(pag.get("limit") or 5)
            if limit < 1 or limit > 200:
                raise RPCError(-32602, "limit must not exceed 200")
            if pag.get("cursor"):
                if params.get("startLedger"):
                    raise RPCError(-32602, "startLedger and cursor cannot both be set")
                start = int(pag["cursor"]) + 1
            else:
                start = int(params.get("startLedger") or 0)
            if start != e["seq"]:  # the window this mock presents is exactly one ledger
                raise RPCError(-32602, "start ledger (%d) must be between the oldest ledger: %d and the "
                                       "latest ledger: %d for this rpc instance" % (start, e["seq"], e["seq"]))
        except (RPCError, ValueError, TypeError) as err:
            code, msg = (err.code, err.message) if isinstance(err, RPCError) else (-32602, "invalid params")
            rec["status"] = "error %d %s" % (code, msg)
            log_request(rec)
            self._send(200, json.dumps({"jsonrpc": "2.0", "id": req.get("id"),
                                        "error": {"code": code, "message": msg}}).encode())
            return
        pre = ('{"jsonrpc":"2.0","id":%s,"result":{"ledgers":[{"hash":"%s","sequence":%d,'
               '"ledgerCloseTime":"%d","headerXdr":"%s","metadataXdr":"'
               % (json.dumps(req.get("id")), e["hash"], e["seq"], e["close_time"], e["header_b64"])).encode()
        post = ('"}],"latestLedger":%d,"latestLedgerCloseTime":%d,"oldestLedger":%d,'
                '"oldestLedgerCloseTime":%d,"cursor":"%d"}}'
                % (e["seq"], e["close_time"], e["seq"], e["close_time"], e["seq"])).encode()
        total = len(pre) + e["b64_len"] + len(post)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(total))
        self.end_headers()
        self.wfile.write(pre)
        remaining = e["b64_len"]
        with open(e["path"], "rb") as f:
            while remaining > 0:
                chunk = f.read(min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                self.wfile.write(chunk)
        self.wfile.write(post)
        bump("bytes_served", total)
        bump("ledgers_served_rpc")
        rec["status"] = "ok"
        rec["response_bytes"] = total
        log_request(rec)


# ---------------------------------------------------------------- S3-compatible store

class S3Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    lake = ""

    def log_message(self, *a):
        pass

    def _xml(self, status, body, head_only=False):
        data = ('<?xml version="1.0" encoding="UTF-8"?>\n' + body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("x-amz-request-id", "shapecov")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _error(self, status, code, message, head_only=False):
        self._xml(status, "<Error><Code>%s</Code><Message>%s</Message></Error>" % (code, escape(message)), head_only)

    def _keys(self):
        """All object keys in lexical order, generated lazily from the directory tree."""
        root = os.path.join(self.lake, "data")

        def walk(d, prefix):
            for name in sorted(os.listdir(d), key=lambda n: n + "/" if os.path.isdir(os.path.join(d, n)) else n):
                p = os.path.join(d, name)
                if os.path.isdir(p):
                    yield from walk(p, prefix + name + "/")
                else:
                    yield prefix + name, p
        if os.path.isdir(root):
            yield from walk(root, "")

    def _serve(self, head_only):
        bump("s3_requests")
        u = urlsplit(self.path)
        parts = unquote(u.path).lstrip("/").split("/", 1)
        bucket, key = parts[0], (parts[1] if len(parts) > 1 else "")
        q = parse_qs(u.query, keep_blank_values=True)
        rec = {"port": "s3", "http": "HEAD" if head_only else "GET", "path": self.path}
        if bucket != BUCKET:
            rec["status"] = 404
            log_request(rec)
            self._error(404, "NoSuchBucket", "The specified bucket does not exist", head_only)
            return
        if not key:  # ListObjectsV2
            prefix = (q.get("prefix") or [""])[0]
            after = (q.get("continuation-token") or q.get("start-after") or [""])[0]
            max_keys = min(int((q.get("max-keys") or ["1000"])[0]), 1000)
            items, truncated, last = [], False, ""
            for k, p in self._keys():
                if not k.startswith(prefix) or (after and k <= after):
                    continue
                if len(items) == max_keys:
                    truncated = True
                    break
                st = os.stat(p)
                items.append("<Contents><Key>%s</Key><LastModified>%s</LastModified><ETag>&quot;%s&quot;</ETag>"
                             "<Size>%d</Size><StorageClass>STANDARD</StorageClass></Contents>"
                             % (escape(k), time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(st.st_mtime)),
                                hashlib.md5(k.encode()).hexdigest(), st.st_size))
                last = k
            body = ("<ListBucketResult xmlns=\"http://s3.amazonaws.com/doc/2006-03-01/\"><Name>%s</Name>"
                    "<Prefix>%s</Prefix><KeyCount>%d</KeyCount><MaxKeys>%d</MaxKeys><IsTruncated>%s</IsTruncated>%s%s"
                    "</ListBucketResult>"
                    % (BUCKET, escape(prefix), len(items), max_keys, "true" if truncated else "false",
                       "<NextContinuationToken>%s</NextContinuationToken>" % escape(last) if truncated else "",
                       "".join(items)))
            rec["status"] = 200
            rec["keys"] = len(items)
            log_request(rec)
            self._xml(200, body, head_only)
            return
        path = os.path.normpath(os.path.join(self.lake, "data", key))
        if not path.startswith(os.path.join(self.lake, "data") + os.sep) or not os.path.isfile(path):
            rec["status"] = 404
            log_request(rec)
            self._error(404, "NoSuchKey", "The specified key does not exist.", head_only)
            return
        st = os.stat(path)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(st.st_size))
        self.send_header("Last-Modified", time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(st.st_mtime)))
        self.send_header("ETag", '"%s"' % hashlib.md5(key.encode()).hexdigest())
        self.send_header("Accept-Ranges", "bytes")
        meta_path = os.path.join(self.lake, "meta", key + ".json")
        if os.path.isfile(meta_path):
            with open(meta_path) as f:
                for k, v in json.load(f).items():
                    self.send_header("x-amz-meta-" + k, v)
        self.end_headers()
        if not head_only:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(CHUNK)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            bump("bytes_served", st.st_size)
            bump("objects_served_s3")
        rec["status"] = 200
        rec["size"] = st.st_size
        log_request(rec)

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)

    def do_PUT(self):
        bump("s3_requests")
        log_request({"port": "s3", "http": "PUT", "path": self.path, "status": 405})
        self._error(405, "MethodNotAllowed", "this store is read-only")

    do_POST = do_DELETE = do_PUT


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--rpc-port", type=int, default=8000)
    ap.add_argument("--s3-port", type=int, default=9000)
    ap.add_argument("--build-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)
    lake = os.path.join(a.work, "lake")
    index, problems = build_index(a.corpus)
    built = build_lake(index, lake)
    with open(os.path.join(a.work, "feeder-index.json"), "w") as f:
        json.dump({"entries": {k: {x: v[x] for x in v if x not in ("path", "header_b64")} for k, v in index.items()},
                   "problems": problems, "lake": built,
                   "maxrss_kb_after_build": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}, f, indent=1)
    print("feeder: %d LedgerCloseMeta entries, %d problems, lake at %s" % (len(index), len(problems), lake), flush=True)
    if a.build_only:
        return
    LOG = open(os.path.join(a.work, "feeder-requests.jsonl"), "a")
    RPCHandler.index = index
    S3Handler.lake = lake
    rpc = ThreadingHTTPServer(("0.0.0.0", a.rpc_port), RPCHandler)
    s3 = ThreadingHTTPServer(("0.0.0.0", a.s3_port), S3Handler)
    threading.Thread(target=s3.serve_forever, daemon=True).start()
    print("feeder: rpc on :%d, s3 on :%d" % (a.rpc_port, a.s3_port), flush=True)
    rpc.serve_forever()


if __name__ == "__main__":
    main()
