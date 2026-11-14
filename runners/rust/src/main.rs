// Reference runner: rs-stellar-xdr. Reads "id\ttype\tb64" lines, writes "id\tstatus\tpayload".
use std::collections::HashMap;
use std::io::{self, BufRead, Write};
use stellar_xdr::{Limits, Type, TypeVariant, WriteXdr};

fn main() {
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
        let (id, ty, b64) = (it.next().unwrap(), it.next().unwrap(), it.next().unwrap());
        let res = match by_name.get(&ty.to_lowercase()) {
            None => ("notype", String::new()),
            Some(v) => {
                let r = std::panic::catch_unwind(|| {
                    Type::from_xdr_base64(*v, b64, Limits { depth: 500, len: 64 * 1024 * 1024 })
                        .and_then(|t| t.to_xdr_base64(Limits::none()))
                });
                match r {
                    Ok(Ok(s)) => ("ok", s),
                    Ok(Err(e)) => ("err", format!("{e:?}")),
                    Err(_) => ("panic", String::new()),
                }
            }
        };
        writeln!(out, "{}\t{}\t{}", id, res.0, res.1.replace(['\t', '\n'], " ")).unwrap();
    }
}
