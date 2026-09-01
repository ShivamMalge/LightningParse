"""Is `benchmark.py`'s 5-runs-plus-1-warmup methodology enough to call a number stable?

Prompted by pypdf on `ieee_template_placeholder.pdf` moving 21.71 ms -> 35.43 ms
between two runs minutes apart on the same machine and the same code — >60%
apart. Two competing explanations, and they call for different responses:

  (a) ordinary jitter on a fast fixture   -> flag that fixture, keep methodology
  (b) the sampling methodology is too thin -> raise WARMUP_RUNS / TIMED_RUNS

Measures four things:

  1. the full distribution per (library, fixture): median, CV, percentiles
  2. a warm-up check — are the first runs systematically slower than later ones?
  3. a BOOTSTRAP of the current methodology: repeatedly draw 5 consecutive runs,
     take their median as benchmark.py would, and report how far that reported
     statistic itself swings. This is the direct answer to "is N=5 enough".
  4. how much the bootstrap spread narrows at N=15 and N=30

Usage:
    python bench_stability.py
"""

from __future__ import annotations

import json
import random
import statistics
import sys
import time
from pathlib import Path

# (fixture, samples) — sized so slow libraries stay tractable.
PLAN = [
    ("benchmarks/corpus/ieee_template_placeholder.pdf", 200),
    ("benchmarks/corpus/Shivam_FullStack.pdf", 60),
]


def time_lightningparse(path: str) -> float:
    import lightningparse

    t = time.perf_counter()
    lightningparse.parse_pdf(path)
    return (time.perf_counter() - t) * 1000.0


def time_pypdf(path: str) -> float:
    from pypdf import PdfReader

    t = time.perf_counter()
    reader = PdfReader(path)
    for p in reader.pages:
        p.extract_text()
    return (time.perf_counter() - t) * 1000.0


def time_pdfplumber(path: str) -> float:
    import pdfplumber

    t = time.perf_counter()
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            p.extract_text()
    return (time.perf_counter() - t) * 1000.0


RUNNERS = {
    "lightningparse": time_lightningparse,
    "pypdf": time_pypdf,
    "pdfplumber": time_pdfplumber,
}


def describe(xs):
    xs_sorted = sorted(xs)
    med = statistics.median(xs_sorted)
    mean = statistics.mean(xs_sorted)
    sd = statistics.stdev(xs_sorted) if len(xs_sorted) > 1 else 0.0
    return {
        "n": len(xs),
        "median": med,
        "mean": mean,
        "stdev": sd,
        "cv": (sd / mean * 100.0) if mean else 0.0,
        "min": xs_sorted[0],
        "max": xs_sorted[-1],
        "p50": med,
        "p90": xs_sorted[int(len(xs_sorted) * 0.90)],
        "p99": xs_sorted[min(len(xs_sorted) - 1, int(len(xs_sorted) * 0.99))],
        "max_over_min": (xs_sorted[-1] / xs_sorted[0]) if xs_sorted[0] else 0.0,
    }


def bootstrap_reported(xs, k, trials=4000):
    """Spread of the statistic benchmark.py actually reports: median of k consecutive runs."""
    if len(xs) < k:
        return None
    out = []
    for _ in range(trials):
        i = random.randrange(0, len(xs) - k + 1)
        out.append(statistics.median(xs[i : i + k]))
    lo, hi = sorted(out)[int(trials * 0.025)], sorted(out)[int(trials * 0.975)]
    return {"lo": lo, "hi": hi, "spread_pct": (hi - lo) / statistics.median(out) * 100.0}


def main() -> int:
    random.seed(7)
    results = {}

    for path, n in PLAN:
        if not Path(path).exists():
            continue
        name = Path(path).name
        results[name] = {}
        for lib, fn in RUNNERS.items():
            try:
                fn(path)  # single warm-up, exactly as benchmark.py does
            except Exception as e:
                print(f"  [skip] {lib}: {e}", file=sys.stderr)
                continue
            xs = [fn(path) for _ in range(n)]
            results[name][lib] = {"raw": xs, "stats": describe(xs)}

    print("=" * 100)
    print("1. DISTRIBUTION  (is the spread specific to one fixture or one library?)")
    print("=" * 100)
    print(f"{'fixture':<32} {'library':<15} {'n':>4} {'median':>9} {'CV%':>7} "
          f"{'min':>9} {'max':>9} {'max/min':>8}")
    for name, libs in results.items():
        for lib, d in libs.items():
            s = d["stats"]
            print(f"{name:<32} {lib:<15} {s['n']:>4} {s['median']:>9.2f} {s['cv']:>7.1f} "
                  f"{s['min']:>9.2f} {s['max']:>9.2f} {s['max_over_min']:>7.2f}x")

    print()
    print("=" * 100)
    print("2. WARM-UP CHECK  (are early runs systematically slower? -> 1 warm-up too few)")
    print("=" * 100)
    for name, libs in results.items():
        for lib, d in libs.items():
            xs = d["raw"]
            if len(xs) < 30:
                continue
            first5 = statistics.median(xs[:5])
            rest = statistics.median(xs[5:])
            drift = (first5 - rest) / rest * 100.0
            verdict = "WARM-UP EFFECT" if abs(drift) > 15 else "no warm-up effect"
            print(f"  {name:<32} {lib:<15} first-5 median={first5:8.2f}  "
                  f"rest={rest:8.2f}  {drift:+6.1f}%  -> {verdict}")

    print()
    print("=" * 100)
    print("3. BOOTSTRAP OF THE REPORTED NUMBER  (median of k consecutive runs, 95% band)")
    print("=" * 100)
    print(f"{'fixture':<32} {'library':<15} {'k=5 spread':>12} {'k=15':>10} {'k=30':>10}")
    for name, libs in results.items():
        for lib, d in libs.items():
            xs = d["raw"]
            row = []
            for k in (5, 15, 30):
                b = bootstrap_reported(xs, k)
                row.append(f"{b['spread_pct']:.1f}%" if b else "n/a")
            print(f"{name:<32} {lib:<15} {row[0]:>12} {row[1]:>10} {row[2]:>10}")

    Path(__file__).parent.joinpath("bench_stability.json").write_text(
        json.dumps({k: {l: v["stats"] for l, v in d.items()} for k, d in results.items()},
                   indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
