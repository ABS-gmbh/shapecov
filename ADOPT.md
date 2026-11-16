# Run ShapeCov in your repository's CI

Two packaged forms, each a few lines of YAML in the repository that wants the checks. ShapeCov's own
CI calls both on every push (`ci.yml`, the jobs named "Reusable sdk-conformance workflow" and
"Linter action").

## An SDK: the conformance corpus on every pull request

```yaml
# .github/workflows/shapecov.yml in the SDK's repository
on: [pull_request]
jobs:
  shapecov:
    uses: ABS-gmbh/shapecov/.github/workflows/sdk-conformance.yml@main  # pin a release tag once one carries this workflow
    with:
      sdk: js                       # rust, js, python, python-xdr, go or java
      version: "github:stellar/js-stellar-sdk#${{ github.event.pull_request.head.sha }}"
      corpus-ref: main              # the ShapeCov tag or commit whose corpus to run
      known-failures: .github/shapecov-known-failures.txt
```

`version` is what the package manager installs instead of ShapeCov's pin:
- a release (`17.4.0`, `v0.9.0`);
- or the pull request's own code: an npm spec, a pip `git+https://…@<sha>` spec, or a Go commit
  hash.

Leave it empty to test ShapeCov's pinned release.

The workflow sends three kinds of input through the SDK and fails on any divergence the
known-failures file does not list:
- every corpus entry, which must decode and re-encode to the same bytes;
- every value the generator made, which must also re-encode to the same bytes;
- every faulty value the generator made, which must be rejected (trailing bytes, non-zero padding,
  an optional flag or bool word other than 0 or 1, and the other faults RFC 4506 rules out).

Its summary, and the `shapecov-conformance-<sdk>` artifact, give every divergence by id and class.

**Known-failures file.** One pattern per line, matched against a divergence's id (`entry:<id>`,
`case:<id>`) or class (`entry`, `valid`, `fault:<kind>`, `crash`), with shell-style wildcards.
Text after `#` is a comment, a good place for the issue that tracks it. A pattern that matches
nothing is reported, so a fixed defect is noticed and its line can go. ShapeCov's own file for
go-stellar-sdk, [`.github/known-failures/go.txt`](.github/known-failures/go.txt), is an example.

## An indexer written in Go: the linter on every pull request

```yaml
# a job in the indexer's workflow
  shapecov-lint:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: ABS-gmbh/shapecov/linter@main   # pin a release tag once one carries this action
        with:
          accepted: .github/shapecov-accepted.json   # optional
```

The action builds the linter from the same ref, runs it on the module (`working-directory`,
default the repository root), and fails on any finding. With `accepted`, it fails only on findings
the file does not list. Each accepted finding needs a reason, and ideally an upstream issue; see
[`linter/accepted/wallet-backend.json`](linter/accepted/wallet-backend.json) for the format. The
rules are described in [`linter/README.md`](linter/README.md).

## What either one needs

- **The conformance workflow** runs on GitHub's `ubuntu-24.04` runner. For Go and Java it pulls
  Docker images (`golang:1.26`, `maven:3.9-eclipse-temurin-21`).
- **The linter action** needs only Go, which it sets up.
- **Neither needs secrets.** The conformance workflow asks only for `contents: read`.
