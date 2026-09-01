"""Sweep every available PDF through the Phase 1 / Phase 2 measurement machinery.

Purpose: de-risk the Tier A harvester and the /PageLabels finding on REAL
documents before real textbook fixtures are sourced. The repo's existing corpus
is not textbooks, but it is real PDFs with real page furniture — enough to show
whether the harvester's 20/20 on synthetic F5a survives contact with anything
that was not generated to be easy.

Diagnosis only. Reports what is; changes nothing.

Usage:
    python sweep_corpus.py [--min-pages 2]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent))

from harness import run, UnacknowledgedWarnings  # noqa: E402
from measure_phase1 import (  # noqa: E402
    harvest_labels,
    harvest_labels_naive,
    monotonicity_check,
    probe_page_labels,
)

ROOTS = [
    Path("benchmarks/corpus"),
    Path("lightningparse-core/tests/fixtures"),
    Path("benchmarks/diagnostic/fixtures"),
]


def discover() -> List[Path]:
    out: List[Path] = []
    for root in ROOTS:
        if root.exists():
            out.extend(sorted(root.rglob("*.pdf")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-pages", type=int, default=2,
                    help="skip single-page files; page furniture needs >1 page to cluster")
    args = ap.parse_args()

    pdfs = discover()
    print(f"discovered {len(pdfs)} PDFs\n")

    hdr = f"{'fixture':<38} {'pg':>3} {'blk':>4} {'tier':<8} {'wrn':>3} {'PgLbl':>5} {'harvest':>8} {'mono':>4}"
    print(hdr)
    print("-" * len(hdr))

    rows = []
    for pdf in pdfs:
        try:
            probe = probe_page_labels(str(pdf))
            has_labels = "YES" if probe.get("present") else "no"
        except Exception:
            has_labels = "err"

        try:
            res = run(str(pdf), ack_warnings=True)
        except Exception as e:
            print(f"{pdf.name:<38} {'-':>3} {'-':>4} {'ERROR':<8} {type(e).__name__}")
            continue

        npages = res["page_count"] or 0
        if npages < args.min_pages:
            continue

        blocks = res["blocks"]
        harvested = harvest_labels(blocks)
        naive = harvest_labels_naive(blocks)
        issues = monotonicity_check(harvested)
        sec = Counter(b["section_id"] for b in blocks)

        print(f"{pdf.name:<38} {npages:>3} {len(blocks):>4} {res['tier']:<8} "
              f"{len(res['warnings']):>3} {has_labels:>5} "
              f"{f'{len(harvested)}/{npages}':>8} {len(issues):>4}"
              f"   (naive {len(naive)}/{npages})")

        rows.append({
            "fixture": pdf.name,
            "pages": npages,
            "blocks": len(blocks),
            "tier": res["tier"],
            "warnings": res["warnings"],
            "page_labels_present": has_labels,
            "harvested": {str(k): v for k, v in sorted(harvested.items())},
            "naive": {str(k): v for k, v in sorted(naive.items())},
            "monotonicity_breaks": issues,
            "section_id_counts": dict(sec),
        })

    print("\n" + "=" * 78)
    print("DETAIL")
    print("=" * 78)
    for r in rows:
        print(f"\n{r['fixture']}  ({r['pages']}p, tier={r['tier']})")
        print(f"  section_id distribution : {r['section_id_counts']}")
        print(f"  labels (slot-based)     : {r['harvested'] or '(none)'}")
        print(f"  labels (naive, for ref) : {r['naive'] or '(none)'}")
        if r["monotonicity_breaks"]:
            print("  monotonicity breaks     :")
            for i in r["monotonicity_breaks"]:
                print(f"    - {i}")
        if r["warnings"]:
            print(f"  warnings ({len(r['warnings'])}):")
            for w in r["warnings"]:
                print(f"    ! {w}")

    print("\n" + "=" * 78)
    print("AGGREGATE")
    print("=" * 78)
    n = len(rows)
    with_labels = sum(1 for r in rows if r["page_labels_present"] == "YES")
    print(f"  multi-page documents measured      : {n}")
    print(f"  carrying a /PageLabels tree        : {with_labels}/{n}")
    full = sum(1 for r in rows if len(r["harvested"]) == r["pages"])
    partial = sum(1 for r in rows if 0 < len(r["harvested"]) < r["pages"])
    none_ = sum(1 for r in rows if not r["harvested"])
    print(f"  Tier A harvested EVERY page        : {full}/{n}")
    print(f"  Tier A harvested SOME pages        : {partial}/{n}")
    print(f"  Tier A harvested NOTHING           : {none_}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
