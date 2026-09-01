# FINDINGS-PHASE1.md

Results for [`NEW_PHASES.md`](./NEW_PHASES.md) **Phase 1 — Citation Fidelity A:
printed label vs. PDF index**.

**Status: ⚠️ PARTIAL — synthetic control (F5a) complete, real fixtures outstanding.**
Phase 1 requires F1, F2, F5a, F5b, F5c. Only **F5a** exists so far, because the
other four need real textbook content that must be sourced before it can be
measured. What F5a proves is reported below; what it cannot prove is stated
explicitly at the end.

Measured 2026-08-30 against **lightningparse 0.4.1 built from the current tree**,
not the published wheel.

> ⚠️ **The system Python still holds a stale `lightningparse` 0.2.0 wheel** —
> the same trap `ASCII_PHASES.md` Phase 0 recorded. Measuring against it would
> have proven nothing about current code. Every number here comes from a
> throwaway venv containing a `maturin build --release` of this source tree
> (`lightningparse-0.4.1-cp311-cp311-win_amd64.whl`). The harness prints the
> resolved import path on every run so this cannot be faked by accident.

---

## Instruments built

| Artifact | Purpose |
|---|---|
| [`benchmarks/diagnostic/make_f5a.py`](../benchmarks/diagnostic/make_f5a.py) | Generates F5a. Synthetic, no real content, so it is committed. |
| [`benchmarks/diagnostic/fixtures/f5a_pagelabels.pdf`](../benchmarks/diagnostic/fixtures/f5a_pagelabels.pdf) | 20 pages: 6 front matter (roman i–vi), 14 body (arabic restarting at 1). Carries **both** a `/PageLabels` tree and the label as ink in a centered footer. |
| [`benchmarks/diagnostic/harness.py`](../benchmarks/diagnostic/harness.py) | Per-**block** dump (`section_id`, `block_role`, `source`, `bbox`, reading-order index) + `metadata.warnings` verbatim. **Refuses to report if warnings are present and not acknowledged** via `--ack-warnings`. |
| [`benchmarks/diagnostic/measure_phase1.py`](../benchmarks/diagnostic/measure_phase1.py) | The Phase 1 measurement, including the Tier A harvester and its monotonicity self-check. Keeps `harvest_labels_naive` alongside the real one so the before/after is visible rather than asserted. |
| [`benchmarks/diagnostic/sweep_corpus.py`](../benchmarks/diagnostic/sweep_corpus.py) | Runs every available PDF through the Phase 1 machinery. Built to de-risk the harvester on real documents before real textbooks are sourced — and it immediately found three harvester bugs. |

F5a carries two independent label carriers on purpose — machine-readable
`/PageLabels` metadata and human-readable ink — so the measurement can
distinguish *"ignores the metadata"* from *"cannot see the label at all."*
Anchor tokens are opaque (`ANCHOR-F5A-07`) and encode only the PDF index, never
the printed label, so a harvester reading body text cannot score correct by
accident.

---

## Result: the bar fails

| Bar (set before running) | Measured | Verdict |
|---|---|---|
| Digital-native body pages → correct printed label | **0 / 14 = 0%** | ❌ **FAIL** |

F5a parses cleanly — `tier: "digital"`, 20 pages, 122 blocks, **zero warnings**.
There is no extraction failure here. The parse is fine; the citation is wrong.
That combination is exactly what makes this failure mode dangerous, and exactly
why it needed its own phase.

### The offset is not constant, so no single correction fixes it

| Numbering run | Offset (cited − printed) | Constant within run? |
|---|---|---|
| Front matter, roman (pdf 1–6) | `0` | ✅ yes |
| Body, arabic (pdf 7–20) | `+6` | ✅ yes |
| **Across the whole document** | **`{0, 6}`** | ❌ **no** |

Two distinct failure modes, not one:

- **Body pages are off by exactly 6.** A student told "page 3" turns to the
  page the book prints as 3, which is PDF page 9 — six pages of a different
  chapter away.
- **Front matter is numerically coincident but typographically wrong.** The
  parser cites `1`; the book prints `i`. The offset is 0, so a naive offset
  check scores it "correct" — but a student told "page 1" turns to body page 1,
  not the title page. **Any future fix that only learns a single integer offset
  will silently keep failing here.**

### End-to-end, through the chunker

Confirmed against the real chunk objects Aakar would consume, not inferred:

```
chunk | cites page | book prints
------+------------+------------
    0 |          1 |           i
    3 |          4 |          iv
    6 |          7 |           1
    9 |         10 |           4
```

`Document.metadata["page_num"]` is the raw PDF index, straight from
[`chunker.py:22`](../lightningparse-api/chunking/chunker.py#L22). 20 chunks, one
per page — confirming **G12** (no chunk spans two pages), so page attribution is
structurally unambiguous and only the *value* is wrong.

---

## Why: `/PageLabels` is present, ignored, and unreachable via `lopdf`

- The tree **is** in the file: `/Nums [ 0 << /S /r >> 6 << /S /D /St 1 >> ]` —
  verified independently with `pikepdf`, so this is not a fixture defect.
- The parser **does not use it**. No printed-label field exists anywhere in the
  output schema; block fields are exactly `bbox`, `block_role`,
  `pdf_page_index`, `section_id`, `source`, `text`, `type`. **G1 confirmed.**
- **`lopdf` 0.44 has zero `/PageLabels` support** — `grep -rn "PageLabel"` over
  the vendored crate source returns **no hits**, and there is no number-tree
  helper of any kind.

**This answers the question Phase 1 was written to answer.** A future fix is a
**raw-dictionary traversal job, not an API call**: `Document::catalog()` exists
([`document.rs:512`](https://docs.rs/lopdf) in the vendored 0.44 source), so
`/PageLabels` is reachable, but the `/Nums` array — and the `/Kids` chain of a
nested number tree — would have to be walked by hand, including the `/S` style
codes (`/D`, `/r`, `/R`, `/a`, `/A`) and `/St` start values. That is a
meaningfully larger job than "read a field," and it is sized now rather than
discovered mid-fix.

---

## The label is recoverable from ink — but only after the harvester was fixed twice

On F5a the Tier A harvester scored **20/20 with 0 monotonicity breaks**. That
result was over-read on first pass, and the correction is worth recording,
because it is the same mistake this document set exists to prevent: **F5a was
generated to be easy.** Running the harvester across the repo's existing real
PDFs is what actually tested it, and the first version failed.

### The corpus sweep

[`sweep_corpus.py`](../benchmarks/diagnostic/sweep_corpus.py) runs every available
PDF through the Phase 1 machinery. On real documents the naive harvester —
"first bare numeral in either margin band" — reported **13/15 coverage on
`arxiv_twocolumn.pdf` while getting three of those pages wrong**:

| Page | Harvested | Actually | What it grabbed |
|---|---|---|---|
| 6 | `2` | `6` | an exponent from `O(n²·d)` in a table at the top of the page |
| 8 | `20` | `8` | an exponent from `1.0×10²⁰` in a results table |
| 9 | `dv` | `9` | the math variable *d_v*, a table column header |

Three distinct root causes, **all in the instrument, none in LightningParse**:

1. **Band derived from content extent reached into real content** — the same
   defect recorded as **G4** in the parser, reproduced in my own harvester.
2. **First-match-wins ordering** — the real folio sits at y≈42–52 on every page,
   but table junk near the top matched first.
3. **The roman regex was far too loose.** Canonicalising it does *not* fix this:
   `dv` (505) and `mix` (1009) are both **valid canonical roman numerals** —
   measured, not assumed.

### Two fixes, both instrument-side

**Position consistency.** A folio sits in the same place on every page; a table
cell that happens to be a numeral does not. The harvester now collects every
candidate, groups them into quantised position slots, and keeps only the slot
that behaves like a folio — present on the most pages, longest monotonic run —
plus a plausibility cap rejecting roman values above 50.

**MediaBox-derived bands.** `arxiv_twocolumn.pdf` p3 is a short figure page whose
content reaches only y=390, so a 12% *content* band ends at y=47 and excludes the
folio at y=52. The harness now reads MediaBox via `pikepdf`, independently of the
parser, so bands come from page geometry. **The parser was not modified** — this
stayed on the instrument side.

### Result across three versions

| Harvester | arxiv (15p) | ieee (8p) | mixed (9p) | wrong labels | mono breaks |
|---|---|---|---|---|---|
| naive first-match | 13/15 | 7/8 | 1/9 | **3** | 5 |
| + position slots | 13/15 | 7/8 | 1/9 | 0 | 2 |
| **+ MediaBox bands** | **14/15** | **8/8** | 0/9 | **0** | **0** |

Zero wrong labels and zero monotonicity breaks across the whole corpus. The
gaps that remain are **correct refusals**, not failures: arxiv p1 is a title
page carrying a NeurIPS conference footer and no folio; `digital_word_export.pdf`
is a two-page memo with no page numbers. Harvesting nothing is the right answer
when there is nothing to harvest — a confident wrong label is worse than a gap.

**The monotonicity self-check earned its place.** It was designed to make a bad
harvest visible, and on first contact with real documents it did exactly that.
Without it, "13/15 harvested" would have been recorded as a success.

### `/PageLabels` is absent from every real document available

| Corpus | Carrying a `/PageLabels` tree |
|---|---|
| 13 pre-existing repo PDFs | **0** |
| F5a (synthetic, built to have one) | 1 |

This **reframes the fix**. Reading `/PageLabels` would correct F5a and nothing
else currently in the repo. It is real evidence for the F5b hypothesis — that
the tree is commonly absent — and it means **ink-harvesting is the load-bearing
path, not the fallback**. That said, none of these 13 are textbooks; real books
may carry the tree more often. It is a directional signal, not a rate.

### Ground truth is unavailable on the one scanned document

Tier A harvested **0/9** on `mixed_test.pdf`, the only mixed/OCR-tier document
available (the naive version's single answer there, `'2'` on p5, was wrong and
is now correctly rejected).

Whether that reflects *absent folios* or *OCR failing to recover them* *cannot
be determined from this fixture* — it is a synthetic test file that may simply
have no page numbers. **F3a resolves it**: a scan of a digital original has
known folios, so it separates the two. Flagged rather than guessed, because if
it turns out OCR cannot recover folios, Tier A contributes nothing on scanned
books — Aakar's most common input — and the Tier B hand-labeling budget in
`NEW_PHASES.md` Phase 0 was sized assuming Tier A covers whole documents
automatically. **That budget may need revisiting for scanned fixtures.**

---

## Phase 2 preview: two content-loss findings, unprompted

Not what Phase 1 set out to measure, but the per-block dump surfaced it and it
would be dishonest to sit on it.

**19 of 20 printed labels survive as `section_id: "body"`.** Exactly one does
not — **page 1**, whose label `i` was tagged `footer` and is therefore deleted by
the chunker ([`chunker.py:33`](../lightningparse-api/chunking/chunker.py#L33)).
That is **G5 confirmed**: the page-1-only fallback classifies page 1 by a
different rule than every other page.

Worse, on page 1 that same fallback also swallowed the page's actual content:

| Page 1 block | y-range | Tagged |
|---|---|---|
| `"Structures of the Human Eye"` (title) | 700–718 | **`header`** → dropped |
| `"A Synthetic Fixture for Parser Diagnostics"` (subtitle) | 660–671 | **`header`** → dropped |
| `"ANCHOR-F5A-01"` | 120–129 | `body` → survives |
| `"i"` (label) | 40–50 | **`footer`** → dropped |

Page 1 contributes **one meaningless token** to retrieval. Its title is gone. On
a real textbook that is the title page — and on a chapter-opener page, the
chapter title.

**And a second, distinct false positive on page 7** — the chapter heading
`"The Human Eye"` at y=700 was tagged `header` and dropped, while the identical
heading pattern on page 8 (`"The Cornea"`) correctly stayed `body`. The
arithmetic, which is **G4**:

```
global_max_y (content extent) = 759.0   ->  top band starts at 0.90 * 759.0 = 683.1
MediaBox height               = 792.0   ->  a MediaBox-based band would start at 712.8
```

The band is derived from **content extent, not page geometry**, so it reaches
~30pt lower than the real top margin — far enough to swallow a heading at y=700.
Page 7's heading text also happens to match the running-head cluster, so both
conditions coincide there. **With a MediaBox-derived band the heading would have
been outside the band entirely.**

Two mechanisms, two pages, both silent, both losing real content. Recorded here;
**not fixed**, per this document set's scope.

---

## Measured on real textbooks

Two open-licensed textbooks were fetched into a local-only corpus **outside the
repo** (`~/Desktop/lp-diagnostic-corpus/`, a sibling of the work tree — verified
with `git rev-parse` before download; `git status` clean after). Licence is
**CC BY-NC-SA 4.0**, per the OpenStax CMS API.

| Book | Pages | Blocks | Parse | Tier | Warnings |
|---|---|---|---|---|---|
| OpenStax *Biology 2e* | 1475 | 70,269 | 11.3 s | `mixed` | **0** |
| OpenStax *College Physics 2e* | 1671 | 89,257 | 9.2 s | `mixed` | **0** |

### The offset on a real textbook is CONSTANT

| Book | Offset (pdf_index − printed) | Holds on |
|---|---|---|
| *Biology 2e* | **20** | **1408 / 1408 harvested pages — 100%** |
| *College Physics 2e* | **18** | **1618 / 1618 harvested pages — 100%** |

PDF page 21 of *Biology 2e* is printed page `1`. A student told "page 21" turns
twenty pages early, into the front matter.

**This is materially better news than F5a suggested.** F5a's offset was variable
(`{0, +6}`) because it restarts numbering; both real textbooks number
continuously from the first body page, so a single integer describes the whole
book. The failure is real and total — **every citation in a 1475-page book is
wrong** — but the *shape* of it is the tractable kind. F5a remains the honest
worst case, and a fix must still handle it; the two are not in conflict, they
bracket the range.

### `/PageLabels` is absent from real textbooks too

**0 of 15** documents now carry the tree — including two professionally produced
textbooks of 1475 and 1671 pages. The only file that has one is the synthetic
F5a, built to have one. This moves the F5b hypothesis from a directional signal
to a well-supported finding: **reading `/PageLabels` would fix nothing on any
real document tested. Ink-harvesting is the load-bearing path, not the fallback.**

### Tier A survives real textbook furniture

| Book | Harvested | Offset consistency | Breaks |
|---|---|---|---|
| *Biology 2e* | 1408 / 1475 | 100% | 47 |
| *College Physics 2e* | 1618 / 1671 | 100% | 35 |

This is the validation that was explicitly *unearned* after F5a. The breaks are
an artifact of coverage gaps, not wrong labels — where a page carries no folio
(chapter openers, full-page figures, front matter) the next harvested page jumps
by more than one. Offset consistency at 100% is the stronger signal: every label
recovered agrees with every other.

---

## Two findings that were not what Phase 1 was looking for

### Header/footer detection tags NOTHING on real textbooks

| Document | Blocks | `header` | `footer` |
|---|---|---|---|
| *Biology 2e* (1475p) | 70,269 | **0** | **0** |
| *College Physics 2e* (1671p) | 89,257 | **0** | **0** |

Both books have running heads and folios on nearly every page. **None were
tagged.** The likely mechanism — to be confirmed in Phase 2, not asserted here —
is the 70%-of-pages cluster threshold: a running head reading
`"Chapter 4 | Cell Structure"` normalises to `"chapter | cell structure"` and
**changes every chapter**, so no single normalised string appears on ≥1033 of
1475 pages.

This is the **exact mirror image** of
[`FINDINGS-CONTENT-EXTENT-BANDS.md`](./FINDINGS-CONTENT-EXTENT-BANDS.md): on
short documents the bands *over*-reach and delete real content; on long real
books the threshold *under*-fires and removes no furniture at all. Every folio
and running head flows straight into the chunks. Both directions are Phase 2's
subject, and both now have real evidence rather than a source reading.

### `tier` is an unreliable provenance signal

*Biology 2e* reports `tier: "mixed"`. It has **zero OCR-sourced blocks** — all
70,269 are `source: "digital"`. The cause is pages 1–2 (image-only cover)
yielding no text, which increments the scanned-page counter in
[`lib.rs:28-33`](../lightningparse-core/src/lib.rs#L28-L33) regardless of whether
OCR recovered anything.

So `tier: "mixed"` here means *"2 pages had no text layer"*, **not** *"2 pages
were scanned"* — and **no warning distinguishes them** (consistent with **G7**).
A consumer using `tier` to gauge provenance strength would downgrade a
pristine digital textbook because its cover is a JPEG. Direct input to Phase 7:
`tier` cannot carry the provenance signal on its own; per-block `source` can.

---

## What F5a cannot prove

Stated plainly, so these numbers are not over-read — the whole reason this
document set exists is that a previous session over-read a single synthetic
fixture.

- **F5a is synthetic.** It shows the *mechanism* is broken; it does not
  establish the *rate* on real books. A single clean fixture is precisely the
  evidence that caused the earlier misdiagnosis, and one clean result should not
  now be over-read in the opposite direction.
- **The 0% is structural, not statistical.** It follows from there being no
  printed-label concept at all (G1), so it will reproduce on every fixture with
  front matter. Real fixtures are needed to measure *how many* real books have
  offsets — not whether the offset exists.
- **F5b / F5c (no `/PageLabels`, chapter-restarted numbering) are untested.**
  These are the cases `NEW_PHASES.md` flagged as genuinely requiring real
  content. The Tier A harvester's 20/20 is on a clean synthetic footer and
  should be expected to degrade.
- **No Tier B anchors recorded yet.** The 100-anchor budget is untouched;
  F5a's opaque tokens are a synthetic stand-in, not the real thing.
- **F1 (digital-native SINGLE-column) is still unsourced.** Both OpenStax books
  turned out to be **two-column**, verified by x-centre distribution on sampled
  body pages — so `NEW_PHASES.md`'s fixture matrix was wrong to assign Biology 2e
  to F1. Biology 2e is a good second two-column fixture; the single-column path
  needs a different source.
- **No scanned real textbook yet**, so Tier A on scanned content is still
  untested (see the 0/9 result above).

## To finish Phase 1

1. Source F1 and F2 (OpenStax, CC BY — open-licensed, so lawful to fetch, but
   still kept **outside** the repo per the sourcing rule).
2. Source F5b and F5c — real books with front matter and with chapter-restarted
   numbering. **These require content the developer supplies**; they cannot be
   synthesized without inventing the quirk under test.
3. Record the Tier B anchors for each.
4. Re-run `measure_phase1.py` per fixture and complete the bars table.
