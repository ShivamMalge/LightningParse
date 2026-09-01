"""Diagnostic harness for NEW_PHASES.md.

Exists because `benchmarks/benchmark.py` is structurally incapable of surfacing
the failures NEW_PHASES.md hunts (finding G10): it reads metadata.tier and
metadata.page_count and never reads metadata.warnings — the exact omission that
turned a known ASCII85 limitation into a phantom "quality problem" in an earlier
session.

So this harness does three things benchmark.py does not:
  1. emits one record per BLOCK, carrying section_id / block_role / source / bbox
     / reading-order index, not just aggregate counts;
  2. surfaces metadata.warnings verbatim;
  3. REFUSES TO REPORT if warnings are present and not explicitly acknowledged.
     Ignoring a warning has to be a deliberate act, not a default.

Usage:
    python harness.py FIXTURE.pdf [--jsonl OUT.jsonl] [--ack-warnings] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


class UnacknowledgedWarnings(RuntimeError):
    """Raised when a parse emitted warnings and the caller did not acknowledge them."""


def parse(pdf_path: str) -> Dict[str, Any]:
    import lightningparse

    return json.loads(lightningparse.parse_pdf(pdf_path))


def page_geometry(pdf_path: str) -> Dict[int, Dict[str, float]]:
    """Per-page MediaBox dimensions, read independently of the parser.

    The parser's output carries no page geometry, so anything derived from
    "page height" would otherwise have to use the CONTENT extent as a proxy —
    which is exactly the defect recorded as G4 in NEW_PHASES.md, and which was
    then observed biting the Tier A harvester on `arxiv_twocolumn.pdf` p3 (a
    short figure page whose content reaches only y=390, putting the real folio
    outside a content-derived band). Reading MediaBox here keeps that fix on the
    instrument side; the parser is not modified.
    """
    try:
        import pikepdf
    except ImportError:
        return {}
    try:
        pdf = pikepdf.open(pdf_path)
    except Exception:
        return {}

    geo: Dict[int, Dict[str, float]] = {}
    for i, page in enumerate(pdf.pages, start=1):
        try:
            mb = [float(v) for v in page.MediaBox]
            geo[i] = {
                "page_x0": mb[0],
                "page_y0": mb[1],
                "page_width": mb[2] - mb[0],
                "page_height": mb[3] - mb[1],
            }
        except Exception:
            continue
    return geo


def block_records(
    parsed: Dict[str, Any], geo: Dict[int, Dict[str, float]] | None = None
) -> List[Dict[str, Any]]:
    """Flatten to one record per block, preserving emitted reading order."""
    geo = geo or {}
    out: List[Dict[str, Any]] = []
    for page in parsed.get("pages", []):
        page_num = page.get("page_num")
        pg = geo.get(page_num, {})
        for idx, block in enumerate(page.get("blocks", [])):
            btype = block.get("type")
            if btype == "table":
                text = " | ".join(
                    " ".join(str(c) for c in row) for row in block.get("rows", [])
                )
            else:
                text = block.get("text", "")
            out.append(
                {
                    "pdf_page_index": page_num,
                    "block_index_in_reading_order": idx,
                    "type": btype,
                    "section_id": block.get("section_id"),
                    "block_role": block.get("block_role"),
                    "source": block.get("source"),
                    "bbox": block.get("bbox"),
                    "page_height": pg.get("page_height"),
                    "page_width": pg.get("page_width"),
                    "text": text,
                }
            )
    return out


def run(pdf_path: str, ack_warnings: bool = False) -> Dict[str, Any]:
    parsed = parse(pdf_path)
    meta = parsed.get("metadata", {})
    warnings = meta.get("warnings", []) or []

    if warnings and not ack_warnings:
        raise UnacknowledgedWarnings(
            f"{len(warnings)} warning(s) emitted and not acknowledged. "
            f"Re-run with --ack-warnings once you have read them:\n  "
            + "\n  ".join(warnings)
        )

    geo = page_geometry(pdf_path)
    return {
        "fixture": Path(pdf_path).name,
        "tier": meta.get("tier"),
        "page_count": meta.get("page_count"),
        "parse_time_ms": meta.get("parse_time_ms"),
        "warnings": warnings,
        "blocks": block_records(parsed, geo),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("--jsonl", help="write per-block records here")
    ap.add_argument(
        "--ack-warnings",
        action="store_true",
        help="proceed even though the parse emitted warnings (you have read them)",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    try:
        result = run(args.pdf, ack_warnings=args.ack_warnings)
    except UnacknowledgedWarnings as e:
        print(f"[BLOCKED] {e}", file=sys.stderr)
        return 2

    if args.jsonl:
        with open(args.jsonl, "w", encoding="utf-8") as fh:
            for rec in result["blocks"]:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    if not args.quiet:
        import lightningparse

        print(f"lightningparse from: {lightningparse.__file__}")
        print(f"fixture     : {result['fixture']}")
        print(f"tier        : {result['tier']}")
        print(f"page_count  : {result['page_count']}")
        print(f"blocks      : {len(result['blocks'])}")
        print(f"warnings    : {len(result['warnings'])}")
        for w in result["warnings"]:
            print(f"  ! {w}")
        if args.jsonl:
            print(f"wrote       : {args.jsonl}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
