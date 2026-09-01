"""NEW_PHASES.md Phase 1 — Citation Fidelity A: printed label vs. PDF index.

Measures, for a fixture with known ground truth:
  1. what page number LightningParse would cause Aakar to cite  (= pdf_page_index)
  2. what printed label a human actually reads on that page      (= ground truth)
  3. whether the PDF carries a /PageLabels tree, and whether it is used
  4. whether a Tier A harvester could recover the label from margin-band ink

Diagnosis only. Reports what is; changes nothing.

Usage:
    python measure_phase1.py --blocks BLOCKS.jsonl --pdf FIXTURE.pdf
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.I)
ARABIC_RE = re.compile(r"^\d+$")


# ── ground truth ────────────────────────────────────────────────

def f5a_ground_truth(total: int = 20, front: int = 6) -> Dict[int, str]:
    """F5a's known structure: roman i..vi for front matter, arabic restarting at 1."""
    roman = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
    gt = {}
    for i in range(1, total + 1):
        gt[i] = roman[i - 1] if i <= front else str(i - front)
    return gt


def roman_to_int(s: str) -> Optional[int]:
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    s = s.lower()
    if not s or not ROMAN_RE.match(s):
        return None
    total, prev = 0, 0
    for ch in reversed(s):
        v = vals.get(ch)
        if v is None:
            return None
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def label_to_int(label: str) -> Optional[int]:
    if ARABIC_RE.match(label):
        return int(label)
    return roman_to_int(label)


# ── /PageLabels probe ───────────────────────────────────────────

def probe_page_labels(pdf_path: str) -> dict:
    """Is a /PageLabels tree present in the file, independent of the parser?"""
    try:
        import pikepdf
    except ImportError:
        return {"available": False, "reason": "pikepdf not installed"}

    pdf = pikepdf.open(pdf_path)
    if "/PageLabels" not in pdf.Root:
        return {"available": True, "present": False}
    return {
        "available": True,
        "present": True,
        "raw": str(pdf.Root.PageLabels),
        "page_count": len(pdf.pages),
    }


# ── Tier A harvester ────────────────────────────────────────────

CANONICAL_ROMAN_RE = re.compile(
    r"^m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.I
)

# Front matter rarely runs past 'l' (50). Capping the accepted roman value is
# what rejects real words that happen to be valid numerals — 'dv' (505),
# 'mix' (1009). Canonicalisation alone does NOT reject those; measured, not assumed.
MAX_PLAUSIBLE_ROMAN = 50


def _is_label_token(txt: str) -> bool:
    if ARABIC_RE.match(txt):
        return len(txt) <= 4          # a page label is not a 5-digit number
    if CANONICAL_ROMAN_RE.match(txt):
        v = roman_to_int(txt)
        return v is not None and 0 < v <= MAX_PLAUSIBLE_ROMAN
    return False


def harvest_labels_naive(blocks: List[dict], band_frac: float = 0.12) -> Dict[int, str]:
    """First matching numeral in either margin band. Kept to show why it is not enough.

    Measured failure on `arxiv_twocolumn.pdf`: harvests table-cell exponents
    ('2' on p6, '20' on p8) and a math variable ('dv' = d_v on p9) instead of
    the real folio, because the band is a fraction of CONTENT extent and a page
    whose table starts high puts real content inside the band.
    """
    by_page: Dict[int, List[dict]] = defaultdict(list)
    for b in blocks:
        by_page[b["pdf_page_index"]].append(b)

    out: Dict[int, str] = {}
    for page, bs in by_page.items():
        max_y = max(b["bbox"][3] for b in bs)
        top_cut, bot_cut = max_y * (1.0 - band_frac), max_y * band_frac
        for b in bs:
            txt = (b["text"] or "").strip()
            if not txt:
                continue
            if (b["bbox"][1] > top_cut or b["bbox"][3] < bot_cut) and (
                ARABIC_RE.match(txt) or ROMAN_RE.match(txt)
            ):
                out[page] = txt
                break
    return out


def harvest_labels(blocks: List[dict], band_frac: float = 0.12) -> Dict[int, str]:
    """Recover the printed label from margin-band ink, using POSITION CONSISTENCY.

    A folio sits in the same place on every page; a table cell that happens to be
    a numeral does not. So rather than taking the first numeral in a band, this
    collects every candidate, groups them into quantised position 'slots', and
    keeps only the single slot that behaves like a folio: present on the most
    pages, and forming the longest monotonic run.

    This replaced a naive first-match harvester after that one scored 13/15
    'coverage' on a real paper while getting three of those pages wrong — the
    slot-based version is what makes Tier A ground truth rather than noise.
    """
    by_page: Dict[int, List[dict]] = defaultdict(list)
    for b in blocks:
        by_page[b["pdf_page_index"]].append(b)

    # 1. collect candidates, keyed by quantised position
    slots: Dict[tuple, Dict[int, str]] = defaultdict(dict)
    for page, bs in by_page.items():
        # Prefer real page geometry over content extent. A content-derived band
        # collapses on short pages: arxiv_twocolumn.pdf p3's content reaches only
        # y=390, so a 12% content band ends at y=47 and excludes a folio sitting
        # at y=52. Measured, not hypothesised. Falls back to content extent only
        # when the harness could not read MediaBox.
        page_h = next((b.get("page_height") for b in bs if b.get("page_height")), None)
        ref_y = page_h if page_h else max(b["bbox"][3] for b in bs)
        top_cut, bot_cut = ref_y * (1.0 - band_frac), ref_y * band_frac
        for b in bs:
            txt = (b["text"] or "").strip()
            if not txt or not _is_label_token(txt):
                continue
            y0, y1 = b["bbox"][1], b["bbox"][3]
            if y0 > top_cut:
                band = "top"
            elif y1 < bot_cut:
                band = "bottom"
            else:
                continue
            y_slot = round(((y0 + y1) / 2.0) / 12.0)
            key = (band, y_slot)
            slots[key].setdefault(page, txt)

    if not slots:
        return {}

    # 2. score each slot: pages covered, and longest monotonic +1 run
    def score(cand: Dict[int, str]) -> tuple:
        pages = sorted(cand)
        vals = [label_to_int(cand[p]) for p in pages]
        best = run = 1 if vals else 0
        for i in range(1, len(vals)):
            a, b_ = vals[i - 1], vals[i]
            if a is not None and b_ is not None and b_ == a + 1:
                run += 1
                best = max(best, run)
            else:
                run = 1
        return (best, len(cand))

    best_key = max(slots, key=lambda k: score(slots[k]))
    return dict(sorted(slots[best_key].items()))


def monotonicity_check(labels: Dict[int, str]) -> List[str]:
    """A real book's labels are monotonic within a numbering run. Report breaks."""
    issues = []
    ordered = sorted(labels.items())
    prev_page, prev_val, prev_kind = None, None, None
    for page, lab in ordered:
        kind = "arabic" if ARABIC_RE.match(lab) else "roman"
        val = label_to_int(lab)
        if prev_val is not None and kind == prev_kind:
            if val is not None and val != prev_val + 1:
                issues.append(
                    f"page {prev_page}->{page}: {prev_kind} label {prev_val}->{val} (not +1)"
                )
        prev_page, prev_val, prev_kind = page, val, kind
    return issues


# ── main measurement ────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--front-matter", type=int, default=6)
    ap.add_argument("--total", type=int, default=20)
    args = ap.parse_args()

    blocks = [json.loads(l) for l in open(args.blocks, encoding="utf-8")]
    gt = f5a_ground_truth(args.total, args.front_matter)

    print("=" * 72)
    print("PHASE 1 — Citation Fidelity A: printed label vs PDF index")
    print(f"fixture: {Path(args.pdf).name}")
    print("=" * 72)

    # 1. schema check
    keys = set()
    for b in blocks:
        keys |= set(b.keys())
    label_fields = [
        k for k in keys
        if any(t in k.lower() for t in ("label", "printed", "folio"))
    ]
    print("\n[1] Does the output carry any printed-page concept?")
    print(f"    block fields: {sorted(keys)}")
    print(f"    printed-label fields found: {label_fields or 'NONE'}")

    # 2. /PageLabels probe
    probe = probe_page_labels(args.pdf)
    print("\n[2] /PageLabels tree in the file?")
    print(f"    present in PDF : {probe.get('present')}")
    if probe.get("present"):
        print(f"    raw            : {probe['raw'][:120]}")
    print("    used by parser : NO  (no printed-label field exists in output)")

    # 3. the actual citation error
    cited = sorted({b["pdf_page_index"] for b in blocks})
    print("\n[3] What Aakar would cite vs. what the student reads")
    print(f"    {'pdf_idx':>7} | {'cited':>5} | {'printed':>7} | match")
    print(f"    {'-'*7}-+-{'-'*5}-+-{'-'*7}-+------")
    correct = 0
    front_correct = 0
    body_correct = 0
    for p in cited:
        printed = gt.get(p, "?")
        ok = str(p) == printed
        correct += ok
        if p <= args.front_matter:
            front_correct += ok
        else:
            body_correct += ok
        print(f"    {p:>7} | {p:>5} | {printed:>7} | {'OK' if ok else 'WRONG'}")

    n = len(cited)
    nbody = n - args.front_matter
    print(f"\n    overall correct      : {correct}/{n}")
    print(f"    front-matter correct : {front_correct}/{args.front_matter}")
    print(f"    body-page correct    : {body_correct}/{nbody}")

    # 4. offset distribution
    print("\n[4] Offset distribution (cited - printed), by numbering run")
    runs: Dict[str, List[int]] = defaultdict(list)
    for p in cited:
        printed = gt.get(p)
        v = label_to_int(printed) if printed else None
        if v is None:
            continue
        kind = "roman(front)" if p <= args.front_matter else "arabic(body)"
        runs[kind].append(p - v)
    for kind, offs in runs.items():
        uniq = sorted(set(offs))
        const = "CONSTANT" if len(uniq) == 1 else "VARIABLE"
        print(f"    {kind:<14}: offsets={uniq}  -> {const}")
    all_off = sorted({o for offs in runs.values() for o in offs})
    print(f"    across whole document: offsets={all_off} -> "
          f"{'CONSTANT' if len(all_off)==1 else 'NOT CONSTANT'}")

    # 5. Tier A harvester
    print("\n[5] Tier A harvester (recover label from margin-band ink)")
    harvested = harvest_labels(blocks)
    hit = sum(1 for p in cited if harvested.get(p) == gt.get(p))
    print(f"    pages harvested      : {len(harvested)}/{n}")
    print(f"    harvested == truth   : {hit}/{n}")
    missing = [p for p in cited if p not in harvested]
    if missing:
        print(f"    pages with no label harvested: {missing}")
    issues = monotonicity_check(harvested)
    print(f"    monotonicity breaks  : {len(issues)}")
    for i in issues:
        print(f"      - {i}")

    # 6. where the label block ended up (feeds Phase 2)
    print("\n[6] Fate of the printed-label block (Phase 2 preview)")
    fate: Dict[str, int] = defaultdict(int)
    for b in blocks:
        txt = (b["text"] or "").strip()
        p = b["pdf_page_index"]
        if txt and txt == gt.get(p):
            fate[b["section_id"]] += 1
    for sec, cnt in sorted(fate.items()):
        note = "  <-- DROPPED by chunker" if sec in ("header", "footer", "footnote") else "  <-- survives into chunks"
        print(f"    section_id={sec:<8}: {cnt} pages{note}")

    print("\n" + "=" * 72)
    print("BARS (set before running, per NEW_PHASES.md)")
    print(f"  digital body pages -> correct printed label : "
          f"{body_correct}/{nbody} = {100.0*body_correct/nbody:.0f}%  (bar 100%)  "
          f"{'PASS' if body_correct==nbody else 'FAIL'}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
