// Go runner: go-stellar-sdk/xdr. Reads "id\ttype\tb64", writes "id\tstatus\tpayload".
package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/stellar/go-stellar-sdk/xdr"
)

func clean(s string) string {
	s = strings.NewReplacer("\t", " ", "\n", " ").Replace(s)
	if len(s) > 300 {
		s = s[:300]
	}
	return s
}

func one(ty, b64 string) (status, payload string) {
	defer func() {
		if r := recover(); r != nil {
			status, payload = "panic", clean(fmt.Sprint(r))
		}
	}()
	mk, ok := registry[strings.ToLower(ty)]
	if !ok {
		return "notype", ""
	}
	v := mk()
	if err := xdr.SafeUnmarshalBase64(b64, v); err != nil {
		return "err", clean(err.Error())
	}
	out, err := xdr.MarshalBase64(v)
	if err != nil {
		return "encerr", clean(err.Error())
	}
	return "ok", out
}

func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1<<20), 64<<20)
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	for sc.Scan() {
		p := strings.SplitN(sc.Text(), "\t", 3)
		st, pl := one(p[1], p[2])
		fmt.Fprintf(w, "%s\t%s\t%s\n", p[0], st, pl)
		w.Flush()
	}
}
