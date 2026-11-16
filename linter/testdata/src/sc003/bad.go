// Seeded violations for SC003. Every line marked "want" must be reported.
package sc003

import (
	"github.com/stellar/go-stellar-sdk/ingest"
	"github.com/stellar/go-stellar-sdk/xdr"

	"sc003helper"
)

// --- Pattern 1: operation bodies appended to a participant slice, with no
// check that the transaction succeeded.

func operationParticipants(tx ingest.LedgerTransaction) []xdr.AccountId {
	var participants []xdr.AccountId
	for _, op := range tx.Envelope.Operations() {
		switch op.Body.Type {
		case xdr.OperationTypePayment:
			participants = append(participants, op.Body.MustPaymentOp().Destination.ToAccountId()) // want `participants is filled from the transaction envelope with no check that the transaction succeeded`
		case xdr.OperationTypeCreateAccount:
			dest := op.Body.MustCreateAccountOp().Destination
			participants = append(participants, dest) // want `participants is filled from the transaction envelope`
		}
	}
	return participants
}

// --- Pattern 2: a set with an Add method.

type addrSet map[string]struct{}

func (s addrSet) Add(a string) { s[a] = struct{}{} }

func affectedAccounts(ops []xdr.Operation) addrSet {
	affected := addrSet{}
	for _, op := range ops {
		if p, ok := op.Body.GetPaymentOp(); ok {
			affected.Add(p.Destination.ToAccountId().Address()) // want `affected is filled from the transaction envelope`
		}
	}
	return affected
}

// --- Pattern 3: a map keyed by address, and a struct field.

func markInvolved(op xdr.Operation, involvedAccounts map[string]bool) {
	involvedAccounts[op.Body.MustCreateAccountOp().Destination.Address()] = true // want `involvedAccounts is filled from the transaction envelope`
}

type opRow struct{ Participants []string }

func fillRow(r *opRow, op xdr.Operation) {
	r.Participants = append(r.Participants, op.Body.MustCreateAccountOp().Destination.Address()) // want `Participants is filled from the transaction envelope`
}

// --- Pattern 4: the declared authorization tree. A success check does not
// help: the host verifies only the entries a require_auth call matched.

func sorobanParticipants(tx ingest.LedgerTransaction, op xdr.InvokeHostFunctionOp) []string {
	var participants []string
	if !tx.Result.Successful() {
		return participants
	}
	for _, entry := range op.Auth {
		if entry.Credentials.Type == xdr.SorobanCredentialsTypeSorobanCredentialsAddress {
			addr, err := entry.Credentials.MustAddress().Address.String()
			if err != nil {
				continue
			}
			participants = append(participants, addr) // want `participants is filled from the declared Soroban authorization tree`
		}
	}
	return participants
}

// --- Pattern 5: a function that returns participants gathered from the tree.

func participantsFromInvocation(inv xdr.SorobanAuthorizedInvocation, depth int) []string {
	var out []string
	if depth > 8 {
		return out
	}
	if fn, ok := inv.Function.GetContractFn(); ok {
		if id, err := fn.ContractAddress.String(); err == nil {
			out = append(out, id)
		}
	}
	for _, sub := range inv.SubInvocations {
		out = append(out, participantsFromInvocation(sub, depth+1)...)
	}
	return out // want `the result of participantsFromInvocation is filled from the declared Soroban authorization tree`
}

// --- Pattern 6: a helper with one caller that checks success and one that
// does not.

func opParticipants(op xdr.Operation) []xdr.AccountId {
	participants := []xdr.AccountId{op.Body.MustCreateAccountOp().Destination} // want `participants is filled from the transaction envelope`
	return participants
}

func checkedCaller(tx *ingest.LedgerTransaction) int {
	if !tx.Successful() {
		return 0
	}
	n := 0
	for _, op := range tx.Envelope.Operations() {
		n += len(opParticipants(op))
	}
	return n
}

func uncheckedCaller(tx *ingest.LedgerTransaction) int {
	n := 0
	for _, op := range tx.Envelope.Operations() {
		n += len(opParticipants(op))
	}
	return n
}

// --- Pattern 7: the success check comes after the envelope was already used.

func checkedTooLate(tx ingest.LedgerTransaction) []xdr.AccountId {
	var participants []xdr.AccountId
	for _, op := range tx.Envelope.Operations() {
		if p, ok := op.Body.GetPaymentOp(); ok {
			participants = append(participants, p.Destination.ToAccountId()) // want `participants is filled from the transaction envelope`
		}
	}
	if !tx.Result.Successful() {
		return nil
	}
	return participants
}

// --- Pattern 8: a return that comes before the fill in the source but inside
// the loop that fills, so a later iteration returns tree data.

func participantsInLoop(invs []xdr.SorobanAuthorizedInvocation) []string {
	var out []string
	for _, inv := range invs {
		if len(out) > 4 {
			return out // want `the result of participantsInLoop is filled from the declared Soroban authorization tree`
		}
		if fn, ok := inv.Function.GetContractFn(); ok {
			if id, err := fn.ContractAddress.String(); err == nil {
				out = append(out, id)
			}
		}
	}
	return out // want `the result of participantsInLoop is filled from the declared Soroban authorization tree`
}

// --- A success check in the called function: trusted only when it is the callee's first
// statement, in this package, and returns early.

// No check at all: reported in the producer and where its result is stored.
func unguardedOpParticipants(w *opWrapper) []string {
	var participants []string
	if p, ok := w.Op.Body.GetPaymentOp(); ok {
		participants = append(participants, p.Destination.ToAccountId().Address()) // want `participants is filled from the transaction envelope`
	}
	return participants
}

func storesUnguarded(tx *ingest.LedgerTransaction) {
	for _, op := range tx.Envelope.Operations() {
		w := &opWrapper{Tx: tx, Op: op}
		participants := unguardedOpParticipants(w) // want `participants is filled from the transaction envelope`
		_ = participants
	}
}

// The envelope is read before the check.
func lateCheckOpParticipants(w *opWrapper) []string {
	dest := w.Op.Body.MustPaymentOp().Destination.ToAccountId().Address()
	if !w.Tx.Successful() {
		return []string{dest}
	}
	return []string{dest}
}

func storesLateCheck(tx *ingest.LedgerTransaction) {
	for _, op := range tx.Envelope.Operations() {
		w := &opWrapper{Tx: tx, Op: op}
		participants := lateCheckOpParticipants(w) // want `participants is filled from the transaction envelope`
		_ = participants
	}
}

// The producer checks first, but it is in another package.
func storesOtherPackage(tx *ingest.LedgerTransaction) {
	for _, op := range tx.Envelope.Operations() {
		participants := sc003helper.GuardedOpParticipants(tx, op) // want `participants is filled from the transaction envelope`
		_ = participants
	}
}

// A keyed literal whose participants field is filled from the envelope.
func literalFromEnvelope(tx ingest.LedgerTransaction) map[int64]opParticipantsRow {
	operationsParticipants := map[int64]opParticipantsRow{}
	for i, op := range tx.Envelope.Operations() {
		operationsParticipants[int64(i)] = opParticipantsRow{Participants: []string{op.Body.MustPaymentOp().Destination.ToAccountId().Address()}} // want `operationsParticipants is filled from the transaction envelope`
	}
	return operationsParticipants
}
