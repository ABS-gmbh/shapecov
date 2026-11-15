#!/bin/sh
# Runs gofmt, go vet and the linter's own tests in Docker, with no network.
# The first run needs network once to fetch golang.org/x/tools into the module cache.
#   scripts/test.sh            # prints to the terminal
#   scripts/test.sh > results/go-test.txt 2>&1
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
IMG=${GO_IMAGE:-golang:1.26}
VOLS="-v $HERE:/linter -v shapecov-linter-gomod:/go/pkg/mod -v shapecov-linter-gobuild:/root/.cache/go-build -w /linter"
docker run --rm --name shapecov-linter-deps $VOLS "$IMG" go mod download >/dev/null 2>&1
docker run --rm --name shapecov-linter-test --network none -e GOPROXY=off -e GOFLAGS=-mod=readonly $VOLS "$IMG" sh -ec '
  go version
  echo "+ gofmt -l ."; test -z "$(gofmt -l . | grep -v "^testdata/seeded" | tee /dev/stderr)"
  echo "+ go vet ./..."; go vet ./...
  echo "+ go test -count=1 -v ./..."; go test -count=1 -v ./...'
