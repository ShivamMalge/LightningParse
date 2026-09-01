"""Slice a chapter out of a large open-licensed textbook into a working fixture.

Real textbook content NEVER enters this repository (NEW_PHASES.md sourcing rule).
This script is committed; its inputs and outputs both live outside the repo, under
$LP_DIAG_CORPUS (default: ../lp-diagnostic-corpus, a sibling of the repo).

Also reports two things Phase 1 needs to know about real books:
  - whether the book carries a /PageLabels number tree
  - the printed label on the first page of the extracted range, so the
    pdf_index -> printed_label offset is known for the slice

Usage:
    python extract_chapter.py --list BOOK.pdf
    python extract_chapter.py --book BOOK.pdf --start-title "Chapter 4" --end-title "Chapter 5" --out NAME.pdf
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pikepdf

CORPUS = Path(os.environ.get("LP_DIAG_CORPUS", Path.home() / "Desktop" / "lp-diagnostic-corpus"))


def page_index_map(pdf: pikepdf.Pdf) -> Dict[object, int]:
    return {p.obj.objgen: i for i, p in enumerate(pdf.pages)}


def outline_entries(pdf: pikepdf.Pdf) -> List[Tuple[str, Optional[int]]]:
    """(title, 0-based page index) for top-level outline entries."""
    idx = page_index_map(pdf)
    out: List[Tuple[str, Optional[int]]] = []
    with pdf.open_outline() as ol:
        for item in ol.root:
            page = None
            try:
                dest = item.destination
                if isinstance(dest, pikepdf.Array) and len(dest):
                    page = idx.get(dest[0].objgen)
                elif item.action is not None and "/D" in item.action:
                    d = item.action["/D"]
                    if isinstance(d, pikepdf.Array) and len(d):
                        page = idx.get(d[0].objgen)
            except Exception:
                pass
            out.append((str(item.title), page))
    return out


def decode_page_labels(pdf: pikepdf.Pdf, n_pages: int) -> Dict[int, str]:
    """Expand a /PageLabels number tree into {1-based pdf index: printed label}."""
    if "/PageLabels" not in pdf.Root:
        return {}
    try:
        nums = pdf.Root.PageLabels.get("/Nums")
        if nums is None:
            return {}
        entries = []
        for i in range(0, len(nums), 2):
            entries.append((int(nums[i]), nums[i + 1]))
    except Exception:
        return {}

    roman = [(1000,"m"),(900,"cm"),(500,"d"),(400,"cd"),(100,"c"),(90,"xc"),
             (50,"l"),(40,"xl"),(10,"x"),(9,"ix"),(5,"v"),(4,"iv"),(1,"i")]

    def to_roman(v: int) -> str:
        s = ""
        for val, sym in roman:
            while v >= val:
                s += sym; v -= val
        return s

    def to_alpha(v: int) -> str:
        s, v = "", v - 1
        while v >= 0:
            s = chr(ord("a") + v % 26) + s
            v = v // 26 - 1
        return s

    out: Dict[int, str] = {}
    for i, (start, d) in enumerate(entries):
        end = entries[i + 1][0] if i + 1 < len(entries) else n_pages
        style = str(d.get("/S")) if d.get("/S") is not None else None
        prefix = str(d.get("/P")) if d.get("/P") is not None else ""
        st = int(d.get("/St")) if d.get("/St") is not None else 1
        for k, pidx in enumerate(range(start, end)):
            v = st + k
            if style == "/D":
                lab = str(v)
            elif style == "/r":
                lab = to_roman(v)
            elif style == "/R":
                lab = to_roman(v).upper()
            elif style == "/a":
                lab = to_alpha(v)
            elif style == "/A":
                lab = to_alpha(v).upper()
            else:
                lab = ""
            out[pidx + 1] = prefix + lab
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book")
    ap.add_argument("--list", dest="list_book")
    ap.add_argument("--start-title")
    ap.add_argument("--end-title")
    ap.add_argument("--out")
    args = ap.parse_args()

    src = Path(args.list_book or args.book)
    if not src.is_absolute():
        src = CORPUS / "openstax" / src
    pdf = pikepdf.open(str(src))
    n = len(pdf.pages)
    labels = decode_page_labels(pdf, n)

    print(f"book        : {src.name}")
    print(f"pages       : {n}")
    print(f"/PageLabels : {'PRESENT' if labels else 'ABSENT'}")
    if labels:
        sample = {k: labels[k] for k in list(labels)[:8]}
        print(f"  first few : {sample}")

    entries = outline_entries(pdf)
    if args.list_book:
        for t, p in entries:
            if p is not None:
                print(f"  p{p+1:<5} {t[:70]}")
        return 0

    starts = [(t, p) for t, p in entries if p is not None and t.startswith(args.start_title)]
    ends = [(t, p) for t, p in entries if p is not None and t.startswith(args.end_title)]
    if not starts or not ends:
        print(f"!! could not resolve titles (start={len(starts)} end={len(ends)})")
        return 1
    s_page, e_page = starts[0][1], ends[0][1]
    print(f"\nslice: '{starts[0][0][:50]}' p{s_page+1} .. p{e_page} ({e_page - s_page} pages)")

    out_pdf = pikepdf.Pdf.new()
    for i in range(s_page, e_page):
        out_pdf.pages.append(pdf.pages[i])

    dest = CORPUS / "fixtures" / args.out
    dest.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.save(str(dest), linearize=False)
    size_mb = dest.stat().st_size / 1048576
    print(f"wrote       : {dest}  ({size_mb:.1f} MB, {len(out_pdf.pages)} pages)")

    if labels:
        first = labels.get(s_page + 1, "?")
        print(f"ground truth: pdf index 1 of the slice == printed label {first!r} "
              f"(offset {s_page + 1} in the full book)")
    else:
        print("ground truth: no /PageLabels in source; printed labels must come from ink")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
