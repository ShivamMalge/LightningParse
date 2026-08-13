use lopdf::{Dictionary, Document, Object, ObjectId};
use std::collections::{BTreeMap, HashSet};

use crate::errors::ParseError;

/// A robust, fault-tolerant replacement for `lopdf::Document::get_pages()`.
///
/// It mimics PyPDF2's leniency:
/// - If a dictionary contains a `/Kids` array, it is a `Pages` node, regardless of `/Type`.
/// - If it doesn't have `/Kids` but is reached via a `Kids` array, it's a `Page`.
/// - Detects cycles to avoid infinite loops on corrupted PDFs.
/// - If the root catalog fails, it falls back to scanning all objects for `Page`-like dictionaries.
pub fn get_pages_tolerant(doc: &Document) -> Result<BTreeMap<u32, ObjectId>, ParseError> {
    let mut pages = BTreeMap::new();
    let mut page_num = 1;
    let mut visited = HashSet::new();

    // 1. Try to start from catalog's Pages
    if let Ok(catalog) = doc.catalog() {
        if let Ok(pages_ref) = catalog.get(b"Pages").and_then(Object::as_reference) {
            walk_tree(doc, pages_ref, &mut pages, &mut page_num, &mut visited);
        }
    }

    // 2. Fallback: if pages is still empty, scan all objects conservatively.
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

fn walk_tree(
    doc: &Document,
    node_id: ObjectId,
    pages: &mut BTreeMap<u32, ObjectId>,
    page_num: &mut u32,
    visited: &mut HashSet<ObjectId>,
) {
    if !visited.insert(node_id) {
        // Cycle detected
        return;
    }

    if let Ok(dict) = doc.get_dictionary(node_id) {
        // Heuristic: If it has a Kids array, it's an intermediate Pages node
        if let Ok(kids) = dict.get_deref(b"Kids", doc).and_then(Object::as_array) {
            for kid in kids {
                if let Ok(kid_id) = kid.as_reference() {
                    walk_tree(doc, kid_id, pages, page_num, visited);
                }
            }
        } else {
            // No Kids array. Since we reached it by walking the page tree,
            // it is treated as a leaf Page node.
            pages.insert(*page_num, node_id);
            *page_num += 1;
        }
    }
}

fn is_page_fallback(dict: &Dictionary) -> bool {
    // Must NOT have Kids (otherwise it's a Pages node)
    if dict.has(b"Kids") {
        return false;
    }

    // Explicit Type == Page
    if let Ok(t) = dict.get(b"Type").and_then(Object::as_name) {
        if t.eq_ignore_ascii_case(b"Page") {
            return true;
        }
    }

    // Without explicit Type, require strong evidence: Contents or MediaBox
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
    }

    #[test]
    fn test_missing_type_page() {
        let mut doc = make_doc();

        // Omit Type=Page
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

    #[test]
    fn test_malformed_type_values() {
        let mut doc = make_doc();

        let mut page = LoDictionary::new();
        page.set("Type", Object::Name(b"PAGE".to_vec())); // uppercase
        let page_id = doc.add_object(page);

        let mut pages_node = LoDictionary::new();
        pages_node.set("Type", Object::Name(b"PaGeS".to_vec()));
        pages_node.set("Kids", Object::Array(vec![Object::Reference(page_id)]));
        let pages_id = doc.add_object(pages_node);

        let mut catalog = LoDictionary::new();
        catalog.set("Pages", Object::Reference(pages_id));
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 1);
    }

    #[test]
    fn test_inherited_page_attributes() {
        let mut doc = make_doc();

        // Leaf node completely empty except maybe an ID, relying on being in Kids array
        let page = LoDictionary::new();
        let page_id = doc.add_object(page);

        // Parent provides MediaBox
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

    #[test]
    fn test_circular_kids_references() {
        let mut doc = make_doc();

        let mut page = LoDictionary::new();
        page.set("Type", Object::Name(b"Page".to_vec()));
        let page_id = doc.add_object(page);

        // Create cycle between pages1 and pages2
        let pages1_id = (100, 0);
        let pages2_id = (101, 0);

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

        // Should not stack overflow, and should find the 1 valid page
        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 1);
        assert_eq!(pages[&1], page_id);
    }

    #[test]
    fn test_missing_catalog_pages_entry_fallback() {
        let mut doc = make_doc();

        // No catalog Pages entry.
        let catalog = LoDictionary::new();
        let cat_id = doc.add_object(catalog);
        doc.trailer.set("Root", Object::Reference(cat_id));

        // Create a standalone page dictionary
        let mut page = LoDictionary::new();
        page.set("Type", Object::Name(b"Page".to_vec()));
        let page_id = doc.add_object(page);

        let mut page2 = LoDictionary::new();
        page2.set("Contents", Object::Array(vec![])); // No Type, but has Contents
        let page2_id = doc.add_object(page2);

        let pages = get_pages_tolerant(&doc).unwrap();
        assert_eq!(pages.len(), 2);

        // Order isn't guaranteed for fallback, but both should be there
        let ids: Vec<_> = pages.values().copied().collect();
        assert!(ids.contains(&page_id));
        assert!(ids.contains(&page2_id));
    }
}
