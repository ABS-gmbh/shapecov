// Command shapecov-lint runs the three shapecov rules (SC001, SC002, SC003)
// over Go packages and prints the findings as JSON.
//
//	shapecov-lint [flags] [packages]      (default package pattern: ./...)
//
// Exit status: 0 no findings, 1 findings, 2 usage or load error.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"golang.org/x/tools/go/analysis"
	"golang.org/x/tools/go/analysis/checker"
	"golang.org/x/tools/go/packages"

	"shapecov/linter/internal/sx"
	"shapecov/linter/sc001"
	"shapecov/linter/sc002"
	"shapecov/linter/sc003"
)

const version = "0.1.0"

type finding struct {
	Rule    string `json:"rule"`
	File    string `json:"file"`
	Line    int    `json:"line"`
	Column  int    `json:"column"`
	Message string `json:"message"`
	Package string `json:"package"`
}

type report struct {
	Tool       string    `json:"tool"`
	Version    string    `json:"version"`
	Rules      []string  `json:"rules"`
	Options    []string  `json:"options"`
	Packages   int       `json:"packages_analyzed"`
	LoadErrors []string  `json:"load_errors"`
	Suppressed int64     `json:"suppressed_by_ignore_comment"`
	Findings   []finding `json:"findings"`
}

func main() {
	var (
		format    = flag.String("format", "json", "output format: json or text")
		out       = flag.String("o", "", "write the report to this file instead of standard output")
		rules     = flag.String("rules", "SC001,SC002,SC003", "comma-separated rule IDs to run")
		tests     = flag.Bool("tests", false, "also analyse _test.go files")
		noIgnores = flag.Bool("no-ignores", false, "report findings even where a //shapecov:ignore comment covers them")
		strict    = flag.Bool("strict", false, "SC003: also report envelope-derived participants guarded by a success check")
		sinks     = flag.String("sinks", "", "SC003: regular expression for names that hold participants (default: participant|affected|involved)")
		valid     = flag.String("validators", "", "SC001: regular expression for function names that count as validators")
		dir       = flag.String("C", "", "run in this directory")
	)
	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "usage: shapecov-lint [flags] [packages]\n")
		flag.PrintDefaults()
	}
	flag.Parse()

	all := map[string]*analysis.Analyzer{"SC001": sc001.Analyzer, "SC002": sc002.Analyzer, "SC003": sc003.Analyzer}
	var analyzers []*analysis.Analyzer
	var ruleIDs []string
	for _, id := range strings.Split(*rules, ",") {
		id = strings.TrimSpace(id)
		a, ok := all[id]
		if !ok {
			fmt.Fprintf(os.Stderr, "shapecov-lint: unknown rule %q\n", id)
			os.Exit(2)
		}
		analyzers = append(analyzers, a)
		ruleIDs = append(ruleIDs, id)
	}

	var options []string
	sx.IncludeTests = *tests
	sx.HonorIgnores = !*noIgnores
	if *tests {
		options = append(options, "tests")
	}
	if *noIgnores {
		options = append(options, "no-ignores")
	}
	if *strict {
		must(sc003.Analyzer.Flags.Set("strict", "true"))
		options = append(options, "strict")
	}
	if *sinks != "" {
		must(sc003.Analyzer.Flags.Set("sinks", *sinks))
		options = append(options, "sinks="+*sinks)
	}
	if *valid != "" {
		must(sc001.Analyzer.Flags.Set("validators", *valid))
		options = append(options, "validators="+*valid)
	}

	patterns := flag.Args()
	if len(patterns) == 0 {
		patterns = []string{"./..."}
	}
	cfg := &packages.Config{
		Mode:  packages.LoadSyntax | packages.NeedModule,
		Tests: *tests,
		Dir:   *dir,
	}
	pkgs, err := packages.Load(cfg, patterns...)
	must(err)

	rep := report{Tool: "shapecov-lint", Version: version, Rules: ruleIDs, Options: options,
		LoadErrors: []string{}, Findings: []finding{}}
	packages.Visit(pkgs, nil, func(p *packages.Package) {
		for _, e := range p.Errors {
			rep.LoadErrors = append(rep.LoadErrors, e.Error())
		}
	})
	rep.Packages = len(pkgs)

	graph, err := checker.Analyze(analyzers, pkgs, nil)
	must(err)

	base := *dir
	if base == "" {
		base, _ = os.Getwd()
	}
	base, _ = filepath.Abs(base)
	seen := map[finding]bool{}
	for act := range graph.All() {
		if !act.IsRoot {
			continue
		}
		if act.Err != nil {
			rep.LoadErrors = append(rep.LoadErrors, fmt.Sprintf("%s on %s: %v", act.Analyzer.Name, act.Package.PkgPath, act.Err))
			continue
		}
		for _, d := range act.Diagnostics {
			pos := act.Package.Fset.Position(d.Pos)
			file := pos.Filename
			if rel, err := filepath.Rel(base, file); err == nil && !strings.HasPrefix(rel, "..") {
				file = filepath.ToSlash(rel)
			}
			f := finding{Rule: act.Analyzer.Name, File: file, Line: pos.Line, Column: pos.Column,
				Message: d.Message, Package: act.Package.PkgPath}
			// With -tests a file can belong to a package and to its test variant.
			f.Package = strings.TrimSuffix(strings.SplitN(f.Package, " [", 2)[0], "_test")
			if !seen[f] {
				seen[f] = true
				rep.Findings = append(rep.Findings, f)
			}
		}
	}
	rep.Suppressed = sx.Suppressed.Load()
	sort.Slice(rep.Findings, func(i, j int) bool {
		a, b := rep.Findings[i], rep.Findings[j]
		if a.File != b.File {
			return a.File < b.File
		}
		if a.Line != b.Line {
			return a.Line < b.Line
		}
		return a.Rule < b.Rule
	})

	w := os.Stdout
	if *out != "" {
		f, err := os.Create(*out)
		must(err)
		defer f.Close()
		w = f
	}
	switch *format {
	case "json":
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		enc.SetEscapeHTML(false)
		must(enc.Encode(rep))
	case "text":
		for _, f := range rep.Findings {
			fmt.Fprintf(w, "%s:%d:%d: %s: %s\n", f.File, f.Line, f.Column, f.Rule, f.Message)
		}
		for _, e := range rep.LoadErrors {
			fmt.Fprintf(w, "load error: %s\n", e)
		}
	default:
		fmt.Fprintf(os.Stderr, "shapecov-lint: unknown format %q\n", *format)
		os.Exit(2)
	}
	fmt.Fprintf(os.Stderr, "shapecov-lint: %d packages, %d findings, %d suppressed, %d load errors\n",
		rep.Packages, len(rep.Findings), rep.Suppressed, len(rep.LoadErrors))
	switch {
	case len(rep.LoadErrors) > 0:
		os.Exit(2)
	case len(rep.Findings) > 0:
		os.Exit(1)
	}
}

func must(err error) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "shapecov-lint: %v\n", err)
		os.Exit(2)
	}
}
