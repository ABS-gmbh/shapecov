#!/bin/sh
# Run shapecov-lint over stellar/wallet-backend at one commit and record the JSON report.
#
#   scripts/run-wallet-backend.sh <ref> [extra shapecov-lint flags]
#
# Writes results/wallet-backend-<commit12>.json (the tool's own output) and .log (stderr).
# Network is used to clone wallet-backend and download the modules the commit pins; the
# linter itself runs with --network none. Clones live in $LINT_WORK (default: linter/.work).
set -eu
REF=${1:?usage: run-wallet-backend.sh <ref> [flags]}
shift
HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=${LINT_WORK:-$HERE/.work}
IMG=${GO_IMAGE:-golang:1.26}
mkdir -p "$WORK" "$HERE/results"
CLONE=$WORK/wallet-backend
[ -d "$CLONE/.git" ] || git clone -q https://github.com/stellar/wallet-backend "$CLONE"
git -C "$CLONE" cat-file -e "$REF^{commit}" 2>/dev/null || git -C "$CLONE" fetch -q origin
SHA=$(git -C "$CLONE" rev-parse "$REF^{commit}")
SRC=$WORK/src/$SHA
if [ ! -d "$SRC" ]; then
  mkdir -p "$SRC"
  git -C "$CLONE" archive "$SHA" | tar -x -C "$SRC"
fi
VOLS="-v $HERE:/linter:ro -v $SRC:/target:ro -v shapecov-linter-gomod:/go/pkg/mod -v shapecov-linter-gobuild:/root/.cache/go-build -v $WORK/bin:/bin-out"
mkdir -p "$WORK/bin"
docker run --rm --name shapecov-linter-build $VOLS -e GOFLAGS=-mod=readonly "$IMG" sh -ec '
  cd /linter && go build -o /bin-out/shapecov-lint ./cmd/shapecov-lint
  cd /target && go mod download'
OUT=$HERE/results/wallet-backend-$(echo "$SHA" | cut -c1-12)
set +e
docker run --rm --name shapecov-linter-run --network none -e GOPROXY=off -e GOFLAGS=-mod=readonly $VOLS "$IMG" \
  /bin-out/shapecov-lint -C /target "$@" ./... > "$OUT.json" 2> "$OUT.log"
CODE=$?
set -e
echo "wallet-backend $SHA $(git -C "$CLONE" show -s --format='%cI %s' "$SHA")" >> "$OUT.log"
echo "exit code $CODE" >> "$OUT.log"
cat "$OUT.log"
