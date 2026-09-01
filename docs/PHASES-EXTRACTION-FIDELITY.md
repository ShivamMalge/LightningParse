# PHASES-EXTRACTION-FIDELITY.md

Detailed build plan for fixing the block-fragmentation bugs found in `lightningparse-extraction-issues.md` and adding heuristic-based semantic block typing (heading, code) on top of corrected extraction. Follows the same phase-by-phase, verify-before-proceeding discipline as `PHASES.md`.

**Do not start Phase 2 until Phase 1 is fixed and independently verified.** Semantic typing built on top of fragmented extraction will inherit and potentially mask the underlying bug — a heading heuristic could misfire on a block that's only a fragment of the real line.

---

## Phase 1 — Fix Same-Line Run Fragmentation

**Goal:** stop splitting single visual lines into multiple blocks when a font/style change occurs mid-line, and stop splitting words mid-run entirely. This is a Tier 1 extraction correctness bug, not a cleanup/heuristic issue — it belongs in `extract/mod.rs`, not `cleanup/mod.rs`.

### Root cause (per the bug report)
The extractor currently treats each text-showing operation from the PDF content stream as a block boundary. When a PDF generator emits a style change mid-line (e.g., a resume template bolding a label like "UI Components:"), the content stream issues a new text-showing operation for the styled run — and the extractor is turning that operation boundary into a block boundary, even though visually it's the same line with no gap.

### Required fix
- [ ] Before finalizing blocks, check whether two consecutive text runs share the same (or near-identical, within a small epsilon) baseline y-coordinate
- [ ] If same baseline AND the horizontal gap between the end of run A and the start of run B is ~0 (no whitespace-width gap), concatenate them into a single continuous text run *before* block segmentation — regardless of font, weight, or size change between them
- [ ] This must handle the exact word-split case: `UI Co` + `mponents:` → `UI Components:`, with no extra/missing space
- [ ] This must also handle the label:value line case: `Frontend:` + ` Next.js, React, TypeScript...` → one block, one continuous sentence
- [ ] Style-change information should not be discarded outright — see the "carry forward" note below for how this feeds Phase 2

### Design question to resolve before implementing
The bug report suggests two options for handling the style/font info that triggered the false split:
1. Drop it — just merge the text, treat style as irrelevant to block structure
2. Preserve it — add a `spans` array to the `Text` block variant, recording style-region boundaries (e.g., `[{start: 0, end: 3, bold: true}, {start: 3, end: 15, bold: false}]`) alongside the now-continuous `text` field

**Recommendation: implement option 2.** Reasoning: Phase 2 of this plan (heading/code detection) needs font-size and weight information to work at all. If style info is discarded in Phase 1, Phase 2 would have nothing to detect against except line length — a much weaker signal. Preserving spans now avoids re-deriving this information later and avoids a second pass through the raw content stream.

### Schema change
Update `ARCHITECTURE.md` §3.1 to document the new `spans` field on the `Text` block variant:
```json
{
  "type": "text",
  "text": "UI Components: shadcn/ui, Lucide React.",
  "spans": [
    {"start": 0, "end": 14, "bold": true, "font_size": 11.0},
    {"start": 14, "end": 40, "bold": false, "font_size": 10.0}
  ],
  "bbox": [...],
  "section_id": "body",
  "source": "digital"
}
```
`spans` can be omitted or empty for blocks with no internal style variation, to avoid bloating output for the common case.

### Test fixtures
- **`Shivam_FullStack.pdf`** — the original fixture where this was found. Both specific examples from the bug report (`UI Co`/`mponents:` merge, and the `Frontend:` label:value line) must be verified fixed via manual JSON inspection, not just a passing test count.
- **New regression fixture** — per the bug report's own suggestion, add a synthetic or real fixture with several label:value bullet lines using inline bold styling (mirroring `Frontend:`, `Backend & Database:`, `Language:` patterns). This locks down the fix against regressions from unrelated future changes, since resumes/reports commonly use this pattern.
- **Regression check on existing fixtures** — re-run the full existing corpus (`arxiv_twocolumn.pdf`, `ieee_template_placeholder.pdf`, `digital_word_export.pdf`, CJK fixture) to confirm the same-line merge logic doesn't over-merge things that should stay separate (e.g., don't accidentally merge two genuinely distinct blocks that happen to share a y-coordinate but have a real gap between them — this is the same false-positive risk pattern seen in the Phase 4 header/footer and Phase 3a table-detection work).

### Acceptance criteria
- [ ] `cargo test` passes, including new fixture-based regression tests for both reported examples
- [ ] Manual JSON inspection on `Shivam_FullStack.pdf` confirms: no mid-word splits anywhere in the document, and the `Frontend:`/`UI Components:`/`Backend & Database:` lines are each single, complete blocks
- [ ] Manual inspection on `arxiv_twocolumn.pdf` and at least one other existing fixture confirms no new over-merging introduced
- [ ] `cargo clippy -- -D warnings` clean
- [ ] `ARCHITECTURE.md` §3.1 updated with the `spans` field documentation and decision log entry explaining why spans are preserved rather than discarded

### Release
Ship as `v0.2.1` — this is a correctness patch to already-published behavior, not a new feature, so it should go out on its own rather than being bundled with Phase 2's feature work.

---

## Phase 2 — Heuristic Semantic Block Typing: Heading Detection

**Goal:** add a `heading` classification, detected via cheap geometric/style heuristics using the `spans` data from Phase 1 — explicitly not ML-based, consistent with `PRD.md`'s existing non-goals around ML-based layout detection.

### Detection approach (propose before implementing, same as table extraction's process)
Candidate signals, in rough order of reliability:
1. **Font size relative to document's own body-text baseline** — compute the most common font size across the document (the "body" size), flag blocks with a meaningfully larger size (e.g., a configurable ratio, not a hardcoded point value, since body text size varies by document) as heading candidates
2. **Short line length** — headings are typically single lines, not wrapped paragraphs
3. **Bold/weight** (from Phase 1's `spans` data) as a supporting signal, not sole signal
4. **Position** — a heading is typically the first block after a vertical gap larger than normal line spacing (reuse logic patterns already established for swath/paragraph-break detection in Phase 4's cleanup pass)

### Explicit false-positive test cases to check before accepting any threshold
This is the step that was skipped early in the original table-extraction work and cost multiple correction rounds — do it proactively this time:
- [ ] Bold **label:value** lines (`Frontend:`, `Language:`, from the same resume fixture) must NOT be misclassified as headings — these are bold and short, which is exactly the false-positive shape to guard against
- [ ] ALL-CAPS section labels that are NOT meant as document headings (e.g., a table's column header text, or an acronym in body text) must not trip the heuristic
- [ ] A genuinely large pull-quote or callout box (if present in any fixture) should be evaluated — is it a heading or not? Decide and document the intended behavior rather than leaving it undefined

### Schema addition
Extend `section_id` or add a new field — **decide explicitly, don't default silently.** Options:
- Add `"heading"` as a new possible value of `section_id` (currently `header`/`footer`/`footnote`/`body`) — risks conflating page-position semantics (header/footer = page furniture) with content-structure semantics (heading = a title within body content). These are different axes.
- **Recommended:** add a separate field, e.g. `"block_role": "heading" | null`, distinct from `section_id`, so a block can independently be `section_id: "body"` and `block_role: "heading"` at the same time (a heading is still body content, not page furniture)

Document this schema decision in `ARCHITECTURE.md` before implementing.

### Test fixtures
- `Shivam_FullStack.pdf` — "PROJECTS", "TECHNICAL SKILLS", "EDUCATION" etc. are genuine section headings; label:value lines must NOT match
- `arxiv_twocolumn.pdf` — "Abstract", "1 Introduction", "2 Background" are genuine headings at a different size than body text; verify detection works across a second, structurally different document
- `ieee_template_placeholder.pdf` — has its own heading structure; also useful for confirming detection generalizes rather than being tuned to one fixture

### Acceptance criteria
- [ ] Manual JSON inspection confirms correct heading detection on all three fixtures above, with the two explicit false-positive cases (bold label:value, ALL-CAPS non-heading) verified NOT triggering
- [ ] Threshold values are justified in code comments/commit message (relative ratios, not magic constants tuned to one document)
- [ ] `cargo test` includes assertions for both true positives and the specific false-positive cases
- [ ] `ARCHITECTURE.md` updated: schema change documented, detection heuristic and its known limitations documented in the decision log

---

## Phase 3 — Heuristic Semantic Block Typing: Code Block Detection

**Goal:** add a `code` classification for blocks set in a monospace font, since this is a genuinely cheap and reliable signal available directly from the PDF's font dictionary.

### Detection approach
- [ ] Check the font name/family string in the block's associated font dictionary for known monospace indicators (e.g., `Courier`, `Consolas`, `Mono`, `Menlo`, `Monaco`, or checking whether the font's declared character widths are uniform — a structural definition of "monospace" independent of naming convention, which is more robust than string-matching font names)
- [ ] Prefer the structural check (uniform character widths) over name-matching where possible, since font names are inconsistent across PDF generators — this also reuses the glyph-width infrastructure already built for CID/Type0 font support in Phase 5/3b of the original roadmap, rather than introducing a new detection mechanism

### Test fixtures
- Needs a new fixture — none of the current corpus documents contain code blocks. Generate one via the same safe method used for `ieee_template_placeholder.pdf`: an Overleaf document (or similar) with a `verbatim`/`lstlisting`-style code block using a monospace font, combined with regular prose, so both detection and non-detection can be verified in the same document
- [ ] Confirm the new fixture is added under a clear name (e.g., `code_block_fixture.pdf`) with no real/attributed content, consistent with the project's existing IP-safety practices

### Acceptance criteria
- [ ] Manual JSON inspection confirms code blocks are correctly flagged via `block_role: "code"` and prose in the same document is not
- [ ] `cargo test` covers both detection and non-detection cases
- [ ] `ARCHITECTURE.md` decision log updated

---

## Explicitly Out of Scope (for this phase set)

- **List item detection** — deferred. Bullet/numbered-list detection has its own false-positive surface (e.g., a hyphen used as punctuation vs. a bullet character) that deserves its own scoped phase rather than being bundled in here.
- **Markdown-aware typing** — not applicable to PDF extraction. Markdown is a source format; a rendered PDF has no markdown syntax to detect. If this need is really about preserving structure for a downstream markdown-aware chunker, that's a FerrumChunk-side concern (structured blocks → markdown chunking strategy), not something LightningParse's PDF extraction should attempt.
- **ML-based layout detection** — remains explicitly out of scope per `PRD.md`. Nothing in this plan should require a model dependency; if a heuristic's false-positive rate proves unacceptable during Phase 2 or 3 verification, the correct response is to narrow the heuristic's scope or accept the limitation and document it — not to introduce an ML dependency to compensate.

## Sequencing Note

Phase 1 is a bug fix to already-shipped, published behavior and should ship independently as soon as it's verified (`v0.2.1`), not held back waiting for Phases 2–3. Phases 2 and 3 are additive features and can ship together or separately as a `v0.3.0`, once both are independently verified against their false-positive test cases.
