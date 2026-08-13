# ⚡ LightningParse

Fast, accurate PDF parsing for RAG pipelines — a Rust extraction core (via PyO3) feeding a Python chunking/embedding/retrieval pipeline.

> **Status:** published on PyPI (`pip install lightningparse`). Core pipeline complete — Rust extraction, cleanup, OCR fallback, semantic block typing, chunking, retrieval, and generation are all implemented and benchmarked end-to-end. See [`PHASES.md`](./PHASES.md) for the original build roadmap and [`BENCHMARKS.md`](./benchmarks/BENCHMARKS.md) for full results.

## What's New in v3.1.0

- **Fault-Tolerant Page Tree Traversal**: We replaced `lopdf`'s strict page tree parser with a custom fault-tolerant tree walker mimicking `PyPDF2`. LightningParse will now successfully extract text from malformed PDFs that omit or mis-capitalize `/Type /Pages` or `/Type /Page` tags, and will safely abort on circular reference loops.
- **Explicit Error Propagation**: Instead of silently returning an empty pages array on fatal parsing errors, the FFI boundary now correctly throws a `CorruptPdfError` exception to fail loudly in Python pipelines.

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

LightningParse is **6.0×–93.1× faster** than pypdf/pdfplumber on digital-native (Tier 1) PDFs, with the gap widening on longer documents. Some representative results:

| Document | Pages | LightningParse (median) | pypdf | pdfplumber |
|---|---:|---:|---:|---:|
| Multi-page IEEE paper (`ieee_template_placeholder.pdf`) | 8 | 0.61 ms | 7.89 ms (12.9× slower) | 56.82 ms (93.1× slower) |
| Two-column academic paper (`arxiv_twocolumn.pdf`) | 15 | 41.12 ms | 951.92 ms (23.1× slower) | 2579.90 ms (62.7× slower) |
| Single-page resume (`Shivam_FullStack.pdf`) | 1 | 6.82 ms | 82.14 ms (12.0× slower) | 208.42 ms (30.6× slower) |

OCR (Tier 2) and mixed-document handling are also supported, benchmarked separately from Tier 1 — pypdf and pdfplumber can't perform OCR, so comparing their near-instant-but-empty results against LightningParse's actual OCR time would be misleading rather than informative. See `BENCHMARKS.md` for those numbers on their own terms.

A concurrent-load test also confirms the Rust FFI genuinely releases Python's GIL during parsing: 10 concurrent OCR-heavy parse requests complete **4.78× faster** than running them sequentially, on an 8-core/16-thread machine.

Full methodology, per-document results, and reproduction steps: [`benchmarks/BENCHMARKS.md`](./benchmarks/BENCHMARKS.md). Run them yourself:

```bash
cd benchmarks
python benchmark.py --tier all
```

Results are published in `benchmarks/BENCHMARKS.md` — generated, not hand-written.

## Known Limitations

- **CID/Type0 composite fonts:** glyph width lookup currently only reads `/Widths` (simple fonts); CID fonts fall back to a standard 0.5 em width, verified safe (no crash) but not pixel-precise for bbox positioning. The same fallback is used for the `code` block-role detector, so monospace CID fonts are only detected via font-name matching, not structural width analysis. See `ARCHITECTURE.md` decision log.
- **Unsupported content stream filters (ASCII85Decode, etc.):** lopdf 0.33 only decodes `FlateDecode` and `LZWDecode` content stream filters. PDFs using other filters (most commonly `ASCII85Decode`, found in older PDF generators and some `reportlab` output) will still produce zero text blocks from Tier 1 extraction and get misrouted to Tier 2 OCR. As of v0.3.0, this is no longer silent — affected pages surface a `warnings` array in the response metadata (`result["metadata"]["warnings"]`) so callers can detect and handle it programmatically. A full fix (adding an ASCII85 decoder) is still tracked for a future release.
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
