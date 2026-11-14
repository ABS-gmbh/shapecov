# Reproduction: stellar/wallet-backend#729

Sighting: "fix: handle CAP-40 signed-payload signers in ingestion". Before the fix, a ledger
containing a signed-payload signer made the signer row fail to encode, the persist transaction
rolled back, and ingestion retried the same ledger forever. The pull request names testnet ledger
4437357 as one that triggers it.

Corpus entry: `testnet-4437357-signed-payload-signer`, that same ledger, taken from Stellar's
public ledger archive (source URL in the manifest). Run on 14 November 2026.

## What was run

The entry is fed to wallet-backend's own `indexer.ProcessLedger` at two commits. Every database
column value of every state change the indexer produces is then encoded with the indexer's own
`driver.Valuer`, which is the step that failed in production. The expected signer key comes from
the corpus manifest, where it is derived from the decoded ledger, not from wallet-backend.

```bash
git clone https://github.com/stellar/wallet-backend /tmp/wb
python3 harness/wallet-backend/expect.py testnet-4437357-signed-payload-signer > /tmp/expect.json
E=corpus/entries/testnet-4437357.LedgerCloseMeta.xdr.b64

# parent of the fix
harness/wallet-backend/replay.sh /tmp/wb 2a0a84ea12523b6c92e278c0c84b443041240095 $E /tmp/expect.json
# the fix (merge commit of #729)
harness/wallet-backend/replay.sh /tmp/wb 2c873353c1f0f3c9b145e25a7d009023ad104a1c $E /tmp/expect.json
```

## Result

Before the fix (`2a0a84ea`): **mishandled**

```
SHAPECOV_RESULT {"entry_id":"testnet-4437357-signed-payload-signer","ledger":4437357,"result":"mishandled","state_changes":17,"mishandled":["state change 0 (SIGNER/ADD) column SignerAccountID does not encode: stellar address PBCK2RYYLIYOSHBEL2FQLAVRSHRH3GP3ID476SGKBV7BEZHMQ6NSAAAAAAB55LN6AANMS has a 40-byte key payload; the account_id column stores only 32-byte account/contract keys"]}
```

With the fix (`2c873353`): **pass**

```
SHAPECOV_RESULT {"entry_id":"testnet-4437357-signed-payload-signer","ledger":4437357,"result":"pass","state_changes":17}
```

The third outcome was exercised too: with an expected signer key that is not in the ledger, the
fixed commit reports **dropped** ("no SIGNER state change for signer key ...").

## Limits

- This reproduces the cause the pull request describes, the row that cannot be encoded. It does
  not run PostgreSQL, so it does not show the rollback and the retry loop themselves.
- The Go modules are downloaded with network access; the test itself runs in a container with no
  network.
