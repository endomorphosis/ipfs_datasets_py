# Legal Corpora Reindex Objective Heap

This heap is consumed by the `ipfs_accelerate_py` objective scanner. Parent links are refinement links; `Depends on` is semantic ordering. Evidence must name immutable or content-addressed artifacts. A drained taskboard is not completion evidence.

## LCR-G000 Publish verified state-law and Federal Register sparse GraphRAG releases
- Status: active
- Parent:
- Depends on:
- Fib priority: 1
- Track: program
- Priority: P0
- Bundle: legal-corpora-reindex-v1
- Goal: Fully scrape the codified statutes of all 50 states and DC, fully inventory the Federal Register through a pinned observation cutoff with official full-text dispositions, reindex both with the US Code sparse GraphRAG method, and publish two immutable verified additive releases.
- Evidence: Fifty-one passing state scrape receipts; a closed Federal Register page/document/text inventory; reconciled admission ledgers; deterministic build/evaluation receipts; staged and public immutable-Hub canaries; two public revisions and rollback receipts.
- Outputs: docs/reports/legal_corpora_reindex/final_release_receipt.json
- Validation: python scripts/ops/legal_data/check_legal_corpora_final_release.py --check
- Acceptance: Every acceptance gate in LEGAL_CORPORA_REINDEX_PLAN.md passes against both immutable public revisions; no missing jurisdiction, Federal Register partition/document/text disposition, semantic family, or publication mismatch remains.
- Gap task: LCR-069
- Refinement: Add bounded child goals and tasks for any jurisdiction, artifact family, evaluation, staging, or publication evidence gap; never lower the full-scrape contract.
- Embedding query: state laws Federal Register complete official corpus 50 states District of Columbia cutoff BM25 vectors graph Hugging Face release
- AST query: state_laws federal_register scraper canonical corpus hf_graphrag build upload canary
- Parallel lane: 0,1,2,3
- Conflict policy: Root evidence is assembled only by the terminal task after all child goals have proof; child tasks own disjoint outputs.

## LCR-G010 Freeze the baseline, authority, identity, and completeness contracts
- Status: active
- Parent: LCR-G000
- Depends on:
- Fib priority: 1
- Track: foundation
- Priority: P0
- Bundle: foundation-contracts
- Goal: Replace filename/count assumptions with pinned remote inventory, official-source authority, 51-jurisdiction set, stable identity/schema, no-truncation, resumable acquisition, and safe publication contracts.
- Evidence: Pinned baseline report, 51-source catalog, versioned schema, completion oracle, frontier audit, runner tests, and authorization policy.
- Outputs: docs/reports/legal_corpora_reindex/baseline.json, data/legal/state_laws/official_source_catalog.json, docs/architecture/legal_corpora_reindex_schema.md
- Validation: python scripts/validate_legal_corpora_reindex_board.py --check-all
- Acceptance: All foundation tasks pass offline fixtures; the exact jurisdiction set includes DC; changed remote revisions force a fresh inventory rather than inheriting conclusions.
- Gap task: LCR-001
- Refinement: Create source-specific child work when authority, hierarchy enumeration, pagination, download bundle, identity, or credential safety is uncertain.
- Embedding query: official state code source catalog completeness frontier closure legal identity schema
- AST query: state_laws_scraper US_STATES completed_states refresh_state_laws_corpus publish
- Parallel lane: 0,1,2,3
- Conflict policy: Foundation tasks use separate modules/reports; shared registry integration waits for downstream tasks.

## LCR-G020 Acquire a complete official corpus for all 51 jurisdictions
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G010
- Fib priority: 1
- Track: acquisition
- Priority: P0
- Bundle: full-scrape
- Goal: Execute resumable, frontier-closing full scrapes for the exact 50-state-plus-DC jurisdiction set and reconcile all official-source work.
- Evidence: Thirteen cohort receipts, 51 per-jurisdiction receipts, discovery/fetch/admission/quarantine reconciliation, and aggregate coverage proof.
- Outputs: docs/reports/legal_corpora_reindex/full_scrape_coverage.json
- Validation: python scripts/ops/legal_data/certify_state_laws_full_scrape.py --require-jurisdictions 51 --check
- Acceptance: Each jurisdiction independently passes the authority, frontier, reconciliation, quality, no-truncation, replay, and safety contract; aggregate proof contains exactly 51 codes.
- Gap task: LCR-023
- Refinement: Split any failed cohort into jurisdiction-specific child goals/tasks; further split by official code family, title range, bundle, or pagination frontier when necessary.
- Embedding query: full scrape all state statutes DC official source frontier reconciliation retry checkpoint
- AST query: state_scrapers registry scrape_state_laws partial_checkpoint completion callback
- Parallel lane: 0,1,2,3
- Conflict policy: Cohorts use isolated output/checkpoint roots and disjoint state modules; aggregation is serialized.

## LCR-G021 Complete acquisition cohorts A through D
- Status: active
- Parent: LCR-G020
- Depends on: LCR-G010
- Fib priority: 1
- Track: acquisition
- Priority: P0
- Bundle: cohorts-a-d
- Goal: Certify AL, AK, AZ, AR, CA, CO, CT, DE, FL, GA, HI, ID, IL, IN, IA, and KS.
- Evidence: Cohort A-D receipts and sixteen jurisdiction receipts with closed official frontiers.
- Outputs: docs/reports/legal_corpora_reindex/cohort_a.json, docs/reports/legal_corpora_reindex/cohort_b.json, docs/reports/legal_corpora_reindex/cohort_c.json, docs/reports/legal_corpora_reindex/cohort_d.json
- Validation: python scripts/ops/legal_data/certify_state_laws_cohort.py --cohorts A,B,C,D --check
- Acceptance: All sixteen jurisdictions pass without sample caps, fallback admission, or unresolved failed-final items.
- Gap task: LCR-009
- Refinement: One child per failed jurisdiction, then per code family/frontier if a state has multiple official corpora.
- Embedding query: Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho Illinois Indiana Iowa Kansas statutes
- AST query: state_scrapers alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho illinois indiana iowa kansas
- Parallel lane: 0,1,2,3
- Conflict policy: Each cohort owns only its listed state adapters, tests, and receipt.

## LCR-G022 Complete acquisition cohorts E through H
- Status: active
- Parent: LCR-G020
- Depends on: LCR-G010
- Fib priority: 1
- Track: acquisition
- Priority: P0
- Bundle: cohorts-e-h
- Goal: Certify KY, LA, ME, MD, MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ, NM, and NY.
- Evidence: Cohort E-H receipts and sixteen jurisdiction receipts with closed official frontiers.
- Outputs: docs/reports/legal_corpora_reindex/cohort_e.json, docs/reports/legal_corpora_reindex/cohort_f.json, docs/reports/legal_corpora_reindex/cohort_g.json, docs/reports/legal_corpora_reindex/cohort_h.json
- Validation: python scripts/ops/legal_data/certify_state_laws_cohort.py --cohorts E,F,G,H --check
- Acceptance: All sixteen jurisdictions pass; especially low prior counts for LA, MA, MT, NJ, and NY cannot be inherited as success.
- Gap task: LCR-013
- Refinement: One child per failed jurisdiction, then per code family/frontier if needed.
- Embedding query: Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota Mississippi Missouri Montana Nebraska Nevada New Hampshire New Jersey New Mexico New York statutes
- AST query: state_scrapers kentucky louisiana maine maryland massachusetts michigan minnesota mississippi missouri montana nebraska nevada new_hampshire new_jersey new_mexico new_york
- Parallel lane: 0,1,2,3
- Conflict policy: Each cohort owns only its listed state adapters, tests, and receipt.

## LCR-G023 Complete acquisition cohorts I through M including DC
- Status: active
- Parent: LCR-G020
- Depends on: LCR-G010
- Fib priority: 1
- Track: acquisition
- Priority: P0
- Bundle: cohorts-i-m
- Goal: Certify NC, ND, OH, OK, OR, PA, RI, SC, SD, TN, TX, UT, VT, VA, WA, WV, WI, WY, and the District of Columbia.
- Evidence: Cohort I-M receipts and nineteen jurisdiction receipts with closed official frontiers.
- Outputs: docs/reports/legal_corpora_reindex/cohort_i.json, docs/reports/legal_corpora_reindex/cohort_j.json, docs/reports/legal_corpora_reindex/cohort_k.json, docs/reports/legal_corpora_reindex/cohort_l.json, docs/reports/legal_corpora_reindex/cohort_m.json
- Validation: python scripts/ops/legal_data/certify_state_laws_cohort.py --cohorts I,J,K,L,M --check
- Acceptance: All nineteen jurisdictions pass; DC is a required first-class jurisdiction and prior OR-only legacy artifacts do not substitute for the full cohort.
- Gap task: LCR-017
- Refinement: One child per failed jurisdiction, then per code family/frontier if needed; DC cannot be excluded by an all-states default.
- Embedding query: North Carolina North Dakota Ohio Oklahoma Oregon Pennsylvania Rhode Island South Carolina South Dakota Tennessee Texas Utah Vermont Virginia Washington West Virginia Wisconsin Wyoming District Columbia statutes
- AST query: state_scrapers north_carolina north_dakota ohio oklahoma oregon pennsylvania rhode_island south_carolina south_dakota tennessee texas utah vermont virginia washington west_virginia wisconsin wyoming district_of_columbia
- Parallel lane: 0,1,2,3
- Conflict policy: Each cohort owns only its listed state adapters, tests, and receipt.

## LCR-G024 Reconcile cohort evidence and refill every acquisition gap
- Status: active
- Parent: LCR-G020
- Depends on: LCR-G021, LCR-G022, LCR-G023
- Fib priority: 1
- Track: acquisition-assurance
- Priority: P0
- Bundle: coverage-reconciliation
- Goal: Prove exact 51-jurisdiction coverage and turn every contradiction or failed frontier into bounded repair work.
- Evidence: Machine-readable 51-jurisdiction matrix and an empty unexplained-gap set.
- Outputs: docs/reports/legal_corpora_reindex/full_scrape_coverage.json
- Validation: python scripts/ops/legal_data/certify_state_laws_full_scrape.py --require-jurisdictions 51 --check
- Acceptance: Jurisdiction set, discovered/fetched/disposition arithmetic, source authority, checksums, full-text metrics, and frontier closure reconcile; refill has no unresolved finding.
- Gap task: LCR-022
- Refinement: Generate continuation tasks linked to the failing receipt; do not mark aggregate coverage complete until their replacement evidence passes.
- Embedding query: aggregate coverage matrix gaps receipts row accounting all jurisdictions
- AST query: certify_state_laws_full_scrape coverage admission ledger objective refill
- Parallel lane: 2,3
- Conflict policy: One serialized aggregator owns aggregate reports; repair tasks own new jurisdiction evidence and depend on the failed cohort.

## LCR-G030 Build a canonical, provenance-rich, bounded state-law corpus
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G010, LCR-G020
- Fib priority: 2
- Track: corpus
- Priority: P0
- Bundle: canonical-corpus
- Goal: Normalize verified source evidence into unique content/legal identities, semantic chunks, quarantine, and bounded artifact descriptors.
- Evidence: Admission ledger, corpus/chunk tests, descriptor reports, and 100 percent source-row accounting.
- Outputs: docs/reports/legal_corpora_reindex/admission.json
- Validation: python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py --validation-only --check
- Acceptance: All admitted rows have entry_cid/legal_id/source_cid and official provenance; no duplicate primary keys, sample/navigation rows, unsafe paths, or unaccounted inputs remain.
- Gap task: LCR-024
- Refinement: Add parser/identity/chunk-boundary child tasks for jurisdiction-specific anomalies without weakening shared identity.
- Embedding query: canonical state statute identity provenance chunks quarantine bounded parquet
- AST query: canonical_legal_corpora state_laws identity chunker hf_graphrag artifacts
- Parallel lane: 0,1,2
- Conflict policy: Identity, chunking, and artifact-adapter tasks own separate modules; corpus assembly follows acquisition.

## LCR-G040 Produce complete sparse, dense, and graph retrieval families
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G030
- Fib priority: 2
- Track: indexing
- Priority: P0
- Bundle: sparse-graphrag
- Goal: Build term-range BM25, pinned centroid-routed vectors, legal/provenance graph, two-way bounded adjacency, locators, and a coherent manifest.
- Evidence: Family summaries, row-conservation proofs, centroid/adjacency checks, and manifest closure.
- Outputs: docs/reports/legal_corpora_reindex/index_reconciliation.json
- Validation: python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py --fixture-only --check
- Acceptance: Every admitted chunk routes through each required family as declared; 4,096 and centroid bounds hold physically; no required semantic family is missing.
- Gap task: LCR-027
- Refinement: Add family- or jurisdiction-specific tasks for skew, recall, graph references, lineage, or descriptor drift.
- Embedding query: BM25 term range GTE small centroids legal graph adjacency manifest locators state laws
- AST query: retrieval/hf_graphrag bm25 vectors graph adjacency manifest state_laws
- Parallel lane: 0,1,2,3
- Conflict policy: Each artifact family has one producer; manifest assembly depends on all producers.

## LCR-G050 Query the immutable Hub release without cloning it
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G040
- Fib priority: 3
- Track: query
- Priority: P0
- Bundle: direct-hub-query
- Goal: Expose bounded BM25, vector, hybrid, neighbor, graph-walk, and semantic graph-walk modes with jurisdiction filters and verified fetch traces.
- Evidence: Offline cache replay, immutable fake-Hub tests, CLI/API tests, and sparse fetch traces.
- Outputs: docs/reports/legal_corpora_reindex/query_contract.json
- Validation: python -m pytest tests/unit/processors/legal_data/test_state_laws_sparse_query.py tests/unit/scripts/test_query_state_laws_hf.py -q
- Acceptance: Query results and explanations are stable by CID; only justified control-plane and routed shards are fetched within explicit budgets.
- Gap task: LCR-033
- Refinement: Create mode-specific tasks for routing, filters, hydration, cache, or budget failures.
- Embedding query: direct Hugging Face state laws query BM25 vector hybrid graph jurisdiction filters
- AST query: state_laws query hf resolver remote engine CLI
- Parallel lane: 1,2
- Conflict policy: Engine and CLI have separate owners; public exports integrate after both.

## LCR-G060 Prove legal quality, security, reproducibility, and local end to end behavior
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G030, LCR-G040, LCR-G050
- Fib priority: 3
- Track: assurance
- Priority: P0
- Bundle: evaluation
- Goal: Seal jurisdiction-diverse relevance labels and prove retrieval quality, graph integrity, deterministic builds, resource safety, tamper resistance, and a clean full local release.
- Evidence: Gold set, metrics, security suite, two-build comparison, and E2E receipt.
- Outputs: docs/reports/legal_corpora_reindex/evaluation.json, docs/reports/legal_corpora_reindex/local_e2e.json
- Validation: python scripts/ops/legal_data/evaluate_state_laws_sparse_graphrag.py --check; python scripts/ops/legal_data/build_state_laws_sparse_graphrag.py --full --check
- Acceptance: Sealed thresholds pass across jurisdiction sizes and source shapes; no fixture-only result is labeled as live full-corpus proof.
- Gap task: LCR-035
- Refinement: Generate metric-, jurisdiction-, security-, or reproducibility-specific tasks when any threshold or invariant fails.
- Embedding query: state statute retrieval gold set recall precision graph integrity determinism security
- AST query: evaluate_state_laws build_state_laws tamper reproducibility e2e
- Parallel lane: 0,1,2,3
- Conflict policy: Gold labels are frozen before tuning; evaluation and build receipts are regenerated from final artifacts.

## LCR-G070 Stage and canary the exact release candidate
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G060
- Fib priority: 5
- Track: release
- Priority: P0
- Bundle: staging
- Goal: Assemble a descriptor-complete candidate, upload it additively to staging, resolve the immutable SHA, redownload it, and run real Viewer/retrieval/coverage canaries.
- Evidence: Candidate receipt, staging commit SHA, descriptor verification, Viewer configs, coverage matrix, and query canary.
- Outputs: docs/reports/legal_corpora_reindex/release_candidate.json, docs/reports/legal_corpora_reindex/staging_canary.json
- Validation: python scripts/ops/legal_data/canary_state_laws_hf_release.py --require-live-staging --check
- Acceptance: The staged revision exactly matches the final local manifest and all 51 jurisdictions; no fixture baseline is accepted as the staging canary.
- Gap task: LCR-039
- Refinement: Create upload-part, Viewer-schema, descriptor, or canary repair tasks while retaining the same manifest identity.
- Embedding query: state laws release candidate staging upload immutable canary dataset viewer
- AST query: build_state_laws_hf_release stage_state_laws canary huggingface
- Parallel lane: 0,1,2
- Conflict policy: Candidate assembly precedes one serialized uploader; canary is read-only against the resulting SHA.

## LCR-G080 Publish and verify the authorized public revision
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G070
- Fib priority: 8
- Track: publication
- Priority: P0
- Bundle: public-release
- Goal: Use the recorded operator authorization to upload the exact staged manifest additively to justicedao/ipfs_state_laws and verify its immutable public SHA.
- Evidence: Pre-publication authorization receipt, Hub commit response, public pin, redownload verification, and production query benchmark.
- Outputs: docs/reports/legal_corpora_reindex/publication_receipt.json, docs/reports/legal_corpora_reindex/public_canary.json
- Validation: python scripts/ops/legal_data/check_state_laws_public_release.py --require-public-pin --check
- Acceptance: Public files match the staged manifest; all 51 jurisdictions and semantic families pass remotely; credentials are absent from all evidence.
- Gap task: LCR-042
- Refinement: Add bounded multipart retry, authentication requirement, remote consistency, Viewer, or query tasks; never claim success without the public immutable pin.
- Embedding query: publish justicedao ipfs_state_laws public immutable revision verify upload
- AST query: publish_state_laws hf api upload_folder commit canary public
- Parallel lane: 0,2,3
- Conflict policy: One uploader owns mutation; verification tasks are read-only and depend on its exact receipt.

## LCR-G090 Preserve compatibility, rehearse rollback, and seal final operations evidence
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G080
- Fib priority: 13
- Track: operations
- Priority: P0
- Bundle: finalization
- Goal: Keep legacy configurations usable, rehearse rollback to the previous pin, document update/resume procedures, and seal the final root evidence.
- Evidence: Compatibility report, rollback rehearsal, operations runbook, public pin, and root final receipt.
- Outputs: docs/reports/legal_corpora_reindex/state_final_release_receipt.json
- Validation: python scripts/ops/legal_data/check_state_laws_public_release.py --check-final
- Acceptance: Operators can reproduce queries at new and previous pins, resume incremental updates, detect stalls, and roll back advertisement without deleting history.
- Gap task: LCR-045
- Refinement: Create compatibility, rollback, documentation, monitoring, or update-cadence tasks for any unresolved operational evidence.
- Embedding query: state laws legacy compatibility rollback operations update monitoring final receipt
- AST query: state_laws runbook rollback public release status refill
- Parallel lane: 0,1,3
- Conflict policy: Compatibility and rollback precede the single terminal evidence assembler.

## LCR-G100 Freeze Federal Register baseline, completeness, schema, and gold contracts
- Status: active
- Parent: LCR-G000
- Depends on:
- Fib priority: 1
- Track: federal-foundation
- Priority: P0
- Bundle: federal-foundation
- Goal: Bind the old Hub pin, official authorities, immutable observation cutoff, page/document/text completeness oracle, stable identity/release schema, and sealed retrieval labels.
- Evidence: Reproducible baseline inventory, official-source policy, adversarial completion receipts, schema tests, and checksum-sealed gold set.
- Outputs: docs/reports/legal_corpora_reindex/federal_baseline.json, docs/architecture/federal_register_sparse_graphrag_schema.md, tests/fixtures/legal_ir/federal_register_gold_v1.json
- Validation: python scripts/validate_legal_corpora_reindex_board.py --check-all
- Acceptance: The old 993703/993708 contradiction, 2026-03-02 endpoint, missing full-text/card contract, immutable cutoff, official page closure, body dispositions, and release identities are explicit and fail closed.
- Gap task: LCR-048
- Refinement: Add source-, partition-, schema-, identity-, or label-specific child work when the official contract is ambiguous; never infer full text or currentness.
- Embedding query: Federal Register official API GovInfo cutoff completeness document number full text schema gold set
- AST query: federal_register inventory scraper metadata jsonld parquet embeddings upload quality
- Parallel lane: 0,2,3
- Conflict policy: Four foundation tasks own disjoint report/policy/schema/gold outputs and can run with state foundation work.

## LCR-G110 Acquire and materialize the cutoff-bound Federal Register corpus
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G100
- Fib priority: 1
- Track: federal-acquisition
- Priority: P0
- Bundle: federal-acquisition
- Goal: Close every official date partition and result page through the pinned cutoff, acquire or type every body-text disposition, normalize identity, and materialize a bounded provenance-rich corpus.
- Evidence: Official inventory receipt, page and response hashes, full-text coverage ledger, identity collision report, admission/recovery ledger, and delta from 2026-03-02.
- Outputs: docs/reports/legal_corpora_reindex/federal_inventory.json, docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json, docs/reports/legal_corpora_reindex/federal_admission.json
- Validation: python scripts/ops/legal_data/acquire_federal_register_full.py --fixture-only --check
- Acceptance: Cutoff-relative enumeration, fetch, disposition, duplicate, text, admission, and recovery arithmetic reconciles with zero unresolved page or failed-final item.
- Gap task: LCR-052
- Refinement: Split gaps by date partition, API page, source host, document type, body format, or identity collision with bounded checkpoints and evidence.
- Embedding query: acquire complete Federal Register date partition pagination official full text resume reconciliation
- AST query: federal_register acquisition pagination checkpoint fulltext identity corpus
- Parallel lane: 0,1,3
- Conflict policy: Inventory, full-text, identity, and materialization are dependency-ordered; checkpoint roots never overlap state acquisition.

## LCR-G120 Build and query Federal Register sparse, dense, and graph families
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G110
- Fib priority: 2
- Track: federal-index-query
- Priority: P0
- Bundle: federal-sparse-graphrag
- Goal: Build term-routed BM25, pinned centroid-routed embeddings, agency/rulemaking/citation/provenance graph, two-way adjacency, immutable-Hub query engine, and API/CLI.
- Evidence: Family conservation and bound reports, model receipt, centroid routes, graph/adjacency inversion, immutable fake-Hub traces, and API/CLI tests.
- Outputs: docs/reports/legal_corpora_reindex/federal_bm25.json, docs/reports/legal_corpora_reindex/federal_vectors.json, docs/reports/legal_corpora_reindex/federal_graph.json, docs/reports/legal_corpora_reindex/federal_query_contract.json
- Validation: python -m pytest tests/unit/processors/legal_data/test_federal_register_sparse_query.py tests/unit/scripts/test_query_federal_register_hf.py -q
- Acceptance: Every searchable chunk reconciles across declared families, physical routes and bounds are true, and all query modes use justified sparse immutable-revision fetches.
- Gap task: LCR-056
- Refinement: Add artifact-, route-, citation-, filter-, cache-, or query-mode child work without changing the sealed identity/vector-space contract.
- Embedding query: Federal Register BM25 GTE small centroids agency rule citation graph adjacency immutable Hugging Face query
- AST query: federal_register bm25 vectors graph sparse_query query_federal_register_hf
- Parallel lane: 0,1,2,3
- Conflict policy: BM25/vector/graph producers are parallel and file-disjoint; query integration follows all three.

## LCR-G130 Build, evaluate, stage, and canary the exact Federal Register release
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G100, LCR-G110, LCR-G120
- Fib priority: 3
- Track: federal-release
- Priority: P0
- Bundle: federal-release
- Goal: Run resumable full/delta builds, assemble one descriptor-complete Viewer-compatible candidate, prove quality/security/determinism, upload to explicit staging, and redownload the live immutable staging revision.
- Evidence: Build checkpoints, candidate manifest and card, sealed metrics, security and reproducibility reports, staging SHA, full redownload, and live query canary.
- Outputs: docs/reports/legal_corpora_reindex/federal_candidate.json, docs/reports/legal_corpora_reindex/federal_evaluation.json, docs/reports/legal_corpora_reindex/federal_staging_canary.json
- Validation: python scripts/ops/legal_data/canary_federal_register_hf_release.py --require-live-staging --check
- Acceptance: Candidate is complete and deterministic; staging exactly matches it; semantic families, Viewer, cutoff/body coverage, tamper/resource gates, and real remote queries pass.
- Gap task: LCR-061
- Refinement: Generate build-family, metric, security, Viewer, multipart upload, or live-canary repair work tied to the failing receipt and same candidate identity.
- Embedding query: Federal Register streaming build delta release manifest dataset card evaluation staging immutable canary
- AST query: build_federal_register_hf_release evaluate stage canary manifest viewer
- Parallel lane: 1,2,3
- Conflict policy: Build/package/evaluation/staging are serialized by dependencies; staging mutation has one owner.

## LCR-G140 Publish Federal Register and seal dual-release operations evidence
- Status: active
- Parent: LCR-G000
- Depends on: LCR-G090, LCR-G130
- Fib priority: 5
- Track: federal-public-finalization
- Priority: P0
- Bundle: dual-public-finalization
- Goal: Additively publish the exact Federal Register candidate, verify its immutable public revision, prove shared substrate/vector compatibility with the state release, rehearse both rollbacks, exhaust refill findings, and seal root evidence.
- Evidence: Prepublication seal, Hub operation receipt, Federal public SHA/canary, cross-corpus compatibility report, dual rollback rehearsal, refill closure, and combined final receipt.
- Outputs: docs/reports/legal_corpora_reindex/federal_publication_receipt.json, docs/reports/legal_corpora_reindex/federal_public_canary.json, docs/reports/legal_corpora_reindex/cross_corpus_canary.json, docs/reports/legal_corpora_reindex/final_release_receipt.json
- Validation: python scripts/ops/legal_data/check_legal_corpora_final_release.py --check
- Acceptance: Both exact authorized targets have manifest-bound verified public revisions; prior pins remain usable; no generated task, goal, gap, block, or active worker remains; root acceptance is content-addressed.
- Gap task: LCR-065
- Refinement: Add bounded publication-retry, remote-consistency, compatibility, rollback, monitoring, or update tasks; never weaken either corpus gate or mutate an alternate repository.
- Embedding query: publish Federal Register state laws dual immutable Hugging Face verify rollback refill final receipt
- AST query: publish_federal_register check_public legal_corpora rollback status objective refill
- Parallel lane: 1,2,3
- Conflict policy: Federal publication has one mutation owner; all later composition, verification, rollback, and terminal work is dependency-ordered and read-only.

## LCR-G141 Prove source rights and redistribution admissibility before publication
- Status: active
- Parent: LCR-G010
- Fib priority: 1
- Track: source-rights-assurance
- Priority: P0
- Bundle: source-rights-assurance
- Goal: Prove that every source and content scope admitted to either public corpus may be redistributed under an explicit, current, evidence-backed policy.
- Evidence: Exact-source rights catalog, observed terms and robots digests, attribution and scope decisions, quarantine dispositions, and a content-addressed cross-corpus compliance receipt.
- Outputs: data/legal/legal_source_rights_catalog.json, docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json
- Validation: python -m pytest tests/unit/processors/legal_data/test_legal_source_rights_policy.py tests/unit/processors/legal_data/test_legal_corpora_publication_gate.py -q; python scripts/ops/legal_data/audit_legal_source_rights.py --require-live-source-evidence --check
- Acceptance: Both target candidates contain only source/content scopes with current allowed evidence, required attribution/notices, and receipt-bound card/manifest metadata; unknown, prohibited, stale, or unreviewed proprietary material is quarantined and every staging/main mutation fails closed without the exact receipt.
- Gap task: LCR-077
- Refinement: Split uncertain findings by source and content scope, then add separate evidence-research or release-binding tasks without weakening the cross-corpus deny-on-unknown rule.
- Embedding query: state statutes Federal Register source rights license terms redistribution attribution government edicts annotations database robots
- AST query: legal_source_rights publication_gate release_schema dataset_card manifest compliance receipt
- Parallel lane: 1,2
- Conflict policy: Contract, live evidence, and release integration are dependency ordered; source-specific research may run in parallel but one receipt assembler owns the final catalog.

## LCR-G142 Bind legal-corpora publication authority to canonical live evidence
- Status: active
- Parent: LCR-G080
- Depends on: LCR-G141
- Fib priority: 1
- Track: publication-authority-repair
- Priority: P0
- Bundle: publication-authority-repair
- Goal: Replace caller-asserted publication authority with a fail-closed runtime that derives repository, task ancestry, receipts, manifest, commit, credential principal, and seal evidence from canonical live sources before either legal-corpora dataset can be mutated.
- Evidence: Four-phase denial and authorization tests against temporary clean Git repositories, independently recomputed receipt and manifest digests, environment-credential identity probes, seal-time bindings, and callback traces proving zero network mutations on every denial or evidence race.
- Outputs: ipfs_datasets_py/processors/legal_data/legal_corpora_publication_gate.py, ipfs_datasets_py/processors/legal_data/legal_corpora_publication_runtime.py, tests/unit/processors/legal_data/test_legal_corpora_publication_gate.py, tests/unit/processors/legal_data/test_legal_corpora_publication_runtime.py, tests/fixtures/legal_ir/legal_corpora_publication_gate.json
- Validation: python -m pytest tests/unit/processors/legal_data/test_legal_corpora_publication_gate.py tests/unit/processors/legal_data/test_legal_corpora_publication_runtime.py -q; python scripts/validate_legal_corpora_reindex_board.py --check-all
- Acceptance: State and Federal staging and main authorization can only be constructed from one clean exact Git HEAD and fixed repository-relative control and evidence paths; caller-supplied status, ancestry, receipt, digest, commit, credential, or seal assertions cannot authorize. Every required receipt and manifest is schema-validated and independently rehashed, the environment token's verified principal has write authority for the exact target, main seals explicitly predate mutation and bind every authority input, and one callback-owning runtime rechecks evidence immediately before invoking the upload exactly once.
- Gap task: LCR-080
- Refinement: Split only schema-specific receipt-digest or uploader-adapter defects discovered by the four-phase integration matrix; do not restore caller authority or weaken any mutation phase.
- Embedding query: legal corpora publication gate canonical taskboard receipt digest exact git commit environment credential identity prepublication seal callback
- AST query: legal_corpora_publication_gate authorize_and_mutate taskboard release_policy receipt manifest credential seal uploader
- Parallel lane: 1
- Conflict policy: Ordered repair of the shared publication gate; it owns the canonical runtime adapter and tests, performs no Hub mutation, and leaves downstream uploader scripts and protected control-plane files to their existing owners.

## LCR-G143 Prove complete authenticated live baseline provenance
- Status: active
- Parent: LCR-G010
- Fib priority: 1
- Track: foundation-baseline-provenance-hardening
- Priority: P0
- Bundle: foundation-baseline-provenance-hardening
- Goal: Replace partial, sample-based, or self-asserted baseline observations with one current authenticated receipt whose complete remote, Viewer, Parquet, local-salvage, and digest evidence fails closed before either corpus can be published.
- Evidence: Authenticated identity and API response hashes, exact pinned commits, exhaustion-proved recursive remote inventories with per-entry metadata, state and Federal Viewer and config response hashes, all 51 state Parquet hashes and counts including DC, Federal Parquet hash and count, complete configured salvage dispositions, and recursively verified canonical receipt digests.
- Outputs: data/legal/legal_corpora_live_baseline_receipt.schema.json, docs/reports/legal_corpora_reindex/live_baseline_provenance_receipt.json
- Validation: python -m pytest tests/unit/scripts/test_audit_legal_corpora_live_baseline.py tests/integration/legal_data/test_audit_legal_corpora_live_baseline_fail_closed.py -q; python scripts/ops/legal_data/audit_legal_corpora_live_baseline.py --require-live-hub --require-local-salvage-inventory --check
- Acceptance: No constant, fixture, injected transport, inventory sample, missing or read-failed file, unavailable or unhashed Viewer response, all-missing salvage set, unchecked mismatch, stale receipt, or syntactic-only digest can authorize; the on-disk receipt exists and exactly binds independently recomputed current evidence at both pins.
- Gap task: LCR-081
- Refinement: Split only a separately evidenced Hub-pagination, Viewer-protocol, Parquet-scale, or salvage-containment defect; never weaken live mode or substitute a fixture.
- Embedding query: authenticated Hugging Face exact revision complete recursive inventory Viewer config Parquet row count local salvage canonical digest fail closed
- AST query: audit_legal_corpora_live_baseline list_repo_tree datasets_server parquet salvage validate receipt_sha256
- Parallel lane: 3
- Conflict policy: Strict ordered successor to LCR-070 and sole owner of its verifier, schema, tests, and receipt while hardening; no overlap with LCR-070 or any other receipt writer.

## LCR-G144 Make source-rights admission evaluator-complete and time-trusted
- Status: active
- Parent: LCR-G010
- Depends on: LCR-G141
- Fib priority: 1
- Track: source-rights-contract-hardening
- Priority: P0
- Bundle: source-rights-contract-hardening
- Goal: Ensure every rights API path uses one deny-on-unknown evaluator backed by canonical license identity, explicit robots and access disposition, required transformation and archive permissions, exact producer identity, and a trusted freshness clock.
- Evidence: Versioned SPDX registry digest and LicenseRef definitions, exhaustive mutated-record denial matrix, robots, derivative and archive, identity, temporal-order tests, admitted-record and evaluator parity, and a fixture audit receipt.
- Outputs: data/legal/spdx_license_registry.json, data/legal/legal_source_rights_catalog.schema.json, tests/fixtures/legal_ir/legal_source_rights_catalog.json
- Validation: python -m pytest tests/unit/processors/legal_data/test_legal_source_rights_policy.py tests/unit/processors/legal_data/test_legal_source_rights_policy_fail_closed.py -q; python scripts/ops/legal_data/audit_legal_source_rights.py --fixture-only --check
- Acceptance: No regex-shaped invented license, undefined LicenseRef, denied, unknown, or unavailable robots disposition, missing derivative or archive permission, unsafe convenience selector, wrong task, goal, or mode identity, self-chosen future seal, stale evidence or review, or impossible review chronology can admit a scope.
- Gap task: LCR-082
- Refinement: Split only registry-refresh or source-specific policy semantics; every selector and caller must retain evaluator parity and trusted-time denial.
- Embedding query: canonical SPDX LicenseRef robots disposition derivatives archive rights admitted records evaluator parity task identity trusted freshness
- AST query: legal_source_rights_policy normalize_spdx LicenseRef robots evaluate_scope_rights admitted_records sealed_at reviewed_at
- Parallel lane: 2
- Conflict policy: Strict ordered successor to LCR-077 and sole owner of the rights contract, schema, audit, and fixtures during hardening; live catalog generation remains ordered after it.

## LCR-G145 Reseal live source rights and publication authority after hardening
- Status: active
- Parent: LCR-G080
- Depends on: LCR-G142, LCR-G143, LCR-G144
- Fib priority: 1
- Track: source-rights-authority-reseal
- Priority: P0
- Bundle: source-rights-authority-reseal
- Goal: Regenerate live cross-corpus rights evidence under the hardened evaluator and make it the sole rights basis for both release schemas and the canonical pre-mutation runtime.
- Evidence: Fresh source and terms observations, evaluator-complete catalog and compliance digests, schema and manifest bindings, four-phase canonical authority tests, environment principal proof, and zero-callback denial traces.
- Outputs: data/legal/legal_source_rights_catalog.json, docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json, ipfs_datasets_py/processors/legal_data/legal_corpora_publication_runtime.py
- Validation: python scripts/ops/legal_data/audit_legal_source_rights.py --require-live-source-evidence --check; python -m pytest tests/unit/processors/legal_data/test_state_laws_release_schema.py tests/unit/processors/legal_data/test_federal_register_release_schema.py tests/unit/processors/legal_data/test_legal_corpora_publication_gate.py tests/unit/processors/legal_data/test_legal_corpora_publication_runtime.py -q
- Acceptance: Every pre-hardening receipt and decision is invalidated; both corpus manifests and cards bind the fresh evaluator-admitted receipt; and every staging or main mutation remains denied until the exact current receipt, task closure, manifest, principal, and phase-correct seal pass immediately before callback.
- Gap task: LCR-083
- Refinement: Split only a source-specific live evidence defect or a phase-specific binding defect, and keep the final cross-corpus receipt and runtime serialization ordered.
- Embedding query: reseal live legal source rights compliance release schema manifest canonical publication authority runtime
- AST query: audit_legal_source_rights release_schema legal_corpora_publication_gate legal_corpora_publication_runtime
- Parallel lane: 1
- Conflict policy: Final ordered successor of the rights evidence, rights integration, authority runtime, and hardening tasks; one task owns the resealed cross-corpus receipt and gate bindings.

## LCR-G146 Prove exact-51 live state-scrape completeness is candidate-bound
- Status: active
- Parent: LCR-G080
- Depends on: LCR-G024, LCR-G143, LCR-G145
- Fib priority: 1
- Track: state-full-live-acceptance-hardening
- Priority: P0
- Bundle: state-full-live-acceptance-hardening
- Goal: Replace self-asserted cohort closure with fresh official-source evidence for every state and DC and bind that evidence exactly to the state release candidate and every publication decision.
- Evidence: Fresh HTTPS response hashes and exhaustive frontier, page, and bundle observations, per-jurisdiction attempts and checkpoints, exact 51 source-item, row, key, and content digests, disposition arithmetic, candidate-shard reconciliation, live-baseline comparison, and zero-callback denial traces.
- Outputs: data/legal/state_laws_full_scrape_acceptance.schema.json, docs/reports/legal_corpora_reindex/full_scrape_acceptance.json, docs/reports/legal_corpora_reindex/release_candidate.json, ipfs_datasets_py/processors/legal_data/legal_corpora_publication_runtime.py, ipfs_datasets_py/huggingface/protected_repo_guard.py, scripts/ops/legal_data/audit_legal_corpora_hugging_face_mutation_paths.py, data/legal/legal_corpora_hugging_face_mutation_path_audit.schema.json, docs/reports/legal_corpora_reindex/hugging_face_mutation_path_audit.json
- Validation: python -m pytest tests/unit/scripts/test_audit_state_laws_full_scrape_acceptance.py tests/integration/legal_data/test_state_laws_full_scrape_acceptance_fail_closed.py tests/unit/scripts/test_build_state_laws_hf_release.py tests/unit/processors/legal_data/test_state_laws_release_schema.py tests/unit/processors/legal_data/test_legal_corpora_publication_gate.py tests/unit/processors/legal_data/test_legal_corpora_publication_runtime.py tests/unit/processors/legal_data/test_legal_corpora_protected_repo_mutations.py tests/unit/scripts/test_audit_legal_corpora_hugging_face_mutation_paths.py tests/unit/legal_scrapers/test_refresh_state_laws_corpus.py tests/unit/legal_scrapers/test_legal_source_recovery.py tests/unit/legal_scrapers/test_legal_source_recovery_promotion.py tests/unit/legal_scrapers/test_justicedao_dataset_inventory.py tests/unit/legal_scrapers/test_legal_scraper_daemon.py tests/unit/legal_scrapers/test_merge_state_admin_recovered_rows.py tests/mcp/unit/test_hf_pipeline_engine.py tests/unit/huggingface/test_generic_publisher.py tests/unit/logic/security_ir/cvefixes/test_publish_command.py tests/unit/test_netherlands_laws_pipeline.py tests/unit/processors/patent/test_hf_release_v2.py -q; python scripts/ops/legal_data/audit_state_laws_full_scrape_acceptance.py --require-live-official --require-jurisdictions 51 --require-production-candidate --check; python scripts/ops/legal_data/audit_legal_corpora_hugging_face_mutation_paths.py --protected-repo justicedao/ipfs_state_laws --protected-repo justicedao/ipfs_federal_register --require-runtime ipfs_datasets_py.processors.legal_data.legal_corpora_publication_runtime --check
- Acceptance: No fixture, injected transport, static test HTML, sample count, caller-declared frontier, or status and digest-only receipt can authorize. Success freshly exhausts every official frontier, reconciles all 51 source items, rows, logical keys, content hashes, attempts, checkpoints, exclusions, quarantines, and failures, and binds the exact admitted shard counts, keys, digests, and deduped union to the exact release manifest; unexplained underfill against either observed official inventory or the authenticated live baseline fails, including the two-row cohort F and I evidence. No direct or indirect Hugging Face writer, daemon flag, CLI, API, MCP path, injected callback, or repository-generic target override can mutate justicedao/ipfs_state_laws or justicedao/ipfs_federal_register unless the one canonical post-LCR-084 runtime revalidates that exact completeness, candidate, task, goal, principal, phase, seal, mutation kind, revision, parent, remote paths, and local byte digests immediately before each individual network mutation; one authorization can never cover a different payload or later write.
- Gap task: LCR-084
- Refinement: Generate one jurisdiction repair task per failed authority or frontier, then split by code family, title, bundle, or pagination boundary; never weaken live observation or candidate equality.
- Embedding query: exact 51 state statute live official scrape frontier response hash candidate shard count key digest underfill
- AST query: certify_state_laws_full_scrape full_scrape_acceptance release_candidate publication_gate
- Parallel lane: 1
- Conflict policy: Ordered successor of LCR-023, LCR-039, LCR-081, and LCR-083; it is the final writer of the state full-scrape receipt, state candidate binding, shared gate and runtime, and protected-repository mutation inventory before publication and performs no Hub mutation.

## LCR-G147 Make Federal full-text exhaustion complete, content-bound, and verifier-time-trusted
- Status: active
- Parent: LCR-G110
- Depends on: LCR-G100
- Fib priority: 1
- Track: federal-fulltext-fail-closed-repair
- Priority: P0
- Bundle: federal-fulltext-fail-closed-repair
- Goal: Replace the merged LCR-075 fail-open semantics with one evaluator that proves the complete LCR-049-derived official authority and format frontier, binds every admitted document to the exact verified body bytes, and uses an explicit trusted verifier clock and exact receipt identity.
- Evidence: Exhaustive per-document authority and format ledger mutation matrix, exact response, content, and admitted-body hash bindings, exact schema, producer, task, goal, and mode tests, zero-future-skew chronology tests, public-helper parity, and regression probes for every demonstrated LCR-075 exploit.
- Outputs: ipfs_datasets_py/processors/legal_data/federal_register_fulltext_gate.py, tests/unit/processors/legal_data/test_federal_register_fulltext_gate.py, tests/unit/processors/legal_data/test_federal_register_fulltext_gate_fail_closed.py, tests/fixtures/legal_ir/federal_register_fulltext_attempt_receipts.json
- Validation: python -m pytest tests/unit/processors/legal_data/test_federal_register_fulltext_gate.py tests/unit/processors/legal_data/test_federal_register_fulltext_gate_fail_closed.py -q
- Acceptance: No failed, skipped, transport-blocked, anti-bot, navigation, error-page, unsupported-format, parse-failed, hashless, partial- or extra-frontier, response-only, content-only, authority-host-or-format-mismatched, identity-omitted-or-defaulted, self-timed, caller-skewed, future-timed, declared-hash-only, or admitted-body-digest-mismatched attempt can prove exhaustion or admission. Every public selector has exact evaluator parity, requires a verifier-owned UTC instant with fixed zero future skew, and exposes no authorizing tolerance override. Only a complete exact LCR-049-derived frontier whose authority-bound usable official body is fetched, response- and content-hash verified, parsed, and byte-bound through a digest independently recomputed from the admitted bytes or immutable artifact-byte stream, or whose every applicable alternative has a source-policy-authorized absence backed by immutable request and response bytes whose hashes are independently recomputed, can pass. Every authorizing identity field must be explicitly present and exactly equal to schema `federal-register-fulltext-gate-v2`, producer `federal_register_fulltext_gate.py@2`, program `legal-corpora-reindex-v1`, task `LCR-085`, goal `LCR-G147`, and mode `live`; no default, alias, coercion, v1 value, or v2 fixture mode can authorize.
- Gap task: LCR-085
- Refinement: Split only authority or format-specific acquisition defects; do not convert availability, parser, transport, or retry failures into evidence of absence and do not weaken identity, hash, chronology, or public-helper parity.
- Embedding query: Federal Register full text authority format exhaustion content hash admitted bytes trusted verifier clock fail closed
- AST query: federal_register_fulltext_gate attempt proves_no_usable_body assert_fulltext_admission content_sha256 verifier_now
- Parallel lane: 1
- Conflict policy: Strict ordered successor and exclusive writer for every LCR-075 output; downstream acquisition and Federal staging and publication remain blocked until repaired evidence is regenerated, and this task performs no Hub mutation.
