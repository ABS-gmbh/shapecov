// J1 through the public API: AbstractTransaction.fromEnvelopeXdr accepts an envelope followed by
// extra bytes and reports the same transaction hash as for the canonical envelope.
import org.stellar.sdk.AbstractTransaction;
import org.stellar.sdk.Network;

public class JavaEnvelope {
  public static void main(String[] a) {
    String canonical = "AAAAAgAAAAADoQe/884Qvh1w3RjnS8CZZ+TWMJulDV8d3IZkElUxuAAAAGQAAAAAAAAAAgAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAFhAAAAAAAAAQAAAAEAAAAAA6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbgAAAABAAAAAAOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4AAAAAAAAAAAAmJaAAAAAAAAAAAA=";
    String trailing = "AAAAAgAAAAADoQe/884Qvh1w3RjnS8CZZ+TWMJulDV8d3IZkElUxuAAAAGQAAAAAAAAAAgAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAFhAAAAAAAAAQAAAAEAAAAAA6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbgAAAABAAAAAAOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4AAAAAAAAAAAAmJaAAAAAAAAAAADerb7v"; // canonical + de ad be ef
    for (String s : new String[] {canonical, trailing}) {
      try {
        AbstractTransaction tx = AbstractTransaction.fromEnvelopeXdr(s, Network.TESTNET);
        System.out.println("ACCEPTED hash " + tx.hashHex() + " re-encodes to canonical: " + tx.toEnvelopeXdrBase64().equals(canonical));
      } catch (Exception e) {
        System.out.println("rejected: " + e);
      }
    }
  }
}
