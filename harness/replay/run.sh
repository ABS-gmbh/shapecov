#!/bin/sh
# Reproduce every result in RESULTS.md from a clean checkout.
#
#   harness/replay/run.sh            the sighting matrix plus every entry at current main
#   harness/replay/run.sh quick      the #729 pair only (pre-fix and fix), both inputs
#
# Needs: Docker, git, python3 (standard library only). Network access is used only to clone
# wallet-backend, pull the images and download the Go modules each commit pins; the indexer
# itself runs on an internal Docker network with no route out.
# Set REPLAY_WORK to reuse clones and builds between runs (default: harness/replay/.work).
set -eu
cd "$(dirname "$0")"

SIGNER=testnet-4437357-signed-payload-signer
# wallet-backend commits, oldest first:
#   79ea2acd  protocol 28 upgrade; a P... signer is silently truncated to 32 bytes  (#716)
#   6e5a5910  #693 adds a length guard; the same ledger now halts ingestion          (#729 bug)
#   2a0a84ea  parent of the #729 fix
#   2c873353  #729 fix: the full signer key is stored
SIGHTING_REFS=79ea2acd1d,6e5a591011,2a0a84ea12523b6c92e278c0c84b443041240095,2c873353c1f0f3c9b145e25a7d009023ad104a1c

case "${1:-full}" in
  quick)
    python3 replay.py run --refs 2a0a84ea12523b6c92e278c0c84b443041240095,2c873353c1f0f3c9b145e25a7d009023ad104a1c \
      --entries "$SIGNER" --inputs rpc,datalake
    ;;
  full)
    python3 replay.py run --refs "$SIGHTING_REFS" --entries "$SIGNER" --inputs rpc,datalake
    # Current main, resolved to a commit now: every LedgerCloseMeta entry in the manifest.
    MAIN=$(git ls-remote https://github.com/stellar/wallet-backend refs/heads/main | cut -f1)
    python3 replay.py run --refs "$MAIN" --all-entries --inputs rpc,datalake --timeout 60
    ;;
  *)
    echo "usage: $0 [quick|full]" >&2
    exit 2
    ;;
esac
echo "see $(pwd)/RESULTS.md"
