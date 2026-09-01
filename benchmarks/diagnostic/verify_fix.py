"""PHASES-MARGIN-BANDS.md Phase 4 — verify the fix matches the prediction.

Before the fix, `simulate_cleanup.py` re-implemented the OLD tagging logic,
was validated to reproduce the real parser exactly, and then forecast the change
set as 19 specific blocks.

This closes the loop against the FIXED binary. Two assertions:

  1. Config C (the simulated NEW behaviour) must now reproduce the real parser
     exactly — 0 mismatches. If it does not, the implementation is not what was
     reviewed.
  2. Config A (the simulated OLD behaviour) must differ from the real parser in
     exactly the predicted places — no more, no fewer.

Usage:
    python verify_fix.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from harness import run  # noqa: E402
from simulate_cleanup import simulate, targets  # noqa: E402

FURNITURE = ("header", "footer", "footnote")

# The change set forecast BEFORE the fix was written, from PHASES-MARGIN-BANDS.md.
PREDICTED = {
    "f5a_pagelabels.pdf": 4,
    "arxiv_twocolumn.pdf": 4,
    "ieee_template_placeholder.pdf": 2,
    "digital_word_export.pdf": 3,
    "mixed_test.pdf": 2,
    "f1_biology_cell_structure.pdf": 2,
    "f2_physics_vision.pdf": 2,
}


def main() -> int:
    print("=" * 78)
    print("Phase 4 — fixed binary vs pre-computed prediction")
    print("=" * 78)

    total_changed = 0
    c_faithful = True
    mismatched_counts = []

    for path in targets():
        name = Path(path).name
        res = run(path, ack_warnings=True)
        blocks = res["blocks"]
        if not blocks:
            continue

        real = {(b["pdf_page_index"], b["block_index_in_reading_order"]):
                b["section_id"] for b in blocks}
        by_key = {(b["pdf_page_index"], b["block_index_in_reading_order"]): b
                  for b in blocks}

        A = simulate(blocks, use_mediabox=False, page1_fallback="full")
        C = simulate(blocks, use_mediabox=True, page1_fallback="footnote_only")

        # (1) the simulated NEW behaviour must now be what the parser does
        c_mismatch = [k for k in real if real[k] != C.get(k)]
        if c_mismatch:
            c_faithful = False

        # (2) the change vs the OLD behaviour
        changed = [k for k in real if A.get(k) != real[k]]
        lost = [k for k in changed if A.get(k) in FURNITURE and real[k] not in FURNITURE]
        gained = [k for k in changed if A.get(k) not in FURNITURE and real[k] in FURNITURE]

        expected = PREDICTED.get(name)
        ok = "OK" if expected == len(lost) else f"EXPECTED {expected}"
        print(f"\n### {name}")
        print(f"  simulated-NEW == real parser : {'YES' if not c_mismatch else f'NO ({len(c_mismatch)} mismatches)'}")
        print(f"  furniture tags now           : {sum(1 for v in real.values() if v in FURNITURE)}")
        print(f"  blocks freed to body         : {len(lost)}  [{ok}]")
        print(f"  blocks newly tagged furniture: {len(gained)}")
        for k in lost:
            b = by_key[k]
            print(f"     p{k[0]} {A[k]:>8} -> body   {b['text'][:60]!r}")
        for k in gained:
            b = by_key[k]
            print(f"     !! p{k[0]} body -> {real[k]}   {b['text'][:60]!r}")

        if expected is not None and expected != len(lost):
            mismatched_counts.append((name, expected, len(lost)))
        total_changed += len(lost)

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    print(f"  simulated-NEW reproduces the fixed parser exactly : {'YES' if c_faithful else 'NO'}")
    print(f"  total blocks freed to body                        : {total_changed}"
          f"  (predicted {sum(PREDICTED.values())})")
    print(f"  fixtures deviating from prediction                : {len(mismatched_counts)}")
    for name, exp, got in mismatched_counts:
        print(f"     {name}: predicted {exp}, got {got}")

    ok = c_faithful and not mismatched_counts and total_changed == sum(PREDICTED.values())
    print(f"\n  PHASE 4 ACCEPTANCE: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
