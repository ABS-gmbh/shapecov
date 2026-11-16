//! The SDK behaviour check of sdk-matrix/MATRIX.md that applies to rs-stellar-xdr above the codec:
//! "map_keys_host_order". Its helper is `ScMap::sorted_from`, which sorts entries by the derived
//! order of `ScVal`. The check reverses a map the host wrote and asks `sorted_from` to sort it back.
//!
//!   rust-behaviour mapkeys <SCVal map base64>
use stellar_xdr::{Limits, ReadXdr, ScMap, ScVal, WriteXdr};

fn emit(result: &str, detail: &str) {
    println!(
        "{{\"sdk\": \"rs-stellar-xdr 30.0.0\", \"check\": \"map_keys_host_order\", \"result\": \"{}\", \"detail\": {:?}}}",
        result, detail
    );
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) != Some("mapkeys") {
        println!("{{\"result\": \"not applicable\", \"detail\": \"rs-stellar-xdr has no such helper\"}}");
        return;
    }
    let host = match ScVal::from_xdr_base64(&args[2], Limits::none()) {
        Ok(ScVal::Map(Some(m))) => m,
        _ => return emit("error", "not a map"),
    };
    let mut entries: Vec<_> = host.0.iter().cloned().collect();
    entries.reverse();
    match ScMap::sorted_from(entries) {
        Ok(sorted) => {
            let again = ScVal::Map(Some(sorted)).to_xdr_base64(Limits::none()).unwrap_or_default();
            if again == args[2] {
                emit("pass", "ScMap::sorted_from gives the host's order")
            } else {
                emit("mishandled", "ScMap::sorted_from does not give the host's key order for a map the host wrote")
            }
        }
        Err(e) => emit("mishandled", &format!("ScMap::sorted_from refused a map the host wrote: {e}")),
    }
}
