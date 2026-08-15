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
        println!("Usage: check_do_ops <pdf>");
        return;
    }
    let doc = Document::load(&args[1]).unwrap();
    let mut total_do_ops = 0;
    let mut form_xobjects = 0;
    let mut image_xobjects = 0;

    for (page_num, page_id) in lightningparse::extract::page_tree::get_pages_tolerant(&doc).unwrap()
    {
        let page = doc.get_object(page_id).unwrap().as_dict().unwrap();

        let res_obj_opt = page.get(b"Resources").ok().or_else(|| {
            let parent_ref = page.get(b"Parent").ok()?;
            let parent = resolve(&doc, parent_ref).ok()?;
            let parent_dict = parent.as_dict().ok()?;
            parent_dict.get(b"Resources").ok()
        });

        let mut xobj_dict = None;
        if let Some(res_obj) = res_obj_opt {
            if let Ok(res) = resolve(&doc, res_obj).and_then(|o| o.as_dict().map_err(|_| ())) {
                if let Ok(xobj_obj) = res.get(b"XObject") {
                    if let Ok(x) = resolve(&doc, xobj_obj).and_then(|o| o.as_dict().map_err(|_| ()))
                    {
                        xobj_dict = Some(x);
                    }
                }
            }
        }

        if let Ok(content_data) = doc.get_page_content(page_id) {
            if let Ok(content) = lopdf::content::Content::decode(&content_data) {
                for op in content.operations.iter() {
                    if op.operator == "Do" {
                        total_do_ops += 1;
                        if let Some(name_obj) = op.operands.first() {
                            if let Ok(name) = name_obj.as_name() {
                                if let Some(xobjs) = xobj_dict {
                                    if let Ok(obj_ref) = xobjs.get(name) {
                                        if let Ok(stream) = resolve(&doc, obj_ref)
                                            .and_then(|o| o.as_stream().map_err(|_| ()))
                                        {
                                            if stream
                                                .dict
                                                .get(b"Subtype")
                                                .and_then(|o| o.as_name())
                                                .unwrap_or(b"")
                                                == b"Form"
                                            {
                                                form_xobjects += 1;
                                                println!("Page {}: Do operator calls Form XObject '{:?}'", page_num, String::from_utf8_lossy(name));
                                            } else {
                                                image_xobjects += 1;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    println!("Total 'Do' operations: {}", total_do_ops);
    println!("  -> Image XObjects: {}", image_xobjects);
    println!("  -> Form XObjects: {}", form_xobjects);
}
