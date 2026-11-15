# shapecov-lint

A linter for Go indexers written against `github.com/stellar/go-stellar-sdk` (or the older
`github.com/stellar/go`). It checks for the three ingestion mistakes the RFP lists, as three
`golang.org/x/tools/go/analysis` analyzers:

| Rule | Mistake |
|---|---|
| **SC001** | Trusting a field stellar-core does not validate: memo text, contract strings, ManageData values, muxed and memo IDs, declared Soroban credentials. |
| **SC002** | Walking a recursive XDR structure (nested `ScVal`, Soroban authorization trees, contract spec types) with no depth or size cap. |
| **SC003** | Deriving participants (the accounts a transaction affected) from the transaction envelope instead of the ledger meta. |

## Run it

```sh
scripts/test.sh                                   # gofmt, go vet, go test (Docker, no network)
scripts/run-wallet-backend.sh <ref> [flags]       # lint stellar/wallet-backend at a commit,
                                                  # writes results/wallet-backend-<sha12>.json
```

Or build the command and run it on any Go module:

```sh
go build -o shapecov-lint ./cmd/shapecov-lint
shapecov-lint -C /path/to/indexer ./...           # JSON report on stdout
shapecov-lint -format text ./...                  # file:line:col: RULE: message
```

| Flag | Effect |
|---|---|
| `-rules SC001,SC003` | Run only these rules. |
| `-tests` | Also analyse `_test.go` files (skipped by default). |
| `-no-ignores` | Report findings that a `//shapecov:ignore` comment would suppress. |
| `-strict` | SC003: also report envelope-derived participants that a success check guards. |
| `-sinks REGEX` | SC003: names that hold participants (default `(?i)participant\|affected\|involved`). |
| `-validators REGEX` | SC001: function names that count as validating their arguments (default `(?i)valid\|sanitiz\|utf8\|quote\|^EncodeToString$`). |

Exit status: 0 for no findings, 1 for findings, 2 for a usage or load error. The JSON report
lists every finding with `rule`, `file`, `line`, `column`, `message` and `package`, plus the
number of packages analysed, load errors, and how many findings ignore comments suppressed.

**Suppression.** A `//shapecov:ignore SC00N <reason>` comment on the line of a finding, or on
the line above it, suppresses that finding. The reason is required; a comment without one
suppresses nothing. Suppressed findings are counted in the report. None of the recorded runs
below use suppressions (`suppressed_by_ignore_comment: 0` in every file).

## What each rule detects, and how

All three rules work on syntax plus type information inside one function at a time (closures
included), recognising XDR types by their package path. None of them does whole-program data
flow. The approximations below are deliberate; the false-positive and false-negative classes
they cause are listed further down.

### SC001: trusting unvalidated fields

Reports, unless a validator covers the value:

1. **Memo text.** `Memo.Text`, `Memo.GetText()` or `Memo.MustText()` is used. stellar-core accepts
   any 28 bytes, including invalid UTF-8 and NUL, both of which Postgres `TEXT` rejects.
2. **Contract and data strings.** An `xdr.ScString`, an `xdr.DataValue`, or the `FunctionName`
   symbol of `InvokeContractArgs` is converted to `string`.
3. **64-bit IDs.** A muxed-account ID or memo ID is narrowed to a smaller integer or a float with
   no range comparison. `MuxedAccount.Address()` is used without `ToAccountId()` or a check of the
   account type, which keeps the `M...` form.
4. **Declared Soroban credentials.** `SorobanAddressCredentials.Address` is read as a field in a
   function that never looks at the nonce ledger entry the host creates for a used credential.

A **validator** is any call whose name matches `-validators`. It covers a value when the value
is inside the call, is the same expression, or is assigned to a variable that is passed to it.
Building an XDR string (`xdr.ScString("name")`) and converting a constant are not reported.

### SC002: missing depth and size caps

Reports two shapes over the recursive XDR types (`ScVal`, `ScVec`, `ScMap`, `ScMapEntry`,
`SorobanAuthorizedInvocation`, and the `ScSpecType*` family; `ClaimPredicate` is left out
because stellar-core rejects predicates nested deeper than four levels):

1. **Recursion.** A cycle of calls (direct, mutual, or through a closure bound to a variable)
   that takes one of these types. The cycle counts as capped when some integer that outlives a
   call (a parameter, a struct field, or an outer variable) is compared in a condition and also
   changes, by assignment or increment or by being passed on in changed form (`depth+1`).
2. **Work-list loops.** A loop that takes items from a slice of one of these types while appending
   to it. The loop counts as capped when, apart from its own condition, it compares the queue or
   an integer the loop changes.

### SC003: participants from the envelope

Follows values read from envelope types (the envelope, transactions, operations and their `*Op`
bodies, host-function arguments, claimants) through local variables into a **participant
collection**: a variable, struct field, map, set (`Add`, `Append`, …) or function result whose
name matches `-sinks`. Two kinds:

- **From operation bodies:** reported when no success check guards the code (`Successful()`,
  `IsSuccess`, `TxSuccess`, …) earlier in the function or in every caller. `-strict` reports them
  even when guarded, since the meta is still the source of record.
- **From the declared Soroban authorization tree** (`SorobanAuthorizationEntry`,
  `SorobanAuthorizedInvocation` and their parts): always reported. A success check does not
  help, because the host verifies only the entries a `require_auth` call matched.

The transaction and operation **source accounts** are not treated as claims. stellar-core checks
their signatures and sequence numbers. `len()` and `cap()` of envelope data carry no taint.

## Tests

`go test ./...` passes; the full output is in [`results/go-test.txt`](results/go-test.txt). Each rule
has `analysistest` fixtures with seeded violations (`bad.go`, each marked with a `want`
comment) and correct code that must produce no finding (`good.go`):

| Rule | Seeded violations | Correct-code functions | Patterns covered |
|---|---|---|---|
| SC001 | 20 | 19 | memo text by field, getter and must-getter; ScString, DataValue, function names; ID narrowing to int, int64, xdr.Int64 and float; muxed `Address()`; declared credentials |
| SC002 | 11 | 12 | direct, mutual and closure recursion over ScVal, auth invocations and spec types; work-list loops |
| SC003 | 11 | 10 | slices, sets, maps, struct fields, function results; auth trees; caller-guarded helpers; success checks that come too late; returns inside a filling loop |

Plus one strict-mode fixture for SC003. The fixtures compile against small stubs of the SDK's
`xdr` and `ingest` packages in `testdata/src/github.com/stellar/go-stellar-sdk/`.

## Run on wallet-backend `main`

Commit `3e22515a44979fdc3a558fda3991ca2b48e38cef` (12 November 2026). The command was
`scripts/run-wallet-backend.sh 3e22515a…`. It analysed 40 packages with no load errors and
reported **10 findings**:
[`results/wallet-backend-3e22515a4497.json`](results/wallet-backend-3e22515a4497.json).

**"Runs clean on current wallet-backend" is not met.** Four findings are real instances of the
mistakes; six are false positives.

| # | Rule | Location | Verdict | Reason |
|---|---|---|---|---|
| 1 | SC002 | `internal/indexer/processors/contract_deploy.go:116` | **true positive**, low severity | `walkInvocation` recurses into `SubInvocations` of the declared auth tree with no depth counter. The submitter chooses the nesting. The Go XDR decoder caps decode depth at 1500, so the walk cannot overflow, but it has no cap of its own. |
| 2 | SC003 | `internal/indexer/processors/participants.go:146` | **true positive** (design) | `GetOperationsParticipants` takes participants from envelope operations for every transaction, including failed ones; its doc comment says so. In a failed transaction, a payment destination is recorded as a participant though nothing changed for it, so anyone can put an account into another account's history. This dates from #474. |
| 3 | SC003 | `internal/indexer/processors/participants.go:155` | **true positive** (same site) | The same participants written into the result map. |
| 4 | SC001 | `internal/utils/ingestion_utils.go:17` | **true positive**, not reachable | `utils.Memo` returns memo text without a UTF-8 check. Nothing in wallet-backend calls it, and no table has a memo column, so it is dead code today. |
| 5 | SC001 | `internal/indexer/processors/contracts/utils.go:35` | false positive | `string(asset)` goes straight into `xdr.BuildAssets`, which rejects anything that is not `CODE:ISSUER`. The rule does not know that parser validates. |
| 6 | SC001 | `internal/indexer/processors/protocol_contracts.go:127` | false positive | The tag is only formatted with `%q`, which escapes invalid UTF-8. |
| 7 | SC001 | `internal/integrationtests/infrastructure/helpers.go:110` | false positive | Test infrastructure that builds an `M...` address on purpose. |
| 8 | SC001 | `internal/integrationtests/infrastructure/soroban_transactions.go:291` | false positive | Test infrastructure signing auth entries of a transaction it built. |
| 9 | SC001 | `pkg/sorobanauth/sorobanauth.go:44` | false positive | A client-side signer copying the address of an entry it is about to sign; no ledger data is read. |
| 10 | SC001 | `pkg/sorobanauth/sorobanauth.go:157` | false positive | The same package checking a request against a list of forbidden signers before signing. |

Two rule bugs found during this triage were fixed, and fixtures now cover them. SC001 reported
`xdr.ScString("SEP41 Token")`, which builds a value rather than reading one. SC003 treated
`len(ops)`, used as a map capacity hint, as a participant. The real participant sites at lines
146 and 155 are still reported. No rule was narrowed in any other way.

## Historical positive controls

Each pair is the commit just before a real fix and the fix itself, linted with the rules as
committed here. Only the findings in the files the fix touched are shown. Full outputs are in
`results/`.

| Rule | Fix | Before (parent) | After (fix) |
|---|---|---|---|
| SC001, contract strings | `e6bb6ea4` #587 "harden SEP-41 metadata surface" (HackerOne: a token `name()` or `symbol()` with invalid UTF-8 or NUL wedged ledger persistence) | `ec6b706f`: 3 findings in `contract_metadata.go`, including `name = string(nameStr)` (line 255) and `symbol = string(symbolStr)` (line 272) | 1 finding: both fixed lines are gone. The one left is the SAC path (`name := string(nameStr)` parsed as `CODE:ISSUER`), which #587 did not touch and #723 later removed. |
| SC001, muxed IDs | `bb0b162b` "reduce a Soroban operation's source to its base account" (#716, producer 1) | `f8e5786d`: 4 `MuxedAccount.Address()` findings in `contract_operations.go` (lines 156, 259, 303, 347) | none of those |
| SC003, auth tree | `9538b3ca` "derive Soroban participants from executed meta, not the auth tree" | `666a64d4`: 9 SC003 findings in `contract_operations.go` | 0 |
| SC002, recursion | the same fix, which removed the recursive auth-tree walk | `666a64d4`: `participantsFromInvocationAndSubInvocations` (line 53) | 0 |

One more pair shows that SC003 follows the success guard. #474 "store failed operations"
(`13c0444a`) removed the success check from envelope-derived participants. Its parent
(`84959de0`) has no envelope-participant findings. #474 itself has 14, in `participants.go` and
`transaction_operation_wrapper.go`.

SC002 has no control in which a depth cap was *added*. In wallet-backend's history, the
recursive walk was removed rather than capped. No such fix was found in a search of
stellar-etl's commit messages either.

## Known false positives

- **Validation the rule cannot see.** SC001 only recognises validators by name. A parser that
  rejects bad input (`xdr.BuildAssets`, `strconv.Parse*`) or a safe sink (`%q`) is not recognised.
  Use `-validators` or an ignore comment with a reason.
- **Code that does not read the ledger.** The rules do not know whether a package ingests ledger
  data. Transaction-building code, signers and test infrastructure use the same types and are
  reported (5 of the 6 false positives on `main`).
- **Envelope participants for failed transactions by design.** SC003 reports indexers that record
  envelope accounts for failed transactions on purpose, as Horizon did. Whether that is a mistake
  is the indexer's call; the finding says what the data is.

## Known false negatives

- **Across functions.** SC001 and SC003 follow values inside one function only. A value read in
  one function and stored by another is missed, except for function results named as
  participants (SC003) and success checks in every caller (SC003).
- **Struct fields and globals.** Taint does not flow through struct fields or package
  variables, only through locals.
- **Names.** SC003 sinks are found by name. A participant set called `accounts` is missed unless
  `-sinks` says otherwise.
- **Any comparison counts as a cap.** SC002 accepts any comparison of a changing integer as a cap.
  It does not check that the limit is small.
- **Generated code** (files marked `// Code generated … DO NOT EDIT.`) is skipped, and so are
  `_test.go` files unless `-tests` is given.
