// Package sc002 implements rule SC002: a traversal of a recursive XDR
// structure (nested ScVals, Soroban authorization trees, contract spec types)
// with no depth or size cap.
//
// Two patterns are reported: recursive functions (direct, mutual, or through a
// closure bound to a variable) and explicit work-list loops. See the README
// for the exact approximation.
package sc002

import (
	"go/ast"
	"go/token"
	"go/types"

	"golang.org/x/tools/go/analysis"

	"shapecov/linter/internal/sx"
)

const Rule = "SC002"

var Analyzer = &analysis.Analyzer{
	Name: Rule,
	Doc:  "SC002: a recursive function or work-list loop walks a recursive XDR structure (ScVal, SorobanAuthorizedInvocation, ScSpecTypeDef) with no depth or size cap",
	Run:  run,
}

// recursiveTypes are the xdr types that can nest to a depth the submitter or a
// contract chooses. ClaimPredicate is left out on purpose: stellar-core
// rejects predicates nested deeper than four levels.
var recursiveTypes = []string{
	"ScVal", "ScVec", "ScMap", "ScMapEntry",
	"SorobanAuthorizedInvocation",
	"ScSpecTypeDef", "ScSpecTypeOption", "ScSpecTypeResult", "ScSpecTypeVec", "ScSpecTypeMap", "ScSpecTypeTuple",
}

func recursiveXDR(t types.Type) string {
	t = sx.Strip(t)
	if m, ok := types.Unalias(t).Underlying().(*types.Map); ok && sx.XDRName(t) == "" {
		t = sx.Strip(m.Elem())
	}
	if sx.IsXDR(t, recursiveTypes...) {
		return "xdr." + sx.XDRName(t)
	}
	return ""
}

type node struct {
	name  string
	pos   token.Pos
	ftype *ast.FuncType
	recv  *ast.FieldList
	body  *ast.BlockStmt
	lit   *ast.FuncLit // nil for declared functions
	calls []edge

	// Tarjan state.
	index, low int
	onStack    bool
	scc        int
}

type edge struct {
	to   *node
	call *ast.CallExpr
}

func run(pass *analysis.Pass) (any, error) {
	info := pass.TypesInfo
	nodes := map[types.Object]*node{}
	lits := map[*ast.FuncLit]*node{}
	var order []*node

	files := sx.Files(pass)
	for _, f := range files {
		for _, d := range f.Decls {
			fd, ok := d.(*ast.FuncDecl)
			if !ok || fd.Body == nil {
				continue
			}
			if obj := info.Defs[fd.Name]; obj != nil {
				n := &node{name: fd.Name.Name, pos: fd.Name.Pos(), ftype: fd.Type, recv: fd.Recv, body: fd.Body}
				nodes[obj] = n
				order = append(order, n)
			}
		}
		// Closures bound to a variable: `walk = func(...) {...}` or `walk := func...`.
		ast.Inspect(f, func(n ast.Node) bool {
			bind := func(lhs ast.Expr, rhs ast.Expr) {
				id, ok := lhs.(*ast.Ident)
				lit, ok2 := rhs.(*ast.FuncLit)
				if !ok || !ok2 {
					return
				}
				obj := info.ObjectOf(id)
				if obj == nil || nodes[obj] != nil {
					return
				}
				nd := &node{name: id.Name, pos: lit.Pos(), ftype: lit.Type, body: lit.Body, lit: lit}
				nodes[obj] = nd
				lits[lit] = nd
				order = append(order, nd)
			}
			switch x := n.(type) {
			case *ast.AssignStmt:
				if len(x.Lhs) == len(x.Rhs) {
					for i := range x.Lhs {
						bind(x.Lhs[i], x.Rhs[i])
					}
				}
			case *ast.ValueSpec:
				if len(x.Names) == len(x.Values) {
					for i := range x.Names {
						bind(x.Names[i], x.Values[i])
					}
				}
			}
			return true
		})
	}

	// Call edges. A bound closure is its own node, so its body is skipped when
	// walking the function that contains it.
	for _, n := range order {
		n := n
		walkBody(n, lits, func(x ast.Node) {
			call, ok := x.(*ast.CallExpr)
			if !ok {
				return
			}
			var obj types.Object
			switch f := ast.Unparen(call.Fun).(type) {
			case *ast.Ident:
				obj = info.Uses[f]
			case *ast.SelectorExpr:
				obj = info.Uses[f.Sel]
			case *ast.IndexExpr: // explicit instantiation of a generic function
				if id, ok := f.X.(*ast.Ident); ok {
					obj = info.Uses[id]
				}
			}
			if fn, ok := obj.(*types.Func); ok {
				obj = fn.Origin()
			}
			if to := nodes[obj]; to != nil {
				n.calls = append(n.calls, edge{to, call})
			}
		})
	}

	sccs := tarjan(order)
	for _, scc := range sccs {
		if len(scc) == 1 && !selfCall(scc[0]) {
			continue
		}
		in := map[*node]bool{}
		for _, n := range scc {
			in[n] = true
		}
		bounded := false
		for _, n := range scc {
			if hasDepthBound(info, n, in, lits) {
				bounded = true
				break
			}
		}
		if bounded {
			continue
		}
		for _, n := range scc {
			if t := carries(info, n); t != "" {
				kind := "function"
				if n.lit != nil {
					kind = "closure"
				}
				sx.Report(pass, Rule, n.pos,
					"recursive %s %s walks %s with no depth cap; nesting is chosen by the transaction submitter or a contract, so pass a depth counter and stop at a fixed limit", kind, n.name, t)
			}
		}
	}

	for _, f := range files {
		ast.Inspect(f, func(n ast.Node) bool {
			if loop, ok := n.(*ast.ForStmt); ok {
				checkWorklist(pass, loop)
			}
			return true
		})
	}
	return nil, nil
}

func walkBody(n *node, lits map[*ast.FuncLit]*node, fn func(ast.Node)) {
	ast.Inspect(n.body, func(x ast.Node) bool {
		if lit, ok := x.(*ast.FuncLit); ok && lits[lit] != nil && lits[lit] != n {
			return false
		}
		if x != nil {
			fn(x)
		}
		return true
	})
}

func selfCall(n *node) bool {
	for _, e := range n.calls {
		if e.to == n {
			return true
		}
	}
	return false
}

// carries returns the recursive xdr type among n's parameters or receiver.
func carries(info *types.Info, n *node) string {
	check := func(fl *ast.FieldList) string {
		if fl == nil {
			return ""
		}
		for _, f := range fl.List {
			if t := recursiveXDR(info.TypeOf(f.Type)); t != "" {
				return t
			}
		}
		return ""
	}
	if t := check(n.ftype.Params); t != "" {
		return t
	}
	return check(n.recv)
}

// hasDepthBound reports whether n limits the recursion: some integer variable
// that outlives one call (a parameter, a struct field, or a variable declared
// outside n's body) is compared in a condition in n and also changes, either
// by assignment or increment in n or by being passed in changed form to a
// function of the same cycle.
func hasDepthBound(info *types.Info, n *node, scc map[*node]bool, lits map[*ast.FuncLit]*node) bool {
	local := func(obj types.Object) bool {
		return obj.Pos() >= n.body.Pos() && obj.Pos() < n.body.End()
	}
	objsIn := func(e ast.Node, into map[types.Object]bool) {
		ast.Inspect(e, func(x ast.Node) bool {
			var id *ast.Ident
			switch y := x.(type) {
			case *ast.Ident:
				id = y
			case *ast.SelectorExpr:
				id = y.Sel
			}
			if id != nil {
				if v, ok := info.Uses[id].(*types.Var); ok && sx.IsIntegerish(v.Type()) && !local(v) {
					into[v] = true
				}
			}
			return true
		})
	}
	compared := map[types.Object]bool{}
	changed := map[types.Object]bool{}
	walkBody(n, lits, func(x ast.Node) {
		switch s := x.(type) {
		case *ast.BinaryExpr:
			switch s.Op {
			case token.LSS, token.LEQ, token.GTR, token.GEQ, token.EQL, token.NEQ:
				objsIn(s, compared)
			}
		case *ast.IncDecStmt:
			objsIn(s.X, changed)
		case *ast.AssignStmt:
			if s.Tok != token.DEFINE {
				for _, l := range s.Lhs {
					objsIn(l, changed)
				}
			}
		case *ast.CallExpr:
			for _, e := range n.calls {
				if e.call != s || !scc[e.to] {
					continue
				}
				for _, a := range s.Args {
					if _, bare := ast.Unparen(a).(*ast.Ident); bare {
						continue
					}
					if _, bare := ast.Unparen(a).(*ast.SelectorExpr); bare {
						continue
					}
					objsIn(a, changed)
				}
			}
		}
	})
	for o := range compared {
		if changed[o] {
			return true
		}
	}
	return false
}

// checkWorklist reports a `for` loop that drains a slice of a recursive xdr
// type while appending to it, with nothing that caps the number of items.
func checkWorklist(pass *analysis.Pass, loop *ast.ForStmt) {
	info := pass.TypesInfo
	if loop.Cond == nil {
		return
	}
	// Slices of recursive xdr values that the loop body appends to.
	var queue types.Object
	var qtype string
	ast.Inspect(loop.Body, func(x ast.Node) bool {
		as, ok := x.(*ast.AssignStmt)
		if !ok || len(as.Lhs) != 1 || len(as.Rhs) != 1 {
			return true
		}
		call, ok := as.Rhs[0].(*ast.CallExpr)
		if !ok || sx.CalleeName(call) != "append" {
			return true
		}
		id, ok := as.Lhs[0].(*ast.Ident)
		if !ok {
			return true
		}
		obj := info.ObjectOf(id)
		if obj == nil {
			return true
		}
		if _, isSlice := types.Unalias(obj.Type()).Underlying().(*types.Slice); !isSlice {
			return true
		}
		if t := recursiveXDR(obj.Type()); t != "" && mentions(info, loop.Cond, obj) {
			queue, qtype = obj, t
		}
		return true
	})
	if queue == nil {
		return
	}
	// A cap is a comparison, other than the loop condition itself, that either
	// tests the queue or tests an integer the loop changes.
	changed := map[types.Object]bool{}
	note := func(e ast.Expr) {
		ast.Inspect(e, func(x ast.Node) bool {
			if id, ok := x.(*ast.Ident); ok {
				if v, ok := info.Uses[id].(*types.Var); ok && sx.IsIntegerish(v.Type()) {
					changed[v] = true
				}
			}
			return true
		})
	}
	ast.Inspect(loop, func(x ast.Node) bool {
		switch s := x.(type) {
		case *ast.IncDecStmt:
			note(s.X)
		case *ast.AssignStmt:
			if s.Tok != token.DEFINE {
				for _, l := range s.Lhs {
					note(l)
				}
			}
		}
		return true
	})
	capped := false
	var scan func(x ast.Node) bool
	scan = func(x ast.Node) bool {
		if inner, ok := x.(*ast.ForStmt); ok {
			// The condition of a nested loop bounds that loop, not this one.
			ast.Inspect(inner.Body, scan)
			return false
		}
		be, ok := x.(*ast.BinaryExpr)
		if !ok {
			return true
		}
		switch be.Op {
		case token.LSS, token.LEQ, token.GTR, token.GEQ:
		default:
			return true
		}
		if mentions(info, be, queue) {
			capped = true
			return false
		}
		for o := range changed {
			if mentions(info, be, o) {
				capped = true
				return false
			}
		}
		return true
	}
	ast.Inspect(loop.Body, scan)
	if !capped {
		sx.Report(pass, Rule, loop.Pos(),
			"work-list loop over %s appends to %s with no size cap; the number of nodes is chosen by the transaction submitter or a contract, so count the items visited and stop at a fixed limit", qtype, queue.Name())
	}
}

func mentions(info *types.Info, e ast.Node, obj types.Object) bool {
	found := false
	ast.Inspect(e, func(x ast.Node) bool {
		if id, ok := x.(*ast.Ident); ok && info.Uses[id] == obj {
			found = true
		}
		return !found
	})
	return found
}

func tarjan(nodes []*node) [][]*node {
	for _, n := range nodes {
		n.index = -1
	}
	var (
		idx   int
		stack []*node
		out   [][]*node
	)
	var strong func(v *node)
	strong = func(v *node) {
		v.index, v.low = idx, idx
		idx++
		stack = append(stack, v)
		v.onStack = true
		for _, e := range v.calls {
			w := e.to
			if w.index < 0 {
				strong(w)
				if w.low < v.low {
					v.low = w.low
				}
			} else if w.onStack && w.index < v.low {
				v.low = w.index
			}
		}
		if v.low == v.index {
			var scc []*node
			for {
				w := stack[len(stack)-1]
				stack = stack[:len(stack)-1]
				w.onStack = false
				scc = append(scc, w)
				if w == v {
					break
				}
			}
			out = append(out, scc)
		}
	}
	for _, n := range nodes {
		if n.index < 0 {
			strong(n)
		}
	}
	return out
}
