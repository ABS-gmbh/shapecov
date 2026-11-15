package sc003_test

import (
	"path/filepath"
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"

	"shapecov/linter/sc003"
)

func testdata(t *testing.T) string {
	dir, err := filepath.Abs(filepath.Join("..", "testdata"))
	if err != nil {
		t.Fatal(err)
	}
	return dir
}

// TestFixtures runs SC003 over testdata/src/sc003: bad.go holds the seeded
// violations (each marked with a "want" comment), good.go holds correct code
// that must produce no finding.
func TestFixtures(t *testing.T) {
	analysistest.Run(t, testdata(t), sc003.Analyzer, "sc003")
}

func TestStrict(t *testing.T) {
	if err := sc003.Analyzer.Flags.Set("strict", "true"); err != nil {
		t.Fatal(err)
	}
	defer sc003.Analyzer.Flags.Set("strict", "false")
	analysistest.Run(t, testdata(t), sc003.Analyzer, "sc003strict")
}
