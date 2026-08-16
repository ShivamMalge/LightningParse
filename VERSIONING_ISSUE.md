# ✅ RESOLVED — Version numbering (historical record)

**Decision: Option B — yank `3.1.0`, continue the `0.x` sequence.**
**Decided: 2026-08-16.**

This file is retained deliberately as a record of what happened and why. It is
no longer a blocker. One verification step remains outstanding — see
[Outstanding](#outstanding-before-publishing) below.

---

## What happened

An earlier session bumped the package version from `0.3.0` straight to `3.1.0`.
That was a numbering mistake: the project was following a `0.x` sequence
(`0.1.0` → `0.2.0` → `0.3.0`), and the intended next release was `0.4.0`.

The mistake was not caught before publishing, so `3.1.0` reached PyPI on
2026-08-13, where it became the version a plain `pip install lightningparse`
resolved to.

## Why it mattered

A PyPI version number is permanently spent — PyPI does not allow re-uploading a
version that has been used, even if the release is deleted. `3.1.0` can never be
reclaimed or reissued.

Under PEP 440, `0.4.0` sorts *below* `3.1.0`, and pip resolves to the *highest*
compatible version, not the most recently uploaded one. So publishing `0.4.0`
while `3.1.0` remained active would have meant:

```
pip install lightningparse        ->  3.1.0   (NOT the new release)
pip install lightningparse==0.4.0 ->  0.4.0   (only when pinned)
```

Every ordinary install would have silently kept receiving `3.1.0`, and would
never have received the ASCII85Decode fix, the filter allowlist, the page-tree
fault tolerance, or the multi-stream join fix.

## The decision

**Option B was chosen:** yank `3.1.0` under PEP 592 and continue the `0.x`
sequence with `0.4.0`.

Yanking removes a release from normal pip resolution without deleting it, so
`pip install lightningparse` resolves to `0.4.0` while `3.1.0` remains
installable for anyone who explicitly pins it. Nobody already running `3.1.0` is
broken. Yanking is also reversible; deleting is not, and was not considered.

The rejected alternative (**Option A**) was to adopt `3.x` going forward and
release `3.2.0` next. It was rejected because the `0.x` → `3.x` jump carried no
real major-version meaning and would have implied post-1.0 API stability
guarantees the project has not made.

`3.1.0` remains permanently reserved on PyPI. That is unavoidable and is the
lasting cost of the original mistake.

## What was changed in the repo (2026-08-16)

| File | Before | After |
|---|---|---|
| `lightningparse-core/Cargo.toml` | `3.1.0` | `0.4.0` |
| `lightningparse-core/pyproject.toml` | `3.1.0` | `0.4.0` |
| `lightningparse-api/pyproject.toml` | `0.1.0` | *unchanged* — see note below |
| `README.md` | had a `## What's New in v3.1.0` section | section deleted entirely; `v0.4.0` is the current entry |
| `ASCII_PHASES.md` | release-blocker banner, Phase 6 gated | banner cleared, Phase 6 unblocked |

Note on `lightningparse-api`: this is a **separate, unpublished package**
(`lightningparse-api`, confirmed absent from PyPI) and is **deliberately left at
`0.1.0`**. It was briefly bumped to `0.4.0` to give the repo a single version
number, then reverted: the two are independently versioned packages, and
coupling the unpublished API layer's number to the core package's would imply a
release relationship that does not exist. Only `lightningparse-core`
(`Cargo.toml` + `pyproject.toml`) tracks the `0.4.0` release.

The `README.md` v3.1.0 section was safe to delete outright because its two
entries — fault-tolerant page tree traversal and `CorruptPdfError` propagation —
are both covered, more accurately, by the v0.4.0 section, which additionally
documents the multi-stream join fix the v3.1.0 section never mentioned.

## Related inconsistency, now fixed

`Cargo.toml` and `pyproject.toml` had been out of sync since the `0.2.0`
release, independently of the `3.1.0` mistake:

- `pyproject.toml` tracked `0.1.0` → `0.2.0` → `0.3.0` → `3.1.0`
- `Cargo.toml` went `0.1.0` → `3.1.0` directly, never recording `0.2.0` or `0.3.0`

Both now read `0.4.0`. **Keep them in lockstep on every future release.**

## Outstanding before publishing

- [x] **Confirm the `3.1.0` yank is live on PyPI — ✅ CONFIRMED 2026-08-16.**
      Verified against both endpoints independently:

      | Endpoint | Result |
      |---|---|
      | JSON API (`/pypi/lightningparse/json`) | `3.1.0` → `yanked=True` |
      | PEP 691 simple index (what pip actually reads) | `lightningparse-3.1.0.tar.gz` → `yanked=True` |

      The decisive signal is that **`info.version` dropped from `3.1.0` to
      `0.3.0`** — resolution actually moved, rather than the flag merely being
      set. Once `0.4.0` publishes it becomes latest, since `0.4.0 > 0.3.0`.

      (An earlier check, before the yank was submitted, showed `yanked=False` on
      both endpoints. Worth remembering that the flag is what matters, not the
      intent to set it.) Re-check any time with:

      ```bash
      curl -s https://pypi.org/pypi/lightningparse/json \
        | python -c "import json,sys; d=json.load(sys.stdin); \
          print('latest:', d['info']['version']); \
          print('3.1.0 yanked:', any(f.get('yanked') for f in d['releases']['3.1.0']))"
      ```

- [ ] **Use an unpinned install to verify the release.** `ASCII_PHASES.md`
      Phase 6 checks with `pip install lightningparse==0.4.0`, which *pins* the
      version and therefore passes even in the broken state. A pinned check
      cannot detect this class of problem. Run a plain
      `pip install lightningparse` in a clean environment and assert the
      resolved version is `0.4.0`.

- [ ] **Decide what happens to the `v3.1.0` git tag** (local and remote). It
      currently points at `a792938` "Bump version to 3.1.0". Because `3.1.0`
      exists permanently on PyPI even after yanking, there is an argument for
      keeping the tag so the published artifact stays traceable to its source
      commit. Deleting it is also defensible. Unresolved at time of writing.
