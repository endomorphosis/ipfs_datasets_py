# US Code Sparse GraphRAG Objective Heap

## USCIR-G000 Deliver a directly queryable US Code sparse GraphRAG release
- Status: active
- Parent:
- Fib priority: 1
- Track: program
- Priority: P0
- Bundle: uscode-sparse-graphrag-v1
- Goal: Improve `ipfs_datasets_py` and stage an additive `justicedao/ipfs_uscode` release with canonical legal data, term-routed BM25, centroid-routed vectors, a legal/BM25 graph, and bounded direct-Hugging-Face queries.
- Evidence: A pinned staged revision, manifest digest, build/admission receipts, evaluation report, sparse fetch traces, clean rebuild comparison, rollback rehearsal, and an explicit publication disposition.
- Outputs: docs/architecture/USCODE_SPARSE_GRAPHRAG_PLAN.md, docs/architecture/uscode_sparse_graphrag.todo.md
- Validation: python scripts/validate_uscode_sparse_graphrag_board.py --check-all
- Acceptance: Every child goal is complete; public publication occurs only under a human seal, otherwise a validated immutable staging revision and explicit external-authorization boundary are delivered.
- Gap task: USCIR-040
- Refinement: Preserve legal provenance and fail closed on mixed vintages, unknown embedding identity, integrity failure, unbounded remote work, or publication without authority.
- Embedding query: US Code legal sparse retrieval BM25 centroid vector graph direct Hugging Face immutable revision
- AST query: us_code_scraper uscode_release_processor hf_vector_layout hf_bm25 semantic_traversal
- Parallel lane: all
- Conflict policy: protected root objective; child tasks own implementation files

## USCIR-G010 Freeze evidence, schemas, and authority policy
- Status: active
- Parent: USCIR-G000
- Fib priority: 1
- Track: foundation
- Priority: P0
- Bundle: foundation-contracts
- Goal: Turn the live dataset audit and prior-pipeline archaeology into executable schemas, frozen fixtures, retrieval labels, and an exact official-source/release-point contract.
- Evidence: Pinned remote inventory, versioned schema/ADR, sealed gold queries, source admission fixtures, and no mutable-latest provenance.
- Outputs: docs/reports/uscode_sparse_graphrag_baseline.json, docs/architecture/uscode_sparse_graphrag_schema.md, tests/fixtures/legal_ir/uscode_sparse_gold.json, ipfs_datasets_py/processors/legal_data/uscode_source_policy.py
- Validation: python -m pytest tests/unit/processors/test_uscode_source_policy.py tests/unit/logic/legal_ir/test_uscode_release_schema.py -q
- Acceptance: All baseline counts reconcile; identity, 4,096 bounds, vector-space, graph, and release authority are unambiguous; first-wave tasks complete.
- Gap task: USCIR-004
- Refinement: Keep physical shard bounds distinct from model token limits and keep BM25 term routing distinct from vector centroid routing.
- Embedding query: official US Code release point schema primary key provenance gold queries
- AST query: canonical_legal_corpora justicedao_dataset_inventory us_code_scraper
- Parallel lane: 0,1,2,3
- Conflict policy: file-disjoint first wave

## USCIR-G020 Build the canonical all-title corpus
- Status: active
- Parent: USCIR-G000
- Fib priority: 2
- Track: corpus
- Priority: P0
- Bundle: legal-corpus
- Goal: Generalize exact-release acquisition to all titles, repair section identity, normalize legal records, quarantine recovery metadata, and emit deterministic semantic chunks with stable CIDs.
- Evidence: Common-release receipts, collision-free legal IDs, row disposition ledger, recovery quarantine, source-path scrubbing, and bounded chunk fixtures.
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/uscode_release_catalog.py, ipfs_datasets_py/processors/legal_data/uscode_normalizer.py, ipfs_datasets_py/processors/legal_data/uscode_chunker.py, ipfs_datasets_py/processors/legal_data/uscode_corpus.py
- Validation: python -m pytest tests/unit/processors/legal_data/test_uscode_normalizer.py tests/unit/processors/legal_data/test_uscode_chunker.py tests/unit/processors/legal_data/test_uscode_corpus.py -q
- Acceptance: Each source row has one admitted/replaced/excluded/quarantined disposition, all admitted rows have canonical identities and provenance, and no recovery workflow row enters search.
- Gap task: USCIR-008
- Refinement: Edition/granule/appendix identity must prevent `(title, section)` collision and Unicode dash truncation.
- Embedding query: legal semantic chunks section subsection official source canonical CID
- AST query: extract_section_number_and_heading uscode_release_processor normalize
- Parallel lane: 0,1,2,3
- Conflict policy: corpus producers own separate modules; integration occurs in USCIR-029

## USCIR-G030 Extract the shared remote GraphRAG substrate
- Status: active
- Parent: USCIR-G000
- Fib priority: 2
- Track: platform
- Priority: P0
- Bundle: shared-hf-graphrag
- Goal: Consolidate the strongest CVEfixes and SkillCenter behavior into reusable bounded artifact writers, routing schemas, immutable resolvers, and integrity verification.
- Evidence: Domain-neutral unit fixtures used by both a reference-domain compatibility test and the US Code adapters.
- Outputs: ipfs_datasets_py/retrieval/hf_graphrag/schema.py, ipfs_datasets_py/retrieval/hf_graphrag/artifacts.py, ipfs_datasets_py/retrieval/hf_graphrag/resolver.py, ipfs_datasets_py/retrieval/hf_graphrag/locators.py
- Validation: python -m pytest tests/unit/retrieval/hf_graphrag -q
- Acceptance: The substrate enforces immutable revisions, descriptor/path/digest/row bounds, 4,096 layouts, cache isolation, and CID-to-corpus/vector lookup without domain-specific ontology.
- Gap task: USCIR-012
- Refinement: Keep compact control-plane lineage separate from verbose release history and verify before parsing.
- Embedding query: reusable Hugging Face GraphRAG shard resolver descriptor verification locator
- AST query: hf_complete_source skillcenter_hf_release ArtifactResolver
- Parallel lane: 0,1,2,3
- Conflict policy: one module per task; public exports serialized by USCIR-029

## USCIR-G040 Build and prove term-routed BM25
- Status: active
- Parent: USCIR-G000
- Fib priority: 3
- Track: bm25
- Priority: P0
- Bundle: sparse-index
- Goal: Implement a legal tokenizer, field-weighted BM25 documents/postings, lexicographic term-range shards, score explanations, and differential validation.
- Evidence: Exact fixture parity, randomized differential tests, bounded posting rows, term-range completeness, and routed fetch traces.
- Outputs: ipfs_datasets_py/retrieval/hf_graphrag/bm25.py, ipfs_datasets_py/processors/legal_data/uscode_bm25.py, tests/unit/processors/legal_data/test_uscode_bm25.py, docs/reports/uscode_bm25_evaluation.json
- Validation: python -m pytest tests/unit/retrieval/hf_graphrag/test_bm25.py tests/unit/processors/legal_data/test_uscode_bm25.py -q
- Acceptance: Sparse results match the unsharded scorer to tolerance and every fetched postings shard is justified by a query term range.
- Gap task: USCIR-016
- Refinement: Tokenization must preserve useful legal citations and section symbols; weights are evaluated rather than inherited silently.
- Embedding query: BM25 legal tokenizer field weights sorted postings term range routing
- AST query: hf_bm25 skillcenter_corpus_bm25 public_legal_bm25_builder
- Parallel lane: 0,1,2,3
- Conflict policy: shared BM25 primitive and legal projection have separate owners

## USCIR-G050 Regenerate and centroid-route vectors
- Status: active
- Parent: USCIR-G000
- Fib priority: 3
- Track: vectors
- Priority: P0
- Bundle: vector-index
- Goal: Re-embed canonical legal chunks with a pinned model, deterministically cluster normalized vectors, similarity-sort bounded shards, and support both centroid and direct-CID routing.
- Evidence: Model/config CID, row conservation, deterministic clustering receipt, exhaustive recall curve, centroid diagnostics, and vector locator tests.
- Outputs: ipfs_datasets_py/retrieval/hf_graphrag/vectors.py, ipfs_datasets_py/processors/legal_data/uscode_embeddings.py, tests/unit/retrieval/hf_graphrag/test_vectors.py, docs/reports/uscode_vector_evaluation.json
- Validation: python -m pytest tests/unit/retrieval/hf_graphrag/test_vectors.py tests/unit/processors/legal_data/test_uscode_embeddings.py -q
- Acceptance: At most 4,096 rows/shard, 8,192 rows/two shards per centroid, stable descending cosine order, exact vector-space metadata, and measured routed recall.
- Gap task: USCIR-020
- Refinement: Never trust or repack legacy vectors whose model and canonical join are unknown; publish direct entry-CID locators for graph frontier embeddings.
- Embedding query: balanced spherical kmeans legal embeddings centroid shard cosine sorted
- AST query: hf_vector_layout spherical_kmeans semantic_centroid_groups
- Parallel lane: 0,1,2,3
- Conflict policy: embedding projection, clustering, validation, and evaluation own distinct files

## USCIR-G060 Build the legal and lexical graph
- Status: active
- Parent: USCIR-G000
- Fib priority: 3
- Track: graph
- Priority: P0
- Bundle: legal-graph
- Goal: Define and build a provenance-backed U.S. Code structural/citation graph, expose BM25 lexical traversal without edge explosion, and export bounded bidirectional adjacency.
- Evidence: Ontology contract, resolved/unresolved citation fixtures, edge source spans, graph integrity receipt, adjacency reconciliation, and BM25 overlay parity.
- Outputs: ipfs_datasets_py/processors/legal_data/uscode_graph.py, ipfs_datasets_py/retrieval/hf_graphrag/graph.py, tests/unit/processors/legal_data/test_uscode_graph.py, docs/reports/uscode_graph_evaluation.json
- Validation: python -m pytest tests/unit/retrieval/hf_graphrag/test_graph.py tests/unit/processors/legal_data/test_uscode_graph.py -q
- Acceptance: Legal edges are evidence-backed and distinct from similarity edges; no dangling durable edges; both directions are complete and bounded; postings-backed term traversal is deterministic.
- Gap task: USCIR-024
- Refinement: Preserve unresolved references; BM25 neighbors are retrieval hints, never legal authority.
- Embedding query: US Code title chapter section citation public law provenance graph adjacency
- AST query: public_legal_graph_builder skillcenter_cid_graph semantic_traversal
- Parallel lane: 0,1,2,3
- Conflict policy: ontology/projection, graph layout, lexical overlay, and integrity report are file-disjoint

## USCIR-G070 Query pinned Hugging Face artifacts directly
- Status: active
- Parent: USCIR-G000
- Fib priority: 5
- Track: query
- Priority: P0
- Bundle: remote-query
- Goal: Implement secure selective remote BM25, dense, hybrid, graph, and embedding-guided traversal with strict budgets, explanations, caches, and fetch traces.
- Evidence: Pinned-revision unit/integration fixtures showing only routed artifacts fetched and identical offline replay.
- Outputs: ipfs_datasets_py/retrieval/hf_graphrag/query.py, ipfs_datasets_py/processors/legal_data/uscode_query.py, scripts/ops/legal_data/query_uscode_hf.py, tests/unit/processors/legal_data/test_uscode_query.py
- Validation: python -m pytest tests/unit/retrieval/hf_graphrag/test_query.py tests/unit/processors/legal_data/test_uscode_query.py -q
- Acceptance: Six query modes are bounded and explainable; graph frontier vectors can be selectively routed by CID; no full repository clone is required.
- Gap task: USCIR-028
- Refinement: Query-time model must exactly match the release vector space; cross-release vectors are late-fused unless explicitly compatible.
- Embedding query: direct Hugging Face BM25 vector hybrid graph semantic beam fetch trace
- AST query: query_skillcenter_hf query_cvefixes_security_ir graph_semantic_walk
- Parallel lane: 0,1,2,3
- Conflict policy: generic query engine, remote modes, legal adapter, and CLI own separate modules

## USCIR-G080 Integrate package builds and release packaging
- Status: active
- Parent: USCIR-G000
- Fib priority: 5
- Track: integration
- Priority: P0
- Bundle: release-builder
- Goal: Register the US Code adapters, create resumable full/delta builders, emit a descriptor-complete additive release, and support deterministic dry-run staging.
- Evidence: Package/API tests, checkpoint-resume receipt, manifest/card validation, compatibility configuration audit, and local candidate build.
- Outputs: ipfs_datasets_py/processors/legal_data/uscode_sparse_graphrag.py, scripts/ops/legal_data/build_uscode_sparse_graphrag.py, ipfs_datasets_py/processors/legal_data/uscode_hf_release.py, scripts/ops/legal_data/stage_uscode_sparse_graphrag.py
- Validation: python -m pytest tests/unit/processors/legal_data/test_uscode_sparse_graphrag.py tests/integration/legal_data/test_uscode_release_local.py -q
- Acceptance: One command can resume, build, validate, and stage all artifact families; the manifest binds one coherent release; legacy configs remain explicit and the default config is viewer-safe.
- Gap task: USCIR-032
- Refinement: Candidate manifests are immutable; publication remains outside implementation-agent authority.
- Embedding query: US Code GraphRAG release builder checkpoint manifest dataset card compatibility
- AST query: hf_release build_skillcenter_hf_release build_cvefixes_security_ir_release
- Parallel lane: 0,1,2,3
- Conflict policy: late integration depends on all producers and serializes shared registry/export changes

## USCIR-G090 Prove quality, security, performance, and remote behavior
- Status: active
- Parent: USCIR-G000
- Fib priority: 5
- Track: assurance
- Priority: P0
- Bundle: evaluation
- Goal: Establish legal relevance, graph-path, routing recall, integrity, resource-bound, determinism, Dataset Viewer, and staged-remote evidence.
- Evidence: Sealed evaluation report, tamper suite, performance/bytes report, clean rebuild comparison, and staged remote canary receipt.
- Outputs: tests/integration/legal_data/test_uscode_sparse_graphrag.py, tests/security/test_uscode_hf_release.py, scripts/ops/legal_data/evaluate_uscode_sparse_graphrag.py, tests/integration/legal_data/test_uscode_hf_remote.py
- Validation: python -m pytest tests/integration/legal_data/test_uscode_sparse_graphrag.py tests/security/test_uscode_hf_release.py -q
- Acceptance: All plan gates pass or have explicit approved exceptions; tampering fails closed; sparse routes meet declared recall and I/O budgets; staged revision works remotely.
- Gap task: USCIR-036
- Refinement: Network canary is opt-in and pinned; ordinary unit tests are offline.
- Embedding query: legal retrieval evaluation integrity performance sparse download remote canary
- AST query: release_gate differential fetch_trace evaluation
- Parallel lane: 0,1,2,3
- Conflict policy: E2E, security, evaluation, and remote canary are isolated

## USCIR-G100 Stage, document, canary, and manually seal publication
- Status: active
- Parent: USCIR-G000
- Fib priority: 8
- Track: release
- Priority: P0
- Bundle: rollout
- Goal: Produce migration/operations documentation, rehearse rollback, stage and redownload an immutable candidate, prepare a publication packet, and require human authorization for the public update.
- Evidence: Operator runbook, rollback rehearsal, immutable staging SHA, redownload validation, candidate manifest digest, and signed or explicitly pending publication seal.
- Outputs: docs/guides/USCODE_SPARSE_GRAPHRAG_RUNBOOK.md, docs/reports/uscode_release_candidate.json, docs/reports/uscode_staging_canary.json, docs/reports/uscode_publication_seal.json
- Validation: python scripts/ops/legal_data/verify_uscode_release_candidate.py --receipt docs/reports/uscode_release_candidate.json
- Acceptance: Candidate is independently verifiable and recoverable; terminal public mutation is either human-authorized and verified or remains clearly pending without blocking the completed implementation/staging evidence.
- Gap task: USCIR-040
- Refinement: No agent may infer Hugging Face publication authority from access to a token or from this plan.
- Embedding query: immutable staged US Code dataset rollback migration publication seal
- AST query: stage upload manifest rollback verify
- Parallel lane: 0,1,2,3
- Conflict policy: rollout tasks are sequential; publication seal is review-only and unschedulable
