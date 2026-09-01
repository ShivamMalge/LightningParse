I'm reopening LightningParse for a specific reason: it's about to become a load-bearing dependency of Aakar, another of my projects. Aakar ingests a student's own textbook chapter, generates a labeled 3D model of a topic in it, and answers questions about any clicked part — grounded in that chapter, with page citations. LightningParse is the ingest path: PDF -> chunks -> Qdrant.

The question isn't "is LightningParse good" — it's "is it good enough for Aakar's specific claims." I want you to produce a phases-style planning document (NEW_PHASES.md, following the same structure and discipline as this repo's existing PHASES.md, PHASES-EXTRACTION-FIDELITY.md, and ASCII_PHASES.md — numbered phases, explicit acceptance criteria, evidence requirements, no phase marked complete without proof).

**Critical scope constraint: this document covers DIAGNOSIS ONLY. Do not include any implementation/fix phases. Every phase in this document ends in "here's what we measured and found" — none end in "here's the code change." I will decide on fixes after seeing real diagnostic output, in a separate follow-up.**

This mirrors a mistake from an earlier session: a benchmark once concluded "LightningParse needs improving" when the actual evidence was a single known ASCII85Decode gap triggered by a synthetic reportlab fixture, misread as a general quality problem. This document exists specifically to avoid repeating that — diagnose precisely before touching any code.

## The failure mode that matters most (not currently in README's Known Limitations)

Citation fidelity. Aakar's headline claim is a cited answer pointing at a page of the student's own book. That claim dies silently if the page number is wrong. Three distinct failure mechanisms, each needs its own diagnostic phase:

1. **Printed page number != PDF page index.** Roman-numeral front matter, chapters that restart numbering, scanned books with a cover page offsetting everything.
2. **Header/footer detection stripping running heads that carry the page label** — if cross-page heuristic detection eats the page label, provenance loses its anchor.
3. **Two-column reading-order reconstruction (Union-Find column clustering)** — if this misclusters, a chunk's text is correct but its position is wrong, attaching it to the wrong part of the diagram.

## Priority order for Aakar specifically

1. Citation fidelity (above) — highest priority
2. OCR noise — students scan textbooks, this path gets hit constantly
3. Encrypted PDFs — textbook PDFs routinely carry owner passwords; needs a clean, explicit rejection rather than a crash or silent OCR fallback. As part of this phase, investigate whether encryption can be detected *before* attempting extraction (fast, clear rejection) rather than failing deep into the pipeline and getting misclassified as generic corruption.
4. CID/Type0 fonts — Devanagari, math glyphs
5. Tables — near-irrelevant for Aakar, which needs structural prose, not tabular data. Deprioritize; if your honest assessment is this doesn't need a diagnostic phase at all, say so and drop it rather than including it for completeness.

## What each phase must define, before any numbers exist

For each of the four active priorities above, a phase must specify:
- Which real textbook chapters are needed and why, covering: digital-native single-column, digital-native two-column, scanned, non-Latin/math-heavy glyphs, and at least one with front matter (for page-label offset testing). Aakar v1 topics are human eye, animal cell, neuron, Earth's layers, DNA, OSI stack — biology, physics, and CS chapters.
- What exactly gets measured, especially for citation fidelity — including how to establish ground truth for "what printed page is this text actually on" without hand-labeling every chunk, and where hand-labeling is genuinely unavoidable, scope exactly how much.
- What the harness must surface that the current benchmark script does not. Note that `result["metadata"]["warnings"]` already exists and was previously ignored by a test harness, which made a known limitation look like a mystery slowdown — don't repeat that.
- A pass/fail bar per axis, decided and written down before any fixture is run.

## Fixture sourcing — hard constraint, not a suggestion

Real textbook content is very likely commercially copyrighted. Any real textbook PDFs and page images derived from them must stay completely outside this git repository — not in `benchmarks/corpus`, not committed at all, gitignored or kept in a local-only folder outside the repo. The diagnostic harness's *code* (measurement scripts, ground-truth methodology) belongs in the repo; the actual textbook content does not.

Where a synthetic or openly-licensed substitute would work as well, prefer it over an arbitrary commercial textbook — e.g., an OpenStax biology/physics chapter (explicitly open-licensed) or an NCERT chapter (verify NCERT's actual reuse terms first, don't assume). For citation-fidelity testing specifically, real books' real page-numbering quirks (roman numerals, restarted chapter numbering, scanned front matter) may be hard to replicate synthetically — flag explicitly, fixture by fixture, which ones genuinely need real content versus which could be built synthetically, and for the ones needing real content, prefer freely-licensed sources over commercial ones.

## Separate investigation: warnings as a provenance-strength signal

Rather than a phase to fix every parser weakness, Aakar could consume the existing `warnings` array and propagate it into a provenance-strength signal — degraded extraction surfaces in the UI as weak provenance instead of being invisible. Add a phase investigating: what warnings LightningParse currently emits, whether they're granular enough to attach per-chunk rather than only per-document (the provenance idea only works if a warning can be tied to the specific chunk it affects), and what would need to change if they aren't. This is diagnostic too — describe the current state and the gap, don't implement the change.

## Scope discipline

This project has no deadline; a different project does (Sept 5). Keep this tight. Resist expanding into a general modernization plan. If your honest read is that any of the five priorities don't need a diagnostic phase at all, say so explicitly in the document rather than building a phase for completeness.

Produce NEW_PHASES.md now. Do not implement anything. Stop after the document is written.
