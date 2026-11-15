// Package sc001signer builds and vets Soroban authorization entries before a
// transaction is submitted. It never reads ledger output, so reading the
// declared credentials here is not taking a claim as fact. Nothing here may be
// reported.
package sc001signer

import (
	"errors"

	"github.com/stellar/go-stellar-sdk/xdr"
)

func resign(e xdr.SorobanAuthorizationEntry, nonce xdr.Int64) xdr.SorobanAuthorizationEntry {
	c := xdr.SorobanAddressCredentials{Address: e.Credentials.Address.Address, Nonce: nonce}
	e.Credentials.Address = &c
	return e
}

func rejectForbidden(entries []xdr.SorobanAuthorizationEntry, forbidden string) error {
	for _, e := range entries {
		if e.Credentials.Address == nil {
			continue
		}
		if s, err := e.Credentials.Address.Address.String(); err == nil && s == forbidden {
			return errors.New("forbidden signer")
		}
	}
	return nil
}
