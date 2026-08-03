# ADR-002: Lazy Optional Capabilities

| Field | Value |
| --- | --- |
| Interface | `LazyCapabilityDecision@1` |
| Task | `IPFSDOC-013` |
| Status | accepted |
| Date proposed | 2026-08-03 |
| Date accepted | 2026-08-03 |
| Decision owners | architecture |
| Consulted | documentation-governance; packaging; logic/prover maintainers; MCP operators |
| Source of truth | `ipfs_datasets_py/__init__.py`; `ipfs_datasets_py/router_deps.py`; `ipfs_datasets_py/auto_installer.py`; `ipfs_datasets_py/dependency_catalog.py`; `ipfs_datasets_py/lazy_dependencies.py`; `ipfs_datasets_py/logic/common/feature_detection.py`; `ipfs_datasets_py/logic/external_provers/lazy_installer.py`; `ipfs_datasets_py/ipfs_backend_router.py`; `pyproject.toml` / `setup.py` extras; [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) |
| Last verified | 2026-08-03 |
| Supersedes | none |
| Superseded by | none |
| Origin | Cross-cutting product decision distilled from hermetic import, lazy install, capability probe, and router contracts (`IPFSDOC-G032`; guide evidence from `IPFSDOC-012`) |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

The full `ipfs_datasets_py` surface—MCP, FastAPI, transformers/LLM stacks,
vector stores, theorem provers, multimedia converters, `ipfs_kit_py` /
`ipfs_accelerate_py` backends—is far larger than a safe default import. Forcing
every optional stack at import time would:

1. **Break hermetic CI and benchmarks** with long installs, network use, and
   missing extras.
2. **Punish library embeds** that only need a narrow domain API.
3. **Collapse discovery into capability** so that “importable” or “probed”
   is mistaken for production readiness, authorization, or proof.
4. **Hide trust failures** behind soft fallbacks if missing validators or
   provers were treated like missing optional image codecs.

Current tree evidence already separates lifecycle phases:

- **Hermetic package import** — `ipfs_datasets_py/__init__.py` defaults
  auto-install env when unset but skips eager MCP/FastAPI/LLM/finance stacks
  unless `IPFS_DATASETS_PY_ENABLE_*` flags (or related) are set; minimal mode via
  `IPFS_DATASETS_PY_MINIMAL_IMPORTS` / `IPFS_DATASETS_PY_BENCHMARK`.
- **Explicit process wiring** — `initialize(...)` and injectable `RouterDeps`
  share accelerate managers, IPFS backends, and caches without re-constructing
  clients at every call site.
- **Declarative dependency catalog** — `dependency_catalog.DependencySpec` maps
  import names to distributions and component tags.
- **Lazy Python modules** — `lazy_dependencies.LazyDependencyProxy` and
  `auto_installer.ensure_module` resolve on first use; construction of the
  proxy does not import third parties.
- **Capability probes without import** — `feature_detection.is_module_available`
  uses `importlib.util.find_spec` only; respects minimal imports.
- **Native prover lazy install** — `logic/external_provers/lazy_installer.py`
  may install on first *execution* when env allows; import of the provers
  package never downloads a solver. Managed CLI:
  `ipfs-datasets-install-provers`.
- **Router selection** — `ipfs_backend_router` and accelerator aliases choose
  backends from env + `RouterDeps`; missing backends degrade features, not
  identity rules.

Forces: Python 3.12+ packaging with many extras; offline/wheelhouse installs;
operator policy against surprise `pip` or sudo; agent/MCP hosts that must start
quickly; security-critical paths (admissibility, proof, side effects) that must
**fail closed** when evidence is missing
([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) kinds of truth;
[DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) §9).

Related but distinct: content identity and provenance
([ADR-001](ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md)) define *what* artifacts
are; this ADR defines *when and how* optional software capabilities become
available without rewriting identity or trust rules.

## Decision

We will keep **optional capabilities lazy and opt-in**: package import stays
hermetic by default; heavy stacks and native tools resolve on **explicit
initialize**, **first real use**, or **managed preflight install**. We will
distinguish **feature degradation** (availability) from **fail-closed trust**
(authorization, proof, identity integrity, side-effect dispatch).

### Decision details

1. **Hermetic import is the default contract.** Importing `ipfs_datasets_py`
   (or narrow submodules under minimal mode) must not require MCP, FastAPI,
   transformers, finance dashboards, or native prover downloads. Missing
   optional stacks do not fail package import.
2. **Opt-in for heavy import-time surfaces.** Flags such as
   `IPFS_DATASETS_PY_ENABLE_MCP_IMPORTS`,
   `IPFS_DATASETS_PY_ENABLE_FASTAPI_IMPORTS`,
   `IPFS_DATASETS_PY_ENABLE_LLM_IMPORTS`,
   `IPFS_DATASETS_PY_ENABLE_FINANCE_DASHBOARD_IMPORTS` gate eager paths.
   Minimal/benchmark modes force installer-off and hermetic behavior.
3. **`initialize()` is the explicit shared-wiring point.** Process-wide
   `RouterDeps` (injected or default) own reusable clients; import is not a
   substitute for initialize.
4. **Lazy resolution at feature boundaries.** Prefer `ensure_module` /
   `LazyDependencyProxy` / router factories on first use. Dependency catalog
   supplies distribution names so runtime install (when allowed) does not guess.
5. **Probes ≠ installs ≠ capabilities ≠ authority.**
   - **Probe** (`find_spec`, status helpers): importability / environment
     evidence only; probes do not install.
   - **Lazy install** (Python or native prover): may run on first use when env
     policy allows; may be disabled for offline, CI, or strict policy.
   - **Capability**: a successful operation or verified demonstration under
     stated conditions—not a green probe alone.
   - **Authorization / proof**: independent gates; never implied by install or
     probe success.
6. **Graceful feature degradation is allowed** for optional compute, media,
   backends, scrapers, and best-effort helpers (soft-disable, local fallback,
   clear unavailable status).
7. **Fail-closed trust is required** for authorization, admissibility, proof
   attestation, identity integrity, and side-effect dispatch. Missing proof is
   not success; missing validator is not allow; empty submodules are not
   capability evidence.
8. **Identifiers and capability evidence stay separate.** Content CIDs,
   provenance ids, install receipts, and capability probes are different truth
   kinds. **A dependency name, probe result, install receipt, or CID is not a
   location guarantee, not an authorization, and not a proof**
   (see [ADR-001](ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) non-identity table
   and SOURCE_AUTHORITY §2).
9. **Operator controls remain first-class.** Auto-install, offline wheelhouse,
   per-prover lazy flags, strict installer modes, and explicit executable
   overrides are part of the decision surface—not afterthoughts. Reviewed
   packaging extras remain the preferred environment creation path; runtime
   install is a convenience under policy, not a substitute for declared extras
   in production images.
10. **Cross-repo backends stay optional and owned externally.**
    `ipfs_kit_py` / `ipfs_accelerate_py` integration is best-effort via routers
    and aliases; implementation authority for accelerate routers lives in
    accelerate. Empty git submodule directories are availability gaps.

## Alternatives considered

| Alternative | Pros | Cons | Why not chosen |
| --- | --- | --- | --- |
| Eager import of all extras at package load | Simple mental model | Breaks CI; huge import cost; fails without full platform | Rejected |
| Always-on runtime auto-install with no off switch | “It just works” demos | Policy/network surprises; non-reproducible environments; sudo risk | Rejected; controls and minimal mode required |
| No runtime install ever; extras only | Maximum purity | Poor DX for local first-use of optional tools | Softened: allow lazy install under env policy; prefer extras in prod |
| Probe success as production capability claim | Easy dashboards | False readiness; confuses discovery with proof/authz | Explicitly forbidden |
| Degrade trust gates when deps missing (fail-open) | Fewer user-visible errors | Unsafe; invalid proofs/authz | Rejected; fail closed on trust |
| Single monolith “capabilities” boolean | Simple API | Hides per-feature state and policy | Rejected; structured status and per-feature unavailability |

## Consequences

### Positive

- CI, benchmarks, and thin embeds can import the package safely.
- Operators control network, offline, and sudo behavior.
- Agents and docs can reason about discovery vs availability vs capability vs
  authorization without conflation.
- Routers reuse process clients via `RouterDeps`, reducing re-init cost.
- Theorem-prover and heavy ML stacks do not tax users who never call them.

### Negative

- First-use latency may include install or large imports when lazy paths run.
- Multiple env flags increase configuration surface area.
- Call sites must handle `None` / unavailable / strict exceptions consistently.
- Documentation must continually restate probe ≠ capability to avoid drift.

### Neutral / deferred

- Exact portfolio membership of managed provers evolves with packaging; this ADR
  fixes the *policy*, not every pin list.
- Fail-closed mediation patterns across all policy engines are expanded in later
  ADRs (`IPFSDOC-G032` layered authority / fail-closed degradation).
- MCP thin-wrapper and dual-runtime decisions remain package-local MCP ADRs.

## Invariants

Rules that remain true while this ADR is `accepted`:

1. **Python 3.12+** is the supported language floor for packaging and runtime.
2. **Package import stays hermetic** unless opt-in flags enable heavy stacks;
   minimal/benchmark modes disable auto-install and force hermetic behavior.
3. **`initialize()` is opt-in process wiring**; import alone is not full platform
   bootstrap.
4. **Lazy proxies do not import third parties at construction time.**
5. **Capability probes do not install** by themselves; first-use installers may,
   only when policy allows.
6. **Discovery is not capability; capability is not authorization; proof is not
   authorization.** Install receipts and probes are environment evidence only.
7. **Feature degradation must not weaken trust boundaries.** Soft-disable media
   or accelerate; never soft-allow side effects or treat missing proof as pass.
8. **Empty submodules and missing extras are availability issues**, not proof
   that a domain was removed from the product map.
9. **Native prover import never downloads a solver**; download/install is tied
   to execution or managed CLI.
10. **Identifiers (CIDs), locations, receipts, authorizations, and proofs remain
    distinct** under ADR-001; lazy capability machinery must not mint fake CIDs
    or promote install success to authz/proof.

Violating an invariant requires a new ADR (or explicit supersession), not a
quiet code change.

## Compliance and validation

```bash
# Hermetic / initialize surface
rg -n 'MINIMAL_IMPORTS|initialize|AUTO_INSTALL|ENABLE_MCP_IMPORTS' \
  ipfs_datasets_py/__init__.py

# Lazy proxy and catalog
rg -n 'class LazyDependencyProxy|ensure_module|DependencySpec' \
  ipfs_datasets_py/lazy_dependencies.py \
  ipfs_datasets_py/dependency_catalog.py \
  ipfs_datasets_py/auto_installer.py

# Probe without import
rg -n 'find_spec|is_module_available|minimal_imports_enabled' \
  ipfs_datasets_py/logic/common/feature_detection.py

# Prover lazy install boundary
rg -n 'LAZY_INSTALL|ensure_prover' \
  ipfs_datasets_py/logic/external_provers/lazy_installer.py

# Architecture guide still aligned
rg -n 'Discovery is not capability|fail-closed|graceful feature' \
  docs/architecture/DEPENDENCY_AND_INITIALIZATION.md
```

Narrative compliance criteria:

1. New optional dependencies are registered in the catalog (or equivalent) and
   resolved lazily at a feature boundary—not at package import.
2. Status APIs label probe results as availability/diagnostics, not production
   authorization.
3. Trust-sensitive paths document fail-closed behavior when deps are missing.
4. Guides do not claim “full platform ready” from a successful import or probe.

## Scope

### Applies to

- Package root import policy and env flags.
- `RouterDeps` / router backend selection.
- Auto-installer, dependency catalog, lazy proxies.
- Feature detection and accelerate/IPFS optional integrations.
- Native theorem-prover provisioning and managed installer CLI.
- Documentation of optional extras and degradation behavior.

### Does not apply to

- Algorithm design inside a domain once its dependencies are present.
- External ownership of kit/accelerate/prover upstream releases (integration
  only).
- Content-addressing byte profiles (ADR-001).
- Changing production defaults as part of a documentation-only task.

## Current evidence (2026-08-03)

| Evidence | Path / note | Supports |
| --- | --- | --- |
| Hermetic import and flags | `ipfs_datasets_py/__init__.py` | Decision 1–2 |
| `initialize` / RouterDeps | `ipfs_datasets_py/__init__.py`, `router_deps.py` | Decision 3 |
| Dependency catalog | `ipfs_datasets_py/dependency_catalog.py` | Decision 4 |
| Lazy proxy | `ipfs_datasets_py/lazy_dependencies.py` | Decision 4, invariant 4 |
| Auto install controls | `ipfs_datasets_py/auto_installer.py` | Decision 5, 9 |
| Feature detection | `ipfs_datasets_py/logic/common/feature_detection.py` | Decision 5 |
| IPFS backend router | `ipfs_datasets_py/ipfs_backend_router.py` | Optional backends |
| Prover lazy installer | `ipfs_datasets_py/logic/external_provers/lazy_installer.py` | Decision 5, invariant 9 |
| Packaging extras + install-provers script | `pyproject.toml` / `setup.py` | Declared install surface |
| Lifecycle guide | `docs/architecture/DEPENDENCY_AND_INITIALIZATION.md` | Full operational narrative |
| Integration boundaries | `docs/architecture/INTEGRATION_BOUNDARIES.md` | Submodules / kit / accelerate |
| Source authority kinds | `docs/maintenance/SOURCE_AUTHORITY.md` | Probe ≠ capability ≠ proof |

**Discrepancies / deferred gates:** Some historical reports claim “works without
optional dependencies” without stating which features degrade; prefer this ADR
and the dependency guide over undated completion narratives. Runtime auto-install
defaults (`IPFS_DATASETS_AUTO_INSTALL` set true when unset) favor DX; production
and CI should still set hermetic/offline flags explicitly—document that as
operator policy, not as “install is authorization.”

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| [ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md](ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Identity vs capability; no fake CIDs when deps missing |
| [DEPENDENCY_AND_INITIALIZATION.md](../DEPENDENCY_AND_INITIALIZATION.md) | How/when load, install, probe (guide) |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | External package and submodule ownership |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | Surfaces and actors |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Authority order and kinds of truth |
| `docs/security_verification/lazy_theorem_prover_installation.md` | Operator-facing prover detail |
| Package-local MCP ADRs | Runtime/tool structure; not this global capability policy |

## Notes / errata

- Numbering: this is global `docs/architecture/decisions/ADR-002`. It does not
  replace package-local `mcp_server/docs/adr/ADR-002-dual-runtime.md`.
- Index row is owned by the later decisions-index task; status here is
  authoritative for the body until superseded.

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Proposed and accepted from current-tree evidence (`IPFSDOC-013`) |
