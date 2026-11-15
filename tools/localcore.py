#!/usr/bin/env python3
"""Produce corpus ledgers from a local stellar-core, for shapes that are rare or absent in history.

  localcore.py --scenario NAME --out DIR [--image IMAGE] [--passphrase testnet|pubnet] [--keep]

Starts a fresh standalone stellar-core in Docker (manual close, no peers, no network
access), runs the scenarios below, and writes every closed ledger's LedgerCloseMeta from core's
own meta stream:

  DIR/ledgers/<seq>.xdr          raw LedgerCloseMeta bytes, exactly as stellar-core emitted them
  DIR/run.json                   what was submitted, core's answer, and which ledger holds what

Transactions are built with tools/encode.py and signed with tools/ed25519.py (no Stellar SDK).
All keys are derived from fixed strings, so every run submits the same transactions; close times
follow core's virtual clock, so ledger hashes differ between runs. The network root key is
sha256(passphrase), as on every standalone network.

Scenarios (one per run):
  muxed-source-p22   Protocol 22, stellar-core 22.2.1. Deploy the native Stellar Asset Contract
                     from a transaction whose source is a muxed account; the operation has no
                     source of its own, so it runs as that muxed account, and it carries no
                     authorization entries. Consensus accepts this before protocol 25. Releases
                     from 23.0.0 refuse to queue it at any protocol, and 22.x refuse it only when
                     it carries non-source-account authorization, so 22.2.1 is the newest release
                     that can produce this ledger.
  muxed-source-refused-p24
                     Protocol 24, stellar-core 30.0.0. The same transaction must be refused by the
                     queue with txSOROBAN_INVALID. Recorded as evidence, not a ledger.
  memo-and-offer-p30 Protocol 30. Create an account, pay it with a text memo whose bytes are not
                     UTF-8 (and include NUL), and submit a ManageSellOffer that names offer ID
                     2^53+1. It fails at apply (MANAGE_SELL_OFFER_BUY_NO_TRUST: the payee holds no
                     USD trustline, and no such offer exists), so the transaction is recorded as
                     failed with the ID in its envelope.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ed25519  # noqa: E402
import mine  # noqa: E402
import strkey  # noqa: E402
from decode import Decoder  # noqa: E402
from encode import Encoder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IMAGE = "stellar/stellar-core:30.0.0-3642.0e49751aa.noble"
IMAGE_V22 = "stellar/stellar-core:22.2.1-2429.e70f0aed8.focal"
SCENARIOS = {"muxed-source-p22": IMAGE_V22, "muxed-source-refused-p24": IMAGE, "memo-and-offer-p30": IMAGE}
NAME = "shapecov-localcore-gen"
PASSPHRASES = {"testnet": "Test SDF Network ; September 2015",
               "pubnet": "Public Global Stellar Network ; September 2015"}
F64_PLUS_1 = 2 ** 53 + 1
BAD_MEMO = b"shapecov \xff\xfe memo \x00 end"  # 23 bytes: invalid UTF-8 and a NUL
assert len(BAD_MEMO) <= 28

CFG = """NETWORK_PASSPHRASE="{passphrase}"
RUN_STANDALONE=true
MANUAL_CLOSE=true
NODE_IS_VALIDATOR=true
NODE_SEED="{seed} self"
UNSAFE_QUORUM=true
FAILURE_SAFETY=0
HTTP_PORT=11626
PUBLIC_HTTP_PORT=false
DATABASE="sqlite3:///data/stellar.db"
BUCKET_DIR_PATH="/data/buckets"
METADATA_OUTPUT_STREAM="/data/meta.xdr"
EMIT_CLASSIC_EVENTS=true
ENABLE_SOROBAN_DIAGNOSTIC_EVENTS=true
ENABLE_DIAGNOSTICS_FOR_TX_SUBMISSION=true
TESTING_SOROBAN_HIGH_LIMIT_OVERRIDE=true

[QUORUM_SET]
THRESHOLD_PERCENT=100
VALIDATORS=["$self"]
"""


def sh(args, check=True):
    p = subprocess.run(args, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit("command failed: %s\n%s%s" % (" ".join(args), p.stdout, p.stderr))
    return p.stdout


class Core:
    def __init__(self, work, passphrase, image=IMAGE):
        self.work, self.passphrase, self.image = Path(work), passphrase, image
        self.network_id = hashlib.sha256(passphrase.encode()).digest()

    def http(self, path):
        # check=False: curl fails while core is still starting, and the caller polls.
        out = sh(["docker", "exec", NAME, "curl", "-s", "http://127.0.0.1:11626/" + path], check=False)
        try:
            return json.loads(out)
        except ValueError:
            return {"raw": out.strip()}

    def start(self):
        self.work.mkdir(parents=True, exist_ok=True)
        node_seed = strkey.encode_secret(hashlib.sha256(b"shapecov localcore validator").digest())
        (self.work / "core.cfg").write_text(CFG.format(passphrase=self.passphrase, seed=node_seed))
        sh(["docker", "rm", "-f", NAME], check=False)
        sh(["docker", "run", "-d", "--name", NAME, "--platform", "linux/amd64", "--network", "none",
            "-v", "%s:/data" % self.work, "--entrypoint", "bash", self.image, "-c",
            "cd /data && stellar-core new-db --conf /data/core.cfg > /data/new-db.log 2>&1 "
            "&& exec stellar-core run --conf /data/core.cfg > /data/core.log 2>&1"])
        for _ in range(240):
            info = self.http("info")
            if info.get("info", {}).get("state") == "Synced!":
                return info["info"]
            time.sleep(0.5)
        raise SystemExit("stellar-core did not start; see %s/core.log" % self.work)

    def info(self):
        return self.http("info")["info"]

    def close(self):
        # Fixed, increasing close times: letting core use the wall clock trips an assertion in its
        # virtual clock (Timer.cpp: t >= mVirtualNow).
        before = self.info()["ledger"]["num"]
        self.close_time = getattr(self, "close_time", 1600000000) + 5
        answer = self.http("manualclose?ledgerSeq=%d&closeTime=%d" % (before + 1, self.close_time))
        # Core refuses a close time behind its virtual clock ("too early ... now=N"). In standalone
        # manual-close mode that clock runs far ahead of real time between requests, so retry
        # with a wide margin above the "now" it reports.
        for _ in range(5):
            m = re.search(r"too early.*now=(\d+)", json.dumps(answer))
            if not m:
                break
            self.close_time = int(m.group(1)) + 100_000
            answer = self.http("manualclose?ledgerSeq=%d&closeTime=%d" % (before + 1, self.close_time))
        for _ in range(100):
            now = self.info()["ledger"]["num"]
            if now > before:
                return now
            time.sleep(0.1)
        raise SystemExit("manual close did not advance the ledger: %s" % json.dumps(answer)[:500])

    def upgrade(self, protocol):
        self.http("upgrades?mode=set&upgradetime=1970-01-01T00:00:00Z&protocolversion=%d" % protocol)
        seq = self.close()
        got = self.info()["ledger"]["version"]
        if got != protocol:
            raise SystemExit("upgrade to protocol %d did not apply (ledger %d is version %d)" % (protocol, seq, got))
        return seq

    def submit(self, blob):
        return self.http("tx?blob=" + urllib.parse.quote(base64.b64encode(blob).decode(), safe=""))

    def stop(self):
        sh(["docker", "rm", "-f", NAME], check=False)


class Keys:
    def __init__(self, label=None, secret=None):
        self.secret = secret if secret is not None else hashlib.sha256(b"shapecov " + label.encode()).digest()
        self.pub = ed25519.public_key(self.secret).hex()

    def account(self):
        return {"type": "PUBLIC_KEY_TYPE_ED25519", "ed25519": self.pub}

    def muxed(self, mux_id=None):
        if mux_id is None:
            return {"type": "KEY_TYPE_ED25519", "ed25519": self.pub}
        return {"type": "KEY_TYPE_MUXED_ED25519", "med25519": {"id": mux_id, "ed25519": self.pub}}


def envelope(enc, core, tx, signer):
    payload = enc.encode("TransactionSignaturePayload", {
        "networkId": core.network_id.hex(),
        "taggedTransaction": {"type": "ENVELOPE_TYPE_TX", "tx": tx}})
    sig = ed25519.sign(signer.secret, hashlib.sha256(payload).digest())
    env = {"type": "ENVELOPE_TYPE_TX", "v1": {"tx": tx, "signatures": [
        {"hint": signer.pub[-8:], "signature": sig.hex()}]}}
    return enc.encode("TransactionEnvelope", env), hashlib.sha256(payload).hexdigest()


def tx(source, seq, ops, fee=1000, memo=None, soroban=None):
    return {"sourceAccount": source, "fee": fee, "seqNum": seq, "cond": {"type": "PRECOND_NONE"},
            "memo": memo or {"type": "MEMO_NONE"}, "operations": ops,
            "ext": {"v": 1, "sorobanData": soroban} if soroban else {"v": 0}}


def diagnostics(dec, answer):
    """Readable form of the diagnostic events core returns with a rejected transaction."""
    raw = answer.get("diagnostic_events")
    if not raw:
        return []
    # One base64 string holding an XDR vector of DiagnosticEvent.
    dec.types.setdefault("_DiagnosticEvents", {"k": "typedef", "t": {
        "r": "array", "of": {"r": "ref", "name": "DiagnosticEvent"}, "max": None}})
    try:
        evs = dec.decode("_DiagnosticEvents", base64.b64decode(raw))
    except Exception as err:  # keep the raw text if it does not decode
        return ["undecodable (%s): %s" % (err, str(raw)[:200])]
    return [json.dumps(ev["event"]["body"])[:600] for ev in evs]


def result_code(dec, answer):
    if "error" not in answer:
        return None
    r = dec.decode("TransactionResult", base64.b64decode(answer["error"]))
    return r["result"]["code"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    ap.add_argument("--image", help="stellar-core image (default: the one the scenario names)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--passphrase", choices=sorted(PASSPHRASES), default="testnet")
    ap.add_argument("--keep", action="store_true", help="leave the container running")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit("%s is not empty; use a fresh directory" % out)
    schema = json.load(open(ROOT / "schema/schema.json"))
    enc, dec = Encoder(schema), Decoder(schema)
    image = a.image or SCENARIOS[a.scenario]
    core = Core(out / "core", PASSPHRASES[a.passphrase], image)
    root = Keys(secret=core.network_id)
    payee = Keys("memo payee")
    run = {"scenario": a.scenario, "stellar_core_image": image, "network_passphrase": core.passphrase,
           "root": strkey.account(root.pub), "steps": []}

    def step(name, protocol, blob, txhash, expect):
        answer = core.submit(blob)
        code = result_code(dec, answer)
        rec = {"step": name, "protocol": protocol, "tx_hash": txhash, "status": answer.get("status"),
               "result_code": code, "expected": expect, "diagnostics": diagnostics(dec, answer)}
        if answer.get("status") != "PENDING":
            rec["answer"] = answer
        run["steps"].append(rec)
        print("%-34s p%d  %s %s" % (name, protocol, answer.get("status"), code or ""), flush=True)
        for d in rec["diagnostics"]:
            print("    diagnostic: " + d, flush=True)
        return rec

    try:
        info = core.start()
        run["stellar_core_version"] = info["build"]
        if a.scenario == "muxed-source-p22":
            muxed_source(core, enc, root, step, run, 22, accepted=True)
        elif a.scenario == "muxed-source-refused-p24":
            muxed_source(core, enc, root, step, run, 24, accepted=False)
        else:
            memo_and_offer_p30(core, enc, root, payee, step, run)
    finally:
        if not a.keep:
            core.stop()

    led = out / "ledgers"
    led.mkdir(exist_ok=True)
    for raw in mine.golden_records(core.work / "meta.xdr"):
        v = dec.decode("LedgerCloseMeta", raw)
        seqno = v["v%d" % v["v"]]["ledgerHeader"]["header"]["ledgerSeq"]
        (led / ("%d.xdr" % seqno)).write_bytes(raw)
    (out / "run.json").write_text(json.dumps(run, indent=1) + "\n")
    print("ledgers: %s" % ", ".join(sorted((p.stem for p in led.iterdir()), key=int)))
    print("scenario ledger: %s" % {k: v for k, v in run.items() if k.startswith("ledger_")})


def muxed_source(core, enc, root, step, run, protocol, accepted):
    core.upgrade(protocol)
    preimage = {"type": "CONTRACT_ID_PREIMAGE_FROM_ASSET", "fromAsset": {"type": "ASSET_TYPE_NATIVE"}}
    contract_id = hashlib.sha256(enc.encode("HashIDPreimage", {
        "type": "ENVELOPE_TYPE_CONTRACT_ID",
        "contractID": {"networkID": core.network_id.hex(), "contractIDPreimage": preimage}})).hexdigest()

    def deploy(seq, mux_tx):
        op = {"sourceAccount": None, "body": {
            "type": "INVOKE_HOST_FUNCTION", "invokeHostFunctionOp": {
                "hostFunction": {"type": "HOST_FUNCTION_TYPE_CREATE_CONTRACT", "createContract": {
                    "contractIDPreimage": preimage, "executable": {"type": "CONTRACT_EXECUTABLE_STELLAR_ASSET"}}},
                "auth": []}}}
        soroban = {"ext": {"v": 0}, "resources": {
            "footprint": {"readOnly": [], "readWrite": [{"type": "CONTRACT_DATA", "contractData": {
                "contract": {"type": "SC_ADDRESS_TYPE_CONTRACT", "contractId": contract_id},
                "key": {"type": "SCV_LEDGER_KEY_CONTRACT_INSTANCE"}, "durability": "PERSISTENT"}}]},
            "instructions": 1_000_000, "diskReadBytes": 0, "writeBytes": 1000}, "resourceFee": 10_000_000}
        t = tx(root.muxed(mux_tx), seq, [op], fee=10_000_000 + 10_000, soroban=soroban)
        return envelope(enc, core, t, root)

    blob, h = deploy(1, 2 ** 63 + 7)
    name = "muxed-source-p%d: deploy" % protocol
    if accepted:
        if step(name, protocol, blob, h, "PENDING, applied")["status"] != "PENDING":
            raise SystemExit("the deploy was refused; see the diagnostics above")
        run["ledger_muxed_source_p%d" % protocol] = core.close()
    elif step(name, protocol, blob, h, "ERROR txSOROBAN_INVALID")["status"] != "ERROR":
        raise SystemExit("the deploy was accepted, expected the queue to refuse it")


def memo_and_offer_p30(core, enc, root, payee, step, run):
    seq = 0  # the root account's sequence number at genesis
    # ---- protocol 30: memo bytes that are not UTF-8, and an offer ID beyond 2^53
    core.upgrade(30)
    seq += 1
    t = tx(root.muxed(), seq, [{"sourceAccount": None, "body": {"type": "CREATE_ACCOUNT", "createAccountOp": {
        "destination": payee.account(), "startingBalance": 100_0000000}}}])
    blob, h = envelope(enc, core, t, root)
    step("memo-and-offer-p30: create payee", 30, blob, h, "PENDING, applied")
    created = core.close()  # a new account's sequence number starts at (ledger << 32)
    run["payee"] = strkey.account(payee.pub)
    seq += 1
    t = tx(root.muxed(), seq, [{"sourceAccount": None, "body": {"type": "PAYMENT", "paymentOp": {
        "destination": payee.muxed(), "asset": {"type": "ASSET_TYPE_NATIVE"}, "amount": 1_0000000}}}],
        memo={"type": "MEMO_TEXT", "text": {"$hex": BAD_MEMO.hex()}})
    blob, h = envelope(enc, core, t, root)
    step("memo-and-offer-p30: payment, bad memo", 30, blob, h, "PENDING, applied")
    seq += 1
    usd = {"type": "ASSET_TYPE_CREDIT_ALPHANUM4", "alphaNum4": {"assetCode": b"USD\0".hex(), "issuer": root.account()}}
    t = tx(payee.muxed(), (created << 32) + 1, [{"sourceAccount": None, "body": {
        "type": "MANAGE_SELL_OFFER", "manageSellOfferOp": {
            "selling": {"type": "ASSET_TYPE_NATIVE"}, "buying": usd, "amount": 1_0000000,
            "price": {"n": 1, "d": 1}, "offerID": F64_PLUS_1}}}])
    blob, h = envelope(enc, core, t, payee)
    step("memo-and-offer-p30: offer 2^53+1", 30, blob, h, "PENDING, fails at apply")
    run["ledger_memo_and_offer_p30"] = core.close()


if __name__ == "__main__":
    main()
