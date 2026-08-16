# ASCII_PHASES.md

> **Versioning: resolved.** The release-blocker banner that stood here is
> cleared. **Option B** was chosen — continue the `0.x` sequence and yank `3.1.0`
> — and the repo now reads `0.4.0` consistently. See
> [`VERSIONING_ISSUE.md`](./VERSIONING_ISSUE.md), kept as the record of what
> happened, for the one remaining verification step before publishing.

Detailed build plan for closing the `ASCII85Decode` content-stream filter gap, tracked as a known limitation since v0.3.0. This ships as part of `v0.4.0` alongside the already-implemented (pending final verification) fault-tolerant page-tree traversal work.

Follows the same phase-by-phase, plan-before-implement, verify-before-proceeding discipline as `PHASES.md` and `PHASES-EXTRACTION-FIDELITY.md`.

---

## Phase 0 — Verify Existing v0.4.0 Work (Page Tree Fault Tolerance) — ✅ COMPLETE

> **Status: COMPLETE.** Verified 2026-08-16 against the current tree, not
> self-reported. Both the fault-tolerance path and the loud-failure path work as
> described. One scope caveat is recorded under the first item.

- [x] Confirm the specific fixture(s) used to prove fault-tolerant traversal — **confirmed: 10 tests in `src/extract/page_tree.rs`**, covering the required cases: `test_missing_type_pages`, `test_missing_type_page`, `test_malformed_type_values` (mis-capitalization), `test_circular_kids_references` (abort-on-loop), plus `test_malformed_kids_not_treated_as_page`, `test_missing_catalog_pages_entry_fallback`, `test_nested_page_tree`, `test_inherited_page_attributes`, and two valid-tree controls.
  - ⚠️ **Scope caveat:** all 10 build `lopdf::Document` objects **in memory** via the API — none contain `Document::load`, `load_mem`, or `include_bytes`. They therefore prove the *tree-walking* logic but never exercise parsing a malformed PDF's **bytes off disk**. Byte-level robustness is covered separately by `test_corrupted_bytes_returns_error`, `test_truncated_pdf_returns_error`, and `test_random_bytes_never_panics`, but no test combines *malformed bytes* with a *malformed page tree*. Accepted as sufficient; noted so the gap isn't mistaken for coverage.
- [x] `cargo test` passes, including a dedicated regression test for the malformed-tree case that confirms pages are extracted **correctly**, not merely that nothing crashed — confirmed. The tests assert page *identity*, e.g. `test_missing_type_pages` asserts both `pages.len() == 1` and `pages[&1] == page_id`. Strongest of the set is `test_lopdf_get_pages_fails_tolerant_succeeds`, a differential test asserting that `lopdf`'s own `get_pages()` returns **0** pages for the malformed tree while `get_pages_tolerant()` returns the right one — so the test would fail loudly if the fault tolerance silently stopped being needed or stopped working. It still passes under `lopdf` 0.44, confirming upstream has not absorbed this behaviour.
- [x] Confirm `CorruptPdfError` is raised correctly on the Python side for a genuinely unparseable PDF — **explicitly tested, not assumed.** The current source was built with `maturin build --release` into `lightningparse-0.4.0-cp311-cp311-win_amd64.whl` and installed into a throwaway venv (deliberately *not* the system environment, which still held a stale published `0.2.0` wheel — testing against that would have proven nothing about this code). Four unparseable inputs each raised `CorruptPdfError` with a real message:

  | Input | Result |
  |---|---|
  | random non-PDF bytes | `CorruptPdfError: Failed to parse PDF: couldn't parse input: invalid file header` |
  | truncated PDF (first 1/3 of a valid file) | `CorruptPdfError: … failed parsing cross reference table: invalid start value` |
  | empty file | `CorruptPdfError: … invalid file header` |
  | header only, no objects | `CorruptPdfError: … invalid start value` |

  `CorruptPdfError` subclasses `Exception` (MRO: `CorruptPdfError → Exception → BaseException → object`), so it is catchable both specifically and generically. The happy path through the same entry point still returns `tier="digital"` with `"Hello ASCII85 World"`, confirming the error path was not bought at the cost of the success path.
- [x] Confirm this didn't regress anything in the existing corpus — full suite green, 33 tests (19 unit + 3 cleanup + 11 integration).
  - ⚠️ **Only 4 of the 6 fixtures named in this checklist item are actually exercised by any test.** Covered by the suite: `arxiv_twocolumn.pdf`, `ieee_template_placeholder.pdf`, `Shivam_FullStack.pdf`, `code_block_fixture.pdf` (plus `bold_label_value.pdf`, `ascii85_test.pdf`, `multistream_test.pdf`, `tier2/mixed_test.pdf`). **Not referenced by any test:** `digital_word_export.pdf` and the CJK fixture `tests/fixtures/tier1/XeLaTeX.pdf` — both exist on disk but no test loads them. Also orphaned: `tier2/scan-to-pdf-1785075273618.pdf`, `phone_photo_invoice.pdf`, `phone_photo_minutes.pdf`.
  - Both named-but-untested fixtures were therefore parsed **manually** to close the item: `XeLaTeX.pdf` → `tier: "digital"`, 1 page, 5 blocks, no warnings, CJK text extracted (`"中文测试文档…"`, `"日本語…テスト…"`); `digital_word_export.pdf` → `tier: "digital"`, 2 pages, 16 blocks, no warnings, clean text (`"CONFIDENTIAL MEMORANDUM"`, `"To: Engineering Team"`). Neither regressed.
  - Separate pre-existing observation, **not** attributable to this release: `XeLaTeX.pdf`'s CJK output carries replacement/surrogate artifacts (`\udc81`, `\xad`) mixed into otherwise-correct glyphs. This is consistent with the CID/ToUnicode limitations already recorded in `ARCHITECTURE.md`, but there is no pre-upgrade baseline captured, so it cannot be proven unchanged. Worth a dedicated look; see the note in "After This Ships".

**Acceptance:** ✅ met — manual confirmation, not agent self-report. The fault-tolerance path is proven by a differential test against `lopdf`'s own parser; the loud-failure path is proven by executing real Python against a freshly built wheel of this exact source.

---

## Phase 1 — Investigate Upstream Support — ✅ COMPLETE

> **Status: COMPLETE.** Outcome: **upstream support exists and the upgrade was
> clean**, so this took the "skip Phase 2" branch. Changelog findings were read
> from the vendored `CHANGELOG.md` in the crates.io source of both versions, not
> recalled from memory.

- [x] Check the currently pinned `lopdf` version in `Cargo.toml` — was `0.33`, now **`0.44`** (bumped in `84a91f5`).
- [x] Check `lopdf`'s changelog for any version that added native `ASCII85Decode` support — **found: `Add ASCII85 decoding (#317)` in v0.34.0** (2024-08-31), the very next release after 0.33. Two follow-up fixes landed in v0.35.0: `Fix mulitplication overflow in ascii85 decode (#348)` and `Also accept ASCII85 streams without EOD marker (#354)`. ⚠️ Worth recording plainly: **0.35.0 would have sufficed.** Going to 0.44 pulled in ten releases of unrelated change surface for a feature available three releases in.
- [x] Evaluate the upgrade — check for breaking API changes, upgrade, run the full test suite before writing new code — done. Two API changes actually touched this codebase, both visible in `84a91f5`: `Document::get_page_content()` became **infallible**, returning `Vec<u8>` instead of `Result<Vec<u8>>` (v0.44.0, *"Make `Document::get_page_content` return `Vec<u8>` since it cannot fail"*), and `Stream::filters()` returns `Vec<&[u8]>` rather than `Vec<String>`, forcing byte-string comparison in the allowlist. Suite was green after the upgrade.
  - ⚠️ The infallibility change is not cosmetic. It is the direct cause of the open malformed-stream finding in Phase 4: with no `Result` to propagate, a failed ASCII85 decode is swallowed upstream and returned as raw undecoded bytes.
  - Behavioural changes beyond that pair were surveyed across v0.34.0–v0.44.0. The most relevant is v0.42.0 `Insert newline between concatenated content streams`, which turned out to be a **correctness fix** we now depend on — see `test_multistream_page_segmentation` in Phase 4. Also reviewed and found not to affect this codebase: v0.40.0 `Fix WinAnsiEncoding handling in SimpleEncoding string conversion`, v0.39.0's `is_encrypted()` breaking change, v0.34.0 `Replace LinkedHashMap with IndexMap`, and v0.44.0's decompression-bomb bounds (opt-in — `LoadOptions.max_decompressed_size` is `Option<usize>` defaulting to `None`, and `load_mem` takes that default, so no limit is imposed).
- [x] Document the outcome either way — done in the `ARCHITECTURE.md` decision log row ("Content stream filter support via lopdf 0.44 (resolved)"), which records that the fix was a version bump plus an allowlist entry rather than a hand-written decoder. Phase 2 below is marked MOOT with the same reasoning.

**If upstream support exists and the upgrade is clean:** skip to Phase 4 (Testing), since Phase 2/3 become unnecessary.

**If no upstream support exists, or upgrading introduces unacceptable breaking changes:** proceed to Phase 2.

---

## Phase 2 — Implement the ASCII85 Decoder — ❌ MOOT (not implemented, not needed)

> **Status: MOOT — superseded by Phase 1.** No custom decoder was written and none
> should be. Phase 1 found native upstream support: `lopdf` added ASCII85 decoding
> in **0.34.0** (`Add ASCII85 decoding (#317)`), with two follow-up fixes in
> **0.35.0** — `Fix mulitplication overflow in ascii85 decode (#348)` and
> `Also accept ASCII85 streams without EOD marker (#354)`. The project upgraded
> `lopdf` 0.33 → 0.44 in commit `84a91f5`, so decoding happens inside `lopdf`'s
> `get_page_content()` before our code ever sees the bytes.
>
> This took the Phase 1 branch: *"If upstream support exists and the upgrade is
> clean: skip to Phase 4 (Testing), since Phase 2/3 become unnecessary."*
> (Phase 3 was done anyway — the allowlist still had to learn the filter was
> supported. See Phase 3.)
>
> **There is no `extract/ascii85.rs` and no decoder of ours to test.** The
> correctness requirements below are now `lopdf`'s responsibility, retained here
> as a record of what was scoped, not as outstanding work.

**Original goal (not pursued):** decode ASCII85-encoded content stream bytes into raw bytes before handing them to the existing (FlateDecode-equivalent) parsing pipeline in `extract/mod.rs`. The rest of the pipeline should not need to know decoding happened.

### Required correctness — ~~ours~~ now handled upstream by `lopdf` 0.44

- ~~Handle the optional `<~` prefix and `~>` suffix delimiters~~ — upstream; `0.35.0` also accepts streams with no EOD marker
- ~~Handle the `z` shorthand (four zero bytes)~~ — upstream
- ~~Handle the final partial group correctly~~ — upstream; incidentally exercised by our fixture (see Phase 4)
- ~~Ignore whitespace within the encoded stream~~ — upstream
- ~~A malformed or truncated stream must return `Err(ParseError::...)`, never panic~~ — upstream decode failure surfaces through our existing `Result` path; see the open item in Phase 4

### Where this lives
- ~~New decoding logic should be a self-contained function/module (e.g. `extract/ascii85.rs`)~~ — **not created.** The only project-side change was the filter allowlist in `extract/mod.rs` (Phase 3).

---

## Phase 3 — Filter Detection & Routing — ✅ COMPLETE

> **Status: COMPLETE.** Delivered by commit `bd5bbe5` ("Fix ASCII85Decode: add to
> filter allowlist, regenerate valid fixture, add end-to-end test").
>
> Note the sequencing, since it is easy to misread: the `lopdf` upgrade commit
> `84a91f5` did **not** add the filter to the allowlist — it only changed
> `filter != "FlateDecode"` to `filter != b"FlateDecode"` for the
> `Vec<String>` → `Vec<&[u8]>` signature change. Between `84a91f5` and `bd5bbe5`,
> ASCII85 PDFs extracted text correctly but still emitted a spurious
> "unsupported filter, falling back to OCR" warning. `bd5bbe5` closed that gap.

- [x] Update the content-stream filter detection logic to recognize `ASCII85Decode` as now-supported, routing it through the new decoder instead of the unsupported-filter warning path — done in `bd5bbe5`; routing is implicit (`lopdf` decodes upstream), so the change was to stop warning. See `extract/mod.rs`, `extract_page()`.
- [x] Confirm the filter allowlist/check is structured so a *future* additional filter is a small, localized change — the check is a single `matches!` over `FlateDecode | LZWDecode | ASCII85Decode | ASCIIHexDecode | RunLengthDecode`; adding a filter is a one-line edit. Flagged in `ARCHITECTURE.md` that this list is hand-maintained and does **not** derive from `lopdf`, so it must be widened in lockstep if upstream gains a filter.
- [x] The `warnings` mechanism itself must remain in place and functional for any *other* still-unsupported filter — verified with a negative control: a synthetic PDF using `JBIG2Decode` still emits `"Page 1: content stream uses unsupported filter 'JBIG2Decode', falling back to OCR"`, populates `metadata.warnings`, and routes to `tier: "scanned"`. The safety net is intact.

---

## Phase 4 — Testing — ⚠️ MOSTLY COMPLETE (1 item open, 1 descoped)

> **Status: acceptance criteria met. Of the two edge-case tests that were never
> written, one is descoped and one stays open.**
>
> They were triaged by asking whether any project-side code sits between the
> encoded bytes and the result — i.e. whether a test would exercise *our* logic
> or merely re-test `lopdf`:
> - **`z` shorthand → descoped.** Purely upstream. No branch of ours depends on it.
> - **Malformed/truncated stream → stays open.** *Not* purely upstream. `lopdf`
>   0.44's `get_page_content()` is infallible and returns raw undecoded bytes on
>   a decode failure, so everything after that point is our code — and it
>   currently misroutes to OCR silently. Details on the item below.

- [x] Generate (or reuse) a synthetic PDF using genuine `ASCII85Decode` content-stream encoding — `benchmarks/corpus/ascii85_test.pdf`, regenerated in `bd5bbe5`. The prior fixture was invalid: its payload decoded to binary garbage (`x\5c\f2\a0…`), never valid PDF operators. The current one decodes to `BT /F1 12 Tf 50 700 Td (Hello ASCII85 World) Tj ET`.
- [x] ~~Add a dedicated test case exercising the `z` shorthand specifically~~ — **DESCOPED, deliberately.** Rationale: with Phase 2 moot there is no project-side code between the encoded bytes and the decoded output for this case. `lopdf` decodes inside `get_page_content()`; we never see the `z`. A test here would assert only that `lopdf`'s ASCII85 alphabet handling is correct, which is upstream's test to own (`lopdf` 0.34.0 `#317`, hardened in 0.35.0 by `#348`/`#354`). There is no branch in our code that a `z` reaches and a non-`z` does not. Descoped rather than left open indefinitely.
- [x] Add a dedicated test case with an odd/partial final group — **satisfied incidentally by the existing fixture**, confirmed by analysis rather than assumed: the payload is 63 data chars = 12 full 5-char groups + a 3-char remainder, decoding to 50 bytes (*not* a multiple of 4). `test_ascii85_digital_extraction` asserts the exact decoded string, which would fail if partial-group padding/truncation were wrong. No separate fixture needed.
- [ ] **OPEN — do NOT descope. This one exercises our code, and current behaviour contradicts the requirement.** A malformed/truncated ASCII85 stream does *not* return a `ParseError`. Verified empirically with two synthetic PDFs (invalid alphabet bytes; valid alphabet truncated mid-group): both parse to `tier: "scanned"`, zero blocks, **and an empty `warnings` array** — silently routed to Tier 2 OCR, indistinguishable in the output from a genuine scanned page.

  **Why this is our code, not `lopdf`'s:** `Document::get_page_content()` is infallible in `lopdf` 0.44 and swallows decode failures — `document.rs:599-602` does `match content_stream.decompressed_content() { Ok(data) => …, Err(_) => content.extend_from_slice(&content_stream.content) }`, i.e. **on decode failure it appends the still-encoded raw bytes.** Those raw bytes then flow into our `Content::decode(…).map_err(ParseError::CorruptPdf)` in `extract/mod.rs`, which does *not* reject them (no `ParseError` is raised), yielding zero text operators → `total_chars == 0` → the OCR fallback in `lib.rs`. Every step after `lopdf` returns is ours.

  This is the same silent-misrouting failure mode the original Known Limitation described for `lopdf` 0.33, still reachable via a *corrupt* (rather than unsupported) ASCII85 stream. The filter allowlist does not help: the filter is on it, so no warning fires. **Needs a decision — this is arguably a behaviour gap, not just a test gap.**
- [x] Confirm the previously ASCII85-triggering test PDF now extracts via Tier 1 with empty warnings and `tier: "digital"` — **N/A as literally written**: the LightningRAG benchmark document is not in this repo (`lightningrag` appears nowhere outside this file), so it is not reproducible here. Equivalent proof is provided by `ascii85_test.pdf` via `test_ascii85_digital_extraction`, which asserts `tier == "digital"`, `warnings.is_empty()`, and `source == "digital"` on every block.
- [x] Full regression run across the existing corpus — full suite green (33 tests: 19 unit + 3 cleanup + 11 integration) with no behavioral change for non-ASCII85 documents.

**Acceptance:** ✅ met.
- `cargo test` — green, 33 passed / 0 failed.
- `cargo clippy --all-targets -- -D warnings` — clean.
- Manual JSON inspection — done, not inferred from test pass/fail. Parsing `ascii85_test.pdf` yields `text: "Hello ASCII85 World"`, `bbox: [50.0, 700.0, 164.0, 712.0]`, `tier: "digital"`, `warnings` absent (serde skips the empty vec). The extracted string was compared against an independent decode of the raw stream and matches exactly. The `dump_json` debug bin (`src/bin/dump_json.rs`, added in `d2e6313`) exists for exactly this inspection.

### Added beyond the original plan

- [x] `test_multistream_page_segmentation` (`d2e6313`) — covers a gap this plan never anticipated. `lopdf` 0.42 began inserting a newline between concatenated content streams. `benchmarks/corpus/multistream_test.pdf` joins two streams at `...Tj ET` + `BT ...` with no whitespace either side; without the separator the operators fuse into a single invalid `ETBT` token and a text-object boundary is lost **with no error raised**. The one real-world multi-stream page in the corpus (`arxiv_twocolumn.pdf` page 1) joins at `ET\n` + `q`, which is benign either way, so this path was previously untested.

---

## Phase 5 — Documentation — ✅ COMPLETE

> **Status: COMPLETE.** Delivered by commit `d2e6313`. Note these docs were *not*
> updated by `bd5bbe5` alongside the code fix, so between `bd5bbe5` and `d2e6313`
> both files actively contradicted the shipped behaviour.

- [x] Remove the `ASCII85Decode` entry from `README.md`'s Known Limitations section — **rewritten rather than removed**, deliberately. Deleting it outright would have been wrong: a residual limitation still exists for filters outside the supported five. The entry is retitled "Content stream filters outside the supported set", names all five supported filters and `lopdf` 0.44, cites `test_ascii85_digital_extraction` as evidence, and re-scopes the remaining gap to filters like `JBIG2Decode` and `/Crypt`. The false claim that "a full fix (adding an ASCII85 decoder) is still tracked for a future release" was dropped.
- [x] Update `ARCHITECTURE.md`'s decision log — the row is retitled "Content stream filter support via lopdf 0.44 (resolved)". It lists all five supported filters (the original checklist text said three; `ASCIIHexDecode` and `RunLengthDecode` are also on the allowlist), keeps the original problem statement as history, and **explicitly confirms the `warnings` mechanism is retained as a safety net**, citing both the positive test and the `JBIG2Decode` negative control. The "Revisit if..." column now carries a live trigger: the allowlist is hand-maintained and does not derive from `lopdf`.
- [x] If Phase 1 resulted in an upstream version bump rather than custom code, document that decision and the version change instead of describing decoder internals that don't exist — done. The `ARCHITECTURE.md` row states the resolution was the version bump plus the allowlist entry, **not** a hand-written decoder, and records that ASCII85 landed upstream in `lopdf` 0.34.0 with fixes in 0.35.0. No non-existent `extract/ascii85.rs` is described anywhere.

### Documentation added beyond the original plan

- [x] `README.md` "What's New in v0.4.0" section (`84b9be4`) — covers both pieces of the release distinctly, per the Phase 6 requirement not to conflate them.
- [x] `VERSIONING_ISSUE.md` (`dda43de`) — the release blocker described at the top of this file.

---

## Phase 6 — Release as v0.4.0 — ▶️ UNBLOCKED (ready to run)

> ✅ **Gate cleared, preconditions met.** The versioning decision is made
> (**Option B**: continue `0.x`, yank `3.1.0`), applied to the core package, and
> the yank is **confirmed live on PyPI** — verified on both the JSON API and the
> PEP 691 simple index, with `info.version` having dropped from `3.1.0` to
> `0.3.0`. See [`VERSIONING_ISSUE.md`](./VERSIONING_ISSUE.md).

- [x] **Versioning decision made and applied** per [`VERSIONING_ISSUE.md`](./VERSIONING_ISSUE.md) — Option B; `lightningparse-core/Cargo.toml` and `lightningparse-core/pyproject.toml` both read `0.4.0`
- [x] **PRECONDITION met:** `3.1.0` yank confirmed live on PyPI (both endpoints, 2026-08-16)
- [x] Bump `version` in `lightningparse-core/pyproject.toml` to `0.4.0` — done, with `Cargo.toml` bumped alongside it (the original checklist did not cover `Cargo.toml`, which had drifted since `0.2.0`). `lightningparse-api/pyproject.toml` stays at `0.1.0` — separate unpublished package, independently versioned.
- [x] Update `README.md`'s "What's New" section to accurately describe **both** pieces of this release — done in `84b9be4`; the two pieces are given separate bullets, plus a third for the multi-stream join fix. The superseded `## What's New in v3.1.0` section has since been deleted outright, so `v0.4.0` is now the current entry and sits directly above `v0.3.0` with no duplication.
- [ ] Final full verification pass: `cargo clippy -- -D warnings`, `cargo test`, full corpus regression
- [ ] Commit, push
- [ ] `git tag v0.4.0 && git push origin v0.4.0`
- [ ] Watch GitHub Actions — confirm all build jobs (linux x2, windows, macos x2, sdist) pass, then confirm the `release` job publishes successfully via Trusted Publishing
- [ ] Verify from a clean environment: `pip install lightningparse==0.4.0 --force-reinstall --no-cache-dir`, confirm `pip show lightningparse` reports `0.4.0`, and re-run a real parse to confirm the ASCII85 fix works from the actual published wheel, not just the local dev build
  - ⚠️ **This check is insufficient on its own** — pinning `==0.4.0` forces the version, so it passes even while a plain `pip install lightningparse` still resolves to `3.1.0`. Also run an **unpinned** `pip install lightningparse` in a clean environment and assert the resolved version is the intended one. See [`VERSIONING_ISSUE.md`](./VERSIONING_ISSUE.md).

---

## After This Ships

Worth revisiting the LightningRAG comparison benchmark from earlier — re-running it on the same synthetic multi-column test PDF that originally triggered the ASCII85Decode OCR fallback should now show LightningParse extracting via Tier 1 directly, giving a clean, uncontaminated latency/quality comparison against the pypdf baseline. That result (not the OCR-fallback-skewed one) is the one worth keeping as real evidence of LightningParse's actual performance characteristics.
