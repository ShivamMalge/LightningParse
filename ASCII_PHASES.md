# ASCII_PHASES.md

Detailed build plan for closing the `ASCII85Decode` content-stream filter gap, tracked as a known limitation since v0.3.0. This ships as part of `v0.4.0` alongside the already-implemented (pending final verification) fault-tolerant page-tree traversal work.

Follows the same phase-by-phase, plan-before-implement, verify-before-proceeding discipline as `PHASES.md` and `PHASES-EXTRACTION-FIDELITY.md`.

---

## Phase 0 — Verify Existing v0.4.0 Work (Page Tree Fault Tolerance)

Before adding new work to this release, confirm what's already in it is solid. This was implemented but not yet independently verified.

- [ ] Confirm the specific fixture(s) used to prove fault-tolerant traversal — a malformed PDF missing or mis-capitalizing `/Type /Pages` or `/Type /Page`, and ideally one with a circular page-tree reference to confirm the abort-on-loop behavior
- [ ] `cargo test` passes, including a dedicated regression test for the malformed-tree case (not just "doesn't crash" — confirm pages are actually extracted correctly)
- [ ] Confirm `CorruptPdfError` is raised correctly on the Python side for a genuinely unparseable PDF — test this explicitly, don't assume the FFI mapping works just because it compiles
- [ ] Confirm this didn't regress anything in the existing corpus (`arxiv_twocolumn.pdf`, `ieee_template_placeholder.pdf`, `Shivam_FullStack.pdf`, `digital_word_export.pdf`, CJK fixture, `code_block_fixture.pdf`)

**Acceptance:** manual confirmation (not just agent self-report) that both the fault-tolerance path and the loud-failure path work as described.

---

## Phase 1 — Investigate Upstream Support

Before writing a custom decoder, check whether the problem is already solved.

- [ ] Check the currently pinned `lopdf` version in `Cargo.toml`
- [ ] Check `lopdf`'s changelog/release notes for any version that added native `ASCII85Decode` support
- [ ] If a newer version supports it: evaluate the upgrade — check for breaking API changes, upgrade, run the full existing test suite before writing any new code
- [ ] Document the outcome either way in the implementation plan (this is a real decision point, not a formality — report back before proceeding to Phase 2)

**If upstream support exists and the upgrade is clean:** skip to Phase 4 (Testing), since Phase 2/3 become unnecessary.

**If no upstream support exists, or upgrading introduces unacceptable breaking changes:** proceed to Phase 2.

---

## Phase 2 — Implement the ASCII85 Decoder

**Goal:** decode ASCII85-encoded content stream bytes into raw bytes before handing them to the existing (FlateDecode-equivalent) parsing pipeline in `extract/mod.rs`. The rest of the pipeline should not need to know decoding happened.

### Required correctness (per the Adobe / PDF-spec ASCII85 convention — get these right, they're the easy things to get subtly wrong)

- [ ] Handle the optional `<~` prefix and `~>` suffix delimiters — some encoders include them, some don't; both must work
- [ ] Handle the `z` shorthand — a single `z` character represents four consecutive zero bytes (`\x00\x00\x00\x00`), not four `z` characters decoded literally
- [ ] Handle the final partial group correctly — ASCII85 groups are normally 5 encoded characters -> 4 decoded bytes, but the last group in a stream may have fewer than 5 characters, requiring specific padding/truncation logic per spec
- [ ] Ignore whitespace within the encoded stream (some encoders wrap lines with newlines/spaces, which must not be treated as data)
- [ ] A malformed or truncated stream must return `Err(ParseError::...)`, never panic — consistent with `AGENTS.md`'s existing rule that fallible operations return `Result`

### Where this lives
- New decoding logic should be a self-contained function/module (e.g. `extract/ascii85.rs`) with pure input->output behavior (bytes in, `Result<Vec<u8>, ParseError>` out) — this keeps it independently unit-testable without needing a full PDF around it, and matches the project's existing pattern of keeping business logic out of the FFI-facing modules

---

## Phase 3 — Filter Detection & Routing

- [ ] Update the content-stream filter detection logic to recognize `ASCII85Decode` as now-supported, routing it through the new decoder instead of the unsupported-filter warning path
- [ ] Confirm the filter allowlist/check is structured so a *future* additional filter (should one ever need supporting) is a small, localized change — not a reason to revisit this whole code path again
- [ ] The `warnings` mechanism itself must remain in place and functional for any *other* still-unsupported filter — this phase closes one specific gap, it doesn't remove the safety net

---

## Phase 4 — Testing

- [ ] Generate (or reuse, if one already exists from the earlier warnings-verification work) a synthetic PDF using genuine `ASCII85Decode` content-stream encoding
- [ ] Add a dedicated test case exercising the `z` shorthand specifically
- [ ] Add a dedicated test case with an odd/partial final group (not a clean multiple of 4 decoded bytes)
- [ ] Add a dedicated test case for a deliberately malformed/truncated ASCII85 stream — confirm it returns a `ParseError`, not a panic, not silently-wrong output
- [ ] Confirm the previously ASCII85-triggering test PDF (if the LightningRAG benchmark's synthetic test document is available/reproducible) now extracts real text via Tier 1, with `metadata.warnings` empty and `metadata.tier` reporting `"digital"` — not falling back to OCR
- [ ] Full regression run across the existing corpus — confirm zero change in behavior for documents that don't use ASCII85Decode

**Acceptance:** `cargo test` green, `cargo clippy -- -D warnings` clean, and a manual JSON inspection (not just test pass/fail) showing real extracted text on the ASCII85 fixture — read the actual text, confirm it matches what was encoded, don't just check that blocks are non-empty.

---

## Phase 5 — Documentation

- [ ] Remove the `ASCII85Decode` entry from `README.md`'s Known Limitations section — it no longer applies
- [ ] Update `ARCHITECTURE.md`'s decision log: note which filters are now supported (`FlateDecode`, `LZWDecode`, `ASCII85Decode`), and explicitly confirm the `warnings` mechanism remains as a safety net for any filter not on that list
- [ ] If Phase 1 resulted in an upstream `lopdf` version bump rather than custom code, document that decision and the version change instead of describing custom decoder internals that don't exist

---

## Phase 6 — Release as v0.4.0

- [ ] Bump `version` in `lightningparse-core/pyproject.toml` to `0.4.0`
- [ ] Update `README.md`'s "What's New" section to accurately describe **both** pieces of this release: page-tree fault tolerance (from earlier work, now verified per Phase 0) and ASCII85Decode support (this document) — don't let one overshadow or get conflated with the other in the changelog wording
- [ ] Final full verification pass: `cargo clippy -- -D warnings`, `cargo test`, full corpus regression
- [ ] Commit, push
- [ ] `git tag v0.4.0 && git push origin v0.4.0`
- [ ] Watch GitHub Actions — confirm all build jobs (linux x2, windows, macos x2, sdist) pass, then confirm the `release` job publishes successfully via Trusted Publishing
- [ ] Verify from a clean environment: `pip install lightningparse==0.4.0 --force-reinstall --no-cache-dir`, confirm `pip show lightningparse` reports `0.4.0`, and re-run a real parse to confirm the ASCII85 fix works from the actual published wheel, not just the local dev build

---

## After This Ships

Worth revisiting the LightningRAG comparison benchmark from earlier — re-running it on the same synthetic multi-column test PDF that originally triggered the ASCII85Decode OCR fallback should now show LightningParse extracting via Tier 1 directly, giving a clean, uncontaminated latency/quality comparison against the pypdf baseline. That result (not the OCR-fallback-skewed one) is the one worth keeping as real evidence of LightningParse's actual performance characteristics.
