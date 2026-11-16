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
GO_IMAGE=golang:1.27.3 scripts/run-target.sh stellar-etl https://github.com/stellar/stellar-etl <ref>
                                                  # any Go repository; writes results/<name>-<sha12>.json
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
| `-tests` | Also analyse `_test.go` files and test-support packages (both skipped by default). |
| `-no-ignores` | Report findings that a `//shapecov:ignore` comment would suppress. |
| `-strict` | SC003: also report envelope-derived participants that a success check guards. |
| `-sinks REGEX` | SC003: names that hold participants (default `(?i)participant\|affected\|involved`). |
| `-validators REGEX` | SC001: function names that count as validating their arguments (default `(?i)valid\|sanitiz\|utf8\|quote\|^EncodeToString$\|^BuildAssets?$\|^Parse(Int\|Uint\|Float\|Bool)$`). |

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
flow.

**Test support is skipped** by default, like `_test.go` files. A package counts as test support
when an element of its import path is `integrationtests`, `integrationtest`, `testutil`,
`testutils`, `testhelper`, `testhelpers`, `testsupport` or `e2e`. `-tests` analyses it too. The approximations below are deliberate; the false-positive and false-negative classes
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
   This pattern applies only in packages that **read ledger output**: the SDK's `ingest` package,
   or an xdr type that records what the network did (transaction and ledger meta, results,
   events, ledger entry changes). A package that never does is building or vetting a transaction
   (a signer, a pre-submission policy check), where reading the declared credentials is correct.

A **validator** is any call whose name matches `-validators`. It covers a value when the value
is inside the call, is the same expression, or is assigned to a variable that is passed to it.
The default includes strict parsers that reject anything outside a fixed grammar
(`xdr.BuildAssets`, `strconv.Parse*`). A value is also covered when it is only an argument of a
`fmt` printf-style call whose verb for it is `%q`, `%x` or `%X`, since those escape every byte.
Building an XDR string (`xdr.ScString("name")`) and converting a constant are not reported. Nor is a
contract string in a function that derives a Stellar Asset Contract's ID from the asset
(`asset.ContractID(passphrase)`) and compares it with the ledger entry's contract ID: such a function
keeps only that contract's own entries, and the host accepted the asset code (ASCII letters and
digits) when it created the contract.

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
| SC001 | 22 | 21 | memo text by field, getter and must-getter; ScString, DataValue, function names; ID narrowing to int, int64, xdr.Int64 and float; muxed `Address()`; declared credentials; `%s` vs `%q` formatting; validating parsers |
| SC002 | 11 | 12 | direct, mutual and closure recursion over ScVal, auth invocations and spec types; work-list loops |
| SC003 | 11 | 10 | slices, sets, maps, struct fields, function results; auth trees; caller-guarded helpers; success checks that come too late; returns inside a filling loop |

Plus one strict-mode fixture for SC003, and two SC001 packages that must produce nothing: a
test-support package (`integrationtests`) and a signer that never reads ledger output. The fixtures compile against small stubs of the SDK's
`xdr` and `ingest` packages in `testdata/src/github.com/stellar/go-stellar-sdk/`.

## Run on wallet-backend `main`

Commit `3e22515a44979fdc3a558fda3991ca2b48e38cef` (12 November 2026). The command was
`scripts/run-wallet-backend.sh 3e22515a…`. It analysed 40 packages with no load errors and
reported **4 findings**:
[`results/wallet-backend-3e22515a4497.json`](results/wallet-backend-3e22515a4497.json).

Two are real instances of the mistakes; the other two, at one site, are a false positive (row 2).
**The linter does not run clean on wallet-backend.** None is a bug to file as is: one is low
severity and already reported (#820), one is in dead code, and the site of the other two has the
check the rule asks for one call down.

**What CI checks instead.** [`accepted/wallet-backend.json`](accepted/wallet-backend.json) lists
the four findings, each with the reason it is accepted and the upstream issue that tracks it where
one exists (#820 for the first, #800 for the memo helper). The `linter` job runs the linter on
wallet-backend at the commit pinned in that file and runs
[`scripts/check_accepted.py`](scripts/check_accepted.py). The job fails on any finding the file
does not list. An entry that no longer matches a finding is printed as resolved. The weekly run
does the same against wallet-backend `main`, so a new finding there turns the job red. This is a
triage record, not a claim that the code is correct: "no finding outside the accepted list", not
"clean".

The fix for finding 1 is prepared on a local branch, awaiting acceptance of #820. With it, the
linter reports 3 findings on that branch, and SC002 no longer fires. That is the first control
in which a depth cap was *added* (see "SC002" below).

| # | Rule | Location | Verdict | Reason |
|---|---|---|---|---|
| 1 | SC002 | `internal/indexer/processors/contract_deploy.go:116` | **true positive**, low severity; reported earlier as [stellar/wallet-backend#820](https://github.com/stellar/wallet-backend/issues/820) by the shapekit project | `walkInvocation` recurses into `SubInvocations` of the declared auth tree with no depth counter. The submitter chooses the nesting. The Go XDR decoder caps decode depth at 1500, so the walk cannot overflow, but it has no cap of its own. |
| 2 | SC003 | `internal/indexer/processors/participants.go:146` | **false positive** for failed transactions | `GetOperationsParticipants` calls `GetOperationParticipants`, which since `9538b3ca` (25 September 2026) returns only the source and the fee-bump account for a failed transaction (lines 166-176), because the addresses a failed transaction names are, in its own comment, "unverified submitter input". SC003 looks for the success check in the function and its callers, not in the function it calls. For a successful transaction the participants come from the operation body, as the rule says; the meta shows those accounts changed. Related, not the same: [stellar/wallet-backend#677](https://github.com/stellar/wallet-backend/issues/677) (open) reports the meta side, participants that the meta records but the indexer drops. |
| 3 | SC003 | `internal/indexer/processors/participants.go:155` | **false positive** (same site) | The same participants written into the result map. |
| 4 | SC001 | `internal/utils/ingestion_utils.go:17` | **true positive**, not reachable | `utils.Memo` returns memo text without a UTF-8 check. Nothing in wallet-backend calls it, and no table has a memo column, so it is dead code today. [stellar/wallet-backend#800](https://github.com/stellar/wallet-backend/issues/800) (open, by a maintainer) plans a memo column; once memo text is stored, the check matters. |

### How the false positives were removed

The first recorded run reported 10 findings: these 4 and 6 false positives. Each false positive
belonged to a class of code, so each class was fixed in the rule, not by suppressing lines. Each
fix has fixtures: code that must stay quiet, and a seeded case that must still fire. Each was
checked against the historical controls below, which are unchanged.

| False positive | Class | Change |
|---|---|---|
| `contracts/utils.go:35`, `string(asset)` passed to `xdr.BuildAssets` | strict parser | `BuildAssets` and `strconv.Parse*` count as validators by default. |
| `protocol_contracts.go:127`, `fmt.Sprintf("tag=%q", string(ref.Tag))` | escaping format | A value printed only with `%q`, `%x` or `%X` counts as validated. `%s` and `%v` still fire. |
| `integrationtests/infrastructure/helpers.go:110` and `soroban_transactions.go:291` | test support | Test-support packages are skipped like `_test.go` files; `-tests` includes them. |
| `pkg/sorobanauth/sorobanauth.go:44` and `:157` | signer, pre-submission check | The declared-credentials pattern applies only in packages that read ledger output. |

Two rule bugs were fixed before that. SC001 reported `xdr.ScString("SEP41 Token")`, which builds a
value rather than reading one. SC003 treated `len(ops)`, used as a map capacity hint, as a
participant.

## Run on stellar-etl `master`

The rules were written against wallet-backend, so they were also run on a second indexer they had
never seen: stellar-etl at `2b24ec89ddce7fc0beb7795de982c93e6895eaf3` (11 November 2026), the commit
the replay harness pins. Command:
`GO_IMAGE=golang:1.27.3 scripts/run-target.sh stellar-etl https://github.com/stellar/stellar-etl 2b24ec89…`.
It analysed 6 packages with no load errors:
[`results/stellar-etl-2b24ec89ddce.json`](results/stellar-etl-2b24ec89ddce.json).

**Go version.** stellar-etl's Dockerfile pins Go 1.27.3. With Go 1.27.4 the packages do not load:
the toolchain rejects the prebuilt library of its cgo dependency `go-stellar-xdr-json`
("disallowed LTO section .llvmbc in #cgo LDFLAGS"), on amd64 and arm64 alike. Lint it with 1.27.3.

**False positives: 1 of 14 before the rule was fixed, 0 of 13 after.** The one false positive was
`internal/transform/contract_data.go:282`, the asset code read from a Stellar Asset Contract's
instance storage in `AssetFromContractData`. The function keeps the asset only when the asset's
contract ID equals the entry's, and the host validates the code before it creates that contract
(`validate_asset` in rs-soroban-env), so the string cannot hold arbitrary bytes. The same function
is in go-stellar-sdk's processors, so any indexer that uses it would have hit this. SC001 now treats
that identity check as covering the string (above, "SC001"), with a fixture that stays quiet and a
seeded case, the ID derived but never compared, that still fires. Rerun with the fix, wallet-backend
`main` and the two contract-string controls (`ec6b706f`, `e6bb6ea4`) give exactly the findings
recorded before: 4, 34 and 32.

| # | Rule | Location | Verdict | Reason |
|---|---|---|---|---|
| 1 | SC001 | `internal/transform/transaction.go:77` | **true positive, live**; reported first as [stellar/stellar-etl#504](https://github.com/stellar/stellar-etl/issues/504) by tolgayayci on 13 November | `TransformTransaction` copies MEMO_TEXT with `MustText()` into the `memo` column. `json.Marshal` replaces invalid UTF-8 with U+FFFD, so a memo that is not UTF-8 is exported changed. #504 names this line. |
| 2–13 | SC003 | `internal/transform/operation.go:2130` to `:2187` (12 sites) | **true positive, not reachable** | `transactionOperationWrapper.Participants()` adds destinations, trustors, claimants and sponsored accounts from the envelope with no success check. Nothing in stellar-etl calls it: it belongs to the copy of Horizon's operations processor that [stellar/stellar-etl#463](https://github.com/stellar/stellar-etl/issues/463) (open, by a maintainer) proposes to delete. #463 names `Details()`, not `Participants()`. Not filed. |

CI runs it like wallet-backend: the `linter-stellar-etl` job lints the pinned commit with Go 1.27.3 and
fails on any finding outside [`accepted/stellar-etl.json`](accepted/stellar-etl.json).

**What this says about the linter.** Its precision held on a codebase it was not tuned on: one
false-positive class, fixed in the rule, and every remaining finding is a real instance of a named
mistake. Its reach is narrow. Of the 17 issues in stellar-etl's own correctness audit (#448) and
#504, only #504 is one of the three mistakes in a form a rule can see in one function, and SC001
finds it. The others are semantic: a wrong pool formula (#451), the wrong effect type (#457), a muxed
destination fabricated from a memo inside the token-transfer events (#450). The replay oracle, not
the linter, is what catches those (`FINDINGS.md`). SC002 reported nothing: stellar-etl has no
recursive walk of its own over contract values, and hands each one to `xdrjson`
(`internal/transform/contract_events.go`, `serializeScVal`). Twelve of the thirteen findings are in
one uncalled function; SC003 reports each site, not each function.

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

SC002 has no control in wallet-backend's history in which a depth cap was *added*; the only one is
our own unmerged branch for #820, described above. In wallet-backend's history, the
recursive walk was removed rather than capped. No such fix was found in a search of
stellar-etl's commit messages either.

## Known false positives

- **A success check inside the called function.** SC003 accepts a success check earlier in the
  function or in every caller, not one inside a function it calls. wallet-backend's
  `GetOperationsParticipants` stores what `GetOperationParticipants` returns, and the check is in
  the latter (rows 2 and 3 of the wallet-backend run).

- **Validation the rule cannot see.** SC001 recognises validators by name, plus the strict
  parsers and `%q`/`%x` formatting listed above. Any other parser or safe sink is not recognised.
  Use `-validators` or an ignore comment with a reason.
- **Producer code in an ingesting package.** The credentials pattern is skipped only for whole
  packages that never read ledger output. A signer that sits in the same package as an indexer
  is still reported. SC001's other patterns and SC003 do not look at this at all.
- **Test support under another name.** Test-support packages are found by path element only.
  A helper package named differently is analysed and may be reported.
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
- **Credentials in a package that only looks ledger-free.** A package that reads declared
  credentials and records them without ever naming a meta, result, event or `ingest` type is
  treated as a signer and not reported.
- **Real code under a test-support path element** (`e2e`, `testutil`, …) is skipped by default.
- **Generated code** (files marked `// Code generated … DO NOT EDIT.`) is skipped, and so are
  `_test.go` files unless `-tests` is given.
