"""Oracle mapping for the toy indexer (ADAPTER.md, "the oracle mapping").

The toy stores only participants, so it checks only the RFP's second rule: every participant the
toy stores for a transaction, or for one of its operations, must be an address the transaction's
meta shows (oracle.participants: its ledger entries and events, plus the source and fee-bump
source, and for a successful transaction each operation's source). `expectations` and
`known_issue` are required by the harness and have nothing to do here.
"""

REPORT_INTRO = ["The toy indexer in `adapters/example/toy.py`, in its two variants. A cell is the verdict of "
                "the oracle's participant rule: participants must come from the meta, not the envelope."]


def expectations(changes, network_passphrase):
    return []


def known_issue(expectation):
    return None


def manifest_expectations(exps):
    """The manifest's hand-written expectations are wallet-backend rows (state changes); the toy
    stores none, so none applies."""
    return []


def participant_expectations(records, network_passphrase):
    return [{"expect": "participants_within", "tx_hash": r["tx_hash"], "allowed": r["shown"], "success": r["success"],
             "derived_from": "oracle: addresses the %s transaction's meta shows"
                             % ("successful" if r["success"] else "failed"),
             "via": {"what": "participant", "how": "outside meta", "success": r["success"]}}
            for r in records]
