// Lead J1: java-stellar-sdk decodes XDR followed by extra bytes without an error.
import java.util.Base64;
import org.stellar.sdk.xdr.Memo;
import org.stellar.sdk.xdr.TransactionEnvelope;

public class JavaTrailing {
  static byte[] hex(String s) {
    byte[] b = new byte[s.length() / 2];
    for (int i = 0; i < b.length; i++) b[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
    return b;
  }

  public static void main(String[] a) throws Exception {
    String canonical = Base64.getEncoder().encodeToString(hex("00000000"));            // Memo MEMO_NONE
    String trailing = Base64.getEncoder().encodeToString(hex("00000000" + "deadbeef")); // + 4 extra bytes
    for (String s : new String[] {canonical, trailing}) {
      try {
        Memo m = Memo.fromXdrBase64(s);
        System.out.println("Memo " + s + ": ACCEPTED, re-encodes to " + m.toXdrBase64());
      } catch (Exception e) {
        System.out.println("Memo " + s + ": rejected: " + e);
      }
    }
    try {
      Memo m = Memo.fromXdrByteArray(hex("00000000" + "deadbeef"));
      System.out.println("fromXdrByteArray with 4 extra bytes: ACCEPTED, re-encodes to " + m.toXdrBase64());
    } catch (Exception e) {
      System.out.println("fromXdrByteArray: rejected: " + e);
    }
  }
}
