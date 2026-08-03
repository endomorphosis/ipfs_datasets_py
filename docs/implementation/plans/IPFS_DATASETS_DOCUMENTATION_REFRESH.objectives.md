# IPFS Datasets Documentation Objective Heap

This file is the durable source of intent for the documentation renewal and
architecture-guide program. The reviewed executable projection is
`docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH.todo.md` with
task prefix `## IPFSDOC-`. The human plan is
`docs/implementation/plans/IPFS_DATASETS_DOCUMENTATION_REFRESH_PLAN_2026_08_03.md`.

The heap is authoritative. A page, task status, model response, old completion
report, or passing link check does not independently prove a goal complete.
Completion requires fresh evidence bound to the current repository tree.

## Goal tree

```text
IPFSDOC-G000  Truthful, navigable, decision-rich documentation system
|-- IPFSDOC-G010  Measured baseline and documentation governance
|   |-- IPFSDOC-G011  Inventory, drift, authority, and coverage baseline
|   `-- IPFSDOC-G012  Information architecture, style, ownership, lifecycle
|-- IPFSDOC-G020  Current product entry and user journeys
|   |-- IPFSDOC-G021  Installation, configuration, optional capabilities
|   `-- IPFSDOC-G022  Python, CLI, MCP, and workflow journeys
|-- IPFSDOC-G030  System architecture and durable design rationale
|   |-- IPFSDOC-G031  Context, domains, data flow, integration boundaries
|   `-- IPFSDOC-G032  ADR corpus and cross-cutting invariants
|-- IPFSDOC-G040  Processing, storage, and distribution architecture
|   |-- IPFSDOC-G041  Processing, conversion, multimedia, web archives
|   `-- IPFSDOC-G042  IPFS/IPLD, storage, caching, P2P, publication
|-- IPFSDOC-G050  Retrieval and knowledge intelligence architecture
|   |-- IPFSDOC-G051  Embeddings, vector stores, and search
|   `-- IPFSDOC-G052  Knowledge graphs, GraphRAG, and optimizers
|-- IPFSDOC-G060  Logic, proof, and governed authorization architecture
|   |-- IPFSDOC-G061  IRs, compilers, semantic round trips, provers
|   `-- IPFSDOC-G062  Legal/security constraints, attestations, authority
|-- IPFSDOC-G070  MCP and runtime surfaces
|   |-- IPFSDOC-G071  Tool lifecycle, registries, dispatch, transports
|   `-- IPFSDOC-G072  Policy, audit, observability, and operations
|-- IPFSDOC-G080  Developer and implementation-agent enablement
|   |-- IPFSDOC-G081  Repository map, extension recipes, testing
|   `-- IPFSDOC-G082  Agent context, invariants, troubleshooting, handoff
|-- IPFSDOC-G090  API reference, examples, and tutorials
|   |-- IPFSDOC-G091  Domain/API inventories with provenance
|   `-- IPFSDOC-G092  Executable journeys and example verification
|-- IPFSDOC-G100  Operations, security, and reliability guidance
|   |-- IPFSDOC-G101  Deployment, performance, diagnostics, recovery
|   `-- IPFSDOC-G102  Threat boundaries, audit, provenance, secrets
`-- IPFSDOC-G110  Navigation, legacy disposition, quality gates, release
    |-- IPFSDOC-G111  Canonical indexes, glossary, legacy routing
    `-- IPFSDOC-G112  Cross-guide validation and freshness closure
```

## IPFSDOC-G000 Truthful navigable decision-rich documentation system

- Status: active
- Parent:
- Fib priority: 1
- Priority: P0
- Track: documentation-program
- Bundle: documentation/root
- Parallel lane: release-integration
- Resource class: cpu-medium
- Goal: Deliver a current, source-grounded documentation system that lets users operate supported product surfaces and lets developers and agents understand domain ownership, end-to-end behavior, design rationale, invariants, extension points, failure modes, and evidence expectations.
- Evidence: 880000000000000000000
- Evidence criteria: Every child goal has a fresh terminal receipt bound to the current commit and documentation tree; canonical navigation, architecture coverage, user journeys, examples, API maps, legacy disposition, link checks, claim checks, and a provisioned site build pass with no unresolved P0/P1 drift.
- Evidence source policy: A root release receipt enumerating child receipts, commands, tree identity, limitations, and reviewer disposition qualifies. Plans, generated prose, task status, source existence, and stale reports do not.
- Outputs: docs, docs/maintenance/RELEASE_EVIDENCE.md
- Validation: test -s docs/maintenance/RELEASE_EVIDENCE.md
- Acceptance: Maintained docs describe current behavior without authority inflation; all major domains and audiences have canonical routes; design choices and invariants are explicit; examples and references are reproducible; historical material is clearly noncanonical.
- Gap task: Close the highest-priority uncovered child goal without changing production behavior or weakening evidence policy.
- Refinement: Prefer exclusive leaf pages in parallel and reserve shared indexes and release state for late single-owner tasks.
- Embedding query: ipfs datasets documentation architecture developer agent design rationale current source grounded
- AST query: ipfs_datasets_py mcp_server processors logic vector_stores knowledge_graphs

## IPFSDOC-G010 Measured baseline and documentation governance

- Status: active
- Parent: IPFSDOC-G000
- Fib priority: 1
- Priority: P0
- Track: governance
- Bundle: documentation/governance
- Parallel lane: docs-governance
- Resource class: cpu-small
- Goal: Establish a reproducible current-state baseline and the authority, organization, ownership, style, review, freshness, and deprecation rules used by all later work.
- Evidence: 880000000000000000010
- Evidence criteria: Child receipts cover a complete inventory, drift/claim matrix, domain coverage matrix, canonical taxonomy, page contract, source-authority policy, and maintenance lifecycle.
- Evidence source policy: Fresh deterministic inventories plus reviewed governance pages qualify; an old reorganization report or raw file count alone does not.
- Outputs: docs/maintenance, docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md
- Validation: test -s docs/maintenance/COVERAGE_MATRIX.md && test -s docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md
- Acceptance: Every maintained guide can identify its audience, owner, authority sources, validation, freshness state, and legacy relationship.
- Gap task: Produce the smallest missing baseline or governance artifact.
- Refinement: Inventory and policy leaves may run concurrently; join them into coverage only after both exist.
- Embedding query: documentation inventory drift governance ownership freshness source authority lifecycle
- AST query: docs mkdocs pyproject package directories

## IPFSDOC-G011 Inventory drift authority and coverage baseline

- Status: active
- Parent: IPFSDOC-G010
- Fib priority: 1
- Priority: P0
- Track: audit
- Bundle: documentation/baseline
- Parallel lane: docs-baseline
- Resource class: cpu-small
- Goal: Measure current documentation and production surfaces, classify stale or ungrounded claims, and map every major domain to current or missing canonical coverage.
- Evidence: 880000000000000000011
- Evidence criteria: Machine-reproducible counts and path inventories, a claim-level drift matrix with source references, and a domain/audience coverage matrix are current-tree bound.
- Evidence source policy: Repository scans and resolved source/test/config citations qualify; estimates copied from existing docs do not.
- Outputs: docs/maintenance/CURRENT_STATE_BASELINE.md, docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md, docs/maintenance/COVERAGE_MATRIX.md
- Validation: test -s docs/maintenance/CURRENT_STATE_BASELINE.md && test -s docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md && test -s docs/maintenance/COVERAGE_MATRIX.md
- Acceptance: The baseline separates maintained, generated, historical, duplicate, superseded, and unknown pages and prioritizes all P0/P1 truth and navigation gaps.
- Gap task: Audit the smallest unaudited domain or high-impact claim with exact evidence.
- Refinement: Split inventory, claim drift, and coverage into exclusive tasks and join only after the first two land.
- Embedding query: docs inventory stale claims drift matrix architecture coverage audience domain
- AST query: package paths imports console scripts optional dependencies tool registries

## IPFSDOC-G012 Information architecture style ownership and lifecycle

- Status: active
- Parent: IPFSDOC-G010
- Fib priority: 1
- Priority: P0
- Track: governance
- Bundle: documentation/policy
- Parallel lane: docs-policy
- Resource class: cpu-small
- Goal: Define canonical page types, stable locations, naming, templates, source citation, diagrams, examples, ownership, review cadence, freshness markers, deprecation, and archival policy.
- Evidence: 880000000000000000012
- Evidence criteria: Reviewed information-architecture and contributor contracts cover canonical-vs-historical disposition, minimum architecture sections, evidence rules, and bounded maintenance workflows.
- Evidence source policy: Policy text reviewed against the live docs tree and build conventions qualifies; generic writing advice does not.
- Outputs: docs/maintenance/INFORMATION_ARCHITECTURE.md, docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md, docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md, docs/architecture/decisions/ADR_TEMPLATE.md
- Validation: test -s docs/maintenance/INFORMATION_ARCHITECTURE.md && test -s docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md && test -s docs/architecture/decisions/ADR_TEMPLATE.md
- Acceptance: New and existing pages have one clear canonical home and a verifiable lifecycle; architecture pages explain rationale and invariants, not just component lists.
- Gap task: Define one missing page type, lifecycle state, evidence field, or ownership rule.
- Refinement: Use separate files for taxonomy, templates, and contribution workflow so initial tasks can run concurrently.
- Embedding query: documentation information architecture style guide ADR template ownership freshness archive
- AST query: docs README index nav archive reports implementation

## IPFSDOC-G020 Current product entry and user journeys

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G010, IPFSDOC-G030
- Fib priority: 1
- Priority: P0
- Track: user-docs
- Bundle: documentation/user
- Parallel lane: docs-user-integration
- Resource class: cpu-small
- Goal: Replace stale entry material with reproducible installation, configuration, Python, CLI, MCP, and end-to-end workflow guidance for currently supported surfaces.
- Evidence: 880000000000000000020
- Evidence criteria: Child receipts prove clean-environment command syntax, import examples, capability-specific installation, configuration precedence, supported journeys, failure guidance, and canonical navigation.
- Evidence source policy: Current packaging, CLI help, imports, fixtures, and bounded smoke tests qualify. Old feature counts or completion summaries do not.
- Outputs: docs/index.md, docs/getting_started.md, docs/installation.md, docs/configuration.md, docs/user_guide.md
- Validation: test -s docs/index.md && test -s docs/getting_started.md && test -s docs/installation.md && test -s docs/user_guide.md
- Acceptance: A new user can select a supported capability, install only its requirements, achieve a first success, understand unavailable/fallback behavior, and reach deeper canonical guides.
- Gap task: Repair the highest-impact broken or stale user journey with a current-tree smoke check.
- Refinement: Prepare capability and journey leaf pages before one owner updates shared entry pages.
- Embedding query: install configure quickstart Python CLI MCP ipfs datasets user journey
- AST query: pyproject project scripts __init__ __main__ cli

## IPFSDOC-G021 Installation configuration and optional capabilities

- Status: active
- Parent: IPFSDOC-G020
- Depends on: IPFSDOC-G011, IPFSDOC-G031
- Fib priority: 1
- Priority: P0
- Track: user-docs
- Bundle: documentation/install-config
- Parallel lane: docs-install
- Resource class: cpu-small
- Goal: Document Python/platform requirements, base installation, optional dependency groups, lazy initialization, environment/config precedence, external binaries, theorem-prover installation, and capability probing.
- Evidence: 880000000000000000021
- Evidence criteria: Every documented extra, console script, environment switch, and external prerequisite resolves to current packaging or implementation, with explicit offline, unavailable, and fallback states.
- Evidence source policy: `pyproject.toml`, setup metadata, dependency catalog/resolver modules, CLI help, and focused import probes qualify.
- Outputs: docs/guides/installation/CAPABILITY_INSTALLATION.md, docs/guides/installation/CONFIGURATION_REFERENCE.md, docs/installation.md, docs/configuration.md
- Validation: test -s docs/guides/installation/CAPABILITY_INSTALLATION.md && test -s docs/guides/installation/CONFIGURATION_REFERENCE.md
- Acceptance: Base installation is not confused with all capabilities; lazy or auto-install behavior and security/operational consequences are explicit; missing optional tools never appear as successful capabilities.
- Gap task: Ground one missing dependency group, configuration key, or platform prerequisite.
- Refinement: Write new references before the late refresh of the two shared root pages.
- Embedding query: optional dependencies lazy import configuration environment theorem prover install capability probe
- AST query: dependency_catalog deps_resolver lazy_dependencies auto_installer initialize

## IPFSDOC-G022 Python CLI MCP and workflow journeys

- Status: active
- Parent: IPFSDOC-G020
- Depends on: IPFSDOC-G031, IPFSDOC-G071, IPFSDOC-G091
- Fib priority: 1
- Priority: P0
- Track: user-docs
- Bundle: documentation/journeys
- Parallel lane: docs-journeys
- Resource class: cpu-small
- Goal: Provide bounded, current journeys for Python APIs, console commands, MCP discovery/invocation, processing-to-storage, retrieval, logic, and provenance workflows.
- Evidence: 880000000000000000022
- Evidence criteria: Examples import or parse against the current tree, name their optional requirements and side effects, and distinguish successful, denied, unavailable, and degraded results.
- Evidence source policy: Executed offline examples and current CLI/MCP contracts qualify; screenshots and unexecuted snippets do not.
- Outputs: docs/tutorials/FIRST_DATASET_WORKFLOW.md, docs/tutorials/MCP_CLIENT_WORKFLOW.md, docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md, docs/getting_started.md, docs/user_guide.md
- Validation: test -s docs/tutorials/FIRST_DATASET_WORKFLOW.md && test -s docs/tutorials/MCP_CLIENT_WORKFLOW.md && test -s docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md
- Acceptance: Users can choose the correct surface and follow at least one verified path through each major capability family without relying on legacy imports.
- Gap task: Add or repair one high-value journey and its bounded verification.
- Refinement: Write tutorials independently, then integrate root user pages under one owner.
- Embedding query: Python CLI MCP workflow processing storage retrieval logic provenance tutorial
- AST query: IPFSDatasets cli server client load_dataset process search

## IPFSDOC-G030 System architecture and durable design rationale

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G010
- Fib priority: 1
- Priority: P0
- Track: architecture
- Bundle: documentation/system-architecture
- Parallel lane: docs-architecture-integration
- Resource class: cpu-small
- Goal: Publish the authoritative mental model for system context, domain ownership, end-to-end flows, initialization/dependency behavior, cross-repository boundaries, and durable design decisions.
- Evidence: 880000000000000000030
- Evidence criteria: Child receipts cover every top-level production domain, supported surface, major data/control boundary, external integration, cross-cutting invariant, and initial ADR topic with code/test/config citations.
- Evidence source policy: Current tree analysis and reviewed decisions qualify; historical architecture summaries qualify only as leads verified against current sources.
- Outputs: docs/architecture/SYSTEM_CONTEXT.md, docs/architecture/DOMAIN_MAP.md, docs/architecture/END_TO_END_DATA_FLOW.md, docs/architecture/DEPENDENCY_AND_INITIALIZATION.md, docs/architecture/INTEGRATION_BOUNDARIES.md, docs/architecture/decisions
- Validation: test -s docs/architecture/SYSTEM_CONTEXT.md && test -s docs/architecture/DOMAIN_MAP.md && test -s docs/architecture/END_TO_END_DATA_FLOW.md && test -s docs/architecture/decisions/README.md
- Acceptance: A developer can locate ownership, follow data and authority, identify optional/external boundaries, and understand why core design constraints exist.
- Gap task: Document the smallest missing domain, boundary, flow, or decision with live citations.
- Refinement: System pages and ADRs use exclusive files; architecture hub integration occurs late.
- Embedding query: system context domain map data flow integration architecture decisions ipfs datasets
- AST query: package topology routers registries protocols schemas interfaces

## IPFSDOC-G031 Context domains data flow and integration boundaries

- Status: active
- Parent: IPFSDOC-G030
- Fib priority: 1
- Priority: P0
- Track: architecture
- Bundle: documentation/system-model
- Parallel lane: docs-system-model
- Resource class: cpu-small
- Goal: Explain supported entry surfaces, package/domain responsibilities, processing/retrieval/logic/MCP flows, dependency initialization, and ipfs_kit/ipfs_accelerate/external-service boundaries.
- Evidence: 880000000000000000031
- Evidence criteria: Guides enumerate all current top-level domains and show inputs, outputs, authorities, extension points, optional dependencies, failure/degradation paths, and cross-repository ownership.
- Evidence source policy: Imports, public contracts, registries, packaging, tests, and submodule integration code qualify.
- Outputs: docs/architecture/SYSTEM_CONTEXT.md, docs/architecture/DOMAIN_MAP.md, docs/architecture/END_TO_END_DATA_FLOW.md, docs/architecture/DEPENDENCY_AND_INITIALIZATION.md, docs/architecture/INTEGRATION_BOUNDARIES.md
- Validation: test -s docs/architecture/SYSTEM_CONTEXT.md && test -s docs/architecture/DOMAIN_MAP.md && test -s docs/architecture/INTEGRATION_BOUNDARIES.md
- Acceptance: Boundaries do not imply ownership the repository does not have; fallback and compatibility layers are visibly distinct from canonical authorities.
- Gap task: Add one uncovered domain or cross-boundary flow using exact paths and contracts.
- Refinement: Assign each page to an exclusive parallel task; join cross-links later.
- Embedding query: package map system context end to end flow dependency initialization submodule integration
- AST query: router_deps ipfs_backend_router embedding_router multimodal_router submodule_registry

## IPFSDOC-G032 ADR corpus and cross-cutting invariants

- Status: active
- Parent: IPFSDOC-G030
- Depends on: IPFSDOC-G031
- Fib priority: 1
- Priority: P0
- Track: decisions
- Bundle: documentation/adrs
- Parallel lane: docs-adrs
- Resource class: cpu-small
- Goal: Record why the system uses content identity/provenance, lazy optional capabilities, layered contract authority, registries/adapters, fail-closed mediation, explicit degradation, and historical compatibility boundaries.
- Evidence: 880000000000000000032
- Evidence criteria: An indexed ADR corpus records context, decision, considered alternatives, consequences, invariants, status, owners, and current implementation evidence for every initial decision family.
- Evidence source policy: Reviewed ADRs grounded in current code/tests qualify; retroactive rationalization without evidence is marked proposed or unknown.
- Outputs: docs/architecture/decisions/README.md, docs/architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md, docs/architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md, docs/architecture/decisions/ADR-003-LAYERED-AUTHORITY.md, docs/architecture/decisions/ADR-004-REGISTRIES-AND-ADAPTERS.md, docs/architecture/decisions/ADR-005-FAIL-CLOSED-DEGRADATION.md
- Validation: test -s docs/architecture/decisions/README.md && test -s docs/architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md && test -s docs/architecture/decisions/ADR-005-FAIL-CLOSED-DEGRADATION.md
- Acceptance: Future changes can identify which invariant they affect and which evidence is required to revise a decision.
- Gap task: Ground one missing decision or correct one unsupported rationale.
- Refinement: ADR topic groups can run independently; one late task owns the decision index.
- Embedding query: ADR content identity provenance lazy capabilities authority registry adapter fail closed degradation
- AST query: cid_utils lazy import capability probe registry policy receipt

## IPFSDOC-G040 Processing storage and distribution architecture

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G031
- Fib priority: 3
- Priority: P1
- Track: data-platform
- Bundle: documentation/data-platform
- Parallel lane: docs-data-platform
- Resource class: cpu-small
- Goal: Explain how sources become normalized artifacts, how artifacts are identified and stored, and how caching, P2P, archive, publication, and external backends participate without obscuring ownership or failure modes.
- Evidence: 880000000000000000040
- Evidence criteria: Child receipts trace representative ingestion-to-storage and storage-to-distribution paths and enumerate registries, protocols, backends, extension points, resource limits, and degradation behavior.
- Evidence source policy: Current processor/storage/router contracts and tests qualify; feature lists without flow or failure evidence do not.
- Outputs: docs/architecture/processing, docs/architecture/storage
- Validation: test -s docs/architecture/processing/README.md && test -s docs/architecture/storage/README.md
- Acceptance: Developers can add or operate a processor/storage path without bypassing content identity, provenance, resource controls, or backend capability checks.
- Gap task: Document one missing processing or distribution path with a verified contract.
- Refinement: Processing and storage subgoals execute in parallel on exclusive directories.
- Embedding query: ingestion processor conversion multimedia archive IPFS IPLD cache P2P distribution
- AST query: processors registry protocol storage engine ipfs backend p2p workflow

## IPFSDOC-G041 Processing conversion multimedia and web archives

- Status: active
- Parent: IPFSDOC-G040
- Fib priority: 3
- Priority: P1
- Track: processing
- Bundle: documentation/processing
- Parallel lane: docs-processing
- Resource class: cpu-small
- Goal: Document processor contracts and registry, input detection, file conversion, PDF/OCR/multimedia, web archival and scraping, legal-data ingestion, batching, resource controls, and provenance handoff.
- Evidence: 880000000000000000041
- Evidence criteria: Architecture pages cite live protocols, registries, implementations, tests, optional dependencies, and representative failure paths for each processing family.
- Evidence source policy: Current source and focused tests qualify; historical migration plans alone do not.
- Outputs: docs/architecture/processing/README.md, docs/architecture/processing/PROCESSOR_PIPELINE.md, docs/architecture/processing/FILE_AND_MULTIMEDIA.md, docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md
- Validation: test -s docs/architecture/processing/PROCESSOR_PIPELINE.md && test -s docs/architecture/processing/FILE_AND_MULTIMEDIA.md && test -s docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md
- Acceptance: Guides identify canonical vs compatibility processors, synchronous/async expectations, optional native/tool requirements, output/provenance contracts, and safe extension seams.
- Gap task: Ground one missing processor family or ambiguous registry path.
- Refinement: Pipeline, file/media, and web/legal pages have separate owners.
- Embedding query: processor registry pipeline file conversion multimedia OCR PDF web archive legal scraper
- AST query: ProcessorProtocol registry UniversalProcessor FileConverter web_archiving legal_scrapers

## IPFSDOC-G042 IPFS IPLD storage caching P2P and publication

- Status: active
- Parent: IPFSDOC-G040
- Fib priority: 3
- Priority: P1
- Track: storage-distribution
- Bundle: documentation/storage
- Parallel lane: docs-storage
- Resource class: cpu-small
- Goal: Explain content addressing, CID/IPLD/CAR representation, storage engines and routers, vector/IPLD boundaries, caches, pinning, IPFS cluster, libp2p/P2P workflows, Hugging Face publication, and offline/degraded operation.
- Evidence: 880000000000000000042
- Evidence criteria: Guides distinguish identifiers from locations and receipts, describe backend selection and consistency, and cite exact storage, cache, P2P, and publishing contracts and tests.
- Evidence source policy: Current codec/router/backend code and fixtures qualify; generic IPFS descriptions do not.
- Outputs: docs/architecture/storage/README.md, docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md, docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md, docs/architecture/storage/P2P_AND_PUBLICATION.md
- Validation: test -s docs/architecture/storage/CONTENT_ADDRESSING_AND_IPLD.md && test -s docs/architecture/storage/STORAGE_CACHING_AND_BACKENDS.md && test -s docs/architecture/storage/P2P_AND_PUBLICATION.md
- Acceptance: The corpus states canonical byte/identity boundaries, backend and cache trust assumptions, pin/distribution behavior, optional network prerequisites, and failure/recovery paths.
- Gap task: Document one missing codec, backend, cache, or distribution boundary.
- Refinement: Identity, backend/cache, and P2P/publication pages can execute concurrently.
- Embedding query: content address CID IPLD CAR storage cache IPFS cluster libp2p Hugging Face
- AST query: cid_utils ipld storage_engine cache_manager ipfs_cluster p2p_networking publisher

## IPFSDOC-G050 Retrieval and knowledge intelligence architecture

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G031, IPFSDOC-G040
- Fib priority: 3
- Priority: P1
- Track: retrieval-knowledge
- Bundle: documentation/retrieval-knowledge
- Parallel lane: docs-retrieval-knowledge
- Resource class: cpu-small
- Goal: Explain how embeddings, sparse/dense vectors, vector stores, search, knowledge graphs, GraphRAG, reasoning, and optimization compose while retaining backend, identity, provenance, and evaluation boundaries.
- Evidence: 880000000000000000050
- Evidence criteria: Child receipts trace indexing and query flows, map canonical interfaces and backend adapters, and identify quality, consistency, optional-model, and degradation contracts.
- Evidence source policy: Current schemas, base classes, routers, engines, optimizers, and tests qualify.
- Outputs: docs/architecture/retrieval, docs/architecture/knowledge
- Validation: test -s docs/architecture/retrieval/README.md && test -s docs/architecture/knowledge/README.md
- Acceptance: Developers can select or extend a retrieval/knowledge path without conflating embeddings, indexes, graph facts, model proposals, critic scores, or proof.
- Gap task: Document the smallest missing retrieval or knowledge contract.
- Refinement: Retrieval and knowledge subgoals run concurrently.
- Embedding query: embeddings vectors semantic search knowledge graph GraphRAG optimizer provenance
- AST query: embeddings vector_stores search knowledge_graphs optimizers

## IPFSDOC-G051 Embeddings vector stores and search

- Status: active
- Parent: IPFSDOC-G050
- Fib priority: 3
- Priority: P1
- Track: retrieval
- Bundle: documentation/retrieval
- Parallel lane: docs-retrieval
- Resource class: cpu-small
- Goal: Document embedding generation/routing, sparse and dense representations, vector-store protocols and backends, IPLD vector persistence, indexing, semantic/hybrid search, query optimization, and streaming behavior.
- Evidence: 880000000000000000051
- Evidence criteria: Pages enumerate canonical schemas/interfaces, backend capability differences, identity/provenance, lifecycle, consistency, optional dependencies, and verified query paths.
- Evidence source policy: Base classes, schemas, engine/router code, backend tests, and bounded examples qualify.
- Outputs: docs/architecture/retrieval/README.md, docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md, docs/architecture/retrieval/VECTOR_STORES.md, docs/architecture/retrieval/SEARCH_AND_QUERY.md
- Validation: test -s docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md && test -s docs/architecture/retrieval/VECTOR_STORES.md && test -s docs/architecture/retrieval/SEARCH_AND_QUERY.md
- Acceptance: Backend-specific features are not presented as universal; fallback mocks/stubs are identified; index identity, updates, deletion, and failure behavior are explicit.
- Gap task: Add one missing backend, query, or index lifecycle contract.
- Refinement: Embedding, vector-store, and search pages use separate output files.
- Embedding query: embedding router sparse dense vector store FAISS Qdrant Elasticsearch IPLD semantic search
- AST query: EmbeddingsEngine BaseVectorStore VectorStoreEngine QueryOptimizer SearchEngine

## IPFSDOC-G052 Knowledge graphs GraphRAG and optimizers

- Status: active
- Parent: IPFSDOC-G050
- Fib priority: 3
- Priority: P1
- Track: knowledge-optimization
- Bundle: documentation/knowledge
- Parallel lane: docs-knowledge
- Resource class: cpu-small
- Goal: Document extraction, graph model/storage/query/indexing/transactions/lineage/reasoning, GraphRAG orchestration, optimizer protocols, generate-critique-optimize loops, and evaluation/quality authority.
- Evidence: 880000000000000000052
- Evidence criteria: Pages map current modular packages and legacy surfaces, trace source-to-graph-to-retrieval flows, and distinguish extracted candidates, persisted graph facts, reasoning results, critic scores, and validation.
- Evidence source policy: Current package contracts, schemas, optimizer base types, tests, and benchmark policy qualify.
- Outputs: docs/architecture/knowledge/README.md, docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md, docs/architecture/knowledge/GRAPHRAG.md, docs/architecture/knowledge/OPTIMIZATION_LOOPS.md
- Validation: test -s docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md && test -s docs/architecture/knowledge/GRAPHRAG.md && test -s docs/architecture/knowledge/OPTIMIZATION_LOOPS.md
- Acceptance: The architecture exposes data authority, transaction/lineage behavior, optional model dependencies, optimizer contracts, quality evidence, and extension points without claiming model output is truth or proof.
- Gap task: Document one missing graph lifecycle or optimizer boundary with live evidence.
- Refinement: Graph lifecycle, GraphRAG, and optimizer pages execute independently.
- Embedding query: knowledge graph extraction query storage transaction lineage GraphRAG optimizer critic
- AST query: knowledge_graphs transactions lineage graphrag BaseOptimizer OptimizationContext

## IPFSDOC-G060 Logic proof and governed authorization architecture

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G031, IPFSDOC-G032
- Fib priority: 1
- Priority: P0
- Track: logic-proof-policy
- Bundle: documentation/logic
- Parallel lane: docs-logic-integration
- Resource class: cpu-small
- Goal: Explain the bespoke IR, formalization, reasoning, prover, proof-artifact, legal/security constraint, and authorization layers with exact result-authority and fail-closed boundaries.
- Evidence: 880000000000000000060
- Evidence criteria: Child receipts map logic families and profiles, source/target IRs, compiler/decompiler and semantic-round-trip flows, prover capability boundaries, proof/attestation identities, constraint selection, policy composition, and authorization receipts.
- Evidence source policy: Current schemas, protocols, compilers, verifiers, policy code, tests, and benchmark receipts qualify. Parser success, generated formulas, similarity, and model confidence do not substitute for stronger authority.
- Outputs: docs/architecture/logic
- Validation: test -s docs/architecture/logic/README.md && test -s docs/architecture/logic/RESULT_AUTHORITY.md
- Acceptance: Readers can tell what each layer proves or does not prove, which backend is authoritative, how unsupported/unavailable outcomes propagate, and where side effects are finally admitted.
- Gap task: Document the smallest missing logic, proof, constraint, or authorization boundary without inflating its authority.
- Refinement: IR/prover and constraint/authorization subgoals run in parallel; shared logic index is late-owned.
- Embedding query: logic IR formal compiler prover proof attestation legal security authorization result authority
- AST query: logic ir_core integration external_provers zkp legal_ir security invocation_intent

## IPFSDOC-G061 IRs compilers semantic round trips and provers

- Status: active
- Parent: IPFSDOC-G060
- Fib priority: 1
- Priority: P0
- Track: logic-formalization
- Bundle: documentation/logic-formalization
- Parallel lane: docs-logic-formalization
- Resource class: cpu-small
- Goal: Document IR family ownership, canonical representation and identity, translation/formalization/decompilation, semantic round-trip evaluation, FOL/F-logic/TDFOL/DCEC/event-calculus profiles, external prover adapters, lazy installation, and capability/result taxonomy.
- Evidence: 880000000000000000061
- Evidence criteria: Guides trace at least one source-grounded compile/check/reconstruct path and enumerate typed results for validation, unknown, unsupported, unavailable, satisfiable/countermodel, and proved outcomes.
- Evidence source policy: Current public logic contracts, schema/codec code, compiler/prover adapters, fixtures, and focused tests qualify.
- Outputs: docs/architecture/logic/IR_FAMILY_AND_IDENTITY.md, docs/architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md, docs/architecture/logic/EXTERNAL_PROVERS.md
- Validation: test -s docs/architecture/logic/IR_FAMILY_AND_IDENTITY.md && test -s docs/architecture/logic/COMPILERS_AND_SEMANTIC_ROUND_TRIP.md && test -s docs/architecture/logic/EXTERNAL_PROVERS.md
- Acceptance: Canonical IRs are distinct from legacy/adapter forms; syntax and translation are not called proof; backend selection, trust, timeout, optional dependency, and degradation behavior are explicit.
- Gap task: Ground one missing IR family, translation edge, result type, or prover adapter.
- Refinement: IR, round-trip, and prover pages have separate owners and can execute concurrently.
- Embedding query: IR family canonical identity compiler decompiler semantic round trip FOL TDFOL DCEC prover
- AST query: ir_core converters compiler decompiler semantic_roundtrip external_provers ProverResult

## IPFSDOC-G062 Legal security constraints attestations and authority

- Status: active
- Parent: IPFSDOC-G060
- Depends on: IPFSDOC-G061
- Fib priority: 1
- Priority: P0
- Track: governed-authorization
- Bundle: documentation/logic-policy
- Parallel lane: docs-logic-policy
- Resource class: cpu-small
- Goal: Explain legal and security constraint compilation and applicability, proof corpora and caches, ZKP/attestation profiles, invocation intent, obligation and portfolio composition, side-effect-free authorization, pre-dispatch enforcement, revocation, and audit receipts.
- Evidence: 880000000000000000062
- Evidence criteria: Pages show exact identities and authorities from source inputs through constraints, evidence verification, policy decision, enforcement, and redacted receipt, including deny/unknown/unavailable/revoked behavior.
- Evidence source policy: Current schemas, trust policies, verifier/enforcement code, adversarial tests, and valid proof fixtures qualify.
- Outputs: docs/architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md, docs/architecture/logic/PROOF_ATTESTATION_AND_ZKP.md, docs/architecture/logic/GOVERNED_AUTHORIZATION.md, docs/architecture/logic/RESULT_AUTHORITY.md
- Validation: test -s docs/architecture/logic/LEGAL_AND_SECURITY_CONSTRAINTS.md && test -s docs/architecture/logic/PROOF_ATTESTATION_AND_ZKP.md && test -s docs/architecture/logic/GOVERNED_AUTHORIZATION.md && test -s docs/architecture/logic/RESULT_AUTHORITY.md
- Acceptance: Monitoring and model output cannot masquerade as proof; a proof cannot silently grant authorization; UI/MCP intent cannot bypass constraint selection, policy, or enforcement; receipts preserve identity while respecting redaction.
- Gap task: Document one missing trust, constraint, attestation, policy, or enforcement boundary with negative evidence.
- Refinement: Constraint, proof/ZKP, authorization, and result-authority pages use exclusive files.
- Embedding query: legal security constraint applicability proof corpus ZKP attestation invocation authorization enforcement
- AST query: legal_ir security proof_corpus invocation_intent policy decision cache pre_dispatch

## IPFSDOC-G070 MCP and runtime surfaces

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G031, IPFSDOC-G060
- Fib priority: 1
- Priority: P0
- Track: mcp-runtime
- Bundle: documentation/mcp
- Parallel lane: docs-mcp-integration
- Resource class: cpu-small
- Goal: Document MCP server composition, context and lifecycle, tool discovery and dispatch, hierarchical and flat registries, interfaces and identity, transports, policy/UCAN mediation, event DAGs, audit, metrics, and operator behavior.
- Evidence: 880000000000000000070
- Evidence criteria: Child receipts cover canonical launch surfaces, tool registration and invocation paths, transport parity/differences, runtime routing, authorization, receipts, health/observability, and archive/legacy dispositions.
- Evidence source policy: Current server, registry, dispatch, interface, transport, policy, and integration tests qualify. Old tool counts and catalogs are only leads.
- Outputs: docs/architecture/mcp
- Validation: test -s docs/architecture/mcp/README.md && test -s docs/architecture/mcp/SERVER_AND_DISPATCH.md
- Acceptance: Developers can add and operate a tool without duplicating registration, bypassing policy, conflating transport with contract, or treating discovery as capability success.
- Gap task: Document one missing MCP lifecycle, interface, transport, or operational boundary.
- Refinement: Server/tool/transport and policy/ops leaves execute independently; MCP hub is late-owned.
- Embedding query: MCP server tool registry dispatch interface transport P2P UCAN policy event DAG metrics
- AST query: server server_context tool_registry dispatch_pipeline interface_descriptor runtime_router transports

## IPFSDOC-G071 Tool lifecycle registries dispatch and transports

- Status: active
- Parent: IPFSDOC-G070
- Fib priority: 1
- Priority: P0
- Track: mcp-core
- Bundle: documentation/mcp-core
- Parallel lane: docs-mcp-core
- Resource class: cpu-small
- Goal: Explain server startup/context, tool discovery and metadata, hierarchical vs flat naming, category ownership, registration/import behavior, validation and dispatch, interface identity, stdio/HTTP/gRPC/MCP++/P2P transport roles, and runtime routing.
- Evidence: 880000000000000000071
- Evidence criteria: Guides trace a tool from implementation through registration, discovery, validation, dispatch, result envelope, and each supported transport, with duplicate/legacy/unavailable paths called out.
- Evidence source policy: Live server and registry code, tool package structure, interface descriptors, transport adapters, and tests qualify.
- Outputs: docs/architecture/mcp/SERVER_AND_DISPATCH.md, docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md, docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md
- Validation: test -s docs/architecture/mcp/SERVER_AND_DISPATCH.md && test -s docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md && test -s docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md
- Acceptance: Canonical and compatibility server paths are explicit; tool counts are generated or dated; import/registration side effects, schemas, aliases, routing, timeout/cancel, and transport-specific capability differences are documented.
- Gap task: Ground one missing server, registry, tool, identity, or transport path.
- Refinement: Server/dispatch, tool lifecycle, and interface/transport pages have exclusive owners.
- Embedding query: MCP server context tool registry hierarchy dispatch interface descriptor stdio HTTP gRPC P2P
- AST query: IPFSDatasetsMCPServer ToolRegistry HierarchicalToolManager dispatch tool_metadata

## IPFSDOC-G072 Policy audit observability and operations

- Status: active
- Parent: IPFSDOC-G070
- Depends on: IPFSDOC-G062, IPFSDOC-G071
- Fib priority: 1
- Priority: P0
- Track: mcp-operations
- Bundle: documentation/mcp-operations
- Parallel lane: docs-mcp-operations
- Resource class: cpu-small
- Goal: Document MCP risk scoring, UCAN/delegation, temporal/deontic policy, secrets, audit/event DAG/receipt behavior, tracing/metrics/Prometheus, health/readiness, P2P service operation, failure recovery, and bounded troubleshooting.
- Evidence: 880000000000000000072
- Evidence criteria: Guides demonstrate non-execution for blocking policy states and map correlation, redaction, health, telemetry, degradation, restart, and recovery contracts to current code/tests.
- Evidence source policy: Policy/adversarial tests, audit schemas, metric definitions, server lifecycle code, and operator commands qualify.
- Outputs: docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md, docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md, docs/guides/operations/MCP_SERVER_RUNBOOK.md
- Validation: test -s docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md && test -s docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md && test -s docs/guides/operations/MCP_SERVER_RUNBOOK.md
- Acceptance: Secrets and sensitive evidence are not exposed; monitoring is not proof; health/readiness states are exact; operators have safe start, inspect, stop, diagnose, and recover paths.
- Gap task: Ground one missing policy, audit, metric, health, or recovery contract.
- Refinement: Policy, observability, and runbook tasks write independent files.
- Embedding query: MCP policy risk UCAN temporal deontic secrets audit event DAG tracing metrics runbook
- AST query: risk_scorer ucan_delegation policy_audit_log event_dag metrics monitoring

## IPFSDOC-G080 Developer and implementation-agent enablement

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G030, IPFSDOC-G040, IPFSDOC-G050, IPFSDOC-G060, IPFSDOC-G070
- Fib priority: 1
- Priority: P0
- Track: developer-docs
- Bundle: documentation/developers
- Parallel lane: docs-developer-integration
- Resource class: cpu-small
- Goal: Give contributors and agents a reliable repository map, architectural invariants, change recipes, test/evidence selection, context-loading strategy, troubleshooting, review, and handoff contract.
- Evidence: 880000000000000000080
- Evidence criteria: Child receipts cover major extension families, nearest tests, optional dependency hygiene, identity/authority/security invariants, file ownership, failure escalation, and documentation obligations.
- Evidence source policy: Current architecture pages, package contracts, tests, CI/config, and validated recipes qualify.
- Outputs: docs/developer_guide.md, docs/developer_guides
- Validation: test -s docs/developer_guide.md && test -s docs/developer_guides/FOR_AGENTS.md && test -s docs/developer_guides/EXTENSION_RECIPES.md
- Acceptance: A bounded contributor can locate the correct owner, make a scoped change, select evidence, preserve invariants, and hand off limitations without broad repository archaeology.
- Gap task: Add the smallest missing extension recipe, invariant, or troubleshooting route.
- Refinement: Recipes, agent guide, testing, and troubleshooting are independent leaves; root developer guide is late-owned.
- Embedding query: developer guide repository map extension recipe implementation agent invariants testing troubleshooting
- AST query: package README protocols base classes registries tests conftest

## IPFSDOC-G081 Repository map extension recipes and testing

- Status: active
- Parent: IPFSDOC-G080
- Fib priority: 1
- Priority: P0
- Track: developer-workflows
- Bundle: documentation/developer-workflows
- Parallel lane: docs-developer-workflows
- Resource class: cpu-small
- Goal: Document repository layout and authority, environment setup, focused test selection, and recipes for processors, storage/vector backends, MCP tools, logic compilers/provers, policies, and documentation.
- Evidence: 880000000000000000081
- Evidence criteria: Each recipe identifies owner interfaces, files, registration/export steps, optional dependencies, negative cases, nearest tests, integration gates, and documentation updates.
- Evidence source policy: Successful current-tree dry runs or existing representative implementations/tests qualify.
- Outputs: docs/developer_guides/REPOSITORY_MAP.md, docs/developer_guides/EXTENSION_RECIPES.md, docs/developer_guides/TESTING_AND_EVIDENCE.md, docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md
- Validation: test -s docs/developer_guides/REPOSITORY_MAP.md && test -s docs/developer_guides/EXTENSION_RECIPES.md && test -s docs/developer_guides/TESTING_AND_EVIDENCE.md
- Acceptance: Recipes do not tell contributors to use retired imports, duplicate registries, eagerly import optional stacks, bypass policy, or claim a stronger evidence class than tests establish.
- Gap task: Validate and document one missing extension workflow.
- Refinement: Repository map, recipes, testing, and docs-contributing pages have distinct owners.
- Embedding query: repository map add processor backend MCP tool compiler prover policy tests documentation
- AST query: protocol registry __init__ pyproject pytest tests unit integration

## IPFSDOC-G082 Agent context invariants troubleshooting and handoff

- Status: active
- Parent: IPFSDOC-G080
- Depends on: IPFSDOC-G081, IPFSDOC-G032
- Fib priority: 1
- Priority: P0
- Track: agent-enablement
- Bundle: documentation/agents
- Parallel lane: docs-agents
- Resource class: cpu-small
- Goal: Define the minimum context an implementation agent must read, hard architectural and security invariants, safe exploration order, protected/hot files, common failure diagnosis, evidence and uncertainty reporting, and handoff format.
- Evidence: 880000000000000000082
- Evidence criteria: The guide is cross-checked against every architecture domain and includes actionable source paths, do-not-assume rules, blocker classification, and example handoffs for success, partial progress, unavailable dependencies, and product defects.
- Evidence source policy: Current architecture/ADR/test evidence and supervisor-safe workflows qualify.
- Outputs: docs/developer_guides/FOR_AGENTS.md, docs/developer_guides/TROUBLESHOOTING.md, docs/developer_guides/HANDOFF_CHECKLIST.md
- Validation: test -s docs/developer_guides/FOR_AGENTS.md && test -s docs/developer_guides/TROUBLESHOOTING.md && test -s docs/developer_guides/HANDOFF_CHECKLIST.md
- Acceptance: Agents distinguish current behavior from desired behavior, preserve identity/authority/optional-dependency boundaries, avoid unrelated edits, and report blockers with evidence rather than rewriting task criteria.
- Gap task: Add one missing invariant, diagnostic decision, or handoff case.
- Refinement: Agent invariants, troubleshooting, and handoff pages can run independently after architecture leaves exist.
- Embedding query: implementation agent context invariants protected files troubleshooting blocker evidence handoff
- AST query: package maps ADR tests config git status optional imports

## IPFSDOC-G090 API reference examples and tutorials

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G031, IPFSDOC-G040, IPFSDOC-G050, IPFSDOC-G060, IPFSDOC-G070
- Fib priority: 3
- Priority: P1
- Track: reference-examples
- Bundle: documentation/reference
- Parallel lane: docs-reference-integration
- Resource class: cpu-small
- Goal: Provide source-grounded public-domain maps, API references, executable tutorials, and a verification ledger without exposing internals as stable merely because they import.
- Evidence: 880000000000000000090
- Evidence criteria: Child receipts map intended public surfaces and stability, verify examples, identify optional requirements and side effects, and link concepts/architecture to callable references.
- Evidence source policy: AST/signature extraction, reviewed exports/protocols, docstrings cross-checked with tests, and executed examples qualify.
- Outputs: docs/api, docs/tutorials, docs/maintenance/EXAMPLE_VERIFICATION.md
- Validation: test -s docs/api/README.md && test -s docs/maintenance/EXAMPLE_VERIFICATION.md
- Acceptance: References are traceable and do not mislabel compatibility aliases or internal modules; tutorials execute in their declared environment or record an explicit provisioned gate.
- Gap task: Ground one missing public domain or broken high-value example.
- Refinement: API families and tutorial families use exclusive pages; reference index is late-owned.
- Embedding query: API reference package domain examples tutorials verification public stable compatibility
- AST query: __all__ protocols ABC classes functions signatures console scripts

## IPFSDOC-G091 Domain and API inventories with provenance

- Status: active
- Parent: IPFSDOC-G090
- Fib priority: 3
- Priority: P1
- Track: api-reference
- Bundle: documentation/api
- Parallel lane: docs-api
- Resource class: cpu-small
- Goal: Create an API/domain index and source-grounded references for core/data, processing/retrieval, knowledge/logic/proof, MCP/runtime, and operational domains, with stability and capability metadata.
- Evidence: 880000000000000000091
- Evidence criteria: Every listed symbol resolves; signature and ownership citations match the current tree; public/reviewed/compatibility/internal status and optional requirements are explicit.
- Evidence source policy: Deterministic AST/import extraction plus reviewed package contracts and tests qualify; importability alone does not establish public stability.
- Outputs: docs/api/README.md, docs/api/domains/CORE_AND_DATA.md, docs/api/domains/PROCESSING_AND_RETRIEVAL.md, docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md, docs/api/domains/MCP_AND_RUNTIME.md, docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md
- Validation: test -s docs/api/domains/CORE_AND_DATA.md && test -s docs/api/domains/PROCESSING_AND_RETRIEVAL.md && test -s docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md && test -s docs/api/domains/MCP_AND_RUNTIME.md
- Acceptance: References route readers to canonical imports and contracts, state sync/async and side-effect behavior, and avoid exhaustive internal listings with no stability promise.
- Gap task: Add one missing domain or correct one stale symbol/signature with provenance.
- Refinement: Each domain reference has an exclusive task; index integration occurs after all leaves.
- Embedding query: API inventory public imports protocols signatures domains capability optional dependency
- AST query: __all__ __getattr__ protocol abstractmethod dataclass project.scripts

## IPFSDOC-G092 Executable journeys and example verification

- Status: active
- Parent: IPFSDOC-G090
- Depends on: IPFSDOC-G091
- Fib priority: 3
- Priority: P1
- Track: tutorials-examples
- Bundle: documentation/tutorials
- Parallel lane: docs-tutorials
- Resource class: cpu-small
- Goal: Provide minimal offline examples and capability-specific tutorials for datasets, processing/storage, retrieval/knowledge, logic/proof, and MCP while maintaining a command/result/environment verification ledger.
- Evidence: 880000000000000000092
- Evidence criteria: Every maintained example has an owner, source page, setup, bounded command, expected evidence, last verified tree, and disposition for network/native/service prerequisites.
- Evidence source policy: Executed commands or syntax/import checks with exact limitations qualify; plausible snippets and screenshots do not.
- Outputs: docs/tutorials/FIRST_DATASET_WORKFLOW.md, docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md, docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md, docs/tutorials/MCP_CLIENT_WORKFLOW.md, docs/maintenance/EXAMPLE_VERIFICATION.md
- Validation: test -s docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md && test -s docs/maintenance/EXAMPLE_VERIFICATION.md
- Acceptance: Examples avoid undeclared downloads and side effects, expose unavailable/degraded outcomes, use canonical imports, and never present mocked or candidate results as production success.
- Gap task: Verify or retire one unverified maintained example.
- Refinement: Tutorial files run in parallel; one late ledger task records all receipts.
- Embedding query: executable examples offline dataset retrieval knowledge logic proof MCP verification ledger
- AST query: examples imports main async run client server

## IPFSDOC-G100 Operations security and reliability guidance

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G031, IPFSDOC-G042, IPFSDOC-G062, IPFSDOC-G072
- Fib priority: 3
- Priority: P1
- Track: operations-security
- Bundle: documentation/operations-security
- Parallel lane: docs-operations-security
- Resource class: cpu-small
- Goal: Publish source-grounded deployment, configuration, performance, observability, diagnostics, recovery, threat-boundary, secrets, audit, provenance, and incident guidance.
- Evidence: 880000000000000000100
- Evidence criteria: Child receipts cover supported deployment surfaces and prerequisites, health/metrics/logs, bounded tuning, safe recovery, trust boundaries, sensitive data, credential handling, audit retention, and failure scenarios.
- Evidence source policy: Current deployment/config manifests, runtime code, tests, security controls, and measured benchmarks qualify; aspirational production-ready claims do not.
- Outputs: docs/guides/operations, docs/guides/security
- Validation: test -s docs/guides/operations/DEPLOYMENT_AND_RUNTIME.md && test -s docs/guides/security/THREAT_MODEL.md
- Acceptance: Operators can distinguish supported, optional, experimental, and unavailable paths; destructive or external-effect steps carry preconditions, confirmation, rollback, and evidence.
- Gap task: Document one missing operational or security scenario with exact current support.
- Refinement: Operations and security subgoals execute concurrently.
- Embedding query: deployment performance observability diagnostics recovery threat model secrets audit provenance incident
- AST query: deployments docker configs monitoring audit security secrets error_reporting

## IPFSDOC-G101 Deployment performance diagnostics and recovery

- Status: active
- Parent: IPFSDOC-G100
- Fib priority: 3
- Priority: P1
- Track: operations
- Bundle: documentation/operations
- Parallel lane: docs-operations
- Resource class: cpu-small
- Goal: Document local/service/container/deployment modes, configuration, health and readiness, resource limits, caching/concurrency, profiling and benchmark interpretation, logging/metrics, common failures, and recoverable restart/migration paths.
- Evidence: 880000000000000000101
- Evidence criteria: Commands and manifests resolve, supported vs example deployments are labeled, tuning claims cite measurements, and diagnostic/recovery decision paths cover unavailable dependencies, storage/network failures, and partial service states.
- Evidence source policy: Current deployment files, CLI help, metrics, tests, and dated benchmark evidence qualify.
- Outputs: docs/guides/operations/DEPLOYMENT_AND_RUNTIME.md, docs/guides/operations/PERFORMANCE_AND_CAPACITY.md, docs/guides/operations/DIAGNOSTICS_AND_RECOVERY.md
- Validation: test -s docs/guides/operations/DEPLOYMENT_AND_RUNTIME.md && test -s docs/guides/operations/PERFORMANCE_AND_CAPACITY.md && test -s docs/guides/operations/DIAGNOSTICS_AND_RECOVERY.md
- Acceptance: Runbooks avoid universal production claims, name external services and persistence, use safe inspection before mutation, and separate measured baselines from targets.
- Gap task: Ground one missing launch, metric, tuning, diagnostic, or recovery path.
- Refinement: Deployment, performance, and diagnostics pages have separate owners.
- Embedding query: deploy Docker Kubernetes service performance capacity benchmark diagnostics recovery
- AST query: deployments docker monitoring metrics profiling error_reporting config

## IPFSDOC-G102 Threat boundaries audit provenance and secrets

- Status: active
- Parent: IPFSDOC-G100
- Fib priority: 1
- Priority: P0
- Track: security
- Bundle: documentation/security
- Parallel lane: docs-security
- Resource class: cpu-small
- Goal: Document trust and threat boundaries, untrusted inputs, parser/model/backend risk, credentials/secrets, UCAN and policy, proof trust, PII/redaction, audit/provenance chains, retention, incident evidence, and responsible disclosure routes.
- Evidence: 880000000000000000102
- Evidence criteria: Threats map to current controls, assumptions, residual risks, tests, owners, and operational detection/recovery; sensitive examples contain no real credentials or private evidence.
- Evidence source policy: Current security, audit, policy, secrets, validation, and adversarial test evidence qualifies.
- Outputs: docs/guides/security/THREAT_MODEL.md, docs/guides/security/SECRETS_AND_CREDENTIALS.md, docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md
- Validation: test -s docs/guides/security/THREAT_MODEL.md && test -s docs/guides/security/SECRETS_AND_CREDENTIALS.md && test -s docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md
- Acceptance: The guides state what is and is not trusted, never confuse cryptographic identity with authorization, and define safe evidence/redaction and incident workflows.
- Gap task: Add one missing threat/control/residual-risk mapping with a current test or explicit evidence gap.
- Refinement: Threat, secrets, and audit/incident pages have exclusive owners.
- Embedding query: threat model untrusted input secrets credentials UCAN proof trust PII redaction audit incident
- AST query: security audit credential secrets ucan validators risk policy

## IPFSDOC-G110 Navigation legacy disposition quality gates and release

- Status: active
- Parent: IPFSDOC-G000
- Depends on: IPFSDOC-G010, IPFSDOC-G020, IPFSDOC-G030, IPFSDOC-G040, IPFSDOC-G050, IPFSDOC-G060, IPFSDOC-G070, IPFSDOC-G080, IPFSDOC-G090, IPFSDOC-G100
- Fib priority: 1
- Priority: P0
- Track: documentation-release
- Bundle: documentation/release
- Parallel lane: docs-release
- Resource class: cpu-small
- Goal: Integrate canonical navigation, terminology, legacy routing, quality validation, maintenance cadence, and current-tree release evidence across the completed corpus.
- Evidence: 880000000000000000110
- Evidence criteria: Child receipts prove canonical page routing, complete major-domain coverage, glossary consistency, legacy disposition, local-link closure, example verification, claim audit, optional build disposition, and release signoff.
- Evidence source policy: Deterministic checks plus reviewed current-tree release evidence qualify; leaf task completion alone does not.
- Outputs: docs/index.md, docs/README.md, docs/DOCUMENTATION_INDEX.md, docs/architecture/README.md, docs/GLOSSARY.md, docs/maintenance/LEGACY_DISPOSITION.md, docs/maintenance/QUALITY_REPORT.md, docs/maintenance/RELEASE_EVIDENCE.md
- Validation: test -s docs/maintenance/QUALITY_REPORT.md && test -s docs/maintenance/RELEASE_EVIDENCE.md
- Acceptance: No maintained page is orphaned, no major domain lacks a canonical route, no P0/P1 drift remains, historical pages are visibly noncanonical, and reproducible release checks pass.
- Gap task: Repair the highest-impact navigation, terminology, legacy, validation, or release-evidence gap.
- Refinement: Navigation, glossary, and legacy mapping may proceed separately; quality/release tasks serialize last.
- Embedding query: documentation navigation index glossary legacy disposition link validation release evidence freshness
- AST query: docs links headings nav mkdocs archive README

## IPFSDOC-G111 Canonical indexes glossary and legacy routing

- Status: active
- Parent: IPFSDOC-G110
- Fib priority: 1
- Priority: P0
- Track: information-architecture
- Bundle: documentation/navigation
- Parallel lane: docs-navigation
- Resource class: cpu-small
- Goal: Route audiences and topics through one canonical index set, define current terminology, and classify legacy/duplicate/historical/superseded pages with replacement links and owners.
- Evidence: 880000000000000000111
- Evidence criteria: Main, architecture, API, developer, and directory indexes reach every canonical page; glossary terms match architecture usage; legacy map covers root summaries and prioritized duplicate clusters.
- Evidence source policy: Link resolution and current-tree coverage matrices qualify; hand-picked navigation samples do not.
- Outputs: docs/index.md, docs/README.md, docs/DOCUMENTATION_INDEX.md, docs/architecture/README.md, docs/api/README.md, docs/GLOSSARY.md, docs/maintenance/LEGACY_DISPOSITION.md
- Validation: test -s docs/index.md && test -s docs/architecture/README.md && test -s docs/GLOSSARY.md && test -s docs/maintenance/LEGACY_DISPOSITION.md
- Acceptance: Readers can tell canonical, generated, historical, and proposed material apart; terms such as capability, CID, IR, proof, policy, receipt, provenance, adapter, backend, and fallback are not used ambiguously.
- Gap task: Route one orphan or resolve one ambiguous/superseded term/page.
- Refinement: Assign exclusive owners for architecture/API/root indexes, glossary, and legacy map, then join root navigation last.
- Embedding query: docs index canonical navigation glossary archive legacy duplicate superseded
- AST query: markdown links headings README index archive

## IPFSDOC-G112 Cross-guide validation and freshness closure

- Status: active
- Parent: IPFSDOC-G110
- Depends on: IPFSDOC-G111
- Fib priority: 1
- Priority: P0
- Track: documentation-quality
- Bundle: documentation/release-quality
- Parallel lane: docs-release
- Resource class: cpu-medium
- Goal: Validate links, referenced paths/symbols/commands, code fences, examples, claims, canonical coverage, architecture invariants, and site build; publish maintenance cadence and tree-bound release evidence.
- Evidence: 880000000000000000112
- Evidence criteria: Deterministic local checks pass, example ledger has no unresolved P0/P1 case, claim audit has no authority inflation, a provisioned site build succeeds, and release evidence binds all child receipts and known limitations.
- Evidence source policy: Exact commands, outputs, commit/tree identities, and reviewer signoff qualify. A generic statement that docs were reviewed does not.
- Outputs: docs/maintenance/README.md, docs/maintenance/QUALITY_REPORT.md, docs/maintenance/RELEASE_EVIDENCE.md
- Validation: test -s docs/maintenance/QUALITY_REPORT.md && test -s docs/maintenance/RELEASE_EVIDENCE.md
- Acceptance: The corpus is reproducibly current at the recorded tree, has an owner/cadence for future drift, and lists any optional or external validation that must be rerun in a provisioned environment.
- Gap task: Repair one failing deterministic check or explicitly provision and run one deferred required gate.
- Refinement: Run deterministic quality before the final provisioned build and release-signoff task.
- Embedding query: docs link check example validation claims architecture invariant site build release freshness
- AST query: markdown links code fences import paths commands mkdocs
