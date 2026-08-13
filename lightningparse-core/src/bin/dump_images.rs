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
        println!("Usage: dump_images <pdf>");
        return;
    }
    let doc = Document::load(&args[1]).unwrap();
    for (page_num, page_id) in lightningparse::extract::page_tree::get_pages_tolerant(&doc).unwrap() {
        let page = doc.get_object(page_id).unwrap().as_dict().unwrap();
        let res_obj_opt = page.get(b"Resources").ok().or_else(|| {
            let parent_ref = page.get(b"Parent").ok()?;
            let parent = resolve(&doc, parent_ref).ok()?;
            let parent_dict = parent.as_dict().ok()?;
            parent_dict.get(b"Resources").ok()
        });

        if let Some(res_obj) = res_obj_opt {
            if let Ok(res) = resolve(&doc, res_obj).and_then(|o| o.as_dict().map_err(|_| ())) {
                if let Ok(xobj_obj) = res.get(b"XObject") {
                    if let Ok(xobj) =
                        resolve(&doc, xobj_obj).and_then(|o| o.as_dict().map_err(|_| ()))
                    {
                        for (name, obj) in xobj.iter() {
                            let obj_ref = obj.as_reference().unwrap();
                            let stream = doc.get_object(obj_ref).unwrap().as_stream().unwrap();
                            let dict = &stream.dict;
                            if dict
                                .get(b"Subtype")
                                .and_then(|o| o.as_name())
                                .unwrap_or(b"")
                                == b"Image"
                            {
                                println!(
                                    "Page {} Image {:?}:",
                                    page_num,
                                    String::from_utf8_lossy(name)
                                );
                                println!("  Filter: {:?}", dict.get(b"Filter"));
                                println!("  Width: {:?}", dict.get(b"Width"));
                                println!("  Height: {:?}", dict.get(b"Height"));
                                println!("  ColorSpace: {:?}", dict.get(b"ColorSpace"));
                                println!("  BitsPerComponent: {:?}", dict.get(b"BitsPerComponent"));
                            }
                        }
                    }
                }
            }
        }
    }
}
