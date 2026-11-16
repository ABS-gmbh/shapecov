// Package sc003helper is a producer of participants in another package. SC003 does not follow a
// success check across packages, so its callers are reported (bad.go).
package sc003helper

import (
	"github.com/stellar/go-stellar-sdk/ingest"
	"github.com/stellar/go-stellar-sdk/xdr"
)

func GuardedOpParticipants(tx *ingest.LedgerTransaction, op xdr.Operation) []string {
	if !tx.Successful() {
		return nil
	}
	if p, ok := op.Body.GetPaymentOp(); ok {
		return []string{p.Destination.ToAccountId().Address()}
	}
	return nil
}
