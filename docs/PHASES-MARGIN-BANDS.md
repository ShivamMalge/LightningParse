# PHASES-MARGIN-BANDS.md

Fix plan for the **content-loss defects G4 and G5** in `cleanup::detect_headers_footers`,
diagnosed in [`FINDINGS-CONTENT-EXTENT-BANDS.md`](./FINDINGS-CONTENT-EXTENT-BANDS.md).

Follows the same plan-before-implement, verify-before-proceeding discipline as
[`PHASES.md`](./PHASES.md), [`PHASES-EXTRACTION-FIDELITY.md`](./PHASES-EXTRACTION-FIDELITY.md),
and [`ASCII_PHASES.md`](./ASCII_PHASES.md).

> **Status: Phases 1–4 COMPLETE and verified. Phase 5 partially complete —
> documentation done, release deliberately NOT cut (version unscoped, pending
> review).**
>
> - `cargo test` — **47 passed / 0 failed** (28 unit incl. 9 new geometry tests,
>   8 cleanup incl. 5 new regression tests, 11 integration)
> - `cargo clippy --all-targets --release -- -D warnings` — clean
> - **Phase 4 acceptance: PASS.** The fixed binary produced **exactly** the 19
>   forecast blocks, with **0** newly tagged, and the simulated new behaviour
>   reproduces the fixed parser exactly on all 7 fixtures
>   (`benchmarks/diagnostic/verify_fix.py`).

---

> ## Scope: two conservative defects only
>
> **IN — both strictly *reduce* how much gets tagged as page furniture.** Since
> everything tagged as furniture is deleted by the chunker, neither change can
> increase content loss:
> - **G4** — margin bands computed from content extent instead of page geometry
> - **G5** — the page-1 fallback tagging header/footer on position alone
>
> **OUT — deliberately, and must not be bundled:**
> - **G3** — `normalize_text` strips digits, so a bare folio normalises to `""`
>   and can never be tagged furniture at any band or threshold
> - **The 70% cluster threshold** — under-fires so badly that a 1475-page textbook
>   gets **zero** furniture tagged. Any change here makes deletion *more*
>   aggressive and has no defensible value without Phase 2 precision/recall.
>
> Bundling the OUT items would put an unmeasured, deletion-increasing change
> inside a release whose purpose is to stop deleting things.

---

## Evidence base

Measured against `lightningparse` 0.4.1 built from the current tree (not the
stale published 0.2.0 wheel). Reproduce with
`python benchmarks/diagnostic/measure_g4.py` and
`python benchmarks/diagnostic/simulate_cleanup.py`.

- **9 blocks of real content deleted across 4 of 4 documents** initially tested;
  band displacement −26.9 pt to −54.8 pt.
- Casualties include a memo's `To:`/`From:` fields, a paper's author line and
  title, a chapter heading, and — on real textbook chapters — **`"CHAPTER 4"` /
  `"Cell Structure"` and `"CHAPTER 26"` / `"Vision and Optical Instruments"`,
  i.e. the chapter's own title.**
- **The band and the 70% threshold are independent.** Under both band
  definitions, zero clusters meet the threshold on *Biology 2e*. Fixing the band
  cannot deepen the under-detection problem.
- **Attribution: 1 block to G4, 8 to G5.** They are separate defects sharing one
  root cause.

---

## Decisions to resolve before implementing

Recorded here rather than defaulted silently, per this repo's convention.

### D1 — MediaBox or CropBox?

`/CropBox` is what a viewer displays; `/MediaBox` is the full sheet and may
include printer bleed. Where they differ, the *visible* page is CropBox, so a
margin band should arguably follow it.

**Recommendation: prefer `/CropBox` when present and non-degenerate, else
`/MediaBox`.** Every fixture measured so far has no CropBox, so this changes
nothing observed — it is future-proofing against print-oriented PDFs, where
using MediaBox would reintroduce exactly the over-reach being fixed.

### D2 — Attribute inheritance

`/MediaBox` and `/CropBox` are **inheritable** page-tree attributes: a leaf
`/Page` may omit them and rely on an ancestor `/Pages` node.

`page_tree.rs` already tolerates leaves with no attributes
(`test_inherited_page_attributes`), but **nothing resolves an inherited
*value*** — and `lopdf` 0.44 offers no helper (no page-geometry accessor exists
in its `document.rs`). The `/Parent` chain must be walked by hand, with a visited
set, since `page_tree.rs` already documents that malformed trees can contain
cycles.

### D3 — Page rotation

`/Rotate` of 90 or 270 swaps effective width and height. A band computed from an
unrotated box on a rotated page would be wrong on the other axis.

**Recommendation: read `/Rotate` (also inheritable), normalise to 0/90/180/270,
and swap the height used for banding when 90 or 270.** No fixture currently
exercises this — a synthetic rotated fixture should be added rather than leaving
it untested.

### D4 — Fallback when geometry is unavailable

If no usable box is found, or it is degenerate (zero/negative height),
**fall back to the current content-extent behaviour.** This guarantees the change
is a strict improvement: PDFs that work today cannot get worse.

### D5 — Schema: expose page geometry?

Cleanup runs on `output::Page`, which carries only `page_num` and `blocks`
([`output/mod.rs:13-17`](../lightningparse-core/src/output/mod.rs#L13-L17)), so
geometry must be plumbed from extraction.

**Recommendation: add optional `page_width` / `page_height` to `output::Page`.**
Additive, so no consumer breaks. It is also **independently useful**: the
diagnostic harness had to open every PDF a second time with `pikepdf` purely to
recover page dimensions the parser already had in hand. Requires an
`ARCHITECTURE.md` §3.1 schema note and a decision-log entry.

### D6 — Which half of the page-1 fallback to remove?

The fallback has three branches: footnote, header, footer.
[`cleanup/mod.rs:133`](../lightningparse-core/src/cleanup/mod.rs#L133) is the
**only site in the entire codebase that ever assigns `section_id: "footnote"`**.
Removing the fallback wholesale would make a documented schema value dead.

**Recommendation: keep the footnote branch, remove only the header/footer
branches** — those are the ones that tag on position alone with no cross-page
corroboration. Verified to matter: the surgical variant preserves the `∗ † ‡`
markers on `arxiv_twocolumn.pdf` p1 that a wholesale removal would have dropped
(19 lost tags instead of 22).

---

## Phase 1 — Plumb page geometry

- [x] Resolve the effective page box per page: CropBox → MediaBox → inherited via
      `/Parent` (cycle-safe) → `None` (D1, D2)
- [x] Apply `/Rotate` normalisation (D3)
- [x] Add `page_width` / `page_height` to `output::Page` as `Option<f64>` (D5)
- [x] Unit tests: explicit box; inherited box; **cyclic** `/Parent` chain must
      terminate; missing box → `None`; degenerate box → `None`; `/Rotate 90`
      swaps the effective height

**Acceptance:** `cargo test` green. Geometry appears in JSON for every corpus
fixture and matches `pikepdf`'s MediaBox for each — an independent oracle, not
self-report.

---

## Phase 2 — G4: bands from page geometry

- [x] `detect_headers_footers` uses the page's own effective height for both the
      cross-page band and the page-1 references, replacing `global_max_y` and
      `page_max_y`
- [x] Fall back to content extent when geometry is `None` (D4)
- [x] This also removes G4's **cross-page coupling** — bands become per-page, so
      one tall page can no longer move every other page's band
- [x] Add a **mixed-page-size fixture** (synthetic, no real content) to exercise
      the coupling that no current fixture covers — `benchmarks/diagnostic/fixtures/mixed_pagesize.pdf`
      (3x Letter + 1x 612x1200, generated by `make_mixed_pagesize.py`), covered by
      `test_mixed_page_sizes_band_independently`

**Acceptance:** on `f5a_pagelabels.pdf` the p7 chapter heading `"The Human Eye"`
is no longer tagged `header`. Full corpus regression shows no *newly* tagged
furniture anywhere (the simulation predicts **0 gained tags** — treat any gain as
a failed acceptance, not a curiosity).

---

## Phase 3 — G5: reduce the page-1 fallback to its footnote branch

- [x] Remove the unconditional page-1 header and footer branches
- [x] **Keep** the footnote branch (D6)
- [x] Regression test asserting `section_id: "footnote"` is still produced for
      `arxiv_twocolumn.pdf` p1's `∗ † ‡` markers — this is the guard that stops a
      future cleanup from quietly deleting the last footnote path

**Acceptance:** page 1 is classified by the same rules as every other page,
except for footnotes. On `digital_word_export.pdf`, `"CONFIDENTIAL MEMORANDUM"`,
`"To: Engineering Team"` and `"From: Architecture Group"` all reach the chunker.

---

## Phase 4 — Verify against the pre-computed prediction

The diff is already predicted. `simulate_cleanup.py` re-implements the current
logic in Python and **was validated to reproduce the real parser's `section_id`
exactly on all 7 fixtures** before being used to forecast anything.

- [x] Re-run `simulate_cleanup.py` against the **fixed** binary. Config A (the
      simulated *old* behaviour) must now differ from the real output in exactly
      the predicted places — **no more, no fewer**
- [x] Confirm the observed change set is exactly the 19 blocks below

### Predicted change set — 19 blocks, all judged

| Fixture | Blocks | Content | Verdict |
|---|---|---|---|
| `f1_biology_cell_structure.pdf` | 2 | `"CHAPTER 4"`, `"Cell Structure"` | ✅ **Fix** — the chapter's own title |
| `f2_physics_vision.pdf` | 2 | `"CHAPTER 26"`, `"Vision and Optical Instruments"` | ✅ **Fix** |
| `digital_word_export.pdf` | 3 | `"CONFIDENTIAL MEMORANDUM"`, `"To:"`, `"From:"` | ✅ **Fix** |
| `ieee_template_placeholder.pdf` | 2 | paper title, author line | ✅ **Fix** |
| `mixed_test.pdf` | 2 | paper title (2 lines) | ✅ **Fix** |
| `f5a_pagelabels.pdf` | 3 | title, subtitle, p7 chapter heading | ✅ **Fix** |
| `f5a_pagelabels.pdf` | 1 | folio `"i"` on p1 | ⚠️ **Accepted regression** |
| `arxiv_twocolumn.pdf` | 3 | Google reproduction-rights notice | ⚠️ **Debatable** |
| `arxiv_twocolumn.pdf` | 1 | NIPS conference footer | ⚠️ **Accepted regression** |

**14 fixes, 5 accepted regressions.** The regressions are all *noise* — a stray
folio and two lines of conference/licence metadata now flowing into chunks. The
fixes are all *content* — titles, authors, chapter headings that are currently
deleted and unrecoverable. **Noise is retrievable and filterable; deleted content
is neither.** That asymmetry is the whole argument for shipping.

Note the folio regression makes page 1 *consistent* with pages 2+, where G3
already prevents bare folios from ever being tagged. It is not a new class of
problem; it is the existing behaviour applied uniformly.

- [x] `cargo clippy --all-targets -- -D warnings` clean
- [x] Manual JSON inspection of at least `f1_biology_cell_structure.pdf` and
      `digital_word_export.pdf` — not inferred from a passing test count

---

## Phase 5 — Documentation and release

- [x] `ARCHITECTURE.md` §3.1: document `page_width`/`page_height`; decision-log
      entry covering D1–D6 and **why G3 and the threshold are excluded**
- [x] `README.md` Known Limitations: the under-detection problem is *not* fixed
      by this release and should be stated plainly — furniture removal still
      fails on long documents, and bare folios are still never tagged
- [ ] Release notes state the behaviour change directly: **fewer blocks are
      tagged as page furniture, so more content reaches downstream consumers.**
      Anyone relying on aggressive header stripping will see more furniture text
- [ ] **Release-order rule** from `ASCII_PHASES.md`: every content commit,
      README included, must land **before** the tag is cut

**Version:** still deferred — to be scoped by the maintainer. No tag cut, nothing published.

---

## Why this is worth jumping the queue

The remaining Phase 1 diagnosis (single-column F1, F5b/F5c, 100 Tier B anchors)
refines a number whose shape is already known: the citation offset is constant at
20 and 18 on real textbooks, and **0 of 15 real documents carry `/PageLabels`**.
More fixtures would sharpen that, not change it.

Meanwhile G4 and G5 are deleting title pages, author lines and chapter headings
from every current LightningParse user's output, silently — no warning, `tier`
unchanged, `warnings` empty. This is a correctness bug independent of Aakar and
independent of citation fidelity.
