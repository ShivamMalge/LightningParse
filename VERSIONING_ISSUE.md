# 🚨 OPEN BLOCKER — Version numbering must be resolved before the next release

**Status:** UNRESOLVED. **Do not publish any release until this is decided.**

The decision itself is deliberately deferred to a dedicated conversation. This
document exists so the problem cannot be silently forgotten — not to pick the
answer.

---

## What happened

An earlier session bumped the package version from `0.3.0` straight to `3.1.0`.
That was a numbering mistake: the project was following a `0.x` sequence
(`0.1.0` → `0.2.0` → `0.3.0`), and the intended next release was `0.4.0`.

The mistake was not caught before publishing, so `3.1.0` reached PyPI.

## Current state (verified 2026-08-16)

**Published on PyPI** — `lightningparse`:

| Version | Uploaded | Yanked | Notes |
|---|---|---|---|
| `0.2.0` | 2026-07-29 | No | |
| `0.3.0` | 2026-08-04 | No | |
| `3.1.0` | 2026-08-13 | No | **current `latest`** — the mistaken number |

**In the repo**, `3.1.0` also appears in:

- `lightningparse-core/Cargo.toml` line 3 — `version = "3.1.0"`
- `lightningparse-core/pyproject.toml` line 7 — `version = "3.1.0"`
- `README.md` — a `## What's New in v3.1.0` section, currently sitting directly
  below the newer `## What's New in v0.4.0` section, with the page-tree work
  described in both
- git tag `v3.1.0` — **local and already pushed to the GitHub remote**

## Why this blocks releasing

**A PyPI version number is permanently spent.** PyPI does not allow re-uploading
a version that has been used, even if the release is deleted. `3.1.0` cannot be
reclaimed or reissued.

**Under PEP 440, `0.4.0` sorts below `3.1.0`.** pip resolves to the *highest*
compatible version, not the most recently uploaded one. So if `0.4.0` is
published while `3.1.0` remains active:

```
pip install lightningparse        ->  installs 3.1.0   (NOT the new release)
pip install lightningparse==0.4.0 ->  installs 0.4.0   (only when pinned)
```

Every user doing an ordinary install would silently keep receiving `3.1.0`, and
would never get the ASCII85Decode fix, the filter-allowlist widening, the
page-tree fault tolerance, or the multi-stream join fix.

**⚠️ The existing Phase 6 acceptance check cannot detect this.** `ASCII_PHASES.md`
Phase 6 verifies with `pip install lightningparse==0.4.0 --force-reinstall` and
then confirms `pip show` reports `0.4.0`. Because that command *pins* the
version, it succeeds and reports `0.4.0` even in the broken state. The check
would go green while ordinary users still receive `3.1.0`. Do not treat a
passing Phase 6 as evidence this issue is resolved.

## The options (undecided — do not action from this document)

### Option A — Adopt `3.x` going forward

Accept `3.1.0` as the real current release and continue from it (next release
`3.2.0`).

- Nothing on PyPI needs changing; ordinary installs resolve correctly.
- The `0.x` → `3.x` jump stays in the permanent public record with no
  corresponding major-version meaning.
- Implies the project is signalling post-1.0 stability, which is a separate
  judgement call about API guarantees, not just a numbering preference.

### Option B — Yank `3.1.0` and continue the `0.x` sequence

Yank (PEP 592) the `3.1.0` release, then publish `0.4.0`.

- Yanking removes `3.1.0` from normal resolution, so `pip install lightningparse`
  would then correctly resolve to `0.4.0`.
- Yanking does **not** free the number — `3.1.0` stays permanently reserved and
  remains installable when explicitly pinned. Anyone already on `3.1.0` keeps it.
- Yanking is reversible (a release can be un-yanked); deleting is not, and is
  not recommended.
- Restores a coherent `0.x` sequence consistent with pre-1.0 semantics.

## Related, smaller inconsistency (fold into whichever option is chosen)

`Cargo.toml` and `pyproject.toml` have been out of sync since the `0.2.0`
release, independently of the `3.1.0` mistake:

- `pyproject.toml` tracked `0.1.0` → `0.2.0` → `0.3.0` → `3.1.0`
- `Cargo.toml` went `0.1.0` → `3.1.0` directly, never recording `0.2.0` or `0.3.0`

Whichever numbering is adopted, these two files should be reconciled and kept in
lockstep. (`lightningparse-api/pyproject.toml` is a separate, unpublished
component at `0.1.0` and is not affected.)

## Before this is closed out

- [ ] Decide Option A or Option B in a dedicated conversation
- [ ] Apply the decision to `Cargo.toml`, `pyproject.toml`, and the `README.md`
      "What's New" headings (removing the now-duplicated page-tree description)
- [ ] Resolve the pushed `v3.1.0` git tag consistently with the decision
- [ ] Replace the Phase 6 acceptance check with an **unpinned** `pip install
      lightningparse` that asserts the resolved version is the intended one
- [ ] Delete this file only once the above are all done
