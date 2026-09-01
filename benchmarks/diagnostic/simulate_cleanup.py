"""Pre-ship spot-check for the G4+G5 fix: simulate header/footer tagging and diff.

The open risk before shipping is a REGRESSION: switching the margin band from
content extent to MediaBox NARROWS the top band, so a legitimate running head
sitting in the abandoned strip would stop being caught.

Asserting that risk is low is not enough. This re-implements
`cleanup::detect_headers_footers` in Python, **validates the re-implementation
against the real parser's output**, and only then uses it to predict what the
fix would change.

Configs:
  A  current      : content-extent bands + page-1 fallback   (baseline)
  B  band only    : MediaBox bands      + page-1 fallback    (G4 fix alone)
  C  both fixes   : MediaBox bands + page-1 fallback reduced to its FOOTNOTE
                    branch only (G4 + G5). Keeps the only code path that ever
                    emits section_id "footnote" (cleanup/mod.rs:133).

Diff A->C is the proposed change. Any block that LOSES a furniture tag is a
candidate regression and is printed in full for judgement.

Usage:
    python simulate_cleanup.py
"""

from __future__ import annotations

import math
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from harness import run  # noqa: E402

CORPUS = Path(os.environ.get(
    "LP_DIAG_CORPUS", Path.home() / "Desktop" / "lp-diagnostic-corpus"))

FOOTNOTE_MARKS = ("*", "∗", "†", "‡", "§")


def normalize_text(t: str) -> str:
    """Mirror of cleanup/mod.rs normalize_text: strip ASCII digits, lowercase, trim."""
    return re.sub(r"[0-9]", "", t or "").lower().strip()


def simulate(blocks: List[dict], use_mediabox: bool, page1_fallback: str) -> Dict[Tuple[int, int], str]:
    """Return {(page, block_index): section_id} exactly as cleanup/mod.rs would assign."""
    by_page: Dict[int, List[dict]] = defaultdict(list)
    for b in blocks:
        by_page[b["pdf_page_index"]].append(b)
    total_pages = len(by_page)
    if total_pages == 0:
        return {}
    threshold = math.ceil(total_pages * 0.7)

    def ref_height(page: int) -> float:
        bs = by_page[page]
        if use_mediabox:
            ph = next((b.get("page_height") for b in bs if b.get("page_height")), None)
            if ph:
                return float(ph)
        # content extent: DOCUMENT-wide, as the parser does
        return max(b["bbox"][3] for b in blocks)

    # Cross-page clustering
    top_c: Dict[str, set] = defaultdict(set)
    bot_c: Dict[str, set] = defaultdict(set)
    for page, bs in by_page.items():
        ref = ref_height(page)
        t_cut, b_cut = ref * 0.90, ref * 0.10
        for b in bs:
            nt = normalize_text(b["text"])
            if not nt:
                continue
            if b["bbox"][1] > t_cut:
                top_c[nt].add(page)
            elif b["bbox"][3] < b_cut:
                bot_c[nt].add(page)

    header_texts = {t for t, ps in top_c.items() if len(ps) >= threshold}
    footer_texts = {t for t, ps in bot_c.items() if len(ps) >= threshold}

    out: Dict[Tuple[int, int], str] = {}
    for page, bs in by_page.items():
        ref = ref_height(page)
        t_cut, b_cut = ref * 0.90, ref * 0.10
        page_max_y = max(b["bbox"][3] for b in bs)
        p_top10, p_bot10, p_bot30 = page_max_y * 0.90, page_max_y * 0.10, page_max_y * 0.30

        for b in bs:
            idx = b["block_index_in_reading_order"]
            key = (page, idx)
            out[key] = "body"
            txt = b["text"] or ""
            nt = normalize_text(txt)
            if not nt:
                continue
            if b["bbox"][1] > t_cut and nt in header_texts:
                out[key] = "header"; continue
            if b["bbox"][3] < b_cut and nt in footer_texts:
                out[key] = "footer"; continue
            if page1_fallback != "none" and page == 1:
                if b["bbox"][1] < p_bot30 and txt.startswith(FOOTNOTE_MARKS):
                    out[key] = "footnote"; continue
                # The header/footer half of the fallback is what deletes content:
                # it tags on position alone, with no cross-page corroboration.
                if page1_fallback == "full":
                    if b["bbox"][1] > p_top10:
                        out[key] = "header"; continue
                    if b["bbox"][3] < p_bot10:
                        out[key] = "footer"; continue
    return out


def targets() -> List[str]:
    t = [
        "benchmarks/diagnostic/fixtures/f5a_pagelabels.pdf",
        "benchmarks/corpus/arxiv_twocolumn.pdf",
        "benchmarks/corpus/ieee_template_placeholder.pdf",
        "benchmarks/corpus/digital_word_export.pdf",
        "lightningparse-core/tests/fixtures/tier2/mixed_test.pdf",
    ]
    for f in ("f1_biology_cell_structure.pdf", "f2_physics_vision.pdf"):
        p = CORPUS / "fixtures" / f
        if p.exists():
            t.append(str(p))
    return [x for x in t if Path(x).exists()]


def main() -> int:
    print("=" * 78)
    print("G4+G5 pre-ship spot-check")
    print("=" * 78)

    all_lost, all_gained = [], []
    validation_ok = True

    for path in targets():
        res = run(path, ack_warnings=True)
        blocks = res["blocks"]
        if not blocks:
            continue
        actual = {(b["pdf_page_index"], b["block_index_in_reading_order"]):
                  b["section_id"] for b in blocks}
        by_key = {(b["pdf_page_index"], b["block_index_in_reading_order"]): b for b in blocks}

        A = simulate(blocks, use_mediabox=False, page1_fallback="full")
        C = simulate(blocks, use_mediabox=True, page1_fallback="footnote_only")

        # ---- validate the simulator against the real parser ----
        mismatches = [k for k in actual if actual[k] != A.get(k)]
        status = "OK" if not mismatches else f"MISMATCH x{len(mismatches)}"
        if mismatches:
            validation_ok = False
        print(f"\n### {Path(path).name}  ({res['page_count']}p, {len(blocks)} blocks)")
        print(f"  simulator vs real parser (config A): {status}")
        if mismatches[:3]:
            for k in mismatches[:3]:
                b = by_key[k]
                print(f"     p{k[0]} idx{k[1]}: real={actual[k]} sim={A.get(k)} {b['text'][:40]!r}")

        FURN = ("header", "footer", "footnote")
        lost = [k for k in actual if A.get(k) in FURN and C.get(k) not in FURN]
        gained = [k for k in actual if A.get(k) not in FURN and C.get(k) in FURN]
        print(f"  furniture tags: A={sum(1 for v in A.values() if v in FURN)}  "
              f"C={sum(1 for v in C.values() if v in FURN)}")
        print(f"  LOST furniture tag (regression risk): {len(lost)}")
        for k in lost:
            b = by_key[k]
            print(f"     p{k[0]} y={b['bbox'][1]:.0f}-{b['bbox'][3]:.0f} "
                  f"was={A[k]} -> body   {b['text'][:66]!r}")
            all_lost.append((Path(path).name, k, b, A[k]))
        print(f"  GAINED furniture tag: {len(gained)}")
        for k in gained[:8]:
            b = by_key[k]
            print(f"     p{k[0]} y={b['bbox'][1]:.0f}-{b['bbox'][3]:.0f} "
                  f"body -> {C[k]}   {b['text'][:66]!r}")
            all_gained.append((Path(path).name, k, b, C[k]))

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  simulator faithful to parser on every fixture : {'YES' if validation_ok else 'NO — DO NOT TRUST THE DIFF'}")
    print(f"  blocks that LOSE a furniture tag              : {len(all_lost)}")
    print(f"  blocks that GAIN a furniture tag              : {len(all_gained)}")
    print()
    print("  Every LOST block must be judged by eye: was it real page furniture")
    print("  (a regression) or body content wrongly deleted today (the fix working)?")
    return 0 if validation_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
