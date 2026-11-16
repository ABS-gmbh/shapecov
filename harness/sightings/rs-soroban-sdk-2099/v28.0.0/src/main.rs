// MuxedAddress::try_from_val on a non-address ScVal (rs-soroban-sdk #2099): the topic symbol
// "transfer", as it appears in contract events in the corpus ledgers.
use soroban_sdk::{xdr::{ReadXdr, Limits, ScVal}, Env, MuxedAddress, TryFromVal};
fn main() {
    let env = Env::default();
    let v = ScVal::from_xdr_base64("AAAADwAAAAh0cmFuc2Zlcg==", Limits::none()).unwrap();
    let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| MuxedAddress::try_from_val(&env, &v).is_err()));
    match r {
        Ok(true) => println!("returns ConversionError"),
        Ok(false) => println!("converted (unexpected)"),
        Err(_) => println!("panics"),
    }
}
