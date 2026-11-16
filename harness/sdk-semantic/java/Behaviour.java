// The SDK behaviour checks of sdk-matrix/MATRIX.md for java-stellar-sdk, the same contracts as
// order.mjs, map_entries.mjs, ids.mjs and the string check: one JSON line per run.
//
//   java -cp '<sdk jars>:.' Behaviour pool <LiquidityPoolConstantProductParameters base64> <expected pool id hex>
//   java ... Behaviour mapkeys <SCVal map base64>            the host's order after a round trip through Scv.toMap
//   java ... Behaviour mapentries <SCVal map base64> <n>     Scv.fromMap keeps every entry
//   java ... Behaviour ids <TransactionEnvelope base64> <spec.json>
//   java ... Behaviour string <Memo base64>                  rebuilding the memo from getText() keeps its bytes
import java.math.BigDecimal;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.stellar.sdk.*;
import org.stellar.sdk.operations.ManageSellOfferOperation;
import org.stellar.sdk.operations.Operation;
import org.stellar.sdk.operations.PaymentOperation;
import org.stellar.sdk.scval.Scv;
import org.stellar.sdk.xdr.LiquidityPoolConstantProductParameters;
import org.stellar.sdk.xdr.LiquidityPoolParameters;
import org.stellar.sdk.xdr.LiquidityPoolType;
import org.stellar.sdk.xdr.SCMapEntry;
import org.stellar.sdk.xdr.SCVal;

public class Behaviour {
  static final String G = "GA7QYNF7SOWQ3GLR2BGMZEHXAVIRZA4KVWLTJJFC7MGXUA74P7UJVSGZ";

  static String q(String s) {
    StringBuilder b = new StringBuilder("\"");
    for (char c : s.toCharArray()) {
      if (c == '"' || c == '\\') b.append('\\').append(c);
      else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
      else b.append(c);
    }
    return b.append('"').toString();
  }

  static void emit(String check, String result, String detail) {
    System.out.println("{\"sdk\": \"java-stellar-sdk 6.0.0\", \"check\": " + q(check) + ", \"result\": " + q(result)
        + ", \"detail\": " + q(detail) + "}");
  }

  static String hex(byte[] b) {
    StringBuilder s = new StringBuilder();
    for (byte x : b) s.append(String.format("%02x", x));
    return s.toString();
  }

  /** A memo's XDR as a user gets it: from a transaction built with it (Memo.toXdr is not public). */
  static String memoXdr(Memo memo) throws Exception {
    Transaction tx = new TransactionBuilder(new Account(G, 1L), Network.TESTNET).addMemo(memo)
        .addOperation(org.stellar.sdk.operations.BumpSequenceOperation.builder().bumpTo(2L).build())
        .setBaseFee(100).setTimeout(0).build();
    return tx.toEnvelopeXdr().getV1().getTx().getMemo().toXdrBase64();
  }

  public static void main(String[] a) throws Exception {
    switch (a[0]) {
      case "pool": {
        LiquidityPoolConstantProductParameters p = LiquidityPoolConstantProductParameters.fromXdrBase64(a[1]);
        try {
          LiquidityPool lp = new LiquidityPool(Asset.fromXdr(p.getAssetA()), Asset.fromXdr(p.getAssetB()));
          String id = lp.getLiquidityPoolId();
          emit("pool_pair_accepted", id.equals(a[2]) ? "pass" : "mishandled",
              id.equals(a[2]) ? "" : "pool ID " + id + ", the ledger records " + a[2]);
        } catch (Exception e) {
          emit("pool_pair_accepted", "mishandled", "rejected an asset pair the network accepted: " + e);
        }
        break;
      }
      case "mapkeys": {
        SCVal map = SCVal.fromXdrBase64(a[1]);
        List<SCMapEntry> entries = new ArrayList<>(List.of(map.getMap().getSCMap()));
        Collections.reverse(entries);
        LinkedHashMap<SCVal, SCVal> reversed = new LinkedHashMap<>();
        for (SCMapEntry e : entries) reversed.put(e.getKey(), e.getVal());
        try {
          // The Map overload is the one that does not promise to keep insertion order.
          SCVal sorted = Scv.toMap((Map<SCVal, SCVal>) reversed);
          boolean ok = sorted.toXdrBase64().equals(a[1]);
          emit("map_keys_host_order", ok ? "pass" : "mishandled",
              ok ? "" : "Scv.toMap(Map) does not give the host's key order for a map the host wrote");
        } catch (Exception e) {
          emit("map_keys_host_order", "mishandled", "Scv.toMap refused a map the host wrote: " + e);
        }
        break;
      }
      case "mapentries": {
        SCVal map = SCVal.fromXdrBase64(a[1]);
        int want = Integer.parseInt(a[2]);
        try {
          int got = Scv.fromMap(map).size();
          emit("map_entries_preserved", got == want ? "pass" : "mishandled",
              got == want ? "" : (want - got) + " entry(ies) dropped without an error by Scv.fromMap");
        } catch (Exception e) {
          emit("map_entries_preserved", "pass", "Scv.fromMap refused with an error instead of dropping entries: " + e);
        }
        break;
      }
      case "ids": {
        List<String> wrong = new ArrayList<>(), accepted = new ArrayList<>();
        String spec = Files.readString(Path.of(a[2]));
        try {
          Transaction tx = (Transaction) AbstractTransaction.fromEnvelopeXdr(a[1], Network.TESTNET);
          Operation[] ops = tx.getOperations();
          Map<String, String> got = new LinkedHashMap<>();
          got.put("offer_id", Long.toString(((ManageSellOfferOperation) ops[0]).getOfferId()));
          got.put("source", tx.getSourceAccount());
          got.put("source_muxed_id", String.valueOf(new MuxedAccount(tx.getSourceAccount()).getMuxedId()));
          PaymentOperation pay = (PaymentOperation) ops[1];
          got.put("destination", pay.getDestination());
          got.put("destination_muxed_id", String.valueOf(new MuxedAccount(pay.getDestination()).getMuxedId()));
          got.put("memo_id", ((MemoId) tx.getMemo()).getId().toString());
          got.put("amount_stroops", pay.getAmount().movePointRight(7).toBigIntegerExact().toString());
          for (Map.Entry<String, String> e : got.entrySet()) {
            String want = spec.replaceAll("(?s).*\"" + e.getKey() + "\": \"([^\"]*)\".*", "$1");
            if (!want.equals(e.getValue())) wrong.add(e.getKey() + ": decoded " + e.getValue() + ", expected " + want);
          }
        } catch (Exception e) {
          wrong.add("decode failed: " + e);
        }
        // The builders take long and BigInteger, so the spec's text inputs ("0x10", " 16 ", "") are not
        // SDK inputs; the values a typed caller can pass are a negative offer ID and a muxed ID of 2^64.
        try {
          Operation op = ManageSellOfferOperation.builder().selling(new AssetTypeNative())
              .buying(Asset.createNonNativeAsset("USD", G)).amount(BigDecimal.ONE).price(Price.fromString("1"))
              .offerId(-1L).build();
          long enc = ((ManageSellOfferOperation) Operation.fromXdr(op.toXdr())).getOfferId();
          accepted.add("offer_id -1 (negative) accepted, encodes " + enc);
        } catch (Exception e) {
          // rejected, as required
        }
        try {
          BigInteger two64 = BigInteger.ONE.shiftLeft(64);
          MuxedAccount m = new MuxedAccount(G, two64);
          BigInteger enc = MuxedAccount.fromXdr(m.toXdr()).getMuxedId();
          accepted.add("muxed_id 18446744073709551616 (2^64, out of range) accepted, encodes " + enc);
        } catch (Exception e) {
          // rejected, as required
        }
        String detail = String.join("; ", wrong) + (wrong.isEmpty() || accepted.isEmpty() ? "" : "; ")
            + String.join("; ", accepted);
        emit("ids_exact", wrong.isEmpty() && accepted.isEmpty() ? "pass" : "mishandled", detail);
        break;
      }
      case "string": {
        org.stellar.sdk.xdr.Memo x = org.stellar.sdk.xdr.Memo.fromXdrBase64(a[1]);
        MemoText m = (MemoText) Memo.fromXdr(x);
        String viaText = memoXdr(new MemoText(m.getText()));
        String viaBytes = memoXdr(new MemoText(m.getBytes()));
        boolean ok = viaText.equals(a[1]);
        emit("string_bytes_kept", ok ? "pass" : "mishandled", ok ? ""
            : "rebuilt from getText(): " + hex(java.util.Base64.getDecoder().decode(viaText)) + ", the ledger has "
                + hex(java.util.Base64.getDecoder().decode(a[1])) + "; rebuilt from getBytes() "
                + (viaBytes.equals(a[1]) ? "keeps the bytes" : "changes them too"));
        break;
      }
      default:
        emit(a[0], "error", "unknown check");
    }
  }
}
