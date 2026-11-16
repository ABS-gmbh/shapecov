// Correct code for SC003. Nothing in this file may be reported.
package sc003

import (
	"github.com/stellar/go-stellar-sdk/ingest"
	"github.com/stellar/go-stellar-sdk/xdr"
)

// Participants from the ledger entry changes in the meta.
func participantsFromChanges(tx *ingest.LedgerTransaction) ([]xdr.AccountId, error) {
	var participants []xdr.AccountId
	changes, err := tx.GetChanges()
	if err != nil {
		return nil, err
	}
	for _, c := range changes {
		if c.Post != nil && c.Post.Data.Type == xdr.LedgerEntryTypeAccount {
			participants = append(participants, c.Post.Data.MustAccount().AccountId)
		}
	}
	return participants, nil
}

// The transaction and fee-bump source accounts: stellar-core checks their
// signatures, so they are not unverified claims.
func transactionParticipants(tx ingest.LedgerTransaction) []string {
	participants := []string{tx.Envelope.SourceAccount().ToAccountId().Address()}
	if tx.Envelope.IsFeeBump() {
		participants = append(participants, tx.Envelope.FeeBumpAccount().ToAccountId().Address())
	}
	return participants
}

func operationSource(op xdr.Operation, participants map[string]bool) {
	if op.SourceAccount != nil {
		participants[op.SourceAccount.ToAccountId().Address()] = true
	}
}

// Operation bodies are read only after the success check.
func guardedInFunction(tx ingest.LedgerTransaction) []xdr.AccountId {
	participants := []xdr.AccountId{tx.Envelope.SourceAccount().ToAccountId()}
	if !tx.Result.Successful() {
		return participants
	}
	for _, op := range tx.Envelope.Operations() {
		if p, ok := op.Body.GetPaymentOp(); ok {
			participants = append(participants, p.Destination.ToAccountId())
		}
	}
	return participants
}

// The helper has no check of its own, but its only caller checks first.
func classicParticipants(op xdr.Operation) []xdr.AccountId {
	var participants []xdr.AccountId
	if p, ok := op.Body.GetPaymentOp(); ok {
		participants = append(participants, p.Destination.ToAccountId())
	}
	return participants
}

func guardedByCaller(tx *ingest.LedgerTransaction) [][]xdr.AccountId {
	if !tx.Successful() {
		return nil
	}
	var out [][]xdr.AccountId
	for _, op := range tx.Envelope.Operations() {
		out = append(out, classicParticipants(op))
	}
	return out
}

// Soroban authorisers from the nonce entries the host created.
func authorisers(changes []ingest.Change) []string {
	var participants []string
	for _, c := range changes {
		if c.Type != xdr.LedgerEntryTypeContractData || c.Pre != nil || c.Post == nil {
			continue
		}
		cd := c.Post.Data.MustContractData()
		if cd.Key.Type != xdr.ScValTypeScvLedgerKeyNonce {
			continue
		}
		if s, err := cd.Contract.String(); err == nil {
			participants = append(participants, s)
		}
	}
	return participants
}

// Envelope data that does not go into a participant collection.
func paymentCount(ops []xdr.Operation) int {
	n := 0
	for _, op := range ops {
		if _, ok := op.Body.GetPaymentOp(); ok {
			n++
		}
	}
	return n
}

func suppressed(op xdr.Operation) []xdr.AccountId {
	//shapecov:ignore SC003 this table records declared destinations on purpose
	participants := []xdr.AccountId{op.Body.MustCreateAccountOp().Destination}
	return participants
}

// The number of envelope operations is only a capacity hint here; the
// participants themselves come from the meta.
func participantsSized(tx ingest.LedgerTransaction, fromMeta []string) map[string]bool {
	ops := tx.Envelope.Operations()
	participants := make(map[string]bool, len(ops)+cap(fromMeta))
	for _, a := range fromMeta {
		participants[a] = true
	}
	return participants
}

// The wallet-backend shape: the producer returns early for a failed transaction (its first
// statement), and the caller stores its result under an integer operation ID, next to the
// operation wrapper it came from.
type opWrapper struct {
	Tx *ingest.LedgerTransaction
	Op xdr.Operation
}

func (w *opWrapper) ID() int64 { return 0 }

type opParticipantsRow struct {
	Wrapper      *opWrapper
	Participants []string
}

func guardedOpParticipants(w *opWrapper) []string {
	if !w.Tx.Successful() {
		return []string{w.Tx.Envelope.SourceAccount().ToAccountId().Address()}
	}
	var participants []string
	if p, ok := w.Op.Body.GetPaymentOp(); ok {
		participants = append(participants, p.Destination.ToAccountId().Address())
	}
	return participants
}

func allOpParticipants(tx *ingest.LedgerTransaction) map[int64]opParticipantsRow {
	operationsParticipants := map[int64]opParticipantsRow{}
	for _, op := range tx.Envelope.Operations() {
		w := &opWrapper{Tx: tx, Op: op}
		participants := guardedOpParticipants(w)
		operationsParticipants[w.ID()] = opParticipantsRow{Wrapper: w, Participants: participants}
	}
	return operationsParticipants
}
