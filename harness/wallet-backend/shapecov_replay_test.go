// Replay adapter for stellar/wallet-backend. replay.sh copies this file into
// internal/indexer/ of a wallet-backend checkout and runs it with `go test`.
//
// It feeds one corpus entry (a base64 LedgerCloseMeta) to the indexer's own
// ProcessLedger, then checks what the indexer produced against expectations
// that come from the corpus manifest, not from the indexer:
//
//   mishandled  the indexer returned an error, or produced a row that its own
//               database encoding (driver.Valuer) rejects
//   dropped     no error, but an expected row is missing
//   pass        every expected row is present and every row encodes
//
// The check walks struct fields by reflection, so the same file compiles
// against wallet-backend commits before and after a field changes its type.
package indexer

import (
	"context"
	"database/sql/driver"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"github.com/alitto/pond/v2"
	"github.com/stellar/go-stellar-sdk/xdr"
)

type shapecovExpect struct {
	EntryID           string   `json:"entry_id"`
	NetworkPassphrase string   `json:"network_passphrase"`
	SignerKeys        []string `json:"signer_keys"` // each must appear in a SIGNER state change
}

type shapecovResult struct {
	EntryID      string   `json:"entry_id"`
	Ledger       uint32   `json:"ledger"`
	Result       string   `json:"result"`
	StateChanges int      `json:"state_changes"`
	Mishandled   []string `json:"mishandled,omitempty"`
	Dropped      []string `json:"dropped,omitempty"`
}

var shapecovValuer = reflect.TypeOf((*driver.Valuer)(nil)).Elem()

func TestShapecovReplay(t *testing.T) {
	entryPath, expectPath := os.Getenv("SHAPECOV_ENTRY"), os.Getenv("SHAPECOV_EXPECT")
	if entryPath == "" || expectPath == "" {
		t.Skip("SHAPECOV_ENTRY and SHAPECOV_EXPECT not set")
	}
	var exp shapecovExpect
	raw, err := os.ReadFile(expectPath)
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(raw, &exp); err != nil {
		t.Fatal(err)
	}
	b64, err := os.ReadFile(entryPath)
	if err != nil {
		t.Fatal(err)
	}
	bin, err := base64.StdEncoding.DecodeString(strings.TrimSpace(string(b64)))
	if err != nil {
		t.Fatal(err)
	}
	var lcm xdr.LedgerCloseMeta
	if err = xdr.SafeUnmarshal(bin, &lcm); err != nil {
		t.Fatalf("entry does not decode with this checkout's SDK: %v", err)
	}

	res := shapecovResult{EntryID: exp.EntryID, Ledger: lcm.LedgerSequence()}
	idx, err := NewIndexer(exp.NetworkPassphrase, pond.NewPool(runtime.NumCPU()), nil)
	if err != nil {
		t.Fatal(err)
	}
	buffer := NewIndexerBuffer()
	if _, err = ProcessLedger(context.Background(), exp.NetworkPassphrase, lcm, idx, buffer); err != nil {
		res.Mishandled = append(res.Mishandled, "ProcessLedger: "+err.Error())
	}

	seenSigners := map[string]bool{}
	changes := buffer.GetStateChanges()
	res.StateChanges = len(changes)
	for i := range changes {
		v := reflect.ValueOf(&changes[i]).Elem()
		for f := 0; f < v.NumField(); f++ {
			field, name := v.Field(f), v.Type().Field(f).Name
			if name == "SignerAccountID" {
				if s, ok := field.Interface().(fmt.Stringer); ok && s.String() != "" {
					seenSigners[s.String()] = true
				}
			}
			if !field.Type().Implements(shapecovValuer) {
				continue
			}
			if field.Kind() == reflect.Pointer && field.IsNil() {
				continue
			}
			if _, verr := field.Interface().(driver.Valuer).Value(); verr != nil {
				res.Mishandled = append(res.Mishandled,
					fmt.Sprintf("state change %d (%v/%v) column %s does not encode: %v",
						i, v.FieldByName("StateChangeCategory").Interface(),
						v.FieldByName("StateChangeReason").Interface(), name, verr))
			}
		}
	}
	for _, k := range exp.SignerKeys {
		if !seenSigners[k] {
			res.Dropped = append(res.Dropped, "no SIGNER state change for signer key "+k)
		}
	}

	switch {
	case len(res.Mishandled) > 0:
		res.Result = "mishandled"
	case len(res.Dropped) > 0:
		res.Result = "dropped"
	default:
		res.Result = "pass"
	}
	out, _ := json.Marshal(res)
	fmt.Println("SHAPECOV_RESULT " + string(out))
}
