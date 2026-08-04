# Changelog and change policy — IPFS Datasets Python

| Field | Value |
| --- | --- |
| Interface | `ChangelogPolicy@1` |
| Task | `IPFSDOC-064` |
| Status | `canonical` (release/change policy + retained history) |
| Package version (current tree) | **0.2.0** (`pyproject.toml`, `setup.py`, `ipfs_datasets_py.__version__`) |
| Last verified | 2026-08-03 |
| Authority | Packaging and git history outrank narrative reports ([SOURCE_AUTHORITY.md](maintenance/SOURCE_AUTHORITY.md)) |

## Purpose

This document is the **project release and change policy** plus a **truthful
retained history** of how changes have been recorded. It is **not**:

- a worker or agent stub-completion log;
- a marketing feature list (see [FEATURES.md](FEATURES.md));
- a place to invent SemVer releases that were never tagged or published.

---

## 1. Change policy (normative)

### 1.1 What counts as a release

A **product release** entry may be added only when at least one of the following
is true and cited:

1. Package metadata version was intentionally bumped (`pyproject.toml` /
   `setup.py` / `__version__` agree), **and**
2. A git tag and/or published distribution artifact exists for that version, **or**
3. A maintainer-signed release note is attached to a specific commit SHA.

**Do not fabricate releases.** If work landed under package version `0.2.0`
without a new tag, document it under **Unreleased / retained history**, not as
`[0.3.0]` or `[v2.0.0]`.

Migration milestone labels (for example “migration to v2.0.0 path cleanup”) are
**schedule language**, not package versions, unless packaging is actually
bumped. See drift claim `CLAIM-version-003` in
[DRIFT_AND_CLAIM_MATRIX.md](maintenance/DRIFT_AND_CLAIM_MATRIX.md).

### 1.2 Entry shape (when a real release exists)

Use Keep-a-Changelog-style sections, newest first:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
### Changed
### Deprecated
### Removed
### Fixed
### Security
```

Each bullet should be **user- or integrator-visible**, not internal stub
generation counts. Link PRs/commits when available. Note **Optional** extras
and **Experimental** surfaces by name.

### 1.3 Unreleased work

Track in-progress visible changes under `## [Unreleased]` only when they are
already merged to the default integration branch and are true product deltas.
Documentation-only corrections (capability matrix honesty, claim repair) may be
summarized briefly without inventing a version bump.

### 1.4 What never goes in the product changelog

| Content type | Prefer instead |
| --- | --- |
| Agent/worker session “completed N stubs” | Internal maintenance notes or PR description |
| Undated “200+ tools / 4400+ tests” marketing | [FEATURES.md](FEATURES.md) inventory method + measurement date |
| Phase STATUS / PROJECT_COMPLETE narratives | Historical status under `docs/archive/` or `docs/implementation/` |
| Proof of authorization / Intent IR rollout gates | Logic architecture + ops runbooks |
| Empty-submodule “feature complete” claims | **Unavailable** / **Optional** labels in FEATURES |

### 1.5 Compatibility and deprecation

- **Deprecated** APIs: record removal target only when a schedule is accepted;
  point to migration guides (for example file-converter deprecation schedule).
- **Compatibility** surfaces (setup.py-only scripts, root facades, legacy MCP
  tools): changelog may note dual packaging, but must not claim a single
  install path always exposes every entry point.
- **Intent IR**, **proof corpus**, **Profile G**, and **wallet** changes that
  affect trust boundaries are **Security** or **Changed** with explicit
  fail-closed language—never silent “enabled by default” without config.

### 1.6 Lazy and optional capability changes

When changing **lazy** install, auto-install, or optional extras:

- Document the extra key (`lazy`, `theorem-provers`, `vectors`, …).
- State offline / **Unavailable** behavior.
- Never imply that lazy install grants proof or allow decisions.

---

## 2. Current package version

| Field | Value | Evidence |
| --- | --- | --- |
| Declared version | `0.2.0` | `pyproject.toml` `project.version`; `setup.py`; package `__init__` |
| Python floor | `>=3.12` | `requires-python` / `python_requires` |
| Public capability map | [FEATURES.md](FEATURES.md) | CapabilityStatusMatrix@1 |
| SemVer release ledger | **No dated `[0.2.0]` product release section is retained below** | Historical file content was worker documentation sessions, not a versioned product ship |

Until maintainers publish a proper release note for `0.2.0` (or a later bump),
treat `0.2.0` as the **declared package version** and use the sections below for
policy and retained historical notes only.

---

## 3. [Unreleased]

Documentation and honesty surfaces (no package version bump implied):

### Changed

- **FEATURES.md** rewritten as a source-grounded capability matrix with
  Stable / Optional / Experimental / Compatibility / Deprecated / Unavailable
  labels covering major domains (processing, logic IR including **Intent IR**
  and **proof corpus**, MCP inventory method, **wallet**, **Profile G**, lazy
  deps, submodule gates).
- **CHANGELOG.md** (this file) converted from worker stub-completion report to
  release/change policy and truthful retained history (**ChangelogPolicy@1**).

### Notes

- Product domains such as Intent IR, proof corpus, Profile G, and wallet remain
  governed by architecture ADRs and domain packages; this unreleased docs
  change does not alter runtime trust gates.

---

## 4. Retained historical notes (non-release)

> **Classification:** Historical documentation-worker activity. These entries
> are **not** product SemVer releases. They are retained so earlier references
> to “Worker 177” documentation sessions remain auditable. Do not promote them
> to versioned release headers.

### 2025-07-04 — Documentation worker session (docstrings)

Historical note: core package classes received expanded docstrings following an
internal docstring format guide (`ipfs_datasets.py`, serialization, KNN index,
multiformats, monitoring, web archive utilities). This improved prose coverage
only; it did not constitute a tagged product release.

### 2025-07-04 — Documentation worker session (API stub generation)

Historical note: a documentation pass generated API stubs and docstring
skeletons across multiple modules (lineage, MCP tool modules, vector helpers,
FastAPI surface sketches, embeddings/search helpers, legal deontic parsers).
Metrics such as “stub coverage %” and “200+ API components” were **session
progress estimates**, not product KPIs and not a release.

**Disposition for writers:** Prefer current architecture guides and live code
over these session metrics. If a symbol only exists as a generated stub, label
it accordingly in domain docs—do not list it as Stable production API solely
from this history.

---

## 5. Related versioning documents

| Document | Role |
| --- | --- |
| [FEATURES.md](FEATURES.md) | Current capability matrix (states, not release dates) |
| [DEPRECATION_SCHEDULE.md](DEPRECATION_SCHEDULE.md) | Feature deprecation targets (schedule; verify against code) |
| [COMPLETE_MIGRATION_GUIDE.md](COMPLETE_MIGRATION_GUIDE.md) | Path migration (old vs new); not package SemVer |
| [MIGRATION_CHANGELOG.md](MIGRATION_CHANGELOG.md) | Migration-oriented change list (secondary) |
| Packaging | `pyproject.toml`, `setup.py` — authoritative version numbers |

---

## 6. Maintainer checklist for the next real release

1. Bump and align version in packaging and `__version__`.
2. Tag the release commit; record SHA in the new changelog section.
3. List user-visible Added/Changed/Deprecated/Removed/Fixed/Security only.
4. Cross-check optional extras and console scripts against pyproject/setup.py.
5. Update FEATURES status rows if a capability moves Stable ↔ Optional ↔ Deprecated.
6. Do not paste agent completion receipts into the product changelog; store
   them under `docs/maintenance/completion_receipts/`.

---

*Policy owners: release maintainers and documentation-governance. Last policy
refresh: IPFSDOC-064 (2026-08-03).*
