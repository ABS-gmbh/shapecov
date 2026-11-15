// Seeded violations for SC002. Every line marked "want" must be reported.
package sc002

import "github.com/stellar/go-stellar-sdk/xdr"

// --- Pattern 1: direct recursion over nested ScVals.

func countVals(v xdr.ScVal) int { // want `recursive function countVals walks xdr.ScVal with no depth cap`
	n := 1
	if vec, ok := v.GetVec(); ok && vec != nil {
		for _, e := range *vec {
			n += countVals(e)
		}
	}
	if m, ok := v.GetMap(); ok && m != nil {
		for _, e := range *m {
			n += countVals(e.Key) + countVals(e.Val)
		}
	}
	return n
}

// --- Pattern 2: a method that recurses over the authorization tree.

type collector struct{ contracts []string }

func (c *collector) walk(inv xdr.SorobanAuthorizedInvocation) { // want `recursive function walk walks xdr.SorobanAuthorizedInvocation with no depth cap`
	if fn, ok := inv.Function.GetContractFn(); ok {
		if id, err := fn.ContractAddress.String(); err == nil {
			c.contracts = append(c.contracts, id)
		}
	}
	for _, sub := range inv.SubInvocations {
		c.walk(sub)
	}
}

// --- Pattern 3: a closure bound to a variable.

func countInvocations(entries []xdr.SorobanAuthorizationEntry) int {
	n := 0
	var visit func(inv xdr.SorobanAuthorizedInvocation)
	visit = func(inv xdr.SorobanAuthorizedInvocation) { // want `recursive closure visit walks xdr.SorobanAuthorizedInvocation with no depth cap`
		n++
		for _, sub := range inv.SubInvocations {
			visit(sub)
		}
	}
	for _, e := range entries {
		visit(e.RootInvocation)
	}
	return n
}

// --- Pattern 4: mutual recursion.

func flattenVal(v xdr.ScVal, out *[]xdr.ScVal) { // want `recursive function flattenVal walks xdr.ScVal`
	*out = append(*out, v)
	if vec, ok := v.GetVec(); ok && vec != nil {
		flattenVec(*vec, out)
	}
}

func flattenVec(vec xdr.ScVec, out *[]xdr.ScVal) { // want `recursive function flattenVec walks xdr.ScVec`
	for _, e := range vec {
		flattenVal(e, out)
	}
}

// --- Pattern 5: something that looks like a cap but is not one.

// The depth is passed on but never tested.
func depthNeverTested(v xdr.ScVal, depth int) { // want `recursive function depthNeverTested`
	if vec, ok := v.GetVec(); ok && vec != nil {
		for _, e := range *vec {
			depthNeverTested(e, depth+1)
		}
	}
}

// The depth is tested but never changes.
func depthNeverChanges(v xdr.ScVal, depth int) { // want `recursive function depthNeverChanges`
	if depth > 10 {
		return
	}
	if vec, ok := v.GetVec(); ok && vec != nil {
		for _, e := range *vec {
			depthNeverChanges(e, depth)
		}
	}
}

// A loop index is compared and incremented, but it is local to one call.
func loopIndexOnly(v xdr.ScVal) int { // want `recursive function loopIndexOnly`
	n := 0
	if vec, ok := v.GetVec(); ok && vec != nil {
		for i := 0; i < len(*vec); i++ {
			n += loopIndexOnly((*vec)[i])
		}
	}
	return n
}

// --- Pattern 6: contract spec types nest too.

func specDepth(t xdr.ScSpecTypeDef) int { // want `recursive function specDepth walks xdr.ScSpecTypeDef`
	if t.Option != nil {
		return 1 + specDepth(t.Option.ValueType)
	}
	if t.Vec != nil {
		return 1 + specDepth(t.Vec.ElementType)
	}
	return 0
}

// --- Pattern 7: an explicit work list with no size cap.

func allInvocations(root xdr.SorobanAuthorizedInvocation) int {
	stack := []xdr.SorobanAuthorizedInvocation{root}
	n := 0
	for len(stack) > 0 { // want `work-list loop over xdr.SorobanAuthorizedInvocation appends to stack with no size cap`
		inv := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		n++
		stack = append(stack, inv.SubInvocations...)
	}
	return n
}

func allVals(root xdr.ScVal) []xdr.ScVal {
	queue := []xdr.ScVal{root}
	for i := 0; i < len(queue); i++ { // want `work-list loop over xdr.ScVal appends to queue with no size cap`
		if vec, ok := queue[i].GetVec(); ok && vec != nil {
			for j := 0; j < len(*vec); j++ {
				queue = append(queue, (*vec)[j])
			}
		}
	}
	return queue
}
