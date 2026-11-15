"""Check "transactions_decode" for py-stellar-base. Same contract as tx_decode.mjs.

  python tx_decode.py < txcases.tsv > results.tsv
"""
import sys

from stellar_sdk import FeeBumpTransactionEnvelope, TransactionBuilder

for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    entry, index, passphrase, b64, want_hash, ops, source = line.split("\t")[:7]
    status, detail = "pass", ""
    try:
        te = TransactionBuilder.from_xdr(b64, passphrase)
        if isinstance(te, FeeBumpTransactionEnvelope):
            got_ops = len(te.transaction.inner_transaction_envelope.transaction.operations)
            fs = te.transaction.fee_source
            got_source = fs.account_muxed or fs.account_id
        else:
            got_ops = len(te.transaction.operations)
            s = te.transaction.source
            got_source = s.account_muxed or s.account_id
        wrong = []
        if te.hash_hex() != want_hash:
            wrong.append(f"hash {te.hash_hex()}")
        if str(got_ops) != ops:
            wrong.append(f"operations {got_ops} (expected {ops})")
        if got_source != source:
            wrong.append(f"source {got_source} (expected {source})")
        if wrong:
            status, detail = "mishandled", "; ".join(wrong)
    except Exception as e:  # noqa: BLE001
        status, detail = "error", f"{type(e).__name__}: {e}".split("\n")[0][:200]
    print("\t".join([entry, index, status, detail]))
