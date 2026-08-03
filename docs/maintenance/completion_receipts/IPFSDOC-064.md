# Completion receipt — IPFSDOC-064

| Field | Value |
| --- | --- |
| Task | `IPFSDOC-064` |
| Title | Refresh the capability matrix and changelog policy |
| Interface | `CapabilityStatusMatrix@1`, `ChangelogPolicy@1` |
| Track | user-docs |
| Stage | implementation |
| Attempt | 1 |
| Completed at (UTC) | `2026-08-03T08:17:16Z` |
| Worktree HEAD (base merge at start) | `37f99e8a2c6dff4ba58ebc9ac26507bb8b9ee60f` |
| Tree id (task envelope) | `37f99e8a2c6dff4ba58ebc9ac26507bb8b9ee60f` |
| Package version (cited) | `0.2.0` |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-064-f1813575ff10` (empty at start; no prior valid checkpoint reused) |

## Acceptance restated

Replace undated marketing/count claims with a source-grounded capability matrix
that labels stable / optional / experimental / compatibility / deprecated /
unavailable states and covers current major domains. Turn CHANGELOG into a
project release/change policy and truthful retained history rather than a
worker/stub completion report; do not fabricate releases. Record the validated
current tree, command, and result in this receipt.

## Declared outputs

| Path | Role | Size (bytes, post-write) |
| --- | --- | --- |
| `docs/FEATURES.md` | Capability status matrix | 17210 |
| `docs/CHANGELOG.md` | Release/change policy + retained history | 8143 |
| `docs/maintenance/completion_receipts/IPFSDOC-064.md` | This receipt | (this file) |

## Evidence used (read-only)

| Source | Use |
| --- | --- |
| `pyproject.toml` extras, scripts, version, requires-python | Install surface and version truth |
| `setup.py` console_scripts (superset) | Compatibility CLI names |
| `ipfs_datasets_py/` domain layout; `logic/{intent_ir,proof_corpus,profile_g,admissibility}`; `wallet/` | Domain presence |
| `.gitmodules` / `git submodule status` (all `-`) | Unavailable nested backends |
| MCP `tools/*_tools` inventory (47 categories; ~394 tool `.py` files) | Tool-count honesty method |
| `docs/architecture/{SYSTEM_CONTEXT,DOMAIN_MAP,DEPENDENCY_AND_INITIALIZATION}.md` | Surface and lifecycle vocabulary |
| `docs/architecture/logic/{IR_FAMILY_AND_IDENTITY,EXTERNAL_PROVERS}.md` | Intent IR / provers |
| `docs/architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md` | Unavailable vs trust |
| `docs/maintenance/{SOURCE_AUTHORITY,DRIFT_AND_CLAIM_MATRIX,COVERAGE_MATRIX,CURRENT_STATE_BASELINE}.md` | Authority and claim repair targets |
| Prior `docs/FEATURES.md` / `docs/CHANGELOG.md` | Replaced marketing / worker logs |

Protected plan files under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH*` were **not** modified.

## What changed

### `docs/FEATURES.md`

- Removed undated marketing claims (hard “200+ tools / 50+ categories” as KPI,
  “4,400+ test functions”, universal acceleration/format counts as evergreen).
- Added status vocabulary: **Stable**, **Optional**, **Experimental**,
  **Compatibility**, **Deprecated**, **Unavailable**, plus **Current** snapshot
  qualifier.
- Matrix covers product surfaces, all pyproject extras (including **lazy**),
  processing, logic (**Intent IR**, **proof corpus**, provers, CEC gates),
  knowledge/retrieval, storage/network, **wallet**, **Profile G**, MCP
  inventory method, and lifecycle/lazy deps.
- Explicit non-claims and links to architecture authority.

### `docs/CHANGELOG.md`

- Replaced Worker 177 stub-completion narrative as product changelog authority.
- Added normative release/change policy: when a SemVer entry may be added,
  unreleased rules, forbidden content, deprecation/lazy/trust notes.
- Recorded **current package version 0.2.0** without fabricating a dated
  product release section for it.
- Retained 2025-07-04 worker sessions as **historical non-release** notes only.
- Documented unreleased docs honesty work for IPFSDOC-064.

## Validated current tree

```text
HEAD: 37f99e8a2c6dff4ba58ebc9ac26507bb8b9ee60f
Subject: Merge branch 'implementation/ipfsdoc-061-700ca429abef-attempt-1-1785744605' into agent/ipfs-datasets-documentation-refresh-20260803
Committer date: 2026-08-03 08:14:44 +0000
Package: ipfs_datasets_py 0.2.0, requires-python >=3.12
```

Commands used for identity:

```bash
git rev-parse HEAD
git log -1 --format='%H %ci %s'
```

## Validation command and result

**Command** (task contract):

```bash
test -s docs/FEATURES.md && test -s docs/CHANGELOG.md && test -s docs/maintenance/completion_receipts/IPFSDOC-064.md && rg -n 'Intent IR|proof corpus|Profile G|wallet|lazy|Current|Experimental|Optional' docs/FEATURES.md docs/CHANGELOG.md
```

**Result:** exit code **0** (all three paths non-empty; pattern matches present in both FEATURES and CHANGELOG for required tokens including Intent IR, proof corpus, Profile G, wallet, lazy, Current, Experimental, Optional).

Representative matches (non-exhaustive):

| Token | Present in |
| --- | --- |
| Intent IR | FEATURES §3.2; CHANGELOG policy / unreleased |
| proof corpus | FEATURES §3.2 / non-claims; CHANGELOG §1.5 / unreleased |
| Profile G | FEATURES surfaces + §3.5; CHANGELOG |
| wallet | FEATURES §3.5; CHANGELOG |
| lazy | FEATURES extras + lifecycle; CHANGELOG §1.6 |
| Current | FEATURES vocabulary; CHANGELOG §2 heading |
| Experimental | FEATURES status table + domain rows; CHANGELOG policy |
| Optional | FEATURES status table + most optional rows; CHANGELOG policy |

## Discrepancies / deferred gates

| Item | Disposition |
| --- | --- |
| No tagged product SemVer release notes for `0.2.0` in history | Policy records declared version only; no fabricated `[0.2.0]` ship section |
| Registered MCP tool census not run | FEATURES uses filesystem inventory method; full registry count needs provisioned runtime |
| Submodules empty in this worktree | Documented as **Unavailable** until init—not product absence |
| setup.py vs pyproject script drift | Documented as **Compatibility**; packaging fix out of scope |
| Architecture leaves still evolving | FEATURES points to DOMAIN_MAP / logic leaves; does not re-own deep contracts |

## Out of scope (not edited)

- Production code under `ipfs_datasets_py/`
- Protected planning files (`IPFS_DATASETS_DOCUMENTATION_REFRESH_*`)
- Install/user guide rewrites owned by other tasks (IPFSDOC-091+)
- README badge repair

## Sign-off

| Check | Status |
| --- | --- |
| All expected outputs present and non-empty | **pass** |
| Capability matrix uses required status labels and major domains | **pass** |
| Changelog is policy + truthful history; no fabricated releases | **pass** |
| Validation command recorded with result | **pass** |
| Protected paths untouched | **pass** |
