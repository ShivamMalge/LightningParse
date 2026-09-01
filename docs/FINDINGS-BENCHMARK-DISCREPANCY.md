# FINDINGS-BENCHMARK-DISCREPANCY.md

Resolution of the two timing questions raised before scoping the G4+G5 release.
**Neither is a performance regression. Both are measurement problems**, and each
has a different fix.

Measured 2026-09-01. Reproduce with `benchmarks/diagnostic/bench_stages.py`.

---

## Q1 — Wall 96 ms vs internal `parse_time_ms` 57 ms

**Answer: consistent, reproducible, and structural. Not an artifact.**
They measure different things, and the gap is expected.

`parse_time_ms` is stopped at the end of `parse_pdf_to_result`
([`lib.rs:47`](../lightningparse-core/src/lib.rs#L47)). The FFI entry point then does
substantially more work *after* that timer stops
([`ffi/mod.rs:63-72`](../lightningparse-core/src/ffi/mod.rs#L63-L72)):

1. `detect_tables`
2. `reconstruct_reading_order`
3. `detect_headers_footers`
4. `detect_headings`
5. `serde_json::to_string`

and then Python runs `json.loads` on the returned string.

Stage decomposition on `arxiv_twocolumn.pdf` (15 pp, medians of 25 runs × 4
interleaved rounds):

| Stage | Median | What it is |
|---|---:|---|
| `internal` (`parse_time_ms`) | 43–44 ms | extraction only |
| `t_ffi` (the `parse_pdf()` call) | 68–69 ms | extraction **+ 4 cleanup passes + JSON serialize** |
| `t_loads` (`json.loads`) | 8–9 ms | Python-side deserialization |
| `t_total` | ~77 ms | what a naive timer around the whole thing sees |

So ~25 ms is cleanup + serialization the internal counter never sees, and ~8 ms
is Python-side `json.loads`. **Anyone comparing `parse_time_ms` against a
wall-clock measurement is comparing two different quantities.** My original
96 ms figure was a single unwarmed sample of `t_total`; warmed, it is ~77 ms.

**Fix: documentation, not code.** `BENCHMARKS.md` now states exactly what is
timed and warns that it necessarily exceeds `parse_time_ms`. Renaming or
re-scoping `parse_time_ms` would be a breaking output change and is not
justified by this finding.

---

## Q2 — Internal 57 ms vs published 41.12 ms: regression or noise?

**Answer: neither. The published number measures different software.**
And separately, the page-geometry lookup is far too cheap to matter.

### The published baseline is stale by construction

`benchmarks/BENCHMARKS.md` was last regenerated in commit `7efa802`
(2026-07-28). Since then the Rust core has taken **15 commits across 3 releases**
(v0.3.0, v0.4.0, v0.4.1), including work that adds real per-page cost:

- `711ea92` heuristic **heading detection** — added to the FFI path *after* the
  benchmark was generated, so the 41.12 ms figure does not include it at all
- span tracking and same-line merge (`19c4248`, `a6ab146`, `3468e16`)
- monospace/code detection (`88e6bc5`)
- `lopdf` 0.33 → 0.44 (`84a91f5`)
- the tolerant page-tree walker (`aa03c35`, `d33cead`, `6ccea37`)

**Comparing today's numbers against 41.12 ms is not a valid comparison in either
direction.** It is five weeks and three feature releases of different software.

### The geometry lookup is not the cause — measured directly

A/B between the **pre-fix** and **post-fix** wheels (both 0.4.1, built from the
same tree modulo this change), paired and interleaved so thermal and scheduling
drift hit both equally. Full textbook, 1475 pages:

| Pair | old | new | delta |
|---|---:|---:|---:|
| 1 | 5484 ms | 5328 ms | **−156** |
| 2 | 4830 ms | 5331 ms | +501 |
| 3 | 4840 ms | 4607 ms | **−233** |
| 4 | 4985 ms | 4584 ms | **−401** |
| 5 | 4394 ms | 4569 ms | +175 |
| 6 | 4522 ms | 4562 ms | +40 |

**3 of 6 pairs show the new build faster. Median delta −58 ms; mean −12 ms.**
The sign is not even consistent, so the effect is below the noise floor, which
on this machine is roughly ±500 ms on a 5-second parse.

The 32-page chapter points the *other* way from the full book (new 23 ms vs old
29 ms internal), which is the same conclusion: noise dominates.

### Direct micro-benchmark — the decisive number

Timing `resolve_page_geometry` in isolation in Rust, no Python, no I/O, best of
5 rounds:

| Document | Pages | Geometry cost | Whole document | As % of parse |
|---|---:|---:|---:|---:|
| `arxiv_twocolumn.pdf` | 15 | 3.76 µs/page | 0.056 ms | **0.13%** |
| `f1_biology_cell_structure.pdf` | 32 | 2.15 µs/page | 0.069 ms | ~0.2% |
| `Biology-2e_WEB.pdf` | 1475 | 4.12 µs/page | 6.08 ms | **0.13%** |

Geometry resolution costs **~0.1% of parse time**, and on the full book it is
**80× smaller than the run-to-run noise** it was suspected of causing. Geometry
resolved successfully on 1475/1475 pages, so this is the real cost, not a cost
avoided by early exit.

**No decision needed. There is no regression to accept or reject.**

---

## What actually needed fixing: benchmark methodology

The real defect is that **a stale `BENCHMARKS.md` was indistinguishable from a
current one.** It recorded no version, no commit, and no date, so the only way to
discover it predated three releases was `git log` on the file — which is exactly
why a stale baseline got mistaken for a regression.

`benchmark.py` now stamps every generated report with:

- generation date
- the installed `lightningparse` version
- the short commit hash
- **a loud warning when `lightningparse-core/src` has uncommitted changes**,
  since the report is then not reproducible from that commit

It also now documents precisely what the timer covers, so Q1 cannot recur.

The stamp proved itself immediately: run from the system Python it reports
`lightningparse 0.2.0` — the stale published wheel that is still installed there
(see [`FINDINGS-PHASE1.md`](./FINDINGS-PHASE1.md)). Benchmarking that would have
measured v0.2.0 while appearing to measure current code.

### Recommendation

`BENCHMARKS.md` should be regenerated before the next release, from a clean tree
with a freshly built wheel — **not** because of this change, but because the
published numbers are three releases stale and understate the parser's current
feature set. That is a release task, not a blocker for the G4+G5 fix: the fix
costs ~0.1% of parse time and nothing in the published table is attributable
to it.


---

## Follow-up: is 5 runs + 1 warm-up enough to call a number stable?

Prompted by pypdf on `ieee_template_placeholder.pdf` moving **21.71 → 35.43 ms**
between consecutive runs on the same machine and code. Measured with
`benchmarks/diagnostic/bench_stability.py` (200 samples on the IEEE fixture,
60 on the resume).

**Answer: the methodology is too thin. This is not a small-fixture artifact.**

### The "sub-2 ms jitter" hypothesis is wrong

Variance is machine-wide, not confined to fast fixtures — and the pypdf figure
that moved is ~29 ms, not sub-2 ms:

| Fixture | Library | Median | CV | max/min |
|---|---|---:|---:|---:|
| ieee (8 pp) | lightningparse | 1.60 ms | 24.6% | 3.51× |
| ieee | pypdf | 29.34 ms | 20.9% | 2.08× |
| ieee | pdfplumber | 155.99 ms | 15.9% | 2.01× |
| resume (1 p) | lightningparse | 15.29 ms | 16.8% | 2.44× |
| resume | pypdf | 183.11 ms | 24.7% | 2.36× |
| resume | pdfplumber | 467.96 ms | 23.3% | 2.53× |

CV sits at 16–25% for **every** library and fixture, including a 468 ms
measurement. Nothing here is quantisation of a tiny timer.

### The observed move was within expected sampling noise

Bootstrapping the statistic `benchmark.py` actually reports — the median of 5
consecutive runs — gives a **95% band of 21.88–36.91 ms** for pypdf on this
fixture, a 52.8% spread. The observed 21.71 and 35.43 sit essentially at the two
edges. So the move is *expected* under the current methodology, which is exactly
the problem: the methodology admits a ±50% swing.

| Fixture / library | median of k=5 | k=15 | k=30 |
|---|---:|---:|---:|
| ieee / lightningparse | **90.6%** | 35.5% | 25.1% |
| ieee / pypdf | 49.2% | 43.9% | 38.4% |
| ieee / pdfplumber | 27.5% | 13.6% | 9.1% |
| resume / lightningparse | 59.0% | 18.8% | 14.5% |
| resume / pypdf | 69.4% | 53.9% | 44.4% |

### A real defect: one warm-up run is not enough, and it biases *our* numbers slow

`WARMUP_RUNS = 1`, so the 5 timed runs still sit inside the warm-up ramp:

| Fixture | Library | median of first 5 | median of rest | drift |
|---|---|---:|---:|---:|
| ieee | lightningparse | 3.00 ms | 1.60 ms | **+87.2%** |
| ieee | pdfplumber | 181.52 ms | 155.40 ms | +16.8% |
| resume | lightningparse | 21.71 ms | 15.22 ms | **+42.6%** |
| resume | pdfplumber | 677.79 ms | 456.88 ms | +48.4% |
| ieee | pypdf | 25.94 ms | 29.87 ms | −13.2% (none) |

LightningParse and pdfplumber both ramp; pypdf does not. After 20 warm-up runs
LightningParse measures **1.29 ms** on the IEEE fixture against the **1.69 ms**
currently published — the published figure **understates our own performance by
roughly 30%**. It is a conservative error, not an overclaim, so it does not
invalidate any published comparison, but it should be corrected.

### `min` is a better statistic than `median` here

The minimum is the least-disturbed run, and it converges far faster:

| Statistic | k=5 | k=15 | k=30 |
|---|---:|---:|---:|
| lightningparse, median of k | 40.8% | 24.9% | 15.4% |
| lightningparse, **min** of k | **22.2%** | **10.4%** | **8.8%** |
| pypdf, median of k | 52.8% | 45.3% | 37.3% |
| pypdf, **min** of k | 53.4% | 44.9% | **25.2%** |

### Recommendation

1. **Raise `WARMUP_RUNS` 1 → 10 and `TIMED_RUNS` 5 → 25.** Uncontroversial: it
   keeps the reported statistic's meaning and removes both the ramp bias and most
   of the sampling spread.
2. **Consider reporting `min` alongside `median`.** This changes what the table
   means, so it is a judgement call rather than a straight fix.
3. **Treat the IEEE fixture's absolute numbers with extra scepticism regardless** —
   at ~1.6 ms for LightningParse, the ratio is dominated by each library's fixed
   startup cost rather than extraction work.

None of this changes the v0.5.0 correctness fix or the conclusion that the
geometry lookup costs ~0.1% of parse time — that was established by a direct
Rust micro-benchmark, not by these Python-level timings.
