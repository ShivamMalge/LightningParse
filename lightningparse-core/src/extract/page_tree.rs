use lopdf::{Dictionary, Document, Object, ObjectId};
use std::collections::{BTreeMap, HashSet};

use crate::errors::ParseError;

/// A robust, fault-tolerant replacement for `lopdf::Document::get_pages()`.
///
/// Mimics PyPDF2's leniency when traversing the page tree:
///
/// - **`/Kids`-based traversal:** If a dictionary contains a `/Kids` array,
///   it is treated as an intermediate `Pages` node regardless of its `/Type`.
/// - **Leaf detection:** A dictionary reached via a `/Kids` array that does
///   *not* contain a `/Kids` key is treated as a leaf `Page` node.
/// - **Malformed `/Kids`:** If a `/Kids` key exists but its value cannot be
///   resolved or is not an array, the node is logged as malformed and skipped.
///   It is *not* silently reinterpreted as a leaf `Page`.
/// - **Cycle detection:** A `HashSet<ObjectId>` tracks visited nodes to safely
///   abort on circular `/Kids` references without stack overflow.
/// - **Catalog fallback:** If the root catalog's `/Pages` entry is missing or
///   the tree walk produces zero pages, a conservative full-object scan looks
///   for dictionaries with strong page-like evidence (`/Type /Page`,
///   `/Contents`, or `/MediaBox` without `/Kids`).
///
/// # Page ordering
///
/// When traversal succeeds via the catalog `/Pages` tree, pages are numbered
/// in the order they appear in the `/Kids` arrays (depth-first, left-to-right),
/// which matches the logical document page order defined by the PDF spec.
///
/// When the **fallback** full-object scan is used (catalog `/Pages` missing or
/// entirely broken), pages are numbered in whatever order `doc.objects` iterates
/// — typically PDF object-table order. This **must not** be treated as
/// guaranteed document page order; it is a best-effort recovery for severely
/// corrupted files where the page tree is completely unavailable.
pub fn get_pages_tolerant(doc: &Document) -> Result<BTreeMap<u32, ObjectId>, ParseError> {
    let mut pages = BTreeMap::new();
    let mut page_num: u32 = 1;
    let mut visited = HashSet::new();

    // 1. Try to start from catalog's /Pages reference.
    if let Ok(catalog) = doc.catalog() {
        if let Ok(pages_ref) = catalog.get(b"Pages").and_then(Object::as_reference) {
            walk_tree(doc, pages_ref, &mut pages, &mut page_num, &mut visited);
        }
    }

    // 2. Fallback: if traversal found nothing, scan all objects conservatively.
    //    See doc-comment above for ordering caveats.
    if pages.is_empty() {
        for (id, obj) in &doc.objects {
            if let Ok(dict) = obj.as_dict() {
                if is_page_fallback(dict) {
                    pages.insert(page_num, *id);
                    page_num += 1;
                }
            }
        }
    }

    if pages.is_empty() {
        return Err(ParseError::CorruptPdf(
            "Document has 0 pages or page tree is malformed/unreadable by lopdf.".to_string(),
        ));
    }

    Ok(pages)
}

/// Effective page dimensions in PDF user-space units, after box selection and
/// rotation normalisation.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PageGeometry {
    pub width: f64,
    pub height: f64,
}

/// Resolve a page's *visible* dimensions.
///
/// Used by `cleanup::detect_headers_footers` to place margin bands against real
/// page geometry rather than against content extent. Deriving a "top 10%" band
/// from the tallest block on the page places it well below the true margin —
/// content essentially never reaches the physical top of the sheet — so the band
/// reaches down into body text and tags it as page furniture, which the
/// downstream chunker then drops.
///
/// - Prefers `/CropBox` (what a viewer displays) over `/MediaBox` (the full
///   sheet, which may include printer bleed).
/// - Both are *inheritable* page-tree attributes, so the `/Parent` chain is
///   walked when the leaf page omits them.
/// - `/Rotate` of 90 or 270 swaps the effective axes.
/// - Returns `None` when nothing usable is found, so callers fall back to the
///   previous content-extent behaviour and PDFs that work today cannot regress.
pub fn resolve_page_geometry(doc: &Document, page_id: ObjectId) -> Option<PageGeometry> {
    let rect = inherited_rect(doc, page_id, b"CropBox")
        .or_else(|| inherited_rect(doc, page_id, b"MediaBox"))?;

    let width = (rect[2] - rect[0]).abs();
    let height = (rect[3] - rect[1]).abs();
    if !width.is_finite() || !height.is_finite() || width <= 0.0 || height <= 0.0 {
        return None;
    }

    let rotate = inherited_int(doc, page_id, b"Rotate").unwrap_or(0).rem_euclid(360);
    if rotate == 90 || rotate == 270 {
        Some(PageGeometry {
            width: height,
            height: width,
        })
    } else {
        Some(PageGeometry { width, height })
    }
}

/// Look up an inheritable attribute, walking `/Parent` when the page omits it.
///
/// Cycle-safe by the same reasoning as `walk_tree`: a malformed page tree can
/// contain loops, and a `/Parent` chain is just as capable of forming one as a
/// `/Kids` chain.
fn inherited<'a>(doc: &'a Document, page_id: ObjectId, key: &[u8]) -> Option<&'a Object> {
    let mut current = page_id;
    let mut visited = HashSet::new();

    loop {
        if !visited.insert(current) {
            eprintln!(
                "lightningparse: /Parent cycle detected at object {:?} while resolving {}",
                current,
                String::from_utf8_lossy(key)
            );
            return None;
        }

        let dict = doc.get_dictionary(current).ok()?;
        if let Ok(obj) = dict.get(key) {
            return doc.dereference(obj).ok().map(|(_, resolved)| resolved);
        }

        current = dict.get(b"Parent").and_then(Object::as_reference).ok()?;
    }
}

/// Resolve an inheritable rectangle (`[x0 y0 x1 y1]`), dereferencing any
/// indirect elements — the array itself and each number may be a reference.
fn inherited_rect(doc: &Document, page_id: ObjectId, key: &[u8]) -> Option<[f64; 4]> {
    let array = inherited(doc, page_id, key)?.as_array().ok()?;
    if array.len() != 4 {
        return None;
    }

    let mut out = [0.0f64; 4];
    for (i, item) in array.iter().enumerate() {
        let resolved = doc.dereference(item).ok().map(|(_, o)| o)?;
        out[i] = f64::from(resolved.as_float().ok()?);
    }
    Some(out)
}

fn inherited_int(doc: &Document, page_id: ObjectId, key: &[u8]) -> Option<i64> {
    inherited(doc, page_id, key)?.as_i64().ok()
}

fn walk_tree(
    doc: &Document,
    node_id: ObjectId,
    pages: &mut BTreeMap<u32, ObjectId>,
    page_num: &mut u32,
    visited: &mut HashSet<ObjectId>,
) {
    // Cycle detection: abort if we've already visited this node.
    if !visited.insert(node_id) {
        eprintln!(
            "lightningparse: page tree cycle detected at object {:?}, skipping",
            node_id
        );
        return;
    }

    // Attempt to resolve the node as a dictionary.
    let dict = match doc.get_dictionary(node_id) {
        Ok(d) => d,
        Err(e) => {
            eprintln!(
                "lightningparse: failed to resolve page-tree node {:?}: {}, skipping",
                node_id, e
            );
            return;
        }
    };

    // Distinguish: /Kids key absent vs /Kids key present.
    if dict.has(b"Kids") {
        // /Kids key exists — attempt to dereference and interpret as array.
        match dict.get_deref(b"Kids", doc).and_then(Object::as_array) {
            Ok(kids) => {
                for kid in kids {
                    if let Ok(kid_id) = kid.as_reference() {
                        walk_tree(doc, kid_id, pages, page_num, visited);
                    }
                }
            }
            Err(_) => {
                // /Kids exists but is malformed (not resolvable or not an array).
                // This is a broken intermediate node — do NOT treat it as a Page.
                eprintln!(
                    "lightningparse: object {:?} has malformed /Kids entry, skipping subtree",
                    node_id
                );
            }
        }
    } else {
        // No /Kids key at all. Since we reached this node by walking the
        // page tree, it is a leaf Page node (attributes may be inherited
        // from ancestor Pages nodes per the PDF spec).
        pages.insert(*page_num, node_id);
        *page_num += 1;
    }
}

/// Conservative heuristic for the full-object fallback scan.
///
/// Returns `true` only if the dictionary looks like a standalone Page:
/// - Must NOT have `/Kids` (that would indicate an intermediate `Pages` node).
/// - Either has explicit `/Type /Page` (case-insensitive), or
/// - Has `/Contents` or `/MediaBox` (strong page-like evidence).
fn is_page_fallback(dict: &Dictionary) -> bool {
    if dict.has(b"Kids") {
        return false;
    }

    // Explicit /Type == Page (case-insensitive)
    if let Ok(t) = dict.get(b"Type").and_then(Object::as_name) {
        if t.eq_ignore_ascii_case(b"Page") {
            return true;
        }
    }

    // Without explicit Type, require strong evidence.
    dict.has(b"Contents") || dict.has(b"MediaBox")
}

#[cfg(test)]
mod tests {
    use super::*;
    use lopdf::Dictionary as LoDictionary;
    use lopdf::{Document, Object};

    fn make_doc() -> Document {
        Document::with_version("1.5")
    }

    // ── Normal valid page tree ────────────────────────────────────

    #[test]
    fn test_valid_normal_page_tree() {
        let mut doc = make_doc();

        let mut page = LoDictionary::new();
        page.set("Type", Object::Name(b"Page".to_vec()));
        page.set("Contents", Object::Array(vec![]));
        let page_id = doc.add_object(page);

        let mut pages_node = LoDictionary::new();
        pages_node.set("Type", Object::Name(b"Pages".to_vec()));
        pages_node.set("Kids", Object::Array(vec![Object::Reference(page_id)]));
        let pages_id = doc.add_object(pages_node);

        let mut catalog = LoDictionary::new();
        catalog.set("Type", Object::Name(b"Catalog".to_vec()));
        catalog.set("Pages", Object::Reference(pages_id));
        let cat_id = doc.add_object(catalog);

        doc.trailer.set("Root", Object::Reference(cat_id));

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 1);
        assert_eq!(pages[&1], page_id);
    }

    // ── Missing /Type /Pages ──────────────────────────────────────

    #[test]
    fn test_missing_type_pages() {
        let mut doc = make_doc();

        let mut page = LoDictionary::new();
        page.set("Type", Object::Name(b"Page".to_vec()));
        let page_id = doc.add_object(page);

        // Omit Type=Pages, but include Kids
        let mut pages_node = LoDictionary::new();
        pages_node.set("Kids", Object::Array(vec![Object::Reference(page_id)]));
        let pages_id = doc.add_object(pages_node);

        let mut catalog = LoDictionary::new();
        catalog.set("Type", Object::Name(b"Catalog".to_vec()));
        catalog.set("Pages", Object::Reference(pages_id));
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 1);
        assert_eq!(pages[&1], page_id);
    }

    // ── Missing /Type /Page ───────────────────────────────────────

    #[test]
    fn test_missing_type_page() {
        let mut doc = make_doc();

        // Omit Type=Page entirely
        let mut page = LoDictionary::new();
        page.set("MediaBox", Object::Array(vec![]));
        let page_id = doc.add_object(page);

        let mut pages_node = LoDictionary::new();
        pages_node.set("Kids", Object::Array(vec![Object::Reference(page_id)]));
        let pages_id = doc.add_object(pages_node);

        let mut catalog = LoDictionary::new();
        catalog.set("Pages", Object::Reference(pages_id));
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 1);
        assert_eq!(pages[&1], page_id);
    }

    // ── Malformed / case-variant /Type ────────────────────────────

    #[test]
    fn test_malformed_type_values() {
        let mut doc = make_doc();

        let mut page = LoDictionary::new();
        page.set("Type", Object::Name(b"PAGE".to_vec())); // wrong case
        let page_id = doc.add_object(page);

        let mut pages_node = LoDictionary::new();
        pages_node.set("Type", Object::Name(b"PaGeS".to_vec())); // wrong case
        pages_node.set("Kids", Object::Array(vec![Object::Reference(page_id)]));
        let pages_id = doc.add_object(pages_node);

        let mut catalog = LoDictionary::new();
        catalog.set("Pages", Object::Reference(pages_id));
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 1);
        assert_eq!(pages[&1], page_id);
    }

    // ── Nested page tree ──────────────────────────────────────────
    //
    // Catalog → Root Pages → [Intermediate A, Intermediate B]
    //   Intermediate A → [Page 1, Page 2]
    //   Intermediate B → [Page 3]

    #[test]
    fn test_nested_page_tree() {
        let mut doc = make_doc();

        let mut page1 = LoDictionary::new();
        page1.set("Type", Object::Name(b"Page".to_vec()));
        page1.set("MediaBox", Object::Array(vec![]));
        let page1_id = doc.add_object(page1);

        let mut page2 = LoDictionary::new();
        page2.set("Type", Object::Name(b"Page".to_vec()));
        page2.set("MediaBox", Object::Array(vec![]));
        let page2_id = doc.add_object(page2);

        let mut page3 = LoDictionary::new();
        page3.set("Type", Object::Name(b"Page".to_vec()));
        page3.set("MediaBox", Object::Array(vec![]));
        let page3_id = doc.add_object(page3);

        // Intermediate A: no /Type, just /Kids
        let mut intermediate_a = LoDictionary::new();
        intermediate_a.set(
            "Kids",
            Object::Array(vec![
                Object::Reference(page1_id),
                Object::Reference(page2_id),
            ]),
        );
        let ia_id = doc.add_object(intermediate_a);

        // Intermediate B: no /Type, just /Kids
        let mut intermediate_b = LoDictionary::new();
        intermediate_b.set("Kids", Object::Array(vec![Object::Reference(page3_id)]));
        let ib_id = doc.add_object(intermediate_b);

        // Root Pages node
        let mut root_pages = LoDictionary::new();
        root_pages.set("Type", Object::Name(b"Pages".to_vec()));
        root_pages.set(
            "Kids",
            Object::Array(vec![Object::Reference(ia_id), Object::Reference(ib_id)]),
        );
        let root_pages_id = doc.add_object(root_pages);

        let mut catalog = LoDictionary::new();
        catalog.set("Type", Object::Name(b"Catalog".to_vec()));
        catalog.set("Pages", Object::Reference(root_pages_id));
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 3);
        assert_eq!(pages[&1], page1_id);
        assert_eq!(pages[&2], page2_id);
        assert_eq!(pages[&3], page3_id);
    }

    // ── Inherited page attributes ─────────────────────────────────

    #[test]
    fn test_inherited_page_attributes() {
        let mut doc = make_doc();

        // Leaf node with no attributes at all — relies on inherited MediaBox
        let page = LoDictionary::new();
        let page_id = doc.add_object(page);

        let mut pages_node = LoDictionary::new();
        pages_node.set("MediaBox", Object::Array(vec![]));
        pages_node.set("Kids", Object::Array(vec![Object::Reference(page_id)]));
        let pages_id = doc.add_object(pages_node);

        let mut catalog = LoDictionary::new();
        catalog.set("Pages", Object::Reference(pages_id));
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 1);
        assert_eq!(pages[&1], page_id);
    }

    // ── Circular /Kids references ─────────────────────────────────

    #[test]
    fn test_circular_kids_references() {
        let mut doc = make_doc();

        let mut page = LoDictionary::new();
        page.set("Type", Object::Name(b"Page".to_vec()));
        let page_id = doc.add_object(page);

        let pages1_id: ObjectId = (100, 0);
        let pages2_id: ObjectId = (101, 0);

        let mut pages1 = LoDictionary::new();
        pages1.set(
            "Kids",
            Object::Array(vec![
                Object::Reference(page_id),
                Object::Reference(pages2_id),
            ]),
        );

        let mut pages2 = LoDictionary::new();
        pages2.set("Kids", Object::Array(vec![Object::Reference(pages1_id)]));

        doc.objects.insert(pages1_id, Object::Dictionary(pages1));
        doc.objects.insert(pages2_id, Object::Dictionary(pages2));

        let mut catalog = LoDictionary::new();
        catalog.set("Pages", Object::Reference(pages1_id));
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 1);
        assert_eq!(pages[&1], page_id);
    }

    // ── Malformed /Kids (key present but not an array) ────────────

    #[test]
    fn test_malformed_kids_not_treated_as_page() {
        let mut doc = make_doc();

        // A real page that should be found
        let mut page = LoDictionary::new();
        page.set("Type", Object::Name(b"Page".to_vec()));
        page.set("MediaBox", Object::Array(vec![]));
        let page_id = doc.add_object(page);

        // Malformed intermediate: /Kids is an integer, not an array.
        let mut malformed = LoDictionary::new();
        malformed.set("Kids", Object::Integer(42));
        let malformed_id = doc.add_object(malformed);

        // Root Pages node with both children
        let mut root_pages = LoDictionary::new();
        root_pages.set(
            "Kids",
            Object::Array(vec![
                Object::Reference(malformed_id),
                Object::Reference(page_id),
            ]),
        );
        let root_id = doc.add_object(root_pages);

        let mut catalog = LoDictionary::new();
        catalog.set("Pages", Object::Reference(root_id));
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        let pages = get_pages_tolerant(&doc).unwrap();

        // The malformed node must NOT be counted as a page.
        // Only the real page should appear.
        assert_eq!(pages.len(), 1);
        assert_eq!(pages[&1], page_id);
    }

    // ── Missing catalog /Pages entry → fallback ───────────────────

    #[test]
    fn test_missing_catalog_pages_entry_fallback() {
        let mut doc = make_doc();

        let catalog = LoDictionary::new();
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        let mut page = LoDictionary::new();
        page.set("Type", Object::Name(b"Page".to_vec()));
        let page_id = doc.add_object(page);

        let mut page2 = LoDictionary::new();
        page2.set("Contents", Object::Array(vec![]));
        let page2_id = doc.add_object(page2);

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 2);

        // Fallback order is object-table order, not guaranteed document order.
        let ids: Vec<_> = pages.values().copied().collect();
        assert!(ids.contains(&page_id));
        assert!(ids.contains(&page2_id));
    }

    // ── Explicit lopdf regression proof ───────────────────────────
    //
    // Demonstrates that lopdf's native `get_pages()` returns 0 pages
    // for a page tree missing /Type tags, while our tolerant walker
    // correctly recovers the pages. This is the exact bug that caused
    // silent extraction failure on real-world PDFs.

    #[test]
    fn test_lopdf_get_pages_fails_tolerant_succeeds() {
        let mut doc = make_doc();

        // Page without /Type /Page
        let mut page = LoDictionary::new();
        page.set("MediaBox", Object::Array(vec![]));
        page.set("Contents", Object::Array(vec![]));
        let page_id = doc.add_object(page);

        // Pages node without /Type /Pages
        let mut pages_node = LoDictionary::new();
        pages_node.set("Kids", Object::Array(vec![Object::Reference(page_id)]));
        let pages_id = doc.add_object(pages_node);

        let mut catalog = LoDictionary::new();
        catalog.set("Pages", Object::Reference(pages_id));
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        // lopdf's strict get_pages() fails — returns empty map
        let native_pages = doc.get_pages();
        assert!(
            native_pages.is_empty(),
            "Expected lopdf::get_pages() to return 0 pages for missing /Type tags, \
             but got {}. If lopdf has been updated to handle this case, \
             this regression test should be revisited.",
            native_pages.len()
        );

        // Our tolerant walker succeeds
        let tolerant_pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(tolerant_pages.len(), 1);
        assert_eq!(tolerant_pages[&1], page_id);
    }
}

#[cfg(test)]
mod geometry_tests {
    use super::*;
    use lopdf::{Dictionary as LoDictionary, Object};

    /// Page with an explicit MediaBox.
    #[test]
    fn test_explicit_mediabox() {
        let mut doc = Document::with_version("1.5");
        let mut page = LoDictionary::new();
        page.set(
            "MediaBox",
            Object::Array(vec![
                Object::Integer(0),
                Object::Integer(0),
                Object::Integer(612),
                Object::Integer(792),
            ]),
        );
        let id = doc.add_object(page);
        let g = resolve_page_geometry(&doc, id).expect("geometry");
        assert_eq!(g.width, 612.0);
        assert_eq!(g.height, 792.0);
    }

    /// CropBox wins over MediaBox: it is what a viewer actually displays.
    #[test]
    fn test_cropbox_preferred_over_mediabox() {
        let mut doc = Document::with_version("1.5");
        let mut page = LoDictionary::new();
        page.set(
            "MediaBox",
            Object::Array(vec![
                Object::Integer(0),
                Object::Integer(0),
                Object::Integer(700),
                Object::Integer(900),
            ]),
        );
        page.set(
            "CropBox",
            Object::Array(vec![
                Object::Integer(0),
                Object::Integer(0),
                Object::Integer(612),
                Object::Integer(792),
            ]),
        );
        let id = doc.add_object(page);
        let g = resolve_page_geometry(&doc, id).expect("geometry");
        assert_eq!(g.width, 612.0);
        assert_eq!(g.height, 792.0);
    }

    /// MediaBox is inheritable: a leaf page may omit it entirely.
    #[test]
    fn test_inherited_mediabox_from_parent() {
        let mut doc = Document::with_version("1.5");
        let page_id = doc.add_object(LoDictionary::new());

        let mut parent = LoDictionary::new();
        parent.set(
            "MediaBox",
            Object::Array(vec![
                Object::Integer(0),
                Object::Integer(0),
                Object::Integer(595),
                Object::Integer(842),
            ]),
        );
        parent.set("Kids", Object::Array(vec![Object::Reference(page_id)]));
        let parent_id = doc.add_object(parent);

        // Link the child back up so the /Parent walk can find the attribute.
        if let Ok(d) = doc.get_dictionary_mut(page_id) {
            d.set("Parent", Object::Reference(parent_id));
        }

        let g = resolve_page_geometry(&doc, page_id).expect("inherited geometry");
        assert_eq!(g.width, 595.0);
        assert_eq!(g.height, 842.0);
    }

    /// A cyclic /Parent chain must terminate rather than recurse forever.
    #[test]
    fn test_cyclic_parent_chain_terminates() {
        let mut doc = Document::with_version("1.5");
        let a_id = doc.add_object(LoDictionary::new());
        let b_id = doc.add_object(LoDictionary::new());
        if let Ok(d) = doc.get_dictionary_mut(a_id) {
            d.set("Parent", Object::Reference(b_id));
        }
        if let Ok(d) = doc.get_dictionary_mut(b_id) {
            d.set("Parent", Object::Reference(a_id));
        }
        // No geometry anywhere and a loop: must return None, not hang.
        assert!(resolve_page_geometry(&doc, a_id).is_none());
    }

    /// Missing geometry yields None so callers fall back to old behaviour.
    #[test]
    fn test_missing_geometry_returns_none() {
        let mut doc = Document::with_version("1.5");
        let id = doc.add_object(LoDictionary::new());
        assert!(resolve_page_geometry(&doc, id).is_none());
    }

    /// Degenerate boxes are rejected rather than producing a zero-height band.
    #[test]
    fn test_degenerate_box_returns_none() {
        let mut doc = Document::with_version("1.5");
        let mut page = LoDictionary::new();
        page.set(
            "MediaBox",
            Object::Array(vec![
                Object::Integer(0),
                Object::Integer(0),
                Object::Integer(0),
                Object::Integer(0),
            ]),
        );
        let id = doc.add_object(page);
        assert!(resolve_page_geometry(&doc, id).is_none());
    }

    /// /Rotate 90 swaps the effective axes.
    #[test]
    fn test_rotate_90_swaps_axes() {
        let mut doc = Document::with_version("1.5");
        let mut page = LoDictionary::new();
        page.set(
            "MediaBox",
            Object::Array(vec![
                Object::Integer(0),
                Object::Integer(0),
                Object::Integer(612),
                Object::Integer(792),
            ]),
        );
        page.set("Rotate", Object::Integer(90));
        let id = doc.add_object(page);
        let g = resolve_page_geometry(&doc, id).expect("geometry");
        assert_eq!(g.width, 792.0);
        assert_eq!(g.height, 612.0);
    }

    /// Negative rotations normalise (rem_euclid), e.g. -90 behaves as 270.
    #[test]
    fn test_negative_rotate_normalises() {
        let mut doc = Document::with_version("1.5");
        let mut page = LoDictionary::new();
        page.set(
            "MediaBox",
            Object::Array(vec![
                Object::Integer(0),
                Object::Integer(0),
                Object::Integer(612),
                Object::Integer(792),
            ]),
        );
        page.set("Rotate", Object::Integer(-90));
        let id = doc.add_object(page);
        let g = resolve_page_geometry(&doc, id).expect("geometry");
        assert_eq!(g.width, 792.0);
        assert_eq!(g.height, 612.0);
    }

    /// Real-valued and offset boxes are handled, not just integer origins.
    #[test]
    fn test_offset_and_real_valued_box() {
        let mut doc = Document::with_version("1.5");
        let mut page = LoDictionary::new();
        page.set(
            "MediaBox",
            Object::Array(vec![
                Object::Real(10.5),
                Object::Real(20.5),
                Object::Real(622.5),
                Object::Real(812.5),
            ]),
        );
        let id = doc.add_object(page);
        let g = resolve_page_geometry(&doc, id).expect("geometry");
        assert_eq!(g.width, 612.0);
        assert_eq!(g.height, 792.0);
    }
}
