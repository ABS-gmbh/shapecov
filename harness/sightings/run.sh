#!/bin/sh
# Reproduce the two RFP sightings outside the indexers and the SDKs' corpus checks: each probe is
# built against the release before the fix and the release with it, and must behave as recorded.
#
#   rs-stellar-xdr#598   JSON for an AccountEntry with 21 signers (the XDR maximum is 20).
#                        28.0.0 accepts it and emits XDR that 30.0.0's decoder rejects;
#                        28.0.1 and 30.0.0 refuse it. 20 signers work everywhere (control).
#   rs-soroban-sdk#2099  MuxedAddress::try_from_val on a non-address ScVal (the topic symbol
#                        "transfer"): 28.0.0 panics, 30.0.0-rc.1 returns ConversionError.
#
# Needs cargo. Builds each probe with --locked from its own Cargo.lock.
set -eu
cd "$(dirname "$0")"
bad=0
build() { (cd "$1" && cargo build --release --locked -q) && ls "$1"/target/release/probe-* | grep -v '\.d$' | head -1; }
expect() {  # label, got, want-prefix
  case "$2" in "$3"*) echo "ok       $1: $2" | cut -c1-150 ;; *) echo "DIFFERS  $1: got '$2', expected '$3...'" | cut -c1-200; bad=$((bad+1)) ;; esac
}
X=rs-stellar-xdr-598
for v in 28.0.0 28.0.1 30.0.0; do eval "P_$(echo $v | tr . _)=$(build $X/v$v)"; done
for v in 28.0.0 28.0.1 30.0.0; do
  p=$(eval echo \$P_$(echo $v | tr . _))
  r=$($p AccountEntry fromjson < $X/acct20.json)
  expect "rs-stellar-xdr $v, 20 signers from JSON" "${r%% *}" ok
  expect "  and 30.0.0 decodes what it emitted" "$(echo "${r#ok }" | $P_30_0_0 AccountEntry fromxdr)" ok
  r=$($p AccountEntry fromjson < $X/acct21.json)
  if [ "$v" = 28.0.0 ]; then
    expect "rs-stellar-xdr $v, 21 signers from JSON (before #598)" "${r%% *}" ok
    expect "  and 30.0.0 rejects what it emitted" "$(echo "${r#ok }" | $P_30_0_0 AccountEntry fromxdr)" "err LengthExceedsMax"
  else
    expect "rs-stellar-xdr $v, 21 signers from JSON (with #598)" "$r" 'err Json(Error("xdr value max length exceeded"'
  fi
done
S=rs-soroban-sdk-2099
expect "soroban-sdk 28.0.0 (before #2099)" "$($(build $S/v28.0.0) 2>/dev/null | tail -1)" panics
expect "soroban-sdk 30.0.0-rc.1 (with #2099)" "$($(build $S/v30.0.0-rc.1) 2>/dev/null | tail -1)" "returns ConversionError"
[ $bad -eq 0 ] && echo "SIGHTINGS OK" || { echo "$bad SIGHTING CHECK(S) FAILED"; exit 1; }
