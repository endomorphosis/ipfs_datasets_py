# Integration and submodule boundaries

| Field | Value |
| --- | --- |
| Interface | `IntegrationBoundaryMap@1` |
| Task | `IPFSDOC-012` |
| Status | `canonical` |
| Owner | architecture |
| Source of truth | `.gitmodules`; `ipfs_datasets_py/logic/submodule_registry.py`; accelerator aliases (`_router_alias.py`, `*_router.py`); `ml/accelerate_integration/`; `ipfs_backend_router.py`; packaging (`pyproject.toml` / `setup.py` dynamic deps); CEC / multimedia / web_archiving wrappers; [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) §7 |
| Last verified | 2026-08-03 |
| Audience | architect, developer, operator, agent |
| Related | [DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md), [DOMAIN_MAP.md](DOMAIN_MAP.md), [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md), historical `submodule_*.md` under this directory |
| Review cadence | when `.gitmodules` or cross-repo contracts change |

## 1. Purpose

This guide answers: **where `ipfs_datasets_py` ends and external repositories,
binaries, and services begin.** It enumerates the **ten current git
submodules**, clarifies **`ipfs_kit_py` / `ipfs_accelerate_py` ownership**, and
ties offline/unavailable integration behavior to graceful feature degradation
versus fail-closed trust boundaries.

Lifecycle mechanics (import hermeticity, `initialize()`, `RouterDeps`, lazy
install) are detailed in
[DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md).

## 2. Audience

- **Primary:** architects and developers deciding where new code, wrappers, and
  docs must live.
- **Secondary:** operators checking out submodules or provisioning external
  provers; agents placing tasks without inventing ownership.

## 3. Scope and non-goals

### In scope

- Git submodule map from root `.gitmodules` (ten entries).
- Ownership of `ipfs_kit_py` and `ipfs_accelerate_py` versus this package.
- Boundary patterns: thin wrappers, router aliases, optional backends.
- External services and native toolchains (not vendored as product core).
- Unavailable/offline integration behavior and trust policy.

### Non-goals

- Fixing broken nested submodules upstream (historical CI notes remain in
  `submodule_architecture.md`).
- Full MCP transport design (MCP architecture leaves).
- Per-prover install recipes (security verification guide + dependency guide).
- Agent-supervisor taskboard semantics (accelerate / runtime docs).

## 4. Context

The product is a modular Python package with **optional** integrations. Many
paths appear in the tree as empty directories until `git submodule update
--init` (or a non-recursive CI checkout) populates them. Packaging prefers
vendored sibling checkouts of kit/accelerate when present so editable installs
can bind to local source without claiming those repositories as part of this
repo's authority.

**Python 3.12+** remains the packaging floor for this package; sibling
repositories may declare their own language constraints.

## 5. Ownership and boundaries (summary)

| This repository **owns** | This repository **does not own** |
| --- | --- |
| Dataset, processing, logic, MCP tool wrappers, packaging for `ipfs_datasets_py` | `ipfs_kit_py` product roadmap and release |
| Integration adapters and env gates that **call** kit/accelerate/provers | `ipfs_accelerate_py` router implementations and agent-supervisor runtime |
| Documented submodule pins (gitlink SHAs) and wrapper APIs | Upstream CEC/Talos/ShadowProver/Eng-DCEC/DCEC internals |
| Logic **submodule registry** (in-package logic families — not the same as git submodules) | External IPFS daemon, Neo4j, HF Hub, or host OS services |
| User-local prover install roots managed by this package's installers | Upstream solver vendors and binary distribution policy |

**Inbound:** library callers, MCP tools, CLIs, CI that optionally initializes
submodules.

**Outbound:** kit, accelerate, Kubo CLI, vector DBs, HF, native provers,
multimedia converter trees, Common Crawl engine, CEC prover assets.

## 6. Ten current git submodules

Authoritative list: repository root `.gitmodules`. Status in a fresh worktree
is often **not initialized** (`git submodule status` shows a leading `-`).
Empty directories are **not** capability evidence.

| # | Path | Remote (owner org) | Branch | Role in this product |
| --- | --- | --- | ---: | --- |
| 1 | `ipfs_kit_py` | `endomorphosis/ipfs_kit_py` | `main` | Primary IPFS kit integration checkout |
| 2 | `.tools/ipfs_kit_py` | `endomorphosis/ipfs_kit_py` | `main` | Tooling mirror of kit (same upstream; tooling layout) |
| 3 | `ipfs_accelerate_py` | `endomorphosis/ipfs_accelerate_py` | `main` | Acceleration, distributed inference, canonical routers, agent-supervisor adjacency |
| 4 | `ipfs_datasets_py/logic/CEC/DCEC_Library` | `endomorphosis/DCEC_Library` | `master` | DCEC library assets for CEC logic |
| 5 | `ipfs_datasets_py/logic/CEC/Talos` | `endomorphosis/Talos` | `master` | Talos prover / CEC tooling |
| 6 | `ipfs_datasets_py/logic/CEC/Eng-DCEC` | `endomorphosis/Eng-DCEC` | `master` | Eng-DCEC assets |
| 7 | `ipfs_datasets_py/logic/CEC/ShadowProver` | `endomorphosis/ShadowProver` | `master` | ShadowProver assets |
| 8 | `ipfs_datasets_py/multimedia/convert_to_txt_based_on_mime_type` | `endomorphosis/convert_to_txt_based_on_mime_type` | `main` | MIME-based text conversion pipeline |
| 9 | `ipfs_datasets_py/multimedia/omni_converter_mk2` | `endomorphosis/omni_converter_mk2` | `main` | Omni media converter (optional system deps) |
| 10 | `ipfs_datasets_py/processors/web_archiving/common_crawl_search_engine` | `endomorphosis/common_crawl_search_engine` | `main` | Common Crawl search engine integration |

```text
ipfs_datasets_py (this repo)
├── ipfs_kit_py/                          [submodule 1]  external ownership
├── .tools/ipfs_kit_py/                   [submodule 2]  external ownership
├── ipfs_accelerate_py/                   [submodule 3]  external ownership
└── ipfs_datasets_py/
    ├── logic/CEC/
    │   ├── DCEC_Library/                 [submodule 4]
    │   ├── Talos/                        [submodule 5]
    │   ├── Eng-DCEC/                     [submodule 6]
    │   └── ShadowProver/                 [submodule 7]
    ├── multimedia/
    │   ├── convert_to_txt_based_on_mime_type/  [submodule 8]
    │   └── omni_converter_mk2/                 [submodule 9]
    └── processors/web_archiving/
        └── common_crawl_search_engine/   [submodule 10]
```

### 6.1 Checkout policy

| Practice | Recommendation |
| --- | --- |
| Local full capability | `git submodule update --init` for needed paths only |
| CI | Prefer **non-recursive** direct submodules when nested gitlinks are broken upstream (see historical `submodule_architecture.md`) |
| Docs / tests without integrations | Leave submodules empty; treat features as optional |
| Claiming capability | Require initialized content **and** runtime probe, not path existence |

### 6.2 Git submodules vs logic submodule registry

Do **not** confuse:

| Concept | Location | Meaning |
| --- | --- | --- |
| **Git submodule** | `.gitmodules` + gitlinks | Separate repositories vendored by path |
| **Logic submodule registry** | `ipfs_datasets_py/logic/submodule_registry.py` | In-package map of logic *families* (`ir_core`, `intent_ir`, `external_provers`, …) |

The registry may note optional empty trees (e.g. ErgoAI placeholder) but it is
**not** a duplicate of `.gitmodules`.

## 7. `ipfs_kit_py` and `ipfs_accelerate_py` ownership

### 7.1 `ipfs_kit_py`

| Aspect | Boundary |
| --- | --- |
| **Canonical owner** | Separate repository (`ipfs_kit_py` submodule / published package) |
| **This package's role** | Optional backend via `ipfs_backend_router`; bootstrap helpers in `auto_installer.ensure_main_ipfs_kit_py`; packaging may prefer local checkout for dynamic dependencies |
| **Enable flags** | `IPFS_DATASETS_PY_ENABLE_IPFS_KIT`, `IPFS_DATASETS_AUTO_INSTALL_IPFS_KIT`, `IPFS_KIT_DISABLE`, `IPFS_KIT_AUTO_INSTALL_DEPS` |
| **Does not own** | Kit's internal APIs beyond the adapter contract; IPFS cluster policy; daemon lifecycle |

`.tools/ipfs_kit_py` is a **second checkout path** of the same upstream for
tooling layouts; it does not create a second product owner.

### 7.2 `ipfs_accelerate_py`

| Aspect | Boundary |
| --- | --- |
| **Canonical owner** | Separate repository (`ipfs_accelerate_py`) |
| **This package's role** | Thin integration (`ml/accelerate_integration`, package `accelerate_integration`), `RouterDeps.get_accelerate_manager`, env `IPFS_ACCELERATE_ENABLED` |
| **Router authority** | `llm_router`, `embeddings_router`, `multimodal_router` **implementations** live in accelerate; datasets paths are **compatibility aliases** via `_router_alias` |
| **Agent supervisor** | Adjacent to accelerate family; this repo documents placement as fail-closed for side effects — it does not own supervisor leases |
| **Does not own** | Accelerate release train, distributed hardware backends, supervisor taskboards |

```text
Caller
  |
  v
ipfs_datasets_py.llm_router  (alias module object)
  |
  v
ipfs_accelerate_py.llm_router  << CANONICAL implementation & state
```

### 7.3 Packaging note

`pyproject.toml` marks core dependencies as **dynamic**, resolved from
`setup.py` so editable installs can prefer vendored `ipfs_kit_py` /
`ipfs_accelerate_py` checkouts when present. Preference is an **install-time
convenience**, not a transfer of repository ownership.

## 8. Components (integration surfaces)

| Surface | Path / entry | External peer | Failure mode |
| --- | --- | --- | --- |
| IPFS backend router | `ipfs_backend_router.py` | kit, accelerate, Kubo CLI, HTTP API | Fallback toward local Kubo; optional providers off |
| Accelerate manager | `ml/accelerate_integration` | `ipfs_accelerate_py` | Local compute / `None` managers |
| Router aliases | `*_router.py`, `_router_alias.py` | accelerate routers | Import error if accelerate missing and no checkout |
| CEC wrappers | `logic/CEC/*_wrapper.py` | CEC submodules 4–7 | Empty tree → feature unavailable |
| Multimedia | `multimedia/*` submodules | converter repos | Optional extras + system bins (ffmpeg, etc.) |
| Common Crawl | `processors/web_archiving/common_crawl_search_engine` | submodule 10 | Search features off |
| External provers | `logic/external_provers` | Z3/CVC5/Lean/Coq/… natives | Lazy install or fail; never silent proof |
| Managed provers CLI | `ipfs-datasets-install-provers` | same natives | Operator-driven portfolio install |
| Vector / graph / HF | `vector_stores`, `knowledge_graphs`, `huggingface` | FAISS/Qdrant/ES, Neo4j, Hub | Optional extras; network |

## 9. End-to-end cross-boundary flows

### 9.1 IPFS operation with optional kit

1. Caller invokes IPFS helper through datasets APIs or MCP tools.
2. `ipfs_backend_router` reads env / `RouterDeps` / forced backend name.
3. If kit enabled and available → kit backend; else try other enabled providers.
4. Default residual path: local Kubo CLI (`IPFS_DATASETS_PY_KUBO_CMD`).
5. If nothing works → feature error / unavailable (degradation), not a forged CID.

### 9.2 LLM / embeddings / multimodal routing

1. Caller imports datasets router alias (compat).
2. Alias loads accelerate module (installed package or sibling checkout).
3. Mutable routing state and provider selection execute **inside accelerate**.
4. Datasets may inject shared managers via `RouterDeps` / `initialize()`.

### 9.3 CEC / ShadowProver path

1. Logic CEC wrappers import only when a CEC feature is requested.
2. Git submodules must be checked out for full native assets.
3. Missing checkout → optional path disabled; formal claims must not pretend
   ShadowProver succeeded.

### 9.4 Theorem prover (native)

See [DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md) §8.6
and [lazy_theorem_prover_installation.md](../security_verification/lazy_theorem_prover_installation.md).
Boundary rule: **datasets owns the installer and bridge**; **solver vendors own
binaries**; **proof policy owns whether a result counts**.

## 10. Contracts

### 10.1 Import and initialization at the boundary

| Rule | Detail |
| --- | --- |
| No import-time kit/accelerate requirement | Package root avoids eager accelerate/kit pulls (minimal and default paths) |
| Explicit initialize | Apps share `RouterDeps` via `initialize()` before multi-router workloads |
| Opt-in backend enables | Kit/accelerate IPFS backends require enable flags (or successful bootstrap that sets them) |
| Alias honesty | Document accelerate routers as canonical; datasets paths as compat |

### 10.2 Capability probing across boundaries

| Probe | Safe conclusion | Unsafe conclusion |
| --- | --- | --- |
| Submodule directory exists | Path reserved | Feature ready |
| `is_accelerate_available()` | Integration layer not env-disabled | Distributed production capacity |
| Prover on PATH after install | Environment has binary | Model verified / authorized |
| MCP tool listed | Tool registered | Side effect allowed |

### 10.3 Offline / unavailable integration behavior

| Boundary offline | Expected datasets behavior |
| --- | --- |
| No network for pip/git | Auto-install fails or uses wheelhouse; features degrade |
| Submodules not initialized | Wrappers report missing; product core still imports |
| No Kubo / kit / accelerate | IPFS ops fail or use whatever single backend remains; no fake success |
| No prover binaries | Routes skip/error; strict mode raises; no silent SAT |
| HF / Neo4j / ES down | Dependent features error; unrelated domains continue |
| Agent supervisor absent | Placement/advisory only; side effects fail closed |

### 10.4 Graceful degradation vs fail-closed trust (integration lens)

| Integration class | Policy |
| --- | --- |
| Media conversion, OCR, optional scrapers, accelerate speedups, remote router cache | **Graceful degradation** — feature off or slower local path |
| IPFS add/cat when no backend | **Hard feature failure** (no forged CID), not a trust grant |
| Proof corpus, admissibility, intent authorization, wallet grants, Profile G side effects | **Fail closed** — missing peer or proof ⇒ deny/abstain/error |
| Simulated ZKP / stub backends | **Never** production-authoritative |
| Supervisor / remote execution | External leases; datasets must not imply execution authority from discovery |

**Same rule as the dependency guide:** degrade **features**; fail closed on
**trust**.

## 11. Invariants

1. Exactly **ten** git submodule entries are declared in current `.gitmodules`;
   document any future change with a revision of this page.
2. `ipfs_kit_py` and `ipfs_accelerate_py` are **external owners**; this package
   adapts and aliases.
3. Datasets package-root routers that re-export accelerate modules are
   **compatibility surfaces**, not alternate authorities.
4. Empty submodule checkouts never satisfy acceptance for submodule-backed
   capability claims.
5. Logic `submodule_registry` ≠ git submodules.
6. Cross-repo integration failures must not weaken authorization or proof gates.
7. Supported language floor for this package remains **Python 3.12+**.

## 12. Extension points

| Need | Where to extend |
| --- | --- |
| New git submodule | `.gitmodules` + wrapper under owning domain; update this table |
| New kit feature | Prefer kit-side API; thin adapter in datasets only |
| New accelerate router | Implement in accelerate; add datasets alias only if compat required |
| New external service | Domain package + optional extra; document offline failure |
| New native prover | Lazy installer + managed portfolio; security guide |

## 13. Failure modes

| Failure | Symptom | Operator action |
| --- | --- | --- |
| Submodule not inited | Empty dirs; import optional failures | `git submodule update --init -- <path>` |
| Nested submodule broken upstream | Recursive CI checkout fails | Non-recursive init (historical guidance) |
| Accelerate missing | Alias import / manager `None` | Install/checkout accelerate or disable features |
| Kit missing | Kit backend unavailable | Enable kit install or use Kubo |
| Docs treat submodule as core dep | False install requirements | Mark optional; cite this page |

## 14. Related documents

| Document | Role |
| --- | --- |
| [DEPENDENCY_AND_INITIALIZATION.md](DEPENDENCY_AND_INITIALIZATION.md) | Import, `initialize`, lazy install, probing, routers |
| [SYSTEM_CONTEXT.md](SYSTEM_CONTEXT.md) | System actors and optional systems list |
| [DOMAIN_MAP.md](DOMAIN_MAP.md) | In-package domain ownership |
| `submodule_architecture.md`, `submodule_deprecation.md`, `submodule_fix.md` | Historical CI/submodule ops notes (verify against current `.gitmodules`) |
| [lazy_theorem_prover_installation.md](../security_verification/lazy_theorem_prover_installation.md) | Native prover provisioning |

## 15. Validation

Re-check when `.gitmodules`, kit/accelerate adapter contracts, or packaging
dynamic-dependency policy change.

```bash
test -s docs/architecture/DEPENDENCY_AND_INITIALIZATION.md \
  && test -s docs/architecture/INTEGRATION_BOUNDARIES.md \
  && rg -n 'Python 3.12|initialize|lazy|ipfs_kit|ipfs_accelerate|submodule' \
       docs/architecture/DEPENDENCY_AND_INITIALIZATION.md \
       docs/architecture/INTEGRATION_BOUNDARIES.md
```

Evidence for this revision: root `.gitmodules` (ten path entries);
`git submodule status` shapes; `_router_alias.py` and package-root router
aliases; accelerate integration env gates; IPFS backend router flags; CEC and
multimedia layout; SYSTEM_CONTEXT optional-systems section; dependency lifecycle
sources cited in the sibling guide.
