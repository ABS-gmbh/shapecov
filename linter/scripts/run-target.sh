#!/bin/sh
# Run shapecov-lint over a Go repository at one commit and record the JSON report.
#
#   scripts/run-target.sh <name> <git url> <ref> [extra shapecov-lint flags]
#
# Writes results/<name>-<commit12>.json (the tool's own output) and .log (stderr).
# Network is used to clone the repository and download the modules the commit pins; the
# linter itself runs with --network none. Clones live in $LINT_WORK (default: linter/.work).
# GO_IMAGE picks the Go image (default golang:1.26; stellar-etl needs golang:1.27). DOCKER_PLATFORM
# (for example linux/amd64) runs it under another platform: stellar-etl's cgo dependency ships an
# arm64 library that Go's cgo flag check rejects, so on an arm64 machine lint it as amd64.
set -eu
NAME=${1:?usage: run-target.sh <name> <git url> <ref> [flags]}
URL=${2:?usage: run-target.sh <name> <git url> <ref> [flags]}
REF=${3:?usage: run-target.sh <name> <git url> <ref> [flags]}
shift 3
HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=${LINT_WORK:-$HERE/.work}
IMG=${GO_IMAGE:-golang:1.26}
PLAT=${DOCKER_PLATFORM:+--platform $DOCKER_PLATFORM}
mkdir -p "$WORK" "$HERE/results"
CLONE=$WORK/$NAME
[ -d "$CLONE/.git" ] || git clone -q "$URL" "$CLONE"
git -C "$CLONE" cat-file -e "$REF^{commit}" 2>/dev/null || git -C "$CLONE" fetch -q origin
SHA=$(git -C "$CLONE" rev-parse "$REF^{commit}")
SRC=$WORK/src/$SHA
if [ ! -d "$SRC" ]; then
  mkdir -p "$SRC"
  git -C "$CLONE" archive "$SHA" | tar -x -C "$SRC"
fi
BIN=$WORK/bin${DOCKER_PLATFORM:+-$(echo "$DOCKER_PLATFORM" | tr / -)}
VOLS="-v $HERE:/linter:ro -v $SRC:/target:ro -v shapecov-linter-gomod:/go/pkg/mod -v shapecov-linter-gobuild:/root/.cache/go-build -v $BIN:/bin-out"
mkdir -p "$BIN"
docker run --rm $PLAT --name shapecov-linter-build $VOLS -e GOFLAGS=-mod=readonly "$IMG" sh -ec '
  cd /linter && go build -o /bin-out/shapecov-lint ./cmd/shapecov-lint
  cd /target && go mod download'
OUT=$HERE/results/$NAME-$(echo "$SHA" | cut -c1-12)
set +e
docker run --rm $PLAT --name shapecov-linter-run --network none -e GOPROXY=off -e GOFLAGS=-mod=readonly $VOLS "$IMG" \
  /bin-out/shapecov-lint -C /target "$@" ./... > "$OUT.json" 2> "$OUT.log"
CODE=$?
set -e
echo "$NAME $SHA $(git -C "$CLONE" show -s --format='%cI %s' "$SHA")" >> "$OUT.log"
echo "exit code $CODE" >> "$OUT.log"
cat "$OUT.log"
