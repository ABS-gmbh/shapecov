// Package sx holds what the three analyzers share: recognising go-stellar-sdk
// XDR types, choosing which files to look at, and reporting with support for
// the //shapecov:ignore comment.
package sx

import (
	"fmt"
	"go/ast"
	"go/token"
	"go/types"
	"regexp"
	"strings"
	"sync/atomic"

	"golang.org/x/tools/go/analysis"
)

// HonorIgnores controls whether //shapecov:ignore comments suppress findings.
var HonorIgnores = true

// IncludeTests controls whether _test.go files are analysed.
var IncludeTests = false

// Suppressed counts findings dropped because of an ignore comment.
var Suppressed atomic.Int64

// IsSDKPkg reports whether p is the named sub-package (for example "xdr" or
// "ingest") of the Stellar Go SDK, under either its current module path
// (github.com/stellar/go-stellar-sdk) or the former one (github.com/stellar/go).
func IsSDKPkg(p *types.Package, sub string) bool {
	if p == nil {
		return false
	}
	path := p.Path()
	if i := strings.LastIndex(path, "/vendor/"); i >= 0 {
		path = path[i+len("/vendor/"):]
	}
	return path == "github.com/stellar/go-stellar-sdk/"+sub || path == "github.com/stellar/go/"+sub
}

// Deref removes pointers from t.
func Deref(t types.Type) types.Type {
	for t != nil {
		p, ok := types.Unalias(t).(*types.Pointer)
		if !ok {
			return t
		}
		t = p.Elem()
	}
	return t
}

// Strip removes pointers, slices and arrays from t, so that []*xdr.ScVal
// yields xdr.ScVal.
func Strip(t types.Type) types.Type {
	for t != nil {
		switch u := types.Unalias(t).(type) {
		case *types.Pointer:
			t = u.Elem()
		case *types.Slice:
			t = u.Elem()
		case *types.Array:
			t = u.Elem()
		default:
			return t
		}
	}
	return t
}

// XDRName returns the type name if t (after removing pointers) is a named type
// declared in the SDK's xdr package, and "" otherwise.
func XDRName(t types.Type) string {
	n, ok := types.Unalias(Deref(t)).(*types.Named)
	if !ok || n.Obj() == nil || !IsSDKPkg(n.Obj().Pkg(), "xdr") {
		return ""
	}
	return n.Obj().Name()
}

// IsXDR reports whether t (after removing pointers) is one of the named xdr types.
func IsXDR(t types.Type, names ...string) bool {
	got := XDRName(t)
	if got == "" {
		return false
	}
	for _, n := range names {
		if n == got {
			return true
		}
	}
	return false
}

// IsIntegerish reports whether t is an integer type or a pointer to one.
func IsIntegerish(t types.Type) bool {
	if t == nil {
		return false
	}
	b, ok := Deref(t).Underlying().(*types.Basic)
	return ok && b.Info()&types.IsInteger != 0
}

// Files returns the files of the pass that should be analysed: generated
// files are skipped, and so are _test.go files unless IncludeTests is set.
func Files(pass *analysis.Pass) []*ast.File {
	var out []*ast.File
	for _, f := range pass.Files {
		if ast.IsGenerated(f) {
			continue
		}
		name := pass.Fset.Position(f.Pos()).Filename
		if !IncludeTests && strings.HasSuffix(name, "_test.go") {
			continue
		}
		out = append(out, f)
	}
	return out
}

var ignoreRE = regexp.MustCompile(`^//\s*shapecov:ignore\s+(SC\d{3})\s+\S`)

// ignored reports whether a "//shapecov:ignore RULE reason" comment sits on
// the line of pos or on the line directly above it. The reason is mandatory:
// a comment without one does not suppress anything.
func ignored(pass *analysis.Pass, rule string, pos token.Pos) bool {
	line := pass.Fset.Position(pos).Line
	for _, f := range pass.Files {
		if pos < f.FileStart || pos > f.FileEnd {
			continue
		}
		for _, cg := range f.Comments {
			for _, c := range cg.List {
				m := ignoreRE.FindStringSubmatch(c.Text)
				if m == nil || m[1] != rule {
					continue
				}
				cl := pass.Fset.Position(c.Pos()).Line
				if cl == line || cl == line-1 {
					return true
				}
			}
		}
	}
	return false
}

// Report emits a diagnostic for rule at pos unless an ignore comment covers it.
func Report(pass *analysis.Pass, rule string, pos token.Pos, format string, args ...any) {
	if HonorIgnores && ignored(pass, rule, pos) {
		Suppressed.Add(1)
		return
	}
	pass.Report(analysis.Diagnostic{Pos: pos, Category: rule, Message: fmt.Sprintf(format, args...)})
}

// WalkStack walks root like ast.Inspect and passes the stack of enclosing
// nodes (root first, n last) to fn. If fn returns false the children of n are
// skipped.
func WalkStack(root ast.Node, fn func(n ast.Node, stack []ast.Node) bool) {
	var stack []ast.Node
	ast.Inspect(root, func(n ast.Node) bool {
		if n == nil {
			stack = stack[:len(stack)-1]
			return true
		}
		stack = append(stack, n)
		if !fn(n, stack) {
			stack = stack[:len(stack)-1]
			return false
		}
		return true
	})
}

// CalleeName returns the bare name of the function or method a call invokes
// ("ValidString" for utf8.ValidString(x)), or "" for calls through other
// expressions.
func CalleeName(call *ast.CallExpr) string {
	switch f := ast.Unparen(call.Fun).(type) {
	case *ast.Ident:
		return f.Name
	case *ast.SelectorExpr:
		return f.Sel.Name
	case *ast.IndexExpr:
		if id, ok := f.X.(*ast.Ident); ok {
			return id.Name
		}
		if s, ok := f.X.(*ast.SelectorExpr); ok {
			return s.Sel.Name
		}
	}
	return ""
}

// IsConversion reports whether call is a type conversion and returns the
// target type.
func IsConversion(info *types.Info, call *ast.CallExpr) (types.Type, bool) {
	if len(call.Args) != 1 {
		return nil, false
	}
	tv, ok := info.Types[call.Fun]
	if !ok || !tv.IsType() {
		return nil, false
	}
	return tv.Type, true
}
