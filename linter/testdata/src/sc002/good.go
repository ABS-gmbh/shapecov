// Correct code for SC002. Nothing in this file may be reported.
package sc002

import (
	"errors"

	"github.com/stellar/go-stellar-sdk/xdr"
)

const (
	maxDepth = 64
	maxNodes = 4096
)

var errTooDeep = errors.New("nested too deeply")

// A depth parameter that is tested and grows with each call.
func countValsBounded(v xdr.ScVal, depth int) (int, error) {
	if depth > maxDepth {
		return 0, errTooDeep
	}
	n := 1
	if vec, ok := v.GetVec(); ok && vec != nil {
		for _, e := range *vec {
			c, err := countValsBounded(e, depth+1)
			if err != nil {
				return 0, err
			}
			n += c
		}
	}
	return n, nil
}

// A remaining-levels parameter that counts down.
func walkRemaining(inv xdr.SorobanAuthorizedInvocation, remaining int) bool {
	if remaining == 0 {
		return false
	}
	for _, sub := range inv.SubInvocations {
		if !walkRemaining(sub, remaining-1) {
			return false
		}
	}
	return true
}

// A counter kept in a struct field.
type walker struct {
	depth, max int
	seen       int
}

func (w *walker) visit(v xdr.ScVal) error {
	w.depth++
	defer func() { w.depth-- }()
	if w.depth > w.max {
		return errTooDeep
	}
	w.seen++
	if vec, ok := v.GetVec(); ok && vec != nil {
		for _, e := range *vec {
			if err := w.visit(e); err != nil {
				return err
			}
		}
	}
	return nil
}

// A node budget shared through a pointer.
func spend(v xdr.ScVal, budget *int) error {
	*budget--
	if *budget < 0 {
		return errTooDeep
	}
	if vec, ok := v.GetVec(); ok && vec != nil {
		for _, e := range *vec {
			if err := spend(e, budget); err != nil {
				return err
			}
		}
	}
	return nil
}

// A closure with a depth parameter.
func countInvocationsBounded(entries []xdr.SorobanAuthorizationEntry) (int, error) {
	n := 0
	var visit func(inv xdr.SorobanAuthorizedInvocation, depth int) error
	visit = func(inv xdr.SorobanAuthorizedInvocation, depth int) error {
		if depth >= maxDepth {
			return errTooDeep
		}
		n++
		for _, sub := range inv.SubInvocations {
			if err := visit(sub, depth+1); err != nil {
				return err
			}
		}
		return nil
	}
	for _, e := range entries {
		if err := visit(e.RootInvocation, 0); err != nil {
			return 0, err
		}
	}
	return n, nil
}

// Mutual recursion where one function of the cycle enforces the cap.
func flattenValBounded(v xdr.ScVal, out *[]xdr.ScVal, depth int) {
	if depth > maxDepth {
		return
	}
	*out = append(*out, v)
	if vec, ok := v.GetVec(); ok && vec != nil {
		flattenVecBounded(*vec, out, depth+1)
	}
}

func flattenVecBounded(vec xdr.ScVec, out *[]xdr.ScVal, depth int) {
	for _, e := range vec {
		flattenValBounded(e, out, depth)
	}
}

// Recursion over something that is not an XDR structure.
type tree struct{ kids []*tree }

func size(t *tree) int {
	n := 1
	for _, k := range t.kids {
		n += size(k)
	}
	return n
}

// One level only: no recursion.
func topLevelStrings(v xdr.ScVal) []string {
	var out []string
	if vec, ok := v.GetVec(); ok && vec != nil {
		for _, e := range *vec {
			if s, ok := e.GetStr(); ok {
				out = append(out, string(s))
			}
		}
	}
	return out
}

// A work list with a visit counter.
func allInvocationsBounded(root xdr.SorobanAuthorizedInvocation) (int, error) {
	stack := []xdr.SorobanAuthorizedInvocation{root}
	n := 0
	for len(stack) > 0 {
		inv := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		n++
		if n > maxNodes {
			return 0, errTooDeep
		}
		stack = append(stack, inv.SubInvocations...)
	}
	return n, nil
}

// A work list capped by its own length.
func allValsBounded(root xdr.ScVal) ([]xdr.ScVal, error) {
	queue := []xdr.ScVal{root}
	for i := 0; i < len(queue); i++ {
		if len(queue) > maxNodes {
			return nil, errTooDeep
		}
		if vec, ok := queue[i].GetVec(); ok && vec != nil {
			queue = append(queue, *vec...)
		}
	}
	return queue, nil
}

func suppressed(v xdr.ScVal) int { //shapecov:ignore SC002 input is a value this service built itself
	n := 1
	if vec, ok := v.GetVec(); ok && vec != nil {
		for _, e := range *vec {
			n += suppressed(e)
		}
	}
	return n
}
