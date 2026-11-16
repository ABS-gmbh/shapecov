#!/bin/sh
# Run shapecov-lint over stellar/wallet-backend at one commit and record the JSON report.
#
#   scripts/run-wallet-backend.sh <ref> [extra shapecov-lint flags]
#
# Writes results/wallet-backend-<commit12>.json and .log. See scripts/run-target.sh.
exec "$(dirname "$0")/run-target.sh" wallet-backend https://github.com/stellar/wallet-backend "$@"
