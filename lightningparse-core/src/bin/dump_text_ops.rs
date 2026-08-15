fn main() {
    let doc = lopdf::Document::load("../lightningparse-core/tests/fixtures/code_block_fixture.pdf")
        .unwrap();
    let page_id = lightningparse::extract::page_tree::get_pages_tolerant(&doc).unwrap()[&1];
    let content_data = doc.get_page_content(page_id);
    println!("Decompressed length: {}", content_data.len());
    let s = String::from_utf8_lossy(&content_data);
    println!("First chars: {:?}", &s[..30.min(s.len())]);
}
