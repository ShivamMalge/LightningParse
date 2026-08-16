# LightningParse — Architecture

This document describes the technical design of the system: module boundaries, data flow, the FFI contract between Rust and Python, and the reasoning behind key decisions. See `PRD.md` for goals/scope and `BENCHMARKS.md` for performance data.

---

## 1. System Diagram

```
┌─────────────┐
│   React     │  (demo/test UI — not core product)
└──────┬──────┘
       │ HTTP
┌──────▼──────────────────────────────────────────┐
│  FastAPI (Python)                                │
│  - async request handling                        │
│  - calls into Rust via PyO3 (GIL released)        │
└──────┬────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────┐
│  Rust Core (lightningparse-core)                  │
│                                                    │
│  ┌──────────────┐   ┌───────────────────────┐   │
│  │ Tier 1        │   │ Tier 2                 │   │
│  │ Digital-native│   │ Scanned → OCR fallback │   │
│  │ text extraction│  │ (Tesseract bindings)   │   │
│  └──────┬────────┘   └───────────┬────────────┘   │
│         │  page-level rayon parallelism            │
│         ▼                        ▼                 │
│  ┌─────────────────────────────────────────────┐  │
│  │ Header/Footer Detector (cross-page heuristic) │  │
│  └──────────────────┬──────────────────────────┘  │
│                      ▼                              │
│  ┌─────────────────────────────────────────────┐  │
│  │ Structured Output Builder → JSON              │  │
│  └─────────────────────────────────────────────┘  │
└──────┬────────────────────────────────────────────┘
       │ JSON (text, page_num, bbox, section_id)
┌──────▼──────────────────────────────────────────┐
│  Python: Metadata-aware Chunker                   │
└──────┬────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────┐
│  Embeddings → FAISS / Chroma                      │
└──────┬────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────┐
│  LLM (via LangChain)                              │
└────────────────────────────────────────────────────┘
```

---

## 2. Module Boundaries

### 2.1 Rust core (`lightningparse-core`)
Owns everything up through "clean structured text out." Nothing here knows about embeddings, chunking, or LLMs — that separation is deliberate so the Rust core stays independently useful (and independently benchmarkable) as a standalone library.

Sub-modules:
- `extract/` — Tier 1 digital-native extraction (per-page, parallelized)
- `ocr/` — Tier 2 scanned-page detection + Tesseract invocation
- `cleanup/` — header/footer detection, reading-order reconstruction, OCR artifact cleanup
- `output/` — structured JSON serialization
- `ffi/` — PyO3 bindings, the only module allowed to touch Python types

**Rule:** business logic (extraction, cleanup) never directly depends on PyO3 types. Only `ffi/` translates between Rust-native structs and Python. This keeps the core testable in pure Rust (`cargo test`) without spinning up Python at all.

### 2.2 Python service (`lightningparse-api`)
- `api/` — FastAPI routes, request/response models
- `chunking/` — metadata-aware chunker consuming the Rust JSON output
- `pipeline/` — embeddings, vector store (FAISS/Chroma), LangChain wiring
- `bindings.py` — thin wrapper around the PyO3 module; this is the only place that imports the compiled Rust extension directly

### 2.3 Benchmarking (`benchmarks/`)
Lives outside both — treated as a peer, not a subdirectory of either. Runs both the Rust core (via bindings) and baseline libraries (pdfplumber, PyPDF2, PyMuPDF) against the same corpus. See `BENCHMARKS.md`.

---

## 3. The FFI Contract (Rust ↔ Python)

This is the most failure-prone part of the system, so it gets explicit rules.

### 3.1 Data format across the boundary
**Decision: JSON string, not native PyO3 objects, for v1.**
Rationale: easier to version, easier to debug (can log/inspect the raw payload), and the serialization cost is negligible next to PDF parsing time itself. Revisit only if profiling shows serialization is a measurable bottleneck — don't optimize this preemptively.

Output schema (per document):
```json
{
  "pages": [
    {
      "page_num": 1,
      "blocks": [
        {
          "type": "text",
          "text": "...",
          "spans": [
            {
              "start": 0,
              "end": 3,
              "bold": true,
              "font_size": 12.0
            }
          ],
          "bbox": [x0, y0, x1, y1],
          "section_id": "header|body|footer|footnote",
          "source": "digital|ocr"
        },
        {
          "type": "table",
          "rows": [
            ["Model", "Accuracy"],
            ["Baseline", "92.4%"],
            ["Proposed", "95.1%"]
          ],
          "bbox": [x0, y0, x1, y1],
          "section_id": "header|body|footer|footnote",
          "source": "digital|ocr"
        }
      ]
    }
  ],
  "metadata": {
    "tier": "digital|scanned|mixed",
    "page_count": 12,
    "parse_time_ms": 340,
    "warnings": ["Warning message (optional)"]
  }
}
```

**Note on Metadata Warnings**: The `warnings` array is omitted from the JSON output when empty. Clients should use `.get('warnings', [])` instead of assuming the key is always present.

**Note on Tables**: v1 Table extraction identifies simple bordered or geometrically aligned tables with single-line cell content. Nested tables, spanned/merged cells, and multi-line cells inside tables are explicitly out of scope for v1.

### 3.2 GIL handling
Rust-side parsing runs inside `Python::allow_threads`, releasing the GIL for the duration of the parse. This is non-negotiable — without it, FastAPI's async event loop stalls on every parse call regardless of how fast Rust is internally.

### 3.3 Error handling
- Rust functions return `Result<T, ParseError>` internally — never panic on malformed input.
- `catch_unwind` wraps the outermost FFI entry point as a last-resort safety net, but should rarely trigger if `Result` handling is done correctly upstream.
- `ParseError` variants map to specific Python exceptions (e.g., `CorruptPdfError`, `UnsupportedPdfError`, `OcrEngineError`) rather than a single generic exception — callers need to distinguish "this PDF is broken" from "OCR isn't installed."

### 3.4 Concurrency model
Two levels of parallelism, kept distinct:
- **Across requests:** FastAPI's async handling + GIL release (many PDFs processed concurrently)
- **Within a request:** rayon parallelizes across pages of a single PDF

These compose, but should be benchmarked both independently and together — a regression in one can hide in aggregate numbers.

---

## 4. Header/Footer Detection Design

Cross-page, not per-page. Algorithm sketch:
1. Extract all text blocks with bounding boxes for every page.
2. Bucket blocks by normalized y-position (top/bottom margin bands).
3. Within each band, cluster by text similarity across pages (allowing for page-number substitution, e.g. "Page 3 of 20" vs "Page 4 of 20").
4. Blocks appearing in the same band on ≥ N% of pages (configurable threshold, default ~70%) are flagged as header/footer and excluded from `body` section_id, tagged separately instead of deleted — so the option to include them later isn't lost.

This is heuristic, not ML-based, in v1 — intentional per PRD non-goals. Document this clearly so accuracy expectations are calibrated correctly.

---

## 5. Tier Routing Logic

Per-page decision, not per-document — a single PDF can be mixed:
```
for each page:
    if page has extractable text layer (non-trivial character count):
        route to Tier 1 (digital extraction)
    else:
        route to Tier 2 (OCR)
```
`metadata.tier` on the document is set to `"mixed"` if pages were routed differently. This matters for benchmarking — mixed documents must be reported as their own category, not blended into pure Tier 1 or Tier 2 numbers (per PRD §5.2).

---

## 6. Chunking (Python side)

Consumes the structured JSON, not raw text. Chunker is metadata-aware:
- Respects `section_id` — never splits a body paragraph across a header boundary
- Carries `page_num` forward into chunk metadata for citation/traceability in the final LLM answer
- Default strategy: semantic/paragraph-boundary chunking with page metadata attached; fixed-size character chunking is a fallback option, not the default

---

## 7. Key Design Decisions & Rationale (running log)

| Decision | Rationale | Revisit if... |
|---|---|---|
| JSON string across FFI, not native PyO3 objects | Simpler, debuggable, cost is negligible vs. parse time | Profiling shows serialization >5% of total time |
| Per-page tier routing (not per-document) | Real-world PDFs are often mixed | Never — this is core to correctness |
| Heuristic header/footer detection (not ML) | Matches v1 scope, avoids model dependency | Accuracy benchmark shows heuristic ceiling is too low |
| rayon for page-level parallelism | Simplest parallelism model for embarrassingly parallel per-page work | Page count is usually 1 (parallelism overhead not worth it) |
| OCR confidence filtering (threshold < 40) | Principled alternative to geometric heuristics. Accepts some margin noise (e.g. "S S") per v1 scope. | Noise materially degrades downstream chunking/retrieval (needs page-cropping/layout ML) |
| Chroma for Vector Store | Pure Python, integrates well with LangChain, no external C++ dependencies | We need robust production-grade persistent indices at high scale |
| Tesseract for OCR in v1 | Pragmatic, well-supported Rust bindings exist | M5 accuracy benchmark shows it's insufficient |
| Font width extraction parses CID/Type0 `/W` arrays and `/DW` fallbacks | Replaces the hardcoded generic 0.5 em fallback which caused incorrect bboxes for CJK text. Validated via `XeLaTeX.pdf` fixture where CJK glyphs accurately fall back to `DW=1000`. | Complex CMap encoding (beyond Identity-H/V) is encountered |
| Same-line text merging with style span tracking | Text fragments sharing the same baseline (with dynamic tolerance based on font size) are merged to fix mid-word and label:value splits. Styling (e.g. bold font detection) is preserved as character-index `spans` within the block. | Profiling shows span tracking adds measurable overhead, or very complex layouts defeat the Y/X tolerance heuristics |
| Heading detection 70-character limit | Prevents large non-heading blocks (e.g. copyright notices) from being misclassified. The longest observed genuine heading across test fixtures is 63 characters (leaving a 7-character margin). | A future document contains a genuine heading longer than 70 characters. (This is a known sensitivity, not a bug) |
| Heading detection stylistic emphasis (Known Limitation) | Because the heuristic relies purely on relative font size and weight, inline stylistic emphasis (like bolded dates, project titles, or pull-quotes) that cross the threshold will be falsely flagged as headings. | A more complex structural parser (e.g., checking vertical gap spacing or block sequence) is implemented to distinguish structural section headers from localized emphasis. |
| Code block precedence over heading | Monospace detection runs earlier during extraction and tags blocks as `code`. The heading detector explicitly checks and skips any block already tagged as `code`. Code snippets are often set in distinct fonts or sizes that might mistakenly trigger the heading heuristic (e.g., small or large code blocks), but semantically they are always code, not structural document headings. | Code blocks begin acting as true section dividers (highly unlikely). |
| Monospace detection fallback limitation | The structural check (uniform width analysis) only applies to simple embedded fonts with a `/Widths` array. Base-14 standard fonts and Composite (CID/Type0) fonts missing width arrays bypass this check and fall back to name-matching (e.g., "courier", "mono"). This is an accepted risk, as properly embedded fonts will trigger the structural check, while fallbacks rely on convention. | We discover a large volume of PDFs using non-standard monospace CID fonts without embedded width arrays, requiring a layout-based or ML heuristic. |
| Content stream filter support via lopdf 0.44 (resolved) | Originally a known limitation: lopdf 0.33 decoded only `FlateDecode` and `LZWDecode`, so streams using other filters fell back to raw encoded bytes via `get_page_content()`, produced 0 extractable chars, and were **misrouted to Tier 2 OCR** — a correctness issue, not just a performance one. Resolved by upgrading to **lopdf 0.44**, which decodes `FlateDecode`, `LZWDecode`, `ASCII85Decode`, `ASCIIHexDecode`, and `RunLengthDecode` natively (ASCII85 support landed upstream in lopdf 0.34.0, with overflow and missing-EOD-marker fixes in 0.35.0). All five are listed in the supported-filter allowlist in `extract/mod.rs`; the resolution was the version bump plus that allowlist entry, **not** a hand-written decoder. The `warnings` mechanism is deliberately retained as a safety net: any filter *not* on the allowlist still emits a per-page warning and routes to OCR, so unsupported filters remain visible rather than silent. Verified end-to-end by `test_ascii85_digital_extraction` (positive) and a `JBIG2Decode` control confirming the warning path still fires (negative). | lopdf gains native support for a further filter (the allowlist must be widened in lockstep — the allowlist is hand-maintained and does not derive from lopdf), or a corpus PDF is found using a filter outside the supported five often enough to justify a dedicated decoder. |
---

## 8. What Lives Where (quick reference)

| Concern | Location |
|---|---|
| PDF byte parsing | `lightningparse-core/src/extract/` |
| OCR invocation | `lightningparse-core/src/ocr/` |
| Header/footer logic | `lightningparse-core/src/cleanup/` |
| PyO3 bindings | `lightningparse-core/src/ffi/` |
| FastAPI routes | `lightningparse-api/api/` |
| Chunking | `lightningparse-api/chunking/` |
| Embeddings/vector store | `lightningparse-api/pipeline/` |
| Benchmark scripts + corpus | `benchmarks/` |
