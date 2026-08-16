<!--
  This file IS the PyPI project description for `lightningparse`.

  `pyproject.toml` sets `readme = "README.md"`, which resolves relative to this
  directory — so this file, not the repo-root README.md, is what gets packaged
  into the wheel and rendered on PyPI. The two are maintained separately on
  purpose: the root README documents the whole repository (Rust core + FastAPI
  layer + benchmarks), this one documents the published Python package.

  Keep it current as part of the release checklist. It previously drifted three
  releases behind, so PyPI advertised v0.2.0 content on a v0.4.0 release.

  Relative links do NOT resolve on PyPI — always use absolute GitHub URLs here.
-->

# ⚡ LightningParse

Fast, accurate PDF parsing for RAG pipelines — a Rust extraction core (via PyO3) returning structured JSON, with automatic OCR fallback for scanned pages.

> **Status:** published on PyPI — `pip install lightningparse`. Prebuilt wheels for CPython 3.8–3.14 on Linux (x86_64, aarch64), Windows (x64), and macOS (x86_64, arm64). Core pipeline complete and benchmarked end-to-end.

## Install

```bash
pip install lightningparse
```

Tier 1 (digital-native) extraction works out of the box with no system dependencies.

**OCR (Tier 2) additionally requires [Tesseract](https://github.com/tesseract-ocr/tesseract) on your `PATH`.** It is invoked only when a page has no extractable text layer. Without it, scanned pages raise `OcrMissingDependencyError` rather than failing silently.

<details>
<summary>Building from source</summary>

```bash
git clone https://github.com/ShivamMalge/LightningParse.git
cd LightningParse/lightningparse-core
maturin develop --release   # requires a Rust toolchain
```
</details>

## Quickstart

`parse_pdf()` returns a **JSON string**, so parse it before use:

```python
import json
from lightningparse import parse_pdf

result = json.loads(parse_pdf("document.pdf"))

for page in result["pages"]:
    for block in page["blocks"]:
        role = block.get("block_role")  # "heading", "code", or None
        print(block["section_id"], role, block["text"][:80])

print(result["metadata"]["tier"])  # "digital", "scanned", or "mixed"

# Pages using a content-stream filter that can't be decoded are reported here
# rather than silently degrading to OCR.
if result["metadata"].get("warnings"):
    print("Warnings:", result["metadata"]["warnings"])
```

Fatal parse errors raise `CorruptPdfError` instead of returning an empty result, so failures surface in your pipeline rather than passing as empty documents:

```python
from lightningparse import parse_pdf, CorruptPdfError

try:
    result = json.loads(parse_pdf("maybe_broken.pdf"))
except CorruptPdfError as e:
    print("Unparseable:", e)
```

## What's New in v0.4.0

- **Content stream filter support (`ASCII85Decode` and friends)**: Tier 1 extraction previously decoded only `FlateDecode` and `LZWDecode`. Content streams using any other filter yielded zero extractable characters and were misrouted to Tier 2 OCR — producing degraded OCR output for pages that contained perfectly good digital text. Upgrading to `lopdf` 0.44 and widening the supported-filter allowlist adds `ASCII85Decode`, `ASCIIHexDecode`, and `RunLengthDecode`. Filters outside the supported five still emit a per-page warning and route to OCR, so the visibility mechanism added in v0.3.0 is retained as a safety net.
- **Fault-tolerant page tree traversal**: `lopdf`'s strict page tree parser is replaced with a custom tolerant tree walker modelled on `PyPDF2`. PDFs that omit or mis-capitalize `/Type /Pages` or `/Type /Page` now extract successfully instead of failing outright, and circular reference loops abort safely rather than looping.
- **Explicit error propagation**: the FFI boundary raises `CorruptPdfError` on fatal parse errors instead of returning an empty pages array.
- **Correct handling of multi-stream pages**: a page whose `/Contents` is an array of several streams is now joined with an explicit separator, so streams meeting at a token boundary no longer fuse the adjacent operators into a single invalid token — which previously corrupted the text-object structure with no error raised.
- **First release published as platform wheels** rather than a source distribution alone, so installation no longer requires a Rust toolchain.

<details>
<summary>Earlier releases</summary>

### v0.3.0

- **Semantic block typing**: text blocks are classified with a `block_role` — `"heading"` (document-relative font-size/weight heuristics) or `"code"` (structural monospace-font analysis)
- **Style span tracking**: a `spans` array preserves per-character style regions (bold, font size, monospace), so mixed-style lines aren't lost during extraction
- **Fixed a same-line fragmentation bug**: lines with a mid-line style change were split into multiple blocks, sometimes mid-word
- **Fixed a PDF-spec-compliance bug**: `BT`/`ET` operators incorrectly reset font state, which also improved reading order on multi-column documents
- **Added visibility for undecodable content stream filters** via the `warnings` array

### v0.2.0

- **Structured table extraction**: captioned tables are parsed into row/column data instead of flat text, with markdown-formatted output in RAG chunks
- **CID/Type0 composite font support**: `/W` and `/DW` array parsing for embedded CJK and other composite fonts, replacing a fixed 0.5 em width fallback
- **New robustness fixtures**: synthetic distorted-scan and Word-export test cases
- **Fixed**: an `O(N²)` → `O(N)` performance regression from table-detection development
- **Fixed**: false-positive table detection merging multi-author affiliation blocks

</details>

## Why

Traditional Python PDF libraries (PyPDF2, pdfplumber, PyMuPDF) are GIL-bound and process pages sequentially, which becomes a bottleneck in RAG ingestion pipelines. LightningParse pushes extraction, header/footer cleanup, and OCR fallback into Rust, parallelized across pages, and returns structured JSON that Python can chunk with page/section metadata intact.

## Architecture

Two processing tiers, selected per page:

- **Tier 1 — Digital-native PDFs:** direct text extraction, no OCR. This is where the speed claim is benchmarked.
- **Tier 2 — Scanned/image PDFs:** routed per-page to OCR (Tesseract) when no text layer is present.

Documents containing both report `tier: "mixed"`.

Full design details: [ARCHITECTURE.md](https://github.com/ShivamMalge/LightningParse/blob/main/ARCHITECTURE.md) · Product scope: [PRD.md](https://github.com/ShivamMalge/LightningParse/blob/main/PRD.md)

## Benchmarks

LightningParse is **6.0×–93.1× faster** than pypdf/pdfplumber on digital-native (Tier 1) PDFs, with the gap widening on longer documents:

| Document | Pages | LightningParse (median) | pypdf | pdfplumber |
|---|---:|---:|---:|---:|
| Multi-page IEEE paper | 8 | 0.61 ms | 7.89 ms (12.9× slower) | 56.82 ms (93.1× slower) |
| Two-column academic paper | 15 | 41.12 ms | 951.92 ms (23.1× slower) | 2579.90 ms (62.7× slower) |
| Single-page resume | 1 | 6.82 ms | 82.14 ms (12.0× slower) | 208.42 ms (30.6× slower) |

OCR (Tier 2) and mixed-document handling are benchmarked separately — pypdf and pdfplumber can't perform OCR, so comparing their near-instant-but-empty results against actual OCR time would mislead rather than inform.

A concurrent-load test confirms the Rust FFI genuinely releases Python's GIL during parsing: 10 concurrent OCR-heavy parse requests complete **4.78× faster** than running them sequentially, on an 8-core/16-thread machine.

Full methodology and per-document results: [benchmarks/BENCHMARKS.md](https://github.com/ShivamMalge/LightningParse/blob/main/benchmarks/BENCHMARKS.md)

## Known Limitations

- **Corrupt ASCII85 streams fail silently to OCR:** a *corrupt or truncated* `ASCII85Decode` stream is not reported. The underlying decoder returns the raw undecoded bytes on failure rather than an error, so the page yields no text and falls through to OCR, reported as `tier: "scanned"` with an empty `warnings` array — indistinguishable from a genuine scan. Undecodable *filters* are still reported normally; this affects only corrupt data within a supported filter. Tracked for a future release.
- **Content stream filters outside the supported set:** `FlateDecode`, `LZWDecode`, `ASCII85Decode`, `ASCIIHexDecode`, and `RunLengthDecode` are decoded. PDFs using any other filter (e.g. `JBIG2Decode`, or a `/Crypt` filter) produce no Tier 1 text and are routed to OCR, with a `warnings` entry so callers can detect it.
- **Monospace detection on composite fonts:** the structural uniform-width check applies only to simple fonts with a `/Widths` array. CID/Type0 fonts bypass it and fall back to font-name matching (`"courier"`, `"mono"`), so an unconventionally-named monospace CID font may not be tagged `block_role: "code"`. Glyph *widths* for CID fonts are parsed correctly from `/W` and `/DW`.
- **Heading detection false positives:** classification uses font-size ratio, weight, and line length relative to the document's own body text, with no semantic understanding. Stylistically-emphasized text that isn't a real heading (a bolded date range, a pull-quote) can be misclassified.
- **Complex or borderless tables:** table detection requires a nearby caption (e.g. "Table 1") and consistent row/column geometry. Tables without captions, or with irregular formatting, fall back to flat text — no data is lost, but structure isn't always recovered.
- **OCR quality on degraded scans:** Tesseract confidence filtering removes most scan artifacts, but heavy combined distortion (rotation + noise + lighting gradient + blur) can cause the filter to discard real content along with the noise. The system fails safely — no crash, no hallucinated text — but does not recover text from severely degraded scans.
- **Encrypted and form PDFs:** not explicitly supported.

## Scope

**In scope:** digital-native PDF extraction, header/footer/footnote removal, semantic block typing, OCR fallback for scanned pages, and metadata-aware output suitable for chunking.

**Not in scope yet:** encrypted/form PDFs, ML-based layout detection. See [PRD.md](https://github.com/ShivamMalge/LightningParse/blob/main/PRD.md) §2 — these are deliberate cuts, not oversights.

## Contributing

See [AGENTS.md](https://github.com/ShivamMalge/LightningParse/blob/main/AGENTS.md) for repo conventions, build commands, and non-negotiable rules (FFI safety, GIL handling, benchmark discipline) before opening a PR.

## License

MIT License.
