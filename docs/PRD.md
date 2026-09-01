# LightningParse — Product Requirements Document

## 1. Overview

**Problem:** PDF parsing in pure Python (PyPDF2, pdfplumber, PyMuPDF) is slow and often inaccurate for RAG/LLM pipelines — GIL-bound, sequential per-page processing, and inconsistent handling of headers/footers, OCR noise, and multi-column layouts.

**Solution:** A Rust-based PDF parsing core exposed to Python via PyO3, feeding a Python-side chunking/embedding/retrieval pipeline. Rust handles extraction and cleanup; Python handles everything downstream (chunking, embeddings, retrieval, LLM calls).

**Goal for this project:** A portfolio-grade, potentially open-sourceable library that is demonstrably faster than traditional Python PDF libraries on digital-native PDFs, with a credible OCR fallback path for scanned documents — backed by reproducible benchmarks, not marketing claims.

---

## 2. Goals & Non-Goals

### Goals
- Significant, benchmarked speed improvement over pdfplumber/PyPDF2/PyMuPDF on digital-native PDFs
- Accurate text extraction with correct reading order (including multi-column layouts)
- Reliable header/footer detection and removal across multi-page documents
- Structured JSON output (text + page number + bbox + section metadata) usable for metadata-aware chunking
- OCR fallback for scanned/image PDFs, clearly benchmarked separately from the digital-native path
- Reproducible, public benchmark suite comparing LightningParse to traditional libraries on speed AND accuracy

### Non-Goals (v1)
- Not competing on OCR speed/accuracy itself (we use existing OCR engines, not building one)
- Not building a full document-understanding model (no ML-based layout detection in v1 — heuristic-based)
- Not optimizing for exotic PDF edge cases (encrypted PDFs, forms, digital signatures) in v1
- Not a hosted product/SaaS at this stage — library/CLI first

---

## 3. Architecture

```
React (demo UI)
   ↓
FastAPI (Python) — async request handling
   ↓
Rust PDF Parser (via PyO3, GIL released during parsing)
   ├── Tier 1: Digital-native text extraction (rayon-parallelized across pages)
   ├── Header/footer detection (cross-page positional heuristics)
   └── Tier 2: Scanned-page detection → OCR fallback (Tesseract bindings)
   ↓
Structured JSON output (text, page_num, bbox, section metadata)
   ↓
Python Chunker (metadata-aware, not naive fixed-size)
   ↓
Embeddings → FAISS/Chroma
   ↓
LLM (via LangChain)
```

### Tech Stack
| Layer | Tech |
|---|---|
| PDF parsing core | Rust (`lopdf` or `pdfium-render`) |
| Parallelism | `rayon` |
| Python bindings | PyO3 |
| Optional tabular bridge | `pyo3-polars` (only if table extraction is prioritized) |
| OCR | Tesseract (Rust bindings) — swappable later |
| API layer | FastAPI |
| Chunking/orchestration | LangChain |
| Vector store | FAISS / Chroma |
| Frontend | React (demo/testing UI, not core product) |

---

## 4. Two-Tier Processing Strategy

**Tier 1 — Digital-native PDFs** (build and prove first)
- Direct text layer extraction, no OCR
- This is the tier the "lightning fast" claim is benchmarked against
- Includes header/footer stripping + reading-order reconstruction

**Tier 2 — Scanned/image PDFs**
- Triggered when a page has no extractable text layer
- Routed to OCR fallback
- Benchmarked and reported separately — OCR performance is not conflated with Tier 1 speed claims

---

## 5. Benchmarking Plan

Benchmarking is a first-class deliverable, built alongside the pipeline (not bolted on after).

### 5.1 Benchmark corpus (public, versioned, checked into repo)
A fixed set of representative real PDFs, covering:
1. Single-column digital-native report
2. Multi-column academic paper (digital-native)
3. Contract/legal doc (digital-native, dense text)
4. Scanned form (image-only, needs OCR)
5. Mixed document (some scanned pages, some digital)

### 5.2 Speed benchmarks
- **Baselines:** PyPDF2, pdfplumber, PyMuPDF (fitz)
- **Metrics:** wall-clock time per document, time per page, throughput under concurrent load (multiple simultaneous FastAPI requests)
- **Methodology:** run N times, report median + p95, same hardware, cold and warm runs noted separately
- Track results per tier — do not average Tier 1 and Tier 2 results together

### 5.3 Accuracy benchmarks
- **Text extraction accuracy:** character/word-level diff against ground-truth transcription for each corpus doc
- **Reading order accuracy:** manual/automated check that multi-column text is reconstructed in correct sequence
- **Header/footer removal:** precision/recall — did it correctly strip repeated boilerplate without removing real content?
- **Downstream retrieval quality (stretch goal):** same corpus, same questions, compare retrieval relevance when chunked via LightningParse output vs. traditional library output

### 5.4 Reporting
- Results published in `BENCHMARKS.md`, regenerated via a script (`benchmark.py`) so numbers are reproducible by anyone who clones the repo
- No claim goes in the README that isn't backed by a number in this file

---

## 6. Milestones

| Phase | Deliverable |
|---|---|
| M1 | Rust: single-PDF, digital-native extraction → structured JSON |
| M2 | PyO3 binding + FastAPI endpoint; first speed benchmark vs. pdfplumber |
| M3 | Page-level parallelism (rayon) added; re-benchmark |
| M4 | Header/footer removal + reading-order logic; accuracy benchmark added |
| M5 | Scanned-page detection + OCR fallback (Tier 2); separate benchmark report |
| M6 | Metadata-aware chunking in Python; end-to-end pipeline through FAISS/Chroma |
| M7 | Benchmark suite finalized, `BENCHMARKS.md` published, repo cleaned up for open-source release |

---

## 7. Success Metrics

- **Speed:** measurable, reproducible speedup factor over pdfplumber/PyMuPDF on Tier 1 corpus (target to be set after M2 baseline is measured — no invented number pre-benchmark)
- **Accuracy:** header/footer removal precision/recall above a defined threshold on benchmark corpus; reading-order correctness verified on multi-column doc
- **Credibility:** benchmark numbers are reproducible by a third party running `benchmark.py` on the published corpus
- **Adoption (if open-sourced):** clear README with honest scope (what it's good at, what it's not), working install path, benchmark results visible without cloning deep into the repo

---

## 8. Risks & Open Questions

- **Table extraction** is unscoped — decide before M4 whether tables are flattened to text or extracted structurally (affects whether `pyo3-polars` is needed)
- **Encrypted/malformed PDFs** — Rust side must not panic; needs explicit `Result`-based error handling mapped to Python exceptions
- **OCR engine choice** — Tesseract is the pragmatic v1 choice but is not state-of-the-art; revisit post-M5 if accuracy is insufficient
- **Benchmark fairness** — must ensure baseline libraries are used correctly/idiomatically (not artificially slowed) to keep comparisons credible
