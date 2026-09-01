# ⚡ LightningParse

Fast, accurate PDF parsing for RAG pipelines — a Rust extraction core (via PyO3) feeding a Python chunking/embedding/retrieval pipeline.

> **Status:** published on PyPI (`pip install lightningparse`). Core pipeline complete — Rust extraction, cleanup, OCR fallback, semantic block typing, chunking, retrieval, and generation are all implemented and benchmarked end-to-end. See [`PHASES.md`](./PHASES.md) for the original build roadmap and [`BENCHMARKS.md`](./benchmarks/BENCHMARKS.md) for full results.

## What's New in v0.5.0

- **Fixed silent content loss in header/footer detection.** Margin bands were computed as a fraction of *content extent* (the tallest block seen) rather than the page's real height. Because content never reaches the physical top of a sheet, the band sat below the true margin and reached down into body text — and anything tagged as page furniture is dropped before chunking. Measured across 7 documents, **19 blocks of genuine content were being deleted**, including a memo's `To:`/`From:` fields, a paper's title and author line, and the chapter titles of two textbook chapters. Bands are now derived from real page geometry.
- **Removed the page-1-only header/footer fallback.** Page 1 was classified by a different rule from every other page — tagging any very-top or very-bottom block on position alone, with no cross-page corroboration. It caused 8 of the 19 deletions. Its *footnote* branch is retained, as it is the only code path that assigns `section_id: "footnote"`.
- **Page geometry is now exposed in the output schema:** each page carries optional `page_width` / `page_height`, resolved from `/CropBox` (preferred) or `/MediaBox`, inherited through the page tree via a cycle-safe `/Parent` walk, with axes swapped for `/Rotate 90|270`. Documents with no usable geometry fall back to the previous behaviour, so nothing that worked before can regress.

**Behaviour change to be aware of:** fewer blocks are now tagged as page furniture, so *more* content reaches downstream consumers. If you relied on aggressive header stripping, you will see more furniture text than before. Nothing that was previously body content changes classification — the change is strictly one-directional (verified: 19 blocks freed, **0** newly tagged).

## What's New in v0.4.1

Two independent pieces of work ship in this release.

- **Content stream filter support (`ASCII85Decode` and friends)**: Tier 1 extraction previously decoded only `FlateDecode` and `LZWDecode`. Content streams using any other filter yielded zero extractable characters and were misrouted to Tier 2 OCR — producing degraded OCR output for pages that contained perfectly good digital text. Upgrading to `lopdf` 0.44 and widening the extractor's supported-filter allowlist adds `ASCII85Decode`, `ASCIIHexDecode`, and `RunLengthDecode`. `ASCII85Decode` — the most common of the three, emitted by older PDF generators and some `reportlab` output — now extracts as digital text with an empty `warnings` array, verified end-to-end by `test_ascii85_digital_extraction`. Filters outside the supported five still emit a per-page warning and route to OCR, so the visibility mechanism added in v0.3.0 is retained unchanged as a safety net.
- **Fault-tolerant page tree traversal**: `lopdf`'s strict page tree parser is replaced with a custom fault-tolerant tree walker modelled on `PyPDF2`. PDFs that omit or mis-capitalize `/Type /Pages` or `/Type /Page` now extract successfully instead of failing outright, and circular reference loops abort safely rather than looping. Relatedly, the FFI boundary now raises `CorruptPdfError` on fatal parse errors instead of silently returning an empty pages array, so failures surface in Python pipelines rather than passing as empty documents.
- **Correct handling of multi-stream pages**: a page whose `/Contents` is an array of several streams is now joined with an explicit separator, so streams meeting at a token boundary (e.g. one ending `...Tj ET` and the next beginning `BT ...`) no longer fuse the adjacent operators into a single invalid token. This previously corrupted the text-object structure silently, without raising an error. Covered by `test_multistream_page_segmentation`.

## What's New in v0.3.0

- **Semantic block typing**: text blocks are now classified with a `block_role` — `"heading"` (detected via document-relative font-size/weight heuristics) or `"code"` (detected via structural monospace-font analysis)
- **Style span tracking**: a new `spans` array on text blocks preserves per-character style regions (bold, font size, monospace), so mixed-style lines (e.g. inline code, bold labels) aren't lost during extraction
- **Fixed a same-line fragmentation bug**: lines with a mid-line style change (e.g. `Frontend:` in bold followed by regular text) were previously split into multiple blocks, sometimes mid-word
- **Fixed a PDF-spec-compliance bug**: `BT`/`ET` operators were incorrectly resetting font state, which also improved reading order on existing multi-column fixtures
- **Added visibility for unsupported content stream filters**: PDFs using filters LightningParse can't yet decode (e.g. `ASCII85Decode`) now surface a `warnings` array in the response metadata instead of silently misrouting to OCR

## Why

Traditional Python PDF libraries (PyPDF2, pdfplumber, PyMuPDF) are GIL-bound and process pages sequentially, which becomes a bottleneck in RAG ingestion pipelines. LightningParse pushes extraction, cleanup, semantic typing, and OCR fallback into Rust, parallelized across pages, and returns structured JSON that Python can chunk with page/section metadata intact.

## Architecture

```
React → FastAPI → Rust PDF Parser (PyO3) → Chunker → Chroma → LLM
```

Two processing tiers:
- **Tier 1 — Digital-native PDFs:** direct text extraction, no OCR. This is where the speed claim is benchmarked.
- **Tier 2 — Scanned/image PDFs:** routed per-page to OCR (Tesseract) when no text layer is present.

Full design details: [`ARCHITECTURE.md`](./ARCHITECTURE.md)
Product scope and roadmap: [`PRD.md`](./PRD.md)
Contributor/agent instructions: [`AGENTS.md`](./AGENTS.md)

## Benchmarks

LightningParse is **16.3×–53.9× faster than pypdf** and **44.8×–84.4× faster than pdfplumber** on the representative digital-native (Tier 1) documents below, with the gap widening on longer documents:

| Document | Pages | LightningParse (median) | pypdf | pdfplumber |
|---|---:|---:|---:|---:|
| Multi-page IEEE paper (`ieee_template_placeholder.pdf`) | 8 | 1.60 ms | 26.03 ms (16.3× slower) | 135.00 ms (84.4× slower) |
| Two-column academic paper (`arxiv_twocolumn.pdf`) | 15 | 68.36 ms | 3685.33 ms (53.9× slower) | 5575.18 ms (81.6× slower) |
| Single-page resume (`Shivam_FullStack.pdf`) | 1 | 13.04 ms | 236.37 ms (18.1× slower) | 583.69 ms (44.8× slower) |

> **Absolute milliseconds are machine-dependent** and will vary with hardware, thermal state and background load. The portable claim is the **speedup ratio** — the baselines are timed on the same machine in the same run, so hardware cancels out. This session's own investigation demonstrated it: these absolute figures moved ~2x from the previous published set while pypdf and pdfplumber (code LightningParse does not touch) moved 2.4-3.5x, i.e. the shift was hardware, not the codebase. Figures are the median of **25 timed runs after 10 warm-up runs** — the warm-up matters, because LightningParse's first runs measure markedly slower than its steady state. See [methodology](./benchmarks/BENCHMARKS.md).

Trivial single-page synthetic fixtures in the corpus span wider in both directions (3.8×–427.4×), because at that size the ratio is dominated by each library's fixed overhead rather than by extraction work. They are not quoted as headline figures.

OCR (Tier 2) and mixed-document handling are also supported, benchmarked separately from Tier 1 — pypdf and pdfplumber can't perform OCR, so comparing their near-instant-but-empty results against LightningParse's actual OCR time would be misleading rather than informative. See `BENCHMARKS.md` for those numbers on their own terms.

A concurrent-load test also confirms the Rust FFI genuinely releases Python's GIL during parsing: 10 concurrent OCR-heavy parse requests complete **4.78× faster** than running them sequentially, on an 8-core/16-thread machine.

Full methodology, per-document results, and reproduction steps: [`benchmarks/BENCHMARKS.md`](./benchmarks/BENCHMARKS.md). Run them yourself:

```bash
cd benchmarks
python benchmark.py --tier all
```

Results are published in `benchmarks/BENCHMARKS.md` — generated, not hand-written.

## Known Limitations

- **Page furniture is under-removed on long documents:** header/footer detection requires a repeated block to appear on ≥70% of pages. Running heads usually change per chapter, so on a long book nothing clusters that widely and **no furniture is removed at all** — measured on a 1475-page textbook whose site-wide footer appears on 734 pages and is still not stripped. Separately, a bare page number normalises to an empty string during clustering and can never be tagged. Both mean folios and running heads can flow into `body` text and into chunks.
- **CID/Type0 composite fonts:** glyph width lookup currently only reads `/Widths` (simple fonts); CID fonts fall back to a standard 0.5 em width, verified safe (no crash) but not pixel-precise for bbox positioning. The same fallback is used for the `code` block-role detector, so monospace CID fonts are only detected via font-name matching, not structural width analysis. See `ARCHITECTURE.md` decision log.
- **Content stream filters outside the supported set:** Tier 1 extraction decodes `FlateDecode`, `LZWDecode`, `ASCII85Decode`, `ASCIIHexDecode`, and `RunLengthDecode` — all five are decoded natively by lopdf 0.44 and are on the extractor's supported-filter allowlist, so pages using them yield real digital text. `ASCII85Decode` (found in older PDF generators and some `reportlab` output) was a known gap in earlier releases and is now fully supported, covered end-to-end by `test_ascii85_digital_extraction`. PDFs whose content streams use any *other* filter (e.g. `JBIG2Decode`, or a `/Crypt` filter) still produce zero text blocks from Tier 1 and are routed to Tier 2 OCR. This remains non-silent — affected pages surface a `warnings` array in the response metadata (`result["metadata"]["warnings"]`) so callers can detect and handle it programmatically. One gap remains within the supported set: a **corrupt ASCII85 stream currently fails silently to OCR fallback rather than raising a warning or error** — the page is reported as `tier: "scanned"` with an empty `warnings` array, indistinguishable from a genuine scan. Tracked for a future release.
- **Heading detection false positives:** heading classification is based purely on font-size ratio, weight, and line length relative to the document's own body text — it has no semantic understanding of document structure. Stylistically-emphasized text that isn't a real section heading (e.g., a bolded date range, a pull-quote) can be misclassified as `block_role: "heading"`. See `ARCHITECTURE.md` decision log for the specific tradeoff.
- **OCR noise:** Tesseract confidence-based filtering removes most scan artifacts (binder shadows, margin smudges) but some low-level noise can still pass through on real-world scans. OCR output is not expected to be flawless — see `PRD.md` non-goals.
- **Tier 2/Mixed fixture coverage:** currently validated against a small number of real scanned/mixed fixtures rather than a broad corpus. On the synthetic `phone_photo_invoice.pdf` fixture specifically, heavy combined distortion (rotation + noise + lighting gradient + blur) caused the OCR confidence filter to discard all real content along with the noise — 0 of 7 real lines recovered. This demonstrates the system fails safely (no crash, no hallucinated garbage) under severe distortion, but does not currently recover text from heavily degraded scans. Speedup claims for Tier 1 are well-validated across multiple document types; Tier 2 performance numbers should be read as representative of the current fixtures, not a broad guarantee.
- **Complex/borderless tables:** table detection requires a nearby caption (e.g. "Table 1") and consistent row/column geometry. Tables without captions, or with irregular formatting (superscripts breaking row alignment, merged cells), fall back to flat text rather than structured rows — no data is lost, but structure isn't always recovered. See `PRD.md`.
- **Encrypted/form PDFs:** not explicitly supported in v1.

## Install

```bash
pip install lightningparse
```

Prebuilt wheels are published for Linux, macOS, and Windows via CI. If no matching wheel is available for your platform/Python version, pip will build from source automatically (requires a Rust toolchain).

For local development on this repo:
```bash
# Rust core (requires maturin)
cd lightningparse-core
maturin develop --release

# Python API layer (reference RAG pipeline, not required to use the core parser)
cd lightningparse-api
pip install -e .
```

## Quickstart

```python
from lightningparse import parse_pdf
import json

result = json.loads(parse_pdf("document.pdf"))

for page in result["pages"]:
    for block in page["blocks"]:
        role = block.get("block_role")  # "heading", "code", or None
        print(block["section_id"], role, block["text"][:80])

# Check for extraction warnings (e.g. unsupported content stream filters)
if result["metadata"].get("warnings"):
    print("Warnings:", result["metadata"]["warnings"])
```

## Scope (v1)

**In scope:** digital-native PDF extraction, header/footer/footnote removal, OCR fallback for scanned pages, structured table extraction, heading/code semantic block typing, metadata-aware chunking, retrieval + LLM Q&A pipeline with citations.

**Not in scope yet:** full CID/Type0 structural width analysis, encrypted/form PDFs, ML-based layout detection, list/markdown-aware block typing. See `PRD.md` §2 for the full non-goals list — these are deliberate cuts, not oversights.

## Contributing

See [`AGENTS.md`](./AGENTS.md) for repo conventions, build commands, and non-negotiable rules (FFI safety, GIL handling, benchmark discipline) before opening a PR.

## License

MIT License.
