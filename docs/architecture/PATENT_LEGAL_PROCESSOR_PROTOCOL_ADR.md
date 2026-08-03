# ADR: Canonical processor protocol for patent legal intelligence

- Status: accepted
- Date: 2026-08-03
- Owners: patent-legal-intelligence / processor-runtime
- Objectives: PATLAW-G011, enables PATLAW-003 and Wave 0 foundation
- Task: PATLAW-002

## Context

Patent legal intelligence processors must share one registration, discovery,
capability-check, execution, and result-conversion contract so USPTO, PDF,
authority, and compliance modules can compose without silent empty routing or
runtime type failures.

The repository currently exposes two incompatible generic processor APIs:

1. **Legacy surface** — `ipfs_datasets_py/processors/protocol.py`
   - Dispatch: `can_process(input_source: str | Path) -> bool`
   - Execution: `process(input_source, **options) -> ProcessingResult`
   - Capability listing: `get_supported_types() -> list[str]`
   - Optional: `get_priority()`, `get_name()`
   - Result: structured `KnowledgeGraph` / `VectorStore` / `content` /
     `ProcessingMetadata` (status enum, no top-level `success` bool)
   - `InputType`: `url`, `file`, `folder`, `ipfs`, `text`, `binary`, `unknown`
   - Protocol is `@runtime_checkable`
   - Used by root `UniversalProcessor`, `processors.adapters.*` (e.g. PDF), and
     package-level `from ipfs_datasets_py.processors import ProcessorProtocol`

2. **Core surface** — `ipfs_datasets_py/processors/core/protocol.py`
   - Dispatch: `can_handle(context: ProcessingContext) -> bool` (async)
   - Execution: `process(context: ProcessingContext) -> ProcessingResult` (async)
   - Capability map: `get_capabilities() -> dict`
   - Result: flat `success`, dict `knowledge_graph`, list `vectors`, dict
     `metadata`, `errors`, `warnings`, optional `raw_output`
   - `InputType`: `url`, `file`, `folder`, `text`, `binary`, `ipfs_cid`, `ipns`
     (no `unknown` / no bare `ipfs`)
   - Carries `ProcessingContext` (type, source, metadata, options, session)
   - Paired with `processors.core.registry.ProcessorRegistry` and
     `processors.core.universal_processor.UniversalProcessor`
   - `is_processor()` requires **async** `can_handle` and `process`

These contracts are not interchangeable:

| Concern | Legacy | Core (canonical) |
| --- | --- | --- |
| Selection method | `can_process(source)` | `can_handle(ProcessingContext)` |
| Process signature | bare source + kwargs | single context object |
| Result success model | `metadata.status` enum | `success: bool` + `errors` |
| Knowledge graph | typed `Entity` / `Relationship` | dict with `entities` / `relationships` |
| Vectors | `VectorStore` mapping | `list[list[float]]` |
| IPFS input enum | `ipfs` | `ipfs_cid`, `ipns` |
| Runtime checkable | yes (`@runtime_checkable`) | no (structural / `is_processor`) |
| Public package default | yes (`processors.__init__`) | via `processors.core` |

### Observed mixed-routing failure modes

The package root currently **mixes** the two surfaces:

- `ipfs_datasets_py.processors` re-exports legacy `ProcessorProtocol` /
  `ProcessingResult` while re-exporting `ProcessorRegistry` from
  `processors.core.registry`.
- Root `UniversalProcessor` types against the legacy protocol but constructs
  the core registry.
- Core registry registration uses `isinstance(processor, ProcessorProtocol)`
  against the non-runtime-checkable core protocol, which raises `TypeError`
  before any processor is stored.
- When selection falls through, legacy processors lack `can_handle`; core
  selection may match nothing and return an empty processor set without a clear
  contract error.
- Calling a legacy adapter with a `ProcessingContext` (or a core processor with
  a bare path) fails at the call boundary or yields an unusable result shape.

Wallet-domain work already selected the core protocol as the sole generic
adapter target (`docs/architecture/WALLET_PROCESSOR_PROTOCOL_ADR.md`). Patent
legal intelligence adopts the same generic runtime so domain packages do not
fork a third contract.

## Decision

### Canonical runtime

**`ipfs_datasets_py.processors.core.protocol` is the single canonical generic
processor runtime** for patent legal intelligence and for all new generic
routing (registry, UniversalProcessor, domain adapters that join the unified
pipeline).

Canonical symbols:

- `ProcessorProtocol` — async `can_handle` / `process`, sync `get_capabilities`
- `ProcessingContext` — required dispatch/execution carrier
- `ProcessingResult` — `success`-centered flat result
- `InputType` — core enum values above
- `is_processor` — structural async conformance helper

Canonical orchestration modules (owned by follow-on PATLAW-003):

- `ipfs_datasets_py.processors.core.registry.ProcessorRegistry`
- `ipfs_datasets_py.processors.core.universal_processor.UniversalProcessor`
- `ipfs_datasets_py.processors.core.processor_registry` (merge/deprecate into
  the single registry surface; no dual live routers)

New patent/USPTO processors implement the **core** protocol (or a domain
protocol that is adapted **once** into core), never the legacy
`can_process` surface.

### Explicit legacy compatibility (not deletion)

The legacy module `ipfs_datasets_py.processors.protocol` remains a **supported
public import** for existing callers and adapters. It is not the canonical
runtime.

Compatibility rules:

1. **No implicit mixed routing.** A registry or UniversalProcessor must not
   treat a legacy-shaped object as a core processor (or vice versa) by duck-typing
   both APIs in one selection loop without an explicit adapter instance.
2. **One explicit adapter direction.** Legacy → core only, at:
   `ipfs_datasets_py/processors/adapters/legacy_protocol_adapter.py`
   (introduced by PATLAW-003). The adapter implements core
   `ProcessorProtocol` and **delegates** to a legacy `can_process` /
   `process` implementer.
3. **No dual registration** of the same logical processor under both APIs.
4. **No adapter** that re-exposes core processors as the primary legacy
   registry contract for new work. Root package re-exports may continue to
   expose legacy names for import stability.
5. **Result conversion** is mandatory at the adapter boundary:

   | Legacy field | Core `ProcessingResult` |
   | --- | --- |
   | `metadata.status in {SUCCESS, PARTIAL}` | `success=True` (PARTIAL may add warnings) |
   | `metadata.status == FAILED` | `success=False` |
   | `metadata.errors` | `errors` |
   | `metadata.warnings` | `warnings` |
   | `knowledge_graph.to_dict()` or equivalent | `knowledge_graph` dict |
   | ordered vector values from `VectorStore` | `vectors` list |
   | `content` + legacy metadata | `metadata` / `raw_output` as needed |

6. **InputType mapping** at the adapter boundary:

   | Legacy | Core |
   | --- | --- |
   | `url` | `url` |
   | `file` | `file` |
   | `folder` | `folder` |
   | `text` | `text` |
   | `binary` | `binary` |
   | `ipfs` | `ipfs_cid` |
   | `unknown` | require detector metadata; do not invent a core enum value |

7. **Supported public imports are preserved.** Package-level imports such as
   `from ipfs_datasets_py.processors import ProcessorProtocol, UniversalProcessor,
   ProcessorRegistry, ProcessingResult, InputType, …` must continue to resolve.
   Core-canonical imports remain available via
   `from ipfs_datasets_py.processors.core import …`. Deprecation of the legacy
   *semantics as the runtime contract* is documentation- and adapter-driven;
   symbols are not deleted in this decision.

### Conformance tests

Executable contract tests own the acceptance criteria for this ADR:

- `tests/unit/processors/core/test_protocol_unification.py` — inventories shape
  incompatibilities, proves implicit mixed routing fails, and defines adapter
  conversion behavior.
- `tests/integration/processors/test_public_processor_surface.py` — freezes
  supported public import surfaces without requiring deletion of legacy names.

## Consequences

- Wave 0 USPTO/PDF/compliance work programs against one async context-carrying
  contract with a single success/error result shape.
- PATLAW-003 can consolidate registries and UniversalProcessor without
  re-litigating which protocol wins.
- Existing legacy adapters keep working only through the explicit legacy→core
  adapter (or remain on isolated legacy call sites that never enter the
  canonical router).
- `isinstance(..., core.ProcessorProtocol)` must not be the sole registration
  gate until the core protocol is `@runtime_checkable` **or** registration uses
  `is_processor` / explicit adapter types (PATLAW-003 repair).
- Domain packages (wallet, USPTO) share the same generic adapter target.

## Rejected alternatives

### Keep dual registries and dual UniversalProcessors indefinitely

Rejected: mixed routing already produces empty discovery and `isinstance`
failures; dual live routers make order and result shape observable and unsafe
for confidential patent material.

### Make legacy `can_process` the canonical runtime

Rejected: bare-source dispatch cannot carry session, classification metadata,
privacy options, or structured input type without out-of-band conventions.
Core `ProcessingContext` is required for patent privacy and provenance gates.

### Delete legacy public imports in this change

Rejected: supported public imports and existing adapters still bind the legacy
module. Compatibility is explicit adaptation, not hard removal. Deletion may
only follow a later deprecation window after callers migrate.

### Auto-duck-type both APIs inside one selection loop

Rejected: that is “implicit mixed routing.” It hides which contract ran,
prevents deterministic tests, and recreates the silent empty-set failure mode.

## Verification

```text
python -m pytest \
  tests/unit/processors/core/test_protocol_unification.py \
  tests/integration/processors/test_public_processor_surface.py -q
```

Follow-on PATLAW-003 must keep these tests green while consolidating registry
and UniversalProcessor routing through the canonical core protocol and the
single legacy adapter.
