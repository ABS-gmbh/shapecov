// Package sc001 implements rule SC001: trusting a field stellar-core does not
// validate.
//
// The rule looks at one function declaration at a time (closures included) and
// reports four patterns. See the README for the exact approximation.
package sc001

import (
	"go/ast"
	"go/constant"
	"go/token"
	"go/types"
	"regexp"
	"strings"

	"golang.org/x/tools/go/analysis"

	"shapecov/linter/internal/sx"
)

const Rule = "SC001"

var validators = `(?i)valid|sanitiz|utf8|quote|^EncodeToString$|^BuildAssets?$|^Parse(Int|Uint|Float|Bool)$`

var Analyzer = &analysis.Analyzer{
	Name: Rule,
	Doc:  "SC001: a field stellar-core does not validate (memo text, contract strings, data values, muxed IDs, declared Soroban credentials) is used without a check",
	Run:  run,
}

func init() {
	Analyzer.Flags.StringVar(&validators, "validators", validators,
		"regular expression; a call to a function or method whose name matches counts as validating its arguments")
}

func run(pass *analysis.Pass) (any, error) {
	re, err := regexp.Compile(validators)
	if err != nil {
		return nil, err
	}
	readsLedger := sx.ReadsLedgerOutput(pass)
	for _, f := range sx.Files(pass) {
		for _, d := range f.Decls {
			if fd, ok := d.(*ast.FuncDecl); ok && fd.Body != nil {
				checkFunc(pass, fd, re, readsLedger)
			}
		}
	}
	return nil, nil
}

type fn struct {
	pass *analysis.Pass
	info *types.Info

	// What validator calls in the function cover.
	valRanges [][2]token.Pos        // source ranges of validator calls
	valExprs  map[string]bool       // printed form of every expression inside a validator call's arguments
	valObjs   map[types.Object]bool // variables mentioned inside a validator call's arguments

	cmpExprs      map[string]bool       // printed form of every expression inside a <, <=, >, >= comparison
	idVars        map[types.Object]bool // variables holding a muxed or memo ID
	muxedTypeSeen bool                  // the function reads MuxedAccount.Type or uses the two-result GetMed25519
	nonceSeen     bool                  // the function refers to ScValTypeScvLedgerKeyNonce
	sacIDVars     map[types.Object]bool // variables holding an Asset's Stellar Asset Contract ID
	sacIDChecked  bool                  // such an ID is compared with == or != (the entry is the asset's own contract)
	readsLedger   bool                  // the package reads ledger output (see sx.ReadsLedgerOutput)
}

func checkFunc(pass *analysis.Pass, fd *ast.FuncDecl, validatorRE *regexp.Regexp, readsLedger bool) {
	f := &fn{
		pass: pass, info: pass.TypesInfo, readsLedger: readsLedger,
		valExprs: map[string]bool{}, valObjs: map[types.Object]bool{},
		cmpExprs: map[string]bool{}, idVars: map[types.Object]bool{}, sacIDVars: map[types.Object]bool{},
	}

	// Pass 1: collect what the function validates, compares and inspects.
	ast.Inspect(fd.Body, func(n ast.Node) bool {
		switch x := n.(type) {
		case *ast.CallExpr:
			if _, conv := sx.IsConversion(f.info, x); !conv && validatorRE.MatchString(sx.CalleeName(x)) {
				f.valRanges = append(f.valRanges, [2]token.Pos{x.Pos(), x.End()})
				for _, a := range x.Args {
					f.recordExprs(a, f.valExprs, f.valObjs)
				}
			}
			if sel, ok := ast.Unparen(x.Fun).(*ast.SelectorExpr); ok &&
				(sel.Sel.Name == "GetMed25519" || sel.Sel.Name == "GetEd25519") &&
				sx.IsXDR(f.info.TypeOf(sel.X), "MuxedAccount") {
				f.muxedTypeSeen = true
			}
		case *ast.BinaryExpr:
			switch x.Op {
			case token.LSS, token.LEQ, token.GTR, token.GEQ:
				f.recordExprs(x.X, f.cmpExprs, nil)
				f.recordExprs(x.Y, f.cmpExprs, nil)
			case token.EQL, token.NEQ:
				if f.mentions(x.X, f.sacIDVars) || f.mentions(x.Y, f.sacIDVars) {
					f.sacIDChecked = true
				}
			}
		case *ast.SelectorExpr:
			if x.Sel.Name == "Type" && sx.IsXDR(f.info.TypeOf(x.X), "MuxedAccount") {
				f.muxedTypeSeen = true
			}
			if x.Sel.Name == "ScValTypeScvLedgerKeyNonce" {
				f.nonceSeen = true
			}
		case *ast.Ident:
			if x.Name == "ScValTypeScvLedgerKeyNonce" {
				f.nonceSeen = true
			}
		case *ast.AssignStmt:
			if len(x.Rhs) == 1 && len(x.Lhs) >= 1 && f.isAssetContractID(x.Rhs[0]) {
				if id, ok := x.Lhs[0].(*ast.Ident); ok {
					if obj := f.info.ObjectOf(id); obj != nil {
						f.sacIDVars[obj] = true
					}
				}
			}
			if len(x.Rhs) == 1 && len(x.Lhs) >= 1 && f.isIDSource(x.Rhs[0]) {
				if id, ok := x.Lhs[0].(*ast.Ident); ok {
					if obj := f.info.ObjectOf(id); obj != nil {
						f.idVars[obj] = true
					}
				}
			}
		case *ast.ValueSpec:
			if len(x.Values) == 1 && len(x.Names) >= 1 && f.isIDSource(x.Values[0]) {
				if obj := f.info.ObjectOf(x.Names[0]); obj != nil {
					f.idVars[obj] = true
				}
			}
		}
		return true
	})

	// Pass 2: find uses.
	sx.WalkStack(fd.Body, func(n ast.Node, stack []ast.Node) bool {
		switch x := n.(type) {
		case *ast.CallExpr:
			f.checkCall(x, stack)
		case *ast.SelectorExpr:
			f.checkSelector(x, stack)
		}
		return true
	})
}

// isAssetContractID reports whether e calls ContractID on an xdr.Asset: the ID of that asset's
// Stellar Asset Contract.
func (f *fn) isAssetContractID(e ast.Expr) bool {
	call, ok := ast.Unparen(e).(*ast.CallExpr)
	if !ok {
		return false
	}
	sel, ok := ast.Unparen(call.Fun).(*ast.SelectorExpr)
	return ok && sel.Sel.Name == "ContractID" && sx.IsXDR(f.info.TypeOf(sel.X), "Asset")
}

// mentions reports whether e refers to any of objs.
func (f *fn) mentions(e ast.Expr, objs map[types.Object]bool) bool {
	found := false
	ast.Inspect(e, func(n ast.Node) bool {
		if id, ok := n.(*ast.Ident); ok && objs[f.info.ObjectOf(id)] {
			found = true
		}
		return !found
	})
	return found
}

// recordExprs records the printed form of e and of every expression inside it,
// and the objects of the identifiers it mentions.
func (f *fn) recordExprs(e ast.Expr, exprs map[string]bool, objs map[types.Object]bool) {
	ast.Inspect(e, func(n ast.Node) bool {
		if ex, ok := n.(ast.Expr); ok {
			exprs[types.ExprString(ex)] = true
		}
		if id, ok := n.(*ast.Ident); ok && objs != nil {
			if obj := f.info.Uses[id]; obj != nil {
				objs[obj] = true
			}
		}
		return true
	})
}

// validated reports whether the text read at src reaches a validator: it sits
// inside a validator call, the same expression is passed to one elsewhere in
// the function, or the variable it is assigned to is.
func (f *fn) validated(src ast.Expr, stack []ast.Node) bool {
	if f.safelyFormatted(src, stack) {
		return true
	}
	for _, r := range f.valRanges {
		if src.Pos() >= r[0] && src.End() <= r[1] {
			return true
		}
	}
	if f.valExprs[types.ExprString(src)] {
		return true
	}
	if call, ok := src.(*ast.CallExpr); ok && len(call.Args) == 1 && f.valExprs[types.ExprString(call.Args[0])] {
		return true
	}
	// The nearest enclosing assignment or var declaration binds the value to
	// a variable; that variable may be validated.
	for i := len(stack) - 1; i >= 0; i-- {
		switch s := stack[i].(type) {
		case *ast.AssignStmt:
			for _, l := range s.Lhs {
				if id, ok := l.(*ast.Ident); ok {
					if obj := f.info.ObjectOf(id); obj != nil && f.valObjs[obj] {
						return true
					}
				}
			}
			return false
		case *ast.ValueSpec:
			for _, id := range s.Names {
				if obj := f.info.ObjectOf(id); obj != nil && f.valObjs[obj] {
					return true
				}
			}
			return false
		case ast.Stmt:
			return false
		}
	}
	return false
}

// isIDSource reports whether e reads a 64-bit ID that stellar-core passes
// through unchecked: the ID of a muxed account or of an ID memo.
func (f *fn) isIDSource(e ast.Expr) bool {
	e = f.unwrapUint64(e)
	switch x := e.(type) {
	case *ast.SelectorExpr:
		if x.Sel.Name == "Id" && sx.IsXDR(f.info.TypeOf(x.X), "MuxedAccountMed25519", "MuxedEd25519Account", "Memo") {
			return true
		}
	case *ast.CallExpr:
		if sel, ok := ast.Unparen(x.Fun).(*ast.SelectorExpr); ok &&
			(sel.Sel.Name == "MustId" || sel.Sel.Name == "GetId") && sx.IsXDR(f.info.TypeOf(sel.X), "Memo") {
			return true
		}
	case *ast.Ident:
		if obj := f.info.Uses[x]; obj != nil && f.idVars[obj] {
			return true
		}
	}
	return false
}

// unwrapUint64 removes parentheses, pointer dereferences and conversions to a
// 64-bit unsigned type, none of which change the value.
func (f *fn) unwrapUint64(e ast.Expr) ast.Expr {
	for {
		switch x := e.(type) {
		case *ast.ParenExpr:
			e = x.X
			continue
		case *ast.StarExpr:
			e = x.X
			continue
		case *ast.CallExpr:
			if t, ok := sx.IsConversion(f.info, x); ok {
				if b, ok := t.Underlying().(*types.Basic); ok && b.Kind() == types.Uint64 {
					e = x.Args[0]
					continue
				}
			}
		}
		return e
	}
}

func (f *fn) checkCall(call *ast.CallExpr, stack []ast.Node) {
	if target, ok := sx.IsConversion(f.info, call); ok {
		f.checkConversion(call, target, stack)
		return
	}
	sel, ok := ast.Unparen(call.Fun).(*ast.SelectorExpr)
	if !ok {
		return
	}
	recv := f.info.TypeOf(sel.X)
	switch {
	case (sel.Sel.Name == "MustText" || sel.Sel.Name == "GetText") && sx.IsXDR(recv, "Memo"):
		if !f.validated(call, stack) {
			sx.Report(f.pass, Rule, call.Pos(),
				"memo text is read with %s() and used without a UTF-8 check; stellar-core accepts any 28 bytes, so validate with utf8.ValidString or store it as bytes", sel.Sel.Name)
		}
	case (sel.Sel.Name == "Address" || sel.Sel.Name == "GetAddress") && sx.IsXDR(recv, "MuxedAccount"):
		if !f.muxedTypeSeen {
			sx.Report(f.pass, Rule, call.Pos(),
				"MuxedAccount.%s() returns the M... form for a muxed account, whose 64-bit ID stellar-core does not validate; call ToAccountId() first or branch on the account Type before using it as an account key", sel.Sel.Name)
		}
	}
}

func (f *fn) checkConversion(call *ast.CallExpr, target types.Type, stack []ast.Node) {
	arg := call.Args[0]
	// Converting a constant reads nothing from the ledger.
	if f.info.Types[arg].Value != nil {
		return
	}
	argT := f.info.TypeOf(arg)
	b, ok := target.Underlying().(*types.Basic)
	if !ok {
		return
	}
	if b.Kind() == types.String {
		if sx.XDRName(target) != "" {
			return // building an XDR string (xdr.ScString(name)) for a transaction, not reading one
		}
		what := ""
		switch {
		case sx.IsXDR(argT, "ScString"):
			what = "a contract-supplied string (xdr.ScString)"
		case sx.IsXDR(argT, "DataValue"):
			what = "a ManageData value (xdr.DataValue)"
		case sx.IsXDR(argT, "ScSymbol"):
			if s, ok := ast.Unparen(arg).(*ast.SelectorExpr); ok && s.Sel.Name == "FunctionName" &&
				sx.IsXDR(f.info.TypeOf(s.X), "InvokeContractArgs") {
				what = "a function name taken from the transaction envelope (xdr.ScSymbol)"
			}
		}
		// A Stellar Asset Contract's stored asset code is bound to the contract's ID: the host
		// validated the code (ASCII alphanumeric) when it created the contract, and a function that
		// derives the contract ID from the asset and compares it with the entry's ID keeps only that
		// contract's entries (go-stellar-sdk's and stellar-etl's AssetFromContractData).
		if sx.IsXDR(argT, "ScString") && f.sacIDChecked {
			return
		}
		if what != "" && !f.validated(call, stack) {
			sx.Report(f.pass, Rule, call.Pos(),
				"%s is converted to string and used without a UTF-8 check; its bytes are arbitrary, so validate with utf8.ValidString (and cap its length) first", what)
		}
		return
	}
	// Narrowing a 64-bit ID.
	narrow := false
	switch b.Kind() {
	case types.Int, types.Int8, types.Int16, types.Int32, types.Int64,
		types.Uint8, types.Uint16, types.Uint32, types.Float32, types.Float64:
		narrow = true
	}
	if !narrow || !f.isIDSource(arg) {
		return
	}
	inner := f.unwrapUint64(arg)
	if f.cmpExprs[types.ExprString(inner)] || f.cmpExprs[types.ExprString(arg)] {
		return
	}
	sx.Report(f.pass, Rule, call.Pos(),
		"a muxed or memo ID is converted to %s with no range check; the ID is any 64-bit value chosen by the submitter, so the result can wrap or lose precision", types.TypeString(target, func(p *types.Package) string { return p.Name() }))
}

func (f *fn) checkSelector(sel *ast.SelectorExpr, stack []ast.Node) {
	xt := f.info.TypeOf(sel.X)
	switch {
	case sel.Sel.Name == "Text" && sx.IsXDR(xt, "Memo"):
		if f.isWriteOrNilCheck(sel, stack) {
			return
		}
		if !f.validated(sel, stack) && !f.validatedDeref(sel, stack) {
			sx.Report(f.pass, Rule, sel.Pos(),
				"memo text is read from Memo.Text and used without a UTF-8 check; stellar-core accepts any 28 bytes, so validate with utf8.ValidString or store it as bytes")
		}
	case sel.Sel.Name == "Address" && sx.IsXDR(xt, "SorobanAddressCredentials"):
		// Reading a declared credential is only a claim taken as fact where the
		// package records ledger output; signers and pre-submission checks read
		// it to build or vet a transaction.
		if !f.readsLedger || f.isWriteOrNilCheck(sel, stack) || f.nonceSeen {
			return
		}
		// Only a field read, not a method call on the credentials.
		if s, ok := f.info.Selections[sel]; ok && s.Kind() != types.FieldVal {
			return
		}
		sx.Report(f.pass, Rule, sel.Pos(),
			"the address in a declared Soroban authorization entry is read as fact; the host never checks entries that no require_auth call matched, so confirm it against the ledger meta (the nonce entry the host creates) before trusting it")
	}
}

// validatedDeref handles `*m.Text`: the dereference, not the selector, is what
// reaches the validator.
func (f *fn) validatedDeref(sel *ast.SelectorExpr, stack []ast.Node) bool {
	if len(stack) >= 2 {
		if star, ok := stack[len(stack)-2].(*ast.StarExpr); ok {
			return f.validated(star, stack[:len(stack)-1])
		}
	}
	return false
}

// isWriteOrNilCheck reports whether the selector is assigned to, or only
// compared with nil.
func (f *fn) isWriteOrNilCheck(sel *ast.SelectorExpr, stack []ast.Node) bool {
	if len(stack) < 2 {
		return false
	}
	switch p := stack[len(stack)-2].(type) {
	case *ast.AssignStmt:
		for _, l := range p.Lhs {
			if l == ast.Expr(sel) {
				return true
			}
		}
	case *ast.BinaryExpr:
		if p.Op == token.EQL || p.Op == token.NEQ {
			other := p.X
			if other == ast.Expr(sel) {
				other = p.Y
			}
			if id, ok := ast.Unparen(other).(*ast.Ident); ok && id.Name == "nil" {
				return true
			}
		}
	}
	return false
}

// fmtFormatArg maps fmt's printf-style functions to the index of their format argument.
var fmtFormatArg = map[string]int{"Sprintf": 0, "Printf": 0, "Errorf": 0, "Fprintf": 1, "Appendf": 1}

// safelyFormatted reports whether the value at src (possibly converted to
// string first) is only an argument of a fmt printf-style call whose verb for
// it is %q, %x or %X. Those escape or hex-encode every byte, so the output is
// valid UTF-8 with no NUL whatever the input was.
func (f *fn) safelyFormatted(src ast.Expr, stack []ast.Node) bool {
	i := len(stack) - 1
	for i >= 0 && stack[i] != ast.Node(src) {
		i--
	}
	if i < 0 {
		return false
	}
	cur := ast.Node(src)
	for j := i - 1; j >= 0; j-- {
		switch p := stack[j].(type) {
		case *ast.ParenExpr, *ast.StarExpr:
			cur = p
		case *ast.CallExpr:
			if t, ok := sx.IsConversion(f.info, p); ok {
				if b, ok := t.Underlying().(*types.Basic); ok && b.Kind() == types.String {
					cur = p
					continue
				}
				return false
			}
			return f.safeVerb(p, cur)
		default:
			return false
		}
	}
	return false
}

func (f *fn) safeVerb(call *ast.CallExpr, arg ast.Node) bool {
	sel, ok := ast.Unparen(call.Fun).(*ast.SelectorExpr)
	if !ok {
		return false
	}
	id, ok := sel.X.(*ast.Ident)
	if !ok {
		return false
	}
	pkg, ok := f.info.Uses[id].(*types.PkgName)
	if !ok || pkg.Imported().Path() != "fmt" {
		return false
	}
	fi, ok := fmtFormatArg[sel.Sel.Name]
	if !ok || fi >= len(call.Args) {
		return false
	}
	tv := f.info.Types[call.Args[fi]]
	if tv.Value == nil || tv.Value.Kind() != constant.String {
		return false
	}
	verbs := printfVerbs(constant.StringVal(tv.Value))
	for k, a := range call.Args[fi+1:] {
		if ast.Node(a) == arg {
			return k < len(verbs) && strings.ContainsRune("qxX", verbs[k])
		}
	}
	return false
}

// printfVerbs returns the verb of each argument a format string consumes, or
// nil when the format uses * or explicit argument indexes, which this does not follow.
func printfVerbs(format string) []rune {
	var verbs []rune
	rs := []rune(format)
	for i := 0; i < len(rs); i++ {
		if rs[i] != '%' {
			continue
		}
		i++
		for i < len(rs) && strings.ContainsRune("+-# 0123456789.", rs[i]) {
			i++
		}
		if i >= len(rs) {
			break
		}
		switch rs[i] {
		case '%':
			continue
		case '*', '[':
			return nil
		}
		verbs = append(verbs, rs[i])
	}
	return verbs
}
