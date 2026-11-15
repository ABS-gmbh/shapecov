// Correct code for SC001. Nothing in this file may be reported.
package sc001

import (
	"encoding/hex"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/stellar/go-stellar-sdk/ingest"
	"github.com/stellar/go-stellar-sdk/xdr"
)

func memoChecked(m xdr.Memo) (string, bool) {
	text, ok := m.GetText()
	if !ok || !utf8.ValidString(text) {
		return "", false
	}
	return text, true
}

func memoSanitized(m xdr.Memo) string {
	return strings.ToValidUTF8(m.MustText(), "?")
}

func memoFieldChecked(m xdr.Memo) string {
	if m.Text == nil || !utf8.ValidString(*m.Text) {
		return ""
	}
	return *m.Text
}

func memoAsHex(m xdr.Memo) string {
	return hex.EncodeToString([]byte(m.MustText()))
}

func memoOwnValidator(m xdr.Memo) string {
	return sanitizeText(m.MustText())
}

func sanitizeText(s string) string {
	return strings.ToValidUTF8(strings.ReplaceAll(s, "\x00", ""), "?")
}

func memoSet(text string) xdr.Memo {
	var m xdr.Memo
	m.Type = xdr.MemoTypeMemoText
	m.Text = &text
	return m
}

func tokenNameChecked(v xdr.ScVal) (string, error) {
	name := string(v.MustStr())
	if len(name) > 32 || !utf8.ValidString(name) {
		return "", errors.New("bad token name")
	}
	return name, nil
}

// A symbol read from ledger meta went through the host, which restricts it to
// [a-zA-Z0-9_]; only the envelope's FunctionName is reported.
func eventTopic(v xdr.ScVal) string {
	return string(v.MustSym())
}

func functionNameChecked(args xdr.InvokeContractArgs) (string, bool) {
	name := string(args.FunctionName)
	return name, utf8.ValidString(name)
}

func baseAccount(op xdr.PaymentOp) string {
	return op.Destination.ToAccountId().Address()
}

func displayAddress(m xdr.MuxedAccount) (address string, muxed bool) {
	if m.Type == xdr.CryptoKeyTypeKeyTypeMuxedEd25519 {
		return m.Address(), true
	}
	return m.Address(), false
}

func muxedIDText(m xdr.MuxedAccount) string {
	med, ok := m.GetMed25519()
	if !ok {
		return ""
	}
	return strconv.FormatUint(uint64(med.Id), 10)
}

func memoIDChecked(m xdr.Memo) (int64, bool) {
	id := m.MustId()
	if id > math.MaxInt64 {
		return 0, false
	}
	return int64(id), true
}

func memoIDUnsigned(m xdr.Memo) uint64 {
	return uint64(m.MustId())
}

// The declared address is only kept when the meta holds the nonce entry the
// host created for it.
func verifiedSigners(entries []xdr.SorobanAuthorizationEntry, changes []ingest.Change) []string {
	created := map[string]bool{}
	for _, c := range changes {
		if c.Type != xdr.LedgerEntryTypeContractData || c.Pre != nil || c.Post == nil {
			continue
		}
		cd := c.Post.Data.MustContractData()
		if cd.Key.Type != xdr.ScValTypeScvLedgerKeyNonce {
			continue
		}
		if s, err := cd.Contract.String(); err == nil {
			created[s] = true
		}
	}
	var out []string
	for _, e := range entries {
		if e.Credentials.Address == nil {
			continue
		}
		if s, err := e.Credentials.Address.Address.String(); err == nil && created[s] {
			out = append(out, s)
		}
	}
	return out
}

func buildCredentials(a xdr.ScAddress) xdr.SorobanAddressCredentials {
	var c xdr.SorobanAddressCredentials
	c.Address = a
	return c
}

func suppressed(m xdr.Memo) string {
	//shapecov:ignore SC001 the caller stores this column as bytea
	return m.MustText()
}

// Building an ScString for a transaction reads nothing from the ledger, whether
// from a constant or from the caller's own string.
func buildName(name string) []xdr.ScVal {
	fixed := xdr.ScString("SEP41 Token")
	given := xdr.ScString(name)
	return []xdr.ScVal{{Str: &fixed}, {Str: &given}}
}

// Formatting with %q or %x escapes every byte, so the output is safe text.
func describeTag(v xdr.ScVal, m xdr.Memo) (string, error) {
	s := fmt.Sprintf("tag=%q", string(v.MustStr()))
	return s, fmt.Errorf("memo %d bytes: %x", 28, m.MustText())
}

// A string handed straight to a parser that accepts only a fixed grammar.
func assetFromScVal(v xdr.ScVal) (xdr.Asset, error) {
	assets, err := xdr.BuildAssets(string(v.MustStr()))
	if err != nil || len(assets) == 0 {
		return xdr.Asset{}, errors.New("not an asset")
	}
	return assets[0], nil
}
