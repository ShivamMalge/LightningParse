# AGENTS.md

Instructions for AI coding agents (Claude Code, etc.) working in this repository. Read this before making changes. See `docs/PRD.md` for product scope and `docs/ARCHITECTURE.md` for system design — this file is about how to work in the codebase day to day.

---

## 1. Repo Layout

```
lightningparse/
├── lightningparse-core/     # Rust: PDF parsing engine
│   ├── src/
│   │   ├── extract/         # Tier 1: digital-native extraction
│   │   ├── ocr/              # Tier 2: scanned-page OCR fallback
│   │   ├── cleanup/          # header/footer detection, reading order
│   │   ├── output/           # JSON serialization
│   │   └── ffi/               # PyO3 bindings ONLY — no business logic here
│   └── Cargo.toml
├── lightningparse-api/       # Python: FastAPI service
│   ├── api/                  # routes, request/response models
│   ├── chunking/             # metadata-aware chunker
│   ├── pipeline/             # embeddings, FAISS/Chroma, LangChain
│   ├── bindings.py           # wraps the compiled Rust extension
│   └── pyproject.toml
├── benchmarks/                # speed + accuracy benchmark suite
│   ├── corpus/                # fixed set of test PDFs (versioned)
│   ├── benchmark.py
│   └── BENCHMARKS.md          # generated results, not hand-edited
├── PRD.md
├── ARCHITECTURE.md
└── AGENTS.md                  # this file
```

---

## 2. Build & Test Commands

**Rust core:**
```bash
cd lightningparse-core
cargo build --release          # release build (always benchmark against release, never debug)
cargo test                     # pure-Rust unit tests, no Python required
cargo clippy -- -D warnings    # must pass before any commit
```

**Python bindings (maturin):**
```bash
cd lightningparse-core
maturin develop --release      # builds Rust + installs into active Python env
```

**Python API:**
```bash
cd lightningparse-api
pip install -e .
pytest                         # integration tests, requires the Rust extension built above
```

**Benchmarks:**
```bash
cd benchmarks
python benchmark.py --tier 1   # digital-native only
python benchmark.py --tier 2   # scanned/OCR only
python benchmark.py --all      # full suite, regenerates BENCHMARKS.md
```

Never hand-edit `benchmarks/BENCHMARKS.md` — it's generated output. If it looks wrong, fix the benchmark script or the underlying code, then regenerate.

---

## 3. Non-Negotiable Rules

These map directly to decisions in `docs/ARCHITECTURE.md` — don't relitigate them in a PR without updating that doc first.

1. **No business logic in `ffi/`.** Extraction, cleanup, and OCR logic must be testable via `cargo test` with zero Python involvement. If you find yourself importing PyO3 types outside `ffi/`, stop and restructure.
2. **No panics across the FFI boundary.** Every fallible operation in the Rust core returns `Result<T, ParseError>`. A malformed PDF must produce a mapped Python exception, never crash the process.
3. **GIL must be released during parsing.** Any FFI entry point that does real parsing work wraps the call in `Python::allow_threads`. If you add a new entry point, check this.
4. **Tier routing is per-page, not per-document.** Don't "simplify" this to a per-document check — real PDFs are frequently mixed, and this is called out explicitly as core to correctness in `docs/ARCHITECTURE.md` §7.
5. **Tier 1 and Tier 2 benchmark numbers are never averaged together.** If you touch `benchmark.py`, keep the reporting split. A combined number hides regressions and misrepresents the speed claim.
6. **Every performance claim needs a corresponding benchmark run.** Don't add speed/accuracy language to `README.md` without a number in `BENCHMARKS.md` backing it.
7. **Header/footer detection tags, doesn't delete.** Flagged blocks get `section_id: "header"/"footer"`, not removal from the output — downstream consumers decide whether to filter them.

---

## 4. Code Style

**Rust:**
- `cargo fmt` before every commit, `cargo clippy -- -D warnings` must be clean
- Prefer explicit `Result`/`Option` handling over `.unwrap()` anywhere near the FFI boundary or file I/O; `.unwrap()` is acceptable only in `#[cfg(test)]` code
- Use `rayon` for page-level parallelism; don't introduce manual thread management unless there's a specific reason `rayon` doesn't fit

**Python:**
- Type hints required on all function signatures in `api/`, `chunking/`, `pipeline/`
- FastAPI route handlers stay thin — business logic lives in `chunking/` or `pipeline/`, not inline in route functions
- `bindings.py` is the only file that imports the compiled Rust extension directly; everything else imports from `bindings.py`

---

## 5. When Adding a Feature

Before writing code, check:
- Does this belong in Rust (`lightningparse-core`) or Python (`lightningparse-api`)? Rule of thumb: anything before "clean structured JSON" is Rust; anything after is Python. See `docs/ARCHITECTURE.md` §2.
- Does it affect the FFI schema (§3.1 in `docs/ARCHITECTURE.md`)? If so, update the schema doc in the same PR.
- Does it change Tier 1 or Tier 2 behavior? Run the relevant benchmark before and after, and note the delta in the PR description.
- Does it introduce a new dependency? Justify it — this project intentionally avoids adding dependencies "just in case" (e.g., `pyo3-polars` is explicitly optional, only pulled in if table extraction is prioritized — see PRD §8).

---

## 6. When Fixing a Bug

- Reproduce it as a `cargo test` case first if it's in the Rust core, even if it was discovered via the Python API — this keeps the core's test suite meaningful independent of Python.
- If the bug involves a malformed/edge-case PDF, add it to `benchmarks/corpus/` only if it's representative of a real document type; otherwise add it to `lightningparse-core/tests/fixtures/` as a regression test, not the benchmark corpus (keep the benchmark corpus stable so historical numbers stay comparable).

---

## 7. Things to Never Do

- Don't optimize FFI serialization before profiling shows it's a bottleneck (see `docs/ARCHITECTURE.md` §7 decision log)
- Don't merge a change to header/footer or tier-routing logic without re-running the accuracy benchmark
- Don't add ML-based layout detection — out of scope for v1 per `docs/PRD.md` §2 non-goals; if this changes, it changes in the PRD first
- Don't let `benchmark.py` silently swallow a failed baseline-library run — a missing comparison point is worse than no comparison
