<!-- FILED 14 Nov 2026: https://github.com/lightsail-network/java-stellar-sdk/issues/833 -->

# XDR decoding accepts trailing bytes: `fromXdrBase64` / `fromXdrByteArray` do not check that the input is fully consumed

**Describe the bug**

`fromXdrByteArray`, and so `fromXdrBase64`, on the generated XDR classes decodes one value and returns. It never checks that the whole input was read. Any bytes after the value are ignored without an error.

`AbstractTransaction.fromEnvelopeXdr(String, Network)` goes through `TransactionEnvelope.fromXdrBase64`, so it accepts a transaction envelope followed by extra bytes and reports the same transaction hash as for the canonical envelope.

stellar-core rejects the same input, as do rs-stellar-xdr, js-stellar-sdk and go-stellar-sdk (for 3 or more trailing bytes; the 1 and 2 byte case in Go is stellar/go-stellar-sdk#6039).

**Version**

`network.lightsail:stellar-sdk:6.0.0`. `main` at 95bca0b5 has the same code in `fromXdrByteArray`.

**To reproduce**

```java
import org.stellar.sdk.AbstractTransaction;
import org.stellar.sdk.Network;

public class JavaEnvelope {
  public static void main(String[] a) {
    String canonical = "AAAAAgAAAAADoQe/884Qvh1w3RjnS8CZZ+TWMJulDV8d3IZkElUxuAAAAGQAAAAAAAAAAgAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAFhAAAAAAAAAQAAAAEAAAAAA6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbgAAAABAAAAAAOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4AAAAAAAAAAAAmJaAAAAAAAAAAAA=";
    String trailing = "AAAAAgAAAAADoQe/884Qvh1w3RjnS8CZZ+TWMJulDV8d3IZkElUxuAAAAGQAAAAAAAAAAgAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAFhAAAAAAAAAQAAAAEAAAAAA6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbgAAAABAAAAAAOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4AAAAAAAAAAAAmJaAAAAAAAAAAADerb7v"; // canonical + de ad be ef
    for (String s : new String[] {canonical, trailing}) {
      AbstractTransaction tx = AbstractTransaction.fromEnvelopeXdr(s, Network.TESTNET);
      System.out.println("ACCEPTED hash " + tx.hashHex()
          + " re-encodes to canonical: " + tx.toEnvelopeXdrBase64().equals(canonical));
    }
  }
}
```

Output on 6.0.0:

```
ACCEPTED hash 5429108abda98db8d3a6b2b73cc078a3898b74bb6f958aa0f14249a81287d0c0 re-encodes to canonical: true
ACCEPTED hash 5429108abda98db8d3a6b2b73cc078a3898b74bb6f958aa0f14249a81287d0c0 re-encodes to canonical: true
```

The smallest case is `Memo.fromXdrBase64("AAAAAN6tvu8=")` (`MEMO_NONE` followed by `deadbeef`), which decodes and re-encodes to `AAAAAA==`.

stellar-core 30.0.0 on the second envelope:

```
$ stellar-core print-xdr trailing.b64 --filetype tx --base64
Could not decode with type 'tx' : unmarshaling did not consume whole message
```

**Expected behavior**

Decoding fails with an `IOException` when bytes remain after the value, as it already does for non-zero padding and for a bool or optional flag that is not 0 or 1.

**Impact**

- Different base64 strings decode to the same value, so anything keyed on the XDR string (de-duplication, caches, allow-lists, logs) can hold several entries for one transaction.
- An application can accept and sign an envelope string that the network will not decode.
- Re-encoding drops the extra bytes silently, so the mismatch is not visible after a round trip.

**Scope**

Every generated XDR class. In a differential run over all 477 types in the Protocol 30 XDR, the SDK accepted 952 of 952 inputs with 1 to 8 trailing bytes. On the seven types `stellar-core print-xdr` can decode, stellar-core rejected 140 of 140.

**Cause and possible fix**

```java
public static Memo fromXdrByteArray(byte[] xdr) throws IOException {
  ByteArrayInputStream byteArrayInputStream = new ByteArrayInputStream(xdr);
  XdrDataInputStream xdrDataInputStream = new XdrDataInputStream(byteArrayInputStream);
  xdrDataInputStream.setMaxInputLen(xdr.length);
  return decode(xdrDataInputStream);
}
```

The stream already knows its length, so the generator template could check `xdrDataInputStream.getRemainingInputLen() != 0` after `decode` and throw. The streaming `decode(XdrDataInputStream)` entry point should stay as it is, since callers use it to read several values from one stream.

**Compatibility**

This is a behaviour change for callers that pass input with extra bytes today. Those inputs are not valid XDR for the type and are rejected by the network.

**How this was found**

A schema-driven differential test: values and faulty encodings generated from the Protocol 30 `.x` files, decoded by rs-stellar-xdr, js-stellar-sdk, py-stellar-base, go-stellar-sdk, java-stellar-sdk and stellar-core 30.0.0, and compared.
