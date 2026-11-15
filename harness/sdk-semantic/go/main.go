// Check "transactions_decode" for go-stellar-sdk. Same contract as tx_decode.mjs:
// TSV from tools/txcases.py on stdin, "entry, index, status, detail" on stdout.
package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/stellar/go-stellar-sdk/txnbuild"
)

func check(pass, b64, hash, ops, source string) (status, detail string) {
	defer func() {
		if r := recover(); r != nil {
			status, detail = "error", fmt.Sprintf("panic: %v", r)
		}
	}()
	g, err := txnbuild.TransactionFromXDR(b64)
	if err != nil {
		return "error", strings.SplitN(err.Error(), "\n", 2)[0]
	}
	var gotHash, gotSource string
	var gotOps int
	if tx, ok := g.Transaction(); ok {
		gotHash, err = tx.HashHex(pass)
		gotOps = len(tx.Operations())
		sa := tx.SourceAccount()
		gotSource = sa.AccountID
	} else if fb, ok := g.FeeBump(); ok {
		gotHash, err = fb.HashHex(pass)
		gotOps = len(fb.InnerTransaction().Operations())
		gotSource = fb.FeeAccount()
	}
	if err != nil {
		return "error", err.Error()
	}
	var wrong []string
	if gotHash != hash {
		wrong = append(wrong, "hash "+gotHash)
	}
	if fmt.Sprint(gotOps) != ops {
		wrong = append(wrong, fmt.Sprintf("operations %d (expected %s)", gotOps, ops))
	}
	if gotSource != source {
		wrong = append(wrong, fmt.Sprintf("source %s (expected %s)", gotSource, source))
	}
	if len(wrong) > 0 {
		return "mishandled", strings.Join(wrong, "; ")
	}
	return "pass", ""
}

func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 0, 1<<20), 64<<20)
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	for sc.Scan() {
		f := strings.Split(sc.Text(), "\t")
		if len(f) < 7 {
			continue
		}
		status, detail := check(f[2], f[3], f[4], f[5], f[6])
		if len(detail) > 200 {
			detail = detail[:200]
		}
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\n", f[0], f[1], status, detail)
	}
}
