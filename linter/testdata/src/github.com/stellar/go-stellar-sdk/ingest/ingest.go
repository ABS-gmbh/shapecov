// Package ingest is a small stand-in for
// github.com/stellar/go-stellar-sdk/ingest, used only by the analyzer tests.
package ingest

import "github.com/stellar/go-stellar-sdk/xdr"

type Change struct {
	Type       xdr.LedgerEntryType
	Pre        *xdr.LedgerEntry
	Post       *xdr.LedgerEntry
	ChangeType xdr.LedgerEntryChangeType
}

type LedgerTransaction struct {
	Index      uint32
	Envelope   xdr.TransactionEnvelope
	Result     xdr.TransactionResultPair
	FeeChanges xdr.LedgerEntryChanges
	UnsafeMeta xdr.TransactionMeta
}

func (t *LedgerTransaction) Successful() bool                               { return t.Result.Successful() }
func (t *LedgerTransaction) GetChanges() ([]Change, error)                  { return nil, nil }
func (t *LedgerTransaction) GetOperationChanges(i uint32) ([]Change, error) { return nil, nil }
