// Reference JSON runner: rs-stellar-xdr with the serde_json feature.
// Reads "id\ttype\tpayload" lines, writes "id\tstatus\tpayload".
//   ref-json tojson    payload = base64 XDR   -> ok payload = SEP-51 JSON (one line)
//   ref-json fromjson  payload = JSON text    -> ok payload = base64 XDR
use std::collections::HashMap;
use std::io::{self, BufRead, Write};
use stellar_xdr::{Limits, Type, TypeVariant, WriteXdr};

fn main() {
    let mode = std::env::args().nth(1).unwrap_or_else(|| "tojson".to_string());
    let mut by_name: HashMap<String, TypeVariant> = HashMap::new();
    for v in TypeVariant::VARIANTS.iter() {
        by_name.insert(v.name().to_lowercase(), *v);
    }
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = line.unwrap();
        let mut it = line.splitn(3, '\t');
        let (id, ty, payload) = (it.next().unwrap(), it.next().unwrap(), it.next().unwrap());
        let res = match by_name.get(&ty.to_lowercase()) {
            None => ("notype", String::new()),
            Some(v) => {
                let r = std::panic::catch_unwind(|| -> Result<String, String> {
                    if mode == "tojson" {
                        let t = Type::from_xdr_base64(*v, payload, Limits { depth: 500, len: 64 * 1024 * 1024 })
                            .map_err(|e| format!("{e:?}"))?;
                        serde_json::to_string(&t).map_err(|e| format!("json: {e}"))
                    } else {
                        let t = Type::from_json(*v, payload.as_bytes()).map_err(|e| format!("{e:?}"))?;
                        t.to_xdr_base64(Limits::none()).map_err(|e| format!("{e:?}"))
                    }
                });
                match r {
                    Ok(Ok(s)) => ("ok", s),
                    Ok(Err(e)) => ("err", e),
                    Err(_) => ("panic", String::new()),
                }
            }
        };
        writeln!(out, "{}\t{}\t{}", id, res.0, res.1.replace(['\t', '\n'], " ")).unwrap();
    }
}
