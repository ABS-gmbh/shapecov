// The SDK behaviour checks of sdk-matrix/MATRIX.md for go-stellar-sdk; the same contracts as the
// JavaScript checks, one JSON line per run. go-stellar-sdk has no helper that builds an ScMap from
// native values or converts one to native values, so the two map rows do not apply to it.
//
//	behaviour pool <LiquidityPoolConstantProductParameters base64> <expected pool id hex>
//	behaviour ids <TransactionEnvelope base64> <spec.json>
//	behaviour string <Memo base64> <TransactionEnvelope base64 that carries it>
package main

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"strings"

	"github.com/stellar/go-stellar-sdk/amount"
	"github.com/stellar/go-stellar-sdk/network"
	"github.com/stellar/go-stellar-sdk/txnbuild"
	"github.com/stellar/go-stellar-sdk/xdr"
)

const g = "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ"

func emit(check, result, detail string) {
	b, _ := json.Marshal(map[string]string{"sdk": "go-stellar-sdk v0.9.0", "check": check, "result": result, "detail": detail})
	fmt.Println(string(b))
}

func asset(a xdr.Asset) txnbuild.Asset {
	var typ xdr.AssetType
	var code, issuer string
	if err := a.Extract(&typ, &code, &issuer); err != nil || typ == xdr.AssetTypeAssetTypeNative {
		return txnbuild.NativeAsset{}
	}
	return txnbuild.CreditAsset{Code: code, Issuer: issuer}
}

func main() {
	a := os.Args[1:]
	switch a[0] {
	case "pool":
		var p xdr.LiquidityPoolConstantProductParameters
		if err := xdr.SafeUnmarshalBase64(a[1], &p); err != nil {
			emit("pool_pair_accepted", "error", err.Error())
			return
		}
		id, err := txnbuild.NewLiquidityPoolId(asset(p.AssetA), asset(p.AssetB))
		switch {
		case err != nil:
			emit("pool_pair_accepted", "mishandled", "rejected an asset pair the network accepted: "+err.Error())
		case hex.EncodeToString(id[:]) != a[2]:
			emit("pool_pair_accepted", "mishandled", "pool ID "+hex.EncodeToString(id[:])+", the ledger records "+a[2])
		default:
			emit("pool_pair_accepted", "pass", "")
		}
	case "ids":
		var spec struct {
			IDs map[string]string `json:"ids"`
		}
		raw, _ := os.ReadFile(a[2])
		_ = json.Unmarshal(raw, &spec)
		var wrong, accepted []string
		gt, err := txnbuild.TransactionFromXDR(a[1])
		tx, ok := gt.Transaction()
		if err != nil || !ok {
			wrong = append(wrong, fmt.Sprintf("decode failed: %v", err))
		} else {
			ops := tx.Operations()
			pay := ops[1].(*txnbuild.Payment)
			src := tx.SourceAccount()
			srcID, _ := xdr.AddressToMuxedAccount(src.AccountID)
			dstID, _ := xdr.AddressToMuxedAccount(pay.Destination)
			stroops, _ := amount.ParseInt64(pay.Amount)
			got := map[string]string{
				"offer_id":             fmt.Sprint(ops[0].(*txnbuild.ManageSellOffer).OfferID),
				"source":               src.AccountID,
				"source_muxed_id":      fmt.Sprint(uint64(srcID.Med25519.Id)),
				"destination":          pay.Destination,
				"destination_muxed_id": fmt.Sprint(uint64(dstID.Med25519.Id)),
				"memo_id":              fmt.Sprint(uint64(tx.Memo().(txnbuild.MemoID))),
				"amount_stroops":       new(big.Int).SetInt64(stroops).String(),
			}
			for k, v := range got {
				if spec.IDs[k] != v {
					wrong = append(wrong, k+": decoded "+v+", expected "+spec.IDs[k])
				}
			}
		}
		// Typed fields: an offer ID is int64 and a muxed ID uint64, so the spec's text inputs and 2^64
		// cannot be passed; a negative offer ID can.
		op := txnbuild.ManageSellOffer{Selling: txnbuild.NativeAsset{}, Buying: txnbuild.CreditAsset{Code: "USD", Issuer: g},
			Amount: "1", Price: xdr.Price{N: 1, D: 1}, OfferID: -1}
		if op.Validate() == nil {
			accepted = append(accepted, "offer_id -1 (negative) accepted")
		}
		res := "pass"
		if len(wrong)+len(accepted) > 0 {
			res = "mishandled"
		}
		emit("ids_exact", res, strings.Join(append(wrong, accepted...), "; "))
	case "string":
		gt, err := txnbuild.TransactionFromXDR(a[2])
		tx, ok := gt.Transaction()
		if err != nil || !ok {
			emit("string_bytes_kept", "error", fmt.Sprintf("decode failed: %v", err))
			return
		}
		m, err := tx.Memo().ToXDR()
		got, _ := xdr.MarshalBase64(m)
		if err != nil || got != a[1] {
			emit("string_bytes_kept", "mishandled", fmt.Sprintf("memo rebuilt from txnbuild.MemoText: %s, the ledger has %s (%v)", got, a[1], err))
			return
		}
		emit("string_bytes_kept", "pass", "txnbuild.MemoText is a Go string, which holds the bytes as they are")
	default:
		emit(a[0], "not applicable", "go-stellar-sdk has no such helper")
	}
	_ = network.TestNetworkPassphrase
}
