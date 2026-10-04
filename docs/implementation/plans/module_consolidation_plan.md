# Module Consolidation Plan (integrations/, file_converter/, ipfs_formats/, ipld/)

Last updated: 2026-02-09

## Goal
Reduce and consolidate the number of top-level modules exposed by the `ipfs_datasets_py` package by moving implementations out of legacy “surface-area” packages:

- `ipfs_datasets_py/integrations/*`
- `ipfs_datasets_py/file_converter/*`
- `ipfs_datasets_py/ipfs_formats/*`
- `ipfs_datasets_py/ipld/*`

Canonical destination for “data transformations” in this repo: `ipfs_datasets_py/data_transformation/*`.

…into existing canonical namespaces (already present but mostly empty):

- `ipfs_datasets_py/data_transformation/ipfs_formats/*`
- `ipfs_datasets_py/data_transformation/ipld/*`
- `ipfs_datasets_py/processors/*` (for processing pipelines)
- `ipfs_datasets_py/rag/*` and `ipfs_datasets_py/knowledge_graphs/*` (for RAG/GraphRAG + KG)

Compatibility requirement: **keep existing import paths working** via thin shims + `DeprecationWarning`, and make optional/advanced features **import-safe** (do not fail at import time because an optional dependency is missing).

Secondary goal: **consolidate overlapping “integration glue”** so callers can default to a small number of canonical namespaces.

## Non-goals
- No behavioral rewrites of conversion/RAG/IPLD logic as part of the move.
- No new UX, APIs, or features.
- No broad reformatting.

## Principles
1. **Canonical code lives in one place**; legacy paths become shims.
2. **Import-safe by default**: optional features fail only when invoked.
3. **Minimize public exports**: avoid wildcard exports in `__init__.py` (especially in shims).
4. **Stage changes**: move smallest/least-coupled modules first.

---

## Current state (already implemented)

The repository already has canonical namespaces in place, with shims for legacy paths:

- Canonical file converter namespace exists: `ipfs_datasets_py.processors.file_converter`
  - Legacy `ipfs_datasets_py.file_converter` exists as a lazy shim emitting `DeprecationWarning`.
- Canonical IPFS formats namespace exists: `ipfs_datasets_py.data_transformation.ipfs_formats`
  - Legacy `ipfs_datasets_py.ipfs_formats` exists as a deprecated import path.
- Canonical IPLD namespace exists: `ipfs_datasets_py.data_transformation.ipld`
  - Current canonical modules are still *re-export shims* to `ipfs_datasets_py.ipld.*`.

This plan focuses on the next step: **physically moving implementations** into canonical packages, then flipping legacy packages into pure shims.

---

## Proposed canonical layout

### 1) IPLD + Formats (data transformation)
- Canonical:
  - `ipfs_datasets_py.data_transformation.ipld.*`
  - `ipfs_datasets_py.data_transformation.ipfs_formats.*`

### 2) File conversion (processors)
- Canonical:
  - `ipfs_datasets_py.processors.file_converter.*`

### 3) GraphRAG integrations (RAG/processors)
The current codebase already has both `ipfs_datasets_py.graphrag/` and `ipfs_datasets_py.rag/`.

Default recommendation for this repo:
- Put GraphRAG-specific integration glue into `ipfs_datasets_py.graphrag.integrations.*`
- Keep generic RAG utilities in `ipfs_datasets_py.rag.*`

Rationale: the legacy folder is named `integrations/` but its contents are almost entirely GraphRAG-related (plus UnixFS), so `graphrag/` is the natural “owner”.

---

## File-by-file mapping

### A) `ipfs_datasets_py/ipfs_formats/*` → `ipfs_datasets_py/data_transformation/ipfs_formats/*`

| Current | Canonical target | Legacy outcome |
|---|---|---|
| `ipfs_formats/ipfs_multiformats.py` | `data_transformation/ipfs_formats/ipfs_multiformats.py` | replace with shim importing canonical |
| `ipfs_formats/__init__.py` | `data_transformation/ipfs_formats/__init__.py` | keep minimal; legacy `ipfs_formats/__init__.py` becomes shim |

Notes:
- There is also a top-level `ipfs_multiformats.py` module in the package root; decide whether it becomes:
  - a shim to the canonical module, or
  - the canonical module itself, with `ipfs_formats/ipfs_multiformats.py` shimming to it.

Recommendation: **canonicalize under `data_transformation/ipfs_formats/`** and make both legacy entrypoints shims.

Implementation note:
- Make legacy `ipfs_formats/__init__.py` lazy (optional) so it doesn’t eagerly import `multiformats` at import time.

### B) `ipfs_datasets_py/ipld/*` → `ipfs_datasets_py/data_transformation/ipld/*`

| Current | Canonical target | Legacy outcome |
|---|---|---|
| `ipld/storage.py` | `data_transformation/ipld/storage.py` | legacy re-exports canonical |
| `ipld/dag_pb.py` | `data_transformation/ipld/dag_pb.py` | legacy re-exports canonical |
| `ipld/optimized_codec.py` | `data_transformation/ipld/optimized_codec.py` | legacy re-exports canonical |
| `ipld/__init__.py` | `data_transformation/ipld/__init__.py` | legacy becomes lazy shim |

New: move the remaining IPLD implementation modules:

| Current | Canonical target | Legacy outcome |
|---|---|---|
| `ipld/vector_store.py` | `vector_stores/ipld.py` (or `vector_stores/ipld_vector_store.py`) | legacy shim re-export |
| `ipld/knowledge_graph.py` | `knowledge_graphs/ipld.py` (or `knowledge_graphs/ipld_knowledge_graph.py`) | legacy shim re-export |
| `ipld/storage_stubs.md`, etc. | `docs/` (keep docs) | no runtime impact |

Additionally split “feature” modules out of IPLD:

| Current | Canonical target | Legacy outcome |
|---|---|---|
| `ipld/vector_store.py` | `vector_stores/ipld_vector_store.py` (or `vector_stores/ipld.py`) | legacy shim re-export |
| `ipld/knowledge_graph.py` | `knowledge_graphs/ipld_knowledge_graph.py` (or `knowledge_graphs/ipld.py`) | legacy shim re-export |

Rationale:
- `ipld/` should represent IPLD primitives/codecs/storage; vector stores and knowledge graphs are higher-level.

Import-safety constraints:
- `vector_store` can pull in heavy deps (numpy/faiss/etc). Ensure `ipfs_datasets_py.data_transformation.ipld` stays import-safe by keeping those imports optional/lazy.

### C) `ipfs_datasets_py/integrations/*` → `ipfs_datasets_py/rag/integrations/*`

Revised canonical target (preferred): `ipfs_datasets_py.graphrag.integrations/*`

| Current | Canonical target | Legacy outcome |
|---|---|---|
| `integrations/graphrag_integration.py` | `graphrag/integrations/graphrag_integration.py` | shim |
| `integrations/enhanced_graphrag_integration.py` | `graphrag/integrations/enhanced_graphrag_integration.py` | shim |
| `integrations/phase7_complete_integration.py` | `graphrag/integrations/phase7_complete_integration.py` | shim |
| `integrations/unixfs_integration.py` | `data_transformation/ipld/unixfs_integration.py` | shim |
| `integrations/__init__.py` | `graphrag/integrations/__init__.py` | legacy shim; avoid `import *` |

Notes:
- Prefer `integrations/__init__.py` to be **minimal** (no wildcard imports); expose only stable symbols.
- Any “phase 7” / “advanced” integrations should be **optional** and import-safe.

### D) `ipfs_datasets_py/file_converter/*` → `ipfs_datasets_py/processors/file_converter/*`

Physical move plan (keep filenames stable to reduce churn):

| Current | Canonical target | Legacy outcome |
|---|---|---|
| `file_converter/converter.py` | `processors/file_converter/converter.py` | legacy shim maps `FileConverter`/`ConversionResult` |
| `file_converter/pipeline.py` | `processors/file_converter/pipeline.py` | legacy shim maps pipeline symbols |
| `file_converter/errors.py` | `processors/file_converter/errors.py` | legacy shim |
| `file_converter/format_detector.py` | `processors/file_converter/format_detector.py` | legacy shim |
| `file_converter/text_extractors.py` | `processors/file_converter/text_extractors.py` | legacy shim |
| `file_converter/metadata_extractor.py` | `processors/file_converter/metadata_extractor.py` | legacy shim |
| `file_converter/batch_processor.py` | `processors/file_converter/batch_processor.py` | legacy shim |
| `file_converter/ipfs_accelerate_converter.py` | `processors/file_converter/ipfs_accelerate_converter.py` | legacy shim |
| `file_converter/knowledge_graph_integration.py` | `processors/file_converter/knowledge_graph_integration.py` | legacy shim |
| `file_converter/vector_embedding_integration.py` | `processors/file_converter/vector_embedding_integration.py` | legacy shim |
| `file_converter/archive_handler.py` | `processors/file_converter/archive_handler.py` | legacy shim |
| `file_converter/url_handler.py` | `processors/file_converter/url_handler.py` | legacy shim |
| `file_converter/office_format_extractors.py` | `processors/file_converter/office_format_extractors.py` | legacy shim |
| `file_converter/exports.py` | `processors/file_converter/exports.py` | legacy shim |
| `file_converter/cli.py` | `cli/file_converter.py` (optional) OR keep at `processors/file_converter/cli.py` | keep backward compatible entrypoint |
| `file_converter/backends/*` | `processors/file_converter/backends/*` | legacy shim |

Exports policy (important):
- Canonical `processors.file_converter` should have:
  - `FileConverter`, `ConversionResult`
  - top-level helper functions (`convert_file`, etc.)
  - minimal + intentional `__all__`
- Legacy `file_converter/__init__.py` becomes a shim that re-exports the canonical surface (and emits `DeprecationWarning`).

---

## Migration mechanics (how to implement safely)

### Phase 0 — Baseline + guardrails
- Add/keep a small “import-walk” sanity check (can be a script or a light pytest) that imports:
  - canonical modules
  - legacy shims
- Ensure optional deps are handled via `try/except ModuleNotFoundError`.

### Phase 1 — IPFS formats (already canonical, refine shims)
1. Ensure `data_transformation/ipfs_formats/` remains the only implementation.
2. Convert legacy `ipfs_formats/` to a lazy shim (no eager imports).
3. Ensure root-level helpers (e.g. `ipfs_multiformats.py` if used) re-export canonical.

### Phase 2 — IPLD primitives (flip direction: canonical becomes implementation)
1. Copy/move real implementations from `ipld/` into `data_transformation/ipld/`.
2. Update imports inside those modules to use canonical paths.
3. Turn legacy `ipld/` into a lazy shim package that re-exports canonical.
4. Split higher-level modules:
  - Move `ipld/vector_store.py` → `vector_stores/ipld.py`
  - Move `ipld/knowledge_graph.py` → `knowledge_graphs/ipld.py`
  - Keep re-exports from `data_transformation/ipld/` only if you want one-stop imports.
5. Run: import-walk + targeted IPLD tests.

### Phase 3 — Move GraphRAG + UnixFS integrations
1. Create `graphrag/integrations/`.
2. Move GraphRAG integration modules from legacy `integrations/` into it.
3. Move `unixfs_integration.py` into `data_transformation/ipld/` (UnixFS is IPLD/DAG-PB adjacent).
4. Replace legacy `integrations/` with a lazy shim (no `import *`).
5. Run: GraphRAG import + smoke execution tests.

### Phase 4 — Move file_converter implementation (physical move)
1. Move the implementation files from `file_converter/` into `processors/file_converter/`.
2. Fix internal imports to use canonical package paths.
3. Keep legacy `file_converter/` as a lazy shim package pointing at canonical.
4. Run: conversion unit tests, import safety checks, MCP tool imports.

### Phase 5 — Reduce package exposure
- Update `ipfs_datasets_py/__init__.py` to export fewer symbols.
- Remove wildcard exports from legacy `__init__.py` modules.
- Document canonical import paths in docs.

Practical definition of “reduce exposure”:
- Keep top-level packages as *internal implementation details* unless they represent major product domains.
- Prefer a small set of canonical domains:
  - `data_transformation.*`
  - `processors.*`
  - `graphrag.*`
  - `rag.*`
  - `knowledge_graphs.*`
  - `vector_stores.*`

---

## Deprecation policy
- Emit `DeprecationWarning` from legacy modules:
  - message includes canonical path and a removal target version.
- Keep shims for at least 2 minor releases (or 90 days), whichever fits your release process.

Deprecation implementation guidance:
- Prefer lazy `__getattr__` shims and avoid `from ... import *` in legacy packages.
- Suppress deprecation warnings *inside* canonical modules when they temporarily import legacy implementations.

---

## Validation checklist
- Import stability:
  - `python -c "import ipfs_datasets_py"`
  - `python -c "import ipfs_datasets_py.file_converter"` (shim)
  - `python -c "import ipfs_datasets_py.processors.file_converter"` (canonical)
- Pytest slices:
  - file conversion tests
  - IPLD serialization/provenance tests
  - GraphRAG processor tests
- Ensure no internal imports still point to legacy paths (except in shims).

---

## Open decisions (pick defaults if not specified)
1. Canonical home for CID/multiformats:
   - Default in this plan: `data_transformation/ipfs_formats/ipfs_multiformats.py`
2. Canonical home for GraphRAG integrations:
  - Default in this plan: `graphrag/integrations/*`
3. Removal timeline for shims:
   - Default: 2 minor releases

4. Clarification: canonical folder name:
  - Confirmed: `data_transformation/` (singular).
