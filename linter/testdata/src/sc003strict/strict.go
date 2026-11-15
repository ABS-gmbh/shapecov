// With -SC003.strict a success check no longer excuses envelope-derived
// participants; source accounts and meta-derived participants stay clean.
package sc003strict

import (
	"github.com/stellar/go-stellar-sdk/ingest"
	"github.com/stellar/go-stellar-sdk/xdr"
)

func guardedInFunction(tx ingest.LedgerTransaction) []xdr.AccountId {
	participants := []xdr.AccountId{tx.Envelope.SourceAccount().ToAccountId()}
	if !tx.Result.Successful() {
		return participants
	}
	for _, op := range tx.Envelope.Operations() {
		if p, ok := op.Body.GetPaymentOp(); ok {
			participants = append(participants, p.Destination.ToAccountId()) // want `strict mode`
		}
	}
	return participants
}

func fromMeta(tx *ingest.LedgerTransaction) []xdr.AccountId {
	var participants []xdr.AccountId
	changes, _ := tx.GetChanges()
	for _, c := range changes {
		if c.Post != nil && c.Post.Data.Type == xdr.LedgerEntryTypeAccount {
			participants = append(participants, c.Post.Data.MustAccount().AccountId)
		}
	}
	return participants
}
