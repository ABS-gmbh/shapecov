// Runs go-stellar-sdk's token transfer processor on one LedgerCloseMeta (base64 file) in both modes.
package main

import (
	"encoding/base64"
	"fmt"
	"os"
	"strings"

	"github.com/stellar/go-stellar-sdk/processors/token_transfer"
	"github.com/stellar/go-stellar-sdk/xdr"
)

func main() {
	pass := os.Args[2]
	b, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(string(b)))
	if err != nil {
		panic(err)
	}
	var lcm xdr.LedgerCloseMeta
	if err := lcm.UnmarshalBinary(raw); err != nil {
		panic(err)
	}
	fmt.Printf("ledger %d protocol %d\n", lcm.LedgerSequence(), lcm.ProtocolVersion())
	for _, mode := range []string{"NewEventsProcessorForUnifiedEvents", "NewEventsProcessor"} {
		p := token_transfer.NewEventsProcessor(pass)
		if mode == "NewEventsProcessorForUnifiedEvents" {
			p = token_transfer.NewEventsProcessorForUnifiedEvents(pass)
		}
		events, err := p.EventsFromLedger(lcm)
		fmt.Printf("%s: %d events, error: %v\n", mode, len(events), err)
		for _, e := range events {
			fmt.Printf("  %s %s\n", e.GetEventType(), e.String())
		}
	}
	fmt.Printf("VerifyEvents(unified=false): %v\n", token_transfer.VerifyEvents(lcm, pass, false))
}
