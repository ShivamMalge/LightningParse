# PHASES.md

Detailed build plan, expanding the milestone table in `PRD.md` §6 into actionable checklists with acceptance criteria. Work through phases in order — each one has a concrete "done" condition, usually a benchmark number or a passing test suite, not just "code written."

Don't start a phase until the previous one's acceptance criteria are met. Skipping ahead (e.g., building OCR before Tier 1 is benchmarked) is how the speed/accuracy claims end up unverifiable.

---

## Phase 0 — Scaffolding

**Goal:** empty-but-working skeleton across the whole stack, so every later phase has a place to land.

- [ ] `lightningparse-core/` Cargo project initialized, `lopdf` (or `pdfium-render`) added as dependency
- [ ] `lightningparse-api/` FastAPI project initialized, basic `/health` route
- [ ] PyO3 module compiles and is importable from Python (`maturin develop`), even if it just returns a hardcoded string
- [ ] `benchmarks/` folder created with empty `corpus/` and a `benchmark.py` stub that can at least invoke pdfplumber on a file
- [ ] Repo docs in place: `PRD.md`, `ARCHITECTURE.md`, `AGENTS.md`, `README.md` (already done)

**Acceptance:** `maturin develop --release` succeeds, and `python -c "import lightningparse"` doesn't error.

---

## Phase 1 (M1) — Digital-Native Extraction, Single PDF

**Goal:** Rust can take one digital-native PDF and produce the structured JSON schema defined in `ARCHITECTURE.md` §3.1 — no parallelism, no header/footer logic, no OCR yet. Correctness first, speed later.

- [ ] `extract/` module: parse a single PDF, extract text blocks with bbox + page number
- [ ] `output/` module: serialize to the JSON schema in `ARCHITECTURE.md` §3.1
- [ ] Basic `Result<T, ParseError>` error handling — malformed PDF returns an error, doesn't panic
- [ ] `cargo test` covers: valid PDF, empty PDF, corrupted/truncated PDF
- [ ] Add 2-3 real digital-native PDFs to `lightningparse-core/tests/fixtures/` (not the benchmark corpus yet)

**Acceptance:** `cargo test` passes with zero Python involved. Output JSON validated against schema manually on at least one real document.

---

## Phase 2 (M2) — PyO3 Binding + First Benchmark

**Goal:** the full FFI path works end-to-end, and you have your first real speed number against a baseline.

- [ ] `ffi/` module: expose `parse_pdf(path: &str) -> PyResult<String>` (JSON string, per architecture decision)
- [ ] GIL released via `Python::allow_threads` around the parse call
- [ ] `ParseError` variants mapped to specific Python exceptions
- [ ] `bindings.py` wraps the compiled extension; `api/` exposes a `/parse` FastAPI route
- [ ] `benchmarks/corpus/` populated with the 5 documents listed in `BENCHMARKS.md`
- [ ] `benchmark.py` runs LightningParse vs. pdfplumber/PyPDF2/PyMuPDF on Tier 1 docs, N=10 runs, reports median/p95
- [ ] `BENCHMARKS.md` regenerated with real numbers (Tier 1 section only)

**Acceptance:** a real speed number exists in `BENCHMARKS.md`, reproducible by running `benchmark.py --tier 1`. This number is what everything downstream gets compared against — don't skip getting it before optimizing further.

---

## Phase 3 (M3) — Page-Level Parallelism

**Goal:** parallelize extraction across pages with `rayon`, and confirm it actually helps.

- [ ] `extract/` refactored to process pages concurrently via `rayon`
- [ ] Confirm output ordering is still correct after parallelization (page order in JSON matches document order — parallel execution, deterministic output)
- [ ] Re-run `benchmark.py --tier 1`, compare against Phase 2 numbers
- [ ] Add a multi-page (20+ page) document to the corpus specifically to make parallelism gains visible — single-page docs won't show a difference

**Acceptance:** `BENCHMARKS.md` shows a measurable improvement on multi-page documents over the Phase 2 baseline. If there's no improvement, investigate before moving on — don't assume rayon "just helps."

---

## Phase 4 (M4) — Header/Footer Removal + Reading Order

**Goal:** the accuracy-critical logic described in `ARCHITECTURE.md` §4.

- [ ] `cleanup/` module: cross-page positional clustering for header/footer detection (per architecture doc — tag, don't delete)
- [ ] Reading-order reconstruction for multi-column layouts
- [ ] Accuracy benchmark added to `benchmark.py`: precision/recall for header/footer detection against manually-labeled ground truth on corpus docs
- [ ] Reading-order correctness check added for the multi-column academic paper in the corpus
- [ ] `BENCHMARKS.md` Tier 1 accuracy section populated

**Acceptance:** header/footer precision and recall both above the threshold set in `PRD.md` §7 (define the number here once Phase 2/3 baseline accuracy is known — don't invent it before measuring). Multi-column doc reads in correct order, verified manually.

---

## Phase 5 (M5) — Scanned-Page Detection + OCR Fallback

**Goal:** Tier 2 exists and is honestly benchmarked separately from Tier 1.

- [ ] `ocr/` module: per-page detection of missing text layer (per `ARCHITECTURE.md` §5 routing logic)
- [ ] Tesseract binding integrated, invoked only for pages routed to Tier 2
- [ ] `metadata.tier` field correctly reports `"digital"`, `"scanned"`, or `"mixed"` per document
- [ ] Scanned form + mixed document from the corpus processed end-to-end
- [ ] `benchmark.py --tier 2` implemented, run separately from `--tier 1` — results never combined
- [ ] `BENCHMARKS.md` Tier 2 and "Mixed documents" sections populated

**Acceptance:** scanned document produces usable output; mixed document correctly routes each page independently and reports itself as `"mixed"` in metadata. Tier 2 numbers are visibly separate in `BENCHMARKS.md`, not blended into Tier 1 claims anywhere (including README).

---

## Phase 6 (M6) — Chunking + End-to-End Pipeline

**Goal:** the Python side of the pipeline is wired up, consuming real structured JSON.

- [ ] `chunking/` module: metadata-aware chunker respecting `section_id` boundaries, carrying `page_num` into chunk metadata
- [ ] Embeddings step wired to FAISS or Chroma (pick one for v1, note the choice)
- [ ] LangChain wiring for the retrieval → LLM step
- [ ] End-to-end integration test: PDF in → chunks with correct page metadata → retrieval returns expected chunk for a known query
- [ ] Concurrent-load benchmark added (per `BENCHMARKS.md` "Concurrent load test" section) to validate GIL-release behavior under real FastAPI traffic

**Acceptance:** a PDF can go in one end and a cited LLM answer come out the other, with page-number traceability intact. Concurrent load test shows throughput scaling with concurrent requests (validates `ARCHITECTURE.md` §3.4 claims).

---

## Phase 7 (M7) — Benchmark Finalization + Open-Source Readiness

**Goal:** everything needed to publish this credibly.

- [ ] Full benchmark suite (`benchmark.py --all`) runs clean, `BENCHMARKS.md` fully populated across Tier 1, Tier 2, mixed, and concurrent load
- [ ] README speed/accuracy claims cross-checked against `BENCHMARKS.md` — nothing stated that isn't backed by a number
- [ ] `cargo clippy -- -D warnings` and Python type checks clean across the repo
- [ ] License chosen, `README.md` License section updated
- [ ] Install instructions verified on a clean environment (not just the dev machine)
- [ ] Known limitations section written honestly: table extraction, encrypted PDFs, ML layout detection all explicitly noted as out of scope (per `PRD.md` §2)

**Acceptance:** a third party could clone the repo, run `benchmark.py --all`, and get results matching what's published in `BENCHMARKS.md`. This reproducibility is the actual bar for "ready" — not a feeling of doneness.

---

## Notes on Sequencing

- Phases 1→3 are all Tier 1 / speed-focused — deliberately sequenced before any accuracy or OCR work, so the core "lightning fast" claim gets proven on the simplest path first.
- Phase 4 (accuracy) comes before Phase 5 (OCR) on purpose — fixing header/footer and reading-order logic is more valuable per hour spent than starting OCR early, and OCR accuracy work would otherwise contaminate Tier 1 accuracy debugging.
- If time-constrained and this stays a portfolio project rather than going open-source, Phases 0–4 alone are enough to make a legitimate, benchmarked claim about Tier 1 performance. Phases 5–7 are what make the "mixed PDF" and "open-source ready" goals real — treat them as a second milestone, not a requirement to call the project done.
