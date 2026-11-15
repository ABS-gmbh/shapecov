#!/bin/sh
# Build the checker against one go-stellar-sdk version. Runs inside golang:1.26.
#   build.sh <version>      -> /work/bin/tx-<version>
set -e
V=$1
D=/tmp/build-$V
mkdir -p "$D" /work/bin && cp /work/main.go "$D"/ && cd "$D"
go mod init txcheck >/dev/null 2>&1
go get github.com/stellar/go-stellar-sdk@"$V" >/dev/null 2>&1
go mod tidy >/dev/null 2>&1
CGO_ENABLED=0 go build -o /work/bin/tx-"$V" . && echo "built tx-$V with $(go list -m github.com/stellar/go-stellar-sdk)"
