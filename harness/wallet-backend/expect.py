"""Write the indexer expectations for one corpus entry, for replay.sh.

  expect.py <entry id>   -> JSON on stdout

Everything here comes from the corpus manifest. Nothing comes from an indexer.
"""
import json
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent.parent / "corpus"
manifest = json.load(open(CORPUS / "manifest.json"))
entry = next(e for e in manifest["entries"] if e["id"] == sys.argv[1])
if entry["xdr_type"] != "LedgerCloseMeta" or entry["source"]["kind"] != "network_ledger":
    sys.exit("replay needs a LedgerCloseMeta entry from a network ledger")
print(json.dumps({
    "entry_id": entry["id"],
    "network_passphrase": entry["source"]["network_passphrase"],
    "signer_keys": [x["signer_key"] for x in entry["expected"].get("indexer", []) if x["expect"] == "signer_state_change"],
}))
