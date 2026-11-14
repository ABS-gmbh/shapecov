#!/bin/sh
# Replay one corpus entry through stellar/wallet-backend's indexer at a given commit.
#
#   replay.sh <wallet-backend checkout> <commit> <entry .xdr.b64> <expect .json>
#
# The checkout is switched to <commit> (it must already be fetched). The Go
# modules are downloaded with network access, then the test itself runs in a
# container with no network. Prints one line: SHAPECOV_RESULT {json}
set -e
WB=$(cd "$1" && pwd); COMMIT=$2
ENTRY=$(cd "$(dirname "$3")" && pwd)/$(basename "$3")
EXPECT=$(cd "$(dirname "$4")" && pwd)/$(basename "$4")
HERE=$(cd "$(dirname "$0")" && pwd)

git -C "$WB" checkout -q "$COMMIT"
cp "$HERE/shapecov_replay_test.go" "$WB/internal/indexer/shapecov_replay_test.go"
trap 'rm -f "$WB/internal/indexer/shapecov_replay_test.go"' EXIT

IMG=golang:1.26
docker run --rm -v "$WB":/wb -v shapecov-gomod:/go/pkg/mod -w /wb "$IMG" \
  go mod download >/dev/null 2>&1
docker run --rm --network none --memory 4g --cpus 4 \
  -v "$WB":/wb -v shapecov-gomod:/go/pkg/mod -v shapecov-gobuild:/root/.cache/go-build \
  -v "$ENTRY":/in/entry.xdr.b64:ro -v "$EXPECT":/in/expect.json:ro \
  -e SHAPECOV_ENTRY=/in/entry.xdr.b64 -e SHAPECOV_EXPECT=/in/expect.json \
  -e GOPROXY=off -w /wb "$IMG" \
  go test ./internal/indexer/ -run '^TestShapecovReplay$' -count=1 -v 2>&1 \
  | grep -E '^(SHAPECOV_RESULT|--- |FAIL|ok|panic)' || true
