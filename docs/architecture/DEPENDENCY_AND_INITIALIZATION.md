# Dependency lifecycle and initialization

| Field | Value |
| --- | --- |
| Interface | `DependencyLifecycle@1` |
| Task | `IPFSDOC-012` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `ipfs_datasets_py/__init__.py`; `router_deps.py`; `auto_installer.py`; `dependency_catalog.py`; `lazy_dependencies.py`; `logic/common/feature_detection.py`; `logic/external_provers/lazy_installer.py`; routers (`ipfs_backend_router.py`, `*_router.py`); `pyproject.toml` / `setup.py`; `.gitmodules`; tests under `tests/` |
| Last verified | 2026-08-03 |
| Audience | architect, developer, operator, agent |
| Related | [INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md), [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md), [DOMAIN_MAP.md](DOMAIN_MAP.md), [lazy_theorem_prover_installation.md](../security_verification/lazy_theorem_prover_installation.md) |
| Review cadence | after packaging, router, or lazy-install changes |

## 1. Purpose

This guide answers: **how `ipfs_datasets_py` loads, installs, probes, and
shares optional dependencies without turning package import into a full
platform bootstrap.** It covers hermetic/minimal imports, explicit
`initialize()`, injected `RouterDeps`, auto and lazy installation controls,
capability probing, router selection, and native theorem-prover provisioning.

Cross-repository ownership (submodules, `ipfs_kit_py`, `ipfs_accelerate_py`,
external services) lives in
[INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md). Authority order for
conflicting claims is
[SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md).

## 2. Audience

- **Primary:** developers wiring libraries, MCP hosts, CLIs, or CI so imports
  stay hermetic and optional stacks remain opt-in.
- **Secondary:** operators provisioning provers/binaries; architects and agents
  placing features without inventing competing initialization roots.

## 3. Scope and non-goals

### In scope

- Python **3.12+** runtime assumption (`requires-python = ">=3.12"`).
- Package-root import policy and env flags.
- Process-wide `initialize()` and `RouterDeps`.
- `auto_installer`, `dependency_catalog`, and `lazy_dependencies`.
- Capability probes (`feature_detection`, accelerate status, backend selection).
- Router selection and cache reuse.
- Lazy native theorem-prover install paths and managed installer CLI.
- Offline / unavailable / degradation behavior for **features**.

### Non-goals

- Per-domain algorithm design ([DOMAIN_MAP.md](DOMAIN_MAP.md) and domain leaves).
- Cross-repo ownership tables (this file points to
  [INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md)).
- End-to-end product data flows ([END_TO_END_DATA_FLOW.md](END_TO_END_DATA_FLOW.md)
  when present).
- Changing production code, packaging, or protected plan files as part of this
  documentation task.

## 4. Context

`ipfs_datasets_py` is an IPFS-native data and AI platform package. The full
surface (MCP, FastAPI, transformers/LLM stacks, vector stores, theorem provers,
multimedia converters, kit/accelerate backends) is far larger than a safe
default import. Recent lifecycle work therefore separates:

1. **Hermetic import** — load the package without side-effect heavy stacks.
2. **Explicit initialize** — opt-in process wiring for shared router deps.
3. **Lazy resolution** — install or load a dependency on first real use.
4. **Probe vs capability** — detect presence without claiming production power.
5. **Fail-closed trust** — authorization, proof, and side-effect gates do **not**
   degrade into silent allow when dependencies are missing.

## 5. Ownership and boundaries

| Owns (this lifecycle) | Does not own |
| --- | --- |
| Import-time hermeticity and env flag policy in package root | External IPFS daemon lifecycle |
| `RouterDeps` process container and router injection contracts | Canonical accelerate router implementations (live in `ipfs_accelerate_py`) |
| Declarative Python dependency catalog and auto-install policy | OS package managers as guaranteed services |
| Feature probes that avoid import side effects | Production authorization / admissibility decisions |
| Managed native prover install roots and progress events | Upstream prover release policy and binary ownership |

**Inbound callers:** Python API, CLI, MCP server startup, tests/`conftest.py`,
operator install scripts.

**Outbound dependencies:** pip/OS package managers, git submodule checkouts,
optional `ipfs_kit_py` / `ipfs_accelerate_py`, native prover binaries, network
index servers (unless offline mode is set).

## 6. Components

| Component | Path | Role |
| --- | --- | --- |
| Package root | `ipfs_datasets_py/__init__.py` | Hermetic import policy; default auto-install env; `initialize()` |
| Router deps | `ipfs_datasets_py/router_deps.py` | Injectable `RouterDeps`; process default get/set |
| Auto installer | `ipfs_datasets_py/auto_installer.py` | Cross-platform install of Python/system deps; kit bootstrap |
| Dependency catalog | `ipfs_datasets_py/dependency_catalog.py` | Import name → distribution mapping; component groups |
| Lazy proxy | `ipfs_datasets_py/lazy_dependencies.py` | On-demand module resolution via `ensure_module` |
| Feature detection | `ipfs_datasets_py/logic/common/feature_detection.py` | `find_spec` probes without import |
| IPFS backend router | `ipfs_datasets_py/ipfs_backend_router.py` | Backend selection; kit/accelerate enable flags; Kubo fallback |
| Accelerator router aliases | `llm_router.py`, `embedding_router.py`, `embeddings_router.py`, `multimodal_router.py`, `_router_alias.py` | Re-export canonical routers from `ipfs_accelerate_py` |
| Accelerate integration | `ipfs_datasets_py/ml/accelerate_integration/` (and package `accelerate_integration/`) | Optional accelerate managers; local fallback |
| Prover lazy installer | `ipfs_datasets_py/logic/external_provers/lazy_installer.py` | First-use native solver install |
| Managed prover CLI | `ipfs_datasets_py.logic.integration.bridges.prover_installer` | Console script `ipfs-datasets-install-provers` |
| Packaging | `pyproject.toml`, `setup.py` | Python 3.12+; extras including `theorem-provers`, `lazy` |

```text
import ipfs_datasets_py
        |
        v
  hermetic __init__  ----env flags----> optional stacks (MCP/LLM/...)
        |
        |  initialize(deps=...)
        v
   RouterDeps (process default)
        |
        +--> ipfs_backend_router / other routers
        +--> AccelerateManager (lazy)
        |
  first real feature use
        |
        v
  ensure_module / ensure_prover_executable
        |
        +--> already on PATH / importable  --> use
        +--> auto/lazy install allowed     --> install then probe again
        +--> offline / disabled / fail     --> degrade feature OR raise (strict)
```

## 7. End-to-end initialization flow

### 7.1 Happy path (application process)

1. Process starts with **Python 3.12+**.
2. Caller imports `ipfs_datasets_py` (or a submodule). Package root runs:
   - default enable of `IPFS_DATASETS_AUTO_INSTALL` / `IPFS_KIT_AUTO_INSTALL_DEPS`
     unless already set;
   - minimal-import detection;
   - **no** eager MCP/FastAPI/LLM/finance dashboard imports.
3. Caller optionally builds a `RouterDeps` and calls
   `ipfs_datasets_py.initialize(deps=...)`.
4. Domain code or routers resolve backends through env + `RouterDeps` caches.
5. First feature that needs an optional Python package calls `ensure_module` /
   `LazyDependencyProxy` / a router factory.
6. First theorem-prover **execution** (not import) may call
   `ensure_prover_executable` when lazy install is enabled.
7. Capability probes report availability; trust-sensitive paths still require
   explicit proof/authz evidence (see §12).

### 7.2 Sequence (control)

```text
Caller                Package root           RouterDeps            Installer
  |                        |                     |                     |
  |-- import package ----->|                     |                     |
  |                        |-- set default env   |                     |
  |                        |-- hermetic exports  |                     |
  |-- initialize(deps) --->|                     |                     |
  |                        |-- set_default ----->|                     |
  |-- use router --------->|                     |                     |
  |                        |-- get deps -------->|                     |
  |                        |-- select backend    |                     |
  |-- feature call ------->|                     |                     |
  |                        |-- ensure_module ---------------------->|
  |                        |                     |  install if allowed |
  |                        |<-- module or None ---------------------|
  |-- prover execute ----->|                     |                     |
  |                        |-- ensure_prover ------------------------>|
  |                        |                     |  native root / PATH |
```

### 7.3 Lifecycle rules

| Phase | Expected behavior |
| --- | --- |
| Import | Cheap, hermetic by default; no network; no prover downloads |
| `initialize()` | Opt-in shared deps; optional SyMAI registration |
| First use | May install (if allowed) or return unavailable |
| Shutdown | No mandatory global teardown; managers live in process caches |

## 8. Contracts

### 8.1 Minimal and opt-in imports

Default package import must remain usable in CI, benchmarks, and lightweight
library embeds.

| Flag / mode | Effect |
| --- | --- |
| `IPFS_DATASETS_PY_MINIMAL_IMPORTS=1` | Hermetic path: stub installer (`auto_install=False`); skip heavy optional exports |
| `IPFS_DATASETS_PY_BENCHMARK=1` | Same minimal treatment as above |
| `IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS=1` | Allow MCP-related import-time exports |
| `IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS=1` | Allow FastAPI-related import-time exports |
| `IPFS_DATASETS_PY_ENABLE_FINANCE_DASHBOARD_IMPORTS=1` | Allow finance dashboard import-time exports |
| `IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS=1` | Allow transformers/LLM stack import-time paths |
| `IPFS_DATASETS_PY_WARN_OPTIONAL_IMPORTS=1` | Emit warnings for missing optional deps (default: quiet / debug only) |
| `IPFS_DATASETS_PY_LOG_DEDUP=1` | Deduplicate root logging handlers (benchmark hygiene) |

**Contract:** Missing optional stacks do **not** fail package import. Features
that require them fail or degrade at **use** time with clear unavailability.

### 8.2 Explicit `initialize()` and injected `RouterDeps`

```python
from ipfs_datasets_py import initialize, RouterDeps
from ipfs_datasets_py.router_deps import get_default_router_deps, set_default_router_deps

deps = RouterDeps()  # optional: inject remote_cache, prebuilt managers
initialize(deps=deps, register_symai_engines=False)
```

| Symbol | Role |
| --- | --- |
| `RouterDeps` | Mutable container: `accelerate_managers`, `ipfs_backend`, `router_cache`, optional `remote_cache` |
| `get_default_router_deps()` | Process-global default (created once under lock) |
| `set_default_router_deps(deps)` | Override process default |
| `initialize(deps=..., register_symai_engines=...)` | Install deps if provided; return resolved default; best-effort SyMAI registration when requested |

**Why injection exists:** Python caches modules in `sys.modules`, but higher-level
integrations still re-create clients if every call site constructs its own
manager. Routers accept shared `RouterDeps` so accelerate managers and resolved
backends are reused.

**SyMAI:** `register_symai_engines=True`, or env
`IPFS_DATASETS_PY_USE_SYMAI_ENGINE_ROUTER` truthy, attempts registration unless
minimal imports are on. Failures are swallowed (best-effort feature enablement).

### 8.3 Auto and lazy installation controls

#### Package-level auto-install (Python / system deps)

| Control | Default behavior |
| --- | --- |
| `IPFS_DATASETS_AUTO_INSTALL` | Package root sets `"true"` if unset; installer reads it (also accepts `IPFS_AUTO_INSTALL`) |
| Minimal/benchmark modes | Force `auto_install=False` regardless of the above |
| `IPFS_DATASETS_AUTO_INSTALL_OFFLINE` | Prefer offline / wheelhouse installs when configured |
| `IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE` | Local wheel path for offline pip |
| `IPFS_DATASETS_PROJECT_ROOT`, `IPFS_DATASETS_LOCAL_BIN`, `IPFS_DATASETS_LOCAL_DEPS`, `IPFS_DATASETS_NPM_PREFIX` | Layout for local bins and deps |
| `IPFS_DATASETS_ENSURE_INSTALLER` | When truthy, may re-check repo installer currency |
| `IPFS_DATASETS_PIP_TIMEOUT`, `IPFS_DATASETS_INSTALL_LOCK_TIMEOUT`, `IPFS_DATASETS_INSTALL_RETRY_SECONDS` | Installer timing |

`dependency_catalog.DependencySpec` maps **import names** (e.g. `fitz`) to
**distributions** (e.g. `pymupdf`) and component tags (`core`, `vectors`,
`theorem` bindings, …). Packaging extras remain the reviewed environment
creation path; the catalog lets runtime features request the same packages
without guessing distribution names.

`lazy_dependencies.LazyDependencyProxy` resolves modules on first attribute
access via `ensure_module(..., required=False)` and never imports third parties
at proxy construction time.

#### Theorem-prover lazy install (native + bindings)

| Control | Effect |
| --- | --- |
| `IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=1` | Enable first-use native installer for requested provers |
| `IPFS_DATASETS_PY_LAZY_INSTALL_<PROVER>=0/1` | Per-prover override |
| `IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS` / `ALL_PROVERS` / portfolios | Managed preflight install paths |
| `IPFS_DATASETS_PY_LAZY_INSTALL_STRICT` / `IPFS_DATASETS_PY_PROVER_INSTALL_STRICT` | Raise on installer failure |
| `IPFS_DATASETS_PY_ALLOW_SUDO_FOR_PROVERS=1` | Permit interactive sudo (default: never) |
| `IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT` | User-local solver root (default under `~/.local/share/ipfs_datasets_py/theorem-provers`) |
| `IPFS_DATASETS_PY_<PROVER>_EXECUTABLE` | Explicit binary or portable launcher |
| `IPFS_DATASETS_PY_<SOLVER>_INSTALL_COMMAND` | Org-managed custom install |

**Import of** `logic.external_provers` **never downloads a solver.** Installation
is tied to execution or an explicit managed CLI invocation.

Python bindings for provers come from the optional extra:

```bash
pip install -e '.[theorem-provers]'
# or managed native portfolio:
ipfs-datasets-install-provers --portfolio legal_ir_generation --yes --strict
```

### 8.4 Capability probing

| Probe API | Behavior | Authority of result |
| --- | --- | --- |
| `feature_detection.is_module_available(name)` | `importlib.util.find_spec` only; respects minimal imports | Presence / importability, **not** production capability |
| `feature_detection.require_module` | Raises `ImportError` with extra hint | Hard requirement at call site |
| `feature_detection.import_optional_module` | Best-effort import or default | Optional feature enablement |
| `is_accelerate_available()` | Env gate (`IPFS_ACCELERATE_ENABLED`); local fallback when backend missing | Integration enabled/disabled |
| `get_accelerate_status()` | Structured availability, env, import error | Diagnostics |
| Prover `ensure_prover_executable` phases | checking / available / installing / blocked / failed | Environment evidence only |
| Empty submodule directories | Path exists but content absent | **Not** capability evidence |

**Invariant:** Discovery ≠ capability; a green probe is not authorization, proof,
or a guarantee that offline/production policy is satisfied.

### 8.5 Router selection

Routers choose backends without hard-wiring optional stacks into package import.

#### IPFS backend router (`ipfs_backend_router.py`)

| Control | Role |
| --- | --- |
| `IPFS_DATASETS_PY_IPFS_BACKEND` | Force registered backend name |
| `IPFS_DATASETS_PY_ENABLE_IPFS_KIT` | Best-effort `ipfs_kit_py` backend |
| `IPFS_DATASETS_PY_ENABLE_IPFS_ACCELERATE` | Best-effort accelerate IPFS path |
| `IPFS_DATASETS_PY_ENABLE_IPFS_HTTPAPI` / `IPFS_HOST` | HTTP API path |
| `IPFS_DATASETS_PY_KUBO_CMD` | Local Kubo CLI (default `ipfs`) |
| `IPFS_DATASETS_PY_ROUTER_CACHE` | Cache resolved backends (`0` disables) |
| `IPFS_DATASETS_AUTO_INSTALL_IPFS_KIT` | Kit bootstrap on demand (falls back to general auto-install) |
| `IPFS_KIT_DISABLE` | Hard-disable kit bootstrap |

Selection order is configuration-driven: explicit override → enabled optional
providers → local Kubo CLI fallback. Kit bootstrap may set
`IPFS_DATASETS_PY_ENABLE_IPFS_KIT=1` after a successful auto-install.

#### Accelerator-owned routers (compat aliases in this package)

| Datasets path | Canonical owner |
| --- | --- |
| `ipfs_datasets_py.llm_router` | `ipfs_accelerate_py.llm_router` |
| `ipfs_datasets_py.embedding_router` / `embeddings_router` | `ipfs_accelerate_py.embeddings_router` |
| `ipfs_datasets_py.multimodal_router` | `ipfs_accelerate_py.multimodal_router` |

Aliases use `_router_alias.load_accelerator_router`, which prefers the installed
package and can locate a sibling source checkout. **Implementation and mutable
router state live in accelerate**, not in datasets.

#### Shared accelerate managers via `RouterDeps`

`RouterDeps.get_accelerate_manager(purpose=...)` lazily constructs
`AccelerateManager` when accelerate integration is available; returns `None`
when disabled or unavailable (graceful feature path).

### 8.6 Native theorem-prover provisioning

Layers:

1. **Python extra `theorem-provers`** — bindings (`z3-solver`, `cvc5`, `pysmt`,
   `symbolicai`, …). Does **not** install native CLIs during `pip install`.
2. **Managed CLI** `ipfs-datasets-install-provers` — reviewed portfolios and
   pinned artifacts (see security guide).
3. **Runtime lazy installer** — first model check / SMT / proof-kernel path may
   install into the user-local root with visible `ProverInstallEvent` progress.
4. **Operator overrides** — explicit executables or install commands for
   unsupported platforms.

| Portfolio example | Contents (summary) |
| --- | --- |
| `legal_ir_generation` | Z3, cvc5, Lean, Vampire, E, ErgoAI |
| `legal_ir_specialists` | Apalache, Maude, Tamarin, ProVerif |
| `reconstruction` | Rocq/Coq, Isabelle |
| `legal_ir_full` | Union + SymbolicAI |

**Installing or finding a solver is environment evidence only.** Proof results
still require reviewed models, pinned inputs, successful solver output, and
policy-level independent evidence.

### 8.7 Offline and unavailable behavior

| Situation | Feature behavior | Trust boundary behavior |
| --- | --- | --- |
| Offline network + auto-install on | Use wheelhouse if configured; otherwise install fails and feature degrades or raises (strict) | Authz/proof gates remain fail-closed |
| Minimal/benchmark import mode | Installer disabled; probes report unavailable | No silent production claims |
| Missing optional extra | Domain feature returns stub/error/unavailable status | Must not imply verified capability |
| Empty git submodule | Integration wrappers report missing; feature off | Same |
| Missing prover binary + lazy install off | Install phase `disabled` / `blocked`; run skips or errors | Never treat as proven |
| Missing prover + lazy install on + fail | Phase `failed`; optional strict exception | Same |
| Accelerate disabled (`IPFS_ACCELERATE_ENABLED=0`) | Local fallback / no distributed manager | Does not authorize remote side effects |
| Remote cache miss/error in `RouterDeps` | Local cache only; remote write-through best-effort | Cache is not a trust root |

**Offline guidance for operators:**

```bash
export IPFS_DATASETS_PY_MINIMAL_IMPORTS=1          # hermetic CI
export IPFS_DATASETS_AUTO_INSTALL=0               # no runtime pip
export IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS=0    # no native downloads
# or offline auto-install:
export IPFS_DATASETS_AUTO_INSTALL_OFFLINE=1
export IPFS_DATASETS_AUTO_INSTALL_WHEELHOUSE=/path/to/wheels
```

## 9. Graceful feature degradation vs fail-closed trust

These are **different policies**. Confusing them causes unsafe documentation and
unsafe runtime assumptions.

### 9.1 Graceful feature degradation (availability)

Applies to optional compute, media, kit/accelerate backends, scrapers, and
best-effort helpers.

| Allowed | Examples |
| --- | --- |
| Soft-disable a feature | No accelerate → local inference path |
| Return empty / stub data for non-authoritative APIs | Fallback dataset list when core deps missing |
| Best-effort cache / remote write-through failures | `RouterDeps.set_cached_and_remote` swallows remote errors |
| Quiet optional import notices | Default without `WARN_OPTIONAL_IMPORTS` |
| Skip a prover route and try another portfolio member | Hammer/router selection among available solvers |

### 9.2 Fail-closed trust boundaries (authority)

Applies to authorization, admissibility, proof attestation, identity integrity,
and side-effect dispatch.

| Required | Examples |
| --- | --- |
| Missing proof ≠ success | Simulated ZKP never production-authoritative |
| Missing validator ≠ allow | Profile G / admissibility default deny or abstain |
| Probe success ≠ grant | Capability install does not issue UCAN/dispatch rights |
| Unknown extension / digest mismatch | Reject / abstain, do not soften |
| Installer blocked | Do not invent proof from absence |

**Rule of thumb:** degrade **features**; fail closed on **trust**.

## 10. Invariants

1. **Python 3.12+** is the supported language floor for packaging and runtime.
2. Package import stays hermetic unless opt-in flags enable heavy stacks.
3. `initialize()` is the explicit process wiring point; import is not.
4. Routers share clients through injected or default `RouterDeps`.
5. Auto-install and lazy prover install are controlled by env and mode flags;
   minimal/benchmark modes disable auto-install.
6. Capability probes never install by themselves; first-use installers may.
7. Empty submodules and missing extras are availability issues, not domain
   absence.
8. Discovery is not capability; capability is not authorization; proof is not
   authorization.

## 11. Extension points

| Need | Extension |
| --- | --- |
| New lazy Python dep | Add `DependencySpec` in `dependency_catalog.py`; wire `ensure_module` call site |
| New router backend | Register in the owning router; accept `RouterDeps`; avoid import-time kit/accelerate |
| New prover | Extend lazy installer aliases/env map; document managed portfolio; pin checksums in installer |
| App-specific shared clients | Construct `RouterDeps`, inject managers/cache, call `initialize(deps=...)` |
| CI hermeticity | Set minimal imports + disable auto/lazy install |

## 12. Failure modes (summary)

| Mode | Symptom | Recovery |
| --- | --- | --- |
| Heavy import in CI | Timeouts / missing extras | Minimal imports; disable auto-install |
| Unexpected pip at runtime | Network/policy violations | `IPFS_DATASETS_AUTO_INSTALL=0` |
| Prover silent hang fear | Long first-use download | Managed preflight CLI; progress events |
| Duplicate accelerate clients | Memory / re-init cost | Shared `RouterDeps` via `initialize` |
| Docs claim “full capability” from probe | False production readiness | Apply §9.2 and SOURCE_AUTHORITY |

## 13. Related documents

| Document | Role |
| --- | --- |
| [INTEGRATION_BOUNDARIES.md](INTEGRATION_BOUNDARIES.md) | Ten submodules; kit/accelerate ownership; external services |
| [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) | Product surfaces and system actors |
| [DOMAIN_MAP.md](DOMAIN_MAP.md) | Domain ownership |
| [lazy_theorem_prover_installation.md](../security_verification/lazy_theorem_prover_installation.md) | Operator-facing prover install detail |
| Planned install guides under `docs/guides/installation/` | Capability extras and configuration reference |

## 14. Validation

Re-check this guide when package root flags, installer env contracts, router
selection, prover portfolios, or Python version requirements change.

Focused gate for this task:

```bash
test -s docs/architecture/DEPENDENCY_AND_INITIALIZATION.md \
  && test -s docs/architecture/INTEGRATION_BOUNDARIES.md \
  && rg -n 'Python 3.12|initialize|lazy|ipfs_kit|ipfs_accelerate|submodule' \
       docs/architecture/DEPENDENCY_AND_INITIALIZATION.md \
       docs/architecture/INTEGRATION_BOUNDARIES.md
```

Evidence for this revision: package `__init__.py` import/init policy;
`router_deps.py`; `auto_installer.py` / `dependency_catalog.py` /
`lazy_dependencies.py`; `feature_detection.py`; `ipfs_backend_router.py`;
accelerator alias modules; `logic/external_provers/lazy_installer.py`;
`pyproject.toml` (`requires-python >= 3.12`, extras, `ipfs-datasets-install-provers`);
`.gitmodules` (ten entries); sibling system/domain architecture pages.
