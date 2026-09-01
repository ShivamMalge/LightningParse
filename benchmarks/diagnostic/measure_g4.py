"""Quantify G4 — margin bands derived from CONTENT extent instead of page geometry.

G4 (NEW_PHASES.md): `detect_headers_footers` computes its top/bottom margin bands
from `global_max_y`, the maximum block extent across the WHOLE document, rather
than from each page's MediaBox. Two consequences, both measurable:

  A. OVER-REACH. If content does not reach the top of the page, the "top 10%"
     band starts lower than the real margin and can swallow body content. A block
     so tagged is then DELETED by the chunker (chunker.py:33), so this is silent
     content loss, not merely a mislabel.

  B. CROSS-PAGE COUPLING. `global_max_y` is a single document-wide number, so one
     unusually tall page moves the band on every other page.

This measures both against real documents. Diagnosis only; changes nothing.

Usage:
    python measure_g4.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent))

from harness import run  # noqa: E402

BAND = 0.10  # the parser's own fraction, cleanup/mod.rs

TARGETS = [
    "benchmarks/diagnostic/fixtures/f5a_pagelabels.pdf",
    "benchmarks/corpus/arxiv_twocolumn.pdf",
    "benchmarks/corpus/ieee_template_placeholder.pdf",
    "benchmarks/corpus/digital_word_export.pdf",
]


def analyse(path: str) -> dict:
    res = run(path, ack_warnings=True)
    blocks = res["blocks"]
    if not blocks:
        return {}

    by_page: Dict[int, List[dict]] = defaultdict(list)
    for b in blocks:
        by_page[b["pdf_page_index"]].append(b)

    # The parser's reference: ONE number for the whole document.
    global_max_y = max(b["bbox"][3] for b in blocks)
    parser_top = global_max_y * (1.0 - BAND)
    parser_bot = global_max_y * BAND

    page_heights = {p: next((b.get("page_height") for b in bs if b.get("page_height")), None)
                    for p, bs in by_page.items()}

    over_reach = []      # tagged furniture, but outside a MediaBox-derived band
    band_deltas = {}

    for p, bs in sorted(by_page.items()):
        ph = page_heights.get(p)
        if not ph:
            continue
        geo_top, geo_bot = ph * (1.0 - BAND), ph * BAND
        band_deltas[p] = (parser_top, geo_top, parser_top - geo_top)

        for b in bs:
            if b["section_id"] not in ("header", "footer"):
                continue
            y0, y1 = b["bbox"][1], b["bbox"][3]
            in_geo_band = (y0 > geo_top) or (y1 < geo_bot)
            if not in_geo_band:
                # Attribute to the code path that could have tagged it. These use
                # DIFFERENT reference heights, so conflating them inflates G4:
                #   page 1  -> page-1-only fallback, `page_top_10 = page_max_y*0.90`
                #             (PER-PAGE content extent)            = G5
                #   page 2+ -> cross-page band, `top_band_threshold = global_max_y*0.90`
                #             (DOCUMENT-WIDE content extent)       = G4
                mechanism = "G5 (page-1 fallback)" if p == 1 else "G4 (cross-page band)"
                over_reach.append({
                    "page": p, "y0": y0, "y1": y1,
                    "section_id": b["section_id"],
                    "text": (b["text"] or "")[:60],
                    "geo_top": geo_top, "parser_top": parser_top,
                    "mechanism": mechanism,
                })

    distinct_heights = sorted({h for h in page_heights.values() if h})
    return {
        "fixture": Path(path).name,
        "pages": len(by_page),
        "blocks": len(blocks),
        "global_max_y": global_max_y,
        "parser_top": parser_top,
        "parser_bot": parser_bot,
        "distinct_page_heights": distinct_heights,
        "band_deltas": band_deltas,
        "over_reach": over_reach,
        "tagged_furniture": sum(1 for b in blocks if b["section_id"] in ("header", "footer")),
    }


def main() -> int:
    print("=" * 78)
    print("G4 — margin bands from CONTENT extent vs PAGE geometry")
    print("=" * 78)

    total_over = 0
    by_mech: dict = {}
    for t in TARGETS:
        if not Path(t).exists():
            continue
        r = analyse(t)
        if not r:
            continue
        print(f"\n### {r['fixture']}  ({r['pages']}p, {r['blocks']} blocks)")
        print(f"  global_max_y (parser's reference) : {r['global_max_y']:.1f}")
        print(f"  distinct MediaBox heights         : {[round(h,1) for h in r['distinct_page_heights']]}")
        print(f"  parser top band starts at         : {r['parser_top']:.1f}")
        gt = {p: v[1] for p, v in r["band_deltas"].items()}
        if gt:
            uniq = sorted({round(v, 1) for v in gt.values()})
            print(f"  geometry top band would start at  : {uniq}")
            worst = max(r["band_deltas"].values(), key=lambda v: abs(v[2]))
            print(f"  worst band displacement           : {worst[2]:+.1f} pt")
        print(f"  blocks tagged header/footer       : {r['tagged_furniture']}")
        print(f"  OF THOSE, outside a geometry band : {len(r['over_reach'])}  <-- G4 over-reach")
        for o in r["over_reach"]:
            print(f"      p{o['page']} y={o['y0']:.0f}-{o['y1']:.0f} "
                  f"tagged={o['section_id']} [{o['mechanism']}] "
                  f"{o['text']!r}")
        total_over += len(r["over_reach"])
        for m in ("G4 (cross-page band)", "G5 (page-1 fallback)"):
            c = sum(1 for o in r["over_reach"] if o["mechanism"] == m)
            if c:
                by_mech[m] = by_mech.get(m, 0) + c

    print("\n" + "=" * 78)
    print(f"TOTAL over-reach blocks across corpus: {total_over}")
    for m, c in sorted(by_mech.items()):
        print(f"   {m:<24}: {c}")
    print("Each is real content tagged as page furniture, and therefore dropped")
    print("by the chunker before retrieval (chunker.py:33).")
    print("")
    print("Both mechanisms share one root cause: the band is a fraction of CONTENT")
    print("extent, never of MediaBox. They differ only in which content extent —")
    print("document-wide (G4) or per-page (G5).")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
