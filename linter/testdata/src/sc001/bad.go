// Seeded violations for SC001. Every line marked "want" must be reported.
package sc001

import (
	"fmt"

	"github.com/stellar/go-stellar-sdk/xdr"
)

// --- Pattern 1: memo text used as text.

func memoMust(m xdr.Memo) string {
	return m.MustText() // want `memo text is read with MustText\(\)`
}

func memoGet(m xdr.Memo) string {
	if text, ok := m.GetText(); ok { // want `memo text is read with GetText\(\)`
		return text
	}
	return ""
}

func memoField(m xdr.Memo) string {
	if m.Text != nil {
		return *m.Text // want `memo text is read from Memo.Text`
	}
	return ""
}

func memoFromEnvelope(env xdr.TransactionEnvelope) string {
	return fmt.Sprintf("memo=%s", env.Memo().MustText()) // want `memo text is read with MustText\(\)`
}

// --- Pattern 2: strings and bytes a contract or submitter chose.

func tokenName(v xdr.ScVal) string {
	return string(v.MustStr()) // want `contract-supplied string \(xdr.ScString\) is converted to string`
}

func tokenNamePtr(v xdr.ScVal) string {
	name := string(*v.Str) // want `contract-supplied string`
	return "token " + name
}

func tokenNameChecksLengthOnly(v xdr.ScVal) string {
	name := string(v.MustStr()) // want `contract-supplied string`
	if len(name) > 32 {
		return ""
	}
	return name
}

func dataEntry(op xdr.ManageDataOp) string {
	return string(*op.DataValue) // want `ManageData value \(xdr.DataValue\)`
}

func functionName(args xdr.InvokeContractArgs) string {
	return string(args.FunctionName) // want `function name taken from the transaction envelope`
}

// --- Pattern 3: muxed accounts and 64-bit IDs.

func accountKey(op xdr.PaymentOp) string {
	return op.Destination.Address() // want `MuxedAccount.Address\(\) returns the M\.\.\. form`
}

func accountKeyErr(m *xdr.MuxedAccount) (string, error) {
	return m.GetAddress() // want `MuxedAccount.GetAddress\(\) returns the M\.\.\. form`
}

func sourceKey(env xdr.TransactionEnvelope) string {
	return env.SourceAccount().Address() // want `MuxedAccount.Address\(\)`
}

func muxedIDColumn(m xdr.MuxedAccount) int64 {
	med := m.MustMed25519()
	return int64(med.Id) // want `a muxed or memo ID is converted to int64 with no range check`
}

func memoIDColumn(m xdr.Memo) int64 {
	id, ok := m.GetId()
	if !ok {
		return 0
	}
	return int64(id) // want `a muxed or memo ID is converted to int64`
}

func memoIDJSON(m xdr.Memo) float64 {
	return float64(uint64(m.MustId())) // want `a muxed or memo ID is converted to float64`
}

func contractMuxedID(a xdr.ScAddress) xdr.Int64 {
	return xdr.Int64(a.MuxedAccount.Id) // want `a muxed or memo ID is converted to xdr.Int64`
}

// --- Pattern 4: the declared Soroban authorization entry read as fact.

func declaredSigners(entries []xdr.SorobanAuthorizationEntry) []string {
	var out []string
	for _, e := range entries {
		if e.Credentials.Type == xdr.SorobanCredentialsTypeSorobanCredentialsAddress {
			s, err := e.Credentials.MustAddress().Address.String() // want `address in a declared Soroban authorization entry is read as fact`
			if err == nil {
				out = append(out, s)
			}
		}
	}
	return out
}

func firstSigner(e xdr.SorobanAuthorizationEntry) xdr.ScAddress {
	return e.Credentials.Address.Address // want `address in a declared Soroban authorization entry`
}

// --- The ignore comment needs the right rule ID and a reason.

func wrongRule(m xdr.Memo) string {
	//shapecov:ignore SC002 this names another rule
	return m.MustText() // want `memo text is read with MustText\(\)`
}

func noReason(m xdr.Memo) string {
	//shapecov:ignore SC001
	return m.MustText() // want `memo text is read with MustText\(\)`
}
