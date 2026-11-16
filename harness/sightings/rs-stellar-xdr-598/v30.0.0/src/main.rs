// probe <type> fromjson  : stdin JSON -> base64 XDR, or the error
// probe <type> fromxdr   : stdin base64 XDR -> "ok" or the error (strict decode, depth 500)
use std::io::Read;
use stellar_xdr::{Limits, Type, TypeVariant, WriteXdr};
fn main() {
    let a: Vec<String> = std::env::args().collect();
    let v = TypeVariant::VARIANTS.iter().find(|t| t.name() == a[1]).expect("type");
    let mut s = String::new();
    std::io::stdin().read_to_string(&mut s).unwrap();
    let out = if a[2] == "fromjson" {
        match Type::from_json(*v, s.as_bytes()) {
            Ok(t) => format!("ok {}", t.to_xdr_base64(Limits::none()).unwrap()),
            Err(e) => format!("err {e:?}"),
        }
    } else {
        match Type::from_xdr_base64(*v, s.trim(), Limits { depth: 500, len: 1 << 26 }) {
            Ok(_) => "ok".to_string(),
            Err(e) => format!("err {e:?}"),
        }
    };
    println!("{}", out);
}
