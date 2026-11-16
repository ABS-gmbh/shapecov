// Package sc003 implements rule SC003: participants (the accounts a
// transaction affected) are derived from the transaction envelope instead of
// from the ledger meta.
//
// The rule follows values read from envelope types into collections whose
// name says they hold participants. See the README for the exact
// approximation.
package sc003

import (
	"go/ast"
	"go/token"
	"go/types"
	"regexp"
	"strings"

	"golang.org/x/tools/go/analysis"

	"shapecov/linter/internal/sx"
)

const Rule = "SC003"

var (
	sinkPattern = `(?i)participant|affected|involved`
	strict      = false
)

var Analyzer = &analysis.Analyzer{
	Name: Rule,
	Doc:  "SC003: a participant set is filled from the transaction envelope (operation bodies, the declared Soroban authorization tree) instead of the ledger meta",
	Run:  run,
}

func init() {
	Analyzer.Flags.StringVar(&sinkPattern, "sinks", sinkPattern,
		"regular expression; a variable, field or function whose name matches is treated as holding participants")
	Analyzer.Flags.BoolVar(&strict, "strict", strict,
		"also report envelope-derived participants that are guarded by a transaction-success check")
}

type kind int

const (
	none kind = iota
	env       // read from an operation body or the envelope
	auth      // read from the declared Soroban authorization tree
)

// authTypes are the envelope types that make up the declared authorization
// tree. A successful transaction does not vouch for them: the host only checks
// the entries a require_auth call matched.
var authTypes = map[string]bool{
	"SorobanAuthorizationEntry": true, "SorobanCredentials": true, "SorobanAddressCredentials": true,
	"SorobanAuthorizedInvocation": true, "SorobanAuthorizedFunction": true,
}

// envTypes are the other envelope types. Every xdr struct whose name ends in
// "Op" (PaymentOp, CreateAccountOp, ...) counts as well.
var envTypes = map[string]bool{
	"TransactionEnvelope": true, "Transaction": true, "TransactionV0": true,
	"TransactionV1Envelope": true, "TransactionV0Envelope": true,
	"FeeBumpTransaction": true, "FeeBumpTransactionEnvelope": true, "FeeBumpTransactionInnerTx": true,
	"Operation": true, "OperationBody": true,
	"HostFunction": true, "InvokeContractArgs": true, "CreateContractArgs": true, "CreateContractArgsV2": true,
	"Claimant": true, "ClaimantV0": true,
}

// sourceNames are selectors that yield a transaction or operation source
// account. stellar-core checks the source account's signature and sequence
// number, so it is not treated as an unverified claim.
var sourceNames = map[string]bool{
	"SourceAccount": true, "FeeBumpAccount": true, "FeeSource": true, "SourceAccountEd25519": true,
}

var successRE = regexp.MustCompile(`^(Is|Was)?(Inner)?Success(ful)?$|TxSuccess$|TxFeeBumpInnerSuccess$`)

var sinkMethodRE = regexp.MustCompile(`^(Add|Append|Insert|Push|Put|Set|Store|Union|Merge|Extend|Update)`)

func typeKind(t types.Type) kind {
	name := sx.XDRName(sx.Strip(t))
	switch {
	case name == "":
		return none
	case authTypes[name]:
		return auth
	case envTypes[name]:
		return env
	case strings.HasSuffix(name, "Op"):
		return env
	}
	return none
}

type site struct {
	caller *ast.FuncDecl
	pos    token.Pos
}

type state struct {
	pass    *analysis.Pass
	info    *types.Info
	sinkRE  *regexp.Regexp
	sites   map[types.Object][]site        // in-package static call sites of each function
	success map[*ast.FuncDecl][]token.Pos  // positions of success checks in each function
	declObj map[*ast.FuncDecl]types.Object // the object each declaration defines
	declOf  map[types.Object]*ast.FuncDecl // the declaration of each function in the package
}

func run(pass *analysis.Pass) (any, error) {
	re, err := regexp.Compile(sinkPattern)
	if err != nil {
		return nil, err
	}
	st := &state{pass: pass, info: pass.TypesInfo, sinkRE: re,
		sites: map[types.Object][]site{}, success: map[*ast.FuncDecl][]token.Pos{}, declObj: map[*ast.FuncDecl]types.Object{},
		declOf: map[types.Object]*ast.FuncDecl{}}

	var decls []*ast.FuncDecl
	// Call sites and success checks come from the same files that are
	// analysed (no generated files, no tests unless asked for).
	for _, f := range sx.Files(pass) {
		for _, d := range f.Decls {
			fd, ok := d.(*ast.FuncDecl)
			if !ok || fd.Body == nil {
				continue
			}
			st.declObj[fd] = st.info.Defs[fd.Name]
			if obj := st.info.Defs[fd.Name]; obj != nil {
				st.declOf[obj] = fd
			}
			ast.Inspect(fd.Body, func(n ast.Node) bool {
				switch x := n.(type) {
				case *ast.Ident:
					if successRE.MatchString(x.Name) {
						st.success[fd] = append(st.success[fd], x.Pos())
					}
				case *ast.CallExpr:
					var obj types.Object
					switch f := ast.Unparen(x.Fun).(type) {
					case *ast.Ident:
						obj = st.info.Uses[f]
					case *ast.SelectorExpr:
						obj = st.info.Uses[f.Sel]
					}
					if fn, ok := obj.(*types.Func); ok && fn.Pkg() == pass.Pkg {
						st.sites[fn.Origin()] = append(st.sites[fn.Origin()], site{fd, x.Pos()})
					}
				}
				return true
			})
		}
	}
	for _, f := range sx.Files(pass) {
		for _, d := range f.Decls {
			if fd, ok := d.(*ast.FuncDecl); ok && fd.Body != nil {
				decls = append(decls, fd)
			}
		}
	}
	for _, fd := range decls {
		st.checkFunc(fd)
	}
	return nil, nil
}

// guardedAt reports whether fd checks transaction success before pos.
func (st *state) guardedAt(fd *ast.FuncDecl, pos token.Pos) bool {
	for _, p := range st.success[fd] {
		if p < pos {
			return true
		}
	}
	return false
}

// guardedCallee reports whether call calls a function of this package whose first statement
// returns early when the transaction did not succeed, and whose early return carries no envelope
// data beyond the source and fee accounts. One level only: the callee's own callees are not
// followed, and a function of another package is never trusted.
func (st *state) guardedCallee(call *ast.CallExpr) bool {
	var obj types.Object
	switch f := ast.Unparen(call.Fun).(type) {
	case *ast.Ident:
		obj = st.info.Uses[f]
	case *ast.SelectorExpr:
		obj = st.info.Uses[f.Sel]
	}
	fn, ok := obj.(*types.Func)
	if !ok || fn.Pkg() != st.pass.Pkg {
		return false
	}
	fd := st.declOf[fn.Origin()]
	if fd == nil || fd.Body == nil || len(fd.Body.List) == 0 {
		return false
	}
	ifs, ok := fd.Body.List[0].(*ast.IfStmt)
	if !ok || ifs.Init != nil || ifs.Else != nil || len(ifs.Body.List) == 0 {
		return false
	}
	// The condition: the negation of a success check (!tx.Successful(), !op.Transaction.Successful()).
	not, ok := ast.Unparen(ifs.Cond).(*ast.UnaryExpr)
	if !ok || not.Op != token.NOT || !isSuccessCheck(not.X) {
		return false
	}
	if _, ok := ifs.Body.List[len(ifs.Body.List)-1].(*ast.ReturnStmt); !ok {
		return false
	}
	// The early return may name the source and fee accounts, and ask yes/no questions of the
	// envelope (IsFeeBump), but nothing else from it.
	clean := true
	ast.Inspect(ifs.Body, func(n ast.Node) bool {
		if !clean {
			return false
		}
		switch x := n.(type) {
		case *ast.FuncLit:
			clean = false
			return false
		case *ast.SelectorExpr:
			if sourceNames[x.Sel.Name] {
				return false
			}
		case *ast.CallExpr:
			if t := st.info.TypeOf(x); t != nil && types.Identical(t.Underlying(), types.Typ[types.Bool]) {
				return false
			}
		}
		if ex, ok := n.(ast.Expr); ok {
			if tv, ok := st.info.Types[ex]; ok && !tv.IsType() && typeKind(tv.Type) != none {
				clean = false
				return false
			}
		}
		return true
	})
	return clean
}

// isSuccessCheck reports whether e is a call or selector whose name is a success check.
func isSuccessCheck(e ast.Expr) bool {
	switch x := ast.Unparen(e).(type) {
	case *ast.CallExpr:
		return isSuccessCheck(x.Fun)
	case *ast.SelectorExpr:
		return successRE.MatchString(x.Sel.Name)
	case *ast.Ident:
		return successRE.MatchString(x.Name)
	}
	return false
}

// guardedByCallers reports whether fd is called from inside the package and
// every such call comes after a success check, in the caller or further up.
func (st *state) guardedByCallers(fd *ast.FuncDecl, seen map[*ast.FuncDecl]bool) bool {
	if seen[fd] {
		return false
	}
	seen[fd] = true
	obj := st.declObj[fd]
	sites := st.sites[obj]
	if obj == nil || len(sites) == 0 {
		return false
	}
	outside := 0
	for _, s := range sites {
		if s.caller == fd {
			continue // a recursive call adds no information
		}
		outside++
		if st.guardedAt(s.caller, s.pos) || st.guardedByCallers(s.caller, seen) {
			continue
		}
		return false
	}
	return outside > 0
}

func (st *state) checkFunc(fd *ast.FuncDecl) {
	vars := map[types.Object]kind{}

	taintAt := map[types.Object]token.Pos{} // earliest position where each variable is tainted

	var kindOfIf func(e ast.Node, count func(types.Object) bool) kind
	kindOfIf = func(e ast.Node, count func(types.Object) bool) kind {
		k := none
		if e == nil {
			return k
		}
		ast.Inspect(e, func(n ast.Node) bool {
			switch x := n.(type) {
			case *ast.FuncLit:
				return false
			case *ast.CallExpr:
				// len and cap of envelope data are only numbers (a capacity hint, a loop bound).
				if id, ok := ast.Unparen(x.Fun).(*ast.Ident); ok {
					if _, builtin := st.info.Uses[id].(*types.Builtin); builtin && (id.Name == "len" || id.Name == "cap") {
						return false
					}
				}
				// The result of a function of this package that returns early for a failed
				// transaction is guarded, whatever its arguments (not in strict mode).
				if !strict && st.guardedCallee(x) {
					return false
				}
			case *ast.CompositeLit:
				// A keyed struct literal with a field named as holding participants: only those
				// fields carry participants; the others (an operation wrapper, an index) are context.
				var sinkVals []ast.Expr
				for _, el := range x.Elts {
					if kv, ok := el.(*ast.KeyValueExpr); ok {
						if key, ok := kv.Key.(*ast.Ident); ok && st.sinkRE.MatchString(key.Name) {
							sinkVals = append(sinkVals, kv.Value)
						}
					}
				}
				if len(sinkVals) > 0 {
					for _, v := range sinkVals {
						if vk := kindOfIf(v, count); vk > k {
							k = vk
						}
					}
					return false
				}
			case *ast.SelectorExpr:
				if sourceNames[x.Sel.Name] {
					return false
				}
			case *ast.Ident:
				if obj := st.info.Uses[x]; obj != nil && vars[obj] > k && (count == nil || count(obj)) {
					k = vars[obj]
				}
			}
			if ex, ok := n.(ast.Expr); ok {
				if tv, ok := st.info.Types[ex]; ok && !tv.IsType() {
					if tk := typeKind(tv.Type); tk > k {
						k = tk
					}
				}
			}
			return true
		})
		return k
	}
	kindOf := func(e ast.Node) kind { return kindOfIf(e, nil) }

	// Propagate through local variables until nothing changes. Variables that
	// are themselves participant collections are sinks, not carriers.
	set := func(lhs ast.Expr, k kind) bool {
		id, ok := lhs.(*ast.Ident)
		if !ok || id.Name == "_" || k == none || st.sinkRE.MatchString(id.Name) {
			return false
		}
		obj := st.info.ObjectOf(id)
		if obj != nil {
			if p, ok := taintAt[obj]; !ok || lhs.Pos() < p {
				taintAt[obj] = lhs.Pos()
			}
		}
		if obj == nil || vars[obj] >= k {
			return false
		}
		vars[obj] = k
		return true
	}
	for changed := true; changed; {
		changed = false
		ast.Inspect(fd.Body, func(n ast.Node) bool {
			switch x := n.(type) {
			case *ast.AssignStmt:
				if len(x.Rhs) == 1 {
					k := kindOf(x.Rhs[0])
					for _, l := range x.Lhs {
						changed = set(l, k) || changed
					}
				} else if len(x.Rhs) == len(x.Lhs) {
					for i := range x.Lhs {
						changed = set(x.Lhs[i], kindOf(x.Rhs[i])) || changed
					}
				}
			case *ast.ValueSpec:
				if len(x.Values) == 1 {
					k := kindOf(x.Values[0])
					for _, id := range x.Names {
						changed = set(id, k) || changed
					}
				} else if len(x.Values) == len(x.Names) {
					for i := range x.Names {
						changed = set(x.Names[i], kindOf(x.Values[i])) || changed
					}
				}
			case *ast.RangeStmt:
				k := kindOf(x.X)
				if x.Value != nil {
					changed = set(x.Value, k) || changed
				}
				if x.Key != nil {
					if _, isMap := st.info.TypeOf(x.X).Underlying().(*types.Map); isMap {
						changed = set(x.Key, k) || changed
					}
				}
			}
			return true
		})
	}

	reported := map[int]bool{}
	report := func(pos token.Pos, k kind, into string) {
		if k == none {
			return
		}
		line := st.pass.Fset.Position(pos).Line
		if reported[line] {
			return
		}
		switch k {
		case auth:
			reported[line] = true
			sx.Report(st.pass, Rule, pos,
				"%s is filled from the declared Soroban authorization tree; the submitter writes that tree and the host checks only the entries a require_auth call matched, so take authorisers from the ledger meta instead", into)
		case env:
			if !strict && (st.guardedAt(fd, pos) || st.guardedByCallers(fd, map[*ast.FuncDecl]bool{})) {
				return
			}
			reported[line] = true
			msg := "%s is filled from the transaction envelope with no check that the transaction succeeded; the envelope records what the submitter claimed, so derive participants from the ledger meta or return only the source account for a failed transaction"
			if strict {
				msg = "%s is filled from the transaction envelope (strict mode: reported even when a success check guards it); the ledger meta records what stellar-core actually changed"
			}
			sx.Report(st.pass, Rule, pos, msg, into)
		}
	}

	fnIsSink := st.sinkRE.MatchString(fd.Name.Name)
	// taintedBy reports whether a variable can already hold envelope or tree data
	// when control reaches pos: it was tainted earlier in the source, or a loop
	// enclosing pos also encloses the taint (a later iteration can return it).
	taintedBy := func(pos token.Pos, stack []ast.Node) func(types.Object) bool {
		return func(obj types.Object) bool {
			at, ok := taintAt[obj]
			if !ok || at < pos {
				return true
			}
			for _, n := range stack {
				switch n.(type) {
				case *ast.ForStmt, *ast.RangeStmt:
					if n.Pos() <= at && at < n.End() {
						return true
					}
				}
			}
			return false
		}
	}
	sx.WalkStack(fd.Body, func(n ast.Node, stack []ast.Node) bool {
		switch x := n.(type) {
		case *ast.AssignStmt:
			for i, l := range x.Lhs {
				name := rootName(l)
				if name == "" || !st.sinkRE.MatchString(name) {
					continue
				}
				var rhs ast.Expr
				if len(x.Rhs) == 1 {
					rhs = x.Rhs[0]
				} else if i < len(x.Rhs) {
					rhs = x.Rhs[i]
				}
				k := kindOf(rhs)
				if ix, ok := l.(*ast.IndexExpr); ok && !isInteger(st.info.TypeOf(ix.Index)) {
					// An integer key (an operation ID, a position) names no account.
					if ik := kindOf(ix.Index); ik > k {
						k = ik
					}
				}
				report(x.Pos(), k, name)
			}
		case *ast.ValueSpec:
			for i, id := range x.Names {
				if !st.sinkRE.MatchString(id.Name) {
					continue
				}
				var rhs ast.Expr
				if len(x.Values) == 1 {
					rhs = x.Values[0]
				} else if i < len(x.Values) {
					rhs = x.Values[i]
				}
				report(x.Pos(), kindOf(rhs), id.Name)
			}
		case *ast.CallExpr:
			sel, ok := ast.Unparen(x.Fun).(*ast.SelectorExpr)
			if !ok || !sinkMethodRE.MatchString(sel.Sel.Name) {
				return true
			}
			name := rootName(sel.X)
			if name == "" || !st.sinkRE.MatchString(name) {
				return true
			}
			k := none
			for _, a := range x.Args {
				if ak := kindOf(a); ak > k {
					k = ak
				}
			}
			report(x.Pos(), k, name)
		case *ast.ReturnStmt:
			if !fnIsSink {
				return true
			}
			k := none
			for _, r := range x.Results {
				if t := st.info.TypeOf(r); t != nil && types.Identical(t, types.Universe.Lookup("error").Type()) {
					continue // an error value that quotes the envelope is not a participant
				}
				if rk := kindOfIf(r, taintedBy(x.Pos(), stack)); rk > k {
					k = rk
				}
			}
			report(x.Pos(), k, "the result of "+fd.Name.Name)
		}
		return true
	})
}

// isInteger reports whether t is an integer type.
func isInteger(t types.Type) bool {
	if t == nil {
		return false
	}
	b, ok := t.Underlying().(*types.Basic)
	return ok && b.Info()&types.IsInteger != 0
}

// rootName returns the name that identifies a collection expression: the
// identifier itself, the selected field, or the indexed collection.
func rootName(e ast.Expr) string {
	switch x := ast.Unparen(e).(type) {
	case *ast.Ident:
		return x.Name
	case *ast.SelectorExpr:
		return x.Sel.Name
	case *ast.IndexExpr:
		return rootName(x.X)
	case *ast.StarExpr:
		return rootName(x.X)
	}
	return ""
}
