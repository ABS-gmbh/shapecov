// Package integrationtests is test support: SC001 skips it unless -tests is
// given, as it skips _test.go files. Nothing here may be reported.
package integrationtests

import "github.com/stellar/go-stellar-sdk/xdr"

func memoForAssertion(m xdr.Memo) string {
	return m.MustText()
}

func muxedForFixture(m xdr.MuxedAccount) string {
	return m.Address()
}
