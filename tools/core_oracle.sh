#!/bin/sh
# Runs inside the stellar-core image. stdin: "id\ttype\tb64"; stdout: "id\tok|err\tmessage".
# stellar-core's own XDR decoder (xdrpp) is the ground truth for what the network accepts.
while IFS="$(printf '\t')" read -r id ty b64; do
  case "$ty" in
    Asset) ft=asset ;; LedgerEntry) ft=ledgerentry ;; LedgerHeader) ft=ledgerheader ;;
    TransactionMeta) ft=meta ;; TransactionResult) ft=result ;; TransactionResultPair) ft=resultpair ;;
    TransactionEnvelope) ft=tx ;; *) printf '%s\tnotype\t\n' "$id"; continue ;;
  esac
  printf '%s\n' "$b64" > /tmp/c.b64
  out=$(stellar-core print-xdr /tmp/c.b64 --filetype "$ft" --base64 --compact --raw 2>&1 | grep -v 'non-release')
  case "$out" in
    *"Could not decode"*) printf '%s\terr\t%s\n' "$id" "$(printf '%s' "$out" | tr '\t\n' '  ' | cut -c1-200)" ;;
    "{"*) printf '%s\tok\t\n' "$id" ;;
    "") printf '%s\terr\tempty input\n' "$id" ;;
    *) printf '%s\tunknown\t%s\n' "$id" "$(printf '%s' "$out" | tr '\t\n' '  ' | cut -c1-200)" ;;
  esac
done
