// Ad-hoc verification harness: parse a PDF and print the full ParseResult JSON.
fn main() {
    let path = std::env::args().nth(1).expect("usage: dump_json <pdf>");
    match lightningparse::parse_pdf_to_result(&path) {
        Ok(result) => {
            println!("{}", serde_json::to_string_pretty(&result).unwrap());
        }
        Err(e) => {
            eprintln!("ERROR: {e}");
            std::process::exit(1);
        }
    }
}
