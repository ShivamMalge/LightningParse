use lopdf::{Document, Object};
use std::env;

fn resolve<'a>(doc: &'a Document, obj: &'a Object) -> Result<&'a Object, ()> {
    match obj {
        Object::Reference(id) => doc.get_object(*id).map_err(|_| ()),
        _ => Ok(obj),
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        println!("Usage: dump_fonts <pdf>");
        return;
    }
    let doc = Document::load(&args[1]).unwrap();
    let pages = lightningparse::extract::page_tree::get_pages_tolerant(&doc).unwrap();

    // Just look at page 1
    if let Some(&page_id) = pages.get(&1) {
        let page = doc.get_object(page_id).unwrap().as_dict().unwrap();

        let res_obj = page.get(b"Resources").unwrap();
        let res = resolve(&doc, res_obj).unwrap().as_dict().unwrap();

        if let Ok(font_obj) = res.get(b"Font") {
            let fonts = resolve(&doc, font_obj).unwrap().as_dict().unwrap();
            for (name, obj) in fonts.iter() {
                let font_dict = resolve(&doc, obj).unwrap().as_dict().unwrap();
                println!("Font {:?}:", String::from_utf8_lossy(name));
                println!(
                    "  Type: {:?}",
                    font_dict.get(b"Type").map(|o| resolve(&doc, o).unwrap())
                );
                println!(
                    "  Subtype: {:?}",
                    font_dict.get(b"Subtype").map(|o| resolve(&doc, o).unwrap())
                );
                println!(
                    "  BaseFont: {:?}",
                    font_dict
                        .get(b"BaseFont")
                        .map(|o| resolve(&doc, o).unwrap())
                );
                println!(
                    "  FirstChar: {:?}",
                    font_dict
                        .get(b"FirstChar")
                        .map(|o| resolve(&doc, o).unwrap())
                );
                println!(
                    "  LastChar: {:?}",
                    font_dict
                        .get(b"LastChar")
                        .map(|o| resolve(&doc, o).unwrap())
                );

                if let Ok(w_obj) = font_dict.get(b"Widths") {
                    let w = resolve(&doc, w_obj).unwrap().as_array().unwrap();
                    println!("  Widths len: {}", w.len());
                } else {
                    println!("  Widths: None");
                }

                if let Ok(desc_obj) = font_dict.get(b"DescendantFonts") {
                    let desc_arr = resolve(&doc, desc_obj).unwrap().as_array().unwrap();
                    let desc_dict = resolve(&doc, &desc_arr[0]).unwrap().as_dict().unwrap();
                    println!(
                        "  DescendantFont Subtype: {:?}",
                        desc_dict.get(b"Subtype").map(|o| resolve(&doc, o).unwrap())
                    );
                    if let Ok(w_obj) = desc_dict.get(b"W") {
                        let w = resolve(&doc, w_obj).unwrap().as_array().unwrap();
                        println!("  CID W array len: {}", w.len());
                    }
                }
            }
        }
    }
}
