#!/bin/sh
# Reproduce the results in RESULTS.md from a clean checkout.
#
#   harness/replay/run.sh quick       the #729 pair only (pre-fix and fix), both inputs
#   harness/replay/run.sh sightings   every pair in sightings.json, then `replay.py check`
#   harness/replay/run.sh full        sightings, plus every LedgerCloseMeta entry at current main, then
#                                     fail on any oracle failure that is neither a known issue nor a sighting
#
# Needs: Docker, git, python3 (standard library only). Network access is used only to clone
# wallet-backend, pull the images and download the Go modules each commit pins; the indexer
# itself runs on an internal Docker network with no route out.
# Set REPLAY_WORK to reuse clones and builds between runs (default: harness/replay/.work).
set -eu
cd "$(dirname "$0")"

both="--inputs rpc,datalake"

sightings() {
  # wallet-backend#729 and the signed-payload half of #716
  python3 replay.py run --entries testnet-4437357-signed-payload-signer $both \
    --refs 79ea2acd1dc65a07166133cc04b12e76db314db0,6e5a59101158dc2996295450190142366062cd05,2a0a84ea12523b6c92e278c0c84b443041240095,2c873353c1f0f3c9b145e25a7d009023ad104a1c
  # wallet-backend#731
  python3 replay.py run --entries localcore-sac-trust-p28-5 $both \
    --refs 764a4f5bcbff5abb0949d93da37f769063013ea0,c152783c054c765c8b51fd26ed313fd1ebc1c50c
  # the muxed half of #716, and #693's duplicate-key side effect
  python3 replay.py run --entries localcore-muxed-source-p22-3 $both \
    --refs 79ea2acd1dc65a07166133cc04b12e76db314db0,6e5a59101158dc2996295450190142366062cd05,f8e5786d22c04adad16318f2e126728beec5aac9,bb0b162b072583c7dabffbdee664d1c117e5ba56
  python3 replay.py check
}

case "${1:-full}" in
  quick)
    python3 replay.py run --entries testnet-4437357-signed-payload-signer $both \
      --refs 2a0a84ea12523b6c92e278c0c84b443041240095,2c873353c1f0f3c9b145e25a7d009023ad104a1c
    ;;
  sightings)
    sightings
    ;;
  full)
    sightings
    # Current main, resolved to a commit now: every LedgerCloseMeta entry in the manifest.
    MAIN=$(git ls-remote https://github.com/stellar/wallet-backend refs/heads/main | cut -f1)
    python3 replay.py run --refs "$MAIN" --all-entries $both --timeout 60
    python3 replay.py check --oracle
    ;;
  *)
    echo "usage: $0 [quick|sightings|full]" >&2
    exit 2
    ;;
esac
echo "see $(pwd)/RESULTS.md"
