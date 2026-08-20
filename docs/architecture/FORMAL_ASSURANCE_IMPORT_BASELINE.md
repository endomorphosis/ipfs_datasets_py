# Formal assurance import baseline (Datasets cold-import)

| Field | Value |
| --- | --- |
| Interface | `DatasetsImportPurityBaseline@1` |
| Task | `FACP-021` |
| Goal | `FACP-G210` |
| Evidence | `facp/datasets-import-purity@1` |
| Bundle | `facp/migration/datasets-import` |
| Status | characterization (legacy impurity; **not** production-success) |
| Owner | datasets-migration |
| Source of truth | `ipfs_datasets_py/__init__.py`; `ipfs_datasets_py/auto_installer.py`; FACP-003 `datasets_claims.json` import_effect_traces; `tests/unit/test_formal_assurance_import_purity.py` |
| Last verified | 2026-08-19 |
| Audience | architect, developer, agent |
| Related | [DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md); FACP-022 explicit initialization; Formal Claim Algebra v1 `import_effect` family |
| Review cadence | after any package-root or auto_installer import-path change |

> **Lifecycle:** This document records **observed legacy cold-import effects**.
> Observations are discovery of impurity only. They must **not** be promoted to
> production-success, hermetic purity, `effect_successful`, or
> `production_supported` (FCA `import_effect` family: `unsafe_promotion: false`).
> Repair belongs to FACP-022; this baseline does not change package import.

## 1. Purpose

Answer: **what exact ambient effects does a cold `import ipfs_datasets_py`
(and installer helpers reachable after import) perform today**, when run from
empty explicit HOME / XDG / project-root equivalents with network, subprocess,
and out-of-sandbox writes denied?

The purity oracle in `tests/unit/test_formal_assurance_import_purity.py`
**fails on every seeded import effect**. A failing purity verdict is the
expected characterization outcome before FACP-022, not a green hermetic claim.

## 2. Audience

- **Primary:** migration agents implementing FACP-022 and reviewers of day-90
  import hermeticity.
- **Secondary:** operators who must not treat current import as an installer
  bootstrap contract.

## 3. Scope and non-goals

### In scope

- FACP-003 seeds `DS-IMPORT-001` … `DS-IMPORT-005`.
- Top-level call graph from package import into `auto_installer`.
- Environment / PATH mutation, installer construction, network/subprocess
  reachability, persistent user PATH helpers, runtime installer state writes.
- Wall-time and memory bounds recorded by the sandboxed probes.
- FCA conservative mapping for family `import_effect`.

### Non-goals

- Changing package import or installer behavior (prohibited in FACP-021).
- Treating probe observation as formal proof or production qualification.
- Resolving MIT/AGPL rights conflict (FACP-003 / human legal review).
- Migrating false-success download/upload outcomes (FACP-023).

## 4. Sandbox contract

Every probe:

1. Creates empty `HOME`, `USERPROFILE`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`,
   `XDG_DATA_HOME`, `XDG_STATE_HOME`, `TMPDIR`, and
   `IPFS_DATASETS_PROJECT_ROOT` / local bin+deps directories under a private
   temporary tree.
2. Clears ambient `IPFS_DATASETS_AUTO_INSTALL`, `IPFS_KIT_AUTO_INSTALL_DEPS`,
   `IPFS_DATASETS_ENSURE_INSTALLER`, and minimal-import flags unless the seed
   explicitly sets them.
3. Denies `socket` connect / `getaddrinfo`, all `subprocess` entry points, and
   `Path.mkdir` / `Path.write_text` / `os.makedirs` outside the sandbox.
4. Records denied attempts as exact observed effects (the impurity), without
   performing host network I/O or durable host writes.
5. Emits a structured observation whose disposition is
   `legacy_impurity_observed` with `normalized_as_success: false`.

## 5. Seeded import effects (exact legacy behavior)

Authority for seed identity is FACP-003
`implementation_plan/formal_assurance_control_plane/baseline/datasets_claims.json`
(`import_effect_traces`). Corpus cross-reference: FACP-008 defect corpus
entries `cx-ds-import-*`.

| Defect | Seed | Family | Reachability | Exact observed legacy behavior (characterization) | Purity verdict |
| --- | --- | --- | --- | --- | --- |
| `DS-IMPORT-001` | `cx-ds-import-auto-install-default-on` | `module_top_level_environment_write` | package import default | Cold import with auto-install env **unset** executes `_enable_default_auto_install()` and sets `IPFS_DATASETS_AUTO_INSTALL=true` and `IPFS_KIT_AUTO_INSTALL_DEPS=1`. | **FAIL** |
| `DS-IMPORT-002` | `cx-ds-import-installer-path-mkdir` | `installer_construction_path_and_fs_mutation` | non-minimal package import | Non-minimal import calls `get_installer()` → `DependencyInstaller.__init__` which `mkdir`s project `bin` / `.deps` / npm prefix dirs and rewrites process `PATH` via `_ensure_bin_on_path`. | **FAIL** |
| `DS-IMPORT-003` | `cx-ds-import-pip-reachability` | `installer_reachability_pip_subprocess` | reachable after import when auto-install enabled | After import defaults enable auto-install, `DependencyInstaller._pip_install` / `ensure_module` attempts `sys.executable -m pip install …` via `subprocess.run`. Under denial the attempt is recorded; missing optional modules do **not** yield typed Unavailable in this legacy path. | **FAIL** |
| `DS-IMPORT-004` | `cx-ds-import-persistent-path` | `persistent_user_path_write` | windows installer helper paths (also attempted on non-Windows via `setx` fallback) | `_add_to_user_path` attempts `winreg` user Environment mutation and/or `subprocess.run(['setx', 'PATH', …])`, then may mutate process `PATH`. Durable user PATH mutation is library-reachable. | **FAIL** |
| `DS-IMPORT-005` | `cx-ds-import-runtime-installer-state` | `runtime_installer_bootstrap_write` | import when `IPFS_DATASETS_ENSURE_INSTALLER` truthy or `force=True` | `ensure_repo_installer_current` may run companion bootstrap helpers (git/pip subprocess) and `_save_runtime_installer_state` writing `state/runtime_installer_state.json` under the package repo root. | **FAIL** |

### 5.1 Top-level call graph (legacy)

```text
import ipfs_datasets_py
        |
        +--> _enable_default_auto_install()     # DS-IMPORT-001 (always)
        |
        +--> [unless MINIMAL_IMPORTS]
                from .auto_installer import get_installer, ensure_repo_installer_current
                installer = get_installer()
                        |
                        +--> DependencyInstaller.__init__
                                mkdir bin/deps/npm
                                _ensure_bin_on_path()          # DS-IMPORT-002
                        |
                ensure_repo_installer_current()               # DS-IMPORT-005 when gated
                        |
                        +--> companion bootstrap helpers
                        +--> _save_runtime_installer_state

later / helper reachability:
        ensure_module / lazy_import
                --> get_installer().ensure_dependency
                        --> _pip_install (subprocess pip)     # DS-IMPORT-003
        DependencyInstaller._add_to_user_path                 # DS-IMPORT-004
                --> winreg and/or setx PATH
```

## 6. FCA classification (conservative)

For every seed above:

| Field | Value |
| --- | --- |
| Family | `import_effect` |
| Informs | discovery only |
| Forbidden predicates | `effect_successful`, `production_supported` |
| `unsafe_promotion` | `false` |
| Disposition | `reject_illegal_promotion` / `legacy_impurity_observed` |
| Must not claim | hermetic purity, production-supported import, installer success |

Probe observation is **not** formal proof. It is a content-bound characterization
input for FACP-022.

## 7. Time and memory bounds

Probes record `elapsed_ms` (parent wall time) and child/self `maxrss` samples.
Bounds are diagnostic, not SLOs:

| Probe class | Typical wall time (local sandbox) | Notes |
| --- | --- | --- |
| Minimal cold import (`DS-IMPORT-001`) | usually well under 5s | env mutation only |
| Non-minimal cold import (`DS-IMPORT-002`) | usually under 30s | installer mkdir + PATH |
| Pip reachability (`DS-IMPORT-003`) | usually under 30s | denied subprocess recorded |
| Persistent PATH helper (`DS-IMPORT-004`) | usually under 30s | winreg/setx attempt |
| Runtime installer bootstrap (`DS-IMPORT-005`) | usually under 60s | denied companion subprocess + state write attempt |

Exact numbers vary by host; the purity verdict depends on **effect matching**,
not on absolute timing.

## 8. Validation

```bash
python3 -m pytest external/ipfs_datasets/tests/unit/test_formal_assurance_import_purity.py -q
```

Acceptance encoded by the test:

1. Purity **fails** on every seeded import effect.
2. Probes run from empty explicit state/home equivalents without harness
   network/process/out-of-sandbox writes.
3. Exact observed legacy behavior is recorded with
   `normalized_as_success: false`.

## 9. Follow-on

- **FACP-022** — Move installation behind explicit initialization so core
  cold import passes this sandbox (no ambient env/PATH/fs/network/process
  mutation; typed non-success when deps are missing).
- **FACP-023** — Replace false-success download/upload/semantic fallbacks
  (separate from import purity).
