package sc002_test

import (
	"path/filepath"
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"

	"shapecov/linter/sc002"
)

func testdata(t *testing.T) string {
	dir, err := filepath.Abs(filepath.Join("..", "testdata"))
	if err != nil {
		t.Fatal(err)
	}
	return dir
}

// TestFixtures runs SC002 over testdata/src/sc002: bad.go holds the seeded
// violations (each marked with a "want" comment), good.go holds correct code
// that must produce no finding.
func TestFixtures(t *testing.T) {
	analysistest.Run(t, testdata(t), sc002.Analyzer, "sc002")
}
