# Knowledge Graphs Production Hardening Todo Board

This is the executable projection for program `KGP`. All tasks begin pending.
The supervisor may run tasks only when their dependencies are complete and must
retain the acceptance and validation evidence in the resulting receipt.

## KGP-001 Capture failing public lifecycle contracts

- Status: completed
- Priority: P0
- Track: baseline
- Depends on:
- Goal id: KGP-G010
- Outputs: tests/knowledge_graphs/contract/test_public_lifecycle.py, docs/architecture/knowledge_graphs_contract_matrix.md
- Validation: python -m pytest -q tests/knowledge_graphs/contract/test_public_lifecycle.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/baseline/contracts
- Parallel lane: baseline-contracts
- Resource class: cpu-small
- Predicted files: tests/knowledge_graphs/contract/test_public_lifecycle.py, docs/architecture/knowledge_graphs_contract_matrix.md
- Conflict policy: Add strict black-box probes and observed expectations; do not repair production code in this task.
- Acceptance: Reproduce create/add/query/reopen/transaction behavior through Python, CLI, MCP, and MCP++ with independent calls and strict return/result assertions. Record missing create_graph, Entity signature mismatch, non-JSON query result, fresh-manager state loss, and any newly found drift. Mark expected failures with issue-linked strict xfails rather than accepting exit code 1 or arbitrary errors.

## KGP-002 Inventory graph producers, artifacts, schemas, and consumers

- Status: completed
- Priority: P0
- Track: baseline
- Depends on:
- Goal id: KGP-G010
- Outputs: docs/architecture/knowledge_graphs_inventory.md, tests/fixtures/knowledge_graphs/corpus_registry.json
- Validation: python -m pytest -q tests/knowledge_graphs/contract/test_corpus_registry.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/baseline/inventory
- Parallel lane: baseline-inventory
- Resource class: io-medium
- Predicted files: docs/architecture/knowledge_graphs_inventory.md, tests/fixtures/knowledge_graphs/corpus_registry.json, tests/knowledge_graphs/contract/test_corpus_registry.py
- Conflict policy: Read all repositories and artifacts, but do not modify generated corpora or nested repository checkouts.
- Acceptance: Inventory lift_coding, canonical ipfs_datasets_py, ipfs_accelerate_py, and 211-AI graph producers and consumers. At minimum include CVEfixes, SkillCenter, 211 retrieval/browser graphs, supervisor objective/AST/code-evidence/conflict graphs, and any other discovered graph kind. Record repository commit and cleanliness, producer and consumer paths, schema, format, counts/size when available, provenance, authoritative owner, and migration risk. Flag the stale dirty nested lift checkout as fixture-only.

## KGP-003 Ratify the canonical API, identity, and compatibility ADR

- Status: completed
- Priority: P0
- Track: architecture
- Depends on: KGP-001, KGP-002
- Goal id: KGP-G020
- Outputs: docs/architecture/knowledge_graphs_service_contract.md, docs/architecture/knowledge_graphs_compatibility.md
- Validation: python -m pytest -q tests/unit/knowledge_graphs/contracts/test_graph_target.py tests/unit/knowledge_graphs/contracts/test_result_envelope.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/control-plane/contracts
- Parallel lane: graph-contracts
- Resource class: cpu-small
- Predicted files: docs/architecture/knowledge_graphs_service_contract.md, docs/architecture/knowledge_graphs_compatibility.md, ipfs_datasets_py/knowledge_graphs/contracts
- Conflict policy: Add versioned standalone contracts; do not rewrite legacy implementations yet.
- Acceptance: Define GraphTarget, lifecycle request/result, typed errors, JSON-safe query envelope, compatibility tiers, and the one-service rule. Explicitly map legacy GraphEngine, extraction KnowledgeGraph, data_transformation IPLD graph, search GraphData/sharded CAR, and KnowledgeGraphManager into adopt/adapt/deprecate categories.

## KGP-004 Implement immutable graph revision manifests

- Status: completed
- Priority: P0
- Track: architecture
- Depends on: KGP-003
- Goal id: KGP-G020
- Outputs: ipfs_datasets_py/knowledge_graphs/contracts/manifest.py, tests/unit/knowledge_graphs/contracts/test_manifest.py
- Validation: python -m pytest -q tests/unit/knowledge_graphs/contracts/test_manifest.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/control-plane/manifest
- Parallel lane: graph-manifest
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/knowledge_graphs/contracts/manifest.py, tests/unit/knowledge_graphs/contracts/test_manifest.py
- Conflict policy: Keep codec and store implementations behind descriptors; no backend-specific imports in the contract.
- Acceptance: Add bounded, versioned, canonical graph and shard descriptors with parent, schema/ontology, graph kind, counts, partitions, indexes, provenance, checksums, codecs, storage profile, and optional root CID. Reject ambiguous IDs, unsafe paths, noncanonical values, unknown required fields, invalid counts, and checksum/CID mismatch.

## KGP-005 Build a durable graph catalog with branch-head CAS

- Status: completed
- Priority: P0
- Track: architecture
- Depends on: KGP-004
- Goal id: KGP-G020
- Outputs: ipfs_datasets_py/knowledge_graphs/catalog, tests/integration/knowledge_graphs/test_catalog_service.py
- Validation: python -m pytest -q tests/unit/knowledge_graphs/catalog tests/integration/knowledge_graphs/test_catalog_service.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/control-plane/catalog
- Parallel lane: graph-catalog
- Resource class: io-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/catalog, tests/unit/knowledge_graphs/catalog, tests/integration/knowledge_graphs/test_catalog_service.py
- Conflict policy: Use SQLite WAL only for control metadata; graph payloads remain storage-adapter owned.
- Acceptance: Persist tenant/graph lifecycle, branches, immutable revision records, head CAS, tombstones, leases, idempotency, and pin roots. Prove restart behavior, concurrent graph identity, uniqueness, atomic head movement, and deterministic typed conflicts without relying on process caches.

## KGP-006 Introduce the long-lived GraphService

- Status: completed
- Priority: P0
- Track: architecture
- Depends on: KGP-005
- Goal id: KGP-G020
- Outputs: ipfs_datasets_py/knowledge_graphs/service.py, tests/integration/knowledge_graphs/test_graph_service.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/test_graph_service.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/control-plane/service
- Parallel lane: graph-service
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/knowledge_graphs/service.py, tests/integration/knowledge_graphs/test_graph_service.py
- Conflict policy: Orchestrate existing primitives behind adapters; do not duplicate query or storage implementations.
- Acceptance: Implement create/list/describe/open/branch/delete/write/query transaction boundaries around explicit GraphTarget and catalog snapshots. Dependency injection must make authorization, storage, clock, faults, and audit testable. A new client instance can reopen committed graphs and never receives an ambient empty graph.

## KGP-007 Specify and implement durable MVCC and WAL

- Status: completed
- Priority: P0
- Track: durability
- Depends on: KGP-006
- Goal id: KGP-G030
- Outputs: ipfs_datasets_py/knowledge_graphs/transactions, tests/unit/knowledge_graphs/test_mvcc_wal.py
- Validation: python -m pytest -q tests/unit/knowledge_graphs/test_mvcc_wal.py tests/unit/knowledge_graphs/test_wal_invariants.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/transactions/mvcc
- Parallel lane: graph-mvcc
- Resource class: io-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/transactions, tests/unit/knowledge_graphs/test_mvcc_wal.py
- Conflict policy: Replace incompatible private-field coupling with public store/catalog protocols; preserve legacy API through an adapter.
- Acceptance: Add snapshot revisions, staged deltas, prepare/publish/complete WAL states, optimistic head CAS, graph-scoped lease fencing, and idempotent replay. Define exact recovery actions at every durable boundary and bound WAL records.

## KGP-008 Prove multi-process concurrency and crash recovery

- Status: completed
- Priority: P0
- Track: durability
- Depends on: KGP-007, KGP-010
- Goal id: KGP-G030
- Outputs: tests/integration/knowledge_graphs/concurrency, tests/chaos/knowledge_graphs/test_crash_recovery.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/concurrency tests/chaos/knowledge_graphs/test_crash_recovery.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/transactions/recovery
- Parallel lane: graph-recovery
- Resource class: cpu-medium
- Predicted files: tests/integration/knowledge_graphs/concurrency, tests/chaos/knowledge_graphs/test_crash_recovery.py
- Conflict policy: Use fault injection and subprocess fixtures; no timing-only assertions.
- Acceptance: Exercise at least 16 graph IDs and multiple tenants with readers/writers in threads and processes. Kill at every WAL/publication boundary and prove only old or fully committed heads are visible. Verify duplicate retry, stale fencing epoch, conflict, compaction snapshot, and cross-tenant isolation invariants.

## KGP-009 Implement the versioned ParquetGraphStore

- Status: completed
- Priority: P0
- Track: storage
- Depends on: KGP-004
- Goal id: KGP-G040
- Outputs: ipfs_datasets_py/knowledge_graphs/storage/parquet.py, tests/contract/knowledge_graphs/storage/test_parquet.py
- Validation: python -m pytest -q tests/contract/knowledge_graphs/storage/test_parquet.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/storage/parquet
- Parallel lane: parquet-store
- Resource class: io-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/storage/parquet.py, tests/contract/knowledge_graphs/storage/test_parquet.py
- Conflict policy: Keep catalog control metadata out of Parquet; publish immutable revision directories atomically.
- Acceptance: Store normalized nodes, edges, adjacency, properties, and indexes with schema versions, bounded row groups, statistics, checksums, predicate pushdown, schema evolution, atomic temp/fsync/rename publication, restart verification, and corrupt/truncated file detection.

## KGP-010 Implement the direct IPFS/IPLD GraphStore

- Status: completed
- Priority: P0
- Track: storage
- Depends on: KGP-004
- Goal id: KGP-G040
- Outputs: ipfs_datasets_py/knowledge_graphs/storage/ipld_store.py, tests/contract/knowledge_graphs/storage/test_ipld.py
- Validation: python -m pytest -q tests/contract/knowledge_graphs/storage/test_ipld.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/storage/ipld
- Parallel lane: ipld-store
- Resource class: io-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/storage/ipld_store.py, tests/contract/knowledge_graphs/storage/test_ipld.py
- Conflict policy: Adapt the router in ipld_backend; do not preserve its unused namespace as a false catalog.
- Acceptance: Store canonical DAG-CBOR manifests/indexes and CAR payload objects, verify bytes against CID after every fetch, support offline CAR round trips, expose pin/unpin/stat capabilities, map Kubo errors to shared typed errors, and prove restart/read behavior with a real daemon when available plus deterministic doubles.

## KGP-011 Implement the ipfs_kit_py GraphStore adapter

- Status: completed
- Priority: P0
- Track: storage
- Depends on: KGP-010
- Goal id: KGP-G040
- Outputs: ipfs_datasets_py/knowledge_graphs/storage/ipfs_kit.py, tests/contract/knowledge_graphs/storage/test_ipfs_kit.py
- Validation: python -m pytest -q tests/contract/knowledge_graphs/storage/test_ipfs_kit.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/storage/ipfs-kit
- Parallel lane: ipfs-kit-store
- Resource class: io-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/storage/ipfs_kit.py, tests/contract/knowledge_graphs/storage/test_ipfs_kit.py
- Conflict policy: Negotiate explicit capabilities; do not silently fall back based only on import success.
- Acceptance: Match the shared GraphStore contract through ipfs_kit_py for put/get/stat/pin/unpin/CAR and cancellation. Report unavailable capabilities before mutation, preserve CID verification and typed errors, and pass the same restart/corruption/idempotency vectors as the direct adapter.

## KGP-012 Add verified hybrid cache, reachability, pin, and GC policy

- Status: completed
- Priority: P0
- Track: storage
- Depends on: KGP-005, KGP-009, KGP-010, KGP-011
- Goal id: KGP-G040
- Outputs: ipfs_datasets_py/knowledge_graphs/storage/hybrid.py, ipfs_datasets_py/knowledge_graphs/storage/gc.py, tests/integration/knowledge_graphs/test_pin_gc.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/test_pin_gc.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/storage/lifecycle
- Parallel lane: storage-lifecycle
- Resource class: io-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/storage/hybrid.py, ipfs_datasets_py/knowledge_graphs/storage/gc.py, tests/integration/knowledge_graphs/test_pin_gc.py
- Conflict policy: GC only immutable objects proven unreachable from catalog roots and active leases; default to dry-run.
- Acceptance: Verify cached objects against descriptor/CID, use atomic cache writes and bounded eviction, record authoritative copy, keep every branch/tag/snapshot/lease root reachable and pinned, identify only abandoned staged objects for collection, and prove dry-run plus interrupted-GC recovery.

## KGP-013 Define the sharded graph manifest v2

- Status: pending
- Priority: P0
- Track: query
- Depends on: KGP-004, KGP-010
- Goal id: KGP-G050
- Outputs: ipfs_datasets_py/knowledge_graphs/storage/sharding/manifest.py, tests/unit/knowledge_graphs/storage/sharding/test_manifest.py
- Validation: python -m pytest -q tests/unit/knowledge_graphs/storage/sharding/test_manifest.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/query-sharding/manifest
- Parallel lane: shard-manifest
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/knowledge_graphs/storage/sharding/manifest.py, tests/unit/knowledge_graphs/storage/sharding/test_manifest.py
- Conflict policy: Preserve a compatibility reader for search.graph_query.sharded_car v1 before adding v2 fields.
- Acceptance: Define bounded v2 virtual/physical shard, rendezvous routing, explicit cross-shard adjacency, schema/index version, statistics, checksums/CIDs, bloom/index bucket, codec, and provenance descriptors. Golden fixtures prove deterministic serialization and v1 read compatibility.

## KGP-014 Implement v2 routing, publishing, and cross-shard traversal

- Status: pending
- Priority: P0
- Track: query
- Depends on: KGP-013
- Goal id: KGP-G050
- Outputs: ipfs_datasets_py/knowledge_graphs/storage/sharding, tests/integration/knowledge_graphs/test_sharded_query.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/test_sharded_query.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/query-sharding/runtime
- Parallel lane: shard-runtime
- Resource class: io-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/storage/sharding, tests/integration/knowledge_graphs/test_sharded_query.py
- Conflict policy: Reuse sharded_car publisher/backend algorithms through adapters; delete nothing until parity passes.
- Acceptance: Publish bounded CAR shards and index buckets, route normalized IDs deterministically, retain incoming/outgoing cross-shard edges, verify all fetched blocks, prefetch within budget, tolerate missing/corrupt/slow shards with typed partial/failure policy, and demonstrate limited movement when physical shard count changes.

## KGP-015 Consolidate one GraphQueryBackend and executor

- Status: pending
- Priority: P0
- Track: query
- Depends on: KGP-006, KGP-009, KGP-014
- Goal id: KGP-G050
- Outputs: ipfs_datasets_py/knowledge_graphs/query/backend.py, ipfs_datasets_py/knowledge_graphs/query/executor.py, tests/contract/knowledge_graphs/test_query_backend.py
- Validation: python -m pytest -q tests/contract/knowledge_graphs/test_query_backend.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/query-sharding/backend
- Parallel lane: query-backend
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/query/backend.py, ipfs_datasets_py/knowledge_graphs/query/executor.py, tests/contract/knowledge_graphs/test_query_backend.py
- Conflict policy: Put existing Cypher IR, hybrid search, and sharded CAR behind adapters; do not create another graph model.
- Acceptance: One target-bound protocol implements scans, lookup, neighbors, paths, Cypher IR, hybrid/vector and explicit federation. Local Parquet and sharded IPFS return canonical equivalent rows. Distributed execution uses declared targets, never a newly constructed empty KnowledgeGraph.

## KGP-016 Enforce query budgets, cursors, cancellation, and streaming

- Status: pending
- Priority: P0
- Track: query
- Depends on: KGP-015
- Goal id: KGP-G050
- Outputs: ipfs_datasets_py/knowledge_graphs/query/runtime.py, tests/knowledge_graphs/contract/test_query_budgets.py
- Validation: python -m pytest -q tests/knowledge_graphs/contract/test_query_budgets.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/query-sharding/budgets
- Parallel lane: query-budgets
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/knowledge_graphs/query/runtime.py, tests/knowledge_graphs/contract/test_query_budgets.py
- Conflict policy: Budget enforcement belongs below every transport; wrappers may only narrow limits.
- Acceptance: Enforce row, byte, time, depth, fan-out, memory, and shard-fetch limits; propagate cancellation; emit bounded streaming pages; bind opaque cursors to target revision/query/authorization; reject cursor replay against another graph or revision; serialize statistics and typed limit errors.

## KGP-017 Publish the stable Python package API

- Status: pending
- Priority: P0
- Track: interfaces
- Depends on: KGP-006, KGP-016
- Goal id: KGP-G060
- Outputs: ipfs_datasets_py/knowledge_graphs/__init__.py, ipfs_datasets_py/knowledge_graphs/client.py, tests/knowledge_graphs/conformance/test_python.py
- Validation: python -m pytest -q tests/knowledge_graphs/conformance/test_python.py tests/unit/knowledge_graphs/test_public_api_surface.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/surfaces/python
- Parallel lane: python-surface
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/knowledge_graphs/__init__.py, ipfs_datasets_py/knowledge_graphs/client.py, tests/knowledge_graphs/conformance/test_python.py
- Conflict policy: Preserve legacy imports with warnings/adapters according to the compatibility ADR.
- Acceptance: Export versioned Client/AsyncClient, GraphTarget, transactions, results, and typed errors. Clients share configured service/catalog state, reopen after restart, expose sync/async streaming and context management, and do not make optional backends import-time requirements.

## KGP-018 Replace the graph CLI with GraphService commands

- Status: pending
- Priority: P0
- Track: interfaces
- Depends on: KGP-017
- Goal id: KGP-G060
- Outputs: ipfs_datasets_py/ipfs_datasets_cli.py, tests/cli/test_graph_commands.py, tests/knowledge_graphs/conformance/test_cli.py
- Validation: python -m pytest -q tests/cli/test_graph_commands.py tests/knowledge_graphs/conformance/test_cli.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/surfaces/cli
- Parallel lane: cli-surface
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/ipfs_datasets_cli.py, tests/cli/test_graph_commands.py, tests/knowledge_graphs/conformance/test_cli.py
- Conflict policy: Require strict exit codes and JSON schema; remove permissive success-or-failure assertions.
- Acceptance: Implement graph create/list/describe/write/query/transaction/branch/delete/import/export/verify commands with tenant/graph/revision/store selectors, stdin/streaming, JSON and table output, stable exit codes, and independent-process persistence. All applicable shared vectors match Python results/errors.

## KGP-019 Route MCP and MCP++ graph tools through a persistent service

- Status: pending
- Priority: P0
- Track: interfaces
- Depends on: KGP-017
- Goal id: KGP-G060
- Outputs: ipfs_datasets_py/mcp_server/tools/graph_tools, ipfs_datasets_py/mcp_server, tests/knowledge_graphs/conformance/test_mcp.py
- Validation: python -m pytest -q tests/knowledge_graphs/conformance/test_mcp.py tests/mcp/test_graph_tools.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/surfaces/mcp
- Parallel lane: mcp-surface
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/mcp_server/tools/graph_tools, ipfs_datasets_py/mcp_server, tests/knowledge_graphs/conformance/test_mcp.py
- Conflict policy: Resolve a server-owned GraphService from request context; never instantiate one manager per tool invocation.
- Acceptance: Every graph tool requires an explicit target, returns canonical JSON-safe envelopes/errors, preserves transactions and cursors across calls, supports streaming/cancellation, and declares MCP++ resource/effect metadata. Independent clients cannot observe another tenant without authorization.

## KGP-020 Build exact cross-surface conformance vectors

- Status: pending
- Priority: P0
- Track: interfaces
- Depends on: KGP-018, KGP-019
- Goal id: KGP-G060
- Outputs: tests/knowledge_graphs/conformance, tests/fixtures/knowledge_graphs/conformance
- Validation: python -m pytest -q tests/knowledge_graphs/conformance
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/surfaces/conformance
- Parallel lane: surface-conformance
- Resource class: cpu-medium
- Predicted files: tests/knowledge_graphs/conformance, tests/fixtures/knowledge_graphs/conformance
- Conflict policy: Keep vectors transport-neutral and compare canonical decoded envelopes.
- Acceptance: Execute the same lifecycle, mutation, Cypher, traversal, hybrid, pagination, transaction, conflict, restart, invalid-input, unavailable-backend, and limit vectors over Python, CLI, MCP, and MCP++. Require exact rows/revision/error codes and normalized metadata; no surface-specific exception waiver.

## KGP-021 Define graph UCAN resources, abilities, and caveats

- Status: completed
- Priority: P0
- Track: security
- Depends on: KGP-003
- Goal id: KGP-G070
- Outputs: ipfs_datasets_py/knowledge_graphs/auth/contracts.py, docs/architecture/knowledge_graphs_ucan.md, tests/security/knowledge_graphs/test_ucan_contracts.py
- Validation: python -m pytest -q tests/security/knowledge_graphs/test_ucan_contracts.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/ucan/contracts
- Parallel lane: ucan-contracts
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/knowledge_graphs/auth/contracts.py, docs/architecture/knowledge_graphs_ucan.md, tests/security/knowledge_graphs/test_ucan_contracts.py
- Conflict policy: Extend the existing UCAN implementation via explicit adapters; do not invent a token format.
- Acceptance: Define canonical graph resources and list/read/query/write/admin/pin/delegate abilities plus branch/revision/query/property/row/byte/depth/time/audience/count caveats. Specify containment and monotonic attenuation for every chain link, issuance, audience, expiry, revocation, replay, and error/audit behavior.

## KGP-022 Enforce UCAN in GraphService and emit audit receipts

- Status: completed
- Priority: P0
- Track: security
- Depends on: KGP-006, KGP-021
- Goal id: KGP-G070
- Outputs: ipfs_datasets_py/knowledge_graphs/auth/service.py, ipfs_datasets_py/knowledge_graphs/audit.py, tests/security/knowledge_graphs/test_service_enforcement.py
- Validation: python -m pytest -q tests/security/knowledge_graphs/test_service_enforcement.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/ucan/enforcement
- Parallel lane: ucan-enforcement
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/knowledge_graphs/auth/service.py, ipfs_datasets_py/knowledge_graphs/audit.py, tests/security/knowledge_graphs/test_service_enforcement.py
- Conflict policy: Authorization precedes catalog/object access; audit records never contain graph properties or raw tokens.
- Acceptance: Enforce resource, ability, full-chain attenuation, issuer/audience, expiry, revocation, nonce/idempotency, and caveats before metadata, graph, index, or shard access. Emit bounded content-addressed allow/deny receipts with policy/revision/request digests and redaction. Python/CLI can opt into the same enforcement context.

## KGP-023 Prove negative authorization, revocation, and replay matrices

- Status: pending
- Priority: P0
- Track: security
- Depends on: KGP-019, KGP-022
- Goal id: KGP-G070
- Outputs: tests/security/knowledge_graphs/test_ucan_adversarial.py, tests/mcp/test_graph_ucan.py
- Validation: python -m pytest -q tests/security/knowledge_graphs/test_ucan_adversarial.py tests/mcp/test_graph_ucan.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/ucan/adversarial
- Parallel lane: ucan-adversarial
- Resource class: cpu-medium
- Predicted files: tests/security/knowledge_graphs/test_ucan_adversarial.py, tests/mcp/test_graph_ucan.py
- Conflict policy: Add adversarial fixtures only; weakening fail-closed defaults is forbidden.
- Acceptance: Deny sibling tenant/graph, widened child ability/resource/caveat, wrong audience, expired/not-yet-valid, revoked ancestor/child, substituted revision/cursor, replayed mutation, unknown key, bad signature, malformed chain, oversized token, confused deputy, and unauthorized shard prefetch. Prove denial has no storage/catalog side effect and audit receipts remain safe.

## KGP-024 Add a read-only CVEfixes adapter and differential suite

- Status: pending
- Priority: P1
- Track: compatibility
- Depends on: KGP-002, KGP-015
- Goal id: KGP-G080
- Outputs: ipfs_datasets_py/knowledge_graphs/adapters/cvefixes.py, tests/integration/knowledge_graphs/corpora/test_cvefixes.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/corpora/test_cvefixes.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/corpora/cvefixes
- Parallel lane: cvefixes-corpus
- Resource class: io-large
- Predicted files: ipfs_datasets_py/knowledge_graphs/adapters/cvefixes.py, tests/integration/knowledge_graphs/corpora/test_cvefixes.py
- Conflict policy: Read lift artifacts without changing them; canonical implementation belongs in the main ipfs_datasets_py checkout.
- Acceptance: Discover and validate source Parquet, generated manifest, graph node/edge/adjacency shards, vector artifacts, checksums/counts/provenance, representative CVE/CWE/file/commit traversals, missing/corrupt shard behavior, and parity with the existing query script. Provide tiny checked fixture plus environment-gated full-corpus receipt.

## KGP-025 Add a read-only SkillCenter adapter and differential suite

- Status: pending
- Priority: P1
- Track: compatibility
- Depends on: KGP-002, KGP-015
- Goal id: KGP-G080
- Outputs: ipfs_datasets_py/knowledge_graphs/adapters/skillcenter.py, tests/integration/knowledge_graphs/corpora/test_skillcenter.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/corpora/test_skillcenter.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/corpora/skillcenter
- Parallel lane: skillcenter-corpus
- Resource class: io-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/adapters/skillcenter.py, tests/integration/knowledge_graphs/corpora/test_skillcenter.py
- Conflict policy: Retain logic/intent_ir/graphrag as current producer until differential gates pass.
- Acceptance: Read corpus, graph nodes/edges/adjacency/index manifests, BM25, embeddings, and CID release descriptors; validate counts/checksums/provenance; compare skill, category, relationship, and hybrid rankings against the existing reader; provide small and full-release test profiles.

## KGP-026 Add a read-only 211-AI adapter and differential suite

- Status: pending
- Priority: P1
- Track: compatibility
- Depends on: KGP-002, KGP-015
- Goal id: KGP-G080
- Outputs: ipfs_datasets_py/knowledge_graphs/adapters/two_eleven.py, tests/integration/knowledge_graphs/corpora/test_two_eleven.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/corpora/test_two_eleven.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/corpora/211
- Parallel lane: two-eleven-corpus
- Resource class: io-large
- Predicted files: ipfs_datasets_py/knowledge_graphs/adapters/two_eleven.py, tests/integration/knowledge_graphs/corpora/test_two_eleven.py
- Conflict policy: Treat 211-AI data/retrieval_package and browser export as read-only external fixtures.
- Acceptance: Validate the 48,851-node/648,958-edge retrieval graph, 22,638 documents/embeddings, communities, adjacency and generated browser shards; compare entity, neighborhood, community, geography and hybrid results to the current exporter/reader; detect stale source paths and manifest/count drift.

## KGP-027 Add code, objective, AST, conflict, and evidence graph adapters

- Status: pending
- Priority: P1
- Track: compatibility
- Depends on: KGP-002, KGP-015
- Goal id: KGP-G080
- Outputs: ipfs_datasets_py/knowledge_graphs/adapters/code_evidence.py, tests/integration/knowledge_graphs/corpora/test_code_evidence.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/corpora/test_code_evidence.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/corpora/code-evidence
- Parallel lane: code-evidence-corpus
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/adapters/code_evidence.py, tests/integration/knowledge_graphs/corpora/test_code_evidence.py
- Conflict policy: Consume supervisor/code graph schemas without coupling knowledge_graphs to supervisor runtime.
- Acceptance: Adapt objective, semantic dependency, AST, conflict, and code-evidence graph records discovered by KGP-002. Preserve typed node/edge kinds, provenance, revision binding, evidence links and incremental updates; prove representative dependency/impact/provenance queries and schema-extensibility with unknown optional kinds.

## KGP-028 Build corpus differential and migration verification reports

- Status: pending
- Priority: P1
- Track: compatibility
- Depends on: KGP-024, KGP-025, KGP-026, KGP-027
- Goal id: KGP-G080
- Outputs: ipfs_datasets_py/knowledge_graphs/migration/verifier.py, tests/integration/knowledge_graphs/corpora/test_differential.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/corpora/test_differential.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/corpora/differential
- Parallel lane: corpus-differential
- Resource class: io-large
- Predicted files: ipfs_datasets_py/knowledge_graphs/migration/verifier.py, tests/integration/knowledge_graphs/corpora/test_differential.py
- Conflict policy: Reports are read-only and content addressed; mismatches cannot be auto-waived.
- Acceptance: Produce revision-bound count/schema/checksum/provenance and golden-query diffs for every corpus, classify expected ordering/precision differences explicitly, sample and full modes, fail on unexplained missing/extra entities/edges/results, and retain enough bounded evidence to reproduce each mismatch.

## KGP-029 Build a reproducible graph load harness

- Status: pending
- Priority: P0
- Track: reliability
- Depends on: KGP-008, KGP-012, KGP-016, KGP-020
- Goal id: KGP-G090
- Outputs: benchmarks/knowledge_graphs, tests/load/knowledge_graphs/test_harness.py
- Validation: python -m pytest -q tests/load/knowledge_graphs/test_harness.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/reliability/harness
- Parallel lane: load-harness
- Resource class: cpu-medium
- Predicted files: benchmarks/knowledge_graphs, tests/load/knowledge_graphs/test_harness.py
- Conflict policy: Keep long profiles opt-in but make harness correctness and a tiny profile mandatory in CI.
- Acceptance: Generate deterministic graph shapes and replay corpus workloads across Python/CLI/MCP/MCP++, Parquet/IPFS/ipfs_kit/hybrid, and read/write/query mixes. Record environment, revision, seed, config, throughput, latency histogram, queue/conflict/error, CPU/RSS/heap/FD, cache/IPFS bytes/fetches, shard fan-out, and recovery in a versioned receipt.

## KGP-030 Establish labelled baselines and ratify SLO gates

- Status: pending
- Priority: P0
- Track: reliability
- Depends on: KGP-028, KGP-029
- Goal id: KGP-G090
- Outputs: benchmarks/knowledge_graphs/baselines, docs/operations/knowledge_graphs_slos.md
- Validation: python -m pytest -q tests/load/knowledge_graphs/test_baseline_comparison.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/reliability/baselines
- Parallel lane: load-baselines
- Resource class: cpu-large
- Predicted files: benchmarks/knowledge_graphs/baselines, docs/operations/knowledge_graphs_slos.md, tests/load/knowledge_graphs/test_baseline_comparison.py
- Conflict policy: Do not claim portable absolute SLOs without environment labels and repeated samples.
- Acceptance: Run smoke, full 211, available CVEfixes, 1M-node/10M-edge synthetic, and at least 16-graph mixed concurrency profiles. Ratify per-environment p95/p99/throughput/recovery/resource bounds with warmup, repetitions and variance; enforce zero correctness/security errors and block unexplained p95 or throughput regressions over 10%.

## KGP-031 Prove soak, chaos, leak, and recovery behavior

- Status: pending
- Priority: P0
- Track: reliability
- Depends on: KGP-030
- Goal id: KGP-G090
- Outputs: tests/chaos/knowledge_graphs, tests/load/knowledge_graphs/test_soak.py, benchmarks/knowledge_graphs/soak
- Validation: python -m pytest -q tests/chaos/knowledge_graphs
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/reliability/chaos
- Parallel lane: graph-chaos
- Resource class: cpu-large
- Predicted files: tests/chaos/knowledge_graphs, tests/load/knowledge_graphs/test_soak.py, benchmarks/knowledge_graphs/soak
- Conflict policy: Fault injection must use isolated temporary stores and disposable IPFS namespaces.
- Acceptance: Test process kill, disk full, read-only disk, corrupt cache/object, missing and slow shard, IPFS outage/reconnect, lease expiry, clock skew, cancellation and concurrent compaction. Complete a 24-hour mixed soak after short profiles pass, with no data/security error and no statistically significant unbounded RSS/FD/cache/WAL/lease growth.

## KGP-032 Add observability, health, backup, restore, and repair tools

- Status: pending
- Priority: P0
- Track: reliability
- Depends on: KGP-012, KGP-016, KGP-022
- Goal id: KGP-G090
- Outputs: ipfs_datasets_py/knowledge_graphs/operations, docs/operations/knowledge_graphs_runbook.md, tests/integration/knowledge_graphs/test_operations.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/test_operations.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/reliability/operations
- Parallel lane: graph-operations
- Resource class: io-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/operations, docs/operations/knowledge_graphs_runbook.md, tests/integration/knowledge_graphs/test_operations.py
- Conflict policy: Scrub graph properties, raw queries, UCAN tokens, and secrets from telemetry by default.
- Acceptance: Add structured logs, OpenTelemetry metrics/traces, liveness/readiness, catalog/WAL/shard/pin/cache diagnostics, manifest scrub/verify/repair previews, immutable backup and restore, disaster-recovery runbook, and alert guidance. Restore proves the same revision/checksums/query vectors and repair never mutates without an explicit bounded plan.

## KGP-033 Implement shadow, canary, and rollback controls

- Status: pending
- Priority: P1
- Track: adoption
- Depends on: KGP-023, KGP-028, KGP-031, KGP-032
- Goal id: KGP-G100
- Outputs: ipfs_datasets_py/knowledge_graphs/migration/shadow.py, ipfs_datasets_py/knowledge_graphs/migration/canary.py, tests/integration/knowledge_graphs/test_shadow_migration.py
- Validation: python -m pytest -q tests/integration/knowledge_graphs/test_shadow_migration.py tests/integration/knowledge_graphs/test_rollback.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/adoption/canary
- Parallel lane: graph-canary
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/knowledge_graphs/migration/shadow.py, ipfs_datasets_py/knowledge_graphs/migration/canary.py, tests/integration/knowledge_graphs/test_shadow_migration.py, tests/integration/knowledge_graphs/test_rollback.py
- Conflict policy: Shadow is read-only by default; dual write requires explicit idempotent producer approval.
- Acceptance: Compare old/new reads without changing caller results, route allowlisted graph IDs to a canary, emit bounded mismatch and performance metrics, stop automatically on security/correctness thresholds, and roll back by atomically restoring the last verified immutable head. Never convert or delete legacy data in place.

## KGP-034 Publish compatibility, migration, and deprecation runbooks

- Status: pending
- Priority: P1
- Track: adoption
- Depends on: KGP-033
- Goal id: KGP-G100
- Outputs: docs/migration/knowledge_graphs, docs/operations/knowledge_graphs_release.md, ipfs_datasets_py/knowledge_graphs/compat.py
- Validation: python -m pytest -q tests/unit/knowledge_graphs/test_compatibility_policy.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/adoption/runbooks
- Parallel lane: graph-runbooks
- Resource class: cpu-small
- Predicted files: docs/migration/knowledge_graphs, docs/operations/knowledge_graphs_release.md, ipfs_datasets_py/knowledge_graphs/compat.py, tests/unit/knowledge_graphs/test_compatibility_policy.py
- Conflict policy: Do not remove an import or data reader in the same release that first warns about it.
- Acceptance: Document producer-specific prerequisites, backup, dry-run, shadow, canary, cutover, rollback, schema evolution, storage selection, UCAN setup and on-call procedures. Publish versioned compatibility tiers and warning/removal windows for legacy graph classes and paths.

## KGP-035 Enforce a production release evidence gate

- Status: pending
- Priority: P0
- Track: adoption
- Depends on: KGP-034
- Goal id: KGP-G100
- Outputs: ipfs_datasets_py/knowledge_graphs/release_gate.py, tests/integration/knowledge_graphs/test_release_gate.py, docs/operations/knowledge_graphs_release.md
- Validation: python -m pytest -q tests/integration/knowledge_graphs/test_release_gate.py
- Board namespace: knowledge-graphs-production-hardening-v1
- Bundle: knowledge-graphs/adoption/release
- Parallel lane: graph-release
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/knowledge_graphs/release_gate.py, tests/integration/knowledge_graphs/test_release_gate.py, docs/operations/knowledge_graphs_release.md
- Conflict policy: Missing, stale, foreign-tree, skipped, partial, or contradicted evidence fails closed.
- Acceptance: Require exact fresh passing receipts for child goals KGP-G010 through KGP-G090 and every root definition-of-done clause, including corpus-specific sign-off. Reject task status, coverage, prose, optional-dependency skip, sample-only corpus runs, absent soak/chaos, missing UCAN negative proof, or unknown environment as substitutes. Emit a signed/content-addressed release decision and retain the platform as not production ready until it passes.

## KGP-036 Review completion-evidence alignment for MCP++ UCAN authorization and audit

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: security
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/security/knowledge_graphs tests/mcp/test_graph_ucan.py
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-036-objective-gap-2f8f50b34b69.md
- Bundle: knowledge-graphs/ucan
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-ucan.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: KGP-G000
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/ucan
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: completion-reconciliation, ipfs_datasets_py/mcp_server/ucan_delegation.py, KGP-G020 service contract
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G070
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/404751ecbca2ff6b2536cde1cbd57cedb9130e6052cd58cea3a9240930ede7f9
- Canonical task CID: baguqeeraibdvd3f4ul7wwjjwzxq4xvl45w4rgdtaklgvrtvdvesasmhn474q
- Semantic identity: objective-family/v1/42934bd10d518cb2d4c705c8899fcac5cec7e5a987502aeb8a49e20fc1a1f512
- Acceptance subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Resource containment and every delegation link attenuate authority, Reconcile the unverified completion decision with current evidence for: MCP++ UCAN authorization and audit, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G070 is schedulable
- Effects: satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: Resource containment and every delegation link attenuate authority, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: MCP++ UCAN authorization and audit, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Resource containment and every delegation link attenuate authority, Reconcile the unverified completion decision with current evidence for: MCP++ UCAN authorization and audit, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G070
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/42934bd10d518cb2d4c705c8899fcac5cec7e5a987502aeb8a49e20fc1a1f512
- Missing evidence: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Resource containment and every delegation link attenuate authority, Reconcile the unverified completion decision with current evidence for: MCP++ UCAN authorization and audit, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: completion reconciliation completion-evidence alignment ipfs_datasets_py/mcp_server/ucan_delegation.py KGP-G020 service contract
- AST query: completion-reconciliation, ipfs_datasets_py/mcp_server/ucan_delegation.py, KGP-G020 service contract
- Surplus group: KGP-G070
- Merge key: objective-family/v1/42934bd10d518cb2d4c705c8899fcac5cec7e5a987502aeb8a49e20fc1a1f512
- Merge family: KGP-G070
- Merge role: completion_gate_gap_manual_review
- Work item count: 8
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: 42934bd10d518cb2
- Acceptance: Objective scan filed this review gap for KGP-G070. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-036-objective-gap-2f8f50b34b69.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.

## KGP-037 Review completion-evidence alignment for Durable concurrency, transactions, and recovery

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: durability
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/unit/knowledge_graphs/test_transactions.py tests/integration/knowledge_graphs/concurrency tests/chaos/knowledge_graphs
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-037-objective-gap-1122d5298b0c.md
- Bundle: knowledge-graphs/transactions
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-transactions.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: KGP-G000
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/transactions
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: completion-reconciliation, KGP-G020 service and catalog contract
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G030
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/bbb55a8086b29d17c1c068035e79b4a17389a67418826424308229026c78a5a0
- Canonical task CID: baguqeeraxo2vvaegwkorpqoanabv46nuufzytjtudcbgijbqqiuqe3dyuwqa
- Semantic identity: objective-family/v1/4b8c2704998a8012377394aa177424333349018b96217a0a0f5553aabd49e571
- Acceptance subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Thread and process tests prove no lost updates or cross-graph leakage, Reconcile the unverified completion decision with current evidence for: Durable concurrency, transactions, and recovery, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G030 is schedulable
- Effects: satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: Thread and process tests prove no lost updates or cross-graph leakage, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: Durable concurrency, transactions, and recovery, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Thread and process tests prove no lost updates or cross-graph leakage, Reconcile the unverified completion decision with current evidence for: Durable concurrency, transactions, and recovery, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G030
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/4b8c2704998a8012377394aa177424333349018b96217a0a0f5553aabd49e571
- Missing evidence: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Thread and process tests prove no lost updates or cross-graph leakage, Reconcile the unverified completion decision with current evidence for: Durable concurrency, transactions, and recovery, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: completion reconciliation completion-evidence alignment KGP-G020 service and catalog contract
- AST query: completion-reconciliation, KGP-G020 service and catalog contract
- Surplus group: KGP-G030
- Merge key: objective-family/v1/4b8c2704998a8012377394aa177424333349018b96217a0a0f5553aabd49e571
- Merge family: KGP-G030
- Merge role: completion_gate_gap_manual_review
- Work item count: 8
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: 4b8c2704998a8012
- Acceptance: Objective scan filed this review gap for KGP-G030. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-037-objective-gap-1122d5298b0c.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.

## KGP-038 Review completion-evidence alignment for Executable truth baseline and compatibility contract

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: baseline
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/knowledge_graphs/contract
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-038-objective-gap-41d8fde4986a.md
- Bundle: knowledge-graphs/baseline
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-baseline.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: KGP-G000
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/baseline
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: completion-reconciliation, direct CLI and MCP probes from 2026-07-29, docs/knowledge_graphs/MASTER_STATUS.md
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G010
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/d1020d842d35aeb61df3fa51b2ac34421c2815fe8e0f6a353ea3512b1b675ece
- Canonical task CID: baguqeera2eba3bbngwxlmhpt7ji3flbuiiocqfp6ryhwunj6uniswg3hl3ha
- Semantic identity: objective-family/v1/7612abd951666d8f9787b5e96e7e08426ff08973b9cf148ecaa356acccab8db9
- Acceptance subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Known CLI/MCP lifecycle failures are reproducible without permissive assertions, Reconcile the unverified completion decision with current evidence for: Executable truth baseline and compatibility contract, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G010 is schedulable
- Effects: satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: Known CLI/MCP lifecycle failures are reproducible without permissive assertions, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: Executable truth baseline and compatibility contract, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Known CLI/MCP lifecycle failures are reproducible without permissive assertions, Reconcile the unverified completion decision with current evidence for: Executable truth baseline and compatibility contract, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G010
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/7612abd951666d8f9787b5e96e7e08426ff08973b9cf148ecaa356acccab8db9
- Missing evidence: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Known CLI/MCP lifecycle failures are reproducible without permissive assertions, Reconcile the unverified completion decision with current evidence for: Executable truth baseline and compatibility contract, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: completion reconciliation completion-evidence alignment direct CLI and MCP probes from 2026-07-29 docs/knowledge_graphs/MASTER_STATUS.md
- AST query: completion-reconciliation, direct CLI and MCP probes from 2026-07-29, docs/knowledge_graphs/MASTER_STATUS.md
- Surplus group: KGP-G010
- Merge key: objective-family/v1/7612abd951666d8f9787b5e96e7e08426ff08973b9cf148ecaa356acccab8db9
- Merge family: KGP-G010
- Merge role: completion_gate_gap_manual_review
- Work item count: 8
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: 7612abd951666d8f
- Acceptance: Objective scan filed this review gap for KGP-G010. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-038-objective-gap-41d8fde4986a.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.

## KGP-039 Review completion-evidence alignment for Canonical graph identity, manifest, catalog, and service

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: architecture
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/unit/knowledge_graphs/contracts tests/integration/knowledge_graphs/test_catalog_service.py
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-039-objective-gap-410184b4078a.md
- Bundle: knowledge-graphs/control-plane
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-control-plane.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: KGP-G000
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/control-plane
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: completion-reconciliation, KGP-G010 contract and inventory outputs
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G020
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/0ea1a2cc5ffad27548c638bcd1b9c1988d38e7da19d06720f20dee77b63dd654
- Canonical task CID: baguqeerab2q2ftc77ljhksgghc6ndoobtcgtrz62dhigoihsbxxhpnr52zka
- Semantic identity: objective-family/v1/285f4556da82fc618b68278c9033b351aaf44f22a68c1abb9f18e6fe2e901c64
- Acceptance subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Tenant/graph/branch/revision identity is explicit and canonical, Reconcile the unverified completion decision with current evidence for: Canonical graph identity, manifest, catalog, and service, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G020 is schedulable
- Effects: satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: Tenant/graph/branch/revision identity is explicit and canonical, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: Canonical graph identity, manifest, catalog, and service, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Tenant/graph/branch/revision identity is explicit and canonical, Reconcile the unverified completion decision with current evidence for: Canonical graph identity, manifest, catalog, and service, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G020
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/285f4556da82fc618b68278c9033b351aaf44f22a68c1abb9f18e6fe2e901c64
- Missing evidence: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Tenant/graph/branch/revision identity is explicit and canonical, Reconcile the unverified completion decision with current evidence for: Canonical graph identity, manifest, catalog, and service, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: completion reconciliation completion-evidence alignment KGP-G010 contract and inventory outputs
- AST query: completion-reconciliation, KGP-G010 contract and inventory outputs
- Surplus group: KGP-G020
- Merge key: objective-family/v1/285f4556da82fc618b68278c9033b351aaf44f22a68c1abb9f18e6fe2e901c64
- Merge family: KGP-G020
- Merge role: completion_gate_gap_manual_review
- Work item count: 8
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: 285f4556da82fc61
- Acceptance: Objective scan filed this review gap for KGP-G020. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-039-objective-gap-410184b4078a.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.

## KGP-040 Review completion-evidence alignment for Production-grade multi-graph knowledge graph platform

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: knowledge-graphs
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/unit/knowledge_graphs tests/integration/knowledge_graphs tests/cli/test_graph_commands.py
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-040-objective-gap-88aaa809eae8.md
- Bundle: knowledge-graphs/root
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-root.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: none
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/root
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: completion-reconciliation, docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G000
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/76eccd42469d6c953aeb9fb27f40566380324bea51be539ab18b6be55c684446
- Canonical task CID: baguqeerao3wm2qsgtvwjkoxlt6zh6qcwmoades7kkg7fhgvrrnv6kxdiirda
- Semantic identity: objective-family/v1/94d760535f198a985d8df6bf1c86380d5348f6ec1da969f9a689790acb751cf8
- Acceptance subset: Every descendant must remain verified with all proof requirements fresh, conclusive, uncontradicted, and satisfied., Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: All exact child goals KGP-G010 through KGP-G100 have fresh current-tree passing evidence, Reconcile the unverified completion decision with current evidence for: Production-grade multi-graph knowledge graph platform, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G000 is schedulable
- Effects: satisfy evidence requirement: Every descendant must remain verified with all proof requirements fresh, conclusive, uncontradicted, and satisfied., satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: All exact child goals KGP-G010 through KGP-G100 have fresh current-tree passing evidence, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: Production-grade multi-graph knowledge graph platform, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every descendant must remain verified with all proof requirements fresh, conclusive, uncontradicted, and satisfied., Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: All exact child goals KGP-G010 through KGP-G100 have fresh current-tree passing evidence, Reconcile the unverified completion decision with current evidence for: Production-grade multi-graph knowledge graph platform, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G000
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/94d760535f198a985d8df6bf1c86380d5348f6ec1da969f9a689790acb751cf8
- Missing evidence: Every descendant must remain verified with all proof requirements fresh, conclusive, uncontradicted, and satisfied., Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: All exact child goals KGP-G010 through KGP-G100 have fresh current-tree passing evidence, Reconcile the unverified completion decision with current evidence for: Production-grade multi-graph knowledge graph platform, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: completion reconciliation completion-evidence alignment docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md
- AST query: completion-reconciliation, docs/architecture/KNOWLEDGE_GRAPHS_PRODUCTION_HARDENING_PLAN_2026_07_29.md
- Surplus group: KGP-G000
- Merge key: objective-family/v1/94d760535f198a985d8df6bf1c86380d5348f6ec1da969f9a689790acb751cf8
- Merge family: KGP-G000
- Merge role: completion_gate_gap_manual_review
- Work item count: 9
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: 94d760535f198a98
- Acceptance: Objective scan filed this review gap for KGP-G000. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-040-objective-gap-88aaa809eae8.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.

## KGP-041 Review completion-evidence alignment for Load, soak, chaos, observability, and operability

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: reliability
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/load/knowledge_graphs tests/chaos/knowledge_graphs
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-041-objective-gap-8ffedab092b6.md
- Bundle: knowledge-graphs/reliability
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-reliability.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: KGP-G000
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/reliability
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: completion-reconciliation, KGP-G030 through KGP-G080 passing contracts
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G090
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/b6955e1037152941a00f4d900cce5f449528d70be868da3dd333402d278cc1ba
- Canonical task CID: baguqeeraw2kv4ebxcuuudiapjwiazts7isksrvyl5bunupotgnac2j4myg5a
- Semantic identity: objective-family/v1/02c6065397ab769686ebf1043dbf5f5fd9f78eee86a262f57dbdce5a63be592d
- Acceptance subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Smoke, 211-AI, CVEfixes, 1M/10M synthetic, 16-graph mixed concurrency, soak, and chaos profiles emit reproducible receipts, Reconcile the unverified completion decision with current evidence for: Load, soak, chaos, observability, and operability, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G090 is schedulable
- Effects: satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: Smoke, 211-AI, CVEfixes, 1M/10M synthetic, 16-graph mixed concurrency, soak, and chaos profiles emit reproducible receipts, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: Load, soak, chaos, observability, and operability, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Smoke, 211-AI, CVEfixes, 1M/10M synthetic, 16-graph mixed concurrency, soak, and chaos profiles emit reproducible receipts, Reconcile the unverified completion decision with current evidence for: Load, soak, chaos, observability, and operability, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G090
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/02c6065397ab769686ebf1043dbf5f5fd9f78eee86a262f57dbdce5a63be592d
- Missing evidence: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Smoke, 211-AI, CVEfixes, 1M/10M synthetic, 16-graph mixed concurrency, soak, and chaos profiles emit reproducible receipts, Reconcile the unverified completion decision with current evidence for: Load, soak, chaos, observability, and operability, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: completion reconciliation completion-evidence alignment KGP-G030 through KGP-G080 passing contracts
- AST query: completion-reconciliation, KGP-G030 through KGP-G080 passing contracts
- Surplus group: KGP-G090
- Merge key: objective-family/v1/02c6065397ab769686ebf1043dbf5f5fd9f78eee86a262f57dbdce5a63be592d
- Merge family: KGP-G090
- Merge role: completion_gate_gap_manual_review
- Work item count: 8
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: 02c6065397ab7696
- Acceptance: Objective scan filed this review gap for KGP-G090. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-041-objective-gap-8ffedab092b6.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.

## KGP-042 Review completion-evidence alignment for Real corpus adapters and differential validation

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P1
- Track: compatibility
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/integration/knowledge_graphs/corpora
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-042-objective-gap-0b703a243441.md
- Bundle: knowledge-graphs/corpora
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-corpora.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: KGP-G000
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/corpora
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: 211-AI data/retrieval_package, agent supervisor graph datasets, completion-reconciliation, KGP-G010 inventory, lift_coding/.cvefixes-build, logic/intent_ir/graphrag
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G080
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/7bcd868f31868c24518361683f8f6996d719e85290ff6f7ee6139a07a9076e1b
- Canonical task CID: baguqeerappgyndzrq2gciumdmfud7d3js3lrt2cssd7w67xgconapkihnynq
- Semantic identity: objective-family/v1/c9250d239a68cb7eac00a425c97b137b3c62bfd1109ff9b31a284fea9fa469eb
- Acceptance subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Each named corpus has a read-only adapter, immutable fixture manifest, representative golden queries, count/checksum/provenance validation, and differential comparison to its current reader, Reconcile the unverified completion decision with current evidence for: Real corpus adapters and differential validation, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G080 is schedulable
- Effects: satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: Each named corpus has a read-only adapter, immutable fixture manifest, representative golden queries, count/checksum/provenance validation, and differential comparison to its current reader, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: Real corpus adapters and differential validation, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Each named corpus has a read-only adapter, immutable fixture manifest, representative golden queries, count/checksum/provenance validation, and differential comparison to its current reader, Reconcile the unverified completion decision with current evidence for: Real corpus adapters and differential validation, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G080
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/c9250d239a68cb7eac00a425c97b137b3c62bfd1109ff9b31a284fea9fa469eb
- Missing evidence: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Each named corpus has a read-only adapter, immutable fixture manifest, representative golden queries, count/checksum/provenance validation, and differential comparison to its current reader, Reconcile the unverified completion decision with current evidence for: Real corpus adapters and differential validation, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: 211-AI data/retrieval_package agent supervisor graph datasets completion reconciliation completion-evidence alignment KGP-G010 inventory lift_coding/.cvefixes-build logic/intent_ir/graphrag
- AST query: 211-AI data/retrieval_package, agent supervisor graph datasets, completion-reconciliation, KGP-G010 inventory, lift_coding/.cvefixes-build, logic/intent_ir/graphrag
- Surplus group: KGP-G080
- Merge key: objective-family/v1/c9250d239a68cb7eac00a425c97b137b3c62bfd1109ff9b31a284fea9fa469eb
- Merge family: KGP-G080
- Merge role: completion_gate_gap_manual_review
- Work item count: 8
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: c9250d239a68cb7e
- Acceptance: Objective scan filed this review gap for KGP-G080. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-042-objective-gap-0b703a243441.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.

## KGP-043 Review completion-evidence alignment for Python, CLI, MCP, and MCP++ surface parity

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: interfaces
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/knowledge_graphs/conformance tests/cli/test_graph_commands.py tests/mcp/test_graph_tools.py
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-043-objective-gap-14ba135f6651.md
- Bundle: knowledge-graphs/surfaces
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-surfaces.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: KGP-G000
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/surfaces
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: completion-reconciliation, KGP-G010 public contract matrix, KGP-G020 service
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G060
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/e43b2d1bea1c42dae934cca223201b43316fa4600fa33b5a325918cef797924f
- Canonical task CID: baguqeera4q5s2g7kdrbnv2juzsrcgia3imyw7jdab6rtwwrslemm554xsjhq
- Semantic identity: objective-family/v1/0fe692a5ed2d629d9ea81e0faede979b4e189e3bc82ba4cc9d7a0ad27e9d0744
- Acceptance subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Create/write/query/transaction/list/delete/reopen operations survive independent process and MCP calls, Reconcile the unverified completion decision with current evidence for: Python, CLI, MCP, and MCP++ surface parity, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G060 is schedulable
- Effects: satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: Create/write/query/transaction/list/delete/reopen operations survive independent process and MCP calls, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: Python, CLI, MCP, and MCP++ surface parity, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Create/write/query/transaction/list/delete/reopen operations survive independent process and MCP calls, Reconcile the unverified completion decision with current evidence for: Python, CLI, MCP, and MCP++ surface parity, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G060
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/0fe692a5ed2d629d9ea81e0faede979b4e189e3bc82ba4cc9d7a0ad27e9d0744
- Missing evidence: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Create/write/query/transaction/list/delete/reopen operations survive independent process and MCP calls, Reconcile the unverified completion decision with current evidence for: Python, CLI, MCP, and MCP++ surface parity, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: completion reconciliation completion-evidence alignment KGP-G010 public contract matrix KGP-G020 service
- AST query: completion-reconciliation, KGP-G010 public contract matrix, KGP-G020 service
- Surplus group: KGP-G060
- Merge key: objective-family/v1/0fe692a5ed2d629d9ea81e0faede979b4e189e3bc82ba4cc9d7a0ad27e9d0744
- Merge family: KGP-G060
- Merge role: completion_gate_gap_manual_review
- Work item count: 8
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: 0fe692a5ed2d629d
- Acceptance: Objective scan filed this review gap for KGP-G060. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-043-objective-gap-14ba135f6651.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.

## KGP-044 Review completion-evidence alignment for Reversible adoption and production release

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P1
- Track: adoption
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/integration/knowledge_graphs/test_shadow_migration.py tests/integration/knowledge_graphs/test_rollback.py
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-044-objective-gap-1c98bc14d11e.md
- Bundle: knowledge-graphs/adoption
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-adoption.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: KGP-G000
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/adoption
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: completion-reconciliation, KGP-G010 through KGP-G090 completion receipts
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G100
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/36f693c3799c7e1cdc243cf90ed475be8fce73fa090f21cd3db13964ebe15a39
- Canonical task CID: baguqeerag33jhq3ztr7bzxbeht4q5vdvx2h44472behsdtj5we4wj27bli4q
- Semantic identity: objective-family/v1/e3149e18f3d785df411f899ee975797e4420765340edb4b020413c201fe9800e
- Acceptance subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Shadow result comparison and canary graph routing are observable, Reconcile the unverified completion decision with current evidence for: Reversible adoption and production release, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G100 is schedulable
- Effects: satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: Shadow result comparison and canary graph routing are observable, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: Reversible adoption and production release, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Shadow result comparison and canary graph routing are observable, Reconcile the unverified completion decision with current evidence for: Reversible adoption and production release, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G100
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/e3149e18f3d785df411f899ee975797e4420765340edb4b020413c201fe9800e
- Missing evidence: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: Shadow result comparison and canary graph routing are observable, Reconcile the unverified completion decision with current evidence for: Reversible adoption and production release, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: completion reconciliation completion-evidence alignment KGP-G010 through KGP-G090 completion receipts
- AST query: completion-reconciliation, KGP-G010 through KGP-G090 completion receipts
- Surplus group: KGP-G100
- Merge key: objective-family/v1/e3149e18f3d785df411f899ee975797e4420765340edb4b020413c201fe9800e
- Merge family: KGP-G100
- Merge role: completion_gate_gap_manual_review
- Work item count: 8
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: e3149e18f3d785df
- Acceptance: Objective scan filed this review gap for KGP-G100. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-044-objective-gap-1c98bc14d11e.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.

## KGP-045 Review completion-evidence alignment for Versioned sharding and bounded unified query

- Status: blocked
- Blocked reason: manual review required because no precise edit targets were authorized
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: query
- Depends on:
- Outputs:
- Validation: git diff --check; python -m pytest -q tests/unit/search/test_sharded_car tests/integration/knowledge_graphs/test_sharded_query.py tests/knowledge_graphs/contract/test_query_budgets.py
- Evidence inputs: data/agent_supervisor/discovery
- Discovery evidence: /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-045-objective-gap-dc5190fd8946.md
- Bundle: knowledge-graphs/query-sharding
- Bundle shard: data/agent_supervisor/knowledge_graphs_production_hardening/bundles/knowledge-graphs-query-sharding.todo.md
- Bundle strategy: bounded_objective_generation
- Graph parents: KGP-G000
- Graph depth: 1
- Objective heap index: 0
- Parallel lane: knowledge-graphs/query-sharding
- Conflict policy: prefer bundle-local changes; invoke the LLM merge resolver for semantic conflicts
- Predicted files:
- Changed paths:
- AST symbols: completion-reconciliation, KGP-G020 and KGP-G040 contracts, search/graph_query/sharded_car
- Interfaces:
- Submodules:
- Generated artifacts: data/agent_supervisor/objective_generation.json
- Allow concurrent with:
- Goal id: KGP-G050
- Completion authority: local
- External authority blockers:
- Canonical task key: task/v1/239e7494b28dc86dd799f90c7a84e9a8d7e3862d14272895ebcdb7f6e2c71e8a
- Canonical task CID: baguqeeraeophjffsrxeg3v4z7eghvbhjvdl6hbrncqtsrfplzw37nywhd2fa
- Semantic identity: objective-family/v1/d604a989b9b6b069136342b925ca39f15e69ced166664e9503e36aab77643e7a
- Acceptance subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: v1 manifests remain readable, Reconcile the unverified completion decision with current evidence for: Versioned sharding and bounded unified query, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Preconditions: objective goal KGP-G050 is schedulable
- Effects: satisfy evidence requirement: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., satisfy evidence requirement: Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., satisfy evidence requirement: Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., satisfy evidence requirement: Produce completion evidence for: v1 manifests remain readable, satisfy evidence requirement: Reconcile the unverified completion decision with current evidence for: Versioned sharding and bounded unified query, satisfy evidence requirement: Require an explicitly healthy analyzer that is safe for completion reasoning., satisfy evidence requirement: Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., satisfy evidence requirement: Task completion is provisional until every criterion has valid evidence.
- Evidence subset: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: v1 manifests remain readable, Reconcile the unverified completion decision with current evidence for: Versioned sharding and bounded unified query, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Resource class: cpu-medium
- Token class: medium
- Estimated tokens: 0
- Resources: cpu-medium
- Merge fate: KGP-G050
- Rejection reasons: none (accepted)
- Evidence obligation key: objective-family/v1/d604a989b9b6b069136342b925ca39f15e69ced166664e9503e36aab77643e7a
- Missing evidence: Every submitted validation proof must be fresh and passing, and every mandatory criterion must have one., Manual review required: no precise implementation, affected-document, or validator-source file was authorized as an edit target., Map every mandatory acceptance criterion to fresh, verified implementation and validation proof bound to the current tree., Produce completion evidence for: v1 manifests remain readable, Reconcile the unverified completion decision with current evidence for: Versioned sharding and bounded unified query, Require an explicitly healthy analyzer that is safe for completion reasoning., Require the configured number of independent, fresh, healthy exhaustive receipts bound to the current repository tree., Task completion is provisional until every criterion has valid evidence.
- Embedding query: completion reconciliation completion-evidence alignment KGP-G020 and KGP-G040 contracts search/graph_query/sharded_car
- AST query: completion-reconciliation, KGP-G020 and KGP-G040 contracts, search/graph_query/sharded_car
- Surplus group: KGP-G050
- Merge key: objective-family/v1/d604a989b9b6b069136342b925ca39f15e69ced166664e9503e36aab77643e7a
- Merge family: KGP-G050
- Merge role: completion_gate_gap_manual_review
- Work item count: 8
- Work scope: bounded_objective_generation
- Goal packet:
- Goal packet role:
- Goal packet goals:
- Goal packet task count: 0
- Goal packet work item count: 0
- Completion goal bindings: {}
- Completion task bindings:
- Candidate kind: generated_task
- Todo vector key: d604a989b9b6b069
- Acceptance: Objective scan filed this review gap for KGP-G050. Inspect the evidence in /home/barberb/ipfs_datasets_py/data/agent_supervisor/knowledge_graphs_production_hardening/discovery/2026-07-29-kgp-045-objective-gap-dc5190fd8946.md; either resolve the diagnostic without an implementation change or authorize precise repository-relative edit targets before changing the task status.
