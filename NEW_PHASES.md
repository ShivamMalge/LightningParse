# NEW_PHASES.md

Diagnostic plan for qualifying LightningParse as the ingest path for **Aakar**
(textbook chapter → chunks → Qdrant → cited answers grounded in the student's own
book, with page citations).

The question this document answers is **not** "is LightningParse good." It is
"is LightningParse good enough for Aakar's specific claims, and where exactly
does it break." Follows the same phase-by-phase, evidence-before-conclusion
discipline as [`PHASES.md`](./PHASES.md),
[`PHASES-EXTRACTION-FIDELITY.md`](./PHASES-EXTRACTION-FIDELITY.md), and
[`ASCII_PHASES.md`](./ASCII_PHASES.md).

---

> ## ⛔ Scope: DIAGNOSIS ONLY
>
> **Every phase in this document ends in "here's what we measured and found."
> None end in "here's the code change."** No phase may be marked complete on the
> strength of a fix; a phase is complete when its measurement exists, is
> reproducible, and is written down — including when the measurement says
> "this is fine."
>
> The one exception is *measurement* code: the harness, the ground-truth
> tooling, and fixture manifests are built in Phase 0 because nothing else can
> be measured without them. That is instrumentation, not remediation.
>
> Fixes are decided **after** this document produces numbers, in a separate
> follow-up plan.

---

## Why this document exists

An earlier session ran a benchmark, saw LightningParse underperform, and
concluded "LightningParse needs improving." The actual cause was a single known
`ASCII85Decode` gap, triggered by a synthetic reportlab fixture, which silently
routed the document to OCR. A specific, already-documented limitation was
misread as a general quality problem — and the evidence that would have caught
it (`result["metadata"]["warnings"]`) was present in the output the whole time
and simply never read by the harness.

Two rules follow, and they shape every phase below:

1. **Diagnose to a mechanism, not to a verdict.** "Citation accuracy is 82%" is
   not a finding. "Citation accuracy is 82%, and 100% of the failures are pages
   whose printed label lives in a running footer that `normalize_text()`
   clustered away" is a finding.
2. **Read everything the parser already tells you before concluding it told you
   nothing.** See Phase 0 and Phase 7.

---

## Grounding: what the source says today

Read from the current tree before any fixture was run. These are **facts about
the code**; the behavioural consequences noted alongside them are **hypotheses
the phases must confirm or refute against real documents**, not conclusions.

| # | Observation (verified in source) | Where | Bears on |
|---|---|---|---|
| G1 | **No `/PageLabels` support exists anywhere in the repo.** `grep -rni "pagelabel\|page_label\|printed_page"` returns zero hits across Rust, Python, and docs. `page_num` is the 1-based PDF page index from the page-tree walk. There is no printed-page concept in the schema at all. | [`extract/mod.rs:29-50`](lightningparse-core/src/extract/mod.rs#L29-L50), [`output/mod.rs`](lightningparse-core/src/output/mod.rs) | Phase 1 |
| G2 | `normalize_text()` **strips ASCII digits** before clustering, so "Page 12" and "Page 13" collapse to the same key `"page"`. A block of *only* digits normalizes to `""`. | [`cleanup/mod.rs:155-164`](lightningparse-core/src/cleanup/mod.rs#L155-L164) | Phase 2 |
| G3 | ⏸️ **Stays diagnostic-only** (deliberately excluded from the G4+G5 fix; any change here increases deletion). Tagging is skipped entirely for empty normalized text (`if norm_text.is_empty() { continue; }`) **before** any header/footer branch is reached. A bare numeric page label therefore can never be tagged furniture. Roman numerals are not ASCII digits, so `"xii"` survives normalization and is unique per page — never reaching the 70% cluster threshold. | [`cleanup/mod.rs:110-112`](lightningparse-core/src/cleanup/mod.rs#L110-L112) | Phase 2 |
| G4 | ➡️ **PROMOTED TO A FIX — see [`PHASES-MARGIN-BANDS.md`](./PHASES-MARGIN-BANDS.md).** Confirmed live with measured content loss; no longer diagnostic-only. Margin bands are computed from `global_max_y` — the maximum block extent **across the whole document** — not from each page's MediaBox. Mixed page sizes or one unusually tall page shift the bands for every other page. | [`cleanup/mod.rs:31-49`](lightningparse-core/src/cleanup/mod.rs#L31-L49) | Phase 2 |
| G5 | ➡️ **PROMOTED TO A FIX — see [`PHASES-MARGIN-BANDS.md`](./PHASES-MARGIN-BANDS.md).** Causes 8 of 9 observed content deletions. A page-1-only fallback tags top/bottom blocks as header/footer **with no cross-page corroboration**. Page 1 is classified by a different rule than every other page. | [`cleanup/mod.rs:124-147`](lightningparse-core/src/cleanup/mod.rs#L124-L147) | Phase 2 |
| G6 | Column clustering unions blocks on **any** x-span overlap, transitively. Blocks ≥65% of the *content* width (not MediaBox width) are pulled out as swath boundaries first. The uncovered window is a block wider than one column but under 65% that straddles the gutter — it unions both columns into one. | [`cleanup/mod.rs:189, 276-286`](lightningparse-core/src/cleanup/mod.rs#L276-L286) | Phase 3 |
| G7 | **Exactly one warning string exists in the entire codebase** — the unsupported-filter message. OCR fallback, CID/ToUnicode failure, corrupt-but-supported filters, and encryption all emit nothing. | [`extract/mod.rs:81`](lightningparse-core/src/extract/mod.rs#L81) (sole site) | Phase 7 |
| G8 | `warnings` is a flat `Vec<String>` on `DocumentMetadata`. The page number appears only as prose inside the message text (`"Page {n}: …"`), never as a structured field. There is no per-block association. | [`output/mod.rs:115-121`](lightningparse-core/src/output/mod.rs#L115-L121), [`lib.rs:24-27`](lightningparse-core/src/lib.rs#L24-L27) | Phase 7 |
| G9 | **No encryption handling of any kind.** `grep -rni encrypt src` returns zero hits. `lopdf` 0.39 introduced `is_encrypted()`; it is not called. | [`lib.rs:15-17`](lightningparse-core/src/lib.rs#L15-L17) | Phase 5 |
| G10 | `benchmark.py` reads `metadata["tier"]` and `metadata["page_count"]` but **never reads `metadata["warnings"]`** — the exact omission that caused the earlier misdiagnosis is still in the harness. | [`benchmarks/benchmark.py:45-66`](benchmarks/benchmark.py#L45-L66) | Phase 0 |
| G11 | The chunker **drops** every block tagged `header`, `footer`, or `footnote` before chunking. Anything the cleanup pass tags as furniture is removed from retrieval entirely. | [`chunking/chunker.py:33-34`](lightningparse-api/chunking/chunker.py#L33-L34) | Phase 2 |
| G12 | Chunks never span pages — the chunk loop is nested inside the page loop, and every chunk carries exactly one `page_num`. Page attribution per chunk is therefore unambiguous *as a structure*; only the *value* can be wrong. | [`chunking/chunker.py:21-22`](lightningparse-api/chunking/chunker.py#L21-L22) | Phase 1 |
| G13 | `is_boundary = section_id in ("title",)` — but `section_id` is only ever `header`/`footer`/`footnote`/`body`. This condition is dead; chunks split on size alone. | [`chunking/chunker.py:64`](lightningparse-api/chunking/chunker.py#L64) | Phase 0 |
| G14 | The trailing-chunk flush reads `source_type` from `blocks[-1]` — the last block **on the page**, which may have been skipped as furniture and need not belong to the chunk. On a mixed-source page the trailing chunk's provenance label can be wrong. | [`chunking/chunker.py:95`](lightningparse-api/chunking/chunker.py#L95) | Phase 7 |

---

## Priority order

| Rank | Axis | Phase | Rationale |
|---|---|---|---|
| 1 | Citation fidelity | 1, 2, 3 | Aakar's headline claim. Fails **silently** — a wrong page number looks exactly like a right one. |
| 2 | OCR noise | 4 | Students scan their own books; this path is hit constantly. |
| 3 | Encrypted PDFs | 5 | Textbook PDFs routinely carry owner passwords. Needs explicit rejection, not a crash or silent OCR fallback. |
| 4 | CID/Type0 fonts | 6 | Devanagari and math glyphs. Known-limited, but **unquantified**. |
| 5 | Tables | — | **Dropped.** See [Dropped: tables](#dropped-tables-and-why). |
| — | Warnings as provenance signal | 7 | Cross-cutting; depends on findings from 1–6. |

---

## Fixture sourcing — hard constraint

**Real textbook content never enters this repository.** Not in
`benchmarks/corpus/`, not in `lightningparse-core/tests/fixtures/`, not in any
branch. Page images rendered from such PDFs are derived works and are covered by
the same rule.

The mechanism:

- Real-book fixtures live in a **local-only directory outside the repo tree**,
  e.g. `../lp-diagnostic-corpus/`. Not a gitignored subdirectory — outside
  entirely, so no `git add -f` can reach it by accident.
- A committed `benchmarks/diagnostic/corpus_manifest.toml` records, per fixture:
  source URL, edition, license, retrieval date, SHA-256, and page ranges used.
  **The manifest makes the work reproducible without redistributing the
  content** — anyone can re-fetch from the recorded source.
- Harness code, ground-truth tooling, and the manifest are committed. The
  measured *numbers* are committed. The PDFs are not.
- Add `../lp-diagnostic-corpus/` to the harness's default search path via an
  env var (`LP_DIAG_CORPUS`), so no path to real content is ever hardcoded in a
  committed file.

**Prefer openly-licensed sources over commercial textbooks wherever the fixture
would work as well.** Where real content is genuinely required, prefer freely
licensed real content over arbitrary commercial content.

### Fixture matrix

Aakar v1 topics are human eye, animal cell, neuron, Earth's layers, DNA, OSI
stack — so biology, physics, and CS chapters, plus at least one non-Latin.

| ID | What | Real or synthetic? | Source preference | Why this one |
|---|---|---|---|---|
| **F1** | Digital-native, single-column | **Real**, open-licensed | ⚠️ **UNSOURCED — matrix corrected.** OpenStax *Biology 2e* was assigned here and is **two-column**, verified by x-centre distribution. A different single-column open textbook is needed. | The baseline happy path. Also the parent of F3a. |
| **F1b** | Digital-native, two-column, biology (animal cell / DNA) | **Real**, open-licensed ✅ **SOURCED** | OpenStax *Biology 2e* ch.4 "Cell Structure", 32 pp — CC **BY-NC-SA** 4.0 (not CC BY; corrected from the API) | Aakar's animal-cell topic. Kept as a two-column fixture since that is what it actually is. |
| **F2** | Digital-native, two-column, math-bearing | **Real**, open-licensed ✅ **SOURCED** | OpenStax *College Physics 2e* ch.26 "Vision and Optical Instruments", 34 pp — CC BY-NC-SA 4.0; existing `arxiv_twocolumn.pdf` retained as the in-repo control | Phase 3's primary target, and it is Aakar's human-eye topic. Two columns + figures + equations is the shape that breaks Union-Find. |
| **F3a** | Scanned twin of F1 | **Synthetic-from-real** — print F1, scan at 300dpi | Derived from F1 | **Key methodological device:** a scan whose exact text is already known. Gives character-level OCR ground truth at zero transcription cost. Stays out of the repo (derived from real content). |
| **F3b** | Genuine phone-photo capture of a physical textbook page | **Real** — must be | A book the developer owns | F3a has clean geometry. Real student captures have skew, shadow gradient, and page curl. F3a cannot simulate these honestly. |
| **F4a** | Devanagari science chapter | **Real** | NCERT — **verify NCERT's actual reuse terms first; do not assume they permit reuse.** If terms don't permit it, substitute any CC-licensed Devanagari technical text. | CID/Type0 with a non-Latin script. The repo's only current CJK fixture already shows unquantified surrogate artifacts (`\udc81`) per `ASCII_PHASES.md`. |
| **F4b** | Heavy display-math chapter | **Real**, open-licensed | OpenStax or an arXiv survey | Math glyphs are Type0 with custom encodings — a different failure surface from Devanagari. |
| **F5a** | Roman→arabic restart **with** a `/PageLabels` tree | **Synthetic** — easily generated | Generated locally, committed (no real content) | Control for "does the code read `/PageLabels` at all." Per G1 the expected answer is no; this makes that *measured* rather than asserted, and gives a regression anchor. |
| **F5b** | Front matter with printed labels and **no** `/PageLabels` tree | **Real — cannot be synthesized honestly** | Any real scanned textbook with front matter | The hard case, and the common one. Real books frequently carry no `/PageLabels`; the printed number exists only as ink. Synthesizing this would mean inventing the very quirk under test. |
| **F5c** | Chapter-restarted numbering (each chapter restarts at 1) | **Real — cannot be synthesized honestly** | A real technical textbook using per-chapter numbering | Same reasoning as F5b. |

**Fixture-by-fixture verdict on synthetic substitution:** F5a is synthetic and
should be. F3a is a legitimate derived fixture. **F5b, F5c, and F3b genuinely
require real content** — they exist precisely to capture quirks that a generator
would have to be told about in advance, which defeats the purpose. F1, F2, F4a,
and F4b should use open-licensed real content rather than commercial.

---

## Phase 0 — Diagnostic Harness & Ground-Truth Methodology — ⚠️ PARTIAL

> **Status: PARTIAL.** Harness, Tier A harvester, and a corpus sweep exist.
> **The harvester's 20/20 on F5a was over-read and has been corrected** — on real
> documents the first version reported 13/15 coverage while getting 3 pages
> wrong (table exponents and the math variable *d_v* harvested as folios). Two
> instrument-side fixes later (position-consistency slots; MediaBox-derived
> bands instead of content-extent) it reaches **14/15 and 8/8 with zero wrong
> labels and zero monotonicity breaks** across the corpus. Still open: the
> corpus manifest, the 100 Tier B anchors, and ground truth for **scanned**
> documents — Tier A harvested 0/9 there. See
> [`FINDINGS-PHASE1.md`](./FINDINGS-PHASE1.md).
>
> ⚠️ **The Tier B budget may be undersized for scanned fixtures.** The
> 20-anchors-per-fixture cap below assumes Tier A covers whole documents
> automatically. On the only mixed/OCR document available it covered nothing.
> Whether that is absent folios or OCR failing to recover them is **untested**;
> F3a (a scan of a digital original, whose folios are known) resolves it.
>
> ⚠️ **Environment trap, confirmed live:** the system Python holds a stale
> published `lightningparse` **0.2.0** wheel — the same trap `ASCII_PHASES.md`
> recorded. All measurement must run against a `maturin build --release` of the
> current tree in a throwaway venv. `harness.py` prints the resolved import path
> on every run so this cannot be missed.

**Goal:** build the instrument. Every later phase reports through it. Nothing
else can start until this exists, because the current harness is structurally
incapable of surfacing the failures being hunted (G10).

### What the current harness does not surface

- `metadata.warnings` — never read (G10). **This is the exact omission that
  caused the earlier misdiagnosis and it has not been fixed.**
- Per-block `section_id` — so "the page label got tagged as furniture" is
  invisible.
- Per-block `source` (`"digital"` / `"ocr"`) — so per-page OCR fallback within a
  `tier: "mixed"` document is invisible.
- Block ordering — reading order is never checked, only presence of text.
- Any notion of a printed page label, because none exists in the schema (G1).

### Deliverables

- [x] `benchmarks/diagnostic/harness.py` — built. Emits one record per block
      (`pdf_page_index`, `block_index_in_reading_order`, `type`, `section_id`,
      `block_role`, `source`, `bbox`, `text`) plus document-level `tier`,
      `page_count`, `parse_time_ms`, and the full `warnings` array verbatim.
- [x] The harness **fails loudly if `warnings` is non-empty and unreviewed** —
      built; exits `2` with `[BLOCKED]` unless `--ack-warnings` is passed.
- [ ] `benchmarks/diagnostic/corpus_manifest.toml` per the sourcing rules above.
      **Not yet written — no real fixtures sourced.**
- [ ] Record, do not fix, the two chunker defects found by inspection (G13 dead
      `"title"` boundary, G14 wrong trailing-chunk `source_type`) in a findings
      file. They are inputs to the fix plan, not work for this document.
- [x] Confirm G12 empirically — **confirmed on F5a**: 20 pages produced exactly
      20 chunks, one per page, no chunk spanning two pages. The ground-truth
      design below is sound.

### Ground truth for "what printed page is this text actually on"

The expensive naive approach is hand-labeling every chunk. It is not necessary.
Use two tiers:

**Tier A — automatic, whole-document, zero hand-labeling.**
Harvest the printed label from each page's own margin text *before* the cleanup
pass tags anything, using a narrow regex over blocks in the top and bottom 12%
bands (arabic, roman, and `Chapter N — M` forms). Cross-check against the
`/PageLabels` tree where the PDF has one. This yields a
`pdf_index → printed_label` map for nearly every page at no labeling cost, and
the map is itself checkable: printed labels in a real book are **monotonic
within a numbering run**, so a broken harvest shows up as a gap or inversion.

**Tier B — hand-labeled, strictly bounded.**
Tier A cannot see pages with no printed label (full-page figures, plates,
chapter openers) and cannot verify that a *chunk's text* is really on the page
it claims. So: **20 anchor phrases per fixture**, each a distinctive string whose
printed page is recorded once by eye, chosen to span front matter, a numbering
restart boundary, ordinary body pages, and at least three figure-heavy pages.

**Total hand-labeling cost across the whole diagnostic effort: 20 anchors × 5
citation-relevant fixtures (F1, F2, F5a, F5b, F5c) = 100 anchors.** That is the
entire manual budget. If a phase wants more, it needs a written justification —
scope creep here is how a diagnostic turns into a labeling project.

- [x] Tier A harvester implemented, with its monotonicity self-check — in
      `measure_phase1.py`. **The self-check earned its place immediately**: it
      flagged 5 breaks on real documents that a coverage count alone would have
      recorded as success.
- [x] Tier A validated against **real** margin furniture via
      `sweep_corpus.py` — and the first version **failed**, harvesting table
      exponents and a math variable as folios. After two instrument-side fixes
      (position-consistency slots, MediaBox-derived bands): `arxiv_twocolumn`
      14/15, `ieee_template` 8/8, **0 wrong labels, 0 monotonicity breaks**. The
      remaining gaps are correct refusals — a title page and a memo that carry
      no folio at all.
      **Note: the fixes were to the harvester, not the parser.** One of them
      (content-extent bands) is the same defect as G4, reproduced in my own
      instrument.
- [ ] Tier A on **scanned** documents — **0/9 on the only mixed-tier fixture
      available.** Unresolved and load-bearing for Phase 4.
- [ ] 100 Tier B anchors recorded in a committed CSV (anchor text + expected
      printed label; the *text* is a short quoted phrase, not redistributed
      content)

**Acceptance:** the harness runs end-to-end on every fixture in the matrix and
emits per-block records including warnings; the Tier A map is validated on 50
spot-checked pages total; the 100 Tier B anchors exist. **No parser quality
claim is made in this phase** — Phase 0 measures the instrument, not the parser.

---

## Phase 1 — Citation Fidelity A: Printed Label vs. PDF Index — ⚠️ PARTIAL (bar FAILED on F5a)

> **Status: PARTIAL — measured on the synthetic control only, and it FAILS.**
> Full results and evidence: [`FINDINGS-PHASE1.md`](./FINDINGS-PHASE1.md).
>
> - **Bar: digital body pages → correct printed label = 0/14 (0%). ❌ FAIL.**
> - The offset is **not constant across the document**: `0` on the roman front
>   matter, `+6` on the arabic body. **No single integer correction fixes it**,
>   and front matter is numerically coincident (offset 0) while still citing
>   `1` where the book prints `i` — so a naive offset check scores it "correct".
> - F5a parses cleanly with **zero warnings**. The extraction is fine; only the
>   citation is wrong. That is what makes this failure silent.
> - **`/PageLabels` is present in the file, ignored by the parser, and
>   unsupported by `lopdf` 0.44** (zero hits for `PageLabel` in the vendored
>   crate source). A fix is a raw catalog-dictionary traversal, not an API call.
> - **Measured on two real textbooks** (OpenStax *Biology 2e*, 1475 pp;
>   *College Physics 2e*, 1671 pp, both fetched to a local-only corpus outside
>   the repo). The offset there is **constant** — `20` and `18`, holding on
>   **100%** of harvested pages — so real books are the *tractable* shape and
>   F5a is the honest worst case. Every citation in both books is still wrong.
> - **`/PageLabels` is absent from 15 of 15 real documents**, including both
>   textbooks. Reading the tree would fix nothing real; ink-harvesting is the
>   load-bearing path.
> - Still outstanding: **F1 (single-column — matrix was wrong, see below)**,
>   F5b, F5c, and all 100 Tier B anchors.

**Mechanism:** the number Aakar shows a student is `page_num` from the chunk
metadata, which is the PDF page index (G1, G12). If the book's front matter
occupies 12 pages, every citation in chapter 1 is off by 12 — silently, and
consistently, which makes it *more* convincing and *more* damaging.

### What gets measured

- [~] For every page of F1, F2, F5a, F5b, F5c: `pdf_index` vs. Tier A printed
      label, reporting the **offset distribution**. **Done for F5a only**
      (offsets `{0, +6}`); F1, F2, F5b, F5c not yet sourced.
- [x] Number of distinct numbering runs per fixture, and whether the offset is
      constant within each run — **F5a: 2 runs, offset constant within each
      (`0` and `+6`), not constant across the document.**
- [ ] For all 100 Tier B anchors: does the chunk containing the anchor carry the
      correct printed label? **Anchors not yet recorded.**
- [x] **F5a specifically** — **done, and the expected answer held.** The tree is
      present (`/Nums [0 <</S /r>> 6 <</S /D /St 1>>]`, verified independently
      with `pikepdf`, so this is not a fixture defect) and the parser ignores it
      entirely: no printed-label field exists anywhere in the output schema.
      **`lopdf` 0.44 exposes nothing** — zero hits for `PageLabel` in the
      vendored crate source, and no number-tree helper. `Document::catalog()`
      does exist, so the dictionary is reachable, but `/Nums`, the `/Kids` chain
      of a nested tree, the `/S` style codes and `/St` start values would all
      have to be walked by hand. **A future fix is a traversal job, not a parse
      job** — sized now rather than discovered mid-fix.

### Pass/fail bar — set before running

| Metric | Bar |
|---|---|
| Digital-native body pages mapping to correct printed label | **100%.** Anything less makes the headline claim false on a document type with no excuse for error. |
| Scanned-fixture pages mapping to correct printed label | **≥95%** |
| Tier B anchors resolving to correct printed page | **≥99/100** |
| Offset constant within a numbering run | Yes/no, per fixture — recorded, not scored |

**Acceptance:** offset table published per fixture; the `/PageLabels` question
answered with evidence. **No fix proposed here** — including the tempting one
(read `/PageLabels`), which is a fix-plan decision, not this document's.

---

## Phase 2 — Citation Fidelity B: Header/Footer Detection vs. the Page Label

**Mechanism:** cross-page heuristic detection tags running heads as `header` or
`footer`; the chunker then **deletes** them (G11). If the printed page label
lives in a running head, the label is destroyed before it ever reaches
retrieval — so even a future `/PageLabels`-free recovery strategy would have
nothing to anchor to.

Source reading (G2, G3) suggests the behaviour splits by label *format*, which
is exactly the kind of thing that must be measured rather than assumed:

- `"Page 12"` → normalizes to `"page"` → clusters across pages → **tagged and
  dropped**.
- `"12"` (bare, the most common textbook form) → normalizes to `""` → hits the
  empty-text `continue` → **never tagged, survives as `body`** — and therefore
  pollutes chunk text with stray numerals.
- `"xii"` → not digits, unique per page → never reaches the 70% threshold →
  **survives as `body`**.

These are three different outcomes from one code path. **Confirm all three
against real documents.** A hypothesis this specific is exactly the kind that
feels true and turns out to be wrong at a boundary.

### What gets measured

- [ ] Per fixture: for every page where a printed label is visually present, is
      that label present anywhere in the output? Tagged as what?
- [ ] Header/footer **precision and recall** against Tier A margin-band labels,
      separating genuine running heads (chapter title, book title) from the page
      label itself. Precision matters more than recall here: a false positive
      deletes real content.
- [ ] Count of stray bare numerals surviving into `body` chunk text (the
      mirror-image failure — noise in retrieval rather than lost provenance).
- [ ] **G4:** whether band thresholds derived from `global_max_y` misbehave on a
      fixture with mixed page sizes. Include one deliberately mixed-size fixture,
      synthesizable, no real content needed.
- [ ] **G5:** whether page 1 is classified differently from pages 2+ in practice,
      measured by running each fixture whole and then again with page 1 removed.

### Pass/fail bar — set before running

| Metric | Bar |
|---|---|
| Pages whose printed label is *recoverable somewhere* in output | **100%.** Below this, page-label recovery is impossible in principle downstream — the strictest bar in this document, and deliberately so. |
| Header/footer precision on non-label running heads | **≥0.95** |
| Header/footer recall on non-label running heads | **≥0.85** (recall failures leave noise; precision failures destroy content) |
| Stray bare numerals in body chunks | Counted and reported; no bar (input to the fix plan) |

**Acceptance:** a per-fixture table of label format → tag assigned → survives
into chunk? — with the three-way format hypothesis explicitly confirmed or
refuted.

---

## Phase 3 — Citation Fidelity C: Two-Column Reading Order

**Mechanism:** on a two-column page, mis-clustering produces text that is
*correct* but *ordered wrong*. The chunk's page number is right; its content is
spliced across columns. For Aakar this attaches the wrong prose to a clicked
part of a 3D model — a failure that reads as a hallucination but is really an
ingest bug, and one that will be diagnosed as a model problem unless it is
measured here first.

Per G6, the specific uncovered window is a block **wider than one column but
under 65% of content width, straddling the gutter** — a wide figure caption, a
spanning equation, or a table that isn't wide enough to be treated as a swath
boundary. Any such block unions both columns transitively into one.

### What gets measured

- [ ] **Adjacent-pair inversion rate** on F2: for consecutive block pairs in
      emitted reading order, what fraction are in the wrong order relative to
      human reading order? This avoids labeling a full permutation per page —
      pairwise checks over ~30 sampled pages are enough to estimate the rate.
- [ ] **Cross-column interleaving count:** how many times does emitted order
      jump from column A to column B and back within one swath? This is the
      failure that actually corrupts meaning; a single adjacent inversion inside
      one column usually does not.
- [ ] **Gutter-straddler census:** count blocks on each F2 page whose width falls
      in the (column width, 65% content width) window. Correlate with the pages
      that show interleaving. **This is the step that turns a rate into a
      mechanism** — without it Phase 3 produces a number and no diagnosis.
- [ ] Whether `page_width` derived from content extent (G6) rather than MediaBox
      shifts the 65% threshold on pages with narrow content.

### Pass/fail bar — set before running

| Metric | Bar |
|---|---|
| Adjacent-pair inversion rate on two-column body prose | **≤2%** |
| Cross-column interleavings on body prose | **0** on ≥90% of pages |
| Straddler-to-interleaving correlation | Reported as a mechanism claim, supported or refuted |

**Acceptance:** inversion rate and interleaving count published for F2 and
`arxiv_twocolumn.pdf`, with the straddler census either explaining the failures
or explicitly failing to — a refuted mechanism is a valid, publishable result
here.

---

## Phase 4 — OCR Noise

**Mechanism:** students photograph and scan their own textbooks. Tier 2 quality
directly bounds answer quality on the most common real input.

F3a (scanned twin of F1) is what makes this cheap: the digital original supplies
exact ground-truth text, so character error rate is computable without anyone
transcribing anything.

### What gets measured

- [ ] **CER and WER** on F3a against F1's digital text, aligned per page.
- [ ] The same on F3b (phone photo) — no exact ground truth, so score against
      the Tier B anchors only, plus a qualitative read of 5 pages.
- [ ] **Page attribution under OCR:** confirm each OCR block lands on the page it
      was rendered from. `extract_page_ocr` shells out to `pdftoppm` per page and
      globs the first PNG in a temp dir; verify this cannot cross-attribute on a
      multi-page document.
- [ ] **Silent-fallback census:** how many pages fall back to OCR with an empty
      `warnings` array? Per G7 the expected answer is "all of them," since the
      fallback emits no warning at all. Confirm, and record the count — this is
      the single most load-bearing input to Phase 7.
- [ ] Confidence-filter behaviour on degraded input: how much *real* text is
      discarded alongside noise (the README already flags this; quantify it).

### Pass/fail bar — set before running

| Metric | Bar |
|---|---|
| CER on F3a (clean 300dpi scan of known text) | **≤5%** |
| WER on F3a | **≤10%** |
| Tier B anchors retrievable from F3b | **≥16/20** |
| OCR page cross-attribution | **0 instances** — a hard zero; this would corrupt citations directly |

**Acceptance:** CER/WER tables published; the page-attribution question answered
with a hard yes or no.

---

## Phase 5 — Encrypted PDFs

**Mechanism:** textbook PDFs routinely carry owner passwords. Per G9 there is no
encryption handling anywhere in the source. The likely path — to be confirmed,
not assumed — is that `Document::load_mem` parses the structure, content streams
fail to decode, text comes back empty, and the document routes to OCR exactly as
a scan would. Aakar would then ingest an encrypted book as a low-quality scan
rather than rejecting it.

### What gets measured

- [ ] Behaviour across the encryption cases: owner-password-only (printing/copy
      restricted, openable), user-password (cannot open without password), and
      AES-256 vs. RC4. All synthesizable with `qpdf` — **no real content needed
      for this phase**, so use a synthetic base document throughout.
- [ ] For each: does it raise a typed `ParseError`, return empty text, or
      silently OCR? Record `tier`, `warnings`, block count, and exception type.
- [ ] **Pre-flight detection investigation** (explicitly requested): can
      encryption be detected *before* extraction is attempted? Determine whether
      `lopdf` exposes `is_encrypted()` (introduced 0.39; the repo is on 0.44) or
      the `/Encrypt` trailer entry, and whether that check is reliable across the
      cases above. Report **what a clean early rejection would need**, and where
      in the current flow it would have to sit — describing the gap, not closing
      it.
- [ ] Whether encryption is currently distinguishable from generic corruption in
      the output. Per the README, corrupt ASCII85 already produces
      `tier: "scanned"` + empty warnings; if encryption produces the identical
      signature, the two are indistinguishable to any caller — which is the
      finding that matters.

### Pass/fail bar — set before running

| Metric | Bar |
|---|---|
| Encrypted PDFs producing an explicit, typed rejection | **100%** (expected to fail — this bar exists to size the gap, not to be met) |
| Encrypted PDFs silently routed to OCR | **0** (same) |
| Pre-flight detection viability | Answered yes/no with evidence from `lopdf` 0.44's API |

**Acceptance:** a behaviour table across all encryption variants, plus a written
answer on pre-flight detection viability. **A failing bar here is a successful
phase** — the point is to size the gap precisely, and a bar set where it *should*
be is what makes the size legible.

---

## Phase 6 — CID/Type0 Fonts

**Mechanism:** Devanagari and display math are Type0/CID-encoded. The repo
already has an unquantified signal: `tests/fixtures/tier1/XeLaTeX.pdf` produces
CJK text with replacement and surrogate artifacts (`\udc81`, `\xad`) mixed into
otherwise-correct glyphs, recorded in `ASCII_PHASES.md` with no baseline and no
measurement. **This phase quantifies what is currently only anecdotal.**

### What gets measured

- [ ] Glyph-level accuracy on F4a (Devanagari) and F4b (math), scored against a
      Tier B anchor set — 20 anchors each, drawn from the existing 100-anchor
      budget where they overlap citation fixtures, otherwise added and counted.
- [ ] **Corruption detectability:** when a glyph fails to map, what appears in
      the output? Replacement char, surrogate, silently dropped, or wrong glyph?
      Silent dropping and wrong glyphs are far worse than a visible `�`,
      because a downstream consumer can filter the latter.
- [ ] Whether any warning is emitted on ToUnicode failure. Per G7, expected: no.
- [ ] Quantify the CJK artifacts in `XeLaTeX.pdf` to give the existing anecdote
      a number, and establish the baseline that `ASCII_PHASES.md` notes is
      missing.

### Pass/fail bar — set before running

| Metric | Bar |
|---|---|
| Devanagari anchor retrieval | **≥17/20** |
| Math-chapter anchor retrieval | **≥17/20** |
| Corruption is *detectable* (visible replacement char, not silent) | **100%** — the bar that actually matters, since detectable corruption can be handled downstream and silent corruption cannot |

**Acceptance:** glyph accuracy numbers exist for both scripts; the corruption
mode is characterized as detectable or silent, with examples.

---

## Phase 7 — Warnings as a Provenance-Strength Signal

**The idea:** rather than fixing every parser weakness, Aakar consumes the
existing signal and surfaces degraded extraction in the UI as *weak provenance*.
A citation from a clean digital page renders differently from one recovered off
a blurry photo. This turns a parser limitation into a product feature — but only
if the signal is granular enough to attach to a specific chunk.

**This phase is diagnostic. Describe the current state and the gap; do not
implement the change.**

### What gets measured

- [ ] **Inventory every warning the parser can emit.** Per G7 the answer appears
      to be exactly one — the unsupported-filter message. Confirm exhaustively by
      source audit, then corroborate against the actual warnings collected across
      every fixture run in Phases 1–6.
- [ ] **Granularity assessment.** Per G8, `warnings` is a flat `Vec<String>` on
      the document with the page number embedded in prose. Determine: can a
      warning be tied to the specific chunk it affects, today? Expected answer:
      **no** — the page is parseable out of the message text by regex, but that
      is string-scraping a human-readable string, not a contract, and there is no
      block-level association at all.
- [ ] **Census of degradations that currently emit nothing.** From Phases 4, 5,
      and 6: OCR fallback (Phase 4), encryption (Phase 5), ToUnicode failure
      (Phase 6), corrupt-but-supported filters (already documented in the
      README). Each is a silent quality loss that a provenance signal would need
      to cover.
- [ ] **What already works per-chunk.** Not everything is missing: `source`
      (`"digital"` / `"ocr"`) is a genuine per-block field and does reach chunk
      metadata as `source_type`. Assess how far a provenance signal could get on
      that alone — **subject to G14**, the trailing-chunk bug that can mislabel
      `source_type` from `blocks[-1]`. Measure how often G14 actually fires
      across the corpus; if it is rare, `source` is already a usable v1 signal
      and the warnings work may not be on Aakar's critical path at all.
- [ ] **Describe the gap:** what would have to change for warnings to be
      chunk-attachable. Structured warning records with page and ideally block
      references; a warning for each silent degradation above. Describe the
      shape. Do not build it.

### Pass/fail bar — set before running

This phase has no pass/fail bar, deliberately. It is a **characterization**, and
inventing a threshold for "is the warnings array granular enough" would be
scoring a design question as if it were a measurement. Its output is a written
assessment plus the two counts above (warnings that exist; degradations that emit
nothing).

**Acceptance:** a written answer to "can a warning be attached to the chunk it
affects, today?" backed by the source audit and the corpus-wide warning census —
plus a recommendation on whether `source`-based provenance is sufficient for
Aakar v1 without any parser change.

---

## Dropped: tables, and why

**No table diagnostic phase. Dropping it rather than including it for
completeness**, per the scope instruction.

Reasoning:

1. Aakar needs structural prose — chapter text describing the human eye, a
   neuron, the OSI stack. It does not query tabular data.
2. Failure here is **not silent in the dangerous way**. Per the README, tables
   without captions or regular geometry fall back to flat text: content is
   preserved, structure is not. That degrades a chunk's readability; it does not
   fabricate a page citation.
3. The chunker already handles both branches explicitly — `type == "table"` is
   serialized to markdown rows, everything else via `text`
   ([`chunker.py:36-57`](lightningparse-api/chunking/chunker.py#L36-L57)). There
   is no silent-drop path for table blocks.

**One residual risk, folded into Phase 0 as a single check rather than a phase:**
a *false-positive* table detection on prose would reshape body text into
markdown pipe-rows, mangling a chunk without losing it. Phase 0's per-block dump
already emits block `type`, so this costs one assertion — count `table` blocks
across F1/F2 and eyeball any that appear outside a real table. If that count is
zero across the corpus, the question is closed. If it isn't, that finding earns
a phase in the follow-up plan; it does not get one pre-emptively here.

---

## Consolidated pass/fail bars

Every bar below was **written down before any fixture was run**, which is the
point of recording them in one place.

| Phase | Metric | Bar |
|---|---|---|
| 1 | Digital body pages → correct printed label | 100% |
| 1 | Scanned pages → correct printed label | ≥95% |
| 1 | Tier B anchors → correct printed page | ≥99/100 |
| 2 | Printed label recoverable somewhere in output | 100% |
| 2 | Header/footer precision (non-label running heads) | ≥0.95 |
| 2 | Header/footer recall (non-label running heads) | ≥0.85 |
| 3 | Adjacent-pair inversion rate, two-column prose | ≤2% |
| 3 | Pages with zero cross-column interleaving | ≥90% |
| 4 | CER on F3a | ≤5% |
| 4 | WER on F3a | ≤10% |
| 4 | Tier B anchors retrievable from F3b | ≥16/20 |
| 4 | OCR page cross-attribution | 0 |
| 5 | Encrypted PDFs explicitly rejected | 100% (expected to fail; sizes the gap) |
| 5 | Encrypted PDFs silently OCR'd | 0 (same) |
| 6 | Devanagari anchor retrieval | ≥17/20 |
| 6 | Math anchor retrieval | ≥17/20 |
| 6 | Corruption detectable, not silent | 100% |
| 7 | — | No bar; characterization only |

---

## What this document deliberately does not do

- **No fixes.** Not even the obvious ones. "Read `/PageLabels`" is a small change
  and is still out of scope — because the point is to find out whether it is the
  *right* change before writing it, and Phase 1 may well show that F5b (no
  `/PageLabels` tree at all) is the common case and the fix has to be
  label-harvesting instead.
- **No general modernization.** Nothing here about performance, API surface,
  dependency currency, or test coverage generally.
- **No table phase.** Dropped with reasoning above.
- **No claim that LightningParse is or isn't good enough.** That conclusion
  requires the numbers this document is designed to produce, and stating it now
  would repeat the exact mistake that prompted the document.

## Sequencing

Phase 0 gates everything — it builds the instrument and the ground truth.
Phases 1–3 are the priority and should run together, since they share fixtures
and the Tier A/B ground-truth machinery. Phases 4–6 are independent of each
other and can run in any order. **Phase 7 must run last**, because its central
census — degradations that emit no warning — is assembled from what Phases 4, 5,
and 6 actually observe.

This project has no deadline; a different one does (2026-09-05). If time is
short, **Phase 0 + Phases 1–3 alone** answer the question that actually gates
Aakar's headline claim. Phases 4–7 are the second tranche.
