"""Decompose LightningParse timing into stages, for A/B between two builds.

Written to answer two questions that were being conflated:

  Q1  Why does wall time (96 ms) exceed the reported `parse_time_ms` (57 ms)?
  Q2  Is `parse_time_ms` higher than the published BENCHMARKS.md figure because
      the new page-geometry lookup is genuinely more expensive, or is it noise?

Q1 is structural, not an artifact: `parse_time_ms` is stopped at the end of
`parse_pdf_to_result` (lib.rs), but the FFI entry point then runs FOUR cleanup
passes (tables, reading order, header/footer, headings) and `serde_json::to_string`
before returning. Anything measured around the Python call therefore includes
work the internal counter never saw, plus `json.loads` on the Python side.

This measures each stage separately:

  t_ffi     wall time of `lightningparse.parse_pdf()` — what benchmarks/benchmark.py
            times: Rust parse + cleanup + JSON serialize, excluding json.loads
  t_loads   Python-side json.loads of the returned string
  t_total   t_ffi + t_loads — what a naive "how long does parsing take" timer sees
  internal  metadata.parse_time_ms — Rust parse ONLY, excluding cleanup+serialize

Emits JSON so a driver can interleave two builds and compare.

Usage:
    python bench_stages.py --label old --runs 30 --out result.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

WARMUP = 5


def measure(path: str, runs: int) -> dict:
    import lightningparse

    for _ in range(WARMUP):
        lightningparse.parse_pdf(path)

    ffi, loads, internal = [], [], []
    for _ in range(runs):
        t0 = time.perf_counter()
        raw = lightningparse.parse_pdf(path)
        t1 = time.perf_counter()
        parsed = json.loads(raw)
        t2 = time.perf_counter()

        ffi.append((t1 - t0) * 1000.0)
        loads.append((t2 - t1) * 1000.0)
        internal.append(float(parsed["metadata"]["parse_time_ms"]))

    def stats(xs):
        xs = sorted(xs)
        return {
            "median": statistics.median(xs),
            "min": xs[0],
            "max": xs[-1],
            "p95": xs[min(len(xs) - 1, int(len(xs) * 0.95))],
            "stdev": statistics.stdev(xs) if len(xs) > 1 else 0.0,
        }

    return {
        "pages": parsed["metadata"]["page_count"],
        "blocks": sum(len(p["blocks"]) for p in parsed["pages"]),
        "t_ffi": stats(ffi),
        "t_loads": stats(loads),
        "t_total": stats([a + b for a, b in zip(ffi, loads)]),
        "internal": stats(internal),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--runs", type=int, default=30)
    ap.add_argument("--out")
    ap.add_argument("--fixtures", nargs="*")
    args = ap.parse_args()

    fixtures = args.fixtures or [
        "benchmarks/corpus/arxiv_twocolumn.pdf",
        "benchmarks/corpus/ieee_template_placeholder.pdf",
        "benchmarks/corpus/Shivam_FullStack.pdf",
    ]

    out = {"label": args.label, "runs": args.runs, "fixtures": {}}
    for f in fixtures:
        if not Path(f).exists():
            continue
        out["fixtures"][Path(f).name] = measure(f, args.runs)

    text = json.dumps(out, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)

    for name, r in out["fixtures"].items():
        print(
            f"  [{args.label}] {name:<34} "
            f"ffi={r['t_ffi']['median']:7.2f}  "
            f"loads={r['t_loads']['median']:6.2f}  "
            f"internal={r['internal']['median']:6.1f}  "
            f"({r['pages']}p)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
