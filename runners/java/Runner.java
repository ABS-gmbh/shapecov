// Java runner: network.lightsail:stellar-sdk. Reads "id\ttype\tb64", writes "id\tstatus\tpayload".
import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.jar.*;

public class Runner {
  static String clean(String s) {
    if (s == null) return "";
    s = s.replace('\t', ' ').replace('\n', ' ');
    return s.length() > 300 ? s.substring(0, 300) : s;
  }

  public static void main(String[] a) throws Exception {
    Map<String, Class<?>> byName = new HashMap<>();
    String jarPath = Class.forName("org.stellar.sdk.xdr.SCVal").getProtectionDomain().getCodeSource().getLocation().getPath();
    try (JarFile jar = new JarFile(jarPath)) {
      for (Enumeration<JarEntry> e = jar.entries(); e.hasMoreElements(); ) {
        String n = e.nextElement().getName();
        if (!n.startsWith("org/stellar/sdk/xdr/") || !n.endsWith(".class")) continue;
        String cn = n.substring(0, n.length() - 6).replace('/', '.');
        String simple = cn.substring(cn.lastIndexOf('.') + 1);
        if (simple.contains("$")) simple = simple.substring(simple.lastIndexOf('$') + 1);
        if (simple.isEmpty() || Character.isDigit(simple.charAt(0)) || simple.endsWith("Builder")) continue;
        try {
          Class<?> c = Class.forName(cn);
          c.getMethod("fromXdrBase64", String.class);
          byName.putIfAbsent(simple.toLowerCase(), c);
        } catch (Throwable t) { /* not a codec class */ }
      }
    }
    BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, "UTF-8");
    String line;
    while ((line = in.readLine()) != null) {
      String[] p = line.split("\t", 3);
      Class<?> c = byName.get(p[1].toLowerCase());
      if (c == null) { out.println(p[0] + "\tnotype\t"); continue; }
      try {
        Object v = c.getMethod("fromXdrBase64", String.class).invoke(null, p[2]);
        String enc = (String) c.getMethod("toXdrBase64").invoke(v);
        out.println(p[0] + "\tok\t" + enc);
      } catch (InvocationTargetException e) {
        Throwable t = e.getCause();
        String kind = (t instanceof Error) ? "panic" : "err";
        out.println(p[0] + "\t" + kind + "\t" + clean(t.getClass().getSimpleName() + ": " + t.getMessage()));
      } catch (Throwable t) {
        out.println(p[0] + "\tpanic\t" + clean(t.getClass().getSimpleName() + ": " + t.getMessage()));
      }
    }
  }
}
