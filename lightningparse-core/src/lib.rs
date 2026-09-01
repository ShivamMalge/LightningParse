use crate::errors::ParseError;
use crate::output::{DocumentMetadata, ParseResult};
use lopdf::Document;

pub mod cleanup;
pub mod errors;
pub mod extract;
pub mod ffi;
pub mod ocr;
pub mod output;

pub fn parse_pdf_to_result(path: &str) -> Result<ParseResult, ParseError> {
    let pdf_bytes = std::fs::read(path).map_err(ParseError::Io)?;
    let start = std::time::Instant::now();

    let doc = Document::load_mem(&pdf_bytes)
        .map_err(|e| ParseError::CorruptPdf(format!("Failed to parse PDF: {e}")))?;

    let extract_results = extract::extract_text(&doc)?;

    let mut pages = Vec::new();
    let mut total_digital_pages = 0;
    let mut total_scanned_pages = 0;
    let mut all_warnings = Vec::new();

    for (mut page, total_chars, mut warnings) in extract_results {
        all_warnings.append(&mut warnings);
        if total_chars == 0 {
            // OCR fallback — page geometry is preserved across the swap.
            page.blocks = ocr::extract_page_ocr(path, page.page_num)?;
            total_scanned_pages += 1;
        } else {
            total_digital_pages += 1;
        }

        pages.push(page);
    }

    let tier = if total_digital_pages > 0 && total_scanned_pages > 0 {
        "mixed"
    } else if total_scanned_pages > 0 {
        "scanned"
    } else {
        "digital"
    };

    // NOTE: this measures Rust-side EXTRACTION ONLY. The cleanup passes
    // (tables, reading order, header/footer, headings) and JSON serialization
    // run in `ffi::parse_pdf` *after* this timer stops, and the caller then
    // deserializes on the Python side — so end-to-end latency is meaningfully
    // higher than this number. On a 15-page two-column paper: ~44 ms here,
    // ~68 ms for the full `parse_pdf()` call, ~77 ms including `json.loads`.
    // Deliberately not renamed — it is a published output field.
    // See FINDINGS-BENCHMARK-DISCREPANCY.md.
    let parse_time_ms = start.elapsed().as_millis() as u64;
    let page_count = pages.len() as u32;

    Ok(ParseResult {
        pages,
        metadata: DocumentMetadata {
            tier: tier.to_string(),
            page_count,
            parse_time_ms,
            warnings: all_warnings,
        },
    })
}
