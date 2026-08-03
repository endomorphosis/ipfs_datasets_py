# IPFS Datasets Documentation Supervisor Task Board

Board namespace: `ipfs-datasets-documentation-v1`
Task prefix: `IPFSDOC-`
Task source kind: `legacy-markdown`

This is the reviewed executable projection of
`docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH.objectives.md`.
The human plan is
`docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH_PLAN_2026_08_03.md`.

The three planning files are protected operator inputs and are never task
outputs. Workers may edit only declared documentation outputs. Production code,
tests, packaging, deployment configuration, nested submodules, and unrelated
working-tree state are read-only evidence for this v1 documentation program.

Program rules:

- Use artifact completion after fresh validation and merge. Tasks whose product
  outputs existed at the planning baseline must also create their declared
  current-tree completion receipt so stale pages cannot satisfy completion.
- Prefer current code, tests, schemas, packaging, and accepted ADRs over old
  plans, status reports, generated summaries, or prose claims.
- Do not change product behavior to make stale documentation true.
- Do not treat discovery as capability, syntax as semantics, model output as
  proof, proof as authorization, monitoring as proof, or UI visibility as
  execution authority.
- Do not mass-delete or move historical documentation; publish a reviewed
  disposition and canonical route first.
- Do not edit shared navigation files before their exclusive late-owner tasks.
- Keep network, native prover, external-service, and full-site-build work out of
  ordinary leaf acceptance. Record provisioned gates explicitly.
- Preserve unrelated nested-submodule and checkout state.

## IPFSDOC-001 Capture the current documentation and code-surface baseline

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: audit
- Depends on:
- Goal id: IPFSDOC-G011
- Outputs: docs/maintenance/CURRENT_STATE_BASELINE.md
- Validation: test -s docs/maintenance/CURRENT_STATE_BASELINE.md && rg -n 'commit|Markdown|package|test|MkDocs|submodule' docs/maintenance/CURRENT_STATE_BASELINE.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/baseline
- Parallel lane: baseline-inventory
- Resource class: cpu-small
- Predicted files: docs/maintenance/CURRENT_STATE_BASELINE.md
- Interfaces: DocumentationBaseline@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates the dated measurement all later tasks cite.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: small
- Estimated tokens: 7000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G011
- Acceptance: Record the current commit, Python/package/test/docs counts, root-page count, navigated-page count, top-level domains, console entry points, extras, submodules, generated/package-local docs, and reproducible commands. Separate tracked facts from estimates and do not copy existing counts as authority.

## IPFSDOC-002 Build the claim-level drift and stale-surface matrix

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: audit
- Depends on: IPFSDOC-001
- Goal id: IPFSDOC-G011
- Outputs: docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md
- Validation: test -s docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md && rg -n 'installation.md|user_guide.md|developer_guide.md|FEATURES.md|CHANGELOG.md|Priority' docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/baseline
- Parallel lane: baseline-drift
- Resource class: cpu-small
- Predicted files: docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md
- Interfaces: DocumentationDriftMatrix@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Produces the prioritized truth-repair queue used by guide writers.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 9000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G011
- Acceptance: Classify high-impact version, Python, dependency-extra, import, command, tool-count, feature, submodule, API-signature, and completion claims against current code/tests/config. Include exact source evidence, severity, owner, canonical target, and disposition; do not blindly replace intentional migration examples.

## IPFSDOC-003 Define information architecture, page contracts, and contribution policy

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: governance
- Depends on: IPFSDOC-001
- Goal id: IPFSDOC-G012
- Outputs: docs/maintenance/INFORMATION_ARCHITECTURE.md, docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md, docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md, docs/architecture/decisions/ADR_TEMPLATE.md
- Validation: test -s docs/maintenance/INFORMATION_ARCHITECTURE.md && test -s docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md && test -s docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md && test -s docs/architecture/decisions/ADR_TEMPLATE.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/policy
- Parallel lane: governance-policy
- Resource class: cpu-small
- Predicted files: docs/maintenance/INFORMATION_ARCHITECTURE.md, docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md, docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md, docs/architecture/decisions/ADR_TEMPLATE.md
- Interfaces: DocumentationPageContract@1, ArchitectureGuideTemplate@1, ADRTemplate@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Freezes the writing and lifecycle contract for parallel documentation lanes.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 9000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G012
- Acceptance: Define audiences, canonical/generated/plan/evidence/historical states, naming and placement, required owner/source/last-verified metadata, diagram/example/citation rules, architecture sections, ADR lifecycle, review cadence, deprecation, and archive policy. Preserve history without presenting it as current authority.

## IPFSDOC-004 Map package-local, generated, and competing documentation authorities

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: audit
- Depends on: IPFSDOC-001, IPFSDOC-003
- Goal id: IPFSDOC-G011
- Outputs: docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md
- Validation: test -s docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md && rg -n 'mcp_server/docs/adr|generated|canonical|pointer|migrate' docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/baseline
- Parallel lane: baseline-authority-map
- Resource class: cpu-small
- Predicted files: docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md
- Interfaces: DocumentationAuthorityMap@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Prevents parallel agents from creating a second authority where useful material already exists.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: small
- Estimated tokens: 7000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G011
- Acceptance: Inventory package-local Markdown, generated references/build output, competing logic/optimizer/processor/MCP guides, and the existing MCP ADRs. Assign canonical, refresh-and-surface, pointer, generated, historical, or review-needed disposition without moving or deleting files.

## IPFSDOC-005 Publish the source-authority and coverage matrix

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: audit
- Depends on: IPFSDOC-002, IPFSDOC-003, IPFSDOC-004
- Goal id: IPFSDOC-G011
- Outputs: docs/maintenance/SOURCE_AUTHORITY.md, docs/maintenance/COVERAGE_MATRIX.md
- Validation: test -s docs/maintenance/SOURCE_AUTHORITY.md && test -s docs/maintenance/COVERAGE_MATRIX.md && rg -n 'processors|logic|mcp_server|wallet|voice|huggingface|Profile G' docs/maintenance/COVERAGE_MATRIX.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/baseline
- Parallel lane: baseline-coverage
- Resource class: cpu-small
- Predicted files: docs/maintenance/SOURCE_AUTHORITY.md, docs/maintenance/COVERAGE_MATRIX.md
- Interfaces: DocumentationSourceAuthority@1, DocumentationCoverageMatrix@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates the reviewed scope and authority input for all architecture and audience tasks.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 8500
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G011
- Acceptance: Define the authority order among tests/schemas, implementation, packaging/config, accepted ADRs, maintained guides, and historical artifacts. Map every top-level production domain and target audience to current, planned, missing, or non-applicable canonical coverage with P0/P1 gaps.

## IPFSDOC-006 Create deterministic documentation validation tooling and runbook

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: quality
- Depends on: IPFSDOC-003
- Goal id: IPFSDOC-G012
- Outputs: docs/maintenance/check_docs.py, docs/maintenance/VALIDATION_RUNBOOK.md
- Validation: python docs/maintenance/check_docs.py --help && python -m py_compile docs/maintenance/check_docs.py && test -s docs/maintenance/VALIDATION_RUNBOOK.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/quality-tooling
- Parallel lane: quality-tooling
- Resource class: cpu-small
- Predicted files: docs/maintenance/check_docs.py, docs/maintenance/VALIDATION_RUNBOOK.md
- Interfaces: DocumentationValidator@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Makes per-lane and release validation reproducible without relying on the broken legacy audit scripts.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 10000
- Estimated context tokens: 12000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G012
- Acceptance: Provide a side-effect-free local checker for Markdown paths, relative links/anchors, referenced repository paths and Python modules, required metadata on canonical pages, duplicate canonical declarations, and fenced Python syntax, with explicit allowlists for archives and before-migration examples. It must not use network access, filesystem mtimes as freshness proof, or delete generated output.

## IPFSDOC-010 Write the current system context and domain ownership map

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: architecture
- Depends on: IPFSDOC-005
- Goal id: IPFSDOC-G031
- Outputs: docs/architecture/SYSTEM_CONTEXT.md, docs/architecture/DOMAIN_MAP.md
- Validation: test -s docs/architecture/SYSTEM_CONTEXT.md && test -s docs/architecture/DOMAIN_MAP.md && rg -n 'processors|logic|mcp_server|optimizers|knowledge_graphs|vector_stores|wallet|voice' docs/architecture/DOMAIN_MAP.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/system-model
- Parallel lane: architecture-context
- Resource class: cpu-small
- Predicted files: docs/architecture/SYSTEM_CONTEXT.md, docs/architecture/DOMAIN_MAP.md
- Interfaces: IPFSDatasetsSystemContext@1, DomainOwnershipMap@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Provides the primary mental model and placement map for later subsystem guides.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 12000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G031
- Acceptance: Describe actors and supported Python/CLI/MCP/service surfaces, all current top-level domains, responsibility and authority boundaries, canonical vs compatibility surfaces, optional/external systems, and non-goals. Ground the map in package topology, public contracts, tests, packaging, and the logic submodule registry.

## IPFSDOC-011 Document end-to-end flows and runtime entry points

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: architecture
- Depends on: IPFSDOC-010
- Goal id: IPFSDOC-G031
- Outputs: docs/architecture/END_TO_END_DATA_FLOW.md, docs/architecture/RUNTIME_ENTRYPOINTS.md
- Validation: test -s docs/architecture/END_TO_END_DATA_FLOW.md && test -s docs/architecture/RUNTIME_ENTRYPOINTS.md && rg -n 'Python|CLI|MCP|provenance|failure' docs/architecture/END_TO_END_DATA_FLOW.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/system-model
- Parallel lane: architecture-flows
- Resource class: cpu-small
- Predicted files: docs/architecture/END_TO_END_DATA_FLOW.md, docs/architecture/RUNTIME_ENTRYPOINTS.md
- Interfaces: DatasetDataFlow@1, RuntimeEntrypointMap@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Establishes cross-domain flow language without idealizing unfinished or compatibility paths.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 11000
- Estimated context tokens: 12000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G031
- Acceptance: Trace representative ingestion-to-artifact, artifact-to-index, query-to-result, logic-to-evidence, and MCP-to-dispatch flows. For every hop identify inputs, outputs, owner, identity/provenance, side effects, optional dependencies, failure/degradation, and the actual callable or console entry point.

## IPFSDOC-012 Explain dependency initialization routers and submodule boundaries

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: architecture
- Depends on: IPFSDOC-010
- Goal id: IPFSDOC-G031
- Outputs: docs/architecture/DEPENDENCY_AND_INITIALIZATION.md, docs/architecture/INTEGRATION_BOUNDARIES.md
- Validation: test -s docs/architecture/DEPENDENCY_AND_INITIALIZATION.md && test -s docs/architecture/INTEGRATION_BOUNDARIES.md && rg -n 'Python 3.12|initialize|lazy|ipfs_kit|ipfs_accelerate|submodule' docs/architecture/DEPENDENCY_AND_INITIALIZATION.md docs/architecture/INTEGRATION_BOUNDARIES.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/system-model
- Parallel lane: architecture-dependencies
- Resource class: cpu-small
- Predicted files: docs/architecture/DEPENDENCY_AND_INITIALIZATION.md, docs/architecture/INTEGRATION_BOUNDARIES.md
- Interfaces: DependencyLifecycle@1, IntegrationBoundaryMap@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Makes the recent lazy theorem-prover and dependency lifecycle changes understandable and operable.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 12000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G031
- Acceptance: Explain minimal and opt-in imports, explicit initialize and injected RouterDeps, auto/lazy installation controls, capability probing, router selection, ten current git submodules, ipfs_kit/ipfs_accelerate ownership, native theorem-prover provisioning, and offline/unavailable behavior. Distinguish graceful feature degradation from fail-closed trust boundaries.

## IPFSDOC-013 Record ADRs for content identity provenance and lazy capabilities

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: decisions
- Depends on: IPFSDOC-003, IPFSDOC-010, IPFSDOC-012
- Goal id: IPFSDOC-G032
- Outputs: docs/architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md, docs/architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md
- Validation: test -s docs/architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md && test -s docs/architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/adrs
- Parallel lane: adr-identity-dependencies
- Resource class: cpu-small
- Predicted files: docs/architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md, docs/architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md
- Interfaces: ContentIdentityDecision@1, LazyCapabilityDecision@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Preserves two core bespoke design rationales for future changes.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 9000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G032
- Acceptance: Record context, alternatives, decision, consequences, invariants, status, owner, and current evidence for canonical bytes/CIDs/provenance and for lazy optional dependency/capability behavior. State where identifiers are not locations, receipts, authorizations, or proof.

## IPFSDOC-014 Record ADRs for layered authority and fail-closed degradation

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: decisions
- Depends on: IPFSDOC-003, IPFSDOC-011
- Goal id: IPFSDOC-G032
- Outputs: docs/architecture/decisions/ADR-003-LAYERED-AUTHORITY.md, docs/architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md
- Validation: test -s docs/architecture/decisions/ADR-003-LAYERED-AUTHORITY.md && test -s docs/architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/adrs
- Parallel lane: adr-authority
- Resource class: cpu-small
- Predicted files: docs/architecture/decisions/ADR-003-LAYERED-AUTHORITY.md, docs/architecture/decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md
- Interfaces: LayeredAuthorityDecision@1, FailClosedDecision@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates the authority vocabulary used by logic, MCP, security, and agent guides.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 9500
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G032
- Acceptance: Explain why parsing, validation, retrieval/model candidates, satisfiability, proof, policy, authorization, dispatch, monitoring, and receipts are non-interchangeable; define UNKNOWN/NOT_MODELED/unavailable/denied behavior and when degradation is allowed versus fail-closed.

## IPFSDOC-015 Record ADRs for registries adapters layering and dual runtimes

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: decisions
- Depends on: IPFSDOC-003, IPFSDOC-010
- Goal id: IPFSDOC-G032
- Outputs: docs/architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md, docs/architecture/decisions/ADR-006-PROCESSOR-LAYERING.md, docs/architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md
- Validation: test -s docs/architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md && test -s docs/architecture/decisions/ADR-006-PROCESSOR-LAYERING.md && test -s docs/architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/adrs
- Parallel lane: adr-structure
- Resource class: cpu-small
- Predicted files: docs/architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md, docs/architecture/decisions/ADR-006-PROCESSOR-LAYERING.md, docs/architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md
- Interfaces: RegistryAdapterDecision@1, ProcessorLayeringDecision@1, MCPRuntimeCompatibilityDecision@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Explains transitional structure without presenting an idealized clean architecture.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 11000
- Estimated context tokens: 12000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G032
- Acceptance: Ground the registry/adapter pattern, mixed processor root/core transition, and canonical-versus-compatibility MCP runtimes in current code and existing package ADRs. Record strangler/deprecation consequences and reject duplicate sources of truth.

## IPFSDOC-016 Index decisions and reconcile existing package-local MCP ADRs

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: decisions
- Depends on: IPFSDOC-013, IPFSDOC-014, IPFSDOC-015
- Goal id: IPFSDOC-G032
- Outputs: docs/architecture/decisions/README.md, docs/architecture/decisions/MCP_ADR_RECONCILIATION.md
- Validation: test -s docs/architecture/decisions/README.md && test -s docs/architecture/decisions/MCP_ADR_RECONCILIATION.md && rg -n 'Status|Owner|Supersed|package-local' docs/architecture/decisions/README.md docs/architecture/decisions/MCP_ADR_RECONCILIATION.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/adrs
- Parallel lane: adr-integration
- Resource class: cpu-small
- Predicted files: docs/architecture/decisions/README.md, docs/architecture/decisions/MCP_ADR_RECONCILIATION.md
- Interfaces: ArchitectureDecisionIndex@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Provides one discoverable decision surface while acknowledging package-local sources.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: small
- Estimated tokens: 7000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G032
- Acceptance: Index every accepted/proposed/superseded ADR and map the six existing package-local MCP ADRs to refresh, canonical pointer, merge, or historical disposition. Preserve their evidence and history; do not independently recreate or delete them.

## IPFSDOC-017 Document agent supervisor taskboards worktrees and Profile G

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: agent-architecture
- Depends on: IPFSDOC-010, IPFSDOC-011, IPFSDOC-012, IPFSDOC-014
- Goal id: IPFSDOC-G082
- Outputs: docs/architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md, docs/architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md
- Validation: test -s docs/architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md && test -s docs/architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md && rg -n 'worktree|heartbeat|merge|blocked|Goal|TaskSpec|fail closed' docs/architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md docs/architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/agents
- Parallel lane: agent-runtime-architecture
- Resource class: cpu-small
- Predicted files: docs/architecture/runtime/AGENT_SUPERVISOR_AND_TASKBOARDS.md, docs/architecture/runtime/PROFILE_G_PLANNING_AND_EVIDENCE.md
- Interfaces: AgentSupervisorExecutionContract@1, ProfileGDatasetProvider@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Gives developers and agents an accurate model of the supervisor being used for this program.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G082
- Acceptance: Explain canonical ownership in ipfs_accelerate versus reusable/compat datasets code; task parsing, goals/subgoals, isolated worktrees, proposal validation, retries/blockers, watchdog/heartbeat, merge authority and receipts, namespace isolation, and Profile G canonical DAG-JSON/CID planning/risk/evidence. State that placement is advisory and execution/leases remain external and fail closed.

## IPFSDOC-020 Document processor contracts pipeline and file/multimedia processing

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: processing
- Depends on: IPFSDOC-003, IPFSDOC-010, IPFSDOC-011
- Goal id: IPFSDOC-G041
- Outputs: docs/architecture/processing/PROCESSOR_PIPELINE.md, docs/architecture/processing/FILE_AND_MULTIMEDIA.md
- Validation: test -s docs/architecture/processing/PROCESSOR_PIPELINE.md && test -s docs/architecture/processing/FILE_AND_MULTIMEDIA.md && rg -n 'protocol|registry|compat|optional|provenance' docs/architecture/processing/PROCESSOR_PIPELINE.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/processing
- Parallel lane: processing-core
- Resource class: cpu-small
- Predicted files: docs/architecture/processing/PROCESSOR_PIPELINE.md, docs/architecture/processing/FILE_AND_MULTIMEDIA.md
- Interfaces: ProcessorPipelineArchitecture@1, FileMultimediaProcessing@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates current developer guidance for the largest package domain.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G041
- Acceptance: Map mixed root/core processor protocols and results, registry ownership, canonical imports, detection, batching, conversion, PDF/OCR/media paths, async/resource controls, optional tools, adapters, output/provenance handoff, and failure modes. Do not claim the transition is complete where duplicate types remain.

## IPFSDOC-021 Document web archival and legal evidence ingestion

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: processing
- Depends on: IPFSDOC-003, IPFSDOC-010, IPFSDOC-011
- Goal id: IPFSDOC-G041
- Outputs: docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md
- Validation: test -s docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md && rg -n 'official|Common Crawl|WARC|effective|citation|CID|publication' docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/processing
- Parallel lane: processing-web-legal
- Resource class: cpu-small
- Predicted files: docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md
- Interfaces: WebArchiveLegalEvidencePipeline@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Documents the large post-baseline legal acquisition and evidence pipeline.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 15000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G041
- Acceptance: Trace official-source-first discovery/fetch/parse/hierarchy/status, Common Crawl and archive fallbacks, cache/resume/WARC pointers, CourtListener/PACER and authentication boundaries, citations/PDFs/manifests, effective dates/versioning, content addressing, KG/reasoner handoff, and publication lifecycle. Separate source evidence from model or heuristic enrichment.

## IPFSDOC-022 Publish the processing architecture index and extension routes

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: processing
- Depends on: IPFSDOC-020, IPFSDOC-021
- Goal id: IPFSDOC-G041
- Outputs: docs/architecture/processing/README.md
- Validation: test -s docs/architecture/processing/README.md && rg -n 'PROCESSOR_PIPELINE|FILE_AND_MULTIMEDIA|WEB_ARCHIVING_AND_LEGAL_INGESTION|canonical' docs/architecture/processing/README.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/processing
- Parallel lane: processing-integration
- Resource class: cpu-small
- Predicted files: docs/architecture/processing/README.md
- Interfaces: ProcessingArchitectureIndex@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Provides one canonical processing entry without rewriting leaf guides.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: small
- Estimated tokens: 5000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G041
- Acceptance: Route developers among canonical processing guides, existing maintained processor pages, package-local details, extension recipes, and historical migrations. State ownership and current/compatibility status for each processing family.

## IPFSDOC-023 Document content addressing IPLD storage backends and caches

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: storage
- Depends on: IPFSDOC-003, IPFSDOC-010, IPFSDOC-013
- Goal id: IPFSDOC-G042
- Outputs: docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md, docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md
- Validation: test -s docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md && test -s docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md && rg -n 'canonical|CID|CAR|cache|backend|integrity' docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/storage
- Parallel lane: storage-core
- Resource class: cpu-small
- Predicted files: docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md, docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md
- Interfaces: ContentAddressedStorageArchitecture@1, StorageCacheBackendArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates the storage identity and backend mental model used by retrieval and release docs.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G042
- Acceptance: Explain canonical bytes, CID profiles, IPLD/CAR codecs, storage engine/router ownership, pinning and external backends, cache keys/trust/invalidation, consistency and integrity, optional dependencies, offline behavior, and failure/recovery. Distinguish identifiers, locations, indexes, and receipts.

## IPFSDOC-024 Document P2P workflows distribution and publication

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: distribution
- Depends on: IPFSDOC-010, IPFSDOC-012, IPFSDOC-023
- Goal id: IPFSDOC-G042
- Outputs: docs/architecture/storage/P2P_AND_PUBLICATION.md
- Validation: test -s docs/architecture/storage/P2P_AND_PUBLICATION.md && rg -n 'libp2p|peer|task|IPFS|Hugging Face|offline|receipt' docs/architecture/storage/P2P_AND_PUBLICATION.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/storage
- Parallel lane: storage-p2p-publication
- Resource class: cpu-small
- Predicted files: docs/architecture/storage/P2P_AND_PUBLICATION.md
- Interfaces: P2PDistributionArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Explains how content and work move beyond a single process.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 11000
- Estimated context tokens: 12000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G042
- Acceptance: Map peer discovery/registry/connectivity, task and workflow scheduling, transport and storage handoffs, IPFS cluster and publication roles, network/identity assumptions, timeout/cancel/retry behavior, and offline/degraded states. Do not present a stub or simulated peer result as distributed completion.

## IPFSDOC-025 Document immutable dataset build publish and load lifecycles

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: publication
- Depends on: IPFSDOC-013, IPFSDOC-023, IPFSDOC-024
- Goal id: IPFSDOC-G042
- Outputs: docs/architecture/storage/IMMUTABLE_DATASET_RELEASES.md
- Validation: test -s docs/architecture/storage/IMMUTABLE_DATASET_RELEASES.md && rg -n 'voice|Parquet|CID|dry-run|approval|revision|rollback|append-only' docs/architecture/storage/IMMUTABLE_DATASET_RELEASES.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/storage
- Parallel lane: storage-immutable-release
- Resource class: cpu-small
- Predicted files: docs/architecture/storage/IMMUTABLE_DATASET_RELEASES.md
- Interfaces: ImmutableDatasetReleaseLifecycle@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Captures a new bespoke release plane not covered by the existing docs.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 13000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G042
- Acceptance: Use voice and Hugging Face packages to explain schema, deterministic normalization/quarantine, safe GraphRAG, offline materialization, integer quality gates, byte-identical shards, approval-gated append-only publishing, commit/digest verification, pinned loaders, pointer canary/rollback, and compatibility identity aliases. Autonomous workers must stop at the documented dry-run boundary.

## IPFSDOC-026 Publish the storage and distribution architecture index

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: storage
- Depends on: IPFSDOC-023, IPFSDOC-024, IPFSDOC-025
- Goal id: IPFSDOC-G042
- Outputs: docs/architecture/storage/README.md
- Validation: test -s docs/architecture/storage/README.md && rg -n 'CONTENT_ADDRESSING_AND_IPLD|STORAGE_CACHING_AND_BACKENDS|P2P_AND_PUBLICATION|IMMUTABLE_DATASET_RELEASES' docs/architecture/storage/README.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/storage
- Parallel lane: storage-integration
- Resource class: cpu-small
- Predicted files: docs/architecture/storage/README.md
- Interfaces: StorageArchitectureIndex@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates one storage/distribution entry point.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: small
- Estimated tokens: 5000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G042
- Acceptance: Route canonical storage, distribution, and release concepts to current pages, retained component references, API docs, and operations. Clearly label backend-specific, optional, compatibility, and historical material.

## IPFSDOC-030 Document embeddings vector stores indexing and search

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: retrieval
- Depends on: IPFSDOC-010, IPFSDOC-013, IPFSDOC-023
- Goal id: IPFSDOC-G051
- Outputs: docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md, docs/architecture/retrieval/VECTOR_STORES.md, docs/architecture/retrieval/SEARCH_AND_QUERY.md
- Validation: test -s docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md && test -s docs/architecture/retrieval/VECTOR_STORES.md && test -s docs/architecture/retrieval/SEARCH_AND_QUERY.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/retrieval
- Parallel lane: retrieval-core
- Resource class: cpu-small
- Predicted files: docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md, docs/architecture/retrieval/VECTOR_STORES.md, docs/architecture/retrieval/SEARCH_AND_QUERY.md
- Interfaces: RetrievalArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates the current retrieval architecture leaf set.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 16000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G051
- Acceptance: Map dense/sparse embedding generation and routing, schemas and shard identity, vector-store protocols and IPLD/FAISS/Qdrant/Elasticsearch differences, index lifecycle, semantic/hybrid/streaming search, query optimization, consistency, provenance, optional models, and unavailable/mock behavior. Backend features must not be generalized.

## IPFSDOC-031 Document the knowledge graph lifecycle and authority model

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: knowledge-graphs
- Depends on: IPFSDOC-010, IPFSDOC-023, IPFSDOC-030
- Goal id: IPFSDOC-G052
- Outputs: docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md
- Validation: test -s docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md && rg -n 'extraction|transaction|lineage|query|reasoning|Neo4j|CID' docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/knowledge
- Parallel lane: knowledge-graph
- Resource class: cpu-small
- Predicted files: docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md
- Interfaces: KnowledgeGraphLifecycle@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Replaces stale version/file-count narratives with a contract-oriented graph architecture.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 13000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G052
- Acceptance: Trace extraction candidates through model/core representation, validation, transaction/storage/indexing, lineage/provenance, JSON-LD/Cypher/SPARQL/query, reasoning, Neo4j compatibility, and migration. State which artifacts are source evidence, persisted graph facts, indexes, inferred results, or compatibility views.

## IPFSDOC-032 Document GraphRAG and optimizer control loops

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: knowledge-optimization
- Depends on: IPFSDOC-010, IPFSDOC-030, IPFSDOC-031
- Goal id: IPFSDOC-G052
- Outputs: docs/architecture/knowledge/GRAPHRAG.md, docs/architecture/knowledge/OPTIMIZATION_LOOPS.md
- Validation: test -s docs/architecture/knowledge/GRAPHRAG.md && test -s docs/architecture/knowledge/OPTIMIZATION_LOOPS.md && rg -n 'generate|critique|optimize|OptimizationContext|candidate|evidence' docs/architecture/knowledge/OPTIMIZATION_LOOPS.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/knowledge
- Parallel lane: knowledge-optimization
- Resource class: cpu-small
- Predicted files: docs/architecture/knowledge/GRAPHRAG.md, docs/architecture/knowledge/OPTIMIZATION_LOOPS.md
- Interfaces: GraphRAGArchitecture@1, OptimizerLoopArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Documents current knowledge orchestration and corrects the stale optimizer template model.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G052
- Acceptance: Explain graph-aware retrieval/generation and provenance, optimizer BaseOptimizer/OptimizationContext contracts, generate-critique-optimize-validate loops, lifecycle hooks, quality/evaluation evidence, lazy LLM dependencies, and failure behavior. Scores and model recommendations remain advisory rather than truth or proof.

## IPFSDOC-033 Publish retrieval and knowledge architecture indexes

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: retrieval-knowledge
- Depends on: IPFSDOC-030, IPFSDOC-031, IPFSDOC-032
- Goal id: IPFSDOC-G050
- Outputs: docs/architecture/retrieval/README.md, docs/architecture/knowledge/README.md
- Validation: test -s docs/architecture/retrieval/README.md && test -s docs/architecture/knowledge/README.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/retrieval-knowledge
- Parallel lane: retrieval-knowledge-integration
- Resource class: cpu-small
- Predicted files: docs/architecture/retrieval/README.md, docs/architecture/knowledge/README.md
- Interfaces: RetrievalKnowledgeArchitectureIndex@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates canonical entry points for two related but non-interchangeable domains.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: small
- Estimated tokens: 6000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G050
- Acceptance: Route canonical retrieval, knowledge, GraphRAG, optimizer, component, API, tutorial, and historical material; remove undated embedded counts and mark backend/optional/compatibility differences.

## IPFSDOC-040 Document IR family ownership canonical identity and provenance

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: logic
- Depends on: IPFSDOC-010, IPFSDOC-013, IPFSDOC-014
- Goal id: IPFSDOC-G061
- Outputs: docs/architecture/logic/IR_FAMILY_AND_IDENTITY.md
- Validation: test -s docs/architecture/logic/IR_FAMILY_AND_IDENTITY.md && rg -n 'ir_core|legal_ir|security_ir|intent_ir|canonical|CID|provenance|compat' docs/architecture/logic/IR_FAMILY_AND_IDENTITY.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/logic
- Parallel lane: logic-ir
- Resource class: cpu-small
- Predicted files: docs/architecture/logic/IR_FAMILY_AND_IDENTITY.md
- Interfaces: IRFamilyArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Turns recently landed IR structure into stable architecture guidance.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G061
- Acceptance: Explain the domain-neutral inward kernel, canonical UTF-8/JSON and stable CIDs, immutable declaration/run/result/receipt artifacts, claims/evidence/source grounding, legal/security/intent families, submodule registry, canonical direct imports, and compatibility-facade migration. Non-interchangeable authority classes must remain explicit.

## IPFSDOC-041 Document formal compilation decompilation and semantic round trips

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: logic
- Depends on: IPFSDOC-040
- Goal id: IPFSDOC-G061
- Outputs: docs/architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md
- Validation: test -s docs/architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md && rg -n 'source map|withhold|abstain|partial|decompil|equivalence|version|CID' docs/architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/logic
- Parallel lane: logic-roundtrip
- Resource class: cpu-small
- Predicted files: docs/architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md
- Interfaces: SemanticRoundTripArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Documents the bespoke bidirectional formalization system and its limits.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G061
- Acceptance: Trace canonical IR through FOL/F-logic/event-calculus/TDFOL/DCEC and related views, source maps and cross-view identities, source-withholding, deterministic reconstruction, ambiguity, abstention/explicit partial semantics, equivalence policy, and exact interface/version/CID pins. Parsing and string similarity must not be called semantic proof.

## IPFSDOC-042 Document external provers hammers backends and lazy provisioning

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: logic-proof
- Depends on: IPFSDOC-012, IPFSDOC-040, IPFSDOC-041
- Goal id: IPFSDOC-G061
- Outputs: docs/architecture/logic/EXTERNAL_PROVERS.md
- Validation: test -s docs/architecture/logic/EXTERNAL_PROVERS.md && rg -n 'hammer|SAT|SMT|Z3|CVC5|timeout|UNKNOWN|capability|lazy' docs/architecture/logic/EXTERNAL_PROVERS.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/logic
- Parallel lane: logic-provers
- Resource class: cpu-small
- Predicted files: docs/architecture/logic/EXTERNAL_PROVERS.md
- Interfaces: ExternalProverArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Provides an honest operational and trust model for theorem-prover integrations.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G061
- Acceptance: Explain trusted-kernel versus SAT/SMT/runtime/evidence authority, hammer premise selection/portfolio/reconstruction, adapters and native/system dependencies, capability probing, lazy user-local installation, timeout/cancel/cache/receipt lifecycle, and typed proved/countermodel/unknown/unsupported/unavailable outcomes.

## IPFSDOC-043 Document legal security constraints proof attestations and ZKP

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: logic-policy
- Depends on: IPFSDOC-040, IPFSDOC-042
- Goal id: IPFSDOC-G062
- Outputs: docs/architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md, docs/architecture/logic/PROOF_ATTESTATION_AND_ZKP.md
- Validation: test -s docs/architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md && test -s docs/architecture/logic/PROOF_ATTESTATION_AND_ZKP.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/logic
- Parallel lane: logic-proof-policy
- Resource class: cpu-small
- Predicted files: docs/architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md, docs/architecture/logic/PROOF_ATTESTATION_AND_ZKP.md
- Interfaces: ConstraintProofArchitecture@1, ProofAttestationArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Establishes proof-evidence and constraint boundaries used by governed authorization.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 16000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G062
- Acceptance: Map constraint compilation and applicability, proof corpus and cache integrity, trust/revocation policy, direct proof versus verifier execution versus membership/signature versus simulation, ZKP and attestation profiles, modeled assumptions, UNKNOWN/NOT_MODELED, redaction, and release assurance. Heuristic extraction remains non-authoritative until admitted.

## IPFSDOC-044 Document governed intent authorization and result authority

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: logic-policy
- Depends on: IPFSDOC-014, IPFSDOC-040, IPFSDOC-043
- Goal id: IPFSDOC-G062
- Outputs: docs/architecture/logic/GOVERNED_AUTHORIZATION.md, docs/architecture/logic/RESULT_AUTHORITY.md
- Validation: test -s docs/architecture/logic/GOVERNED_AUTHORIZATION.md && test -s docs/architecture/logic/RESULT_AUTHORITY.md && rg -n 'side-effect-free|pre-dispatch|one-time|deny|simulation|does not' docs/architecture/logic/GOVERNED_AUTHORIZATION.md docs/architecture/logic/RESULT_AUTHORITY.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/logic
- Parallel lane: logic-authorization
- Resource class: cpu-small
- Predicted files: docs/architecture/logic/GOVERNED_AUTHORIZATION.md, docs/architecture/logic/RESULT_AUTHORITY.md
- Interfaces: GovernedAuthorizationArchitecture@1, ResultAuthorityTaxonomy@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Documents the recently landed legal/security intent gate and prevents authority inflation.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 16000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G062
- Acceptance: Trace immutable invocation intent, constraint applicability, proof-corpus query/verification, obligations and portfolio decision, side-effect-free authorization, exact-context pre-dispatch revalidation, atomic one-time capability consumption, separate dispatch, revocation, cache, telemetry, and receipts. Prompts/skills/MCP bodies remain data; proof alone never grants execution.

## IPFSDOC-045 Publish the logic proof and policy architecture index

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: logic
- Depends on: IPFSDOC-040, IPFSDOC-041, IPFSDOC-042, IPFSDOC-043, IPFSDOC-044
- Goal id: IPFSDOC-G060
- Outputs: docs/architecture/logic/README.md
- Validation: test -s docs/architecture/logic/README.md && rg -n 'IR_FAMILY_AND_IDENTITY|COMPILERS_AND_SEMANTIC_ROUND_TRIP|EXTERNAL_PROVERS|GOVERNED_AUTHORIZATION|RESULT_AUTHORITY' docs/architecture/logic/README.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/logic
- Parallel lane: logic-integration
- Resource class: cpu-small
- Predicted files: docs/architecture/logic/README.md
- Interfaces: LogicArchitectureIndex@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates the stable logic architecture spine missing from current navigation.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: small
- Estimated tokens: 6000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G060
- Acceptance: Provide one current route across canonical logic families, proof/policy guides, existing maintained operations guides, component references, API/tutorials, and historical plans. Relabel completed proposal plans rather than making them the canonical architecture.

## IPFSDOC-050 Document MCP server context dispatch and tool lifecycle

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: mcp
- Depends on: IPFSDOC-010, IPFSDOC-011, IPFSDOC-015
- Goal id: IPFSDOC-G071
- Outputs: docs/architecture/mcp/SERVER_AND_DISPATCH.md, docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md
- Validation: test -s docs/architecture/mcp/SERVER_AND_DISPATCH.md && test -s docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md && rg -n 'meta-tool|lazy|hierarch|schema|cache|circuit|dispatch|compat' docs/architecture/mcp/SERVER_AND_DISPATCH.md docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/mcp
- Parallel lane: mcp-core
- Resource class: cpu-small
- Predicted files: docs/architecture/mcp/SERVER_AND_DISPATCH.md, docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md
- Interfaces: MCPServerArchitecture@1, MCPToolLifecycle@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Replaces obsolete MCP path/catalog assumptions with the live lifecycle.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 15000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G071
- Acceptance: Trace canonical server startup/context, four meta-tools and lazy discovery, schema/result caches and circuit breaker, flat/hierarchical naming and category ownership, root tool modules, metadata/validation, integrated and legacy dispatch, result envelopes, duplicates/aliases, and unavailable tools. Do not embed undated tool counts.

## IPFSDOC-051 Document MCP interfaces identity transports and runtime routing

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: mcp
- Depends on: IPFSDOC-012, IPFSDOC-050
- Goal id: IPFSDOC-G071
- Outputs: docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md
- Validation: test -s docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md && rg -n 'interface|CID|stdio|HTTP|FastAPI|gRPC|Trio|P2P|MCP\+\+|Profile G' docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/mcp
- Parallel lane: mcp-transports
- Resource class: cpu-small
- Predicted files: docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md
- Interfaces: MCPInterfaceTransportArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Explains one contract across multiple runtimes without implying exact transport parity.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 13000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G071
- Acceptance: Separate transport-neutral tool/interface contracts and content identity from stdio, HTTP/FastAPI, gRPC, Trio/AnyIO, MCP++ and libp2p adapters, P2P registries/services, runtime routing, Profile G service boundaries, transport-specific capabilities, timeout/cancel, and degradation.

## IPFSDOC-052 Document MCP policy audit event DAG and observability

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: mcp-security
- Depends on: IPFSDOC-014, IPFSDOC-043, IPFSDOC-044, IPFSDOC-050
- Goal id: IPFSDOC-G072
- Outputs: docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md, docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md
- Validation: test -s docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md && test -s docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md && rg -n 'risk|UCAN|deny|redact|event DAG|receipt|trace|metric|health' docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/mcp
- Parallel lane: mcp-policy-observability
- Resource class: cpu-small
- Predicted files: docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md, docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md
- Interfaces: MCPPolicyArchitecture@1, MCPObservabilityArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Provides the security and operator evidence model for MCP calls.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 15000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G072
- Acceptance: Explain compliance/risk/delegation/UCAN/temporal-deontic policy gates and non-execution outcomes; event DAG/CID traces, audit and receipt correlation/redaction; metrics, OpenTelemetry, Prometheus, health/readiness and P2P service states. Monitoring and visibility never substitute for policy, proof, or successful dispatch.

## IPFSDOC-053 Publish the MCP architecture index and operator runbook

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: mcp-operations
- Depends on: IPFSDOC-050, IPFSDOC-051, IPFSDOC-052
- Goal id: IPFSDOC-G070
- Outputs: docs/architecture/mcp/README.md, docs/guides/operations/MCP_SERVER_RUNBOOK.md
- Validation: test -s docs/architecture/mcp/README.md && test -s docs/guides/operations/MCP_SERVER_RUNBOOK.md && rg -n 'start|discover|probe|health|stop|recover|unavailable' docs/guides/operations/MCP_SERVER_RUNBOOK.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/mcp
- Parallel lane: mcp-integration
- Resource class: cpu-small
- Predicted files: docs/architecture/mcp/README.md, docs/guides/operations/MCP_SERVER_RUNBOOK.md
- Interfaces: MCPArchitectureIndex@1, MCPServerRunbook@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Makes MCP architecture navigable and operable.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 10000
- Estimated context tokens: 12000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G070
- Acceptance: Index canonical MCP guides and package-local ADRs, then give safe local start/discover/capability-probe/invoke/inspect/stop/diagnose/recover procedures with prerequisites, expected state, redaction, timeouts, and unavailable/degraded behavior. Distinguish canonical from simple/standalone/legacy servers.

## IPFSDOC-060 Write the threat model and secrets credential guide

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: security
- Depends on: IPFSDOC-012, IPFSDOC-014, IPFSDOC-044, IPFSDOC-052
- Goal id: IPFSDOC-G102
- Outputs: docs/guides/security/THREAT_MODEL.md, docs/guides/security/SECRETS_AND_CREDENTIALS.md
- Validation: test -s docs/guides/security/THREAT_MODEL.md && test -s docs/guides/security/SECRETS_AND_CREDENTIALS.md && rg -n 'trust|untrusted|residual|secret|redact|rotation|revoke' docs/guides/security/THREAT_MODEL.md docs/guides/security/SECRETS_AND_CREDENTIALS.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/security
- Parallel lane: security-threats
- Resource class: cpu-small
- Predicted files: docs/guides/security/THREAT_MODEL.md, docs/guides/security/SECRETS_AND_CREDENTIALS.md
- Interfaces: IPFSDatasetsThreatModel@1, SecretsCredentialGuide@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Provides a coherent security spine across data, logic, and service planes.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G102
- Acceptance: Map trust boundaries and threats for parsers, archives, models, backends, network transports, native provers, caches, credentials, delegated capabilities, PII, and generated content to current controls, tests, assumptions, residual risks, owners, detection, revocation/rotation, and recovery. Include no real secrets.

## IPFSDOC-061 Document audit provenance incidents and wallet trust/privacy

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: security
- Depends on: IPFSDOC-013, IPFSDOC-043, IPFSDOC-044, IPFSDOC-060
- Goal id: IPFSDOC-G102
- Outputs: docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md, docs/architecture/WALLET_TRUST_AND_PRIVACY.md
- Validation: test -s docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md && test -s docs/architecture/WALLET_TRUST_AND_PRIVACY.md && rg -n 'UCAN|multisig|encrypt|replication|simulated|redact|incident' docs/architecture/WALLET_TRUST_AND_PRIVACY.md docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/security
- Parallel lane: security-audit-wallet
- Resource class: cpu-small
- Predicted files: docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md, docs/architecture/WALLET_TRUST_AND_PRIVACY.md
- Interfaces: AuditIncidentGuide@1, WalletTrustPrivacyArchitecture@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Documents a new security-sensitive domain and the end-to-end incident evidence lifecycle.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 15000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G102
- Acceptance: Explain audit/provenance correlation, retention/redaction/export, incident evidence and disclosure; plus wallet encrypted records/envelope keys, UCAN grants/invocations/revocation, approval/multisig, local/IPFS/S3/Filecoin replication, deterministic versus simulated location proofs, privacy analytics/WorldID, redacted GraphRAG, public export sanitation, and trust/authority of proof fields.

## IPFSDOC-062 Write deployment performance capacity diagnostics and recovery guides

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: operations
- Depends on: IPFSDOC-012, IPFSDOC-026, IPFSDOC-033, IPFSDOC-045, IPFSDOC-053
- Goal id: IPFSDOC-G101
- Outputs: docs/guides/operations/DEPLOYMENT_AND_RUNTIME.md, docs/guides/operations/PERFORMANCE_AND_CAPACITY.md, docs/guides/operations/DIAGNOSTICS_AND_RECOVERY.md
- Validation: test -s docs/guides/operations/DEPLOYMENT_AND_RUNTIME.md && test -s docs/guides/operations/PERFORMANCE_AND_CAPACITY.md && test -s docs/guides/operations/DIAGNOSTICS_AND_RECOVERY.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/operations
- Parallel lane: operations-core
- Resource class: cpu-small
- Predicted files: docs/guides/operations/DEPLOYMENT_AND_RUNTIME.md, docs/guides/operations/PERFORMANCE_AND_CAPACITY.md, docs/guides/operations/DIAGNOSTICS_AND_RECOVERY.md
- Interfaces: DeploymentRuntimeGuide@1, PerformanceCapacityGuide@1, DiagnosticsRecoveryGuide@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Replaces production-ready slogans with safe current operator guidance.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 17000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G101
- Acceptance: Ground local/service/container/Kubernetes and example deployment modes, persistence/external services, health/readiness, resource and concurrency limits, caches, profiling/benchmarks, logs/metrics, unavailable dependencies, storage/network/partial-service failures, safe inspection, restart/migration/rollback. Label measured baselines, targets, examples, optional and unsupported paths.

## IPFSDOC-063 Write capability installation and configuration references

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: user-docs
- Depends on: IPFSDOC-005, IPFSDOC-012, IPFSDOC-042, IPFSDOC-051, IPFSDOC-060
- Goal id: IPFSDOC-G021
- Outputs: docs/guides/installation/CAPABILITY_INSTALLATION.md, docs/guides/installation/CONFIGURATION_REFERENCE.md
- Validation: test -s docs/guides/installation/CAPABILITY_INSTALLATION.md && test -s docs/guides/installation/CONFIGURATION_REFERENCE.md && rg -n 'Python 3.12|theorem-provers|file_conversion|vectors|precedence|IPFS_DATASETS' docs/guides/installation/CAPABILITY_INSTALLATION.md docs/guides/installation/CONFIGURATION_REFERENCE.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/install-config
- Parallel lane: user-install-config
- Resource class: cpu-small
- Predicted files: docs/guides/installation/CAPABILITY_INSTALLATION.md, docs/guides/installation/CONFIGURATION_REFERENCE.md
- Interfaces: CapabilityInstallationGuide@1, ConfigurationReference@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates authoritative inputs for the late installation/configuration refresh.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G021
- Acceptance: Derive Python/platform requirements, real optional extras, console scripts, native/system tools, auto/lazy behavior, capability probing, environment/config precedence and security consequences from current packaging/code. Remove nonexistent singular extras and placeholder organizations; show base, capability, offline, unavailable, and uninstall/rollback implications.

## IPFSDOC-064 Refresh the capability matrix and changelog policy

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: user-docs
- Depends on: IPFSDOC-005, IPFSDOC-022, IPFSDOC-026, IPFSDOC-033, IPFSDOC-045, IPFSDOC-053, IPFSDOC-061
- Goal id: IPFSDOC-G020
- Outputs: docs/FEATURES.md, docs/CHANGELOG.md, docs/maintenance/completion_receipts/IPFSDOC-064.md
- Validation: test -s docs/FEATURES.md && test -s docs/CHANGELOG.md && test -s docs/maintenance/completion_receipts/IPFSDOC-064.md && rg -n 'Intent IR|proof corpus|Profile G|wallet|lazy|Current|Experimental|Optional' docs/FEATURES.md docs/CHANGELOG.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/product-status
- Parallel lane: user-capabilities-history
- Resource class: cpu-small
- Predicted files: docs/FEATURES.md, docs/CHANGELOG.md, docs/maintenance/completion_receipts/IPFSDOC-064.md
- Interfaces: CapabilityStatusMatrix@1, ChangelogPolicy@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Repairs two high-visibility product-truth surfaces.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 12000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G020
- Acceptance: Replace undated marketing/count claims with a source-grounded capability matrix that labels stable/optional/experimental/compatibility/deprecated/unavailable states and covers current major domains. Turn CHANGELOG into a project release/change policy and truthful retained history rather than a worker/stub completion report; do not fabricate releases. Record the validated current tree, command, and result in the declared completion receipt.

## IPFSDOC-070 Write the current developer repository map

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: developer-docs
- Depends on: IPFSDOC-010, IPFSDOC-022, IPFSDOC-026, IPFSDOC-033, IPFSDOC-045, IPFSDOC-053, IPFSDOC-061
- Goal id: IPFSDOC-G081
- Outputs: docs/developer_guides/REPOSITORY_MAP.md
- Validation: test -s docs/developer_guides/REPOSITORY_MAP.md && rg -n 'owner|canonical|compat|tests|optional|docs' docs/developer_guides/REPOSITORY_MAP.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/developers
- Parallel lane: developer-map
- Resource class: cpu-small
- Predicted files: docs/developer_guides/REPOSITORY_MAP.md
- Interfaces: DeveloperRepositoryMap@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Gives developers a bounded first context set.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 11000
- Estimated context tokens: 12000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G081
- Acceptance: Map repository/package/test/example/deployment/docs structure, domain owners, canonical imports and entry points, compatibility and archive areas, hot/shared files, nearest tests, optional dependencies, and cross-repository ownership. Use current counts only with generated provenance and date.

## IPFSDOC-071 Write subsystem extension recipes

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: developer-docs
- Depends on: IPFSDOC-070
- Goal id: IPFSDOC-G081
- Outputs: docs/developer_guides/EXTENSION_RECIPES.md
- Validation: test -s docs/developer_guides/EXTENSION_RECIPES.md && rg -n 'processor|vector|MCP tool|compiler|prover|policy|documentation' docs/developer_guides/EXTENSION_RECIPES.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/developers
- Parallel lane: developer-recipes
- Resource class: cpu-small
- Predicted files: docs/developer_guides/EXTENSION_RECIPES.md
- Interfaces: ExtensionRecipeCatalog@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Turns architecture into actionable, invariant-preserving change workflows.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 15000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G081
- Acceptance: Provide grounded recipes for a processor, storage/vector backend, MCP tool, logic IR/compiler/prover, policy/constraint, and documentation page. Each names owner contracts, files, registration/export steps, optional dependencies, negative cases, tests, integration gates, and docs; forbid duplicate registries, eager optional imports, policy bypass, and undocumented public exports.

## IPFSDOC-072 Define focused testing and evidence selection

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: developer-docs
- Depends on: IPFSDOC-005, IPFSDOC-006, IPFSDOC-070
- Goal id: IPFSDOC-G081
- Outputs: docs/developer_guides/TESTING_AND_EVIDENCE.md
- Validation: test -s docs/developer_guides/TESTING_AND_EVIDENCE.md && rg -n 'unit|integration|conformance|benchmark|proof|negative|receipt' docs/developer_guides/TESTING_AND_EVIDENCE.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/developers
- Parallel lane: developer-testing
- Resource class: cpu-small
- Predicted files: docs/developer_guides/TESTING_AND_EVIDENCE.md
- Interfaces: TestingEvidenceGuide@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Lets agents select proportional evidence and report its authority correctly.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 10000
- Estimated context tokens: 12000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G081
- Acceptance: Map change types to nearest unit/integration/conformance/security/benchmark/build checks, fixtures and optional provisioning; distinguish tests, metrics, solver candidates, proof, policy, runtime and release evidence; require negative/unavailable paths and exact command/tree receipts without promising that the entire large suite is always the first gate.

## IPFSDOC-073 Write agent invariants troubleshooting and handoff guides

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: agent-enablement
- Depends on: IPFSDOC-016, IPFSDOC-017, IPFSDOC-070, IPFSDOC-071, IPFSDOC-072
- Goal id: IPFSDOC-G082
- Outputs: docs/developer_guides/FOR_AGENTS.md, docs/developer_guides/TROUBLESHOOTING.md, docs/developer_guides/HANDOFF_CHECKLIST.md
- Validation: test -s docs/developer_guides/FOR_AGENTS.md && test -s docs/developer_guides/TROUBLESHOOTING.md && test -s docs/developer_guides/HANDOFF_CHECKLIST.md && rg -n 'must not|blocked|unavailable|evidence|handoff' docs/developer_guides/FOR_AGENTS.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/agents
- Parallel lane: agent-guides
- Resource class: cpu-small
- Predicted files: docs/developer_guides/FOR_AGENTS.md, docs/developer_guides/TROUBLESHOOTING.md, docs/developer_guides/HANDOFF_CHECKLIST.md
- Interfaces: ImplementationAgentGuide@1, AgentHandoffContract@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates the decision-rich agent guide requested by the program.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 15000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G082
- Acceptance: Define minimum context and exploration order, protected/hot files, identity/authority/optional-dependency/security invariants, current-versus-desired behavior, common import/provider/prover/MCP/worktree/merge failures, blocker classification, safe recovery, uncertainty, and success/partial/unavailable/product-defect handoffs. Agents must not weaken tasks or rewrite queue status to hide failure.

## IPFSDOC-074 Refresh the root developer guide

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: developer-docs
- Depends on: IPFSDOC-070, IPFSDOC-071, IPFSDOC-072, IPFSDOC-073
- Goal id: IPFSDOC-G080
- Outputs: docs/developer_guide.md, docs/maintenance/completion_receipts/IPFSDOC-074.md
- Validation: test -s docs/developer_guide.md && test -s docs/maintenance/completion_receipts/IPFSDOC-074.md && rg -n 'Python 3.12|REPOSITORY_MAP|EXTENSION_RECIPES|TESTING_AND_EVIDENCE|FOR_AGENTS' docs/developer_guide.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/developers
- Parallel lane: developer-integration
- Resource class: cpu-small
- Predicted files: docs/developer_guide.md, docs/maintenance/completion_receipts/IPFSDOC-074.md
- Interfaces: DeveloperGuide@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Repairs the canonical developer landing page under one exclusive owner.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 9000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G080
- Acceptance: Replace removed requirements/scripts/modules and stale setup instructions with a concise current contributor entry routing to repository, architecture, recipe, testing, agent, contributing, security, and documentation guides. Validate all introduced paths and commands; do not duplicate detailed leaf content. Record the validated current tree, command, and result in the declared completion receipt.

## IPFSDOC-080 Build core data processing and retrieval API domain references

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: api-reference
- Depends on: IPFSDOC-010, IPFSDOC-020, IPFSDOC-023, IPFSDOC-030
- Goal id: IPFSDOC-G091
- Outputs: docs/api/domains/CORE_AND_DATA.md, docs/api/domains/PROCESSING_AND_RETRIEVAL.md
- Validation: test -s docs/api/domains/CORE_AND_DATA.md && test -s docs/api/domains/PROCESSING_AND_RETRIEVAL.md && rg -n 'Source|Stability|Optional|async|canonical' docs/api/domains/CORE_AND_DATA.md docs/api/domains/PROCESSING_AND_RETRIEVAL.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/api
- Parallel lane: api-data
- Resource class: cpu-small
- Predicted files: docs/api/domains/CORE_AND_DATA.md, docs/api/domains/PROCESSING_AND_RETRIEVAL.md
- Interfaces: CoreDataAPIReference@1, ProcessingRetrievalAPIReference@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Replaces incomplete handwritten core and retrieval API coverage with traceable references.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 15000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G091
- Acceptance: Use deterministic AST/signature and reviewed export/protocol evidence to cover all eight current core-operations exports plus intended dataset, processor, embedding, vector, search, storage, archive and publication surfaces. Mark public/reviewed/compatibility/internal stability, sync/async, side effects, optional requirements and canonical imports; correct wrong legacy method names.

## IPFSDOC-081 Build knowledge logic proof MCP and operations API references

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: api-reference
- Depends on: IPFSDOC-031, IPFSDOC-032, IPFSDOC-040, IPFSDOC-044, IPFSDOC-050, IPFSDOC-052, IPFSDOC-061
- Goal id: IPFSDOC-G091
- Outputs: docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md, docs/api/domains/MCP_AND_RUNTIME.md, docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md
- Validation: test -s docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md && test -s docs/api/domains/MCP_AND_RUNTIME.md && test -s docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/api
- Parallel lane: api-logic-mcp
- Resource class: cpu-small
- Predicted files: docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md, docs/api/domains/MCP_AND_RUNTIME.md, docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md
- Interfaces: KnowledgeLogicAPIReference@1, MCPRuntimeAPIReference@1, OperationsAPIReference@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates source-grounded references for the most bespoke domains.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 17000
- Estimated context tokens: 20000
- Estimated validation seconds: 600
- Merge fate: objective/IPFSDOC-G091
- Acceptance: Map intended knowledge/optimizer/IR/compiler/prover/policy, MCP server/tool/interface/client, and audit/wallet/workflow/config/integration surfaces from live signatures and contracts. Importability is not public stability; compatibility aliases, optional providers, side effects, and result authority must be explicit.

## IPFSDOC-082 Publish the API reference index and generation provenance

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: api-reference
- Depends on: IPFSDOC-080, IPFSDOC-081
- Goal id: IPFSDOC-G091
- Outputs: docs/api/README.md, docs/api/GENERATION_AND_FRESHNESS.md
- Validation: test -s docs/api/README.md && test -s docs/api/GENERATION_AND_FRESHNESS.md && rg -n 'CORE_AND_DATA|PROCESSING_AND_RETRIEVAL|KNOWLEDGE_LOGIC_AND_PROOF|MCP_AND_RUNTIME' docs/api/README.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/api
- Parallel lane: api-integration
- Resource class: cpu-small
- Predicted files: docs/api/README.md, docs/api/GENERATION_AND_FRESHNESS.md
- Interfaces: APIReferenceIndex@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Provides one authoritative API entry and an honest generated-doc lifecycle.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: small
- Estimated tokens: 7000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G091
- Acceptance: Index conceptual-to-domain API routes, document generation inputs/coverage/limitations/freshness verification, classify legacy generated optimizer/TDFOL/stub artifacts, and state how to detect signature drift. Do not present exhaustive internal AST output as a public contract.

## IPFSDOC-083 Write first-dataset and retrieval/knowledge tutorials

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: tutorials
- Depends on: IPFSDOC-026, IPFSDOC-030, IPFSDOC-031, IPFSDOC-063, IPFSDOC-080
- Goal id: IPFSDOC-G092
- Outputs: docs/tutorials/FIRST_DATASET_WORKFLOW.md, docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md
- Validation: test -s docs/tutorials/FIRST_DATASET_WORKFLOW.md && test -s docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md && python -m compileall -q docs/tutorials
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/tutorials
- Parallel lane: tutorials-data
- Resource class: cpu-small
- Predicted files: docs/tutorials/FIRST_DATASET_WORKFLOW.md, docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md
- Interfaces: DatasetWorkflowTutorial@1, RetrievalKnowledgeTutorial@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates verified user journeys for data and retrieval planes.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 13000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G092
- Acceptance: Provide bounded offline-first journeys from install/import through dataset processing/identity/storage and through embedding/index/query/knowledge results, with declared extras, temporary data, cleanup, expected evidence, unavailable/mock distinctions, and canonical imports. Every Python fence must syntax-check and selected snippets must run.

## IPFSDOC-084 Write logic/proof and MCP client tutorials

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: tutorials
- Depends on: IPFSDOC-044, IPFSDOC-053, IPFSDOC-063, IPFSDOC-081
- Goal id: IPFSDOC-G092
- Outputs: docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md, docs/tutorials/MCP_CLIENT_WORKFLOW.md
- Validation: test -s docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md && test -s docs/tutorials/MCP_CLIENT_WORKFLOW.md && python -m compileall -q docs/tutorials
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/tutorials
- Parallel lane: tutorials-logic-mcp
- Resource class: cpu-small
- Predicted files: docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md, docs/tutorials/MCP_CLIENT_WORKFLOW.md
- Interfaces: LogicProofTutorial@1, MCPClientTutorial@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates verified journeys for the governed logic and service planes.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: large
- Estimated tokens: 14000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G092
- Acceptance: Show validation/formalization/prover capability and typed result handling without calling parser/model output proof; and MCP discovery/capability probe/invocation/denial/unavailable/result receipt using a bounded local route. Declare native/service prerequisites, timeouts, cleanup, redaction and side effects.

## IPFSDOC-085 Publish the example verification ledger

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: tutorials
- Depends on: IPFSDOC-083, IPFSDOC-084
- Goal id: IPFSDOC-G092
- Outputs: docs/maintenance/EXAMPLE_VERIFICATION.md
- Validation: test -s docs/maintenance/EXAMPLE_VERIFICATION.md && rg -n 'Command|Environment|Tree|Result|Deferred|Owner' docs/maintenance/EXAMPLE_VERIFICATION.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/tutorials
- Parallel lane: tutorials-verification
- Resource class: cpu-small
- Predicted files: docs/maintenance/EXAMPLE_VERIFICATION.md
- Interfaces: ExampleVerificationLedger@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates durable, reviewable evidence for examples instead of relying on prose plausibility.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 8000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G092
- Acceptance: Inventory maintained core tutorials and high-traffic snippets with owner, page, setup, exact bounded command, expected evidence, current tree, result and external/network/native/service disposition. Mark failures and deferred provisioned gates explicitly; screenshots and syntax-only checks cannot stand in for execution.

## IPFSDOC-090 Rebuild the architecture documentation hub

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: navigation
- Depends on: IPFSDOC-016, IPFSDOC-017, IPFSDOC-022, IPFSDOC-026, IPFSDOC-033, IPFSDOC-045, IPFSDOC-053, IPFSDOC-061, IPFSDOC-062
- Goal id: IPFSDOC-G111
- Outputs: docs/architecture/README.md, docs/maintenance/completion_receipts/IPFSDOC-090.md
- Validation: test -s docs/architecture/README.md && test -s docs/maintenance/completion_receipts/IPFSDOC-090.md && rg -n 'SYSTEM_CONTEXT|DOMAIN_MAP|processing|storage|retrieval|knowledge|logic|mcp|decisions|runtime' docs/architecture/README.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/navigation
- Parallel lane: navigation-architecture
- Resource class: cpu-small
- Predicted files: docs/architecture/README.md, docs/maintenance/completion_receipts/IPFSDOC-090.md
- Interfaces: ArchitectureDocumentationHub@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates the single canonical architecture entry under exclusive ownership.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 8000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G111
- Acceptance: Replace the stale short diagram/index with audience and decision routes across system, runtime, processing, storage, retrieval, knowledge, logic, MCP, security/wallet, ADRs, operations and package-local details. Clearly label current architecture versus proposed plans, implementation evidence, compatibility and history. Record the validated current tree, command, and result in the declared completion receipt.

## IPFSDOC-091 Refresh root installation and configuration pages

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: user-docs
- Depends on: IPFSDOC-063
- Goal id: IPFSDOC-G021
- Outputs: docs/installation.md, docs/configuration.md, docs/maintenance/completion_receipts/IPFSDOC-091.md
- Validation: test -s docs/installation.md && test -s docs/configuration.md && test -s docs/maintenance/completion_receipts/IPFSDOC-091.md && rg -n 'Python 3.12|CAPABILITY_INSTALLATION|CONFIGURATION_REFERENCE|optional|unavailable' docs/installation.md docs/configuration.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/install-config
- Parallel lane: user-install-integration
- Resource class: cpu-small
- Predicted files: docs/installation.md, docs/configuration.md, docs/maintenance/completion_receipts/IPFSDOC-091.md
- Interfaces: InstallationGuide@1, ConfigurationGuide@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Repairs two canonical root user pages after source-grounded leaves land.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 10000
- Estimated context tokens: 12000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G021
- Acceptance: Replace Python 3.7/3.9, nonexistent extras, placeholder organizations, obsolete CUDA advice, and incomplete environment coverage with concise verified base/capability installation and configuration precedence routes. Preserve platform/security/offline caveats and link to the detailed references. Record the validated current tree, command, and result in the declared completion receipt.

## IPFSDOC-092 Refresh getting-started and user-guide journeys

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: user-docs
- Depends on: IPFSDOC-064, IPFSDOC-082, IPFSDOC-083, IPFSDOC-084, IPFSDOC-085, IPFSDOC-091
- Goal id: IPFSDOC-G022
- Outputs: docs/getting_started.md, docs/user_guide.md, docs/maintenance/completion_receipts/IPFSDOC-092.md
- Validation: test -s docs/getting_started.md && test -s docs/user_guide.md && test -s docs/maintenance/completion_receipts/IPFSDOC-092.md && rg -n 'FIRST_DATASET_WORKFLOW|MCP_CLIENT_WORKFLOW|LOGIC_AND_PROOF_WORKFLOW|unavailable' docs/getting_started.md docs/user_guide.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/journeys
- Parallel lane: user-journey-integration
- Resource class: cpu-small
- Predicted files: docs/getting_started.md, docs/user_guide.md, docs/maintenance/completion_receipts/IPFSDOC-092.md
- Interfaces: GettingStartedGuide@1, UserGuide@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Repairs the two highest-use user journeys under one exclusive owner.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 13000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G022
- Acceptance: Remove missing legacy modules and invalid extras; provide the shortest verified first success and route Python/CLI/MCP, processing/storage, retrieval/knowledge, logic/proof and operations journeys to canonical tutorials/references. State optional requirements, side effects, cleanup, compatibility and unavailable/degraded outcomes. Record the validated current tree, command, and result in the declared completion receipt.

## IPFSDOC-093 Rebuild the glossary and authority vocabulary

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: navigation
- Depends on: IPFSDOC-013, IPFSDOC-014, IPFSDOC-015, IPFSDOC-045, IPFSDOC-053, IPFSDOC-061
- Goal id: IPFSDOC-G111
- Outputs: docs/GLOSSARY.md, docs/maintenance/completion_receipts/IPFSDOC-093.md
- Validation: test -s docs/GLOSSARY.md && test -s docs/maintenance/completion_receipts/IPFSDOC-093.md && rg -n 'capability|CID|IR|proof|policy|receipt|provenance|adapter|backend|fallback|authority' docs/GLOSSARY.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/navigation
- Parallel lane: navigation-glossary
- Resource class: cpu-small
- Predicted files: docs/GLOSSARY.md, docs/maintenance/completion_receipts/IPFSDOC-093.md
- Interfaces: DocumentationGlossary@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Gives all audiences one consistent vocabulary.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 8000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G111
- Acceptance: Define current project-specific terms, distinguish commonly conflated identity/evidence/authority/runtime states, name canonical aliases and deprecated terminology, and cross-link architecture sources. Avoid generic dictionary text and unsupported acronym expansion. Record the validated current tree, command, and result in the declared completion receipt.

## IPFSDOC-094 Publish the legacy duplicate and historical disposition map

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: navigation
- Depends on: IPFSDOC-002, IPFSDOC-004, IPFSDOC-005, IPFSDOC-090, IPFSDOC-092
- Goal id: IPFSDOC-G111
- Outputs: docs/maintenance/LEGACY_DISPOSITION.md
- Validation: test -s docs/maintenance/LEGACY_DISPOSITION.md && rg -n 'current|superseded|historical|duplicate|review-needed|replacement' docs/maintenance/LEGACY_DISPOSITION.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/navigation
- Parallel lane: navigation-legacy
- Resource class: cpu-small
- Predicted files: docs/maintenance/LEGACY_DISPOSITION.md
- Interfaces: LegacyDocumentationDisposition@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Makes the large legacy corpus navigable without destructive cleanup.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 12000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G111
- Acceptance: Classify all high-priority root plans/status/phase reports, versioned/old/backup variants, competing architecture docs, generated builds, package-local docs, and prioritized broken-link clusters with owner, status, canonical replacement and future move/delete review. Do not bulk move or delete history in this task.

## IPFSDOC-095 Rebuild root documentation navigation

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: navigation
- Depends on: IPFSDOC-064, IPFSDOC-074, IPFSDOC-082, IPFSDOC-090, IPFSDOC-091, IPFSDOC-092, IPFSDOC-093, IPFSDOC-094
- Goal id: IPFSDOC-G111
- Outputs: docs/index.md, docs/README.md, docs/DOCUMENTATION_INDEX.md, docs/maintenance/completion_receipts/IPFSDOC-095.md
- Validation: test -s docs/index.md && test -s docs/README.md && test -s docs/DOCUMENTATION_INDEX.md && test -s docs/maintenance/completion_receipts/IPFSDOC-095.md && rg -n 'Getting Started|Architecture|Developers|API|Operations|Security|Historical' docs/index.md docs/README.md docs/DOCUMENTATION_INDEX.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/navigation
- Parallel lane: navigation-root
- Resource class: cpu-small
- Predicted files: docs/index.md, docs/README.md, docs/DOCUMENTATION_INDEX.md, docs/maintenance/completion_receipts/IPFSDOC-095.md
- Interfaces: DocumentationNavigationRoot@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Integrates all leaf documentation through one late exclusive navigation owner.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 12000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G111
- Acceptance: Choose one canonical landing flow and make the three existing entry files consistent pointers rather than competing indexes. Route by audience and task to every canonical guide/domain, remove stale February/latest/count/completion claims, distinguish maintained/generated/historical material, and avoid orphaning deep component docs. Record the validated current tree, command, and result in the declared completion receipt.

## IPFSDOC-096 Run cross-guide validation and publish the quality report

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: quality
- Depends on: IPFSDOC-006, IPFSDOC-085, IPFSDOC-090, IPFSDOC-091, IPFSDOC-092, IPFSDOC-093, IPFSDOC-094, IPFSDOC-095
- Goal id: IPFSDOC-G112
- Outputs: docs/maintenance/QUALITY_REPORT.md
- Validation: python docs/maintenance/check_docs.py --root docs --report docs/maintenance/QUALITY_REPORT.md && test -s docs/maintenance/QUALITY_REPORT.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/release-quality
- Parallel lane: quality-integration
- Resource class: cpu-small
- Predicted files: docs/maintenance/QUALITY_REPORT.md
- Interfaces: DocumentationQualityReport@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Creates the reproducible pre-release quality gate.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 12000
- Estimated context tokens: 16000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G112
- Acceptance: Run deterministic local link/anchor, path/module, metadata, canonical coverage, duplicate authority, code-fence syntax, tutorial ledger, and authority-claim checks on the integrated tree. Report exact command/tree/counts, allowlisted historical findings, P0/P1 failures and optional build gaps; do not hide failures by expanding allowlists.

## IPFSDOC-097 Publish documentation maintenance cadence and ownership

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: governance
- Depends on: IPFSDOC-003, IPFSDOC-006, IPFSDOC-096
- Goal id: IPFSDOC-G112
- Outputs: docs/maintenance/README.md
- Validation: test -s docs/maintenance/README.md && rg -n 'owner|cadence|trigger|generated|drift|release|archive' docs/maintenance/README.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/release-quality
- Parallel lane: maintenance-governance
- Resource class: cpu-small
- Predicted files: docs/maintenance/README.md
- Interfaces: DocumentationMaintenanceLifecycle@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Prevents the renewed corpus from immediately becoming another point-in-time snapshot.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: small
- Estimated tokens: 6000
- Estimated context tokens: 12000
- Estimated validation seconds: 180
- Merge fate: objective/IPFSDOC-G112
- Acceptance: Define owners, routine and change-triggered reviews, generated-reference refresh, example revalidation, drift triage, release checks, archive/disposition review, exception expiry, and how product changes must update architecture/ADR/API/user docs. Link all v1 baseline and quality artifacts.

## IPFSDOC-098 Publish provisioned build disposition and final release evidence

- Status: todo
- Completion: artifact
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: documentation-release
- Depends on: IPFSDOC-096, IPFSDOC-097
- Goal id: IPFSDOC-G112
- Outputs: docs/maintenance/SITE_BUILD_AND_NAVIGATION.md, docs/maintenance/RELEASE_EVIDENCE.md
- Validation: test -s docs/maintenance/SITE_BUILD_AND_NAVIGATION.md && test -s docs/maintenance/RELEASE_EVIDENCE.md && rg -n 'commit|tree|child|command|result|MkDocs|limitation|review' docs/maintenance/RELEASE_EVIDENCE.md
- Board namespace: ipfs-datasets-documentation-v1
- Bundle: documentation/release
- Parallel lane: release-integration
- Resource class: cpu-small
- Predicted files: docs/maintenance/SITE_BUILD_AND_NAVIGATION.md, docs/maintenance/RELEASE_EVIDENCE.md
- Interfaces: DocumentationReleaseEvidence@1
- Allow concurrent with:
- Conflict policy: Exclusive ownership of the declared outputs. Read current code, tests, configuration, historical docs, and sibling guide outputs as evidence; do not edit production files, protected planning files, shared indexes owned by later tasks, or unrelated documentation.
- Preconditions: Declared dependencies are complete and their current-tree evidence is available. Work offline unless the task explicitly records a separately provisioned validation gate.
- Effects: Closes the documentation program with auditable evidence and an honest external build disposition.
- Evidence subset: current-tree source citations, required guide contract, focused validation command, and explicit discrepancies or unavailable/deferred gates
- Token class: medium
- Estimated tokens: 10000
- Estimated context tokens: 12000
- Estimated validation seconds: 300
- Merge fate: objective/IPFSDOC-G112
- Acceptance: Record the current MkDocs/Sphinx/navigation configuration gap, exact provisioned strict-build procedure and result, and any separately owned root config/CI follow-up without editing production code. Bind root release evidence to the current commit/tree, every child goal/task receipt, quality/example reports, zero unresolved P0/P1 drift, known limitations and reviewer disposition. Do not mark the root complete without a successful provisioned site build.
