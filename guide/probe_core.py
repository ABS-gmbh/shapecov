#!/usr/bin/env python3
"""Ask a local stellar-core what it does with values the guide says it checks.

  python3 guide/probe_core.py run   [--out guide/probes.json]   run every probe, write the records
  python3 guide/probe_core.py check                              run every probe, compare with guide/probes.json

For each "Checked" claim in the guide's section 1 tables that a transaction can break, a probe
builds a transaction that breaks it and submits it to a fresh standalone stellar-core 30.0.0 at
protocol 30. A probe records what core did with it:
- rejected at submission, with the transaction result code and the operation result codes;
- accepted, then failed when the ledger closed, with the codes from the ledger;
- rejected as undecodable, for values beyond an XDR length limit.

Probes that pass validation on purpose (controls) show where the line is. Transactions are built
with tools/encode.py, signed with tools/ed25519.py and submitted through tools/localcore.py's
Core class, which this script uses as a library. It runs in its own container
(shapecov-guide-probes), so it never touches a localcore.py run. Keys and close times are fixed,
so a run is reproducible. Needs Docker and the stellar-core image localcore.py names.

`check` exits 1 when any probe's outcome differs from the committed record.
"""
import argparse
import base64
import hashlib
import json
import re
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
import localcore as lc  # noqa: E402
import strkey  # noqa: E402
from decode import Decoder  # noqa: E402
from encode import Encoder  # noqa: E402

lc.NAME = "shapecov-guide-probes"  # never the container localcore.py itself uses
PROTOCOL = 30
DEFAULT_OUT = HERE / "probes.json"


def codes(v):
    """Every result code in a decoded result, in order, without repeats (opINNER is dropped)."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            for k, y in x.items():
                if k == "code" and isinstance(y, str) and y not in out and y != "opINNER":
                    out.append(y)
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(v)
    return out


def host_errors(meta):
    """The distinct SCError values in a transaction's diagnostic events, as TYPE/CODE."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("type") == "SCV_ERROR" and isinstance(x.get("error"), dict):
                e = x["error"]
                code = e.get("code", e.get("contractCode"))
                s = "%s/%s" % (e.get("type"), code)
                if s not in out:
                    out.append(s)
            for y in x.values():
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(meta)
    return out


def replace_once(blob, old, new):
    if blob.count(old) != 1:
        raise SystemExit("patch target found %d times" % blob.count(old))
    return blob.replace(old, new)


def xdr_opaque(b):
    return struct.pack(">I", len(b)) + b + b"\0" * ((4 - len(b) % 4) % 4)


class Probes:
    def __init__(self, work):
        schema = json.load(open(ROOT / "schema/schema.json"))
        self.enc, self.dec = Encoder(schema), Decoder(schema)
        self.core = lc.Core(Path(work) / "core", lc.PASSPHRASES["testnet"])
        self.root = lc.Keys(secret=self.core.network_id)
        self.seq = 0
        self.records = []

    # ---- building and submitting
    def tx(self, ops, memo=None, cond=None, source=None, fee=1000, soroban=None):
        t = lc.tx(source or self.root.muxed(), self.seq + 1, ops, fee=fee, memo=memo, soroban=soroban)
        if cond:
            t["cond"] = cond
        return t

    def sign(self, t):
        blob, _ = lc.envelope(self.enc, self.core, t, self.root)
        return blob

    def submit(self, pid, row, rule, blob, expect, note="", host=None):
        answer = self.core.submit(blob)
        status = answer.get("status")
        rec = {"id": pid, "row": row, "rule": rule, "expect": expect + ("; host error: " + host if host else ""),
               "note": note}
        if status == "ERROR" and "error" in answer:
            r = self.dec.decode("TransactionResult", base64.b64decode(answer["error"]))
            rec["outcome"] = "rejected at submission: " + " / ".join(codes(r["result"]))
        elif status == "PENDING":
            self.core.close()
            self.seq += 1
            rec["outcome"] = "accepted; when applied: " + self.applied(blob)
        elif status is None and ("exception" in answer or "raw" in answer):
            text = answer.get("exception") or answer.get("raw") or ""
            rec["outcome"] = "rejected: not decodable (%s)" % text.strip().splitlines()[0][:120] if text else \
                "rejected: not decodable"
        else:
            rec["outcome"] = "status %s: %s" % (status, json.dumps(answer)[:160])
        rec["agrees"] = rec["outcome"].startswith(expect) and (host is None or "host error: " + host in rec["outcome"])
        self.records.append(rec)
        print("%-34s %s" % (pid, rec["outcome"]), flush=True)
        return rec

    def applied(self, blob):
        """The result codes of the transaction in the ledger core just closed."""
        lcm = lc.last_ledger(self.core, self.dec)
        body = lcm["v%d" % lcm["v"]]
        env = self.dec.decode("TransactionEnvelope", blob)
        tx_bytes = self.enc.encode("TransactionSignaturePayload", {
            "networkId": self.core.network_id.hex(),
            "taggedTransaction": {"type": "ENVELOPE_TYPE_TX", "tx": env["v1"]["tx"]}})
        h = hashlib.sha256(tx_bytes).hexdigest()
        for p in body["txProcessing"]:
            if p["result"]["transactionHash"] == h:
                r = p["result"]["result"]
                text = "%s (fee charged: %d stroops)" % (" / ".join(codes(r["result"])), r["feeCharged"])
                errs = host_errors(p["txApplyProcessing"])
                return text + ("; host error: " + ", ".join(errs) if errs else "")
        raise SystemExit("the accepted transaction is not in the closed ledger")

    # ---- the probes
    def run(self):
        core, enc = self.core, self.enc
        info = core.start()
        self.version = info["build"]
        core.upgrade(PROTOCOL)
        other = lc.Keys("guide probe other")
        native = {"type": "ASSET_TYPE_NATIVE"}

        def op(body_type, field, value):
            return lc.op(body_type, field, value)

        # Memo text
        memo28 = {"type": "MEMO_TEXT", "text": "x" * 28}
        t = self.tx([op("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": 0})], memo=memo28)
        blob = replace_once(self.sign(t), xdr_opaque(b"x" * 28), xdr_opaque(b"x" * 29))
        self.submit("memo-text-29-bytes", "Memo text", "at most 28 bytes", blob, "rejected: not decodable")

        sac_preimage = {"type": "CONTRACT_ID_PREIMAGE_FROM_ASSET", "fromAsset": native}
        sac = hashlib.sha256(enc.encode("HashIDPreimage", {
            "type": "ENVELOPE_TYPE_CONTRACT_ID",
            "contractID": {"networkID": core.network_id.hex(), "contractIDPreimage": sac_preimage}})).hexdigest()
        instance = {"type": "CONTRACT_DATA", "contractData": {
            "contract": {"type": "SC_ADDRESS_TYPE_CONTRACT", "contractId": sac},
            "key": {"type": "SCV_LEDGER_KEY_CONTRACT_INSTANCE"}, "durability": "PERSISTENT"}}

        def soroban(ro, rw):
            return {"ext": {"v": 0}, "resources": {"footprint": {"readOnly": ro, "readWrite": rw},
                    "instructions": 5_000_000, "diskReadBytes": 20_000, "writeBytes": 5_000}, "resourceFee": 50_000_000}

        deploy_op = {"sourceAccount": None, "body": {"type": "INVOKE_HOST_FUNCTION", "invokeHostFunctionOp": {
            "hostFunction": {"type": "HOST_FUNCTION_TYPE_CREATE_CONTRACT", "createContract": {
                "contractIDPreimage": sac_preimage, "executable": {"type": "CONTRACT_EXECUTABLE_STELLAR_ASSET"}}},
            "auth": []}}}
        t = self.tx([deploy_op], memo={"type": "MEMO_TEXT", "text": "hi"}, fee=50_010_000,
                    soroban=soroban([], [instance]))
        self.submit("memo-on-contract-invocation", "Memo text", "no memo on a contract invocation from protocol 25",
                    self.sign(t), "rejected at submission: txSOROBAN_INVALID")

        # Muxed source of a contract invocation
        t = self.tx([deploy_op], source=self.root.muxed(7), fee=50_010_000, soroban=soroban([], [instance]))
        self.submit("muxed-source-contract-invocation", "Muxed source of a contract invocation",
                    "invalid from protocol 25", self.sign(t), "rejected at submission: txSOROBAN_INVALID")

        # Signed-payload signer
        def signed_payload(payload):
            return {"type": "SIGNER_KEY_TYPE_ED25519_SIGNED_PAYLOAD",
                    "ed25519SignedPayload": {"ed25519": other.pub, "payload": payload.hex()}}

        def set_options(**kw):
            body = {k: None for k in ("inflationDest", "clearFlags", "setFlags", "masterWeight", "lowThreshold",
                                      "medThreshold", "highThreshold", "homeDomain", "signer")}
            body.update(kw)
            return op("SET_OPTIONS", "setOptionsOp", body)

        t = self.tx([set_options(signer={"key": signed_payload(b""), "weight": 1})])
        self.submit("signed-payload-signer-empty", "Signed-payload signer (`SetOptions` signer, `extraSigners`)",
                    "payload not empty", self.sign(t), "rejected at submission")
        t = self.tx([set_options(signer={"key": signed_payload(b"p" * 64), "weight": 1})])
        blob = replace_once(self.sign(t), xdr_opaque(b"p" * 64), xdr_opaque(b"p" * 65))
        self.submit("signed-payload-signer-65-bytes", "Signed-payload signer (`SetOptions` signer, `extraSigners`)",
                    "payload at most 64 bytes", blob, "rejected: not decodable")

        def v2(extra):
            return {"type": "PRECOND_V2", "v2": {"timeBounds": None, "ledgerBounds": None, "minSeqNum": None,
                                                 "minSeqAge": 0, "minSeqLedgerGap": 0, "extraSigners": extra}}
        bump = op("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": 0})
        key = signed_payload(b"abcd")
        t = self.tx([bump], cond=v2([key, key]))
        self.submit("extra-signers-repeated", "Signed-payload signer (`SetOptions` signer, `extraSigners`)",
                    "not the same key twice", self.sign(t), "rejected at submission: txMALFORMED")
        key2 = signed_payload(b"wxyz")
        t = self.tx([bump], cond=v2([key, key2]))
        blob = self.sign(t)
        two = struct.pack(">I", 2) + enc.encode("SignerKey", key) + enc.encode("SignerKey", key2)
        three = struct.pack(">I", 3) + enc.encode("SignerKey", key) + enc.encode("SignerKey", key2) + \
            enc.encode("SignerKey", signed_payload(b"3333"))
        self.submit("extra-signers-three", "Signed-payload signer (`SetOptions` signer, `extraSigners`)",
                    "at most two extraSigners", replace_once(blob, two, three), "rejected: not decodable")

        # ManageData
        def manage_data(name, value):
            return op("MANAGE_DATA", "manageDataOp", {"dataName": name, "dataValue": value})
        t = self.tx([manage_data({"$hex": b"\x01bad".hex()}, "00")])
        self.submit("manage-data-name-control-char", "`ManageData` name", "each byte printable ASCII",
                    self.sign(t), "rejected at submission: txFAILED / MANAGE_DATA_INVALID_NAME")
        t = self.tx([manage_data("", "00")])
        self.submit("manage-data-name-empty", "`ManageData` name", "1 to 64 bytes", self.sign(t),
                    "rejected at submission: txFAILED / MANAGE_DATA_INVALID_NAME")
        t = self.tx([manage_data("guide", (b"v" * 64).hex())])
        blob = replace_once(self.sign(t), xdr_opaque(b"v" * 64), xdr_opaque(b"v" * 65))
        self.submit("manage-data-value-65-bytes", "`ManageData` value", "at most 64 bytes", blob,
                    "rejected: not decodable")
        t = self.tx([manage_data("guide", "00ff0a")])
        self.submit("manage-data-value-any-bytes", "`ManageData` value", "the bytes are not checked",
                    self.sign(t), "accepted; when applied: txSUCCESS", note="the value is 00 ff 0a")

        # Home domain
        t = self.tx([set_options(homeDomain={"$hex": b"a\x01b".hex()})])
        self.submit("home-domain-control-char", "Home domain", "each byte printable ASCII", self.sign(t),
                    "rejected at submission: txFAILED / SET_OPTIONS_INVALID_HOME_DOMAIN")
        t = self.tx([set_options(homeDomain="d" * 32)])
        blob = replace_once(self.sign(t), xdr_opaque(b"d" * 32), xdr_opaque(b"d" * 33))
        self.submit("home-domain-33-bytes", "Home domain", "at most 32 bytes", blob, "rejected: not decodable")
        t = self.tx([set_options(homeDomain="not a domain!")])
        self.submit("home-domain-not-a-domain", "Home domain", "domain syntax is not checked", self.sign(t),
                    "accepted; when applied: txSUCCESS", note="the home domain is the text 'not a domain!'")

        # Asset code
        def alnum4(code, issuer):
            return {"type": "ASSET_TYPE_CREDIT_ALPHANUM4",
                    "alphaNum4": {"assetCode": code.hex(), "issuer": issuer.account()}}

        def change_trust(line):
            return op("CHANGE_TRUST", "changeTrustOp", {"line": line, "limit": 1000})
        t = self.tx([change_trust(alnum4(b"A-B\0", other))])
        self.submit("asset-code-punctuation", "Asset code", "letters and digits only", self.sign(t),
                    "rejected at submission: txFAILED / CHANGE_TRUST_MALFORMED")
        t = self.tx([change_trust(alnum4(b"A\0B\0", other))])
        self.submit("asset-code-nul-inside", "Asset code", "NUL only as trailing padding", self.sign(t),
                    "rejected at submission: txFAILED / CHANGE_TRUST_MALFORMED")

        # Liquidity-pool asset pair: two issuers whose strkey text order is the reverse of their
        # key byte order.
        i = 0
        while True:
            a, b = lc.Keys("guide probe issuer a %d" % i), lc.Keys("guide probe issuer b %d" % i)
            ka, kb = bytes.fromhex(a.pub), bytes.fromhex(b.pub)
            sa, sb = strkey.account(a.pub), strkey.account(b.pub)
            if (ka < kb) != (sa < sb):
                break
            i += 1
        lo, hi = (a, b) if ka < kb else (b, a)  # lo < hi as bytes, hi < lo as strkey text

        def pool(first, second):
            return {"type": "ASSET_TYPE_POOL_SHARE", "liquidityPool": {
                "type": "LIQUIDITY_POOL_CONSTANT_PRODUCT", "constantProduct": {
                    "assetA": alnum4(b"USD\0", first), "assetB": alnum4(b"USD\0", second), "fee": 30}}}
        t = self.tx([change_trust(pool(hi, lo))])
        self.submit("pool-pair-in-strkey-order", "Liquidity-pool asset pair",
                    "assetA < assetB as XDR values, not strkey text", self.sign(t),
                    "rejected at submission: txFAILED / CHANGE_TRUST_MALFORMED",
                    note="issuers %s and %s: in strkey text order, which is the reverse of key byte order"
                    % (strkey.account(hi.pub), strkey.account(lo.pub)))
        t = self.tx([change_trust(pool(lo, hi))])
        self.submit("pool-pair-in-byte-order", "Liquidity-pool asset pair",
                    "control: the same pair in key byte order passes validation", self.sign(t),
                    "accepted; when applied", note="it then fails because the account holds no USD trustlines")

        # Claim predicates and claimants
        def nested_not(depth):
            p = {"type": "CLAIM_PREDICATE_UNCONDITIONAL"}
            for _ in range(depth):
                p = {"type": "CLAIM_PREDICATE_NOT", "notPredicate": p}
            return p

        def claimable(claimants):
            return op("CREATE_CLAIMABLE_BALANCE", "createClaimableBalanceOp", {
                "asset": native, "amount": 1_0000000, "claimants": [
                    {"type": "CLAIMANT_TYPE_V0", "v0": {"destination": k.account(), "predicate": p}}
                    for k, p in claimants]})
        # Core counts the unconditional leaf as a level: three NOTs over it are 4 levels.
        t = self.tx([claimable([(other, nested_not(3))])])
        self.submit("claim-predicate-4-levels", "Claim predicates and claimants",
                    "control: 4 levels (three NOTs over an unconditional leaf)",
                    self.sign(t), "accepted; when applied: txSUCCESS")
        t = self.tx([claimable([(other, nested_not(4))])])
        self.submit("claim-predicate-5-levels", "Claim predicates and claimants",
                    "at most 4 levels (four NOTs over an unconditional leaf are 5)",
                    self.sign(t), "rejected at submission: txFAILED / CREATE_CLAIMABLE_BALANCE_MALFORMED")
        uncond = {"type": "CLAIM_PREDICATE_UNCONDITIONAL"}
        t = self.tx([claimable([(other, uncond), (other, uncond)])])
        self.submit("claimant-repeated", "Claim predicates and claimants", "no repeated destination",
                    self.sign(t), "rejected at submission: txFAILED / CREATE_CLAIMABLE_BALANCE_MALFORMED")

        # Path payment path
        hops = [alnum4(("P%d\0\0" % k).encode()[:4], other) for k in range(5)]
        t = self.tx([op("PATH_PAYMENT_STRICT_SEND", "pathPaymentStrictSendOp", {
            "sendAsset": native, "sendAmount": 1, "destination": other.muxed(), "destAsset": native,
            "destMin": 1, "path": hops})])
        blob = self.sign(t)
        five = struct.pack(">I", 5) + b"".join(enc.encode("Asset", h) for h in hops)
        six = struct.pack(">I", 6) + b"".join(enc.encode("Asset", h) for h in hops) + enc.encode("Asset", hops[0])
        self.submit("path-6-hops", "Path payment path", "at most 5 hops", replace_once(blob, five, six),
                    "rejected: not decodable")
        t = self.tx([op("PATH_PAYMENT_STRICT_SEND", "pathPaymentStrictSendOp", {
            "sendAsset": native, "sendAmount": 1, "destination": other.muxed(), "destAsset": native,
            "destMin": 1, "path": [hops[0], hops[0]]})])
        self.submit("path-repeated-hops", "Path payment path", "repeated hops are not checked", self.sign(t),
                    "accepted; when applied", note="the path names the same asset twice; it passes validation")

        # Operations per transaction
        t = self.tx([])
        self.submit("operations-none", "Operations per transaction", "at least 1", self.sign(t),
                    "rejected at submission: txMISSING_OPERATION")
        ops = [op("BUMP_SEQUENCE", "bumpSequenceOp", {"bumpTo": k}) for k in range(100)]
        t = self.tx(ops)
        blob = self.sign(t)
        hundred = struct.pack(">I", 100) + enc.encode("Operation", ops[0])
        hundred_one = struct.pack(">I", 101) + enc.encode("Operation", ops[0]) + enc.encode("Operation", ops[0])
        self.submit("operations-101", "Operations per transaction", "at most 100", replace_once(blob, hundred, hundred_one),
                    "rejected: not decodable")

        # Signatures per envelope
        t = self.tx([bump])
        blob = self.sign(t)
        env = self.dec.decode("TransactionEnvelope", blob)
        sig = enc.encode("DecoratedSignature", env["v1"]["signatures"][0])
        blob = replace_once(blob, struct.pack(">I", 1) + sig, struct.pack(">I", 21) + sig * 21)
        self.submit("signatures-21", "Signatures per envelope", "at most 20", blob, "rejected: not decodable")

        # Offer ID
        usd = alnum4(b"USD\0", self.root)
        t = self.tx([op("MANAGE_SELL_OFFER", "manageSellOfferOp", {
            "selling": native, "buying": usd, "amount": 1_0000000, "price": {"n": 1, "d": 1}, "offerID": -1})])
        self.submit("offer-id-negative", "Offer ID", "not negative", self.sign(t),
                    "rejected at submission: txFAILED / MANAGE_SELL_OFFER_MALFORMED")

        # Destination and operation-source accounts: checked only when applied
        t = self.tx([op("PAYMENT", "paymentOp", {"destination": other.muxed(), "asset": native,
                                                  "amount": 1_0000000})])
        self.submit("payment-to-missing-account", "Destination and operation-source accounts",
                    "checked when applied, not when accepted", self.sign(t),
                    "accepted; when applied: txFAILED / PAYMENT_NO_DESTINATION")

        # Contract values, through the native Stellar Asset Contract. Each call is meant to fail;
        # the host's error code in the diagnostic events shows which check failed it.
        t = self.tx([deploy_op], fee=50_010_000, soroban=soroban([], [instance]))
        self.submit("deploy-native-asset-contract", "(setup)", "deploy the native Stellar Asset Contract",
                    self.sign(t), "accepted; when applied: txSUCCESS")

        def call(name, args):
            c = {"contractAddress": {"type": "SC_ADDRESS_TYPE_CONTRACT", "contractId": sac},
                 "functionName": name, "args": args}
            return {"sourceAccount": None, "body": {"type": "INVOKE_HOST_FUNCTION", "invokeHostFunctionOp": {
                "hostFunction": {"type": "HOST_FUNCTION_TYPE_INVOKE_CONTRACT", "invokeContract": c}, "auth": []}}}

        def nested_vec(depth):
            v = {"type": "SCV_U32", "u32": 1}
            for _ in range(depth - 1):
                v = {"type": "SCV_VEC", "vec": [v]}
            return v

        def invoke(pid, row, rule, name, args, host, note=""):
            t = self.tx([call(name, args)], fee=50_010_000, soroban=soroban([instance], []))
            return self.submit(pid, row, rule, self.sign(t),
                               "accepted; when applied: txFAILED / INVOKE_HOST_FUNCTION_TRAPPED", note=note, host=host)

        nest = "Nesting of contract values (`ScVal`)"
        invoke("scval-arg-2-levels", nest, "control: a wrong-typed argument 2 levels deep", "balance",
               [nested_vec(2)], "SCE_VALUE/SCEC_UNEXPECTED_TYPE", note="fails on the argument's type, not on depth")
        invoke("scval-arg-100-levels", nest, "control: 100 levels", "balance", [nested_vec(100)],
               "SCE_VALUE/SCEC_UNEXPECTED_TYPE", note="still fails on the argument's type, not on depth")
        invoke("scval-arg-101-levels", nest, "at most 100 levels for a value the host reads", "balance",
               [nested_vec(101)], "SCE_CONTEXT/SCEC_EXCEEDED_LIMIT")
        invoke("symbol-invalid-char", "Symbols (`ScSymbol`)", "only [_0-9A-Za-z]", "bal-ance",
               [nested_vec(1)], "SCE_VALUE/SCEC_INVALID_INPUT", note="the function name is the symbol bal-ance")
        invoke("string-arg-not-utf8", "Contract strings (`ScString`)", "UTF-8 and NUL not checked", "balance",
               [{"type": "SCV_STRING", "str": {"$hex": b"\xff\xfe\x00A".hex()}}], "SCE_VALUE/SCEC_UNEXPECTED_TYPE",
               note="the host takes the bytes ff fe 00 41 as a string and fails only because balance() wants an "
                    "address, as for any wrong-typed argument; a symbol with a bad byte fails as SCEC_INVALID_INPUT")
        unsorted = {"type": "SCV_MAP", "map": [{"key": {"type": "SCV_U32", "u32": 2}, "val": nested_vec(1)},
                                               {"key": {"type": "SCV_U32", "u32": 1}, "val": nested_vec(1)}]}
        invoke("map-keys-unsorted", "Maps (`ScMap`)", "keys strictly ascending", "balance", [unsorted],
               "SCE_OBJECT/SCEC_INVALID_INPUT")
        sorted_map = {"type": "SCV_MAP", "map": list(reversed(unsorted["map"]))}
        invoke("map-keys-sorted", "Maps (`ScMap`)", "control: the same map with sorted keys", "balance",
               [sorted_map], "SCE_VALUE/SCEC_UNEXPECTED_TYPE", note="fails on the argument's type, not on key order")
        core.stop()


def run_probes():
    with tempfile.TemporaryDirectory(prefix="guide-probes-", ignore_cleanup_errors=True) as work:
        p = Probes(work)
        try:
            p.run()
        finally:
            p.core.stop()
        return {"stellar_core": p.version, "image": lc.IMAGE, "protocol": PROTOCOL,
                "network_passphrase": p.core.passphrase, "probes": p.records}


def same(outcome):
    """An outcome without the fee amount, which is not part of any claim and may change with core."""
    return re.sub(r"fee charged: \d+ stroops", "fee charged", outcome)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "check"])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    got = run_probes()
    bad = [r["id"] for r in got["probes"] if not r["agrees"]]
    if a.cmd == "run":
        Path(a.out).write_text(json.dumps(got, indent=1) + "\n")
        print("wrote %s: %d probes, %d disagree with their expectation" % (a.out, len(got["probes"]), len(bad)))
        return 1 if bad else 0
    want = json.load(open(DEFAULT_OUT))
    old = {r["id"]: same(r["outcome"]) for r in want["probes"]}
    new = {r["id"]: same(r["outcome"]) for r in got["probes"]}
    diff = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    for k in diff:
        print("CHANGED %s\n  recorded: %s\n  now:      %s" % (k, old.get(k), new.get(k)))
    print("PROBES OK" if not diff and not bad else "PROBES DIFFER (%d changed, %d disagree)" % (len(diff), len(bad)))
    return 1 if diff or bad else 0


if __name__ == "__main__":
    sys.exit(main())
