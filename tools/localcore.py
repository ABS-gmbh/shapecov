#!/usr/bin/env python3
"""Produce corpus ledgers from a local stellar-core, for shapes that are rare or absent in history.

  localcore.py --scenario NAME --out DIR [--image IMAGE] [--passphrase testnet|pubnet] [--keep]

Starts a fresh standalone stellar-core in Docker (manual close, no peers, no network
access), runs the scenarios below, and writes every closed ledger's LedgerCloseMeta from core's
own meta stream:

  DIR/ledgers/<seq>.xdr          raw LedgerCloseMeta bytes, exactly as stellar-core emitted them
  DIR/run.json                   what was submitted, core's answer, and which ledger holds what

Transactions are built with tools/encode.py and signed with tools/ed25519.py (no Stellar SDK).
All keys are derived from fixed strings and close times are fixed (4,000,000,000, then + 10,000,000 per ledger), so
every run with the same image and passphrase produces the same ledgers, byte for byte. The network root key is
sha256(passphrase), as on every standalone network.

Scenarios (one per run):
  muxed-source-p22   Protocol 22, stellar-core 22.2.1. Deploy the native Stellar Asset Contract
                     from a transaction whose source is a muxed account; the operation has no
                     source of its own, so it runs as that muxed account, and it carries no
                     authorization entries. Consensus accepts this before protocol 25. Releases
                     from 23.0.0 refuse to queue it at any protocol, and 22.x refuse it only when
                     it carries non-source-account authorization, so 22.2.1 is the newest release
                     that can produce this ledger.
  classic-p22        Protocol 22, stellar-core 22.2.1. One CreateAccount from the root account: a
                     protocol 22 ledger with only a classic transaction, so TransactionMeta
                     v3 and no unified events. Tools that read only v4 meta reject it.
  pools-sponsorship-p30
                     Protocol 30, stellar-core 30.0.0. An issuer with AUTH_REVOCABLE and three assets
                     (AAA, BBB, CCC); a trustor holding shares in two pools that share AAA (AAA/BBB and
                     AAA/CCC). Three recorded ledgers:
                     pool-revoke-two-pools: the issuer clears AAA's authorization on the trustor, so
                       core redeems both pools' shares into claimable balances and removes both
                       pool-share trustlines in one operation (CAP-38).
                     claim-and-sponsor: the trustor claims the BBB balance from that revocation; in
                       another transaction a sponsor pays the reserves of a claimant's new data
                       entry and new signer (CAP-33).
                     sponsorship-transfer: a second sponsor takes over both sponsorships through
                       RevokeSponsorship inside a sponsorship sandwich.
  flags-preauth-p30  Protocol 30, stellar-core 30.0.0. Two recorded ledgers:
                     maintain-liabilities: an issuer moves a trustline from AUTHORIZED to
                       AUTHORIZED_TO_MAINTAIN_LIABILITIES with SetTrustLineFlags (CAP-18).
                     preauth-failed: a transaction authorized only by a pre-auth-tx signer fails at
                       apply (an underfunded payment); core still removes the signer (CAP-28).
  sac-trust-p28      Protocol 28, stellar-core 30.0.0. Create a trustor account, deploy the Stellar
                     Asset Contract for USD issued by the root account, then have the trustor call
                     the contract's trust(trustor) (CAP-73) in a ledger of its own. That creates a
                     trustline with no ChangeTrust operation and no contract event
                     (stellar/wallet-backend#731). Protocol 28 so that wallet-backend commits that
                     pin go-stellar-sdk v0.7.3 can read the ledger.
  participants-p28   Protocol 28, stellar-core 30.0.0. Deploy the native Stellar Asset Contract, then,
                     in two ledgers, a transfer of 1 XLM by a caller who authorizes it, carrying one
                     more authorization entry that no require_auth matches, signed by nobody:
                     planted-auth: an address credential for an account that declares a transfer
                       from itself; the host never checks it, so the account appears only in the
                       envelope (stellar/wallet-backend 9538b3c).
                     declared-deploy: an address credential that declares creating a contract from
                       its address; no contract is created (stellar/wallet-backend 80121f3).
                     Protocol 28 so that commits pinning go-stellar-sdk v0.7.3 can read the ledger.
  failures-p30       Protocol 30, stellar-core 30.0.0. Operations and transactions that fail when they
                     apply, many in one ledger: see tools/localcore_failures.py. Recorded ledgers
                     op-failures, tx-failures-plain, tx-failures-bumped and upgrades.
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
SCENARIOS = {"muxed-source-p22": IMAGE_V22, "classic-p22": IMAGE_V22, "pools-sponsorship-p30": IMAGE,
             "flags-preauth-p30": IMAGE, "muxed-source-refused-p24": IMAGE, "memo-and-offer-p30": IMAGE,
             "sac-trust-p28": IMAGE, "participants-p28": IMAGE, "failures-p30": IMAGE}
NAME = "shapecov-localcore-gen"
PASSPHRASES = {"testnet": "Test SDF Network ; September 2015",
               "pubnet": "Public Global Stellar Network ; September 2015"}
F64_PLUS_1 = 2 ** 53 + 1
CLOSE_TIME_BASE = 4_000_000_000
# In manual-close mode core's own clock runs ahead of the last close by up to about a day between
# requests, and a close time behind it is refused as "too early". A step of 10,000,000 seconds keeps
# every close ahead of it; even 100 ledgers end below core's maximum close time (7,258,118,400).
CLOSE_TIME_STEP = 10_000_000
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
        # Fixed close times make every run byte-for-byte reproducible: the same transactions, keys
        # and close times give the same ledgers.
        before = self.info()["ledger"]["num"]
        self.close_time = getattr(self, "close_time", CLOSE_TIME_BASE) + CLOSE_TIME_STEP
        answer = self.http("manualclose?ledgerSeq=%d&closeTime=%d" % (before + 1, self.close_time))
        if "too early" in json.dumps(answer) or "exception" in answer:
            raise SystemExit("core refused close time %d: %s" % (self.close_time, json.dumps(answer)[:300]))
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


def envelope_multi(enc, core, tx, signers):
    """A v1 envelope signed by every key in `signers`."""
    payload = enc.encode("TransactionSignaturePayload", {
        "networkId": core.network_id.hex(),
        "taggedTransaction": {"type": "ENVELOPE_TYPE_TX", "tx": tx}})
    digest = hashlib.sha256(payload).digest()
    sigs = [{"hint": k.pub[-8:], "signature": ed25519.sign(k.secret, digest).hex()} for k in signers]
    env = {"type": "ENVELOPE_TYPE_TX", "v1": {"tx": tx, "signatures": sigs}}
    return enc.encode("TransactionEnvelope", env), digest.hex()


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
        elif a.scenario == "classic-p22":
            classic_p22(core, enc, root, payee, step, run)
        elif a.scenario == "flags-preauth-p30":
            flags_preauth_p30(core, enc, root, step, run)
        elif a.scenario == "pools-sponsorship-p30":
            pools_sponsorship_p30(core, enc, dec, root, step, run)
        elif a.scenario == "sac-trust-p28":
            sac_trust_p28(core, enc, dec, root, step, run)
        elif a.scenario == "failures-p30":
            import localcore_failures
            localcore_failures.failures(sys.modules[__name__], core, enc, dec, root, step, run, 30)
        elif a.scenario == "participants-p28":
            participants_p28(core, enc, root, step, run)
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


def classic_p22(core, enc, root, payee, step, run):
    core.upgrade(22)
    t = tx(root.muxed(), 1, [{"sourceAccount": None, "body": {"type": "CREATE_ACCOUNT", "createAccountOp": {
        "destination": payee.account(), "startingBalance": 100_0000000}}}])
    blob, h = envelope(enc, core, t, root)
    step("classic-p22: create account", 22, blob, h, "PENDING, applied")
    run["payee"] = strkey.account(payee.pub)
    run["ledger_classic_p22"] = core.close()


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


def op(body_type, field, value, source=None):
    body = {"type": body_type}
    if field:
        body[field] = value
    return {"sourceAccount": source.muxed() if source else None, "body": body}


def last_ledger(core, dec):
    """The newest LedgerCloseMeta core has written, decoded."""
    raws = list(mine.golden_records(core.work / "meta.xdr"))
    return dec.decode("LedgerCloseMeta", raws[-1])


def pools_sponsorship_p30(core, enc, dec, root, step, run):
    core.upgrade(30)
    issuer, trustor, claimant, s1, s2 = (Keys("pools issuer"), Keys("pools trustor"), Keys("pools claimant"),
                                         Keys("sponsor one"), Keys("sponsor two"))
    for name, k in (("issuer", issuer), ("trustor", trustor), ("claimant", claimant), ("sponsor_one", s1),
                    ("sponsor_two", s2)):
        run[name] = strkey.account(k.pub)
    no_opts = {"inflationDest": None, "clearFlags": None, "setFlags": None, "masterWeight": None,
               "lowThreshold": None, "medThreshold": None, "highThreshold": None, "homeDomain": None, "signer": None}
    big = 2 ** 63 - 1

    def asset(code):
        return {"type": "ASSET_TYPE_CREDIT_ALPHANUM4", "alphaNum4": {"assetCode": (code.encode() + b"\0").hex(),
                                                                       "issuer": issuer.account()}}
    aaa, bbb, ccc = asset("AAA"), asset("BBB"), asset("CCC")

    def params(a, b):
        return {"type": "LIQUIDITY_POOL_CONSTANT_PRODUCT", "constantProduct": {"assetA": a, "assetB": b, "fee": 30}}

    def pool_id(a, b):
        return hashlib.sha256(enc.encode("LiquidityPoolParameters", params(a, b))).hexdigest()

    def send(name, t, signers, expect="PENDING, applied"):
        blob, h = envelope_multi(enc, core, t, signers)
        if step("pools-sponsorship-p30: " + name, 30, blob, h, expect)["status"] != "PENDING":
            raise SystemExit("%s was refused; see the diagnostics above" % name)

    # 1. accounts
    send("create accounts", tx(root.muxed(), 1, [
        op("CREATE_ACCOUNT", "createAccountOp", {"destination": k.account(), "startingBalance": 1000_0000000})
        for k in (issuer, trustor, claimant, s1, s2)], fee=5000), [root])
    born = core.close() << 32
    seq = {k.pub: born for k in (issuer, trustor, claimant, s1, s2)}

    def nxt(k):
        seq[k.pub] += 1
        return seq[k.pub]

    # 2. issuer is AUTH_REVOCABLE; trustor trusts AAA, BBB, CCC
    send("issuer sets AUTH_REVOCABLE", tx(issuer.muxed(), nxt(issuer), [
        op("SET_OPTIONS", "setOptionsOp", dict(no_opts, setFlags=2))]), [issuer])
    send("trustor trusts AAA, BBB, CCC", tx(trustor.muxed(), nxt(trustor), [
        op("CHANGE_TRUST", "changeTrustOp", {"line": a, "limit": big}) for a in (aaa, bbb, ccc)], fee=3000), [trustor])
    core.close()
    # 3. issuer pays the trustor
    send("issuer pays the trustor", tx(issuer.muxed(), nxt(issuer), [
        op("PAYMENT", "paymentOp", {"destination": trustor.muxed(), "asset": a, "amount": 1000_0000000})
        for a in (aaa, bbb, ccc)], fee=3000), [issuer])
    core.close()
    # 4. two pools sharing AAA, one deposit each
    price = {"minPrice": {"n": 1, "d": 2}, "maxPrice": {"n": 2, "d": 1}}
    ops = []
    for b in (bbb, ccc):
        ops.append(op("CHANGE_TRUST", "changeTrustOp", {"line": {"type": "ASSET_TYPE_POOL_SHARE",
                                                                 "liquidityPool": params(aaa, b)}, "limit": big}))
        ops.append(op("LIQUIDITY_POOL_DEPOSIT", "liquidityPoolDepositOp", dict(
            {"liquidityPoolID": pool_id(aaa, b), "maxAmountA": 100_0000000, "maxAmountB": 100_0000000}, **price)))
    send("trustor deposits into AAA/BBB and AAA/CCC", tx(trustor.muxed(), nxt(trustor), ops, fee=4000), [trustor])
    core.close()
    run["pools"] = {"AAA/BBB": pool_id(aaa, bbb), "AAA/CCC": pool_id(aaa, ccc)}
    # 5. revoke AAA: both pools redeemed in one operation
    send("issuer revokes AAA on the trustor", tx(issuer.muxed(), nxt(issuer), [
        op("SET_TRUST_LINE_FLAGS", "setTrustLineFlagsOp", {"trustor": trustor.account(), "asset": aaa,
                                                           "clearFlags": 1, "setFlags": 0})]), [issuer])
    run["ledger_pool_revoke_two_pools"] = core.close()
    created = []
    meta = last_ledger(core, dec)
    body = meta["v%d" % meta["v"]]
    for tp in body["txProcessing"]:
        m = tp["txApplyProcessing"]
        for o in (m["v%d" % m["v"]].get("operations") or []):
            for ch in o["changes"]:
                if ch["type"] == "LEDGER_ENTRY_CREATED" and ch["created"]["data"]["type"] == "CLAIMABLE_BALANCE":
                    created.append(ch["created"]["data"]["claimableBalance"])
    run["revocation_claimable_balances"] = len(created)
    bbb_balance = next(cb for cb in created if cb["asset"] == bbb)
    # 6. claim the BBB balance; sponsor a data entry and a signer for the claimant
    send("trustor claims the BBB balance", tx(trustor.muxed(), nxt(trustor), [
        op("CLAIM_CLAIMABLE_BALANCE", "claimClaimableBalanceOp", {"balanceID": bbb_balance["balanceID"]})]), [trustor])
    signer_key = {"type": "SIGNER_KEY_TYPE_ED25519", "ed25519": s2.pub}
    send("sponsor one pays for the claimant's data entry and signer", tx(s1.muxed(), nxt(s1), [
        op("BEGIN_SPONSORING_FUTURE_RESERVES", "beginSponsoringFutureReservesOp", {"sponsoredID": claimant.account()}),
        op("MANAGE_DATA", "manageDataOp", {"dataName": "shapecov", "dataValue": b"1".hex()}, source=claimant),
        op("SET_OPTIONS", "setOptionsOp", dict(no_opts, signer={"key": signer_key, "weight": 1}), source=claimant),
        op("END_SPONSORING_FUTURE_RESERVES", None, None, source=claimant)], fee=4000), [s1, claimant])
    run["ledger_claim_and_sponsor"] = core.close()
    # 7. sponsor two takes both sponsorships over
    data_key = {"type": "DATA", "data": {"accountID": claimant.account(), "dataName": "shapecov"}}
    send("sponsor two takes over both sponsorships", tx(s2.muxed(), nxt(s2), [
        op("BEGIN_SPONSORING_FUTURE_RESERVES", "beginSponsoringFutureReservesOp", {"sponsoredID": s1.account()}),
        op("REVOKE_SPONSORSHIP", "revokeSponsorshipOp", {"type": "REVOKE_SPONSORSHIP_LEDGER_ENTRY",
                                                         "ledgerKey": data_key}, source=s1),
        op("REVOKE_SPONSORSHIP", "revokeSponsorshipOp", {"type": "REVOKE_SPONSORSHIP_SIGNER", "signer": {
            "accountID": claimant.account(), "signerKey": signer_key}}, source=s1),
        op("END_SPONSORING_FUTURE_RESERVES", None, None, source=s1)], fee=4000), [s2, s1])
    run["ledger_sponsorship_transfer"] = core.close()


def flags_preauth_p30(core, enc, root, step, run):
    core.upgrade(30)
    issuer, holder, owner = Keys("liabilities issuer"), Keys("liabilities holder"), Keys("preauth owner")
    for name, k in (("issuer", issuer), ("holder", holder), ("preauth_owner", owner)):
        run[name] = strkey.account(k.pub)
    no_opts = {"inflationDest": None, "clearFlags": None, "setFlags": None, "masterWeight": None,
               "lowThreshold": None, "medThreshold": None, "highThreshold": None, "homeDomain": None, "signer": None}
    lia = {"type": "ASSET_TYPE_CREDIT_ALPHANUM4", "alphaNum4": {"assetCode": b"LIA\0".hex(), "issuer": issuer.account()}}

    def send(name, t, signers, expect="PENDING, applied"):
        blob, h = envelope_multi(enc, core, t, signers)
        if step("flags-preauth-p30: " + name, 30, blob, h, expect)["status"] != "PENDING":
            raise SystemExit("%s was refused; see the diagnostics above" % name)
        return h

    send("create accounts", tx(root.muxed(), 1, [
        op("CREATE_ACCOUNT", "createAccountOp", {"destination": k.account(), "startingBalance": 100_0000000})
        for k in (issuer, holder, owner)], fee=3000), [root])
    born = core.close() << 32
    send("issuer sets AUTH_REVOCABLE", tx(issuer.muxed(), born + 1, [
        op("SET_OPTIONS", "setOptionsOp", dict(no_opts, setFlags=2))]), [issuer])
    send("holder trusts LIA", tx(holder.muxed(), born + 1, [
        op("CHANGE_TRUST", "changeTrustOp", {"line": lia, "limit": 2 ** 63 - 1})]), [holder])
    # The transaction the pre-auth signer will authorize: a payment far beyond the owner's balance,
    # valid to submit, failing at apply with PAYMENT_UNDERFUNDED.
    doomed = tx(owner.muxed(), born + 2, [op("PAYMENT", "paymentOp", {
        "destination": root.muxed(), "asset": {"type": "ASSET_TYPE_NATIVE"}, "amount": 1_000_000_0000000})])
    payload = enc.encode("TransactionSignaturePayload", {
        "networkId": core.network_id.hex(), "taggedTransaction": {"type": "ENVELOPE_TYPE_TX", "tx": doomed}})
    doomed_hash = hashlib.sha256(payload).hexdigest()
    send("owner adds a pre-auth signer for the doomed payment", tx(owner.muxed(), born + 1, [
        op("SET_OPTIONS", "setOptionsOp", dict(no_opts, signer={
            "key": {"type": "SIGNER_KEY_TYPE_PRE_AUTH_TX", "preAuthTx": doomed_hash}, "weight": 1}))]), [owner])
    core.close()
    send("issuer: AUTHORIZED -> AUTHORIZED_TO_MAINTAIN_LIABILITIES", tx(issuer.muxed(), born + 2, [
        op("SET_TRUST_LINE_FLAGS", "setTrustLineFlagsOp", {"trustor": holder.account(), "asset": lia,
                                                           "clearFlags": 1, "setFlags": 2})]), [issuer])
    run["ledger_maintain_liabilities"] = core.close()
    env = {"type": "ENVELOPE_TYPE_TX", "v1": {"tx": doomed, "signatures": []}}
    if step("flags-preauth-p30: the pre-authorized payment, no signatures", 30, enc.encode("TransactionEnvelope", env),
            doomed_hash, "PENDING, fails at apply")["status"] != "PENDING":
        raise SystemExit("the pre-authorized payment was refused")
    run["ledger_preauth_failed"] = core.close()


def sac_trust_p28(core, enc, dec, root, step, run):
    core.upgrade(28)
    trustor = Keys("sac trustor")
    run["trustor"] = strkey.account(trustor.pub)
    usd = {"type": "ASSET_TYPE_CREDIT_ALPHANUM4", "alphaNum4": {"assetCode": b"USD\0".hex(), "issuer": root.account()}}
    preimage = {"type": "CONTRACT_ID_PREIMAGE_FROM_ASSET", "fromAsset": usd}
    sac = hashlib.sha256(enc.encode("HashIDPreimage", {
        "type": "ENVELOPE_TYPE_CONTRACT_ID",
        "contractID": {"networkID": core.network_id.hex(), "contractIDPreimage": preimage}})).hexdigest()
    run["sac"] = strkey.contract(sac)
    instance = {"type": "CONTRACT_DATA", "contractData": {
        "contract": {"type": "SC_ADDRESS_TYPE_CONTRACT", "contractId": sac},
        "key": {"type": "SCV_LEDGER_KEY_CONTRACT_INSTANCE"}, "durability": "PERSISTENT"}}

    def soroban(read_only, read_write):
        return {"ext": {"v": 0}, "resources": {"footprint": {"readOnly": read_only, "readWrite": read_write},
                "instructions": 5_000_000, "diskReadBytes": 20_000, "writeBytes": 5_000},
                "resourceFee": 50_000_000}

    # 1. the trustor account
    t = tx(root.muxed(), 1, [{"sourceAccount": None, "body": {"type": "CREATE_ACCOUNT", "createAccountOp": {
        "destination": trustor.account(), "startingBalance": 1000_0000000}}}])
    blob, h = envelope(enc, core, t, root)
    step("sac-trust-p28: create trustor", 28, blob, h, "PENDING, applied")
    created = core.close()
    # 2. the asset contract for USD:root
    op = {"sourceAccount": None, "body": {"type": "INVOKE_HOST_FUNCTION", "invokeHostFunctionOp": {
        "hostFunction": {"type": "HOST_FUNCTION_TYPE_CREATE_CONTRACT", "createContract": {
            "contractIDPreimage": preimage, "executable": {"type": "CONTRACT_EXECUTABLE_STELLAR_ASSET"}}},
        "auth": []}}}
    t = tx(root.muxed(), 2, [op], fee=50_010_000, soroban=soroban([], [instance]))
    blob, h = envelope(enc, core, t, root)
    if step("sac-trust-p28: deploy USD asset contract", 28, blob, h, "PENDING, applied")["status"] != "PENDING":
        raise SystemExit("the asset contract deploy was refused; see the diagnostics above")
    core.close()
    # 3. trust(trustor), alone in its ledger
    me = {"type": "SCV_ADDRESS", "address": {"type": "SC_ADDRESS_TYPE_ACCOUNT", "accountId": trustor.account()}}
    call = {"contractAddress": {"type": "SC_ADDRESS_TYPE_CONTRACT", "contractId": sac},
            "functionName": "trust", "args": [me]}
    op = {"sourceAccount": None, "body": {"type": "INVOKE_HOST_FUNCTION", "invokeHostFunctionOp": {
        "hostFunction": {"type": "HOST_FUNCTION_TYPE_INVOKE_CONTRACT", "invokeContract": call},
        "auth": [{"credentials": {"type": "SOROBAN_CREDENTIALS_SOURCE_ACCOUNT"},
                  "rootInvocation": {"function": {"type": "SOROBAN_AUTHORIZED_FUNCTION_TYPE_CONTRACT_FN",
                                                  "contractFn": call}, "subInvocations": []}}]}}}
    footprint_ro = [instance, {"type": "ACCOUNT", "account": {"accountID": root.account()}}]
    footprint_rw = [{"type": "ACCOUNT", "account": {"accountID": trustor.account()}},
                    {"type": "TRUSTLINE", "trustLine": {"accountID": trustor.account(), "asset": usd}}]
    t = tx(trustor.muxed(), (created << 32) + 1, [op], fee=50_010_000, soroban=soroban(footprint_ro, footprint_rw))
    blob, h = envelope(enc, core, t, trustor)
    if step("sac-trust-p28: trust(trustor)", 28, blob, h, "PENDING, applied")["status"] != "PENDING":
        raise SystemExit("trust() was refused; see the diagnostics above")
    run["ledger_sac_trust_p28"] = core.close()



def participants_p28(core, enc, root, step, run):
    """Authorization entries that name addresses the ledger never touches."""
    core.upgrade(28)
    preimage = {"type": "CONTRACT_ID_PREIMAGE_FROM_ASSET", "fromAsset": {"type": "ASSET_TYPE_NATIVE"}}
    native = hashlib.sha256(enc.encode("HashIDPreimage", {
        "type": "ENVELOPE_TYPE_CONTRACT_ID",
        "contractID": {"networkID": core.network_id.hex(), "contractIDPreimage": preimage}})).hexdigest()
    run["native_sac"] = strkey.contract(native)
    instance = {"type": "CONTRACT_DATA", "contractData": {
        "contract": {"type": "SC_ADDRESS_TYPE_CONTRACT", "contractId": native},
        "key": {"type": "SCV_LEDGER_KEY_CONTRACT_INSTANCE"}, "durability": "PERSISTENT"}}

    def soroban(read_only, read_write):
        return {"ext": {"v": 0}, "resources": {"footprint": {"readOnly": read_only, "readWrite": read_write},
                "instructions": 5_000_000, "diskReadBytes": 20_000, "writeBytes": 5_000},
                "resourceFee": 50_000_000}

    caller = Keys("participants caller")
    planted = Keys("participants planted")    # named by an auth entry, never touched
    deployer = Keys("participants deployer")  # declares a deploy that never runs
    for name, k in (("caller", caller), ("planted", planted), ("deployer", deployer)):
        run[name] = strkey.account(k.pub)
    # 1. the caller account, and the native asset contract
    t = tx(root.muxed(), 1, [{"sourceAccount": None, "body": {"type": "CREATE_ACCOUNT", "createAccountOp": {
        "destination": caller.account(), "startingBalance": 1000_0000000}}}])
    blob, h = envelope(enc, core, t, root)
    step("participants-p28: create caller", 28, blob, h, "PENDING, applied")
    created = core.close()
    op = {"sourceAccount": None, "body": {"type": "INVOKE_HOST_FUNCTION", "invokeHostFunctionOp": {
        "hostFunction": {"type": "HOST_FUNCTION_TYPE_CREATE_CONTRACT", "createContract": {
            "contractIDPreimage": preimage, "executable": {"type": "CONTRACT_EXECUTABLE_STELLAR_ASSET"}}},
        "auth": []}}}
    t = tx(root.muxed(), 2, [op], fee=50_010_000, soroban=soroban([], [instance]))
    blob, h = envelope(enc, core, t, root)
    if step("participants-p28: deploy native asset contract", 28, blob, h, "PENDING, applied")["status"] != "PENDING":
        raise SystemExit("the native asset contract deploy was refused; see the diagnostics above")
    core.close()

    # 2. two transfers of 1 XLM from the caller to the root account, each in a ledger of its own and
    # each carrying, besides the caller's own source-account authorization, one entry nothing matches.
    # The transfer emits an event, so the meta shows the contract; only the extra entry's addresses
    # are envelope-only.
    def addr(k):
        return {"type": "SC_ADDRESS_TYPE_ACCOUNT", "accountId": k.account()}

    def amount(n):
        return {"type": "SCV_I128", "i128": {"hi": 0, "lo": n}}

    def transfer_call(frm, to):
        return {"contractAddress": {"type": "SC_ADDRESS_TYPE_CONTRACT", "contractId": native},
                "functionName": "transfer",
                "args": [{"type": "SCV_ADDRESS", "address": addr(frm)}, {"type": "SCV_ADDRESS", "address": addr(to)},
                         amount(1_0000000)]}

    def unsigned(k, function):
        return {"credentials": {"type": "SOROBAN_CREDENTIALS_ADDRESS", "address": {
            "address": addr(k), "nonce": 7, "signatureExpirationLedger": 1_000_000,
            "signature": {"type": "SCV_VOID"}}},
            "rootInvocation": {"function": function, "subInvocations": []}}

    call = transfer_call(caller, root)
    own = {"credentials": {"type": "SOROBAN_CREDENTIALS_SOURCE_ACCOUNT"},
           "rootInvocation": {"function": {"type": "SOROBAN_AUTHORIZED_FUNCTION_TYPE_CONTRACT_FN", "contractFn": call},
                              "subInvocations": []}}
    planted_fn = {"type": "SOROBAN_AUTHORIZED_FUNCTION_TYPE_CONTRACT_FN", "contractFn": transfer_call(planted, caller)}
    salt = hashlib.sha256(b"shapecov declared deploy").hexdigest()
    declared = {"type": "CONTRACT_ID_PREIMAGE_FROM_ADDRESS", "fromAddress": {"address": addr(deployer), "salt": salt}}
    run["declared_contract"] = strkey.contract(hashlib.sha256(enc.encode("HashIDPreimage", {
        "type": "ENVELOPE_TYPE_CONTRACT_ID",
        "contractID": {"networkID": core.network_id.hex(), "contractIDPreimage": declared}})).hexdigest())
    deploy_fn = {"type": "SOROBAN_AUTHORIZED_FUNCTION_TYPE_CREATE_CONTRACT_HOST_FN", "createContractHostFn": {
        "contractIDPreimage": declared, "executable": {"type": "CONTRACT_EXECUTABLE_WASM", "wasm_hash": "00" * 32}}}
    footprint_rw = [{"type": "ACCOUNT", "account": {"accountID": caller.account()}},
                    {"type": "ACCOUNT", "account": {"accountID": root.account()}}]
    for n, (name, extra) in enumerate((("planted-auth", unsigned(planted, planted_fn)),
                                       ("declared-deploy", unsigned(deployer, deploy_fn)))):
        op = {"sourceAccount": None, "body": {"type": "INVOKE_HOST_FUNCTION", "invokeHostFunctionOp": {
            "hostFunction": {"type": "HOST_FUNCTION_TYPE_INVOKE_CONTRACT", "invokeContract": call},
            "auth": [own, extra]}}}
        t = tx(caller.muxed(), (created << 32) + 1 + n, [op], fee=50_010_000, soroban=soroban([instance], footprint_rw))
        blob, h = envelope(enc, core, t, caller)
        run["tx_" + name.replace("-", "_")] = h
        if step("participants-p28: " + name, 28, blob, h, "PENDING, applied")["status"] != "PENDING":
            raise SystemExit("%s was refused; see the diagnostics above" % name)
        run["ledger_" + name.replace("-", "_")] = core.close()


if __name__ == "__main__":
    main()
