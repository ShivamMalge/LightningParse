//! Integration tests using real-world PDF files.
//!
//! These tests exercise the extraction engine on actual documents rather
//! than programmatically generated fixtures.  They verify:
//!   - Parsing succeeds without errors
//!   - Pages and blocks are non-empty (for digital-native PDFs)
//!   - Page order is deterministic (important now that rayon is in play)
//!   - JSON serialisation round-trips cleanly

use std::path::PathBuf;

fn corpus_dir() -> PathBuf {
    let mut p = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    p.pop(); // up from lightningparse-core/
    p.push("benchmarks");
    p.push("corpus");
    p
}

fn read_corpus_file(name: &str) -> String {
    let path = corpus_dir().join(name);
    path.to_str().unwrap().to_string()
}

// ── Shivam_FullStack.pdf (image-based / scanned, Tier 2 — not in Tier 1 corpus) ──

#[test]
fn test_real_canva_pdf_form_xobject_extraction() {
    // Lives in benchmarks/corpus/ (Tier 1).
    let path = read_corpus_file("Shivam_FullStack.pdf");

    let result = lightningparse::parse_pdf_to_result(&path)
        .expect("Shivam_FullStack.pdf should parse without error");

    assert_eq!(result.metadata.page_count, 1);
    assert_eq!(result.pages.len(), 1);
    assert_eq!(result.metadata.tier, "digital");

    // This PDF is a Canva digital-native PDF that wraps the entire page in a Form XObject.
    // It should now correctly extract text since Form XObject `Do` tracking is implemented.
    let total_blocks: usize = result.pages.iter().map(|p| p.blocks.len()).sum();
    assert_eq!(
        total_blocks, 48,
        "Canva PDF should produce 48 blocks from digital extraction inside Form XObjects"
    );
}

// ── ieee_template_placeholder.pdf (multi-page, two-column, digital-native) ────

#[test]
fn test_real_latex_pdf_parses() {
    let path = read_corpus_file("ieee_template_placeholder.pdf");
    let result = lightningparse::parse_pdf_to_result(&path)
        .expect("ieee_template_placeholder.pdf should parse successfully");

    assert!(
        result.metadata.page_count >= 2,
        "LaTeX doc should have multiple pages, got {}",
        result.metadata.page_count,
    );
    assert_eq!(result.pages.len(), result.metadata.page_count as usize);
    assert_eq!(result.metadata.tier, "digital");
}

#[test]
fn test_real_latex_pdf_page_order() {
    let path = read_corpus_file("ieee_template_placeholder.pdf");
    let result = lightningparse::parse_pdf_to_result(&path).unwrap();

    for w in result.pages.windows(2) {
        assert!(
            w[0].page_num < w[1].page_num,
            "pages out of order: {} >= {}",
            w[0].page_num,
            w[1].page_num,
        );
    }
}

#[test]
fn test_real_latex_pdf_has_text() {
    let path = read_corpus_file("ieee_template_placeholder.pdf");
    let result = lightningparse::parse_pdf_to_result(&path).unwrap();

    let total_blocks: usize = result.pages.iter().map(|p| p.blocks.len()).sum();
    assert!(total_blocks > 0, "LaTeX PDF should produce text blocks");

    // Spot-check: combined text should be substantial.
    let all_text: String = result
        .pages
        .iter()
        .flat_map(|p| p.blocks.iter())
        .map(|b| b.text())
        .collect::<Vec<_>>()
        .join(" ");
    assert!(
        all_text.len() > 50,
        "combined text should be substantial, got {} chars",
        all_text.len(),
    );
}

#[test]
fn test_real_latex_pdf_json_roundtrip() {
    let path = read_corpus_file("ieee_template_placeholder.pdf");
    let result = lightningparse::parse_pdf_to_result(&path).unwrap();

    let json = serde_json::to_string(&result).expect("serialisation should work");
    let val: serde_json::Value = serde_json::from_str(&json).unwrap();

    assert!(val["pages"].is_array());
    let pages_arr = val["pages"].as_array().unwrap();
    assert!(pages_arr.len() >= 2);

    // Every block must have the required fields.
    for page in pages_arr {
        for blk in page["blocks"].as_array().unwrap_or(&vec![]) {
            assert!(blk["text"].is_string());
            assert!(blk["bbox"].is_array());
            assert_eq!(blk["bbox"].as_array().unwrap().len(), 4);
            assert!(blk["section_id"].is_string());
            assert!(blk["source"].is_string());
        }
    }
}

// ── Determinism: multiple runs must produce identical content ────

#[test]
fn test_parallel_determinism() {
    let path = read_corpus_file("arxiv_twocolumn.pdf");

    // Process using our multi-threaded pipeline
    let first = lightningparse::parse_pdf_to_result(&path).unwrap();

    // Process multiple times to verify thread stability
    for i in 0..5 {
        let r = lightningparse::parse_pdf_to_result(&path).unwrap();

        assert_eq!(first.pages.len(), r.pages.len(), "run count differs",);

        for (p1, p2) in first.pages.iter().zip(r.pages.iter()) {
            assert_eq!(p1.page_num, p2.page_num, "run {i}: page_num mismatch",);
            assert_eq!(
                p1.blocks.len(),
                p2.blocks.len(),
                "run {i}: block count differs on page {}",
                p1.page_num,
            );
            for (b1, b2) in p1.blocks.iter().zip(p2.blocks.iter()) {
                assert_eq!(
                    b1.text(),
                    b2.text(),
                    "run {i}: text differs on page {}",
                    p1.page_num,
                );
                assert_eq!(
                    b1.bbox(),
                    b2.bbox(),
                    "run {i}: bbox differs on page {}",
                    p1.page_num,
                );
            }
        }
    }
}

// -- Mixed PDF Test ----

#[test]
fn test_mixed_document_routing() {
    let mut path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    path.push("tests");
    path.push("fixtures");
    path.push("tier2");
    path.push("mixed_test.pdf");

    // The mixed PDF contains 8 digital pages and 1 scanned page.
    let result = lightningparse::parse_pdf_to_result(path.to_str().unwrap())
        .expect("mixed_test.pdf should parse successfully");

    assert_eq!(result.metadata.tier, "mixed");
    assert_eq!(result.metadata.page_count, 9);
    assert_eq!(result.pages.len(), 9);

    let mut digital_count = 0;
    let mut ocr_count = 0;
    for page in &result.pages {
        for block in &page.blocks {
            if block.source() == "digital" {
                digital_count += 1;
            } else if block.source() == "ocr" {
                ocr_count += 1;
            }
        }
    }

    assert!(digital_count > 0, "Expected digital blocks, found none");
    assert!(ocr_count > 0, "Expected OCR blocks, found none");
}

#[test]
fn test_bold_label_value_spans() {
    let path = read_corpus_file("bold_label_value.pdf");
    let result =
        lightningparse::parse_pdf_to_result(&path).expect("Should parse bold_label_value.pdf");

    let mut found_target = false;
    for page in result.pages {
        for block in page.blocks {
            if let lightningparse::output::Block::Text { text, spans, .. } = block {
                if text.starts_with("Frontend:") {
                    assert_eq!(spans.len(), 2, "Should have exactly 2 spans after merging");
                    assert!(spans[0].bold, "First span (Frontend:) should be bold");
                    assert!(
                        !spans[1].bold,
                        "Second span (Next.js...) should not be bold"
                    );
                    assert_eq!(spans[0].start, 0);
                    assert_eq!(spans[0].end, 10); // "Frontend: " is 10 chars
                    assert_eq!(spans[1].start, 10);
                    assert_eq!(spans[1].end, 36); // "Next.js, React, TypeScript" is 26 chars (10+26=36)
                    found_target = true;
                }
            }
        }
    }
    assert!(found_target, "Did not find the target merged text block");
}

#[test]
fn test_code_block_detection() {
    let mut path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    path.push("tests");
    path.push("fixtures");
    path.push("code_block_fixture.pdf");
    let doc = lightningparse::parse_pdf_to_result(path.to_str().unwrap()).unwrap();
    let blocks = &doc.pages[0].blocks;

    // "This is a regular paragraph of body text." -> None
    assert_eq!(blocks[0].block_role(), None);
    // "We can also call parse() inline." -> None (it's inline, not a structural code block)
    assert_eq!(blocks[2].block_role(), None);
    // "def fibonacci(n):" -> code
    assert_eq!(blocks[3].block_role(), Some("code"));
}

// ── ASCII85Decode: end-to-end digital extraction ────────────────

#[test]
fn test_ascii85_digital_extraction() {
    let path = read_corpus_file("ascii85_test.pdf");
    let result = lightningparse::parse_pdf_to_result(&path)
        .expect("ascii85_test.pdf should parse successfully");

    assert_eq!(result.metadata.page_count, 1);
    assert_eq!(result.pages.len(), 1);

    // The critical assertion: tier must be "digital", not "scanned"
    assert_eq!(
        result.metadata.tier, "digital",
        "ASCII85-encoded PDF should be routed as Tier 1 digital, not scanned/OCR"
    );

    // Warnings must be empty — ASCII85Decode is a supported filter
    assert!(
        result.metadata.warnings.is_empty(),
        "ASCII85Decode should not trigger unsupported-filter warnings, got: {:?}",
        result.metadata.warnings
    );

    // Should have extracted actual text blocks
    let total_blocks: usize = result.pages.iter().map(|p| p.blocks.len()).sum();
    assert!(
        total_blocks > 0,
        "Should extract text blocks from ASCII85-encoded content"
    );

    // Every block should report source="digital"
    for page in &result.pages {
        for block in &page.blocks {
            assert_eq!(
                block.source(),
                "digital",
                "ASCII85 content blocks should be digital, not scanned"
            );
        }
    }

    // Spot-check: the encoded content should contain "Hello ASCII85"
    let all_text: String = result
        .pages
        .iter()
        .flat_map(|p| p.blocks.iter())
        .map(|b| b.text())
        .collect::<Vec<_>>()
        .join(" ");
    assert!(
        all_text.contains("Hello") || all_text.contains("ASCII85"),
        "Extracted text should contain expected content from ASCII85 stream, got: {:?}",
        all_text
    );
}

// ── Multi-stream pages: content-stream join boundary ────────────

/// lopdf 0.42 started inserting a newline between concatenated content
/// streams.  `multistream_test.pdf` joins two streams at an adversarial
/// boundary — the first ends with `ET` and the second begins with `BT`, with
/// no whitespace on either side.  Without the separator the two operators fuse
/// into a single corrupt `ETBT` token, silently dropping a text-object
/// boundary rather than raising an error.  This test pins the decoded result.
#[test]
fn test_multistream_page_segmentation() {
    let path = read_corpus_file("multistream_test.pdf");
    let result = lightningparse::parse_pdf_to_result(&path)
        .expect("multistream_test.pdf should parse successfully");

    assert_eq!(result.metadata.page_count, 1);
    assert_eq!(result.metadata.tier, "digital");
    assert!(
        result.metadata.warnings.is_empty(),
        "Uncompressed multi-stream page should not warn, got: {:?}",
        result.metadata.warnings
    );

    let blocks = &result.pages[0].blocks;

    // Each stream must yield its own block — a fused ETBT token collapses the
    // text objects and changes this count.
    assert_eq!(
        blocks.len(),
        2,
        "Expected one block per content stream, got: {:?}",
        blocks.iter().map(|b| b.text()).collect::<Vec<_>>()
    );

    // Reading order is top-down: y=700 before y=650.
    assert_eq!(blocks[0].text().trim(), "Alpha from stream one");
    assert_eq!(blocks[1].text().trim(), "Beta from stream two");

    // Text from the second stream must not bleed into the first.
    assert!(
        !blocks[0].text().contains("Beta"),
        "Stream contents must not merge across the join boundary"
    );
}
