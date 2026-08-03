# Subsystem extension recipes

| Field | Value |
| --- | --- |
| Interface | `ExtensionRecipeCatalog@1` |
| Task | `IPFSDOC-071` |
| Status | `canonical` |
| Owner | developer-docs |
| Source of truth | Live package trees under `ipfs_datasets_py/`; architecture leaves under `docs/architecture/`; [ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-003](../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md), [ADR-005](../architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md); sibling [REPOSITORY_MAP.md](REPOSITORY_MAP.md), [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md) |
| Last verified | 2026-08-03 |
| Audience | developer, agent, architect |
| Related | [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md), [DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md), [RUNTIME_ENTRYPOINTS.md](../architecture/RUNTIME_ENTRYPOINTS.md) |

## 1. Purpose

This page turns architecture into **actionable, invariant-preserving workflows**
for the six extension kinds contributors most often implement:

| # | Recipe | Primary domain tree |
| --- | --- | --- |
| 1 | **Processor** | `ipfs_datasets_py/processors/` |
| 2 | **Storage / vector backend** | `ipfs_backend_router`, `vector_stores/` |
| 3 | **MCP tool** | `ipfs_datasets_py/mcp_server/tools/` |
| 4 | **Logic IR / compiler / prover** | `ipfs_datasets_py/logic/` |
| 5 | **Policy / constraint** | `logic` admissibility + `mcp_server` dispatch |
| 6 | **Documentation page** | `docs/` under information architecture |

Each recipe names **owner contracts**, **files**, **registration / export
steps**, **optional dependencies**, **negative cases**, **tests**,
**integration gates**, and **docs** to update. Recipes cite current-tree paths;
when dual surfaces still coexist (especially processors), the dual surface is
documented rather than pretended unified.

This page does **not** replace domain architecture leaves. Use
[REPOSITORY_MAP.md](REPOSITORY_MAP.md) to locate trees, then this page for the
change workflow, then the leaf guides for full contracts.

---

## 2. Global invariants (all recipes)

These rules are **fail-closed product policy**. Recipes that violate them are
incorrect even if tests are green for a narrow case.

| Invariant | Requirement | Authority |
| --- | --- | --- |
| **One registry per concern** | Do not create a second discovery map for the same names, schemas, or selection policy. Deprecation shims may re-export only. | [ADR-005](../architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) |
| **No eager optional imports** | Heavy / optional stacks (FAISS, Qdrant, solvers, OCR, FastMCP, LLM) load on first use or behind env flags—not at hermetic package import. | [ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) |
| **No policy bypass** | Discovery, health, cache hit, rank, parse success, or soft-skip is never authorization or proof. Do not add “allow when subsystem missing” for trust paths. | [ADR-003](../architecture/decisions/ADR-003-LAYERED-AUTHORITY.md), [ADR-004](../architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) |
| **No undocumented public exports** | New public symbols go through deliberate `__all__` / package exports and, for logic topology, `submodule_registry` / view registry when applicable. | Domain leaves + packaging surface |
| **Domain owns algorithms** | MCP tools, CLI, and adapters are thin wrappers. Business logic lives in domain packages. | MCP package ADR-001/004; [ADR-005](../architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) |
| **Discovery ≠ capability** | A registered name means addressable **if** deps allow; it does not assert production readiness. | [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) |

### Forbidden anti-patterns (catalog)

- Duplicate registries or Markdown “inventories” treated as equal authority to code.
- Eager import of optional backends at package or module top level without guards.
- Skipping dispatch pipeline / admissibility / constraint checks “for convenience.”
- Exporting new public APIs only via star-import side effects with no docs or tests.
- Putting product logic only in `mcp_server/tools/**` or only in adapter files.
- Claiming proof, grant, or content identity from pin success, search score, or list membership.

---

## 3. How to use a recipe

1. Confirm **domain ownership** in [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md)
   and [REPOSITORY_MAP.md](REPOSITORY_MAP.md) §4–5.
2. Open the **owner architecture leaf** linked in the recipe.
3. Implement domain code first; wrappers and registration second.
4. Keep optional deps lazy; exercise missing-extra negative paths.
5. Register on the **canonical** registry for that concern only.
6. Add nearest tests and run the recipe’s integration gates when provisioned.
7. Update the listed docs (architecture leaf + this page if the workflow changes).

---

## 4. Recipe: Processor

### 4.1 Owner contracts

| Concern | Owner |
| --- | --- |
| Protocol / result shapes | `ProcessorProtocol` families under `processors/protocol.py` and `processors/core/protocol.py` |
| Registry (canonical for new unified work) | `processors.core.registry` (`ProcessorRegistry`, `get_global_registry`) |
| Parallel registry singleton (compat period) | `processors.core.processor_registry` — still used by core `UniversalProcessor`; do not invent a third |
| Adapters | `processors/adapters/*` + `adapters/auto_register.py` |
| Entry orchestration | Root `UniversalProcessor` and `core/universal_processor.py` (dual; match the registry you register on) |
| Architecture leaf | [PROCESSOR_PIPELINE.md](../architecture/processing/PROCESSOR_PIPELINE.md) |

**Does not own:** MCP framing, formal IR digests, vector backend selection.

### 4.2 Files to touch

| Step | Paths |
| --- | --- |
| Domain engine | `ipfs_datasets_py/processors/<domain>/…` or `specialized/`, `file_converter/`, `multimedia/`, scrapers as appropriate |
| Protocol implementation | New class in domain module **or** adapter under `processors/adapters/<name>_adapter.py` |
| Auto-register table (if adapter) | `processors/adapters/auto_register.py` (add tuple to `adapters_to_register`) |
| Optional package export | `processors/adapters/__init__.py` (`__all__` + guarded import); root `processors/__init__.py` only if intentionally public |
| MCP exposure (optional, thin) | `mcp_server/tools/<category>/…` wrapping the domain API |
| Tests | `tests/unit/processors/…`; adapter tests near existing `test_*_adapter.py` |

### 4.3 Registration and export steps

1. Implement processing logic in the domain package (not in MCP).
2. Choose **one** protocol family for the dual-surface period:
   - **Core routing:** `can_handle` / `process(context)` / `get_capabilities`.
   - **Root-shaped adapters (legacy wrap):** `can_process` / `process` /
     `get_supported_types` (existing adapters pattern).
3. Register on the **same** registry the chosen `UniversalProcessor` imports:
   ```python
   from ipfs_datasets_py.processors.core.registry import get_global_registry
   registry = get_global_registry()
   registry.register(processor=instance, priority=10, name="MyProcessor")
   ```
4. Prefer `register_all_adapters()` for stock adapters; extend its table rather
   than a parallel register loop.
5. Export only symbols that are part of the public story (`__all__`); keep
   private helpers underscored.
6. Do **not** assume import of `processors` auto-registers adapters—callers must
   invoke registration.

### 4.4 Optional dependencies

| Stack | Typical extras / probes | Behavior when missing |
| --- | --- | --- |
| OCR | `ocr` extra (`easyocr`, …) | Adapter omitted or `DependencyError`-class failure |
| Multimedia | FFmpeg, yt-dlp, package multimedia paths | Feature absent; registration loop continues |
| PDF / native extractors | optional libraries | Extractor registry omits backend |
| LLM classify | LLM extras | Domain API returns structured error |

Use lazy imports inside methods; adapter `__init__.py` already uses try/except
ImportError → `None` for optional adapter classes.

### 4.5 Negative cases

| Case | Expected outcome |
| --- | --- |
| Duplicate processor `name` | `ValueError` from `register` |
| Optional adapter ImportError | Warning; remaining adapters still register |
| Dual registry mismatch | “Registered but not found” if UP uses the other singleton—pass explicit shared registry or align imports |
| Protocol mismatch (root adapter vs core `can_handle`) | Skip or AttributeError—bridge or match families |
| Untrusted path/URL | Permanent validation error; no infinite retry |
| Claiming proof from extract success | **Forbidden** |

### 4.6 Tests

| Layer | Location / focus |
| --- | --- |
| Unit selection | `can_*` / priority selection with fake processors |
| Unit process | One success path + one permanent failure path |
| Adapter | `tests/unit/processors/test_*_adapter.py` patterns |
| Auto-register | Registration count and graceful skip on missing deps |
| Nearest map | [REPOSITORY_MAP.md](REPOSITORY_MAP.md) § tests table for `processors` |

### 4.7 Integration gates

```bash
# Structural anchors
test -e ipfs_datasets_py/processors/core/registry.py
test -e ipfs_datasets_py/processors/adapters/auto_register.py
rg -n 'def get_global_registry' ipfs_datasets_py/processors/core/registry.py \
  ipfs_datasets_py/processors/core/processor_registry.py

# Focused unit (when suite is provisioned)
python -m pytest tests/unit/processors/ -q --collect-only
# Tighten to concrete modules after implementation, e.g.:
# python -m pytest tests/unit/processors/test_batch_adapter.py -q
```

Optional OCR/FFmpeg/submodules are **not** required for hermetic unit gates;
label live media/PDF runs as integration with provisioned tools.

### 4.8 Docs to update

- [PROCESSOR_PIPELINE.md](../architecture/processing/PROCESSOR_PIPELINE.md) if
  dual surface, registration, or protocol changes.
- Sibling [FILE_AND_MULTIMEDIA.md](../architecture/processing/FILE_AND_MULTIMEDIA.md)
  or web/legal leaf when those domains gain processors.
- Package-local README only as component notes subordinate to architecture.

---

## 5. Recipe: Storage / vector backend

Two related but **separate** concerns share this recipe: content-addressed
**IPFS / storage backends** and **vector index backends**. Do not merge their
registries.

### 5.1 Owner contracts

| Concern | Owner | Architecture leaf |
| --- | --- | --- |
| IPFS backend protocol + factory registry | `ipfs_datasets_py/ipfs_backend_router.py` (`IPFSBackend`, `register_ipfs_backend`) | [STORAGE_CACHING_AND_BACKENDS.md](../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md) |
| Content identity / CID rules | storage + ADR-001 | [CONTENT_ADDRESSING_AND_IPLD.md](../architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md) |
| Vector store protocol | `vector_stores/base.py` (`BaseVectorStore`) | [VECTOR_STORES.md](../architecture/retrieval/VECTOR_STORES.md) |
| Multi-store manager | `vector_stores/manager.py` (`VectorStoreManager`, `_create_store`) | same |
| Index management engine | `vector_stores/management_engine.py` | same (tool-friendly create/list; not a second protocol) |
| High-level API | `vector_stores/api.py` (`create_vector_store`, …) | same |
| Config / types | `vector_stores/config.py` (`VectorStoreType`, factory helpers) | same |

**Does not own:** embedding generation (`embeddings/`), hybrid query fusion
(`search/`), authorization of who may search, or treating collection names as CIDs.

### 5.2 Files to touch

**IPFS / storage backend**

| Step | Paths |
| --- | --- |
| Backend implementation | New module implementing `IPFSBackend` (prefer next to router consumers, not inside MCP) |
| Registration | Call `register_ipfs_backend(name, factory)` from an explicit init path—not import-time side effects that force kit install |
| Cache / pin (if applicable) | `caching/`, `core_operations` pinner helpers—document key schema and that cache ≠ proof |
| Tests | Env-matrix backend resolution; pin failure; offline IPLD local mode |

**Vector backend**

| Step | Paths |
| --- | --- |
| Store class | `ipfs_datasets_py/vector_stores/<name>_store.py` subclassing `BaseVectorStore` |
| Type enum / config | `vector_stores/config.py` (`VectorStoreType`, `create_*_config`) |
| Factory branch | `VectorStoreManager._create_store` and `api.create_vector_store` |
| Optional import guard | Top of store module / manager (pattern: Elasticsearch try/except in `manager.py`) |
| Migration bridge (optional) | `vector_stores/bridges/` |
| MCP thin wrappers | `mcp_server/tools/vector_store_tools/`, `vector_tools/`, `index_management_tools/` — delegate only |
| Tests | `tests/unit/vector_stores/` |

### 5.3 Registration and export steps

**IPFS backend**

1. Implement `IPFSBackend` methods required by the router contract.
2. Register: `register_ipfs_backend("mybackend", factory)`.
3. Document env force flags and capability gaps (especially block API vs pin-only).
4. Clear router caches after config changes in long-lived processes
   (`clear_ipfs_backend_router_caches` when applicable).
5. Export factory only if part of public package surface; keep mocks labeled.

**Vector backend**

1. Implement all abstract methods on `BaseVectorStore`.
2. Add `VectorStoreType` value and config helper.
3. Branch in `_create_store` and public `create_vector_store` API.
4. `manager.register_store(name, config)` for multi-store workflows.
5. Optional IPLD hooks: default no-op/warn when unsupported—never fake success.
6. Export public constructors via `vector_stores` package `__all__` / `api` only
   when intentional; document capability matrix per backend.

### 5.4 Optional dependencies

| Backend | Deps / extras | Missing behavior |
| --- | --- | --- |
| FAISS / IPLD search | `vectors` extra (`faiss-cpu`, …) | Constructor fail-closed or structured error—no fake neighbors |
| Qdrant | `qdrant-client` | Import guard; unavailable when selected |
| Elasticsearch | `elasticsearch` async client | `HAVE_ELASTICSEARCH` style guard in manager |
| IPFS kit / accelerate | env + `RouterDeps` | Feature degrade; identity rules unchanged |
| Local IPLD | in-tree / disk | Offline mode OK when explicitly local |

Never import heavy clients at `ipfs_datasets_py` package import time.

### 5.5 Negative cases

| Case | Expected outcome |
| --- | --- |
| Unsupported vector backend name | Structured error with supported list (management engine pattern) |
| Required dep missing for selected backend | Raise or error dict—not plausible fake ANN results |
| `export_to_ipld` on non-IPLD store | No-op / warning; not success with fake CID |
| Using collection name as content CID | **Forbidden** documentation and API claim |
| Pin success as authorization | **Forbidden** |
| Caching policy decisions without input digests | **Forbidden** |
| Business logic only in MCP vector tools | **Forbidden**—engines under `vector_stores/` |

### 5.6 Tests

| Layer | Location / focus |
| --- | --- |
| Vector unit | `tests/unit/vector_stores/` (`test_manager_and_api.py`, `test_ipld_vector_store.py`, mocks for remote clients) |
| Protocol compliance | create/add/search/delete with in-memory or mock store |
| Storage / router | backend resolution with env matrix; pin error paths; offline IPLD |
| MCP | thin-wrapper tests that assert delegation, not reimplemented ANN |

### 5.7 Integration gates

```bash
test -e ipfs_datasets_py/vector_stores/base.py
test -e ipfs_datasets_py/vector_stores/manager.py
test -e ipfs_datasets_py/ipfs_backend_router.py
rg -n 'def register_ipfs_backend|class IPFSBackend' ipfs_datasets_py/ipfs_backend_router.py
rg -n 'class BaseVectorStore|def _create_store' ipfs_datasets_py/vector_stores/

python -m pytest tests/unit/vector_stores/ -q --collect-only
```

Live Qdrant/Elasticsearch/IPFS daemon tests are optional integration only when
services are provisioned.

### 5.8 Docs to update

- [VECTOR_STORES.md](../architecture/retrieval/VECTOR_STORES.md) for new vector
  backends and capability gaps.
- [STORAGE_CACHING_AND_BACKENDS.md](../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md)
  and [CONTENT_ADDRESSING_AND_IPLD.md](../architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md)
  for IPFS backends / identity boundaries.
- Retrieval hub extension table: [retrieval/README.md](../architecture/retrieval/README.md).

---

## 6. Recipe: MCP tool

### 6.1 Owner contracts

| Concern | Owner |
| --- | --- |
| Hierarchical discovery / dispatch | `mcp_server/hierarchical_tool_manager.py` + directory tree `mcp_server/tools/<category>/` |
| Server meta-tools registration | `mcp_server/server.py` (`IPFSDatasetsMCPServer.register_tools`) — hierarchical meta-tools, not per-function FastMCP register |
| Thin-wrapper contract | Package ADR-001; [THIN_TOOL_ARCHITECTURE.md](../../ipfs_datasets_py/mcp_server/THIN_TOOL_ARCHITECTURE.md) |
| Class-style object registry (compat) | `mcp_server/tool_registry.py` — migration only, not a second product inventory |
| Architecture leaves | [TOOL_LIFECYCLE_AND_REGISTRIES.md](../architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md), [SERVER_AND_DISPATCH.md](../architecture/mcp/SERVER_AND_DISPATCH.md) |

**Does not own:** domain algorithms, IR schemas, processor plugin registry.

### 6.2 Files to touch

| Step | Paths |
| --- | --- |
| Domain engine first | Appropriate `ipfs_datasets_py/<domain>/…` or `core_operations/` |
| Tool module | `ipfs_datasets_py/mcp_server/tools/<category>/<tool_name>.py` |
| Category package | `tools/<category>/__init__.py` export if category uses explicit exports |
| Optional metadata | `@tool_metadata(...)` when used by the category |
| Optional category.json | Only when a **new** category is justified |
| CLI alignment (optional) | Dynamic runner import path `…tools.<category>.<tool>` |
| Tests | `tests/mcp/`, `tests/unit/mcp*/`, category-focused unit tests |

### 6.3 Registration and export steps

1. Confirm capability exists (or implement it) in the **domain** package.
2. Choose existing `tools/<category>/` matching the concern; create a category
   only when domain ownership cannot fit an existing one.
3. Add public async function preferably named like the module (e.g. `my_tool`).
4. Thin body: validate → import domain → delegate → return `dict` with clear
   `status` / error.
5. **Do not** call FastMCP `register` for each new function on the canonical
   hierarchical server—directory discovery + meta-tools list/dispatch.
6. Do not reintroduce flat bulk registration of hundreds of tools as the
   default path (`import_tools_from_directory` is legacy).
7. Document parameters in the docstring (first line is list description).
8. Export only intentional public callables; private helpers stay `_`-prefixed
   so discovery skips them.

### 6.4 Optional dependencies

| Situation | Behavior |
| --- | --- |
| Domain optional extra missing | Tool may still **list**; call returns structured `status=error` / unavailable |
| Module import fails | Tool absent from category list for this process |
| `mcp` package missing | Meta-tools may not register—fail closed on real MCP run |
| Pipeline / policy stages unconfigured | See policy recipe; soft-skip is not a security proof |

Lazy-import domain engines **inside** the tool function when the stack is heavy.

### 6.5 Negative cases

| Case | Expected outcome |
| --- | --- |
| Private `_helper` function | Not discovered as a tool |
| Business logic only in tool file | **Forbidden**—extract engine |
| Flat FastMCP re-registration of all tools | **Forbidden** as default product path |
| Duplicate class-registry name | Compat registry may warn and overwrite—prefer hierarchical naming |
| Treating `tools_list_tools` presence as capability success | **Forbidden** |
| Uncaught exceptions for expected missing extras | Prefer structured error dict |

### 6.6 Tests

| Layer | Focus |
| --- | --- |
| Unit import/call | Import module; call function with mocks of domain engine |
| Missing extra | Assert error envelope without process crash |
| Hierarchical manager | `tests/unit/mcp*/test_hierarchical_tool_manager.py` patterns |
| Integration | Meta-tool list → dispatch for the category when MCP stack provisioned |

### 6.7 Integration gates

```bash
test -d ipfs_datasets_py/mcp_server/tools
python -c "
from pathlib import Path
root = Path('ipfs_datasets_py/mcp_server/tools')
cats = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith('_'))
print('categories_on_disk', len(cats))
"
# Optional focused tests
python -m pytest tests/unit/test_hierarchical_tool_manager.py -q --collect-only 2>/dev/null || true
```

### 6.8 Docs to update

- [TOOL_LIFECYCLE_AND_REGISTRIES.md](../architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md)
  when discovery rules change.
- Category README only if present and maintained; never undated global tool-count
  tables as inventory authority.
- Domain architecture leaf for the capability, not only MCP docs.

---

## 7. Recipe: Logic IR / compiler / prover

This recipe covers three layers that must stay **non-interchangeable** in
authority: IR identity, compile/decompile formalization, and external proof
backends.

### 7.1 Owner contracts

| Layer | Owner | Architecture leaf |
| --- | --- | --- |
| IR kernel / identity / families | `logic/ir_core/`, family packages | [IR_FAMILY_AND_IDENTITY.md](../architecture/logic/IR_FAMILY_AND_IDENTITY.md) |
| Logic topology map | `logic/submodule_registry.py` (`logic_submodule_specs`, `logic_integration_manifest`) | same + registry module docstring |
| Formalization / views / compilers | `logic/formalization/` (`ViewRegistry`, compilers); legal_ir / modal / family compilers | [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](../architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) |
| Proof backends registry | `logic/backends/registry.py` (`ProofBackend`, register; no import-time solver load) | [EXTERNAL_PROVERS.md](../architecture/logic/EXTERNAL_PROVERS.md) |
| External provers / hammers | `logic/external_provers/`, `logic/hammers/`, bridge router | EXTERNAL_PROVERS |
| Result authority | Result/status protocols—not SAT stdout alone | [RESULT_AUTHORITY.md](../architecture/logic/RESULT_AUTHORITY.md) |

**Does not own:** MCP transport; treating reconstruction quality or hammer
portfolio success as theorem kernel verification without native-kernel receipt.

### 7.2 Files to touch

| Extension kind | Paths |
| --- | --- |
| New IR family / submodule | Family package under `logic/<family>/`; **must** add `LogicSubmoduleSpec` in `logic/submodule_registry.py` |
| Shared IR contracts | `logic/ir_core/` (canonical, identity, provenance, schema_registry, protocols) |
| New formalization view | `logic/formalization/views.py` + compiler paths; identity-pin view registry |
| Domain compiler | e.g. `logic/legal_ir/canonical_compiler.py`, `logic/modal/compiler.py` |
| New proof backend | `logic/backends/<backend>/` + register with backend registry (side-effect-free declaration) |
| Prover adapter | `logic/external_provers/…`; capability probe via `feature_detection` / adapter `is_available` |
| Lazy install (optional) | `logic/external_provers/lazy_installer.py`; CLI `ipfs-datasets-install-provers` |
| MCP exposure | `mcp_server/tools/logic_tools/` thin wrappers only |
| Tests | `tests/unit/logic/…`, `tests/unit/logic/formalization/`, `tests/unit/logic/backends/`, `tests/unit/logic/test_logic_submodule_registry.py` |

### 7.3 Registration and export steps

**IR / submodule**

1. Implement family modules with fail-closed unknown extensions.
2. Register in `logic_submodule_specs` with roles, optional deps, public symbols,
   and import-check flags—**without** importing heavy optional stacks at map
   load time.
3. Export public symbols through family `__init__` / documented
   `public_symbols`; avoid silent star-export of experimental APIs.

**Compiler / formalization**

1. Bind formulas only to **registered views** and known symbols (`ViewRegistry`).
2. Preserve source-withholding rules for decompilers; source maps are evidence,
   not decompiler-required leakage.
3. Schema version bump when contract shapes change; pin identities in artifacts.
4. Never equate parse success or string similarity with semantic proof.

**Prover / backend**

1. Declare backend capabilities immutably; `register` rejects duplicates
   (`DuplicateBackendError`).
2. Availability checked only on explicit `is_available` or immediately before
   `run`—not at import.
3. Typed outcomes: proved / countermodel / UNKNOWN / unsupported / unavailable /
   timeout / policy-denied—do not collapse into a boolean “ok.”
4. Promote to trusted verification only via the authority model in RESULT_AUTHORITY
   / native-kernel paths—not solver stdout alone.

### 7.4 Optional dependencies

| Stack | Packaging | Notes |
| --- | --- | --- |
| Logic Python extras | `logic` optional-deps group | Import-safe without solvers |
| Theorem provers | `theorem-provers` extra + native binaries | Lazy / user-local install; see installer docs |
| Z3 / CVC5 / Lean / Coq / … | Backend-specific | Probe without download on import |
| ZKP circuits | package data under `logic/zkp/` | Separate attestation path |

Env and minimal-import flags from [ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md)
and [DEPENDENCY_AND_INITIALIZATION.md](../architecture/DEPENDENCY_AND_INITIALIZATION.md)
apply.

### 7.5 Negative cases

| Case | Expected outcome |
| --- | --- |
| Duplicate backend id | `DuplicateBackendError` |
| Unknown backend | `UnknownBackendError` |
| Unsupported lowering | `UnsupportedBackendRequest`—fail closed, no silent meaning loss |
| Solver missing | `unavailable` / structured error—not fake VERIFIED |
| Hammer / SAT success as theorem kernel | **Forbidden** substitution |
| Source text embedded in IR identity | Violates provenance contracts—**forbidden** |
| Second IR kernel outside `ir_core` / registered families | **Forbidden** |
| Eager solver install on package import | **Forbidden** |

### 7.6 Tests

| Layer | Location / focus |
| --- | --- |
| Registry completeness | `tests/unit/logic/test_logic_submodule_registry.py` |
| Formalization | `tests/unit/logic/formalization/` (contracts, views, compilers) |
| Backends | `tests/unit/logic/backends/`, registry duplicate/unknown cases |
| Import quiet / layering | `tests/unit/logic/test_logic_api_import_quiet.py`, `test_layering_import_boundaries.py` |
| Round-trip benchmarks | `benchmarks/semantic_roundtrip/` when measuring parity—not as unit proof |
| Integration | `tests/integration/logic/` when provisioned |

### 7.7 Integration gates

```bash
test -e ipfs_datasets_py/logic/submodule_registry.py
test -e ipfs_datasets_py/logic/backends/registry.py
test -e ipfs_datasets_py/logic/formalization/views.py

python -m pytest \
  tests/unit/logic/test_logic_submodule_registry.py \
  tests/unit/logic/formalization/ \
  -q --collect-only

# Hermetic: package import must not download solvers
python -c "import ipfs_datasets_py.logic.submodule_registry as s; print(len(s.logic_submodule_specs))"
```

Native prover installs and full ITP portfolios are **provisioned** gates, not
default CI obligations.

### 7.8 Docs to update

- [IR_FAMILY_AND_IDENTITY.md](../architecture/logic/IR_FAMILY_AND_IDENTITY.md)
- [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](../architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md)
- [EXTERNAL_PROVERS.md](../architecture/logic/EXTERNAL_PROVERS.md)
- [RESULT_AUTHORITY.md](../architecture/logic/RESULT_AUTHORITY.md) when outcome
  taxonomy or promotion rules change
- Operator guides under `docs/guides/` only when operator surface changes

---

## 8. Recipe: Policy / constraint

Policy spans **MCP pre-dispatch** (risk, UCAN, compliance meta-tools) and
**logic admissibility / legal-security constraints**. Do not implement either
as a soft flag inside a random tool.

### 8.1 Owner contracts

| Concern | Owner | Architecture leaf |
| --- | --- | --- |
| Dispatch pipeline gates | `mcp_server/dispatch_pipeline.py` (`DispatchPipeline`, `PipelineConfig`) | [POLICY_AND_AUTHORIZATION.md](../architecture/mcp/POLICY_AND_AUTHORIZATION.md) |
| Policy audit log | `mcp_server/policy_audit_log.py` | same + audit leaf |
| NL / UCAN policy surfaces | `mcp_server/nl_ucan_policy.py`, `temporal_policy.py`; tools under `logic_tools/` | POLICY_AND_AUTHORIZATION |
| Governed intent authorization | `logic/admissibility/`, intent IR | [GOVERNED_AUTHORIZATION.md](../architecture/logic/GOVERNED_AUTHORIZATION.md) |
| Legal / security constraints | `logic/legal_ir/`, `logic/security_ir/`, formalization constraint contracts | [LEGAL_AND_SECURITY_CONSTRAINTS.md](../architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md) |
| Constraint artifacts | `logic/formalization/constraint_contracts.py` and domain constraint modules | same |
| Graph constraints (product feature) | knowledge / graph tools that **add** constraints—not replace gate | knowledge + graph tool modules |

**Does not own:** “Open by default when no NL policy is registered” as a claim
of global security—production closed-world requires explicit policy registration
and pipeline configuration.

### 8.2 Files to touch

| Extension kind | Paths |
| --- | --- |
| New pre-dispatch stage | `dispatch_pipeline.py` + injectors; wire only when host enables flags |
| Policy meta-tools | `mcp_server/tools/logic_tools/policy_management_tool.py`, `nl_ucan_policy_tool.py` (thin) |
| Admissibility profile / gate | `logic/admissibility/…` |
| Legal selector / constraint | `logic/legal_ir/`, reasoner policy packs under processors legal reasoner when legal-domain |
| Security extension vocabulary | `logic/security_ir/` — **allowlist** unknown ids fail closed |
| Constraint schema version | `ConstraintArtifact` (or domain equivalent) with version bump |
| Tests | `tests/unit/logic/admissibility/`, `tests/unit/logic/security_ir/`, `tests/unit/logic/legal_ir/`, MCP policy/admissibility tests |

### 8.3 Registration and export steps

1. Prefer **composition**: attach `DispatchPipeline` with explicit
   `PipelineConfig` flags and injected checkers for production.
2. Register NL policies / compliance rules through the managed APIs
   (`policy_register`, `compliance_*`) rather than ad-hoc tool if-branches.
3. For security IR extensions: register vocabulary in the known-extension
   allowlist **before** cache put; unknown extensions reject.
4. For new constraint roles/families: version the artifact schema; do not
   silently concatenate families.
5. Record denials to audit/metrics without treating counters as authorization.
6. Export public policy APIs deliberately; do not expose internal bypass hooks.

### 8.4 Optional dependencies

| Component | Missing behavior |
| --- | --- |
| UCAN / key material | Tests may use mocks; production requires real verification policy |
| Policy meta-tools | Optional—absence does not remove hierarchical tools |
| Integrated pipeline stages | Soft-skip if unconfigured—**must not** be documented as fail-closed allow |
| ZKP attach on constraints | Optional; reuse shared ZKP helpers; not required for constraint identity |

### 8.5 Negative cases

| Case | Expected outcome |
| --- | --- |
| Allow without constraints | **Forbidden** |
| Promote retrieval rank to authority | **Forbidden** |
| Treat NOT_MODELED / UNKNOWN as grant | Reject / abstain until modeled |
| Soft-skip missing checker as security proof | **Forbidden** documentation and production reliance |
| Bypass pipeline “for agent convenience” | **Forbidden** |
| Health / Prometheus success ⇒ allow | **Forbidden** |
| Secrets in intent params that enter CIDs | **Forbidden**—use commitments / vault refs |
| Unknown security extension id | Reject put and reload |

### 8.6 Tests

| Layer | Focus |
| --- | --- |
| Unit profiles | `tests/unit/logic/admissibility/` |
| Constraint contracts | `tests/unit/logic/formalization/test_constraint_contracts.py` |
| Security / legal IR | `tests/unit/logic/security_ir/`, `legal_ir/` |
| MCP admissibility | `tests/unit/test_logic_admissibility_*.py` patterns |
| Golden / integration | Attested intent suites when present under `tests/integration/logic/` |

### 8.7 Integration gates

```bash
test -s docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md
test -s docs/architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md
test -e ipfs_datasets_py/mcp_server/dispatch_pipeline.py

python -c "
from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline, PipelineConfig, PipelineIntent
r = DispatchPipeline(config=PipelineConfig()).check(PipelineIntent('demo'))
print(r.verdict, r.allowed)
"

python -m pytest \
  tests/unit/logic/admissibility/ \
  tests/unit/logic/formalization/test_constraint_contracts.py \
  -q --collect-only
```

### 8.8 Docs to update

- [POLICY_AND_AUTHORIZATION.md](../architecture/mcp/POLICY_AND_AUTHORIZATION.md)
- [LEGAL_AND_SECURITY_CONSTRAINTS.md](../architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md)
- [GOVERNED_AUTHORIZATION.md](../architecture/logic/GOVERNED_AUTHORIZATION.md)
- [AUDIT_EVENTS_AND_OBSERVABILITY.md](../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md)
  when denial telemetry changes
- Operator [ATTESTED_INTENT_AUTHORIZATION.md](../guides/ATTESTED_INTENT_AUTHORIZATION.md)
  when operator surface moves

---

## 9. Recipe: Documentation page

### 9.1 Owner contracts

| Concern | Owner |
| --- | --- |
| Information architecture / placement | [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md) |
| Contributor workflow | [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md) |
| Page interface (this catalog) | `DocumentationPageContract@1` via contributing guide |
| Architecture page shape | [ARCHITECTURE_GUIDE_TEMPLATE.md](../architecture/ARCHITECTURE_GUIDE_TEMPLATE.md) |
| ADR lifecycle | [ADR_TEMPLATE.md](../architecture/decisions/ADR_TEMPLATE.md) |
| Source authority order | [SOURCE_AUTHORITY.md](../maintenance/SOURCE_AUTHORITY.md) |

**Does not own:** Silent rewrites of protected plan files; inventing product
behavior to match stale docs; treating session completion reports as API truth.

### 9.2 Files to touch

| Step | Paths |
| --- | --- |
| New page | Placement per IA (e.g. `docs/architecture/…`, `docs/developer_guides/…`, `docs/guides/…`) |
| Hub link | Parent README / domain index |
| Nav (selective) | `mkdocs.yml` only for maintained product entries—not full inventory |
| Deprecation of old home | Banner + pointer on superseded page |
| Evidence pages | Dated measurement sections under `docs/maintenance/` when measuring |
| **Never without task ownership** | Protected plans under `docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH_*` |

### 9.3 Registration and export steps

“Registration” for docs means **discoverability under IA**, not a Python
registry:

1. Choose placement and lifecycle state (`canonical`, `plan`, `evidence`,
   `historical`, …).
2. Copy the correct template; fill required metadata (`Status`, `Owner`,
   `Source of truth`, `Last verified`, audience).
3. Write required sections (purpose, scope, source grounding, validation,
   related pages). Architecture pages add ownership, flow, contracts, failure
   modes, extension points, invariants.
4. Link from the hub; add `mkdocs.yml` nav only when appropriate.
5. Cite live paths and tests; label historical quotes.
6. Do not create a parallel “better” root without deprecating the previous
   authority.

### 9.4 Optional dependencies

| Dependency | When needed |
| --- | --- |
| MkDocs + docs extras | `mkdocs build --strict` site gate |
| Optional product extras | Only when examples claim executable optional features—label prerequisites |
| Submodules | Document empty/uninitialized submodule state honestly |

Docs tasks must remain valid offline for structural checks (`test -s`, `rg`).

### 9.5 Negative cases

| Case | Expected outcome |
| --- | --- |
| Undocumented public export of a new package API | Recipe incomplete—add page section or API map entry + tests |
| Duplicate canonical home for same concern | Deprecate one; single authority |
| Eager claim of “production-ready / N tools” from undated banners | **Forbidden** as authority |
| Editing protected supervisor plan files | **Forbidden** |
| Rewriting archive to match new APIs | **Forbidden**—banner + pointer only |
| Stronger evidence class than tests establish | **Forbidden** |

### 9.6 Tests (validation)

Documentation “tests” are structural and authority checks:

```bash
test -s path/to/your_page.md
rg -n 'Status|Owner|Source of truth|Last verified' path/to/your_page.md
# Named implementation anchors exist
test -e ipfs_datasets_py/some_module.py
# Optional site build when provisioned
# mkdocs build --strict
```

### 9.7 Integration gates

- Links resolve relative to the new page.
- Bounded offline examples run when claimed executable.
- Domain architecture leaf and [REPOSITORY_MAP.md](REPOSITORY_MAP.md) still
  agree on ownership after the change.
- For this catalog page specifically:

```bash
test -s docs/developer_guides/EXTENSION_RECIPES.md
rg -n 'processor|vector|MCP tool|compiler|prover|policy|documentation' \
  docs/developer_guides/EXTENSION_RECIPES.md
```

### 9.8 Docs to update when the docs system changes

- [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md)
- [INFORMATION_ARCHITECTURE.md](../maintenance/INFORMATION_ARCHITECTURE.md)
- Parent hub READMEs
- This file when a new extension **kind** or registry concern appears

---

## 10. Cross-recipe quick reference

| Extension | Canonical discovery / registry | Primary code home | Thin edge |
| --- | --- | --- | --- |
| Processor | `processors.core.registry` (+ dual `processor_registry` compat) | `processors/` domain + `adapters/` | MCP pdf/media/file tools |
| IPFS storage backend | `register_ipfs_backend` in `ipfs_backend_router` | backend impl + router | MCP ipfs tools |
| Vector backend | `VectorStoreManager` / `api.create_vector_store` | `vector_stores/*_store.py` | `vector_store_tools` |
| MCP tool | Hierarchical tool tree + meta-tools | domain package engine | `mcp_server/tools/<cat>/` |
| Logic submodule / IR | `logic.submodule_registry` + `ir_core` | `logic/<family>/` | `logic_tools` |
| Compiler / views | `formalization.ViewRegistry` | `logic/formalization/`, family compilers | logic MCP tools |
| Prover backend | `logic.backends.registry` | `logic/backends/`, `external_provers/` | logic MCP tools |
| Policy / constraint | DispatchPipeline + admissibility / constraint artifacts | `mcp_server` + `logic` | policy meta-tools |
| Documentation page | IA placement + hub links | `docs/**` | `mkdocs.yml` (selective) |

---

## 11. Related pages

| Document | Relationship |
| --- | --- |
| [REPOSITORY_MAP.md](REPOSITORY_MAP.md) | Locate trees, hot files, nearest tests |
| [DOCUMENTATION_CONTRIBUTING.md](DOCUMENTATION_CONTRIBUTING.md) | Full docs page workflow |
| [DOMAIN_MAP.md](../architecture/DOMAIN_MAP.md) | Product domain ownership |
| [ADR-002](../architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Lazy optional capabilities |
| [ADR-005](../architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) | One registry per concern |
| [PROCESSOR_PIPELINE.md](../architecture/processing/PROCESSOR_PIPELINE.md) | Processor contracts |
| [VECTOR_STORES.md](../architecture/retrieval/VECTOR_STORES.md) | Vector backends |
| [STORAGE_CACHING_AND_BACKENDS.md](../architecture/storage/STORAGE_CACHING_AND_BACKENDS.md) | Storage backends |
| [TOOL_LIFECYCLE_AND_REGISTRIES.md](../architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md) | MCP tools |
| [COMPILERS_AND_SEMANTIC_ROUND_TRIP.md](../architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md) | Compilers |
| [EXTERNAL_PROVERS.md](../architecture/logic/EXTERNAL_PROVERS.md) | Provers |
| [POLICY_AND_AUTHORIZATION.md](../architecture/mcp/POLICY_AND_AUTHORIZATION.md) | MCP policy |
| [LEGAL_AND_SECURITY_CONSTRAINTS.md](../architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md) | Logic constraints |
| [TESTING_AND_EVIDENCE.md](TESTING_AND_EVIDENCE.md) | Focused evidence selection (sibling track) |

---

## 12. Validation (this page)

```bash
test -s docs/developer_guides/EXTENSION_RECIPES.md
rg -n 'processor|vector|MCP tool|compiler|prover|policy|documentation' \
  docs/developer_guides/EXTENSION_RECIPES.md
```

Expected: non-empty file; keyword hits for every recipe family listed in
acceptance for `IPFSDOC-071`.
