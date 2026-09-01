# FINDINGS-CONTENT-EXTENT-BANDS.md

**A live content-loss bug in LightningParse's cleanup pass, logged separately
from the page-labeling work because its implications are broader.**

Status: **CONFIRMED on 4 of 4 real documents tested.** Diagnosis only — nothing
fixed. Measured 2026-08-30 against `lightningparse` 0.4.1 built from the current
tree (not the stale published 0.2.0 wheel; see
[`FINDINGS-PHASE1.md`](./FINDINGS-PHASE1.md)).

Reproduce: `python benchmarks/diagnostic/measure_g4.py`

---

## The question this answers

This was surfaced while building the Phase 1 diagnostic harness: my *own*
harvester had a content-extent band bug, and the natural question followed —
**is the same defect live in the parser itself, beyond page-number harvesting?**

**Yes.** It is not a harness artifact, and it is not confined to citation
fidelity. It causes **silent deletion of real body content** from retrieval, on
every document tested.

---

## Mechanism

`cleanup/mod.rs` decides whether a block sits in a page's margin by comparing it
against a fraction of **content extent** — the tallest block seen — rather than
against the page's actual **MediaBox** height. Nothing in the cleanup pass ever
reads page geometry.

There are two such paths, and they use *different* reference heights. Keeping
them apart matters: conflating them inflates G4 by 8×.

| | Reference height | Applies to | Finding |
|---|---|---|---|
| Cross-page band | `global_max_y * 0.90` — tallest block in the **whole document** ([`cleanup/mod.rs:31-49`](../lightningparse-core/src/cleanup/mod.rs#L31-L49)) | all pages | **G4** |
| Page-1 fallback | `page_max_y * 0.90` — tallest block **on page 1** ([`cleanup/mod.rs:124-147`](../lightningparse-core/src/cleanup/mod.rs#L124-L147)) | page 1 only, no cross-page corroboration | **G5** |

Because a page's content essentially never reaches the physical top of the
paper, both references are systematically *lower* than the true margin, so both
bands reach **down into body text**. A block caught this way is tagged `header`
or `footer`, and the chunker then **drops it outright**
([`chunker.py:33`](../lightningparse-api/chunking/chunker.py#L33)) — it never
reaches retrieval.

G4 carries a second consequence G5 does not: `global_max_y` is a single
document-wide number, so **one unusually tall page moves the band on every other
page.** Untested — it needs a mixed-page-size fixture — but it follows directly
from the code.

---

## Measured

Band displacement is the gap between where the parser's band starts and where a
geometry-derived band would start. Every document tested is displaced downward.

| Fixture | Pages | Band displacement | Tagged furniture | **Over-reach** |
|---|---|---|---|---|
| `f5a_pagelabels.pdf` | 20 | **−29.7 pt** | 18 | **3** |
| `arxiv_twocolumn.pdf` | 15 | **−54.8 pt** | 4 | **3** |
| `ieee_template_placeholder.pdf` | 8 | **−26.9 pt** | 2 | **1** |
| `digital_word_export.pdf` | 2 | **−28.2 pt** | 3 | **2** |
| | | | | **9 total** |

−54.8 pt is roughly three quarters of an inch of extra reach on every page of
that document.

### Attribution

| Mechanism | Blocks |
|---|---|
| **G5** (page-1 fallback, per-page content extent) | **8** |
| **G4** (cross-page band, document-wide content extent) | **1** |

G5 dominates because the page-1 fallback needs no cross-page corroboration —
it tags anything above the line on sight. G4's single instance is
`f5a_pagelabels.pdf` p7, where a chapter heading at y=700 fell inside a band
starting at 683.1 that a MediaBox-derived band (712.8) would have excluded.

### What was actually deleted

| Document | Content dropped | Fair call? |
|---|---|---|
| `digital_word_export.pdf` | `"To: Engineering Team"`, `"From: Architecture Group"` | ❌ No — memo recipient and sender |
| `ieee_template_placeholder.pdf` | `"Anonymous Authors, Example University"` | ❌ No — the author line |
| `f5a_pagelabels.pdf` p1 | title and subtitle | ❌ No — the entire title page |
| `f5a_pagelabels.pdf` p7 | `"The Human Eye"` chapter heading | ❌ No — a chapter heading |
| `arxiv_twocolumn.pdf` p1 | Google reproduction-rights notice (3 blocks) | ⚠️ **Debatable** — arguably genuine page furniture |

**8 of 9 are clearly wrong. 1 is debatable** and is reported as such rather than
counted as a clean win.

On `f5a_pagelabels.pdf`, page 1 ends up contributing a **single meaningless
token** to retrieval — its title, subtitle and page label all deleted, leaving
only an anchor string. On a real textbook that is the title page; on a chapter
opener, the chapter title.

---

## Why this matters beyond citation fidelity

The page-label work cares about this because a deleted running head takes the
folio with it. But the blast radius is wider, and this is the part that warrants
a separate finding:

- **Retrieval recall, not just citation accuracy.** Content that never enters
  the index cannot be retrieved at any relevance threshold. No amount of
  downstream tuning recovers it.
- **It is biased toward the highest-value blocks.** Titles, author lines,
  chapter headings and memo fields all live near the top of a page — exactly
  where the band over-reaches. This preferentially eats the most
  semantically-dense, most retrieval-useful lines in the document.
- **It is silent.** No warning is emitted (consistent with **G7**: exactly one
  warning string exists in the whole codebase). `tier` stays `"digital"`,
  `warnings` stays empty. Nothing distinguishes a document that lost its title
  from one that did not.
- **Page 1 is disproportionately hit** by the G5 path, and page 1 carries title,
  author, abstract — the block a "what is this document about" query most needs.

---

## The band and the threshold are INDEPENDENT failures

The obvious worry about a MediaBox fix is that narrowing the band would worsen
detection — and `Biology 2e` already tags **zero** furniture across 70,269
blocks. If the two were coupled, fixing over-reach would deepen under-detection,
and this could not ship on its own.

**Measured on `Biology 2e` (1475 pp), they are not coupled:**

| Band definition | Top-band blocks | Bottom-band blocks | Clusters meeting the 70% threshold |
|---|---|---|---|
| Parser (content extent, top > 691.1) | 5301 | 1368 | **0** |
| MediaBox (top > 712.8) | 2758 | 1575 | **0** |

Zero either way. The binding constraint is the **70%-of-pages cluster
threshold**, not the band: the largest real cluster is
`"access for free at openstax.org"` — a genuine book-wide footer — on **734 of
1475 pages**, needing 1033 to qualify. It is a footer, it should be stripped,
and it is not.

A third defect compounds it: **G3**. `normalize_text` strips digits, so a bare
folio normalises to `""` and is skipped before any tagging branch. **A bare page
number can never be tagged furniture at any band or any threshold.**

### Consequence for sequencing

Three independent defects in one function, pulling in two directions:

| # | Defect | Effect | Fix direction | Risk |
|---|---|---|---|---|
| 1 | **G4** band from content extent | deletes real content | derive from MediaBox | **Low** — strictly narrows the candidate set, so it can only *reduce* over-tagging |
| 2 | **G5** page-1 fallback, no corroboration | deletes real content (8 of 9 observed) | require cross-page corroboration | **Low** — same direction |
| 3 | 70% cluster threshold | removes no furniture on long books | **unknown** — no principled replacement value | **High** — needs Phase 2 precision/recall |

Defects 1 and 2 are **conservative**: both strictly reduce how much gets tagged
as furniture, and everything tagged as furniture is deleted. Neither can increase
content loss. Defect 3 is the opposite — any change makes deletion *more*
aggressive, and it has no defensible value without measurement.

**They should therefore not ship together.** 1 and 2 are a content-loss fix that
can be verified with the fixtures already in hand. 3 is a tuning problem that
needs Phase 2. Bundling them would put an unmeasured, deletion-increasing change
inside a release whose purpose is to stop deleting things.

---

## What is *not* established

- **No precision/recall figure against labelled ground truth.** These 9 are
  blocks that a geometry-derived band would have excluded. That is a strong
  signal of over-reach, not a scored error rate. Establishing the real rate is
  Phase 2's job.
- **The reverse direction is unmeasured.** Whether a geometry-derived band would
  *under*-detect genuine furniture that the current band correctly catches has
  not been tested. **Not a fix recommendation** — the trade-off is unquantified.
- **G4's cross-page coupling is untested.** All fixtures here are single-page-size.
  A mixed-page-size fixture is needed, and is cheap to synthesize.
- **Only 4 documents, none of them textbooks.** Direction is clear and
  consistent; the rate is not established.

## Relationship to the phase plan

This is **not new scope** — G4 and G5 were already recorded in `NEW_PHASES.md`
and assigned to **Phase 2**. What is new is that they are now **confirmed live
with measured consequences**, rather than hypotheses read out of source. Phase 2
should treat the mechanism as established and spend its effort on the rate and
on the precision/recall trade-off, not on re-confirming existence.

**Update:** the MediaBox trade-off has since been measured (see above) and is
**low-risk and independent** of the under-detection problem. That is enough to
justify treating defects 1 and 2 as a fix candidate outside this diagnostic
document — see the sequencing table. Defect 3 stays diagnostic-only.
