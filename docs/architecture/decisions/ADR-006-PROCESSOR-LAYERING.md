# ADR-006: Processor Layering (Root / Core Transition)

| Field | Value |
| --- | --- |
| Interface | `ProcessorLayeringDecision@1` |
| Task | `IPFSDOC-015` |
| Status | accepted |
| Date proposed | 2026-08-03 |
| Date accepted | 2026-08-03 |
| Decision owners | architecture; processors maintainers |
| Consulted | documentation-governance; MCP engine-extraction authors |
| Source of truth | `ipfs_datasets_py/processors/core/`; `ipfs_datasets_py/processors/__init__.py`; `ipfs_datasets_py/processors/registry.py` (deprecation shim); `ipfs_datasets_py/processors/adapters/`; `ipfs_datasets_py/processors/specialized/`; `ipfs_datasets_py/processors/engines/`; package ADR-004; `docs/guides/processors/PROCESSORS_ARCHITECTURE.md` (exposition, mixed-layout note) |
| Last verified | 2026-08-03 |
| Supersedes | none |
| Superseded by | none |
| Origin | Observed mixed root/core layout; engine extraction (package ADR-004); unified processor protocol work |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

The `processors` domain is the largest first-level package by Python file count
(~974 `*.py` in baseline evidence) and owns multimodal and domain processing
([DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.1). Refactoring introduced a **layered**
layout under `processors/core/`, `infrastructure/`, `adapters/`, `specialized/`,
and `engines/`, while **root-level** modules under `ipfs_datasets_py/processors/`
remain part of the public surface.

Observed coexistence (current tree, not aspirational):

| Concern | Root (package `processors/`) | Core / layered |
| --- | --- | --- |
| Protocol types | `protocol.py` (~480 lines) | `core/protocol.py` (~370 lines) — related but not a byte-identical twin |
| Registry | `registry.py` — **deprecated shim** → `core.registry` | `core/registry.py` — consolidated SoT; `core/processor_registry.py` still imported by some core paths |
| Universal entry | `universal_processor.py` | `core/universal_processor.py` |
| Input detection | `input_detection.py` | `core/input_detector.py` |
| Package exports | `__init__.py` re-exports protocol from root and registry from **core** | `core/__init__.py` documents dual surfaces |

Guide material already states production status as **mixed root/core layout**
(`docs/guides/processors/PROCESSORS_ARCHITECTURE.md`). Presenting a pure
five-layer diagram without this transitional reality misleads agents into
“cleaning up” by deleting live imports or inventing a second registry.

Package ADR-004 places many **engines** under `processors.*` and related
domains; this ADR covers **layering and import authority** inside the
processors package during the strangler, complementary to
[ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md).

## Decision

We will document and enforce a **strangler-style processor layering** in which:

1. **`processors.core`** is the preferred home for unified protocol, registry,
   and core universal-processor contracts for **new** layered work.
2. **Root-level modules** remain a **compatibility and public convenience**
   surface until call sites migrate; they are not a second design authority.
3. **Domain engines and specialized packages** own algorithms; **adapters**
   bridge them to `ProcessorProtocol` and register into the canonical registry.
4. Documentation must describe the **mixed** layout honestly and must not treat
   an idealized clean tree as already shipped.

### Decision details

#### Layer dependency direction (normative for new code)

```text
  [ MCP / CLI / library callers ]
              │
              ▼
  root package surface (compat + convenience re-exports)
              │
              ▼
  adapters  ──►  specialized / engines / domain subpackages
              │
              ▼
  infrastructure (caching, retry, monitoring helpers)
              │
              ▼
  core (protocol, registry, core universal processor, input detector)
```

| Layer | Path | May depend on | Must not |
| --- | --- | --- | --- |
| **Core** | `processors/core/` | stdlib, typing, anyio-class primitives | Import specialized processors, MCP, adapters |
| **Infrastructure** | `processors/infrastructure/` | core | Import specialized domain logic as required deps |
| **Specialized / engines** | `processors/specialized/`, `engines/`, legal_scrapers, multimedia, … | core (+ infrastructure as needed) | Import MCP tool modules for algorithms |
| **Adapters** | `processors/adapters/` | core + specialized/engines | Own long-lived business logic copies |
| **Root surface** | `processors/*.py`, `__init__.py` | core and domain packages | Become a second registry or protocol authority |

#### Canonical vs compatibility imports

| Symbol / concern | Canonical (new work) | Compatibility / transitional |
| --- | --- | --- |
| `ProcessorRegistry`, `get_global_registry` | `ipfs_datasets_py.processors.core.registry` | `ipfs_datasets_py.processors.registry` (deprecation warning; re-export) |
| Core package facade | `ipfs_datasets_py.processors.core` | Root `__init__` selective re-exports |
| Specialized PDF engine | `processors.specialized.pdf` (and related) | Older import paths via adapters/fallbacks |
| Engine placement by domain | package ADR-004 table | MCP tool paths as 3–15 line shims only |

`processors/core/__init__.py` itself notes that `processor_registry.py` remains
in tree and is still imported by some infrastructure/core modules while
`registry.py` is the newer consolidated surface. That internal dual is
**transitional debt**, not two permanent equal authorities: new registration
APIs should converge on `core.registry` / `get_global_registry` as exported by
core.

#### Root modules that still carry weight

Root files such as `universal_processor.py`, `input_detection.py`,
`protocol.py`, `graphrag_processor.py`, and domain entry modules remain
**real code paths**. Rules:

1. Prefer **extending** specialized/core packages rather than growing new
   monolithic root modules.
2. When root and core both define analogous types, **do not** silently fork
   semantics; align or deprecate with warnings (as `registry.py` does).
3. Package `__init__.py` stays **lightweight** (optional import guards) so
   minimal environments do not pull the full graph.

#### Relationship to engines (package ADR-004)

Engine extraction remains binding:

- Business logic lives in `*_engine` modules or specialized packages.
- MCP tools and CLI wrappers stay thin.
- This ADR does not relocate engines; it constrains **which processor layer**
  may own contracts vs implementations during the mixed layout.

## Alternatives considered

| Alternative | Pros | Cons | Why not chosen |
| --- | --- | --- | --- |
| Pretend pure five-layer architecture already | Clean diagrams | False; breaks imports; agents “fix” live paths | Rejected |
| Freeze all new code at root only | Least migration | Undoes core/registry consolidation | Rejected |
| Big-bang delete root modules now | Ends dual SoT | High breakage; not this program’s scope | Deferred (code task with deprecation calendar) |
| Dual permanent registries (root + core) | Isolates refactors | Violates ADR-005; name/policy drift | Rejected |
| Do nothing (no ADR) | Zero doc cost | Guides and agents disagree on SoT | Rejected |

## Consequences

### Positive

- New work has a clear default: core contracts, specialized/engines algorithms,
  adapters for protocol conformance.
- Strangler shims keep old imports working with explicit deprecation.
- Documentation matches production (mixed layout) instead of aspirational clean
  architecture.

### Negative

- Two protocol modules and two universal-processor modules increase cognitive
  load until consolidation finishes.
- Import path mistakes are easy (`processors.registry` vs `core.registry`).
- Some root modules still import core registry while defining their own protocol
  surface—reviewers must watch for type mismatches.

### Neutral / deferred

- **Strangler / deprecation consequences:**
  - `processors.registry` warns and targets removal in v2.0.0 (August 2026 era
    per shim text); callers must migrate to `core.registry`.
  - Root `protocol.py` / `universal_processor.py` / `input_detection.py` vs
    core counterparts: migration is incremental; no silent dual feature adds.
  - `core.processor_registry` vs `core.registry`: treat consolidated
    `registry.py` as the registration SoT for new adapters; do not expand the
    alternate without a superseding decision.
- Full tree cleanup, test rewiring, and guide rewrite of
  `docs/guides/processors/*` are out of this ADR’s edit scope.
- Multimedia submodule deprecations and file-converter native backends are
  adjacent product history (`docs/architecture/submodule_deprecation.md`);
  they do not redefine processor layer ownership.

## Invariants

Rules that remain true while this ADR is `accepted`:

1. New unified-system processors and adapters register with
   `processors.core.registry` (or APIs that re-export it without forking).
2. Core must not import specialized/adapters/MCP for its contract definitions.
3. Domain algorithms live in specialized/engines/domain packages—not in MCP
   tools and not as permanent copies inside adapters.
4. Documentation of processors must label root modules as compatibility or
   transitional when they duplicate core concerns—not as a second architecture.
5. Deprecation shims may re-export; they must not implement divergent registry
   policy.

Violating an invariant requires a new ADR (or explicit supersession), not a
quiet code change.

## Compliance and validation

```bash
# Deprecation shim points at core (must remain true until removed)
rg -n "deprecated|core\.registry|DeprecationWarning" \
  ipfs_datasets_py/processors/registry.py

# Public package pulls registry from core
rg -n "from \.core\.registry|ProcessorRegistry" \
  ipfs_datasets_py/processors/__init__.py

# Core documents dual residual modules honestly
rg -n "processor_registry|compatibility|root-level" \
  ipfs_datasets_py/processors/core/__init__.py

# Adapters target protocol + core registry registration path
rg -n "ProcessorProtocol|get_global_registry|core" \
  ipfs_datasets_py/processors/adapters/auto_register.py

# Layer presence (structural smoke)
test -d ipfs_datasets_py/processors/core
test -d ipfs_datasets_py/processors/adapters
test -d ipfs_datasets_py/processors/specialized
test -s ipfs_datasets_py/processors/core/registry.py
```

Narrative compliance criteria:

1. Architecture guides that show only `core/` without mentioning root
   coexistence are incomplete for current state.
2. New features do not add a third registry module for the same concern.
3. Engine locations continue to follow package ADR-004 for extracted logic.
4. Preferred library entry points for PDF and similar remain domain/specialized
   APIs (see [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md)), with
   adapters as protocol bridges.

## Scope

### Applies to

- `ipfs_datasets_py/processors/` package layout and import authority.
- Processor-facing documentation under architecture and processor guides.
- Interaction with MCP thin wrappers that call processor engines.

### Does not apply to

- Non-processor domains (`logic`, `embeddings`, `vector_stores`) except where
  they consume processor APIs.
- Choosing HTTP vs stdio MCP runtime ([ADR-007](ADR-007-MCP-RUNTIME-COMPATIBILITY.md)).
- Deleting or rewriting production modules as part of this documentation task.

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| [ADR-005-REGISTRIES-AND-ADAPTERS.md](ADR-005-REGISTRIES-AND-ADAPTERS.md) | Registry/adapter SoT rules |
| [ADR-007-MCP-RUNTIME-COMPATIBILITY.md](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | How MCP hosts call processors |
| Package ADR-004 engine extraction | Canonical engine placement |
| Package ADR-001 thin wrapper | MCP side of engine calls |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.1 | Domain ownership of processors |
| `docs/guides/processors/PROCESSORS_ARCHITECTURE.md` | Layer exposition (mixed layout) |
| `processors/registry.py` | Deprecation shim evidence |
| `processors/core/registry.py` | Consolidated registry SoT |

## Notes / errata

- **2026-08-03:** Global ADR-006 is **not** package-local MCP ADR-006
  (MCP++ alignment). Different trees, different decisions; IPFSDOC-016 indexes both.
- Evidence of dual `protocol.py` sizes is for layout honesty, not a claim that
  one file is fully superseded yet.

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Proposed and accepted as IPFSDOC-015 artifact (`ProcessorLayeringDecision@1`) |
