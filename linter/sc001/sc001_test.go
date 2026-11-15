package sc001_test

import (
	"path/filepath"
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"

	"shapecov/linter/sc001"
)

func testdata(t *testing.T) string {
	dir, err := filepath.Abs(filepath.Join("..", "testdata"))
	if err != nil {
		t.Fatal(err)
	}
	return dir
}

// TestFixtures runs SC001 over testdata/src/sc001: bad.go holds the seeded
// violations (each marked with a "want" comment), good.go holds correct code
// that must produce no finding.
func TestFixtures(t *testing.T) {
	analysistest.Run(t, testdata(t), sc001.Analyzer, "sc001")
}

// TestTestSupportSkipped checks that a test-support package (an import path
// element such as "integrationtests") produces no finding by default.
func TestTestSupportSkipped(t *testing.T) {
	analysistest.Run(t, testdata(t), sc001.Analyzer, "sc001support/integrationtests")
}

// TestSignerPackage checks that declared credentials read in a package that
// never reads ledger output (a signer) produce no finding.
func TestSignerPackage(t *testing.T) {
	analysistest.Run(t, testdata(t), sc001.Analyzer, "sc001signer")
}
