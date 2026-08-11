# Site build and navigation disposition

| Field | Value |
| --- | --- |
| Interface | `SiteBuildAndNavigationDisposition@1` |
| Task | `IPFSDOC-098` |
| Status | `evidence` |
| Owner | release-docs / documentation-governance |
| Source of truth | Root `mkdocs.yml`, `docs/tdfol/conf.py`, `requirements-docs.txt`, this disposition, provisioned build logs |
| Last verified | 2026-08-04 |
| Audience | maintainer, release reviewer, agent, CI owner |
| Depends on | `IPFSDOC-096`, `IPFSDOC-097` |
| Companion | [RELEASE_EVIDENCE.md](RELEASE_EVIDENCE.md), [README.md](README.md) §7, [VALIDATION_RUNBOOK.md](VALIDATION_RUNBOOK.md) |
| Measured at (UTC) | `2026-08-04T00:01:29Z` (strict), `2026-08-04T00:02:37Z` (non-strict) |
| Worktree commit (`HEAD`) | `e2790eb5fa2208d409866559bb9fb24bda62b321` |
| Worktree tree (`HEAD^{tree}`) | `ed2e0c8b267dac24cf72a91cddacefda55c517cc` |
| Supervisor tree_id (packet) | `e2790eb5fa2208d409866559bb9fb24bda62b321` |
| Package | `ipfs_datasets_py` **0.2.0** (`requires-python >=3.12`) |
| Measurement Python | `Python 3.12.3` |
| Checkpoint dir | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` → `…/implementation_checkpoints/ipfsdoc-098-f567e338a4d8` |

## Purpose

Record the **current** MkDocs / Sphinx / navigation configuration gap, the
**exact** provisioned strict-build procedure and measured results, and any
**separately owned** root config / CI follow-up required to make a release-grade
site gate green.

This task **does not** edit production code, root `mkdocs.yml`, Sphinx config,
requirements files, or CI workflows. Those remain owned by root-config / CI
follow-up work outside the IPFSDOC-098 allowed edit set.

**Program root completeness rule (from acceptance and maintenance cadence):**
do **not** mark the documentation program root complete without a **successful
provisioned `mkdocs build --strict`**. This disposition records that the
strict gate **failed** on the current tree; non-strict build **succeeded**.

---

## 1. Configuration inventory (current tree)

### 1.1 MkDocs (product hub site)

| Item | Current value |
| --- | --- |
| Config path | `mkdocs.yml` (repository root) |
| Config SHA-256 | `c46522b886b6e92403904a6291ddf9b2ad0ca0b59f02b097761ad63e24c35119` |
| `site_name` | IPFS Datasets Python |
| `docs_dir` | `docs` |
| `site_dir` | `site` |
| Theme | `mkdocs` (built-in; not Material) |
| Plugins | `search` only |
| `exclude_patterns` | **absent** |
| `markdown_extensions` | **absent** (defaults) |
| `strict` default | CLI flag only (`--strict`); not set in YAML |
| MkDocs in `requirements-docs.txt` | **absent** (file is Sphinx-oriented) |
| MkDocs in `pyproject.toml` extras | **absent** |
| Docs site CI workflow | **none** found under `.github/workflows/` for `mkdocs build` |
| `site/` gitignore | **not** listed in `.gitignore` (generated output currently untracked if present) |

Committed `mkdocs.yml` navigation (7 leaves):

```yaml
nav:
  - Home: index.md
  - Getting Started: getting_started.md
  - Installation: installation.md
  - User Guide: user_guide.md
  - Developer Guide: developer_guide.md
  - API Reference:
      - Optimizers API: api/OPTIMIZERS_API_REFERENCE.md
      - Core Operations API: api/CORE_OPERATIONS_API.md
```

All seven nav targets **exist** on this tree as files under `docs/`.

### 1.2 Sphinx (TDFOL subsystem only)

| Item | Current value |
| --- | --- |
| Config | `docs/tdfol/conf.py` |
| RTD sample | `docs/tdfol/.readthedocs.yaml` |
| Project title in conf | TDFOL - Temporal Deontic First-Order Logic |
| Theme | `sphinx_rtd_theme` |
| Source suffix | `.rst` |
| `requirements-docs.txt` | Sphinx ≥7,<8 + RTD theme + autodoc helpers (not MkDocs) |
| Committed build products | `docs/tdfol/_build/` present (historical/generated) |
| Product-wide Sphinx site | **none** — TDFOL only |

Sphinx is **not** the product documentation site. Product entry and hub
navigation are Markdown under `docs/` with optional MkDocs packaging.

### 1.3 Markdown corpus vs navigated spine

| Metric | Value (this measurement) |
| --- | ---: |
| `docs/**/*.md` files | **1572** |
| MkDocs nav leaves | **7** |
| Pages MkDocs reports “not included in nav” (INFO) | **1560** |
| README/index conflicts excluded by MkDocs | **5** (`README.md` vs `index.md` pairs) |

**Observation:** MkDocs publishes a thin product spine over a very large docs
tree. Most Markdown is reachable from git/hub indexes
([docs/index.md](../index.md), [DOCUMENTATION_INDEX.md](../DOCUMENTATION_INDEX.md))
but is **unnavigated** from `mkdocs.yml`. That is intentional for selective
nav (see [DOCUMENTATION_CONTRIBUTING.md](../developer_guides/DOCUMENTATION_CONTRIBUTING.md))
but collides with a naive whole-tree strict link check when every page under
`docs_dir` is still **built**.

---

## 2. Configuration gap (summary)

| Gap ID | Severity | Gap | Owner (separately owned) | Blocking strict gate? |
| --- | --- | --- | --- | --- |
| GAP-MK-001 | P0 gate | `mkdocs build --strict` aborts with **567** warnings on current tree | root docs config + page owners | **Yes** |
| GAP-MK-002 | P1 | No `exclude_patterns` for archive/historical/plan/stub trees | root `mkdocs.yml` owner | Yes (reduces warning surface) |
| GAP-MK-003 | P1 | Thin nav (7 leaves) while entire `docs/` is still the build set | nav owner + root config | Contributes to noise; not the only cause of warnings |
| GAP-MK-004 | P1 | API nav still points at **generated dumps** (`OPTIMIZERS_API_REFERENCE`, `CORE_OPERATIONS_API`) rather than maintained domain maps under `docs/api/domains/` | nav / api-reference | Product honesty (not only strict build) |
| GAP-MK-005 | P1 | Links from hub pages to repo-root / package-local paths (`../CONTRIBUTING.md`, `../ipfs_datasets_py/...`) are outside `docs_dir` and fail MkDocs resolution | page authors + optional MkDocs plugins (`mkdocs-same-dir` / monorepo patterns) or rewrite links | Yes (spine warnings on `index.md`, `developer_guide.md`, …) |
| GAP-MK-006 | P1 | README vs index conflicts force exclusion of 5 `README.md` files | directory layout / MkDocs policy | Warning-level under strict |
| GAP-MK-007 | P2 | MkDocs not declared in `requirements-docs.txt` or a docs extra | packaging / docs tooling | Provisioning friction |
| GAP-MK-008 | P2 | No CI job runs provisioned `mkdocs build --strict` | CI owner | Regression risk |
| GAP-MK-009 | P2 | `site/` not gitignored | root hygiene | Accidental commit risk |
| GAP-SP-001 | P3 | Sphinx/TDFOL stack separate from MkDocs; dual toolchains | domain + docs tooling | No for product hub strict gate |
| GAP-SP-002 | P3 | Committed Sphinx `_build/` is generated authority risk if cited as design | archive-steward / api-reference | Docs honesty, not MkDocs strict |

---

## 3. Exact provisioned strict-build procedure

### 3.1 Preconditions

| Requirement | Disposition on this worker |
| --- | --- |
| Python 3.12+ | **available** (`Python 3.12.3`) |
| Repository root as CWD | **yes** |
| Network for `pip install mkdocs` | **used once** to provision an isolated venv (PEP 668 blocks system pip) |
| Editable package install | **not required** for MkDocs HTML generation |
| Root `mkdocs.yml` unchanged | **yes** (read-only for this task) |

### 3.2 Commands (reproducible)

```bash
# Identity (bind evidence to tree)
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'

# Isolated provision (do not use system site-packages on PEP 668 hosts)
export CKPT="${IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR:?set checkpoint dir}"
python3 -m venv "$CKPT/mkdocs-venv"
"$CKPT/mkdocs-venv/bin/pip" install -U pip
"$CKPT/mkdocs-venv/bin/pip" install 'mkdocs>=1.5,<2'
export PATH="$CKPT/mkdocs-venv/bin:$PATH"
mkdocs --version   # measured: mkdocs, version 1.6.1

# Gate required for program-root completeness
mkdocs build --strict
echo "exit=$?"

# Optional diagnostic (not a release pass criterion)
mkdocs build
echo "exit=$?"
```

Checkpoint build logs (this run):

| Log | Path under checkpoint |
| --- | --- |
| Strict | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR/build_logs/mkdocs_strict.log` |
| Non-strict | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR/build_logs/mkdocs_nonstrict.log` |

### 3.3 What “strict” means here

MkDocs `--strict` treats **warnings as fatal**. On this tree, warnings are
dominated by:

1. **Broken / out-of-docs_dir links** (`WARNING - Doc file '…' contains a link … target is not found among documentation files`) — **562** of 567 warnings.
2. **README/index exclusions** — **5** warnings.

Unnavigated pages are reported as **INFO** (not counted toward the 567 strict
abort) but still participate in the build and link check.

---

## 4. Measured results (this tree)

### 4.1 Strict build (release gate)

| Field | Value |
| --- | --- |
| **Command** | `mkdocs build --strict` |
| **Started (UTC)** | `2026-08-04T00:01:29Z` |
| **MkDocs** | `1.6.1` |
| **Commit** | `e2790eb5fa2208d409866559bb9fb24bda62b321` |
| **Tree** | `ed2e0c8b267dac24cf72a91cddacefda55c517cc` |
| **Result** | **FAIL** — aborted |
| **Terminal message** | `Aborted with 567 warnings in strict mode!` |
| **Process disposition** | Non-zero exit; site output not accepted as release success |
| **Warning total** | **567** |
| **Warning buckets** | excluding conflicts: **5**; link-target missing under docs_dir: **562** |
| **Unique docs with WARNING lines** | **144** |
| **Top warning roots** | `logic/` (34), `archive/` (27), `guides/` (11), `knowledge_graphs/` (11), `optimizers/` (10), … |
| **Spine (`index.md`) sample causes** | `README.md` conflict targets; `../CONTRIBUTING.md`; `../ipfs_datasets_py/*/README.md` package-local links |

**Strict gate status for program root:** **not passed**.

### 4.2 Non-strict build (diagnostic only)

| Field | Value |
| --- | --- |
| **Command** | `mkdocs build` |
| **Started (UTC)** | `2026-08-04T00:02:37Z` |
| **Result** | **PASS** (exit `0`) |
| **Duration** | `13.66` seconds (`Documentation built in 13.66 seconds`) |
| **site/ files** | **1952** |
| **site/ size** | **149M** (ephemeral; removed after measurement to avoid untracked bulk) |
| **Spine HTML present** | `site/index.html`, `getting_started/`, `installation/`, `user_guide/`, `developer_guide/` confirmed |

Non-strict success proves the theme/plugins/nav graph can render; it does
**not** satisfy the provisioned **strict** release criterion.

### 4.3 Sphinx (not executed this run)

Sphinx/TDFOL was **not** re-provisioned or rebuilt in this task:

| Reason | Note |
| --- | --- |
| Product site gate is MkDocs | Program completeness cites MkDocs strict for the hub |
| `requirements-docs.txt` is Sphinx-only | Separate domain gate when TDFOL RST changes |
| `_build/` already committed | Treated as generated/historical per API generation policy |

Follow-up owners may run `sphinx-build` from `docs/tdfol` when that corpus
changes; record a new evidence row if required for a TDFOL-specific release.

---

## 5. Separately owned root config / CI follow-up

These items are **out of edit scope** for IPFSDOC-098. They must be owned and
landed before the documentation program root may claim complete.

| Follow-up ID | Owner lane | Change (proposal only) | Intent |
| --- | --- | --- | --- |
| FU-001 | root docs config | Add MkDocs to a declared install surface (`requirements-docs.txt` and/or `pyproject` docs extra) | Reproducible provision without ad-hoc venv discovery |
| FU-002 | root docs config | Add `exclude_patterns` for archive, historical plans, completion dumps, stubs, committed Sphinx `_build`, and other non-product trees | Shrink strict warning surface to maintained pages |
| FU-003 | nav / api-reference | Expand or retarget `nav` to maintained hubs (architecture, api domains, tutorials, operations) and stop promoting generated dumps as primary API | Align site graph with [docs/index.md](../index.md) |
| FU-004 | page owners + config | Resolve out-of-`docs_dir` links (repo root `CONTRIBUTING.md`, package-local READMEs) via in-docs copies, absolute project URL policy, or a supported plugin | Clear spine strict warnings |
| FU-005 | layout | Decide README/index dual-file policy (rename, exclude, or merge) for the five conflict pairs | Remove exclusion warnings |
| FU-006 | CI | Add workflow job: provision MkDocs → `mkdocs build --strict` on PRs touching `docs/` or `mkdocs.yml` | Prevent regression |
| FU-007 | hygiene | Add `/site` to `.gitignore`; never commit generated site HTML | Artifact policy |
| FU-008 | Sphinx domain | Keep TDFOL Sphinx as optional domain gate; do not conflate with product MkDocs | Toolchain clarity |

**Explicit non-actions of IPFSDOC-098**

- Did not modify `mkdocs.yml`, `docs/tdfol/conf.py`, `requirements-docs.txt`, CI YAML, or product code.
- Did not expand offline `check_docs.py` allowlists to hide findings.
- Did not delete or rewrite historical docs to force a green strict build.
- Did not mark program root complete.

---

## 6. Relationship to offline quality gates

| Gate | Tool | Role vs site build |
| --- | --- | --- |
| Offline corpus validator | `docs/maintenance/check_docs.py` | Links/anchors/paths/modules/metadata/syntax without network or MkDocs |
| Quality report | [QUALITY_REPORT.md](QUALITY_REPORT.md) | Published full-tree findings (IPFSDOC-096) |
| Example ledger | [EXAMPLE_VERIFICATION.md](EXAMPLE_VERIFICATION.md) | Executable tutorial evidence |
| Maintenance cadence | [README.md](README.md) | Release checklist; site build is provisioned optional until green |
| **This disposition** | MkDocs provisioned strict | Site packaging gate; currently **failed** |

Offline validator success (or disclosed quality report) **does not** substitute
for `mkdocs build --strict`. Conversely, a green MkDocs build would not
substitute for claim-level honesty on install/API surfaces.

---

## 7. Acceptance mapping (IPFSDOC-098 site portion)

| Acceptance element | Where satisfied |
| --- | --- |
| Current MkDocs/Sphinx/navigation configuration gap | §§1–2 |
| Exact provisioned strict-build procedure | §3 |
| Result | §4.1 **FAIL** (567 warnings); §4.2 non-strict **PASS** (diagnostic) |
| Separately owned root config/CI follow-up | §5 |
| Without editing production code | Explicit non-actions; allowed paths only maintenance evidence |
| Do not mark root complete without successful provisioned site build | Root remains **incomplete**; see [RELEASE_EVIDENCE.md](RELEASE_EVIDENCE.md) reviewer disposition |

---

## 8. Document control

| Item | Value |
| --- | --- |
| Produced by | `IPFSDOC-098` |
| Update when | Root `mkdocs.yml` / docs install surface / CI site job changes; after a successful strict build on a new tree |
| Supersedes | Prior baseline note that MkDocs binary availability was not measured ([CURRENT_STATE_BASELINE.md](CURRENT_STATE_BASELINE.md) §9.4 / §11 limitations) for **this** release wave |
| Checkpoint | `$IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR` (venv + `build_logs/`) |
