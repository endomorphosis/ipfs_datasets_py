# Documentation quality report

| Field | Value |
| --- | --- |
| Interface | `DocumentationQualityReport@1` |
| Validator | `DocumentationValidator@1` |
| Generator | `docs/maintenance/check_docs.py` v1.0.0 |
| Quality task | `IPFSDOC-096` |
| Tool task | `IPFSDOC-006` |
| Started (UTC) | `2026-08-03T23:56:37Z` |
| Finished (UTC) | `2026-08-03T23:56:40Z` |
| Repo root | `/home/barberb/lift_coding/data/agent_supervisor/ipfs_datasets_documentation_refresh_20260803/artifact_completion_run_unblocked_bd0825fcd/shards/0/worktrees/workspace-806bd848d63c-05701c127c35` |
| Scan root | `docs` |
| Git HEAD | `537b8db95fa5250d6a1fa1d52d7ba16cf9866311` |
| Files scanned | 1570 |
| Checks run | markdown_paths, links, anchors, repo_paths, python_modules, metadata, duplicates, python_syntax |
| Errors | 2768 |
| Warnings | 7 |
| Allowlisted | 1926 |
| P0 (authority/entry) | 17 |
| P1 (tree debt) | 2751 |

## Command and tree

```bash
python docs/maintenance/check_docs.py --root docs --report docs/maintenance/QUALITY_REPORT.md
```

Report publishing uses process exit policy **fail-on never** when `--report` is set (unless `--fail-on` is passed explicitly), so the quality artifact can be written and disclosed even when the integrated tree still has non-allowlisted findings. Failures are **not** hidden by expanding allowlists.

## Side-effect and authority notes

- This report was produced offline: **no network fetches** were performed.
- **Filesystem mtimes were not used** as freshness proof; only in-document `Last verified` metadata is considered for metadata checks.
- The checker **does not delete** generated output (`site/`, build artifacts). It only writes this report path when requested.
- Allowlisted archive and before-migration findings are listed below but do not fail the gate unless `--strict-allowlist` is set.
- Optional MkDocs build / external link liveness / live services are **out of scope** for this offline gate (deferred unless separately provisioned).

## Priority summary (P0 / P1)

| Priority | Count | Meaning |
| --- | ---: | --- |
| **P0** | 17 | Canonical metadata gaps, duplicate `Interface` authority, or broken links/anchors on entry/spine pages |
| **P1** | 2751 | Remaining non-allowlisted debt (repo paths, modules, fence syntax, secondary links/anchors, …) |
| Allowlisted | 1926 | Archive / migration / historical paths (reported, non-gating) |

### P0 samples (up to 40)

| Check | Path | Line | Message |
| --- | --- | ---: | --- |
| `anchors` | `docs/faq.md` | 178 | Anchor #troubleshooting not found in docs/user_guide.md |
| `metadata` | `docs/CHANGELOG.md` |  | Status=canonical page missing required metadata: Owner, Source / Source of truth, Audience |
| `metadata` | `docs/FEATURES.md` |  | Status=canonical page missing required metadata: Owner, Source / Source of truth, Audience |
| `metadata` | `docs/developer_guides/REPOSITORY_MAP.md` |  | Status=canonical page missing required metadata: Last verified |
| `metadata` | `docs/getting_started.md` |  | Status=canonical page missing required metadata: Source / Source of truth |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-074.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-090.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-091.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-092.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-093.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-095.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |
| `metadata` | `docs/tutorials/FIRST_DATASET_WORKFLOW.md` |  | Status=canonical page missing required metadata: Source / Source of truth |
| `metadata` | `docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md` |  | Status=canonical page missing required metadata: Source / Source of truth |
| `metadata` | `docs/tutorials/MCP_CLIENT_WORKFLOW.md` |  | Status=canonical page missing required metadata: Source / Source of truth |
| `metadata` | `docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md` |  | Status=canonical page missing required metadata: Source / Source of truth |
| `metadata` | `docs/user_guide.md` |  | Status=canonical page missing required metadata: Source / Source of truth |
| `duplicates` | `docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md` |  | Duplicate canonical Interface declaration: 'RetrievalArchitecture@1' used by 3 pages |

## Counts by check

| Check | Findings |
| --- | ---: |
| `markdown_paths` | 1 |
| `links` | 556 |
| `anchors` | 84 |
| `repo_paths` | 3056 |
| `python_modules` | 558 |
| `metadata` | 19 |
| `duplicates` | 1 |
| `python_syntax` | 699 |

## Allowlist prefixes

- `docs/archive/`
- `docs/archived_stubs/`
- `archive/`
- `docs/knowledge_graphs/archive/`
- `docs/logic/archive/`
- `docs/tdfol/`

## Findings

### error (2768)

| Check | Path | Line | Message | Detail |
| --- | --- | ---: | --- | --- |
| `links` | `docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md` | 211 | Relative link target missing: decisions/ADR-NNN-....md | decisions/ADR-NNN-....md |
| `anchors` | `docs/architecture/github_actions_infrastructure.md` | 16 | In-page anchor not found: #integration-with-ipfs_accelerate_py |  |
| `anchors` | `docs/architecture/mcp_tools_catalog.md` | 26 | In-page anchor not found: #security--auth-tools |  |
| `anchors` | `docs/architecture/mcp_tools_catalog.md` | 43 | In-page anchor not found: #development-tools |  |
| `anchors` | `docs/deployment/DOCKER_DEPLOYMENT_GUIDE.md` | 11 | In-page anchor not found: #production-deployment |  |
| `anchors` | `docs/deployment/DOCKER_DEPLOYMENT_GUIDE.md` | 12 | In-page anchor not found: #troubleshooting |  |
| `anchors` | `docs/examples/finance_usage_examples.md` | 143 | Anchor #graphrag not found in docs/README.md |  |
| `anchors` | `docs/faq.md` | 178 | Anchor #troubleshooting not found in docs/user_guide.md |  |
| `anchors` | `docs/guides/DEPLOYMENT_GUIDE_NEW.md` | 10 | In-page anchor not found: #-docker-deployment |  |
| `anchors` | `docs/guides/DEPLOYMENT_GUIDE_NEW.md` | 11 | In-page anchor not found: #-kubernetes-deployment |  |
| `anchors` | `docs/guides/DEPLOYMENT_GUIDE_NEW.md` | 12 | In-page anchor not found: #-cloud-deployment |  |
| `anchors` | `docs/guides/DEPLOYMENT_GUIDE_NEW.md` | 13 | In-page anchor not found: #-bare-metal-deployment |  |
| `anchors` | `docs/guides/DEPLOYMENT_GUIDE_NEW.md` | 161 | Anchor #monitoring--observability not found in docs/guides/deployment/README.md |  |
| `anchors` | `docs/guides/MCP_TOOLS_COMPREHENSIVE_REFERENCE.md` | 24 | In-page anchor not found: #security--authentication-tools |  |
| `links` | `docs/guides/THEOREM_PROVER_INTEGRATION_GUIDE.md` | 77 | Relative link target missing: proposition | proposition |
| `links` | `docs/guides/THEOREM_PROVER_INTEGRATION_GUIDE.md` | 78 | Relative link target missing: proposition | proposition |
| `links` | `docs/guides/THEOREM_PROVER_INTEGRATION_GUIDE.md` | 79 | Relative link target missing: proposition | proposition |
| `links` | `docs/guides/THEOREM_PROVER_INTEGRATION_GUIDE.md` | 84 | Relative link target missing: exercise_diligent_oversight_ensuring_shareholder_interests_and_securities_compliance | exercise_diligent_oversight_ensuring_shareholder_interests_and_securities_compliance |
| `anchors` | `docs/guides/deployment/docker_deployment.md` | 11 | In-page anchor not found: #production-deployment |  |
| `anchors` | `docs/guides/deployment/docker_deployment.md` | 12 | In-page anchor not found: #vs-code-integration |  |
| `anchors` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md` | 24 | In-page anchor not found: #problems--challenges |  |
| `anchors` | `docs/guides/processors/PROCESSORS_INTEGRATION_INDEX.md` | 146 | Anchor #-import-changes not found in docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md |  |
| `anchors` | `docs/guides/processors/PROCESSORS_INTEGRATION_INDEX.md` | 156 | Anchor #%EF%B8%8F-deprecation-timeline not found in docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md |  |
| `anchors` | `docs/guides/processors/PROCESSORS_REFACTORING_CHANGELOG.md` | 258 | Anchor #deprecation-timeline not found in docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md |  |
| `anchors` | `docs/guides/query_optimization.md` | 17 | In-page anchor not found: #best-practices |  |
| `anchors` | `docs/logic/CEC/ADDITIONAL_THEOREM_PROVERS_STRATEGY.md` | 16 | In-page anchor not found: #implementation-plan |  |
| `anchors` | `docs/logic/CEC/API_INTERFACE_DESIGN.md` | 15 | In-page anchor not found: #authentication--security |  |
| `anchors` | `docs/logic/CEC/API_INTERFACE_DESIGN.md` | 18 | In-page anchor not found: #performance--caching |  |
| `anchors` | `docs/logic/CEC/API_INTERFACE_DESIGN.md` | 19 | In-page anchor not found: #monitoring--logging |  |
| `anchors` | `docs/logic/CEC/API_REFERENCE.md` | 18 | In-page anchor not found: #container--namespace |  |
| `anchors` | `docs/logic/CEC/API_REFERENCE.md` | 23 | In-page anchor not found: #parsing--cleaning |  |
| `anchors` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 20 | In-page anchor not found: #building--running |  |
| `anchors` | `docs/logic/CEC/EXTENDED_NL_SUPPORT_ROADMAP.md` | 14 | In-page anchor not found: #implementation-plan |  |
| `anchors` | `docs/logic/CEC/PERFORMANCE_OPTIMIZATION_PLAN.md` | 15 | In-page anchor not found: #implementation-plan |  |
| `anchors` | `docs/logic/CEC/PERFORMANCE_OPTIMIZATION_PLAN.md` | 16 | In-page anchor not found: #benchmarking--profiling |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 18 | In-page anchor not found: #3-critical-issues |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 19 | In-page anchor not found: #4-phase-1-documentation-consolidation |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 21 | In-page anchor not found: #6-phase-3-feature-completions |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 22 | In-page anchor not found: #7-phase-4-production-excellence |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 23 | In-page anchor not found: #8-phase-5-code-reduction--god-module-splits |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 24 | In-page anchor not found: #9-phase-6-remaining-work-and-continuous-improvement- |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 25 | In-page anchor not found: #10-phase-7-cross-module-bug-fixes-and-tdfol-prover-hardening |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 26 | In-page anchor not found: #11-phase-8-advanced-coverage-and-mcp-b2-testing |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 27 | In-page anchor not found: #12-timeline-and-priorities |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 28 | In-page anchor not found: #13-success-criteria |  |
| `anchors` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 29 | In-page anchor not found: #14-document-inventory-and-disposition |  |
| `anchors` | `docs/logic/QUICKSTART.md` | 120 | Anchor #batch-processing not found in docs/logic/FEATURES.md |  |
| `anchors` | `docs/logic/README.md` | 41 | Anchor #getting-started not found in ipfs_datasets_py/logic/README.md |  |
| `anchors` | `docs/logic/TDFOL/INDEX.md` | 414 | Anchor #-quick-wins-this-week not found in docs/logic/TDFOL/ARCHIVE/QUICK_REFERENCE_2026_02_18.md |  |
| `anchors` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 51 | In-page anchor not found: #code-quality-improvements |  |
| `anchors` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 52 | In-page anchor not found: #performance-optimization |  |
| `anchors` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 53 | In-page anchor not found: #testing-strategy |  |
| `anchors` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 54 | In-page anchor not found: #documentation-plan |  |
| `anchors` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 55 | In-page anchor not found: #deployment--operations |  |
| `anchors` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 56 | In-page anchor not found: #risk-assessment |  |
| `anchors` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 58 | In-page anchor not found: #timeline--resources |  |
| `anchors` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 59 | In-page anchor not found: #appendices |  |
| `anchors` | `docs/logic/zkp/QUICKSTART.md` | 88 | Anchor #api-reference not found in ipfs_datasets_py/logic/zkp/README.md |  |
| `anchors` | `docs/optimizers/INFINITE_TODO_SESSION_SUMMARY.md` | 94 | Anchor #batch-230 not found in docs/optimizers/TODO.md |  |
| `anchors` | `docs/optimizers/INFINITE_TODO_SESSION_SUMMARY.md` | 95 | Anchor #batch-231 not found in docs/optimizers/TODO.md |  |
| `anchors` | `docs/optimizers/INFINITE_TODO_SESSION_SUMMARY.md` | 96 | Anchor #batch-232 not found in docs/optimizers/TODO.md |  |
| `anchors` | `docs/optimizers/INFINITE_TODO_SESSION_SUMMARY.md` | 97 | Anchor #batch-233 not found in docs/optimizers/TODO.md |  |
| `anchors` | `docs/optimizers/INFINITE_TODO_SESSION_SUMMARY.md` | 98 | Anchor #batch-234 not found in docs/optimizers/TODO.md |  |
| `anchors` | `docs/optimizers/INFINITE_TODO_SESSION_SUMMARY.md` | 99 | Anchor #batch-235 not found in docs/optimizers/TODO.md |  |
| `links` | `docs/reports/DOCS_ACTION_CHECKLIST_2026_01_31.md` | 33 | Relative link target missing: archive/deprecated/ | archive/deprecated/ |
| `links` | `docs/reports/DOCS_ACTION_CHECKLIST_2026_01_31.md` | 37 | Relative link target missing: archive/deprecated/master_documentation_index.md | archive/deprecated/master_documentation_index.md |
| `links` | `docs/security_verification/production_release_decision_policy.md` | 5 | Relative link target missing: ../../security_ir_artifacts/policies/security-decision-policy.json | ../../security_ir_artifacts/policies/security-decision-policy.json |
| `repo_paths` | `docs/AGENTIC_LEGAL_SCRAPER_DAEMON.md` | 346 | Referenced repository path not found: cycles/cycle_XXXX.json |  |
| `repo_paths` | `docs/AGENTIC_LEGAL_SCRAPER_DAEMON.md` | 347 | Referenced repository path not found: cycles/cycle_XXXX_pending_retry.json |  |
| `repo_paths` | `docs/AGENTIC_LEGAL_SCRAPER_DAEMON.md` | 349 | Referenced repository path not found: cycles/cycle_XXXX_document_gaps.json |  |
| `repo_paths` | `docs/AGENTIC_LEGAL_SCRAPER_DAEMON.md` | 351 | Referenced repository path not found: cycles/cycle_XXXX_router_assist.json |  |
| `repo_paths` | `docs/AGENTIC_LEGAL_SCRAPER_DAEMON.md` | 353 | Referenced repository path not found: cycles/cycle_XXXX_parallel_admin_assist.json |  |
| `repo_paths` | `docs/ARCHITECTURE_VALIDATION_QUICK_START.md` | 467 | Referenced repository path not found: .github/workflows/ |  |
| `repo_paths` | `docs/ARCHITECTURE_VALIDATION_REPORT.md` | 362 | Referenced repository path not found: ipfs_datasets_py/p2p/ |  |
| `repo_paths` | `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | 195 | Referenced repository path not found: graph_tools/graph_create.py |  |
| `repo_paths` | `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | 226 | Referenced repository path not found: ipfs_datasets_py/datasets/ |  |
| `repo_paths` | `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | 232 | Referenced repository path not found: ipfs_datasets_py/ipfs_embeddings_py/ |  |
| `repo_paths` | `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | 238 | Referenced repository path not found: ipfs_datasets_py/graph/ |  |
| `repo_paths` | `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | 256 | Referenced repository path not found: ipfs_datasets_py/legal/ |  |
| `repo_paths` | `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | 261 | Referenced repository path not found: ipfs_datasets_py/logic_integration/ |  |
| `repo_paths` | `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | 266 | Referenced repository path not found: ipfs_datasets_py/web_archive/ |  |
| `repo_paths` | `docs/CORE_OPERATIONS_GUIDE.md` | 428 | Referenced repository path not found: ipfs_datasets_py/core_operations/new_module.py |  |
| `repo_paths` | `docs/CORE_OPERATIONS_GUIDE.md` | 515 | Referenced repository path not found: tests/unit/core_operations/test_new_module.py |  |
| `repo_paths` | `docs/CORE_OPERATIONS_GUIDE.md` | 517 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/category/tool_name.py |  |
| `repo_paths` | `docs/CROSS_CUTTING_INTEGRATION_GUIDE.md` | 227 | Referenced repository path not found: infrastructure/caching.py |  |
| `repo_paths` | `docs/CROSS_CUTTING_INTEGRATION_GUIDE.md` | 628 | Referenced repository path not found: docs/PHASE_9_10_PROGRESS_REPORT.md |  |
| `repo_paths` | `docs/DOMAIN_AWARE_CONFIG.md` | 205 | Referenced repository path not found: tests/unit_tests/optimizers/graphrag/test_domain_aware_config.py |  |
| `repo_paths` | `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | 472 | Referenced repository path not found: processors/graphrag/ |  |
| `repo_paths` | `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | 574 | Referenced repository path not found: docs/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md |  |
| `repo_paths` | `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | 575 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md |  |
| `repo_paths` | `docs/HOTPATH_PERFORMANCE_ANALYSIS.md` | 171 | Referenced repository path not found: common/profiling.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | 689 | Referenced repository path not found: monitoring/grafana-dashboard.json |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 159 | Referenced repository path not found: docs/SHARDING_ARCHITECTURE.md |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 300 | Referenced repository path not found: bridges/faiss_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 313 | Referenced repository path not found: bridges/qdrant_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 326 | Referenced repository path not found: bridges/elasticsearch_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 338 | Referenced repository path not found: benchmarks/bridge_performance.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 384 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/vector_store_tools.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 463 | Referenced repository path not found: vector_stores/monitoring.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 476 | Referenced repository path not found: vector_stores/caching.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 488 | Referenced repository path not found: vector_stores/resilience.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 512 | Referenced repository path not found: vector_stores/backup.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 649 | Referenced repository path not found: examples/rag_system/ |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 650 | Referenced repository path not found: examples/semantic_search/ |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 651 | Referenced repository path not found: examples/recommendation_engine/ |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 662 | Referenced repository path not found: docs/guides/performance-tuning.md |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 673 | Referenced repository path not found: docs/troubleshooting/ |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 741 | Referenced repository path not found: tests/load/ |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_SESSION_STATUS.md` | 132 | Referenced repository path not found: sharding/__init__.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_DATABASE_SESSION_STATUS.md` | 133 | Referenced repository path not found: sharding/coordinator.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_FINAL_SUMMARY.md` | 53 | Referenced repository path not found: bridges/base_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_FINAL_SUMMARY.md` | 54 | Referenced repository path not found: bridges/__init__.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 345 | Referenced repository path not found: ipfs_datasets_py/vector_stores/bridges/faiss_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 350 | Referenced repository path not found: ipfs_datasets_py/vector_stores/bridges/qdrant_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 354 | Referenced repository path not found: ipfs_datasets_py/vector_stores/bridges/elasticsearch_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 357 | Referenced repository path not found: ipfs_datasets_py/vector_stores/bridges/ipld_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 521 | Referenced repository path not found: ipfs_datasets_py/vector_stores/router_factory.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 548 | Referenced repository path not found: tests/unit/vector_stores/test_bridges.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 553 | Referenced repository path not found: tests/unit/vector_stores/test_manager.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 560 | Referenced repository path not found: tests/integration/vector_stores/test_ipld_integration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 565 | Referenced repository path not found: tests/integration/vector_stores/test_cross_store_migration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 571 | Referenced repository path not found: tests/integration/vector_stores/test_router_integration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 578 | Referenced repository path not found: tests/performance/vector_stores/test_ipld_performance.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 590 | Referenced repository path not found: docs/vector_stores/IPLD_VECTOR_STORE_GUIDE.md |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 596 | Referenced repository path not found: docs/vector_stores/CROSS_STORE_MIGRATION_GUIDE.md |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 602 | Referenced repository path not found: docs/vector_stores/ROUTER_INTEGRATION_GUIDE.md |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 609 | Referenced repository path not found: docs/api/vector_stores.md |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 617 | Referenced repository path not found: examples/vector_stores/ipld_basic_usage.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 618 | Referenced repository path not found: examples/vector_stores/cross_store_migration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 619 | Referenced repository path not found: examples/vector_stores/router_integration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 620 | Referenced repository path not found: examples/vector_stores/car_file_exchange.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 60 | Referenced repository path not found: bridges/faiss_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 61 | Referenced repository path not found: bridges/qdrant_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 62 | Referenced repository path not found: bridges/elasticsearch_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 63 | Referenced repository path not found: bridges/ipld_bridge.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 83 | Referenced repository path not found: tests/unit/vector_stores/test_bridges.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 84 | Referenced repository path not found: tests/unit/vector_stores/test_manager.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 85 | Referenced repository path not found: tests/unit/vector_stores/test_router_integration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 88 | Referenced repository path not found: tests/integration/vector_stores/test_ipld_integration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 89 | Referenced repository path not found: tests/integration/vector_stores/test_cross_store_migration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 90 | Referenced repository path not found: tests/integration/vector_stores/test_router_integration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 94 | Referenced repository path not found: docs/vector_stores/IPLD_VECTOR_STORE_GUIDE.md |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 95 | Referenced repository path not found: docs/vector_stores/CROSS_STORE_MIGRATION_GUIDE.md |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 96 | Referenced repository path not found: docs/vector_stores/ROUTER_INTEGRATION_GUIDE.md |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 99 | Referenced repository path not found: examples/vector_stores/ipld_basic_usage.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 100 | Referenced repository path not found: examples/vector_stores/cross_store_migration.py |  |
| `repo_paths` | `docs/IPLD_VECTOR_STORE_QUICKSTART.md` | 101 | Referenced repository path not found: examples/vector_stores/router_integration.py |  |
| `repo_paths` | `docs/LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md` | 140 | Referenced repository path not found: state_scrapers/base_scraper.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 4 | Referenced repository path not found: ipfs_datasets_py/ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus_module |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 7 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 29 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/server.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 30 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/__main__.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 33 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/hierarchical_tool_manager.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 35 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/tool_registry.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 38 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/p2p_service_manager.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 39 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/p2p_mcp_registry_adapter.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 40 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/trio_bridge.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 46 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/configs.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 47 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/logger.py |  |
| `repo_paths` | `docs/MCPPLUSPLUS_INTEGRATION_INFINITE_TODO.md` | 48 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/monitoring.py |  |
| `repo_paths` | `docs/MCP_REFACTORING_PLAN.md` | 207 | Referenced repository path not found: ipfs_datasets_py/datasets/ |  |
| `repo_paths` | `docs/MCP_REFACTORING_PLAN.md` | 211 | Referenced repository path not found: ipfs_datasets_py/ipfs/ |  |
| `repo_paths` | `docs/MCP_REFACTORING_PLAN.md` | 223 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tool_manager.py |  |
| `repo_paths` | `docs/MCP_REFACTORING_PLAN.md` | 228 | Referenced repository path not found: tools/dataset_tools/category.json |  |
| `repo_paths` | `docs/MCP_REFACTORING_PLAN.md` | 286 | Referenced repository path not found: graph_tools/create_transaction.py |  |
| `repo_paths` | `docs/MCP_REFACTORING_PLAN.md` | 287 | Referenced repository path not found: graph_tools/create_index.py |  |
| `repo_paths` | `docs/MCP_REFACTORING_PLAN.md` | 288 | Referenced repository path not found: graph_tools/add_constraint.py |  |
| `repo_paths` | `docs/MCP_REFACTORING_SUMMARY.md` | 255 | Referenced repository path not found: ipfs_datasets_py/datasets/loader.py |  |
| `repo_paths` | `docs/MCP_REFACTORING_SUMMARY.md` | 256 | Referenced repository path not found: ipfs_datasets_py/datasets/saver.py |  |
| `repo_paths` | `docs/MCP_REFACTORING_SUMMARY.md` | 257 | Referenced repository path not found: ipfs_datasets_py/datasets/converter.py |  |
| `repo_paths` | `docs/MCP_REFACTORING_SUMMARY.md` | 258 | Referenced repository path not found: ipfs_datasets_py/ipfs/pin.py |  |
| `repo_paths` | `docs/MCP_REFACTORING_SUMMARY.md` | 259 | Referenced repository path not found: ipfs_datasets_py/ipfs/get.py |  |
| `repo_paths` | `docs/PHASE3C6_COMPLETION_REPORT.md` | 51 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/contracts/GrothVerifier.sol |  |
| `repo_paths` | `docs/PHASE3C_COMPLETION_FULL.md` | 459 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/target/release/groth16 |  |
| `repo_paths` | `docs/PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md` | 104 | Referenced repository path not found: ipfs_datasets_py/logic_integration/ |  |
| `repo_paths` | `docs/PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md` | 273 | Referenced repository path not found: ipfs_datasets_py/p2p/ |  |
| `repo_paths` | `docs/PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md` | 309 | Referenced repository path not found: p2p/taskqueue.py |  |
| `repo_paths` | `docs/PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md` | 310 | Referenced repository path not found: p2p/peer_manager.py |  |
| `repo_paths` | `docs/PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md` | 311 | Referenced repository path not found: ml/huggingface.py |  |
| `repo_paths` | `docs/PHASE_2_ARCHITECTURE_VALIDATION_SUMMARY.md` | 487 | Referenced repository path not found: ipfs_datasets_py/p2p/taskqueue.py |  |
| `repo_paths` | `docs/PHASE_7_8_COMPLETE.md` | 13 | Referenced repository path not found: tests/unit/core_operations/test_knowledge_graph_manager.py |  |
| `repo_paths` | `docs/SENTENCE_WINDOW_BENCHMARK_REPORT.md` | 180 | Referenced repository path not found: benchmarks/bench_sentence_window_scaling.py::TestSentenceWindowScaling |  |
| `repo_paths` | `docs/TESTING_STRATEGY.md` | 30 | Referenced repository path not found: tests/unit/multimedia/ |  |
| `repo_paths` | `docs/TEST_COVERAGE_SUMMARY.md` | 6 | Referenced repository path not found: ipfs_datasets_py/optimizers/tests/unit/agentic/test_cli_argparse_smoke.py |  |
| `repo_paths` | `docs/TEST_COVERAGE_SUMMARY.md` | 16 | Referenced repository path not found: ipfs_datasets_py/optimizers/tests/unit/graphrag/test_ontology_refinement_agent.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 25 | Referenced repository path not found: ipfs_datasets_py/docs/WEB_ARCHIVING_PROVIDER_MATRIX.md |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 26 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/__init__.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 37 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/metrics/baseline_harness.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 38 | Referenced repository path not found: ipfs_datasets_py/tests/integration_tests/web_archiving/test_baseline_harness.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 49 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/contracts.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 50 | Referenced repository path not found: ipfs_datasets_py/tests/unit_tests/web_archive/test_unified_contracts.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 61 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/base.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 62 | Referenced repository path not found: ipfs_datasets_py/tests/unit_tests/web_archive/test_provider_protocols.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 75 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/metrics/registry.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 76 | Referenced repository path not found: ipfs_datasets_py/tests/unit_tests/web_archive/test_metrics_registry.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 87 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/scoring.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 88 | Referenced repository path not found: ipfs_datasets_py/tests/unit_tests/web_archive/test_scoring.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 99 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/resilience.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 100 | Referenced repository path not found: ipfs_datasets_py/tests/unit_tests/web_archive/test_resilience.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 111 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/planner.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 112 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/executor.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 113 | Referenced repository path not found: ipfs_datasets_py/tests/unit_tests/web_archive/test_planner_executor.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 127 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_api.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 129 | Referenced repository path not found: ipfs_datasets_py/tests/unit_tests/web_archive/test_unified_api.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 138 | Referenced repository path not found: search_engines/orchestrator.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 140 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/search_engines/orchestrator.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 141 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/search/multi_engine_provider.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 152 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_web_scraper.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 153 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/fetch/unified_scraper_provider.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 164 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/unified_api_tools.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 165 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/__init__.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 166 | Referenced repository path not found: ipfs_datasets_py/tests/unit_tests/web_archive/test_mcp_unified_api_tools.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 179 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/compat/legacy_wrappers.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 203 | Referenced repository path not found: ipfs_datasets_py/docs/WEB_ARCHIVING_MIGRATION_GUIDE.md |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 204 | Referenced repository path not found: ipfs_datasets_py/README.md |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 217 | Referenced repository path not found: ipfs_datasets_py/tests/integration_tests/web_archiving/test_failure_injection.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_EXECUTION_TICKETS.md` | 240 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/metrics/telemetry.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 20 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_web_scraper.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 21 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/search_engines/base.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 22 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/search_engines/orchestrator.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 23 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/common_crawl_integration.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 24 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/__init__.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 46 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/unified_api.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 76 | Referenced repository path not found: .../web_archiving/orchestration/policy.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 77 | Referenced repository path not found: .../web_archiving/orchestration/planner.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 78 | Referenced repository path not found: .../web_archiving/orchestration/executor.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 79 | Referenced repository path not found: .../web_archiving/orchestration/scoring.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 190 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/contracts.py |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 191 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/search/ |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 192 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/providers/fetch/ |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 193 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/orchestration/ |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 194 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/metrics/ |  |
| `repo_paths` | `docs/WEB_ARCHIVING_UNIFIED_API_REFACTOR_PLAN.md` | 195 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/web_archiving/compat/ |  |
| `repo_paths` | `docs/WORK_SUMMARY_2026_02_23.md` | 6 | Referenced repository path not found: ipfs_datasets_py/optimizers/tests/unit/agentic/test_cli_argparse_smoke.py |  |
| `repo_paths` | `docs/WORK_SUMMARY_2026_02_23.md` | 16 | Referenced repository path not found: ipfs_datasets_py/optimizers/tests/unit/graphrag/test_ontology_refinement_agent.py |  |
| `repo_paths` | `docs/WORK_SUMMARY_2026_02_23.md` | 45 | Referenced repository path not found: ipfs_datasets_py/optimizers/TODO.md |  |
| `repo_paths` | `docs/WORK_SUMMARY_2026_02_23.md` | 64 | Referenced repository path not found: ipfs_datasets_py/optimizers/tests/unit/agentic/__init__.py |  |
| `repo_paths` | `docs/WORK_SUMMARY_2026_02_23.md` | 66 | Referenced repository path not found: ipfs_datasets_py/optimizers/tests/unit/graphrag/__init__.py |  |
| `repo_paths` | `docs/analysis/code_overlap_analysis_for_audit_folder.md` | 93 | Referenced repository path not found: /ipfs_datasets_py/data_provenance.py |  |
| `repo_paths` | `docs/analysis/code_overlap_analysis_for_audit_folder.md` | 94 | Referenced repository path not found: /ipfs_datasets_py/data_provenance_enhanced.py |  |
| `repo_paths` | `docs/analysis/code_overlap_analysis_for_audit_folder.md` | 95 | Referenced repository path not found: /ipfs_datasets_py/provenance_dashboard.py |  |
| `repo_paths` | `docs/analysis/code_overlap_analysis_for_audit_folder.md` | 262 | Referenced repository path not found: /ipfs_datasets_py/admin_dashboard.py |  |
| `repo_paths` | `docs/analysis/code_overlap_analysis_for_audit_folder.md` | 263 | Referenced repository path not found: /ipfs_datasets_py/unified_monitoring_dashboard.py |  |
| `repo_paths` | `docs/analysis/code_overlap_analysis_for_audit_folder.md` | 267 | Referenced repository path not found: /ipfs_datasets_py/enhanced_rag_visualization.py |  |
| `repo_paths` | `docs/analysis/code_overlap_analysis_for_audit_folder.md` | 331 | Referenced repository path not found: /ipfs_datasets_py/cross_document_lineage.py |  |
| `repo_paths` | `docs/analysis/code_overlap_analysis_for_audit_folder.md` | 332 | Referenced repository path not found: /ipfs_datasets_py/cross_document_lineage_enhanced.py |  |
| `repo_paths` | `docs/analysis/code_overlap_analysis_for_audit_folder.md` | 375 | Referenced repository path not found: /ipfs_datasets_py/audit/examples.py |  |
| `repo_paths` | `docs/analysis/complete_integration_summary.md` | 118 | Referenced repository path not found: backends/ipfs_backend.py |  |
| `repo_paths` | `docs/analysis/config_folder_audit_report.md` | 109 | Referenced repository path not found: ./config.toml |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 35 | Referenced repository path not found: docs/misc_markdown/COMPREHENSIVE_MCP_DASHBOARD.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 38 | Referenced repository path not found: docs/P2P_CACHE_SYSTEM.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 44 | Referenced repository path not found: docs/DISCORD_ALERTS_GUIDE.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 48 | Referenced repository path not found: docs/ROOT_REORGANIZATION.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 51 | Referenced repository path not found: docs/comprehensive_web_scraping_guide.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 64 | Referenced repository path not found: docs/GITHUB_ACTIONS_INFRASTRUCTURE.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 67 | Referenced repository path not found: docs/distributed_features.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 70 | Referenced repository path not found: docs/performance_optimization.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 73 | Referenced repository path not found: docs/misc_markdown/CLI_README.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 76 | Referenced repository path not found: docs/misc_markdown/CLI_TESTING_REPORT.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 79 | Referenced repository path not found: docs/misc_markdown/DISCORD_INTEGRATION_SUMMARY.md |  |
| `repo_paths` | `docs/analysis/individual_file_scan_complete.md` | 82 | Referenced repository path not found: docs/misc_markdown/DEPENDENCY_TOOLS_README.md |  |
| `repo_paths` | `docs/analysis/logic_tools_verification.md` | 37 | Referenced repository path not found: tests/unit/test_logic_mcp_tools.py |  |
| `repo_paths` | `docs/analysis/logic_tools_verification.md` | 38 | Referenced repository path not found: tests/unit/test_logic_tools_discoverability.py |  |
| `repo_paths` | `docs/analysis/logic_tools_verification.md` | 39 | Referenced repository path not found: tests/integration/test_logic_tools_integration.py |  |
| `repo_paths` | `docs/analysis/readme_diagnostics.md` | 276 | Referenced repository path not found: docs/SCRAPER_DOCUMENTATION.md |  |
| `repo_paths` | `docs/analysis/readme_diagnostics.md` | 277 | Referenced repository path not found: docs/README_DIAGNOSTICS.md |  |
| `repo_paths` | `docs/api/GENERATION_AND_FRESHNESS.md` | 65 | Referenced repository path not found: tests/unit/... |  |
| `repo_paths` | `docs/api/domains/MCP_AND_RUNTIME.md` | 9 | Referenced repository path not found: tools/tool_wrapper.py |  |
| `repo_paths` | `docs/architecture/ARCHITECTURE_GUIDE_TEMPLATE.md` | 111 | Referenced repository path not found: ipfs_datasets_py/... |  |
| `repo_paths` | `docs/architecture/DOMAIN_MAP.md` | 146 | Referenced repository path not found: docs/adr/ |  |
| `repo_paths` | `docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md` | 88 | Referenced repository path not found: logic/legal_ir_compiler_api.py |  |
| `repo_paths` | `docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md` | 89 | Referenced repository path not found: logic/legal_ir_pass_manager.py |  |
| `repo_paths` | `docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md` | 90 | Referenced repository path not found: logic/legal_ir_schema_evolution.py |  |
| `repo_paths` | `docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md` | 92 | Referenced repository path not found: logic/legal_ir_proof_carrying_artifacts.py |  |
| `repo_paths` | `docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md` | 125 | Referenced repository path not found: ir/cid.py |  |
| `repo_paths` | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | 201 | Referenced repository path not found: ipfs_datasets_py/legal_datasets/ |  |
| `repo_paths` | `docs/architecture/RUNTIME_ENTRYPOINTS.md` | 28 | Referenced repository path not found: egg-info/entry_points.txt |  |
| `repo_paths` | `docs/architecture/decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md` | 309 | Referenced repository path not found: docs/architecture/decisions/ADR-001 |  |
| `repo_paths` | `docs/architecture/decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md` | 288 | Referenced repository path not found: docs/architecture/decisions/ADR-002 |  |
| `repo_paths` | `docs/architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md` | 40 | Referenced repository path not found: …/ADR-003-hierarchical-tool-system.md |  |
| `repo_paths` | `docs/architecture/decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md` | 41 | Referenced repository path not found: …/ADR-004-engine-extraction-pattern.md |  |
| `repo_paths` | `docs/architecture/decisions/ADR-006-PROCESSOR-LAYERING.md` | 35 | Referenced repository path not found: core/protocol.py |  |
| `repo_paths` | `docs/architecture/decisions/ADR-006-PROCESSOR-LAYERING.md` | 36 | Referenced repository path not found: core/registry.py |  |
| `repo_paths` | `docs/architecture/decisions/ADR-006-PROCESSOR-LAYERING.md` | 36 | Referenced repository path not found: core/processor_registry.py |  |
| `repo_paths` | `docs/architecture/decisions/ADR-006-PROCESSOR-LAYERING.md` | 37 | Referenced repository path not found: core/universal_processor.py |  |
| `repo_paths` | `docs/architecture/decisions/ADR-006-PROCESSOR-LAYERING.md` | 38 | Referenced repository path not found: core/input_detector.py |  |
| `repo_paths` | `docs/architecture/decisions/ADR-006-PROCESSOR-LAYERING.md` | 39 | Referenced repository path not found: core/__init__.py |  |
| `repo_paths` | `docs/architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md` | 206 | Referenced repository path not found: mcp_server/tools/<category>/ |  |
| `repo_paths` | `docs/architecture/decisions/README.md` | 106 | Referenced repository path not found: …/ADR-002-dual-runtime.md |  |
| `repo_paths` | `docs/architecture/decisions/README.md` | 107 | Referenced repository path not found: …/ADR-003-hierarchical-tool-system.md |  |
| `repo_paths` | `docs/architecture/decisions/README.md` | 108 | Referenced repository path not found: …/ADR-004-engine-extraction-pattern.md |  |
| `repo_paths` | `docs/architecture/decisions/README.md` | 109 | Referenced repository path not found: …/ADR-005-v6-coverage-hardening.md |  |
| `repo_paths` | `docs/architecture/decisions/README.md` | 110 | Referenced repository path not found: …/ADR-006-mcp++-alignment.md |  |
| `repo_paths` | `docs/architecture/decisions/README.md` | 148 | Referenced repository path not found: docs/architecture/decisions/ADR-NNN-short-kebab-title.md |  |
| `repo_paths` | `docs/architecture/github_actions_infrastructure.md` | 105 | Referenced repository path not found: ipfs_datasets_py/codeql_cache.py |  |
| `repo_paths` | `docs/architecture/github_actions_infrastructure.md` | 141 | Referenced repository path not found: ipfs_datasets_py/credential_manager.py |  |
| `repo_paths` | `docs/architecture/github_actions_infrastructure.md` | 174 | Referenced repository path not found: ipfs_datasets_py/cache.py |  |
| `repo_paths` | `docs/architecture/github_actions_infrastructure.md` | 255 | Referenced repository path not found: .github/cache-config.yml |  |
| `repo_paths` | `docs/architecture/github_actions_infrastructure.md` | 278 | Referenced repository path not found: .github/p2p-config.yml |  |
| `repo_paths` | `docs/architecture/github_actions_infrastructure.md` | 310 | Referenced repository path not found: .github/workflows/example-cached-workflow.yml |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 152 | Referenced repository path not found: extraction/entities.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 153 | Referenced repository path not found: extraction/graph.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 154 | Referenced repository path not found: extraction/extractor.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 155 | Referenced repository path not found: extraction/validator.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 156 | Referenced repository path not found: extraction/provenance.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 157 | Referenced repository path not found: extraction/advanced.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 158 | Referenced repository path not found: core/graph_engine.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 159 | Referenced repository path not found: core/query_executor.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 160 | Referenced repository path not found: core/types.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 161 | Referenced repository path not found: storage/ipld_backend.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 162 | Referenced repository path not found: storage/types.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 163 | Referenced repository path not found: transactions/manager.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 164 | Referenced repository path not found: indexing/manager.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 170 | Referenced repository path not found: ontology/reasoning.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 344 | Referenced repository path not found: extraction/relationships.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 347 | Referenced repository path not found: neo4j_compat/types.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 349 | Referenced repository path not found: lineage/types.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 361 | Referenced repository path not found: jsonld/validation.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 363 | Referenced repository path not found: migration/schema_checker.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 401 | Referenced repository path not found: lineage/core.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 415 | Referenced repository path not found: query/unified_engine.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 416 | Referenced repository path not found: query/hybrid_search.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 417 | Referenced repository path not found: query/semantic_traversal.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 418 | Referenced repository path not found: query/sparql_templates.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 419 | Referenced repository path not found: jsonld/translator.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 420 | Referenced repository path not found: query/graphql.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 435 | Referenced repository path not found: reasoning/helpers.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 606 | Referenced repository path not found: indexing/specialized.py |  |
| `repo_paths` | `docs/architecture/knowledge/KNOWLEDGE_GRAPH_LIFECYCLE.md` | 609 | Referenced repository path not found: core/ir_executor.py |  |
| `repo_paths` | `docs/architecture/knowledge/OPTIMIZATION_LOOPS.md` | 115 | Referenced repository path not found: common/base_optimizer.py |  |
| `repo_paths` | `docs/architecture/knowledge/OPTIMIZATION_LOOPS.md` | 119 | Referenced repository path not found: common/optimizer_result.py |  |
| `repo_paths` | `docs/architecture/knowledge/OPTIMIZATION_LOOPS.md` | 120 | Referenced repository path not found: common/lifecycle_hooks.py |  |
| `repo_paths` | `docs/architecture/knowledge/OPTIMIZATION_LOOPS.md` | 122 | Referenced repository path not found: common/base_critic.py |  |
| `repo_paths` | `docs/architecture/knowledge/README.md` | 159 | Referenced repository path not found: storage/ipld_backend.py |  |
| `repo_paths` | `docs/architecture/logic_intent_legal_gate.todo.md` | 43 | Referenced repository path not found: security_ir/formalization_adapter.py |  |
| `repo_paths` | `docs/architecture/logic_intent_legal_gate.todo.md` | 44 | Referenced repository path not found: intent_ir/source_adapters/skillcenter.py |  |
| `repo_paths` | `docs/architecture/logic_intent_legal_gate.todo.md` | 118 | Referenced repository path not found: formalization/compiler.py |  |
| `repo_paths` | `docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md` | 552 | Referenced repository path not found: mcplusplus/peer_registry.py |  |
| `repo_paths` | `docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md` | 554 | Referenced repository path not found: ipfs_datasets_py/profile_g |  |
| `repo_paths` | `docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md` | 561 | Referenced repository path not found: mcp_server/tools/<category>/ |  |
| `repo_paths` | `docs/architecture/mcp/README.md` | 219 | Referenced repository path not found: tools/validators.py |  |
| `repo_paths` | `docs/architecture/mcp/SERVER_AND_DISPATCH.md` | 9 | Referenced repository path not found: mcplusplus/result_cache.py |  |
| `repo_paths` | `docs/architecture/mcp/SERVER_AND_DISPATCH.md` | 230 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/<category_name>/ |  |
| `repo_paths` | `docs/architecture/mcp/SERVER_AND_DISPATCH.md` | 385 | Referenced repository path not found: tools/validators.py |  |
| `repo_paths` | `docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md` | 9 | Referenced repository path not found: tools/tool_wrapper.py |  |
| `repo_paths` | `docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md` | 9 | Referenced repository path not found: tools/tool_registration.py |  |
| `repo_paths` | `docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md` | 9 | Referenced repository path not found: tools/validators.py |  |
| `repo_paths` | `docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md` | 109 | Referenced repository path not found: tools/__init__.py |  |
| `repo_paths` | `docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md` | 393 | Referenced repository path not found: tools/<category>/<tool_name>.py |  |
| `repo_paths` | `docs/architecture/mcp_tools_technical_reference.md` | 86 | Referenced repository path not found: "./data/file.csv" |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 97 | Referenced repository path not found: file_converter/converter.py |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 121 | Referenced repository path not found: specialized/pdf/pdf_processor.py |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 122 | Referenced repository path not found: specialized/pdf/ocr_engine.py |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 149 | Referenced repository path not found: multimedia/ffmpeg_wrapper.py |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 150 | Referenced repository path not found: multimedia/ytdlp_wrapper.py |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 151 | Referenced repository path not found: multimedia/media_processor.py |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 153 | Referenced repository path not found: specialized/media/advanced_processing.py |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 165 | Referenced repository path not found: adapters/pdf_adapter.py |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 166 | Referenced repository path not found: adapters/file_converter_adapter.py |  |
| `repo_paths` | `docs/architecture/processing/FILE_AND_MULTIMEDIA.md` | 167 | Referenced repository path not found: adapters/multimedia_adapter.py |  |
| `repo_paths` | `docs/architecture/processing/PROCESSOR_PIPELINE.md` | 198 | Referenced repository path not found: core/registry.py |  |
| `repo_paths` | `docs/architecture/processing/PROCESSOR_PIPELINE.md` | 199 | Referenced repository path not found: core/processor_registry.py |  |
| `repo_paths` | `docs/architecture/processing/PROCESSOR_PIPELINE.md` | 200 | Referenced repository path not found: core/__init__.py |  |
| `repo_paths` | `docs/architecture/processing/PROCESSOR_PIPELINE.md` | 247 | Referenced repository path not found: adapters/auto_register.py |  |
| `repo_paths` | `docs/architecture/processing/PROCESSOR_PIPELINE.md` | 531 | Referenced repository path not found: core/protocol.py |  |
| `repo_paths` | `docs/architecture/processing/PROCESSOR_PIPELINE.md` | 602 | Referenced repository path not found: processing/README.md |  |
| `repo_paths` | `docs/architecture/processing/README.md` | 117 | Referenced repository path not found: core/protocol.py |  |
| `repo_paths` | `docs/architecture/processing/README.md` | 117 | Referenced repository path not found: core/processor_registry.py |  |
| `repo_paths` | `docs/architecture/processing/README.md` | 129 | Referenced repository path not found: processors/<domain>/ |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 149 | Referenced repository path not found: legal_scrapers/recap_archive_scraper.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 150 | Referenced repository path not found: legal_scrapers/legal_corpus/interfaces.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 151 | Referenced repository path not found: legal_scrapers/shared_fetch_cache.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 152 | Referenced repository path not found: legal_scrapers/scraping_state.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 153 | Referenced repository path not found: legal_scrapers/ipfs_storage_integration.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 154 | Referenced repository path not found: legal_scrapers/legal_graphrag.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 155 | Referenced repository path not found: legal_scrapers/legal_dataset_api.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 156 | Referenced repository path not found: legal_data/courtlistener_ingestion.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 157 | Referenced repository path not found: legal_data/docket_dataset.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 158 | Referenced repository path not found: legal_data/citation_extraction.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 163 | Referenced repository path not found: legal_data/workspace_packaging.py |  |
| `repo_paths` | `docs/architecture/processing/WEB_ARCHIVING_AND_LEGAL_INGESTION.md` | 202 | Referenced repository path not found: legal_corpus/interfaces.py |  |
| `repo_paths` | `docs/architecture/project_structure.md` | 21 | Referenced repository path not found: scripts/development/ |  |
| `repo_paths` | `docs/architecture/project_structure.md` | 23 | Referenced repository path not found: scripts/deployment/ |  |
| `repo_paths` | `docs/architecture/project_structure.md` | 24 | Referenced repository path not found: scripts/maintenance/ |  |
| `repo_paths` | `docs/architecture/project_structure.md` | 29 | Referenced repository path not found: archive/migration_tests/ |  |
| `repo_paths` | `docs/architecture/project_structure.md` | 36 | Referenced repository path not found: config/mcp_server/ |  |
| `repo_paths` | `docs/architecture/project_structure.md` | 37 | Referenced repository path not found: config/development/ |  |
| `repo_paths` | `docs/architecture/project_structure.md` | 38 | Referenced repository path not found: config/production/ |  |
| `repo_paths` | `docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md` | 339 | Referenced repository path not found: sharding/coordinator.py |  |
| `repo_paths` | `docs/architecture/retrieval/VECTOR_STORES.md` | 97 | Referenced repository path not found: ./vector_indexes |  |
| `repo_paths` | `docs/architecture/storage/IMMUTABLE_DATASET_RELEASES.md` | 375 | Referenced repository path not found: runtime/abby_voice_release_pointer.json |  |
| `repo_paths` | `docs/architecture/storage/README.md` | 287 | Referenced repository path not found: ipld/storage_stubs.md |  |
| `repo_paths` | `docs/architecture/submodule_fix.md` | 57 | Referenced repository path not found: .github/workflows/docker-build-test.yml |  |
| `repo_paths` | `docs/architecture/submodule_fix.md` | 58 | Referenced repository path not found: .github/workflows/docker-ci.yml |  |
| `repo_paths` | `docs/benchmarks/semantic_roundtrip_plateau_supervisor_launch.md` | 133 | Referenced repository path not found: $RUNTIME/bundles/index.json |  |
| `repo_paths` | `docs/configuration.md` | 24 | Referenced repository path not found: ~/.ipfs_datasets/cli.json |  |
| `repo_paths` | `docs/deployment/PYPI_PREPARATION.md` | 44 | Referenced repository path not found: docs/test_results/mcp_integration_test_results.json |  |
| `repo_paths` | `docs/deployment/PYPI_PREPARATION.md` | 56 | Referenced repository path not found: .github/copilot-instructions.md |  |
| `repo_paths` | `docs/developer_guides/CREATING_TOOLS.md` | 98 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/my_category/ |  |
| `repo_paths` | `docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md` | 85 | Referenced repository path not found: docs/architecture/decisions/ADR-NNN-....md |  |
| `repo_paths` | `docs/developer_guides/DOCUMENTATION_CONTRIBUTING.md` | 204 | Referenced repository path not found: docs/architecture/decisions/ADR-NNN-short-title.md |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 87 | Referenced repository path not found: adapters/auto_register.py |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 88 | Referenced repository path not found: core/universal_processor.py |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 97 | Referenced repository path not found: ipfs_datasets_py/processors/<domain>/… |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 98 | Referenced repository path not found: processors/adapters/<name>_adapter.py |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 102 | Referenced repository path not found: tests/unit/processors/… |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 221 | Referenced repository path not found: ipfs_datasets_py/vector_stores/<name>_store.py |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 315 | Referenced repository path not found: mcp_server/tools/<category>/ |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 327 | Referenced repository path not found: ipfs_datasets_py/<domain>/… |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 328 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/<category>/<tool_name>.py |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 329 | Referenced repository path not found: tools/<category>/__init__.py |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 438 | Referenced repository path not found: tests/unit/logic/… |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 667 | Referenced repository path not found: docs/architecture/… |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 667 | Referenced repository path not found: docs/developer_guides/… |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 667 | Referenced repository path not found: docs/guides/… |  |
| `repo_paths` | `docs/developer_guides/EXTENSION_RECIPES.md` | 755 | Referenced repository path not found: mcp_server/tools/<cat>/ |  |
| `repo_paths` | `docs/developer_guides/HANDOFF_CHECKLIST.md` | 317 | Referenced repository path not found: ipfs_datasets_py/some_module.py |  |
| `repo_paths` | `docs/developer_guides/REPOSITORY_MAP.md` | 654 | Referenced repository path not found: ipfs_datasets_py/<domain>/ |  |
| `repo_paths` | `docs/developer_guides/REPOSITORY_MAP.md` | 655 | Referenced repository path not found: mcp_server/tools/<category>/ |  |
| `repo_paths` | `docs/developer_guides/REPOSITORY_MAP.md` | 657 | Referenced repository path not found: tests/unit/<domain>/ |  |
| `repo_paths` | `docs/developer_guides/TESTING_AND_EVIDENCE.md` | 147 | Referenced repository path not found: .github/workflows/gpu-tests.yml |  |
| `repo_paths` | `docs/developer_guides/TESTING_AND_EVIDENCE.md` | 215 | Referenced repository path not found: tests/unit/<domain>/ |  |
| `repo_paths` | `docs/developer_guides/TESTING_AND_EVIDENCE.md` | 441 | Referenced repository path not found: .github/workflows/ |  |
| `repo_paths` | `docs/developer_guides/TESTING_AND_EVIDENCE.md` | 525 | Referenced repository path not found: .github/workflows/logic-benchmarks.yml |  |
| `repo_paths` | `docs/developer_guides/TESTING_AND_EVIDENCE.md` | 526 | Referenced repository path not found: .github/workflows/workflow-integration-tests.yml |  |
| `repo_paths` | `docs/developer_guides/TESTING_AND_EVIDENCE.md` | 527 | Referenced repository path not found: .github/workflows/documentation-maintenance.yml |  |
| `repo_paths` | `docs/developer_guides/TROUBLESHOOTING.md` | 265 | Referenced repository path not found: tools/tool_registration.py |  |
| `repo_paths` | `docs/developer_guides/TROUBLESHOOTING.md` | 266 | Referenced repository path not found: tools/tool_wrapper.py |  |
| `repo_paths` | `docs/examples/finance_usage_examples.md` | 306 | Referenced repository path not found: finance/__init__.py |  |
| `repo_paths` | `docs/guides/ARM64_DOCKER_SUCCESS.md` | 9 | Referenced repository path not found: ipfs_datasets_py/llm/llm_graphrag.py |  |
| `repo_paths` | `docs/guides/ATTESTED_INTENT_AUTHORIZATION.md` | 227 | Referenced repository path not found: …/service.py |  |
| `repo_paths` | `docs/guides/ATTESTED_INTENT_AUTHORIZATION.md` | 227 | Referenced repository path not found: …/receipt.py |  |
| `repo_paths` | `docs/guides/ATTESTED_INTENT_AUTHORIZATION.md` | 227 | Referenced repository path not found: …/enforcement.py |  |
| `repo_paths` | `docs/guides/ATTESTED_INTENT_AUTHORIZATION.md` | 228 | Referenced repository path not found: …/telemetry.py |  |
| `repo_paths` | `docs/guides/AUTOHEALING_ENHANCEMENTS.md` | 11 | Referenced repository path not found: .github/workflows/enhanced-autohealing.yml |  |
| `repo_paths` | `docs/guides/AUTOHEALING_ENHANCEMENTS.md` | 29 | Referenced repository path not found: .github/copilot-instructions/ |  |
| `repo_paths` | `docs/guides/AUTOHEALING_ENHANCEMENTS.md` | 41 | Referenced repository path not found: .github/workflows/scraper-validation.yml |  |
| `repo_paths` | `docs/guides/CICD_QUICK_REFERENCE.md` | 62 | Referenced repository path not found: docs/RUNNER_SETUP.md |  |
| `repo_paths` | `docs/guides/CICD_QUICK_REFERENCE.md` | 70 | Referenced repository path not found: .github/workflows/ |  |
| `repo_paths` | `docs/guides/CICD_RUNNER_SETUP_GUIDE.md` | 400 | Referenced repository path not found: docs/RUNNER_SETUP.md |  |
| `repo_paths` | `docs/guides/CICD_RUNNER_SETUP_GUIDE.md` | 431 | Referenced repository path not found: .github/workflows/ |  |
| `repo_paths` | `docs/guides/CI_CD_ANALYSIS.md` | 48 | Referenced repository path not found: docs/ipfs_embeddings_py |  |
| `repo_paths` | `docs/guides/CI_CD_ANALYSIS.md` | 49 | Referenced repository path not found: docs/ipfs_kit_py |  |
| `repo_paths` | `docs/guides/CI_CD_ANALYSIS.md` | 50 | Referenced repository path not found: docs/ipfs_kit_py-1 |  |
| `repo_paths` | `docs/guides/CI_CD_ANALYSIS.md` | 128 | Referenced repository path not found: docs/ARM64_RUNNER_SETUP.md |  |
| `repo_paths` | `docs/guides/CI_CD_ANALYSIS.md` | 201 | Referenced repository path not found: docs/GPU_RUNNER_SETUP.md |  |
| `repo_paths` | `docs/guides/COMPREHENSIVE_MCP_DASHBOARD.md` | 204 | Referenced repository path not found: rag/rag_query_dashboard.py |  |
| `repo_paths` | `docs/guides/COPILOT_AUTO_FIX_IMPLEMENTATION.md` | 46 | Referenced repository path not found: docs/copilot_auto_fix_all_prs.md |  |
| `repo_paths` | `docs/guides/COPILOT_AUTO_FIX_IMPLEMENTATION.md` | 58 | Referenced repository path not found: examples/copilot_auto_fix_example.py |  |
| `repo_paths` | `docs/guides/COPILOT_CLI_INTEGRATION.md` | 252 | Referenced repository path not found: .github/workflows/pr-copilot-reviewer.yml |  |
| `repo_paths` | `docs/guides/COPILOT_CLI_INTEGRATION.md` | 256 | Referenced repository path not found: .github/workflows/copilot-agent-autofix.yml |  |
| `repo_paths` | `docs/guides/COPILOT_INVOCATION_GUIDE.md` | 86 | Referenced repository path not found: .github/workflows/copilot-issue-assignment.yml |  |
| `repo_paths` | `docs/guides/COPILOT_TASK.md` | 28 | Referenced repository path not found: .github/workflows/pdf-processing-pipeline-ci-cd.yml\ |  |
| `repo_paths` | `docs/guides/DASHBOARD_CHANGES.md` | 22 | Referenced repository path not found: ipfs_datasets_py/mcp_dashboard.py |  |
| `repo_paths` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 35 | Referenced repository path not found: .github/workflows/docker-build-test.yml |  |
| `repo_paths` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 43 | Referenced repository path not found: .github/workflows/docker-ci.yml |  |
| `repo_paths` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 44 | Referenced repository path not found: .github/workflows/self-hosted-runner.yml |  |
| `repo_paths` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 48 | Referenced repository path not found: docs/RUNNER_SETUP.md |  |
| `repo_paths` | `docs/guides/DOCUMENTATION_UPDATE_CURRENT.md` | 81 | Referenced repository path not found: .vscode/mcp_config.json |  |
| `repo_paths` | `docs/guides/ENHANCED_AUTO_HEALING_GUIDE.md` | 38 | Referenced repository path not found: .github/workflows/comprehensive-scraper-validation.yml |  |
| `repo_paths` | `docs/guides/ENHANCED_AUTO_HEALING_GUIDE.md` | 64 | Referenced repository path not found: .github/workflows/copilot-agent-autofix.yml |  |
| `repo_paths` | `docs/guides/ENHANCED_AUTO_HEALING_GUIDE.md` | 147 | Referenced repository path not found: .github/workflows/workflow-auto-fix-config.yml |  |
| `repo_paths` | `docs/guides/ERROR_REPORTING_IMPLEMENTATION.md` | 90 | Referenced repository path not found: examples/error_reporting_example.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 11 | Referenced repository path not found: ipfs_datasets_py/mcp_dashboard.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 13 | Referenced repository path not found: logic_integration/temporal_deontic_rag_store.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 74 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/finance_data_tools/forex_scrapers.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 89 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/finance_data_tools/bond_scrapers.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 104 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/finance_data_tools/futures_scrapers.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 119 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/finance_data_tools/crypto_scrapers.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 193 | Referenced repository path not found: ipfs_datasets_py/web_archive.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 204 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/finance_data_tools/timeseries_storage.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 238 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/finance_data_tools/data_validator.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 268 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/finance_data_tools/entity_extractor.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 299 | Referenced repository path not found: ipfs_datasets_py/graphrag_integration.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 304 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/finance_data_tools/finance_knowledge_graph.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 354 | Referenced repository path not found: ipfs_datasets_py/logic_integration/finance_theorems.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 411 | Referenced repository path not found: ipfs_datasets_py/logic_integration/finance_fuzzy_logic.py |  |
| `repo_paths` | `docs/guides/FINANCE_DASHBOARD_IMPROVEMENT_PLAN.md` | 450 | Referenced repository path not found: ipfs_datasets_py/logic_integration/finance_causal_reasoning.py |  |
| `repo_paths` | `docs/guides/FINANCE_WORKFLOW_GUIDE.md` | 520 | Referenced repository path not found: finance_data_tools/README.md |  |
| `repo_paths` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 294 | Referenced repository path not found: .github/workflows/copilot-agent-autofix.yml |  |
| `repo_paths` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 295 | Referenced repository path not found: .github/workflows/issue-to-draft-pr.yml |  |
| `repo_paths` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 296 | Referenced repository path not found: .github/workflows/pr-copilot-reviewer.yml |  |
| `repo_paths` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 437 | Referenced repository path not found: .github/WORKFLOW_FIXES.md |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_COMPLETE_SUMMARY.md` | 207 | Referenced repository path not found: /test_medicine_dashboard_integration.py |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_COMPLETE_SUMMARY.md` | 208 | Referenced repository path not found: /test_medicine_syntax.py |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_COMPLETE_SUMMARY.md` | 211 | Referenced repository path not found: /ipfs_datasets_py/mcp_dashboard.py |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_SUMMARY_SCRAPE_THE_LAW_MK3.md` | 15 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/legal_dataset_mcp_tools.py |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_SUMMARY_SCRAPE_THE_LAW_MK3.md` | 90 | Referenced repository path not found: docs/MUNICIPAL_CODES_TOOL_GUIDE.md |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_SUMMARY_SCRAPE_THE_LAW_MK3.md` | 98 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/README.md |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_SUMMARY_SCRAPE_THE_LAW_MK3.md` | 202 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/scrape_the_law_mk3 |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_SUMMARY_VSCODE_CLI.md` | 54 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/vscode_cli_tools.py |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_SUMMARY_VSCODE_CLI.md` | 84 | Referenced repository path not found: development_tools/__init__.py |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_SUMMARY_VSCODE_CLI.md` | 106 | Referenced repository path not found: docs/VSCODE_CLI_INTEGRATION.md |  |
| `repo_paths` | `docs/guides/IMPLEMENTATION_SUMMARY_VSCODE_CLI.md` | 121 | Referenced repository path not found: examples/vscode_cli_example.py |  |
| `repo_paths` | `docs/guides/INTEGRATION_COMPLETE_SUMMARY.md` | 42 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/legal_dataset_mcp_tools.py |  |
| `repo_paths` | `docs/guides/INTEGRATION_COMPLETE_SUMMARY.md` | 43 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/README.md |  |
| `repo_paths` | `docs/guides/INTEGRATION_COMPLETE_SUMMARY.md` | 50 | Referenced repository path not found: docs/MUNICIPAL_CODES_TOOL_GUIDE.md |  |
| `repo_paths` | `docs/guides/INTEGRATION_COMPLETE_SUMMARY.md` | 51 | Referenced repository path not found: docs/MUNICIPAL_CODES_DASHBOARD_GUIDE.md |  |
| `repo_paths` | `docs/guides/INTEGRATION_COMPLETE_SUMMARY.md` | 52 | Referenced repository path not found: test_screenshots/dashboard_preview.html |  |
| `repo_paths` | `docs/guides/ISSUE_TO_PR_IMPLEMENTATION_SUMMARY.md` | 17 | Referenced repository path not found: .github/workflows/issue-to-draft-pr.yml |  |
| `repo_paths` | `docs/guides/ISSUE_TO_PR_IMPLEMENTATION_SUMMARY.md` | 24 | Referenced repository path not found: .github/workflows/README-issue-to-draft-pr.md |  |
| `repo_paths` | `docs/guides/ISSUE_TO_PR_IMPLEMENTATION_SUMMARY.md` | 33 | Referenced repository path not found: .github/workflows/QUICKSTART-issue-to-draft-pr.md |  |
| `repo_paths` | `docs/guides/ISSUE_TO_PR_IMPLEMENTATION_SUMMARY.md` | 42 | Referenced repository path not found: .github/workflows/README.md |  |
| `repo_paths` | `docs/guides/ISSUE_TO_PR_IMPLEMENTATION_SUMMARY.md` | 49 | Referenced repository path not found: .github/scripts/test_issue_to_pr_workflow.py |  |
| `repo_paths` | `docs/guides/JSONNET_IMPLEMENTATION.md` | 21 | Referenced repository path not found: ipfs_datasets_py/jsonnet_utils.py |  |
| `repo_paths` | `docs/guides/JSONNET_IMPLEMENTATION.md` | 38 | Referenced repository path not found: ipfs_datasets_py/dataset_serialization.py |  |
| `repo_paths` | `docs/guides/JSONNET_IMPLEMENTATION.md` | 39 | Referenced repository path not found: ipfs_datasets_py/car_conversion.py |  |
| `repo_paths` | `docs/guides/MAPS_INTEGRATION_REPORT.md` | 110 | Referenced repository path not found: ipfs_datasets_py/mcp_dashboard.py |  |
| `repo_paths` | `docs/guides/MCP_IMPLEMENTATION_SUMMARY.md` | 72 | Referenced repository path not found: docs/docker_deployment.md |  |
| `repo_paths` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 88 | Referenced repository path not found: ipfs_datasets_py/data_processing/ |  |
| `repo_paths` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 89 | Referenced repository path not found: ipfs_datasets_py/data_processing/__init__.py |  |
| `repo_paths` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 90 | Referenced repository path not found: ipfs_datasets_py/data_processing/processor.py |  |
| `repo_paths` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 109 | Referenced repository path not found: ipfs_datasets_py/storage/manager.py |  |
| `repo_paths` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 127 | Referenced repository path not found: ipfs_datasets_py/workflow_engine/ |  |
| `repo_paths` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 128 | Referenced repository path not found: ipfs_datasets_py/workflow_engine/__init__.py |  |
| `repo_paths` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 129 | Referenced repository path not found: ipfs_datasets_py/workflow_engine/engine.py |  |
| `repo_paths` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 130 | Referenced repository path not found: ipfs_datasets_py/workflow_engine/registry.py |  |
| `repo_paths` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 142 | Referenced repository path not found: ipfs_tools/get_from_ipfs.py |  |
| `repo_paths` | `docs/guides/MEDICINE_DASHBOARD_IMPROVEMENT_PLAN.md` | 44 | Referenced repository path not found: /ipfs_datasets_py/logic_integration/medical_theorem_framework.py |  |
| `repo_paths` | `docs/guides/MEDICINE_DASHBOARD_IMPROVEMENT_PLAN.md` | 101 | Referenced repository path not found: /ipfs_datasets_py/mcp_dashboard.py |  |
| `repo_paths` | `docs/guides/PATENT_FEATURE_SUMMARY.md` | 11 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/patent_scraper.py |  |
| `repo_paths` | `docs/guides/PATENT_FEATURE_SUMMARY.md` | 17 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/patent_dataset_mcp_tools.py |  |
| `repo_paths` | `docs/guides/PATENT_FEATURE_SUMMARY.md` | 28 | Referenced repository path not found: ipfs_datasets_py/patent_dashboard.py |  |
| `repo_paths` | `docs/guides/PATENT_FEATURE_SUMMARY.md` | 87 | Referenced repository path not found: docs/PATENT_SCRAPER_GUIDE.md |  |
| `repo_paths` | `docs/guides/PRE_MERGE_VALIDATION_REPORT.md` | 19 | Referenced repository path not found: tests/scraper_tests/test_caselaw_scrapers.py |  |
| `repo_paths` | `docs/guides/PRE_MERGE_VALIDATION_REPORT.md` | 20 | Referenced repository path not found: tests/scraper_tests/test_finance_scrapers.py |  |
| `repo_paths` | `docs/guides/PRE_MERGE_VALIDATION_REPORT.md` | 21 | Referenced repository path not found: tests/scraper_tests/test_medicine_scrapers.py |  |
| `repo_paths` | `docs/guides/PRE_MERGE_VALIDATION_REPORT.md` | 22 | Referenced repository path not found: tests/scraper_tests/test_software_scrapers.py |  |
| `repo_paths` | `docs/guides/PRE_MERGE_VALIDATION_REPORT.md` | 39 | Referenced repository path not found: docs/SCRAPER_TESTING_FRAMEWORK.md |  |
| `repo_paths` | `docs/guides/PR_AUTOMATION_SYSTEM.md` | 318 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/copilot_cli_tools.py |  |
| `repo_paths` | `docs/guides/PR_AUTOMATION_SYSTEM.md` | 392 | Referenced repository path not found: .github/workflows/README.md |  |
| `repo_paths` | `docs/guides/PR_AUTOMATION_SYSTEM.md` | 395 | Referenced repository path not found: .github/copilot-instructions.md |  |
| `repo_paths` | `docs/guides/PR_MONITORING_ANALYSIS_AND_RECOMMENDATIONS.md` | 260 | Referenced repository path not found: .github/workflows/enhanced-pr-completion-monitor.yml |  |
| `repo_paths` | `docs/guides/PR_SUMMARY.md` | 20 | Referenced repository path not found: .github/workflows/comprehensive-scraper-validation.yml |  |
| `repo_paths` | `docs/guides/PR_SUMMARY.md` | 35 | Referenced repository path not found: .github/workflows/copilot-agent-autofix.yml |  |
| `repo_paths` | `docs/guides/RECAP_IMPLEMENTATION_SUMMARY.md` | 25 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/legal_dataset_mcp_tools.py |  |
| `repo_paths` | `docs/guides/RECAP_IMPLEMENTATION_SUMMARY.md` | 59 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/temporal_deontic_mcp_server.py |  |
| `repo_paths` | `docs/guides/RELEASE_CHECKLIST.md` | 6 | Referenced repository path not found: docs/implementation_plans/ |  |
| `repo_paths` | `docs/guides/SCRAPER_FIX_SUMMARY.md` | 120 | Referenced repository path not found: state_scrapers/alabama.py |  |
| `repo_paths` | `docs/guides/SCRAPER_FIX_SUMMARY.md` | 121 | Referenced repository path not found: state_scrapers/delaware.py |  |
| `repo_paths` | `docs/guides/SCRAPER_FIX_SUMMARY.md` | 122 | Referenced repository path not found: state_scrapers/georgia.py |  |
| `repo_paths` | `docs/guides/SCRAPER_FIX_SUMMARY.md` | 123 | Referenced repository path not found: state_scrapers/indiana.py |  |
| `repo_paths` | `docs/guides/SCRAPER_FIX_SUMMARY.md` | 124 | Referenced repository path not found: state_scrapers/wyoming.py |  |
| `repo_paths` | `docs/guides/SCRAPER_FIX_SUMMARY.md` | 125 | Referenced repository path not found: state_scrapers/missouri.py |  |
| `repo_paths` | `docs/guides/SCRAPER_FIX_SUMMARY.md` | 126 | Referenced repository path not found: state_scrapers/tennessee.py |  |
| `repo_paths` | `docs/guides/SCRAPER_FIX_SUMMARY.md` | 127 | Referenced repository path not found: state_scrapers/__init__.py |  |
| `repo_paths` | `docs/guides/SCRAPER_TESTING_QUICKSTART.md` | 194 | Referenced repository path not found: docs/SCRAPER_TESTING_FRAMEWORK.md |  |
| `repo_paths` | `docs/guides/SETUP_COMPLETE.md` | 37 | Referenced repository path not found: .github/workflows/docker-build-test.yml |  |
| `repo_paths` | `docs/guides/SUBMODULE_FIX_SUMMARY.md` | 36 | Referenced repository path not found: .github/workflows/docker-build-test.yml |  |
| `repo_paths` | `docs/guides/SUBMODULE_FIX_SUMMARY.md` | 40 | Referenced repository path not found: .github/workflows/docker-ci.yml |  |
| `repo_paths` | `docs/guides/SUBMODULE_FIX_SUMMARY.md` | 44 | Referenced repository path not found: docs/SUBMODULE_FIX.md |  |
| `repo_paths` | `docs/guides/SUCCESS.md` | 67 | Referenced repository path not found: ipfs_accelerate_py/github_cli/cache.py |  |
| `repo_paths` | `docs/guides/SUCCESS.md` | 68 | Referenced repository path not found: ipfs_accelerate_py/github_cli/wrapper.py |  |
| `repo_paths` | `docs/guides/VALIDATION_REPORT.md` | 64 | Referenced repository path not found: docs/ipfs_embeddings_py |  |
| `repo_paths` | `docs/guides/WEB_SEARCH_IMPLEMENTATION_SUMMARY.md` | 39 | Referenced repository path not found: docs/WEB_SEARCH_API_GUIDE.md |  |
| `repo_paths` | `docs/guides/WEB_SEARCH_IMPLEMENTATION_SUMMARY.md` | 40 | Referenced repository path not found: examples/demo_search_integrations.py |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_COMPLETE_SUMMARY.md` | 21 | Referenced repository path not found: .github/scripts/generate_copilot_instruction.py |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_COMPLETE_SUMMARY.md` | 49 | Referenced repository path not found: .github/scripts/test_workflow_scripts.py |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_COMPLETE_SUMMARY.md` | 70 | Referenced repository path not found: docs/RUNNER_AUTHENTICATION_SETUP.md |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_COMPLETE_SUMMARY.md` | 72 | Referenced repository path not found: .github/workflows/README.md |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 35 | Referenced repository path not found: .github/scripts/enhance_workflow_copilot_integration.py |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 40 | Referenced repository path not found: .github/scripts/minimal_workflow_fixer.py |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 45 | Referenced repository path not found: .github/scripts/copilot_workflow_helper.py |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 50 | Referenced repository path not found: .github/scripts/workflow_fix_helper.sh |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 56 | Referenced repository path not found: .github/GITHUB_ACTIONS_FIX_GUIDE.md |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 57 | Referenced repository path not found: .github/scripts/README.md |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 58 | Referenced repository path not found: .github/workflow_health_report.json |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 59 | Referenced repository path not found: .github/workflow_fixes_applied.json |  |
| `repo_paths` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 234 | Referenced repository path not found: .github/workflows/ |  |
| `repo_paths` | `docs/guides/comprehensive_validation_guide.md` | 40 | Referenced repository path not found: .github/workflows/comprehensive-scraper-validation.yml |  |
| `repo_paths` | `docs/guides/comprehensive_validation_guide.md` | 151 | Referenced repository path not found: validation_results/comprehensive_validation_report.json |  |
| `repo_paths` | `docs/guides/comprehensive_validation_guide.md` | 152 | Referenced repository path not found: validation_results/validation_summary.txt |  |
| `repo_paths` | `docs/guides/deployment/runner_setup.md` | 217 | Referenced repository path not found: docs/DOCKER_PERMISSION_INFRASTRUCTURE_SOLUTIONS.md |  |
| `repo_paths` | `docs/guides/deployment/runner_setup.md` | 316 | Referenced repository path not found: .github/workflows/docker-build-test.yml |  |
| `repo_paths` | `docs/guides/deployment/runner_setup.md` | 317 | Referenced repository path not found: .github/workflows/self-hosted-runner.yml |  |
| `repo_paths` | `docs/guides/infrastructure/auto_healing_implementation.md` | 182 | Referenced repository path not found: .github/workflows/copilot-agent-autofix.yml |  |
| `repo_paths` | `docs/guides/infrastructure/auto_healing_implementation.md` | 195 | Referenced repository path not found: .github/scripts/analyze_workflow_failure.py |  |
| `repo_paths` | `docs/guides/infrastructure/auto_healing_implementation.md` | 258 | Referenced repository path not found: .github/scripts/generate_workflow_fix.py |  |
| `repo_paths` | `docs/guides/infrastructure/auto_healing_implementation.md` | 279 | Referenced repository path not found: .github/scripts/apply_workflow_fix.py |  |
| `repo_paths` | `docs/guides/infrastructure/auto_healing_implementation.md` | 289 | Referenced repository path not found: .github/scripts/test_autohealing_system.py |  |
| `repo_paths` | `docs/guides/infrastructure/auto_healing_implementation.md` | 310 | Referenced repository path not found: .github/workflows/workflow-auto-fix-config.yml |  |
| `repo_paths` | `docs/guides/infrastructure/automated_pr_review_guide.md` | 226 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/automated_pr_review_tools.py |  |
| `repo_paths` | `docs/guides/infrastructure/automated_pr_review_guide.md` | 254 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/github_cli_tools.py |  |
| `repo_paths` | `docs/guides/infrastructure/automated_pr_review_guide.md` | 259 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/copilot_cli_tools.py |  |
| `repo_paths` | `docs/guides/infrastructure/copilot_invocation_update.md` | 56 | Referenced repository path not found: .github/workflows/pr-copilot-monitor.yml |  |
| `repo_paths` | `docs/guides/infrastructure/copilot_queue_integration.md` | 333 | Referenced repository path not found: .github/scripts/analyze_workflow_failure.py |  |
| `repo_paths` | `docs/guides/infrastructure/copilot_queue_integration.md` | 334 | Referenced repository path not found: .github/scripts/generate_workflow_fix.py |  |
| `repo_paths` | `docs/guides/infrastructure/copilot_queue_integration.md` | 335 | Referenced repository path not found: .github/workflows/copilot-agent-autofix.yml |  |
| `repo_paths` | `docs/guides/infrastructure/copilot_queue_integration.md` | 336 | Referenced repository path not found: .github/workflows/comprehensive-scraper-validation.yml |  |
| `repo_paths` | `docs/guides/infrastructure/copilot_queue_integration.md` | 337 | Referenced repository path not found: .github/workflows/issue-to-draft-pr.yml |  |
| `repo_paths` | `docs/guides/infrastructure/pr_copilot_throttling.md` | 23 | Referenced repository path not found: .github/workflows/pr-copilot-monitor.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/RUNNER_AND_DASHBOARD_VALIDATION.md` | 143 | Referenced repository path not found: .github/workflows/gpu-tests.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/RUNNER_AND_DASHBOARD_VALIDATION.md` | 152 | Referenced repository path not found: .github/workflows/docker-build-test.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_COMPLETE.md` | 27 | Referenced repository path not found: .github/workflows/runner-validation-clean.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_COMPLETE.md` | 34 | Referenced repository path not found: .github/workflows/arm64-runner.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_COMPLETE.md` | 39 | Referenced repository path not found: .github/workflows/mcp-dashboard-tests.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_COMPLETE.md` | 44 | Referenced repository path not found: .github/workflows/mcp-integration-tests.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_COMPLETE.md` | 104 | Referenced repository path not found: ./manage-runners.sh |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_COMPLETE.md` | 139 | Referenced repository path not found: docs/ARM64_RUNNER_SETUP.md |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_SETUP.md` | 103 | Referenced repository path not found: .github/workflows/self-hosted-runner.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_SETUP.md` | 108 | Referenced repository path not found: .github/workflows/gpu-tests.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_SETUP.md` | 111 | Referenced repository path not found: .github/workflows/arm64-runner.yml |  |
| `repo_paths` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_SETUP.md` | 191 | Referenced repository path not found: .github/workflows/ |  |
| `repo_paths` | `docs/guides/infrastructure/vscode_cli_integration.md` | 453 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/vscode_cli_tools.py |  |
| `repo_paths` | `docs/guides/installation/CAPABILITY_INSTALLATION.md` | 392 | Referenced repository path not found: ~/.ipfs_datasets/cli.json |  |
| `repo_paths` | `docs/guides/installation/CONFIGURATION_REFERENCE.md` | 30 | Referenced repository path not found: ~/.ipfs_datasets/cli.json |  |
| `repo_paths` | `docs/guides/knowledge_graph_large_block_fix.md` | 96 | Referenced repository path not found: ipfs_datasets_py/ipld/knowledge_graph.py |  |
| `repo_paths` | `docs/guides/knowledge_graph_large_block_fix.md` | 97 | Referenced repository path not found: ipfs_datasets_py/ipld/README.md |  |
| `repo_paths` | `docs/guides/knowledge_graph_large_block_fix.md` | 98 | Referenced repository path not found: ipfs_datasets_py/ipld/CHANGELOG.md |  |
| `repo_paths` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_NEXT_STEPS.md` | 157 | Referenced repository path not found: processors/graphrag/ |  |
| `repo_paths` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_REFACTOR_BACKLOG.md` | 8 | Referenced repository path not found: core/expression_evaluator.py |  |
| `repo_paths` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_REFACTOR_BACKLOG.md` | 9 | Referenced repository path not found: core/ir_executor.py |  |
| `repo_paths` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_REFACTOR_BACKLOG.md` | 29 | Referenced repository path not found: core/query_executor.py |  |
| `repo_paths` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_REFACTOR_BACKLOG.md` | 44 | Referenced repository path not found: storage/ipld_backend.py |  |
| `repo_paths` | `docs/guides/legal_data/DOCKET_SOURCE_TEMPLATE_GUIDE.md` | 55 | Referenced repository path not found: juriscraper/pacer/docket_report.py |  |
| `repo_paths` | `docs/guides/legal_data/DOCKET_SOURCE_TEMPLATE_GUIDE.md` | 56 | Referenced repository path not found: tests/local/test_DocketParseTest.py |  |
| `repo_paths` | `docs/guides/legal_data/DOCKET_SOURCE_TEMPLATE_GUIDE.md` | 57 | Referenced repository path not found: tests/local/PacerParseTestCase.py |  |
| `repo_paths` | `docs/guides/legal_data/DOCKET_SOURCE_TEMPLATE_GUIDE.md` | 71 | Referenced repository path not found: juriscraper/pacer/acms_docket.py |  |
| `repo_paths` | `docs/guides/legal_data/DOCKET_SOURCE_TEMPLATE_GUIDE.md` | 72 | Referenced repository path not found: tests/local/test_PacerParseACMSDocketTest.py |  |
| `repo_paths` | `docs/guides/legal_data/DOCKET_SOURCE_TEMPLATE_GUIDE.md` | 114 | Referenced repository path not found: cl/recap/factories.py |  |
| `repo_paths` | `docs/guides/legal_data/DOCKET_SOURCE_TEMPLATE_GUIDE.md` | 115 | Referenced repository path not found: cl/recap/mergers.py |  |
| `repo_paths` | `docs/guides/legal_data/DOCKET_SOURCE_TEMPLATE_GUIDE.md` | 116 | Referenced repository path not found: cl/recap/tasks.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 14 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_v2_blueprint.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 15 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/v2_cli.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 16 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/__init__.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 57 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/serialization.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 58 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_COMPREHENSIVE_IMPROVEMENT_PLAN.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 83 | Referenced repository path not found: ipfs_datasets_py/tests/reasoner/fixtures/cnl_parse_replay_corpus.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 107 | Referenced repository path not found: ipfs_datasets_py/tests/reasoner/fixtures/dcec_conformance_cases.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 108 | Referenced repository path not found: ipfs_datasets_py/tests/reasoner/fixtures/tdfol_conformance_cases.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 133 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/optimizer_policy.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 134 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/kg_enrichment.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 158 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/prover_backends.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 160 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/models.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 187 | Referenced repository path not found: ipfs_datasets_py/tests/reasoner/test_hybrid_v2_cli.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 210 | Referenced repository path not found: ipfs_datasets_py/.vscode/tasks.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 211 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 212 | Referenced repository path not found: ipfs_datasets_py/.github/workflows/ |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md` | 283 | Referenced repository path not found: .github/workflows/legal-v2-reasoner-ci.yml |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_IR_SPEC.md` | 29 | Referenced repository path not found: src/municipal_scrape_workspace/hybrid_legal_ir.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md` | 6 | Referenced repository path not found: src/municipal_scrape_workspace/cli.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md` | 7 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/engine.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md` | 8 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/models.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md` | 9 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/serialization.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_IMPROVEMENT_PLAN.md` | 686 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_IMPROVEMENT_PLAN.md` | 699 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/ |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 6 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_shadow_mode.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 7 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_mode.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 8 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_ga_gate.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 9 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_optimizer_benchmark.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 10 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_certificate_audit.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 11 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_canary_proof_audit_smoke.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 12 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_regression_proof_audit_smoke.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 13 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_formal_logic_proof_audit_integration_smoke.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 14 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_proof_audit_integration_summary.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 15 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/build_shadow_mode_audit.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 16 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/select_formal_logic_canary_mode.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 17 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_ga_gate.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 18 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/assess_formal_logic_optimizer_benchmark.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 19 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/export_proof_certificates_audit.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 20 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 21 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_hybrid_v2_pipeline.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 98 | Referenced repository path not found: .github/workflows/legal-v2-reasoner-ci.yml |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 140 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/shadow_mode_audit.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 156 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/canary_mode_decision.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 172 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ga_gate_assessment.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 188 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/optimizer_onoff_benchmark.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 204 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/proof_certificate_audit.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 372 | Referenced repository path not found: ipfs_datasets_py/.vscode/tasks.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 375 | Referenced repository path not found: scripts/ops/run_formal_logic_canary_proof_audit_smoke.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 379 | Referenced repository path not found: scripts/ops/run_formal_logic_regression_proof_audit_smoke.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 383 | Referenced repository path not found: scripts/ops/run_formal_logic_proof_audit_integration_smoke.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 399 | Referenced repository path not found: scripts/ops/run_formal_logic_proof_audit_integration_matrix_smoke.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 636 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/templates/HYBRID_LEGAL_WS11_ISSUE_BODIES_01_06.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 637 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/templates/HYBRID_LEGAL_WS11_ISSUE_BODIES_07_12.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 124 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/CI_SOAK_SNAPSHOT_20260302.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 125 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/ci_soak_runs_20260302.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 126 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/ci_soak_summary_20260302.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 127 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/CI_SOAK_SUMMARY_20260302.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 130 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_ci_soak_20260302/pytest_schema_drift_sentinel_20260302.txt |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 132 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/EVIDENCE_PACK_MANIFEST.txt |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 133 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/pytest_reasoner_release_gate.txt |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 134 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/backend_smoke_mock_smt.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 134 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/backend_smoke_mock_fol.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 135 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/hybrid_v2_cli_batch_smoke.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 136 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/templates/HYBRID_LEGAL_RELEASE_CHECKLIST_TEMPLATE.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 137 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws10_release_20260302/WS10_RELEASE_CHECKLIST_20260302.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 138 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 139 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/run_legal_v2_ci_soak_snapshot.sh |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 140 | Referenced repository path not found: ipfs_datasets_py/scripts/ops/legal_data/collect_legal_v2_ci_soak_snapshot.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 169 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/pytest_reasoner_ws11.txt |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 170 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/EVIDENCE_PACK_MANIFEST.txt |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 171 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/pytest_reasoner_release_gate.txt |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 172 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/backend_smoke_mock_smt.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 172 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/backend_smoke_mock_fol.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 173 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/hybrid_v2_cli_batch_smoke.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 174 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws11_release_20260302/WS11_RELEASE_CHECKLIST_20260302.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 175 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/serialization.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 176 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/__init__.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 239 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/pytest_reasoner_ws9.txt |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 240 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/backend_smoke_mock_smt.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 240 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/backend_smoke_mock_fol.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 241 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/hybrid_v2_cli_batch_smoke.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 242 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws9_release_20260302/WS9_RELEASE_CHECKLIST_20260302.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 243 | Referenced repository path not found: ipfs_datasets_py/.github/workflows/legal-v2-reasoner-ci.yml |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 296 | Referenced repository path not found: ipfs_datasets_py/tests/reasoner/fixtures/hybrid_v2_api_schema_snapshot.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 296 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/schemas/v2_check_compliance.schema.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 296 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/schemas/v2_find_violations.schema.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 296 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/schemas/v2_explain_proof.schema.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 297 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/pytest_reasoner_ws8.txt |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 298 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/backend_smoke_mock_smt.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 298 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/backend_smoke_mock_fol.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 299 | Referenced repository path not found: artifacts/formal_logic_tmp_verify/federal/ws8_release_20260302/hybrid_v2_perf_baseline.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 368 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/ |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 404 | Referenced repository path not found: .vscode/tasks.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 413 | Referenced repository path not found: ipfs_datasets_py/.vscode/tasks.json |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 414 | Referenced repository path not found: src/municipal_scrape_workspace/hybrid_legal_ir.py |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 414 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/ |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md` | 428 | Referenced repository path not found: .github/workflows/legal-v2-reasoner-ci.yml |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_V2_OPTIMIZER_KG_PROVER_INTEGRATION_PLAN.md` | 20 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/ |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_V2_OPTIMIZER_KG_PROVER_INTEGRATION_PLAN.md` | 21 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/ |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_V2_OPTIMIZER_KG_PROVER_INTEGRATION_PLAN.md` | 24 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/ |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_WS10_POST_WS9_STABILIZATION_TICKETS.md` | 40 | Referenced repository path not found: .github/workflows/legal-v2-reasoner-ci.yml |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_WS11_V3_INTEGRATION_IMPLEMENTATION_TICKETS.md` | 222 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_WS11_V3_INTEGRATION_IMPLEMENTATION_TICKETS.md` | 257 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_WS11_V3_INTEGRATION_IMPLEMENTATION_TICKETS.md` | 258 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_WS8_IMPLEMENTATION_TICKETS.md` | 212 | Referenced repository path not found: .github/workflows/legal-v2-reasoner-ci.yml |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_WS9_IR_CNL_REASONER_IMPLEMENTATION_TICKETS.md` | 211 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_IR_CNL_REASONER_INTEGRATION_IMPROVEMENT_PLAN.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_WS9_IR_CNL_REASONER_IMPLEMENTATION_TICKETS.md` | 227 | Referenced repository path not found: ipfs_datasets_py/.github/workflows/legal-v2-reasoner-ci.yml |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_WS9_IR_CNL_REASONER_IMPLEMENTATION_TICKETS.md` | 228 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md |  |
| `repo_paths` | `docs/guides/legal_data/HYBRID_LEGAL_WS9_IR_CNL_REASONER_IMPLEMENTATION_TICKETS.md` | 229 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md |  |
| `repo_paths` | `docs/guides/legal_data/README.md` | 30 | Referenced repository path not found: ipfs_datasets_py/docs/guides/CLI_TOOL_MERGE.md |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 7 | Referenced repository path not found: src/municipal_scrape_workspace/hybrid_legal_ir.py |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 9 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/legal_data/reasoner/hybrid_legal_ir.py |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 18 | Referenced repository path not found: docs/HYBRID_LEGAL_IR_SPEC.md |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 19 | Referenced repository path not found: docs/HYBRID_LEGAL_REASONING_EXECUTION_PLAYBOOK.md |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 20 | Referenced repository path not found: docs/HYBRID_LEGAL_REASONING_IMPROVEMENT_PLAN.md |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 21 | Referenced repository path not found: docs/HYBRID_LEGAL_REASONING_TODO.md |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 22 | Referenced repository path not found: docs/REASONER_ARCHITECTURE.md |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 24 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/ |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 35 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/ROOT_TO_SUBMODULE_SCOPE1_MANIFEST_2026-03-01.tsv |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 36 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/ROOT_TO_SUBMODULE_SCOPE2_MANIFEST_2026-03-01.tsv |  |
| `repo_paths` | `docs/guides/legal_data/ROOT_TO_SUBMODULE_NONDATA_COMPLETION_2026-03-01.md` | 37 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/ROOT_TO_SUBMODULE_SCOPE3_MANIFEST_2026-03-01.tsv |  |
| `repo_paths` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md` | 66 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md |  |
| `repo_paths` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 29 | Referenced repository path not found: fixtures/cnl_parse_replay_v2_corpus.json |  |
| `repo_paths` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 30 | Referenced repository path not found: fixtures/compiler_parity_v2_cases.json |  |
| `repo_paths` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 31 | Referenced repository path not found: fixtures/cnl_parse_paraphrase_equivalence_v2.json |  |
| `repo_paths` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 32 | Referenced repository path not found: fixtures/cnl_v3_transformation_cases.json |  |
| `repo_paths` | `docs/guides/legal_data/templates/HYBRID_LEGAL_WS11_ISSUE_BODIES_07_12.md` | 122 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md |  |
| `repo_paths` | `docs/guides/legal_data/templates/HYBRID_LEGAL_WS11_ISSUE_BODIES_07_12.md` | 187 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md |  |
| `repo_paths` | `docs/guides/legal_data/templates/HYBRID_LEGAL_WS11_ISSUE_BODIES_07_12.md` | 188 | Referenced repository path not found: ipfs_datasets_py/docs/guides/legal_data/HYBRID_LEGAL_REASONING_TODO.md |  |
| `repo_paths` | `docs/guides/legal_data/templates/HYBRID_LEGAL_WS8_ISSUE_BODIES_06_15.md` | 218 | Referenced repository path not found: .github/workflows/legal-v2-reasoner-ci.yml |  |
| `repo_paths` | `docs/guides/p2p/P2P_CACHE_FINAL_STATUS.md` | 26 | Referenced repository path not found: ipfs_datasets_py/cache.py |  |
| `repo_paths` | `docs/guides/p2p/P2P_CACHE_INTEGRATION_SUMMARY.md` | 49 | Referenced repository path not found: ipfs_accelerate_py/github_cli/cache.py |  |
| `repo_paths` | `docs/guides/p2p/P2P_CACHE_INTEGRATION_SUMMARY.md` | 274 | Referenced repository path not found: mcp/tools/github_tools.py |  |
| `repo_paths` | `docs/guides/p2p/P2P_CACHE_INTEGRATION_SUMMARY.md` | 284 | Referenced repository path not found: ipfs_accelerate_py/copilot_cli/wrapper.py |  |
| `repo_paths` | `docs/guides/p2p/P2P_CACHE_INTEGRATION_SUMMARY.md` | 313 | Referenced repository path not found: ipfs_accelerate_py/distributed_cache.py |  |
| `repo_paths` | `docs/guides/p2p/P2P_CACHE_INTEGRATION_SUMMARY.md` | 314 | Referenced repository path not found: ipfs_accelerate_py/cached_github_cli.py |  |
| `repo_paths` | `docs/guides/p2p/P2P_CACHE_QUICK_REF.md` | 277 | Referenced repository path not found: github_cli/cache.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_BREAKING_CHANGES.md` | 328 | Referenced repository path not found: docs/PROCESSORS_ASYNC_COMPLETE_SUMMARY.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_CHANGELOG.md` | 127 | Referenced repository path not found: docs/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_CHANGELOG.md` | 229 | Referenced repository path not found: docs/PROCESSORS_MASTER_PLAN.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_CHANGELOG.md` | 230 | Referenced repository path not found: docs/PROCESSORS_QUICK_REFERENCE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` | 131 | Referenced repository path not found: processors/graphrag/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` | 225 | Referenced repository path not found: ipfs_datasets_py/processors/graphrag/unified_graphrag.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` | 288 | Referenced repository path not found: ipfs_datasets_py/data_transformation/ipld/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md` | 15 | Referenced repository path not found: ipfs_datasets_py/data_transformation/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 28 | Referenced repository path not found: ipfs_datasets_py/data_transformation/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 134 | Referenced repository path not found: data_transformation/unixfs.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 140 | Referenced repository path not found: data_transformation/ucan.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 446 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_MIGRATION_GUIDE_V2.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 454 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_FINAL_PROJECT_SUMMARY.md` | 83 | Referenced repository path not found: adapters/auto_register.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_FINAL_PROJECT_SUMMARY.md` | 189 | Referenced repository path not found: docs/PROCESSORS_CHANGELOG.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_FINAL_PROJECT_SUMMARY.md` | 199 | Referenced repository path not found: docs/PROCESSORS_BREAKING_CHANGES.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_FINAL_PROJECT_SUMMARY.md` | 210 | Referenced repository path not found: docs/PROCESSORS_PHASE7_DEVEX_COMPLETE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 37 | Referenced repository path not found: processors/DEPRECATIONS.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 53 | Referenced repository path not found: processors/graphrag/unified_graphrag.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 53 | Referenced repository path not found: specialized/graphrag/unified_processor.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 54 | Referenced repository path not found: processors/graphrag/integration.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 54 | Referenced repository path not found: specialized/graphrag/integration.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 55 | Referenced repository path not found: processors/graphrag/website_system.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 55 | Referenced repository path not found: specialized/graphrag/website_system.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 89 | Referenced repository path not found: specialized/pdf/processor.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 91 | Referenced repository path not found: specialized/pdf/text_extraction.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 92 | Referenced repository path not found: adapters/pdf_adapter.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 104 | Referenced repository path not found: adapters/multimodal_adapter.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 119 | Referenced repository path not found: infrastructure/caching.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 120 | Referenced repository path not found: infrastructure/monitoring.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 121 | Referenced repository path not found: infrastructure/error_handling.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 122 | Referenced repository path not found: infrastructure/profiling.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 123 | Referenced repository path not found: infrastructure/debug_tools.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 124 | Referenced repository path not found: infrastructure/cli.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 144 | Referenced repository path not found: specialized/__init__.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 157 | Referenced repository path not found: file_converter/batch_processor.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 176 | Referenced repository path not found: adapters/batch_adapter.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 192 | Referenced repository path not found: docs/archive/processors_stubs/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 227 | Referenced repository path not found: domains/patent/dataset_api.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 228 | Referenced repository path not found: domains/patent/scraper.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 229 | Referenced repository path not found: domains/geospatial/analysis.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 256 | Referenced repository path not found: multimedia/README.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 257 | Referenced repository path not found: multimedia/ARCHITECTURE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_CHECKLIST.md` | 258 | Referenced repository path not found: omni_converter_mk2/README.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_SUMMARY.md` | 16 | Referenced repository path not found: core/registry.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_SUMMARY.md` | 16 | Referenced repository path not found: core/processor_registry.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_SUMMARY.md` | 439 | Referenced repository path not found: ipfs_datasets_py/processors/graphrag/unified_graphrag.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_SUMMARY.md` | 446 | Referenced repository path not found: docs/PROCESSORS_REFACTORING_PLAN.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_SUMMARY.md` | 447 | Referenced repository path not found: docs/PROCESSORS_QUICK_REFERENCE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_SUMMARY.md` | 448 | Referenced repository path not found: docs/PROCESSORS_IMPLEMENTATION_SUMMARY.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_INDEX.md` | 274 | Referenced repository path not found: ipfs_datasets_py/data_transformation/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_INDEX.md` | 318 | Referenced repository path not found: ipfs_datasets_py/data_transformation/ipld/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 86 | Referenced repository path not found: processors/multimedia/converters/omni_converter/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 148 | Referenced repository path not found: processors/multimedia/converters/mime_converter/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 491 | Referenced repository path not found: tests/integration/processors/test_data_transformation_adapter.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 492 | Referenced repository path not found: tests/integration/processors/test_adapter_updates.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 513 | Referenced repository path not found: processors/graphrag/complete_advanced_graphrag.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 514 | Referenced repository path not found: processors/graphrag/integration.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 515 | Referenced repository path not found: processors/graphrag/phase7_complete_integration.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 516 | Referenced repository path not found: processors/graphrag/unified_graphrag.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 531 | Referenced repository path not found: docs/GRAPHRAG_AUDIT_REPORT.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 572 | Referenced repository path not found: docs/UNIFIED_GRAPHRAG_ARCHITECTURE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 629 | Referenced repository path not found: processors/graphrag/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 809 | Referenced repository path not found: tests/integration/test_complete_integration.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 810 | Referenced repository path not found: tests/integration/test_multimedia_pipeline.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 811 | Referenced repository path not found: tests/integration/test_serialization_pipeline.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 812 | Referenced repository path not found: tests/integration/test_graphrag_workflow.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 839 | Referenced repository path not found: docs/benchmarks/integration_benchmarks.json |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 840 | Referenced repository path not found: docs/PERFORMANCE_REPORT.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 867 | Referenced repository path not found: tests/compatibility/test_deprecation_warnings.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_PLAN_QUICK_REFERENCE.md` | 118 | Referenced repository path not found: core/processor_registry.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_PLAN_QUICK_REFERENCE.md` | 124 | Referenced repository path not found: core/input_detection.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_PLAN_QUICK_REFERENCE.md` | 127 | Referenced repository path not found: engines/relationship/analyzer.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_PLAN_QUICK_REFERENCE.md` | 128 | Referenced repository path not found: engines/relationship/api.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_PLAN_QUICK_REFERENCE.md` | 129 | Referenced repository path not found: engines/relationship/corpus.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_QUICK_REFERENCE.md` | 20 | Referenced repository path not found: core/universal_processor.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_QUICK_REFERENCE.md` | 273 | Referenced repository path not found: docs/PROCESSORS_ARCHITECTURE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_QUICK_REFERENCE.md` | 274 | Referenced repository path not found: docs/PROCESSORS_API_REFERENCE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_QUICK_REFERENCE.md` | 275 | Referenced repository path not found: docs/PROCESSORS_MIGRATION_GUIDE.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_QUICK_REFERENCE.md` | 276 | Referenced repository path not found: docs/PROCESSORS_ADDING_NEW.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_QUICK_REFERENCE.md` | 294 | Referenced repository path not found: docs/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 40 | Referenced repository path not found: graphrag/unified_graphrag.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 41 | Referenced repository path not found: graphrag/integration.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 42 | Referenced repository path not found: graphrag/website_system.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 43 | Referenced repository path not found: graphrag/complete_advanced_graphrag.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 44 | Referenced repository path not found: graphrag/extract.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 45 | Referenced repository path not found: graphrag/query.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 84 | Referenced repository path not found: file_converter/batch_processor.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 108 | Referenced repository path not found: core/protocol.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 109 | Referenced repository path not found: core/processor_registry.py |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 301 | Referenced repository path not found: processors/graphrag/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md` | 22 | Referenced repository path not found: processors/graphrag/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_REFACTORING_SUMMARY_2026.md` | 56 | Referenced repository path not found: processors/graphrag/ |  |
| `repo_paths` | `docs/guides/processors/PROCESSORS_STATUS_2026_02_16.md` | 30 | Referenced repository path not found: core/registry.py |  |
| `repo_paths` | `docs/guides/reference/scraper_testing_framework.md` | 43 | Referenced repository path not found: ipfs_datasets_py/scraper_testing_framework.py |  |
| `repo_paths` | `docs/guides/reference/scraper_testing_framework.md` | 53 | Referenced repository path not found: tests/scraper_tests/ |  |
| `repo_paths` | `docs/guides/reference/scraper_testing_framework.md` | 62 | Referenced repository path not found: .github/workflows/scraper-validation.yml |  |
| `repo_paths` | `docs/guides/security/SECRETS_AND_CREDENTIALS.md` | 109 | Referenced repository path not found: ~/.ipfs_datasets/secrets_vault.json |  |
| `repo_paths` | `docs/guides/security/audit_logging.md` | 692 | Referenced repository path not found: examples/rag_audit_integration_example.py |  |
| `repo_paths` | `docs/guides/tools/brave_search_client.md` | 164 | Referenced repository path not found: ipfs_datasets_py/web_archiving/brave_search_client.py |  |
| `repo_paths` | `docs/guides/tools/brave_search_client.md` | 290 | Referenced repository path not found: ccsearch/brave_search.py |  |
| `repo_paths` | `docs/guides/tools/brave_search_ipfs_cache.md` | 469 | Referenced repository path not found: docs/brave_search_client.md |  |
| `repo_paths` | `docs/guides/tools/caselaw_dashboard_guide.md` | 269 | Referenced repository path not found: ~/.ipfs_datasets/state_laws/schedule.json |  |
| `repo_paths` | `docs/guides/tools/caselaw_dashboard_guide.md` | 270 | Referenced repository path not found: ~/.ipfs_datasets/state_laws/state_laws_<schedule_id>_<timestamp>.json |  |
| `repo_paths` | `docs/guides/tools/cli_error_auto_healing.md` | 269 | Referenced repository path not found: docs/CLI_ERROR_AUTO_HEALING.md |  |
| `repo_paths` | `docs/guides/tools/cli_readme.md` | 202 | Referenced repository path not found: ~/.ipfs_datasets/cli.json |  |
| `repo_paths` | `docs/guides/tools/common_crawl_integration.md` | 377 | Referenced repository path not found: ipfs_datasets_py/web_archiving/common_crawl_search_engine/README.md |  |
| `repo_paths` | `docs/guides/tools/common_crawl_integration.md` | 379 | Referenced repository path not found: docs/guides/mcp_server.md |  |
| `repo_paths` | `docs/guides/tools/common_crawl_integration.md` | 380 | Referenced repository path not found: docs/dashboards.md |  |
| `repo_paths` | `docs/guides/tools/common_crawl_integration_summary.md` | 372 | Referenced repository path not found: docs/common_crawl_integration.md |  |
| `repo_paths` | `docs/guides/tools/common_crawl_integration_summary.md` | 378 | Referenced repository path not found: ipfs_datasets_py/web_archiving/common_crawl_search_engine_README.md |  |
| `repo_paths` | `docs/guides/tools/common_crawl_integration_summary.md` | 383 | Referenced repository path not found: ipfs_datasets_py/web_archiving/common_crawl_search_engine/README.md |  |
| `repo_paths` | `docs/guides/tools/discord_alerts_guide.md` | 674 | Referenced repository path not found: examples/discord_alerts_demo.py |  |
| `repo_paths` | `docs/guides/tools/js_error_auto_healing_guide.md` | 46 | Referenced repository path not found: docs/javascript_error_auto_healing.md |  |
| `repo_paths` | `docs/guides/tools/js_error_auto_healing_guide.md` | 50 | Referenced repository path not found: ipfs_datasets_py/admin_dashboard.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 85 | Referenced repository path not found: mcp_tools/tools/embedding_tools.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 105 | Referenced repository path not found: embeddings/create_embeddings.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 106 | Referenced repository path not found: ipfs_embeddings_py/multi_model_embedding.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 107 | Referenced repository path not found: llm/llm_interface.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 113 | Referenced repository path not found: ipfs_embeddings_py/embeddings_engine.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 114 | Referenced repository path not found: embeddings/chunker.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 115 | Referenced repository path not found: embeddings/core.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 119 | Referenced repository path not found: pdf_processing/query_engine.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 120 | Referenced repository path not found: pdf_processing/llm_optimizer.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 121 | Referenced repository path not found: pdf_processing/ocr_engine.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 122 | Referenced repository path not found: pdf_processing/classify_with_llm.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 123 | Referenced repository path not found: pdf_processing/graphrag_integrator.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_FINAL_VERIFICATION.md` | 132 | Referenced repository path not found: mcp_server/tools/legal_dataset_tools/.../make_openai_embeddings.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_COMPLETE.md` | 14 | Referenced repository path not found: ipfs_datasets_py/embeddings/create_embeddings.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_COMPLETE.md` | 34 | Referenced repository path not found: ipfs_datasets_py/ipfs_embeddings_py/multi_model_embedding.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_COMPLETE.md` | 54 | Referenced repository path not found: ipfs_datasets_py/llm/llm_interface.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_COMPLETE.md` | 295 | Referenced repository path not found: ipfs_datasets_py/accelerate_integration/README.md |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_COMPLETE.md` | 297 | Referenced repository path not found: examples/accelerate_integration_demo.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_PLAN.md` | 123 | Referenced repository path not found: ipfs_datasets_py/ipfs_embeddings_py/multi_model_embedding.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_PLAN.md` | 198 | Referenced repository path not found: embeddings/create_embeddings.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_PLAN.md` | 199 | Referenced repository path not found: ipfs_embeddings_py/multi_model_embedding.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_SUMMARY.md` | 73 | Referenced repository path not found: ipfs_datasets_py/accelerate_integration/README.md |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_SUMMARY.md` | 92 | Referenced repository path not found: examples/accelerate_integration_demo.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_SUMMARY.md` | 237 | Referenced repository path not found: embeddings/create_embeddings.py |  |
| `repo_paths` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_SUMMARY.md` | 238 | Referenced repository path not found: ipfs_embeddings_py/multi_model_embedding.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 20 | Referenced repository path not found: tests/unit/test_all_mcp_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 20 | Referenced repository path not found: tests/migration_tests/comprehensive_mcp_tools_test_suite.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 21 | Referenced repository path not found: tests/migration_tests/test_all_mcp_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 23 | Referenced repository path not found: tests/migration_tests/test_generator_for_dataset_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 29 | Referenced repository path not found: tests/migration_tests/test_generator_for_ipfs_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 34 | Referenced repository path not found: tests/migration_tests/comprehensive_mcp_test.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 40 | Referenced repository path not found: tests/migration_tests/test_generator_for_audit_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 46 | Referenced repository path not found: tests/test_admin_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 55 | Referenced repository path not found: tests/test_cache_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 62 | Referenced repository path not found: tests/migration_tests/test_runner_debug.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 65 | Referenced repository path not found: tests/migration_tests/test_test_generator.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 75 | Referenced repository path not found: tests/migration_tests/test_web_archive_mcp_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 90 | Referenced repository path not found: tests/migration_tests/test_multiple_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 244 | Referenced repository path not found: tests/mcp/test_mcp_server_integration.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 245 | Referenced repository path not found: tests/unit/test_pdf_processing.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 250 | Referenced repository path not found: tests/integration/test_multimedia_integration.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_ANALYSIS.md` | 250 | Referenced repository path not found: tests/unit/test_ytdlp_wrapper.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_TODO.md` | 41 | Referenced repository path not found: /tests/unit/test_pdf_mcp_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_TODO.md` | 45 | Referenced repository path not found: /tests/unit/test_ytdlp_mcp_real.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_TODO.md` | 49 | Referenced repository path not found: /tests/unit/test_vector_mcp_real.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_TODO_CHANGELOG.md` | 171 | Referenced repository path not found: /tests/unit/test_pdf_mcp_tools.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_TODO_CHANGELOG.md` | 182 | Referenced repository path not found: /tests/unit/test_ytdlp_mcp_stubs.py |  |
| `repo_paths` | `docs/implementation/plans/MCP_TOOLS_TEST_COVERAGE_TODO_CHANGELOG.md` | 192 | Referenced repository path not found: /tests/unit/test_vector_mcp_stubs.py |  |
| `repo_paths` | `docs/implementation/plans/NOTIMPLEMENTEDERROR_IMPLEMENTATION_PLAN.md` | 61 | Referenced repository path not found: ipfs_datasets_py/llm/llm_interface.py |  |
| `repo_paths` | `docs/implementation/plans/NOTIMPLEMENTEDERROR_IMPLEMENTATION_PLAN.md` | 66 | Referenced repository path not found: ipfs_datasets_py/data_provenance_enhanced.py |  |
| `repo_paths` | `docs/implementation/plans/NOTIMPLEMENTEDERROR_IMPLEMENTATION_PLAN.md` | 66 | Referenced repository path not found: ipfs_datasets_py/resilient_operations.py |  |
| `repo_paths` | `docs/implementation/plans/PHASE7_COMPLETION_SUMMARY.md` | 30 | Referenced repository path not found: ipfs_datasets_py/phase7_complete_integration.py |  |
| `repo_paths` | `docs/implementation/plans/ROOT_CLEANUP_COMPLETION_REPORT.md` | 117 | Referenced repository path not found: archive/migration/tests/ |  |
| `repo_paths` | `docs/implementation/plans/ROOT_CLEANUP_COMPLETION_REPORT.md` | 118 | Referenced repository path not found: archive/test_results/ |  |
| `repo_paths` | `docs/implementation/plans/ROOT_CLEANUP_COMPLETION_REPORT.md` | 119 | Referenced repository path not found: archive/test_visualizations/ |  |
| `repo_paths` | `docs/implementation/plans/ROOT_CLEANUP_PLAN.md` | 39 | Referenced repository path not found: .gitignore |  |
| `repo_paths` | `docs/implementation/plans/ROOT_CLEANUP_PLAN.md` | 51 | Referenced repository path not found: .github/ |  |
| `repo_paths` | `docs/implementation/plans/ROOT_CLEANUP_PLAN.md` | 60 | Referenced repository path not found: docs/migration/ |  |
| `repo_paths` | `docs/implementation/plans/ROOT_CLEANUP_PLAN.md` | 120 | Referenced repository path not found: archive/migration/tests/ |  |
| `repo_paths` | `docs/implementation/plans/ROOT_CLEANUP_PLAN.md` | 121 | Referenced repository path not found: archive/test_results/ |  |
| `repo_paths` | `docs/implementation/plans/ROOT_CLEANUP_PLAN.md` | 122 | Referenced repository path not found: archive/test_visualizations/ |  |
| `repo_paths` | `docs/implementation/plans/file_conversion_integration_plan.md` | 212 | Referenced repository path not found: ipfs_datasets_py/file_converter/converter.py |  |
| `repo_paths` | `docs/implementation/plans/file_conversion_integration_plan.md` | 379 | Referenced repository path not found: ipfs_datasets_py/file_converter/backends/markitdown_backend.py |  |
| `repo_paths` | `docs/implementation/plans/file_conversion_integration_plan.md` | 450 | Referenced repository path not found: ipfs_datasets_py/file_converter/backends/omni_backend.py |  |
| `repo_paths` | `docs/implementation/plans/file_conversion_integration_plan.md` | 506 | Referenced repository path not found: ipfs_datasets_py/file_converter/backends/native_backend.py |  |
| `repo_paths` | `docs/implementation/plans/file_conversion_systems_analysis.md` | 56 | Referenced repository path not found: ipfs_datasets_py/data_transformation/multimedia/omni_converter_mk2 |  |
| `repo_paths` | `docs/implementation/plans/file_conversion_systems_analysis.md` | 116 | Referenced repository path not found: ipfs_datasets_py/data_transformation/multimedia/convert_to_txt_based_on_mime_type |  |
| `repo_paths` | `docs/implementation/plans/file_conversion_systems_analysis.md` | 376 | Referenced repository path not found: ipfs_datasets_py/rag/ |  |
| `repo_paths` | `docs/implementation/plans/file_converter_complete_summary.md` | 195 | Referenced repository path not found: backends/ipfs_backend.py |  |
| `repo_paths` | `docs/implementation/plans/graphrag_website_implementation_plan.md` | 20 | Referenced repository path not found: ipfs_datasets_py/website_graphrag_processor.py |  |
| `repo_paths` | `docs/implementation/plans/graphrag_website_implementation_plan.md` | 85 | Referenced repository path not found: ipfs_datasets_py/multimodal_processor.py |  |
| `repo_paths` | `docs/implementation/plans/graphrag_website_implementation_plan.md` | 111 | Referenced repository path not found: ipfs_datasets_py/website_graphrag_system.py |  |
| `repo_paths` | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` | 347 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/a0-baseline-v1/state/baseline-manifest.json |  |
| `repo_paths` | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` | 389 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/results/frontend-overlap-v1.json |  |
| `repo_paths` | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` | 410 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/results/proof-overlap-ordering-v1.json |  |
| `repo_paths` | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` | 563 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/results/pilot-shortlist-v1.json |  |
| `repo_paths` | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` | 630 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/results/holdout-evaluation-v1.json |  |
| `repo_paths` | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` | 979 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/state/baseline-manifest.json |  |
| `repo_paths` | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` | 1154 | Referenced repository path not found: reassessment-v2/receipts/capability-inventory.json |  |
| `repo_paths` | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` | 1224 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/matrix-execution-v2.json |  |
| `repo_paths` | `docs/implementation/plans/hammer_symai_spacy_leanstral_benchmark_objectives.md` | 1511 | Referenced repository path not found: reassessment-v2/replay/replay-index.json |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 82 | Referenced repository path not found: ipfs_formats/ipfs_multiformats.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 82 | Referenced repository path not found: data_transformation/ipfs_formats/ipfs_multiformats.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 83 | Referenced repository path not found: ipfs_formats/__init__.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 83 | Referenced repository path not found: data_transformation/ipfs_formats/__init__.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 99 | Referenced repository path not found: ipld/storage.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 99 | Referenced repository path not found: data_transformation/ipld/storage.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 100 | Referenced repository path not found: ipld/dag_pb.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 100 | Referenced repository path not found: data_transformation/ipld/dag_pb.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 101 | Referenced repository path not found: ipld/optimized_codec.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 101 | Referenced repository path not found: data_transformation/ipld/optimized_codec.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 102 | Referenced repository path not found: ipld/__init__.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 102 | Referenced repository path not found: data_transformation/ipld/__init__.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 108 | Referenced repository path not found: ipld/vector_store.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 109 | Referenced repository path not found: ipld/knowledge_graph.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 109 | Referenced repository path not found: knowledge_graphs/ipld_knowledge_graph.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 110 | Referenced repository path not found: ipld/storage_stubs.md |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 131 | Referenced repository path not found: integrations/graphrag_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 131 | Referenced repository path not found: graphrag/integrations/graphrag_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 132 | Referenced repository path not found: integrations/enhanced_graphrag_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 132 | Referenced repository path not found: graphrag/integrations/enhanced_graphrag_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 133 | Referenced repository path not found: integrations/phase7_complete_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 133 | Referenced repository path not found: graphrag/integrations/phase7_complete_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 134 | Referenced repository path not found: integrations/unixfs_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 134 | Referenced repository path not found: data_transformation/ipld/unixfs_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 135 | Referenced repository path not found: integrations/__init__.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 135 | Referenced repository path not found: graphrag/integrations/__init__.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 147 | Referenced repository path not found: file_converter/converter.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 148 | Referenced repository path not found: file_converter/pipeline.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 149 | Referenced repository path not found: file_converter/errors.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 150 | Referenced repository path not found: file_converter/format_detector.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 151 | Referenced repository path not found: file_converter/text_extractors.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 152 | Referenced repository path not found: file_converter/metadata_extractor.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 153 | Referenced repository path not found: file_converter/batch_processor.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 154 | Referenced repository path not found: file_converter/ipfs_accelerate_converter.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 155 | Referenced repository path not found: file_converter/knowledge_graph_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 156 | Referenced repository path not found: file_converter/vector_embedding_integration.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 157 | Referenced repository path not found: file_converter/archive_handler.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 158 | Referenced repository path not found: file_converter/url_handler.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 159 | Referenced repository path not found: file_converter/office_format_extractors.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 160 | Referenced repository path not found: file_converter/exports.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 161 | Referenced repository path not found: file_converter/cli.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 161 | Referenced repository path not found: cli/file_converter.py |  |
| `repo_paths` | `docs/implementation/plans/module_consolidation_plan.md` | 169 | Referenced repository path not found: file_converter/__init__.py |  |
| `repo_paths` | `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md` | 1266 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/replay/replay-index.json |  |
| `repo_paths` | `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md` | 1348 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/a0-baseline-v1/state/baseline-manifest.json |  |
| `repo_paths` | `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md` | 1350 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/matrix-execution-v2.json |  |
| `repo_paths` | `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md` | 1351 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/pilot-shortlist-v2.json |  |
| `repo_paths` | `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md` | 1352 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/holdout-evaluation-v2.json |  |
| `repo_paths` | `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md` | 1354 | Referenced repository path not found: workspace/benchmarks/hammer-symai-spacy-leanstral/reassessment-v2/results/statistics.json |  |
| `repo_paths` | `docs/implementation/runbooks/hammer_symai_spacy_leanstral_benchmark.md` | 1358 | Referenced repository path not found: data/agent_supervisor/discovery/2026-07-24-hssl-bench-043-objective-gap-f4c6a8ab86c9.md |  |
| `repo_paths` | `docs/implementation/runbooks/leanstral_legal_ir_rollout.md` | 30 | Referenced repository path not found: workspace/leanstral-audit-worker/lean-proof-cache.json |  |
| `repo_paths` | `docs/implementation/runbooks/leanstral_legal_ir_rollout.md` | 144 | Referenced repository path not found: workspace/test-logs/<run-id>.reference-examples.json |  |
| `repo_paths` | `docs/implementation/runbooks/logic_intent_legal_gate_rollout.md` | 497 | Referenced repository path not found: ipfs_accelerate_py/agent_supervisor/admissibility_bridge.py |  |
| `repo_paths` | `docs/implementation/runbooks/semantic_roundtrip_dynamic_supervisor.md` | 21 | Referenced repository path not found: bundles/index.json |  |
| `repo_paths` | `docs/implementation/scrapers/UNIFIED_SCRAPER_IMPLEMENTATION.md` | 9 | Referenced repository path not found: ipfs_datasets_py/unified_web_scraper.py |  |
| `repo_paths` | `docs/implementation/scrapers/UNIFIED_SCRAPER_IMPLEMENTATION.md` | 28 | Referenced repository path not found: ipfs_datasets_py/scraper_cli.py |  |
| `repo_paths` | `docs/implementation/scrapers/UNIFIED_SCRAPER_IMPLEMENTATION.md` | 144 | Referenced repository path not found: state_scrapers/base_scraper.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 52 | Referenced repository path not found: query/completion.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 61 | Referenced repository path not found: query/explanation.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 74 | Referenced repository path not found: query/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 91 | Referenced repository path not found: query/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 131 | Referenced repository path not found: query/groth16_bridge.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 171 | Referenced repository path not found: query/zkp.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 202 | Referenced repository path not found: query/gnn.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 231 | Referenced repository path not found: extraction/provenance.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 235 | Referenced repository path not found: extraction/graph.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 240 | Referenced repository path not found: extraction/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 255 | Referenced repository path not found: query/federation.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 282 | Referenced repository path not found: extraction/visualization.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 309 | Referenced repository path not found: query/graphql.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 372 | Referenced repository path not found: extraction/extractor.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 374 | Referenced repository path not found: migration/formats.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 378 | Referenced repository path not found: extraction/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 388 | Referenced repository path not found: cypher/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 389 | Referenced repository path not found: core/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 460 | Referenced repository path not found: reasoning/cross_document.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 543 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/knowledge_graphs/ |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 661 | Referenced repository path not found: extraction/srl.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 743 | Referenced repository path not found: lineage/visualization.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 764 | Referenced repository path not found: core/ir_executor.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 894 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/MASTER_STATUS.md |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 895 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/IMPROVEMENT_TODO.md |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 896 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1037 | Referenced repository path not found: ontology/reasoning.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1090 | Referenced repository path not found: query/unified_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1091 | Referenced repository path not found: transactions/wal.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1092 | Referenced repository path not found: storage/ipld_backend.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1093 | Referenced repository path not found: query/hybrid_search.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1130 | Referenced repository path not found: reasoning/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1132 | Referenced repository path not found: reasoning/helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1133 | Referenced repository path not found: reasoning/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1134 | Referenced repository path not found: reasoning/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1150 | Referenced repository path not found: lineage/cross_document.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1151 | Referenced repository path not found: lineage/cross_document_enhanced.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1152 | Referenced repository path not found: query/knowledge_graph.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1153 | Referenced repository path not found: query/sparql_templates.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1154 | Referenced repository path not found: extraction/finance_graphrag.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1160 | Referenced repository path not found: lineage/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 1161 | Referenced repository path not found: graph_tools/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 21 | Referenced repository path not found: cypher/parser.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 21 | Referenced repository path not found: cypher/compiler.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 21 | Referenced repository path not found: core/expression_evaluator.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 59 | Referenced repository path not found: cypher/ast.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 59 | Referenced repository path not found: core/ir_executor.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 135 | Referenced repository path not found: cypher/lexer.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 185 | Referenced repository path not found: migration/formats.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 244 | Referenced repository path not found: extraction/extractor.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 277 | Referenced repository path not found: extraction/srl.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 369 | Referenced repository path not found: ontology/reasoning.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 426 | Referenced repository path not found: query/distributed.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 450 | Referenced repository path not found: query/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 555 | Referenced repository path not found: extraction/graph.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 696 | Referenced repository path not found: query/graphql.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 754 | Referenced repository path not found: extraction/visualization.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 770 | Referenced repository path not found: extraction/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 845 | Referenced repository path not found: query/federation.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 976 | Referenced repository path not found: query/gnn.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 1015 | Referenced repository path not found: query/zkp.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 1090 | Referenced repository path not found: query/groth16_bridge.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 1148 | Referenced repository path not found: query/completion.py |  |
| `repo_paths` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 1189 | Referenced repository path not found: query/explanation.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 33 | Referenced repository path not found: graph_tools/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 34 | Referenced repository path not found: query/completion.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 34 | Referenced repository path not found: query/explanation.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 34 | Referenced repository path not found: query/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 35 | Referenced repository path not found: query/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 36 | Referenced repository path not found: query/zkp.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 37 | Referenced repository path not found: query/gnn.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 38 | Referenced repository path not found: extraction/provenance.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 39 | Referenced repository path not found: query/federation.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 40 | Referenced repository path not found: extraction/visualization.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 41 | Referenced repository path not found: query/graphql.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 59 | Referenced repository path not found: migration/formats.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 113 | Referenced repository path not found: extraction/extractor.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 113 | Referenced repository path not found: migration/ipfs_importer.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 205 | Referenced repository path not found: migration/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 212 | Referenced repository path not found: core/query_executor.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 213 | Referenced repository path not found: extraction/_entity_helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 213 | Referenced repository path not found: core/_legacy_graph_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 216 | Referenced repository path not found: core/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 216 | Referenced repository path not found: core/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 245 | Referenced repository path not found: ipfs_datasets_py/.coveragerc |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 250 | Referenced repository path not found: transactions/wal.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 251 | Referenced repository path not found: query/unified_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 252 | Referenced repository path not found: query/hybrid_search.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 253 | Referenced repository path not found: core/graph_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 254 | Referenced repository path not found: core/ir_executor.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 255 | Referenced repository path not found: transactions/manager.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 256 | Referenced repository path not found: jsonld/validation.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 257 | Referenced repository path not found: cypher/parser.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 257 | Referenced repository path not found: cypher/compiler.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 261 | Referenced repository path not found: migration/neo4j_exporter.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 262 | Referenced repository path not found: storage/ipld_backend.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 264 | Referenced repository path not found: core/expression_evaluator.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 267 | Referenced repository path not found: extraction/validator.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 300 | Referenced repository path not found: lineage/test_core.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 302 | Referenced repository path not found: extraction/_wikipedia_helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 303 | Referenced repository path not found: extraction/advanced.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 303 | Referenced repository path not found: extraction/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 330 | Referenced repository path not found: indexing/btree.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 343 | Referenced repository path not found: extraction/graph.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 346 | Referenced repository path not found: extraction/srl.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 366 | Referenced repository path not found: jsonld/translator.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 366 | Referenced repository path not found: ontology/reasoning.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 366 | Referenced repository path not found: reasoning/cross_document.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 369 | Referenced repository path not found: query/distributed.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 369 | Referenced repository path not found: reasoning/helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 369 | Referenced repository path not found: cypher/functions.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 369 | Referenced repository path not found: cypher/lexer.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 369 | Referenced repository path not found: neo4j_compat/result.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 369 | Referenced repository path not found: neo4j_compat/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 369 | Referenced repository path not found: jsonld/rdf_serializer.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 369 | Referenced repository path not found: extraction/finance_graphrag.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 372 | Referenced repository path not found: lineage/enhanced.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 372 | Referenced repository path not found: lineage/metrics.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 375 | Referenced repository path not found: indexing/manager.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 375 | Referenced repository path not found: jsonld/context.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 378 | Referenced repository path not found: extraction/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 381 | Referenced repository path not found: lineage/visualization.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 384 | Referenced repository path not found: query/knowledge_graph.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 444 | Referenced repository path not found: neo4j_compat/driver.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 448 | Referenced repository path not found: lineage/core.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 449 | Referenced repository path not found: reasoning/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 569 | Referenced repository path not found: tests/unit/knowledge_graphs/test_master_status_session52.py::TestIpldCarAvailable |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 573 | Referenced repository path not found: tests/unit/knowledge_graphs/test_master_status_session53.py::TestGetConnectedEntitiesDepthInvariant::test_get_connected_entities_returns_correct_neighbors |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 837 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/knowledge_graphs/ |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 1083 | Referenced repository path not found: cypher/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 1084 | Referenced repository path not found: core/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 1122 | Referenced repository path not found: extraction/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/IMPROVEMENT_TODO.md` | 1217 | Referenced repository path not found: query/groth16_bridge.py |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 142 | Referenced repository path not found: extraction/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 143 | Referenced repository path not found: cypher/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 144 | Referenced repository path not found: query/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 145 | Referenced repository path not found: core/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 146 | Referenced repository path not found: storage/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 147 | Referenced repository path not found: neo4j_compat/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 148 | Referenced repository path not found: transactions/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 150 | Referenced repository path not found: lineage/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 151 | Referenced repository path not found: indexing/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 152 | Referenced repository path not found: jsonld/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 153 | Referenced repository path not found: constraints/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/INDEX.md` | 154 | Referenced repository path not found: reasoning/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 41 | Referenced repository path not found: storage/ipld_backend.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 42 | Referenced repository path not found: cypher/parser.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 43 | Referenced repository path not found: cypher/compiler.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 44 | Referenced repository path not found: ontology/reasoning.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 45 | Referenced repository path not found: extraction/extractor.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 46 | Referenced repository path not found: migration/formats.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 47 | Referenced repository path not found: cypher/functions.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 48 | Referenced repository path not found: query/distributed.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 49 | Referenced repository path not found: reasoning/cross_document.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 50 | Referenced repository path not found: extraction/srl.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 51 | Referenced repository path not found: extraction/advanced.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 102 | Referenced repository path not found: core/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 105 | Referenced repository path not found: extraction/_entity_helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 106 | Referenced repository path not found: core/_legacy_graph_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 108 | Referenced repository path not found: query/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 182 | Referenced repository path not found: storage/ipld_legacy.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 191 | Referenced repository path not found: extraction/_wikipedia_helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 225 | Referenced repository path not found: extraction/validator.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 248 | Referenced repository path not found: lineage/core.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 248 | Referenced repository path not found: lineage/enhanced.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 248 | Referenced repository path not found: lineage/metrics.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 299 | Referenced repository path not found: cypher/ast.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 299 | Referenced repository path not found: cypher/lexer.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 299 | Referenced repository path not found: core/ir_executor.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 299 | Referenced repository path not found: core/expression_evaluator.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 331 | Referenced repository path not found: query/unified_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 332 | Referenced repository path not found: tests/unit/knowledge_graphs/test_unwind_with_clauses.py::TestAsyncExecute |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 353 | Referenced repository path not found: reasoning/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 353 | Referenced repository path not found: reasoning/helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_REFACTORING_PLAN_2026.md` | 353 | Referenced repository path not found: reasoning/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 6 | Referenced repository path not found: graph_tools/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 142 | Referenced repository path not found: extraction/srl.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 143 | Referenced repository path not found: ontology/reasoning.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 144 | Referenced repository path not found: query/distributed.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 239 | Referenced repository path not found: extraction/graph.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 240 | Referenced repository path not found: migration/formats.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 249 | Referenced repository path not found: lineage/visualization.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 254 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/knowledge_graphs/ |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 260 | Referenced repository path not found: cypher/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 260 | Referenced repository path not found: core/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 261 | Referenced repository path not found: extraction/extractor.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 261 | Referenced repository path not found: extraction/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 262 | Referenced repository path not found: extraction/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 264 | Referenced repository path not found: query/graphql.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 264 | Referenced repository path not found: query/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 265 | Referenced repository path not found: extraction/visualization.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 266 | Referenced repository path not found: query/federation.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 267 | Referenced repository path not found: query/gnn.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 267 | Referenced repository path not found: query/zkp.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 268 | Referenced repository path not found: query/README.md |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 270 | Referenced repository path not found: query/completion.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 270 | Referenced repository path not found: query/explanation.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 271 | Referenced repository path not found: query/groth16_bridge.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 561 | Referenced repository path not found: extraction/validator.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 561 | Referenced repository path not found: core/graph_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 581 | Referenced repository path not found: extraction/_wikipedia_helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 583 | Referenced repository path not found: extraction/finance_graphrag.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 584 | Referenced repository path not found: transactions/manager.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 585 | Referenced repository path not found: storage/ipld_backend.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 597 | Referenced repository path not found: transactions/wal.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 603 | Referenced repository path not found: jsonld/validation.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 609 | Referenced repository path not found: core/expression_evaluator.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 612 | Referenced repository path not found: query/knowledge_graph.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 634 | Referenced repository path not found: core/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 635 | Referenced repository path not found: neo4j_compat/driver.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 657 | Referenced repository path not found: migration/neo4j_exporter.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 657 | Referenced repository path not found: migration/ipfs_importer.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 657 | Referenced repository path not found: core/_legacy_graph_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 696 | Referenced repository path not found: reasoning/helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 696 | Referenced repository path not found: jsonld/context.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 696 | Referenced repository path not found: lineage/core.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 696 | Referenced repository path not found: lineage/enhanced.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 696 | Referenced repository path not found: lineage/metrics.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 702 | Referenced repository path not found: jsonld/rdf_serializer.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 706 | Referenced repository path not found: neo4j_compat/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 710 | Referenced repository path not found: extraction/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 719 | Referenced repository path not found: neo4j_compat/connection_pool.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 719 | Referenced repository path not found: transactions/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 719 | Referenced repository path not found: neo4j_compat/result.py+session.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 719 | Referenced repository path not found: query/unified_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 719 | Referenced repository path not found: query/hybrid_search.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 719 | Referenced repository path not found: indexing/btree.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 719 | Referenced repository path not found: cypher/compiler.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 719 | Referenced repository path not found: cypher/ast.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 724 | Referenced repository path not found: neo4j_compat/bookmarks.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 725 | Referenced repository path not found: neo4j_compat/result.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 726 | Referenced repository path not found: neo4j_compat/session.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 755 | Referenced repository path not found: extraction/relationships.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 755 | Referenced repository path not found: extraction/_entity_helpers.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 755 | Referenced repository path not found: core/query_executor.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 755 | Referenced repository path not found: reasoning/cross_document.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 763 | Referenced repository path not found: core/ir_executor.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 788 | Referenced repository path not found: cypher/lexer.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 788 | Referenced repository path not found: extraction/advanced.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 827 | Referenced repository path not found: cypher/parser.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 836 | Referenced repository path not found: jsonld/translator.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 963 | Referenced repository path not found: constraints/__init__.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 1050 | Referenced repository path not found: lineage/cross_document.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 1051 | Referenced repository path not found: lineage/cross_document_enhanced.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 1053 | Referenced repository path not found: storage/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 1055 | Referenced repository path not found: indexing/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 1057 | Referenced repository path not found: indexing/manager.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 1098 | Referenced repository path not found: reasoning/types.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 1102 | Referenced repository path not found: migration/test_formats.py |  |
| `repo_paths` | `docs/knowledge_graphs/MASTER_STATUS.md` | 1125 | Referenced repository path not found: query/sparql_templates.py |  |
| `repo_paths` | `docs/knowledge_graphs/P3_P4_IMPLEMENTATION_COMPLETE.md` | 17 | Referenced repository path not found: extraction/extractor.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 45 | Referenced repository path not found: extraction/srl.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 49 | Referenced repository path not found: ontology/reasoning.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 53 | Referenced repository path not found: query/distributed.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 57 | Referenced repository path not found: migration/formats.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 150 | Referenced repository path not found: extraction/extractor.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 269 | Referenced repository path not found: transactions/wal.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 271 | Referenced repository path not found: extraction/entities.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 271 | Referenced repository path not found: extraction/relationships.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 277 | Referenced repository path not found: query/unified_engine.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 279 | Referenced repository path not found: storage/ipld_backend.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 280 | Referenced repository path not found: query/hybrid_search.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 309 | Referenced repository path not found: extraction/graph.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 313 | Referenced repository path not found: core/expression_evaluator.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 316 | Referenced repository path not found: cypher/compiler.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 347 | Referenced repository path not found: query/gnn.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 348 | Referenced repository path not found: extraction/visualization.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 349 | Referenced repository path not found: query/graphql.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 350 | Referenced repository path not found: extraction/provenance.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 351 | Referenced repository path not found: query/federation.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 352 | Referenced repository path not found: query/zkp.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 357 | Referenced repository path not found: query/completion.py |  |
| `repo_paths` | `docs/knowledge_graphs/ROADMAP.md` | 358 | Referenced repository path not found: query/explanation.py |  |
| `repo_paths` | `docs/logic/BEST_PRACTICES.md` | 620 | Referenced repository path not found: docs/LOGIC_INTEGRATION_GUIDE.md |  |
| `repo_paths` | `docs/logic/BEST_PRACTICES.md` | 648 | Referenced repository path not found: docs/LOGIC_USAGE_EXAMPLES.md |  |
| `repo_paths` | `docs/logic/BEST_PRACTICES.md` | 649 | Referenced repository path not found: docs/LOGIC_ARCHITECTURE.md |  |
| `repo_paths` | `docs/logic/BEST_PRACTICES.md` | 650 | Referenced repository path not found: docs/LOGIC_API_REFERENCE.md |  |
| `repo_paths` | `docs/logic/CEC/CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` | 414 | Referenced repository path not found: vocabularies/german.py |  |
| `repo_paths` | `docs/logic/CEC/CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` | 415 | Referenced repository path not found: vocabularies/french.py |  |
| `repo_paths` | `docs/logic/CEC/CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` | 416 | Referenced repository path not found: vocabularies/spanish.py |  |
| `repo_paths` | `docs/logic/CEC/CEC_SYSTEM_GUIDE.md` | 620 | Referenced repository path not found: ipfs_datasets_py/logic/CEC/MIGRATION_GUIDE.md |  |
| `repo_paths` | `docs/logic/CEC/CEC_SYSTEM_GUIDE.md` | 621 | Referenced repository path not found: ipfs_datasets_py/logic/CEC/PHASE4_TUTORIAL.md |  |
| `repo_paths` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 524 | Referenced repository path not found: .pre-commit-config.yaml |  |
| `repo_paths` | `docs/logic/CEC/STATUS.md` | 246 | Referenced repository path not found: inference_rules/modal.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v10.md` | 66 | Referenced repository path not found: tools/logic_tools/delegation_audit_tool.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v11.md` | 89 | Referenced repository path not found: tools/logic_tools/delegation_audit_tool.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v12.md` | 90 | Referenced repository path not found: tools/logic_tools/delegation_audit_tool.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md` | 164 | Referenced repository path not found: strategies/modal_tableaux.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md` | 181 | Referenced repository path not found: tests/unit_tests/logic/TDFOL/strategies/test_modal_tableaux_session_v13.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md` | 226 | Referenced repository path not found: TDFOL/nl/tdfol_nl_preprocessor.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md` | 239 | Referenced repository path not found: TDFOL/strategies/modal_tableaux.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md` | 240 | Referenced repository path not found: CEC/nl/grammar_nl_policy_compiler.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md` | 241 | Referenced repository path not found: zkp/ucan_zkp_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v3.md` | 225 | Referenced repository path not found: TDFOL/security_validator.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v3.md` | 237 | Referenced repository path not found: TDFOL/performance_dashboard.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v3.md` | 346 | Referenced repository path not found: zkp/ucan_zkp_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v4.md` | 105 | Referenced repository path not found: zkp/ucan_zkp_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 32 | Referenced repository path not found: CEC/nl/nl_to_policy_compiler.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 37 | Referenced repository path not found: zkp/ucan_zkp_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 38 | Referenced repository path not found: zkp/backends/groth16.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 38 | Referenced repository path not found: zkp/backends/groth16_ffi.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 58 | Referenced repository path not found: strategies/modal_tableaux.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 59 | Referenced repository path not found: strategies/strategy_selector.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 60 | Referenced repository path not found: strategies/cec_delegate.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 61 | Referenced repository path not found: strategies/forward_chaining.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 62 | Referenced repository path not found: TDFOL/security_validator.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 109 | Referenced repository path not found: integration/cec_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 112 | Referenced repository path not found: TDFOL/strategies/cec_delegate.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 114 | Referenced repository path not found: CEC/nl/tdfol_nl_preprocessor.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v5.md` | 115 | Referenced repository path not found: integration/proof_cache.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 33 | Referenced repository path not found: CEC/nl/nl_to_policy_compiler.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 39 | Referenced repository path not found: zkp/ucan_zkp_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 40 | Referenced repository path not found: zkp/backends/groth16.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 40 | Referenced repository path not found: zkp/backends/groth16_ffi.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 62 | Referenced repository path not found: strategies/modal_tableaux.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 63 | Referenced repository path not found: strategies/strategy_selector.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 64 | Referenced repository path not found: TDFOL/security_validator.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 65 | Referenced repository path not found: integration/cec_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 66 | Referenced repository path not found: CEC/nl/french_parser.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 67 | Referenced repository path not found: CEC/nl/spanish_parser.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 68 | Referenced repository path not found: CEC/nl/german_parser.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 69 | Referenced repository path not found: CEC/nl/language_detector.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v6.md` | 195 | Referenced repository path not found: strategies/cec_delegate.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v7.md` | 35 | Referenced repository path not found: CEC/nl/nl_to_policy_compiler.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v7.md` | 41 | Referenced repository path not found: CEC/nl/nl_policy_conflict_detector.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v7.md` | 42 | Referenced repository path not found: zkp/ucan_zkp_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v7.md` | 43 | Referenced repository path not found: zkp/backends/groth16.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v7.md` | 43 | Referenced repository path not found: zkp/backends/groth16_ffi.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v9.md` | 15 | Referenced repository path not found: zkp/ucan_zkp_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v9.md` | 30 | Referenced repository path not found: CEC/nl/nl_policy_conflict_detector.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v9.md` | 31 | Referenced repository path not found: CEC/nl/grammar_nl_policy_compiler.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v9.md` | 32 | Referenced repository path not found: CEC/nl/french_parser.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v9.md` | 33 | Referenced repository path not found: CEC/nl/spanish_parser.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v9.md` | 34 | Referenced repository path not found: CEC/nl/german_parser.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v9.md` | 35 | Referenced repository path not found: integration/ucan_policy_bridge.py |  |
| `repo_paths` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v9.md` | 45 | Referenced repository path not found: tools/logic_tools/delegation_audit_tool.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 20 | Referenced repository path not found: tests/fixtures/legal_parser/ |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 21 | Referenced repository path not found: tests/unit_tests/logic/deontic/test_deontic_parser_snapshots.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 178 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/slot_extraction.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 180 | Referenced repository path not found: tests/fixtures/legal_parser/enumerations.json |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 270 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/schema.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 271 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/patterns.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 283 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/segmentation.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 284 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/context.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 294 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/quality.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 295 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/repair.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 415 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/reconstruction_metrics.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 417 | Referenced repository path not found: tests/unit_tests/logic/deontic/test_deontic_reconstruction_metrics.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 470 | Referenced repository path not found: tests/fixtures/legal_parser/reconstruction_roundtrip.json |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPLEMENTATION_PLAN.md` | 471 | Referenced repository path not found: tests/unit_tests/logic/deontic/test_deontic_reconstruction_fixtures.py |  |
| `repo_paths` | `docs/logic/DETERMINISTIC_LEGAL_PARSER_IMPROVEMENT_PLAN.md` | 169 | Referenced repository path not found: tests/fixtures/legal_parser/ |  |
| `repo_paths` | `docs/logic/FEATURES.md` | 81 | Referenced repository path not found: integration/proof_cache.py |  |
| `repo_paths` | `docs/logic/FEATURES.md` | 82 | Referenced repository path not found: integration/ipfs_proof_cache.py |  |
| `repo_paths` | `docs/logic/FEATURES.md` | 83 | Referenced repository path not found: TDFOL/tdfol_proof_cache.py |  |
| `repo_paths` | `docs/logic/FEATURES.md` | 84 | Referenced repository path not found: external_provers/proof_cache.py |  |
| `repo_paths` | `docs/logic/FEATURES.md` | 350 | Referenced repository path not found: fol/utils/nlp_predicate_extractor.py |  |
| `repo_paths` | `docs/logic/FEATURES.md` | 351 | Referenced repository path not found: fol/text_to_fol.py |  |
| `repo_paths` | `docs/logic/FEATURES.md` | 426 | Referenced repository path not found: integration/ipld_logic_storage.py |  |
| `repo_paths` | `docs/logic/FEATURES.md` | 524 | Referenced repository path not found: external_provers/monitoring.py |  |
| `repo_paths` | `docs/logic/INTEGRATION_GUIDE.md` | 700 | Referenced repository path not found: docs/LOGIC_TROUBLESHOOTING.md |  |
| `repo_paths` | `docs/logic/KNOWN_LIMITATIONS.md` | 312 | Referenced repository path not found: integration/bridges/base_prover_bridge.py |  |
| `repo_paths` | `docs/logic/KNOWN_LIMITATIONS.md` | 335 | Referenced repository path not found: security/rate_limiting.py |  |
| `repo_paths` | `docs/logic/KNOWN_LIMITATIONS.md` | 336 | Referenced repository path not found: security/input_validation.py |  |
| `repo_paths` | `docs/logic/LEGAL_PARSER_DAEMON_SUPERVISOR_ARCHITECTURE.md` | 15 | Referenced repository path not found: .daemon/legal_parser_daemon_ensure.status.json |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 7 | Referenced repository path not found: docs/IPFS_DATASETS_LOGIC_TYPESCRIPT_PORT_PLAN.md |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 8 | Referenced repository path not found: docs/LOGIC_PORT_PARITY.md |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 86 | Referenced repository path not found: ipfs_datasets_py/.daemon/logic-port-daemon-supervisor.pid |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 87 | Referenced repository path not found: ipfs_datasets_py/.daemon/logic-port-daemon.pid |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 88 | Referenced repository path not found: ipfs_datasets_py/.daemon/logic-port-daemon-supervisor.lock |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 89 | Referenced repository path not found: ipfs_datasets_py/.daemon/logic-port-daemon-supervisor.status.json |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 90 | Referenced repository path not found: ipfs_datasets_py/.daemon/logic-port-daemon-supervisor.latest.log |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 91 | Referenced repository path not found: ipfs_datasets_py/.daemon/logic-port-daemon-ensure.status.json |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 95 | Referenced repository path not found: ppd/daemon/ppd_supervisor.py |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 95 | Referenced repository path not found: ppd/daemon/ppd_daemon.py |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 140 | Referenced repository path not found: ipfs_datasets_py/.daemon/failed-patches/ |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 165 | Referenced repository path not found: ipfs_datasets_py/.daemon/logic-port-daemon.status.json |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 171 | Referenced repository path not found: ipfs_datasets_py/.daemon/logic-port-daemon.progress.json |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 223 | Referenced repository path not found: docs/IPFS_DATASETS_LOGIC_PORT_DAEMON_ACCEPTED.md |  |
| `repo_paths` | `docs/logic/LOGIC_PORT_DAEMON.md` | 227 | Referenced repository path not found: ipfs_datasets_py/.daemon/accepted-work/ |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 85 | Referenced repository path not found: CEC/native/prover_core.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 86 | Referenced repository path not found: CEC/native/dcec_core.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 87 | Referenced repository path not found: integration/reasoning/proof_execution_engine.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 88 | Referenced repository path not found: integration/interactive/interactive_fol_constructor.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 89 | Referenced repository path not found: integration/reasoning/deontological_reasoning.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 90 | Referenced repository path not found: integration/reasoning/logic_verification.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 91 | Referenced repository path not found: TDFOL/performance_profiler.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 92 | Referenced repository path not found: TDFOL/performance_dashboard.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 98 | Referenced repository path not found: tests/logic/TDFOL/ |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 99 | Referenced repository path not found: tests/logic/CEC/native/ |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 101 | Referenced repository path not found: tests/logic/common/ |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 102 | Referenced repository path not found: tests/logic/deontic/ |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 103 | Referenced repository path not found: tests/logic/fol/ |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 104 | Referenced repository path not found: tests/logic/zkp/ |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 288 | Referenced repository path not found: native/NATIVE_REFACTORING_PLAN_2026.md |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 289 | Referenced repository path not found: native/NATIVE_REFACTORING_QUICK_GUIDE.md |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 389 | Referenced repository path not found: TDFOL/nl/tdfol_nl_patterns.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 400 | Referenced repository path not found: CEC/native/grammar_rules.yaml |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 491 | Referenced repository path not found: CEC/nl/french_parser.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 494 | Referenced repository path not found: CEC/nl/spanish_parser.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 554 | Referenced repository path not found: common/__init__.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 716 | Referenced repository path not found: converters/deontic_logic_core.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 717 | Referenced repository path not found: converters/logic_translation_core.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 718 | Referenced repository path not found: domain/deontic_query_engine.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 719 | Referenced repository path not found: caching/ipfs_proof_cache.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 720 | Referenced repository path not found: converters/modal_logic_extension.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 728 | Referenced repository path not found: converters/deontic_logic_converter.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 729 | Referenced repository path not found: domain/document_consistency_checker.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 730 | Referenced repository path not found: domain/legal_domain_knowledge.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 731 | Referenced repository path not found: interactive/interactive_fol_constructor.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 732 | Referenced repository path not found: reasoning/deontological_reasoning_utils.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 742 | Referenced repository path not found: reasoning/proof_execution_engine.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 743 | Referenced repository path not found: domain/temporal_deontic_api.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 744 | Referenced repository path not found: domain/legal_symbolic_analyzer.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 745 | Referenced repository path not found: symbolic/neurosymbolic/embedding_prover.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 746 | Referenced repository path not found: symbolic/neurosymbolic/hybrid_confidence.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 747 | Referenced repository path not found: symbolic/neurosymbolic/reasoning_coordinator.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 748 | Referenced repository path not found: interactive/interactive_fol_utils.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 749 | Referenced repository path not found: reasoning/proof_execution_engine_utils.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 750 | Referenced repository path not found: reasoning/proof_execution_engine_types.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 757 | Referenced repository path not found: reasoning/_prover_backend_mixin.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 758 | Referenced repository path not found: symbolic/neurosymbolic_api.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 759 | Referenced repository path not found: domain/symbolic_contracts.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 760 | Referenced repository path not found: caching/ipld_logic_storage.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 767 | Referenced repository path not found: reasoning/_logic_verifier_backends_mixin.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 769 | Referenced repository path not found: reasoning/deontological_reasoning.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 770 | Referenced repository path not found: reasoning/_deontic_conflict_mixin.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 771 | Referenced repository path not found: domain/medical_theorem_framework.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 772 | Referenced repository path not found: reasoning/logic_verification.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 773 | Referenced repository path not found: reasoning/logic_verification_utils.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 776 | Referenced repository path not found: symbolic/symbolic_logic_primitives.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 790 | Referenced repository path not found: bridges/tdfol_cec_bridge.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 791 | Referenced repository path not found: domain/caselaw_bulk_processor.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 814 | Referenced repository path not found: CEC/nl/german_parser.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 815 | Referenced repository path not found: CEC/nl/language_detector.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 829 | Referenced repository path not found: CEC/provers/tptp_utils.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 830 | Referenced repository path not found: CEC/provers/__init__.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 831 | Referenced repository path not found: integration/cec_bridge.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 840 | Referenced repository path not found: integration/proof_cache.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 843 | Referenced repository path not found: integration/logic_verification_utils.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 844 | Referenced repository path not found: integration/interactive_fol_constructor.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 859 | Referenced repository path not found: TDFOL/tdfol_inference_rules.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 860 | Referenced repository path not found: integration/CEC/native/dcec_core.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 861 | Referenced repository path not found: integration/CEC/native/propositional.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 862 | Referenced repository path not found: integration/CEC/native/temporal.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 863 | Referenced repository path not found: integration/CEC/native/deontic.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 864 | Referenced repository path not found: integration/domain/symbolic_contracts.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 872 | Referenced repository path not found: CEC/native/dcec_integration.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 873 | Referenced repository path not found: CEC/native/cec_proof_cache.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 875 | Referenced repository path not found: TDFOL/strategies/forward_chaining.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 876 | Referenced repository path not found: TDFOL/tdfol_prover.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 900 | Referenced repository path not found: p2p/ipfs_proof_storage.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 901 | Referenced repository path not found: nl/tdfol_nl_generator.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 901 | Referenced repository path not found: nl/llm.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 901 | Referenced repository path not found: nl/tdfol_nl_api.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 902 | Referenced repository path not found: strategies/strategy_selector.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 902 | Referenced repository path not found: strategies/cec_delegate.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 902 | Referenced repository path not found: strategies/modal_tableaux.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 903 | Referenced repository path not found: CEC/native/proof_optimization.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 904 | Referenced repository path not found: strategies/__init__.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 904 | Referenced repository path not found: CEC/native/proof_strategies.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 905 | Referenced repository path not found: CEC/nl/base_parser.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 905 | Referenced repository path not found: CEC/native/nl_converter.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 906 | Referenced repository path not found: CEC/nl/domain_vocabularies/domain_vocab.py |  |
| `repo_paths` | `docs/logic/MASTER_REFACTORING_PLAN_2026.md` | 906 | Referenced repository path not found: TDFOL/strategies/cec_delegate.py |  |
| `repo_paths` | `docs/logic/NL_UCAN_POLICY_COMPILER_PLAN.md` | 358 | Referenced repository path not found: mcp_server/ADR-006-mcp++-alignment.md |  |
| `repo_paths` | `docs/logic/PROJECT_STATUS.md` | 44 | Referenced repository path not found: strategies/modal_tableaux.py |  |
| `repo_paths` | `docs/logic/PROJECT_STATUS.md` | 45 | Referenced repository path not found: strategies/cec_delegate.py |  |
| `repo_paths` | `docs/logic/PROJECT_STATUS.md` | 46 | Referenced repository path not found: strategies/strategy_selector.py |  |
| `repo_paths` | `docs/logic/README.md` | 19 | Referenced repository path not found: ../../ipfs_datasets_py/logic/DOCUMENTATION_INDEX.md |  |
| `repo_paths` | `docs/logic/README.md` | 20 | Referenced repository path not found: ../../ipfs_datasets_py/logic/ARCHITECTURE.md |  |
| `repo_paths` | `docs/logic/README.md` | 21 | Referenced repository path not found: ../../ipfs_datasets_py/logic/FEATURES.md |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 138 | Referenced repository path not found: tests/unit_tests/logic/TDFOL/nl/test_generation_pipeline.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 153 | Referenced repository path not found: tests/unit_tests/logic/TDFOL/nl/test_parsing_pipeline.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 172 | Referenced repository path not found: tests/unit_tests/logic/TDFOL/test_proof_tree_viz.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 182 | Referenced repository path not found: tests/unit_tests/logic/TDFOL/test_countermodel_viz.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 195 | Referenced repository path not found: tests/unit_tests/logic/TDFOL/test_integration_workflows.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 256 | Referenced repository path not found: inference_rules/propositional.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 257 | Referenced repository path not found: inference_rules/first_order.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 258 | Referenced repository path not found: inference_rules/temporal.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 259 | Referenced repository path not found: inference_rules/deontic.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 260 | Referenced repository path not found: inference_rules/temporal_deontic.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 327 | Referenced repository path not found: examples/basic_proving.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 333 | Referenced repository path not found: examples/nl_conversion.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 339 | Referenced repository path not found: examples/visualization.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 345 | Referenced repository path not found: examples/distributed_proving.py |  |
| `repo_paths` | `docs/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md` | 351 | Referenced repository path not found: examples/custom_strategy.py |  |
| `repo_paths` | `docs/logic/TDFOL/QUICK_REFERENCE.md` | 597 | Referenced repository path not found: .github/workflows/ |  |
| `repo_paths` | `docs/logic/TDFOL/STATUS_2026.md` | 481 | Referenced repository path not found: p2p/ipfs_proof_storage.py |  |
| `repo_paths` | `docs/logic/TDFOL/ZKP_INTEGRATION_STRATEGY.md` | 180 | Referenced repository path not found: TDFOL/zkp_integration.py |  |
| `repo_paths` | `docs/logic/TDFOL/performance_profiler_README.md` | 595 | Referenced repository path not found: docs/TDFOL/ |  |
| `repo_paths` | `docs/logic/UNIFIED_CONVERTER_GUIDE.md` | 11 | Referenced repository path not found: common/converters.py |  |
| `repo_paths` | `docs/logic/UNIFIED_CONVERTER_GUIDE.md` | 20 | Referenced repository path not found: fol/converter.py |  |
| `repo_paths` | `docs/logic/UNIFIED_CONVERTER_GUIDE.md` | 25 | Referenced repository path not found: deontic/converter.py |  |
| `repo_paths` | `docs/logic/USAGE_EXAMPLES.md` | 628 | Referenced repository path not found: docs/architecture.md |  |
| `repo_paths` | `docs/logic/USAGE_EXAMPLES.md` | 629 | Referenced repository path not found: docs/best_practices.md |  |
| `repo_paths` | `docs/logic/USAGE_EXAMPLES.md` | 630 | Referenced repository path not found: docs/troubleshooting.md |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 13 | Referenced repository path not found: CEC/native/dcec_integration.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 18 | Referenced repository path not found: CEC/native/dcec_core.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 21 | Referenced repository path not found: CEC/native/cec_proof_cache.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 23 | Referenced repository path not found: TDFOL/strategies/forward_chaining.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 24 | Referenced repository path not found: TDFOL/tdfol_prover.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 32 | Referenced repository path not found: TDFOL/tdfol_inference_rules.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 34 | Referenced repository path not found: integration/domain/symbolic_contracts.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 37 | Referenced repository path not found: CEC/provers/tptp_utils.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 38 | Referenced repository path not found: CEC/provers/__init__.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 39 | Referenced repository path not found: integration/cec_bridge.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 41 | Referenced repository path not found: integration/proof_cache.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 42 | Referenced repository path not found: integration/reasoning/logic_verification.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 43 | Referenced repository path not found: integration/logic_verification_utils.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 43 | Referenced repository path not found: integration/interactive_fol_constructor.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 51 | Referenced repository path not found: CEC/native/inference_rules/temporal.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 52 | Referenced repository path not found: CEC/native/inference_rules/cognitive.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 52 | Referenced repository path not found: CEC/native/dcec_types.py |  |
| `repo_paths` | `docs/logic/integration/CHANGELOG.md` | 53 | Referenced repository path not found: CEC/native/inference_rules/propositional.py |  |
| `repo_paths` | `docs/logic/integration/TODO.md` | 27 | Referenced repository path not found: CEC/native/dcec_core.py |  |
| `repo_paths` | `docs/logic/integration/TODO.md` | 28 | Referenced repository path not found: converters/logic_translation_core.py |  |
| `repo_paths` | `docs/logic/integration/TODO.md` | 29 | Referenced repository path not found: reasoning/proof_execution_engine_types.py |  |
| `repo_paths` | `docs/logic/integration/TODO.md` | 60 | Referenced repository path not found: strategies/modal_tableaux.py |  |
| `repo_paths` | `docs/logic/integration/TODO.md` | 61 | Referenced repository path not found: strategies/cec_delegate.py |  |
| `repo_paths` | `docs/logic/integration/TODO.md` | 62 | Referenced repository path not found: strategies/strategy_selector.py |  |
| `repo_paths` | `docs/logic/integration/TODO.md` | 65 | Referenced repository path not found: CEC/proof_strategies.py |  |
| `repo_paths` | `docs/logic/integration/TODO.md` | 66 | Referenced repository path not found: CEC/nl/tdfol_nl_preprocessor.py |  |
| `repo_paths` | `docs/logic/itp_hammer_capability_inventory.md` | 6 | Referenced repository path not found: data/logic/itp_hammer/environment.json |  |
| `repo_paths` | `docs/logic/itp_hammer_capability_inventory.md` | 130 | Referenced repository path not found: .../security_models/crypto_exchange/compilers/to_z3.py |  |
| `repo_paths` | `docs/logic/itp_hammer_capability_inventory.md` | 131 | Referenced repository path not found: .../security_models/crypto_exchange/runners/cvc5_runner.py |  |
| `repo_paths` | `docs/logic/itp_hammer_failure_policy.md` | 184 | Referenced repository path not found: reconstructors/lean.py |  |
| `repo_paths` | `docs/logic/itp_hammer_failure_policy.md` | 193 | Referenced repository path not found: reconstructors/isabelle.py |  |
| `repo_paths` | `docs/logic/itp_hammer_provenance.md` | 11 | Referenced repository path not found: docs/logic/itp_hammer_translation.md |  |
| `repo_paths` | `docs/logic/itp_hammer_receipts.md` | 171 | Referenced repository path not found: <root_dir>/index.json |  |
| `repo_paths` | `docs/logic/itp_hammer_security_model.md` | 135 | Referenced repository path not found: data/logic/itp_hammer/release-evidence.json |  |
| `repo_paths` | `docs/logic/itp_hammer_security_model.md` | 147 | Referenced repository path not found: data/logic/itp_hammer/environment.json |  |
| `repo_paths` | `docs/logic/itp_hammer_user_guide.md` | 261 | Referenced repository path not found: data/logic/itp_hammer/golden-report.json |  |
| `repo_paths` | `docs/logic/logic_API_REFERENCE.md` | 36 | Referenced repository path not found: deontic/__init__.py |  |
| `repo_paths` | `docs/logic/logic_ARCHITECTURE.md` | 89 | Referenced repository path not found: TDFOL/zkp_integration.py |  |
| `repo_paths` | `docs/logic/logic_ARCHITECTURE.md` | 90 | Referenced repository path not found: CEC/native/cec_zkp_integration.py |  |
| `repo_paths` | `docs/logic/logic_ARCHITECTURE.md` | 91 | Referenced repository path not found: flogic/flogic_zkp_integration.py |  |
| `repo_paths` | `docs/logic/zkp/EXAMPLES.md` | 15 | Referenced repository path not found: examples/zkp_basic_demo.py |  |
| `repo_paths` | `docs/logic/zkp/EXAMPLES.md` | 49 | Referenced repository path not found: examples/zkp_advanced_demo.py |  |
| `repo_paths` | `docs/logic/zkp/EXAMPLES.md` | 65 | Referenced repository path not found: examples/zkp_ipfs_integration.py |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 22 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/ |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 23 | Referenced repository path not found: ./groth16_backend/ |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 24 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/target/release/groth16 |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 61 | Referenced repository path not found: backends/groth16.py |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 85 | Referenced repository path not found: backends/__init__.py |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 86 | Referenced repository path not found: backends/backend_protocol.py |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 121 | Referenced repository path not found: backends/simulated.py |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 274 | Referenced repository path not found: logic/zkp/LEGAL_THEOREM_SEMANTICS.md |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 282 | Referenced repository path not found: logic/zkp/THREAT_MODEL.md |  |
| `repo_paths` | `docs/logic/zkp/TODO_MASTER.md` | 330 | Referenced repository path not found: logic/zkp/SETUP_GUIDE.md |  |
| `repo_paths` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 195 | Referenced repository path not found: media_tools/__init__.py |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 149 | Referenced repository path not found: docs/DOCUMENTATION_PLAN.md |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 150 | Referenced repository path not found: docs/adr/ |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 153 | Referenced repository path not found: docs/development/ |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 155 | Referenced repository path not found: docs/history/ |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 156 | Referenced repository path not found: docs/testing/ |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 157 | Referenced repository path not found: docs/tools/README.md |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 165 | Referenced repository path not found: compat/README.md |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 167 | Referenced repository path not found: tools/TOOLS_IMPROVEMENT_PLAN_2026.md |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 204 | Referenced repository path not found: docs/architecture/dual-runtime.md |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 248 | Referenced repository path not found: optimizers/common\|graphrag\|logic_theorem_optimizer/README.md |  |
| `repo_paths` | `docs/maintenance/PACKAGE_LOCAL_DOCUMENTATION_MAP.md` | 269 | Referenced repository path not found: provekit_backend/README.md |  |
| `repo_paths` | `docs/maintenance/SOURCE_AUTHORITY.md` | 110 | Referenced repository path not found: .github/ |  |
| `repo_paths` | `docs/modules/file_converter/README.md` | 198 | Referenced repository path not found: backends/native_backend.py |  |
| `repo_paths` | `docs/modules/file_converter/README.md` | 200 | Referenced repository path not found: tests/test_file_converter.py |  |
| `repo_paths` | `docs/optimizers/AGENTIC_KWARGS_AUDIT.md` | 12 | Referenced repository path not found: agentic/methods/actor_critic.py |  |
| `repo_paths` | `docs/optimizers/AGENTIC_KWARGS_AUDIT.md` | 22 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/optimizers/agentic/methods/actor_critic.py |  |
| `repo_paths` | `docs/optimizers/AGENTIC_KWARGS_AUDIT.md` | 26 | Referenced repository path not found: ipfs_datasets_py/tests/unit/optimizers/agentic/test_actor_critic.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 38 | Referenced repository path not found: graphrag/ontology_generator.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 231 | Referenced repository path not found: common/base_optimizer.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 370 | Referenced repository path not found: agentic/llm_integration.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 371 | Referenced repository path not found: common/llm_integration.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 376 | Referenced repository path not found: common/base_critic.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 381 | Referenced repository path not found: common/base_session.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 465 | Referenced repository path not found: common/prompt_templates.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 474 | Referenced repository path not found: graphrag/visualization.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 479 | Referenced repository path not found: logic_theorem_optimizer/distributed_processor.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 674 | Referenced repository path not found: graphrag/ontology_harness.py |  |
| `repo_paths` | `docs/optimizers/ARCHITECTURE_UNIFIED.md` | 682 | Referenced repository path not found: agentic/validation.py |  |
| `repo_paths` | `docs/optimizers/CLI_PATH_VALIDATION_AUDIT.md` | 45 | Referenced repository path not found: tests/test_batch_265_path_validation_security.py |  |
| `repo_paths` | `docs/optimizers/COMPREHENSIVE_REFACTOR_PLAN.md` | 366 | Referenced repository path not found: graphrag/query_optimizer.py |  |
| `repo_paths` | `docs/optimizers/COMPREHENSIVE_REFACTOR_PLAN.md` | 367 | Referenced repository path not found: graphrag/query_unified_optimizer.py |  |
| `repo_paths` | `docs/optimizers/COMPREHENSIVE_REFACTOR_PLAN.md` | 368 | Referenced repository path not found: graphrag/ontology_generator.py |  |
| `repo_paths` | `docs/optimizers/COMPREHENSIVE_REFACTOR_PLAN.md` | 369 | Referenced repository path not found: graphrag/ontology_critic.py |  |
| `repo_paths` | `docs/optimizers/COMPREHENSIVE_REFACTOR_PLAN.md` | 370 | Referenced repository path not found: graphrag/ontology_mediator.py |  |
| `repo_paths` | `docs/optimizers/COMPREHENSIVE_REFACTOR_PLAN.md` | 373 | Referenced repository path not found: common/base_optimizer.py |  |
| `repo_paths` | `docs/optimizers/COMPREHENSIVE_REFACTOR_PLAN.md` | 374 | Referenced repository path not found: common/query_validation.py |  |
| `repo_paths` | `docs/optimizers/COMPREHENSIVE_REFACTOR_PLAN.md` | 375 | Referenced repository path not found: common/caching_layer.py |  |
| `repo_paths` | `docs/optimizers/CONTRIBUTING.md` | 19 | Referenced repository path not found: ipfs_datasets_py/optimizers/TODO.md |  |
| `repo_paths` | `docs/optimizers/CONTRIBUTING.md` | 22 | Referenced repository path not found: ipfs_datasets_py/optimizers/CHANGELOG.md |  |
| `repo_paths` | `docs/optimizers/CONTRIBUTING.md` | 36 | Referenced repository path not found: tests/unit/optimizers/.../test_batch_<N>_<topic>.py |  |
| `repo_paths` | `docs/optimizers/CREDENTIAL_REDACTION_AUDIT_REPORT.md` | 108 | Referenced repository path not found: common/log_redaction.py |  |
| `repo_paths` | `docs/optimizers/CREDENTIAL_REDACTION_AUDIT_REPORT.md` | 123 | Referenced repository path not found: common/structured_logging.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 15 | Referenced repository path not found: common/base_optimizer.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 35 | Referenced repository path not found: common/performance.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 56 | Referenced repository path not found: graphrag/ontology_critic.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 76 | Referenced repository path not found: agentic/validation.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 98 | Referenced repository path not found: agentic/methods/chaos.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 121 | Referenced repository path not found: agentic/methods/actor_critic.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 143 | Referenced repository path not found: agentic/methods/adversarial.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 157 | Referenced repository path not found: logic_theorem_optimizer/additional_provers.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 177 | Referenced repository path not found: logic_theorem_optimizer/unified_optimizer.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_USAGE_AUDIT.md` | 25 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/semantic_deduplicator_cached.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_USAGE_AUDIT.md` | 27 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/validation_cache.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_USAGE_AUDIT.md` | 30 | Referenced repository path not found: ipfs_datasets_py/tests/unit/optimizers/graphrag/test_validation_cache.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_USAGE_AUDIT.md` | 33 | Referenced repository path not found: ipfs_datasets_py/tests/unit/optimizers/graphrag/test_semantic_entity_deduplication.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_USAGE_AUDIT.md` | 38 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag/semantic_deduplicator.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_USAGE_AUDIT.md` | 43 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/optimizers/common/exceptions.py |  |
| `repo_paths` | `docs/optimizers/EXCEPTION_USAGE_AUDIT.md` | 45 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/optimizers/graphrag_repl.py |  |
| `repo_paths` | `docs/optimizers/GITHUB_INTEGRATION.md` | 5 | Referenced repository path not found: .github/ |  |
| `repo_paths` | `docs/optimizers/GITHUB_INTEGRATION.md` | 10 | Referenced repository path not found: .github/scripts/github_api_counter.py |  |
| `repo_paths` | `docs/optimizers/GITHUB_INTEGRATION.md` | 12 | Referenced repository path not found: .github/scripts/ |  |
| `repo_paths` | `docs/optimizers/GITHUB_INTEGRATION.md` | 55 | Referenced repository path not found: .github/cache-config.yml |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 9 | Referenced repository path not found: ipfs_datasets_py/optimizers/<your_optimizer>/ |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 22 | Referenced repository path not found: common/base_optimizer.py |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 38 | Referenced repository path not found: common/base_critic.py |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 39 | Referenced repository path not found: common/base_session.py |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 40 | Referenced repository path not found: common/base_harness.py |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 41 | Referenced repository path not found: common/exceptions.py |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 42 | Referenced repository path not found: common/backend_selection.py |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 43 | Referenced repository path not found: common/metrics_prometheus.py |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 66 | Referenced repository path not found: tests/unit/optimizers/<your_optimizer>/ |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 86 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/optimizers/README.md |  |
| `repo_paths` | `docs/optimizers/HOW_TO_ADD_NEW_OPTIMIZER.md` | 87 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/optimizers/TODO.md |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 15 | Referenced repository path not found: agentic/base.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 26 | Referenced repository path not found: agentic/patch_control.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 35 | Referenced repository path not found: agentic/github_control.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 44 | Referenced repository path not found: agentic/coordinator.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 58 | Referenced repository path not found: agentic/methods/test_driven.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 76 | Referenced repository path not found: agentic/methods/adversarial.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 94 | Referenced repository path not found: agentic/methods/actor_critic.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 112 | Referenced repository path not found: agentic/methods/chaos.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 129 | Referenced repository path not found: agentic/llm_integration.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 147 | Referenced repository path not found: agentic/validation.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 168 | Referenced repository path not found: agentic/cli.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 196 | Referenced repository path not found: agentic/dashboard.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 233 | Referenced repository path not found: tests/chaos/test_optimizer_resilience.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 284 | Referenced repository path not found: .github/workflows/agentic-optimization.yml |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_PLAN.md` | 302 | Referenced repository path not found: .github/workflows/approve-optimization.yml |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_SUMMARY.md` | 12 | Referenced repository path not found: agentic/base.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_SUMMARY.md` | 24 | Referenced repository path not found: agentic/patch_control.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_SUMMARY.md` | 38 | Referenced repository path not found: agentic/github_control.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_SUMMARY.md` | 53 | Referenced repository path not found: agentic/coordinator.py |  |
| `repo_paths` | `docs/optimizers/IMPLEMENTATION_SUMMARY.md` | 69 | Referenced repository path not found: agentic/methods/test_driven.py |  |
| `repo_paths` | `docs/optimizers/IMPROVEMENT_SESSION_2026_02_24.md` | 46 | Referenced repository path not found: common/exceptions.py |  |
| `repo_paths` | `docs/optimizers/INFINITE_TODO_SESSION_2026_02_24.md` | 99 | Referenced repository path not found: optimizers/tests/typecheck/mypy_public_imports_smoke.py |  |
| `repo_paths` | `docs/optimizers/INFINITE_TODO_SESSION_2026_02_24.md` | 126 | Referenced repository path not found: common/exceptions.py |  |
| `repo_paths` | `docs/optimizers/INFINITE_TODO_SESSION_2026_02_24.md` | 164 | Referenced repository path not found: ipfs_datasets_py/tests/unit/optimizers/conftest.py |  |
| `repo_paths` | `docs/optimizers/PHASES_3_6_8_IMPLEMENTATION_SUMMARY.md` | 156 | Referenced repository path not found: .github/workflows/agentic-optimization.yml |  |
| `repo_paths` | `docs/optimizers/PHASES_3_6_8_IMPLEMENTATION_SUMMARY.md` | 188 | Referenced repository path not found: .github/workflows/approve-optimization.yml |  |
| `repo_paths` | `docs/optimizers/QUERY_OPTIMIZER_BASELINE_REPORT.md` | 144 | Referenced repository path not found: graphrag/query_unified_optimizer.py |  |
| `repo_paths` | `docs/optimizers/QUERY_OPTIMIZER_MODULARIZATION_PLAN.md` | 6 | Referenced repository path not found: graphrag/query_unified_optimizer.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 90 | Referenced repository path not found: graphrag/ontology_pipeline.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 99 | Referenced repository path not found: graphrag/query_optimizer.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 99 | Referenced repository path not found: graphrag/traversal_heuristics.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 213 | Referenced repository path not found: graphrag/cli_wrapper.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 331 | Referenced repository path not found: optimizers/common/llm_integration.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 331 | Referenced repository path not found: agentic/llm_integration.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 372 | Referenced repository path not found: graphrag/logic_validator.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 381 | Referenced repository path not found: graphrag/ontology_generator.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 391 | Referenced repository path not found: graphrag/ontology_optimizer.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 397 | Referenced repository path not found: graphrag/ontology_critic.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 414 | Referenced repository path not found: logic_theorem_optimizer/cli_wrapper.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 434 | Referenced repository path not found: tests/unit/optimizers/agentic/test_cli_argparse_smoke.py::test_argparse_cli_config_show_masks_tokens |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 444 | Referenced repository path not found: graphrag/query_planner.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 446 | Referenced repository path not found: graphrag/learning_adapter.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 447 | Referenced repository path not found: graphrag/serialization.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 467 | Referenced repository path not found: common/base_optimizer.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 468 | Referenced repository path not found: common/base_critic.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 469 | Referenced repository path not found: common/base_session.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 471 | Referenced repository path not found: common/base_harness.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 495 | Referenced repository path not found: graphrag/ontology_mediator.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 514 | Referenced repository path not found: logic_theorem_optimizer/__init__.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 594 | Referenced repository path not found: logic_theorem_optimizer/logic_repl.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 646 | Referenced repository path not found: tests/performance/optimizers/test_optimizer_benchmarks.py::TestExtractEntitiesBenchmarks::test_extract_entities_10k_tokens |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 648 | Referenced repository path not found: tests/performance/optimizers/test_optimizer_benchmarks.py::TestLogicValidatorBenchmarks::test_validate_ontology_100_entities |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 730 | Referenced repository path not found: common/README.md |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 765 | Referenced repository path not found: tests/performance/optimizers/test_optimizer_benchmarks.py::TestOntologyMergeBenchmarks::test_merge_ontologies_1000_entities |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 845 | Referenced repository path not found: tests/unit/optimizers/graphrag/test_ontology_generator_doctest_conformance.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 2476 | Referenced repository path not found: common/optimizer_config.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 2502 | Referenced repository path not found: tests/properties/test_entity_properties.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 2530 | Referenced repository path not found: common/logging_audit.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 2555 | Referenced repository path not found: tests/performance/profile_generate.py |  |
| `repo_paths` | `docs/optimizers/TODO.md` | 2580 | Referenced repository path not found: common/exception_audit.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 133 | Referenced repository path not found: processors/graphrag/ |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 605 | Referenced repository path not found: tests/test_ontology_generator.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 606 | Referenced repository path not found: tests/test_ontology_critic.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 607 | Referenced repository path not found: tests/test_ontology_mediator.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 608 | Referenced repository path not found: tests/test_logic_validator.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 609 | Referenced repository path not found: tests/test_ontology_optimizer.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 610 | Referenced repository path not found: tests/test_ontology_session.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 611 | Referenced repository path not found: tests/test_ontology_harness.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 620 | Referenced repository path not found: examples/basic_ontology_generation.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 621 | Referenced repository path not found: examples/sgd_optimization_cycle.py |  |
| `repo_paths` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 622 | Referenced repository path not found: examples/legal_ontology_example.py |  |
| `repo_paths` | `docs/profiling/INFER_RELATIONSHIPS_PERFORMANCE_ANALYSIS.md` | 366 | Referenced repository path not found: ipfs_datasets_py/tests/unit/optimizers/graphrag/test_infer_relationships_performance.py |  |
| `repo_paths` | `docs/rag_optimizer/learning_metrics_implementation.md` | 97 | Referenced repository path not found: test/simulate_rag_optimizer_learning.py |  |
| `repo_paths` | `docs/reorganization/DEEP_REORGANIZATION.md` | 144 | Referenced repository path not found: processors/graphrag/website_system.py |  |
| `repo_paths` | `docs/reorganization/DEEP_REORGANIZATION.md` | 145 | Referenced repository path not found: processors/graphrag/complete_advanced_graphrag.py |  |
| `repo_paths` | `docs/reorganization/DEEP_REORGANIZATION.md` | 146 | Referenced repository path not found: examples/graphrag_website_example.py |  |
| `repo_paths` | `docs/reorganization/DEEP_REORGANIZATION.md` | 447 | Referenced repository path not found: ../REORGANIZATION_SUMMARY.md |  |
| `repo_paths` | `docs/reorganization/DEEP_REORGANIZATION.md` | 449 | Referenced repository path not found: ../FINAL_VALIDATION_REPORT.md |  |
| `repo_paths` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 33 | Referenced repository path not found: ipfs_datasets_py/integrations/ |  |
| `repo_paths` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 211 | Referenced repository path not found: integrations/__init__.py |  |
| `repo_paths` | `docs/reports/ADHOC_TOOLS_REFACTORING.md` | 51 | Referenced repository path not found: .github/workflows/README-documentation-maintenance.md |  |
| `repo_paths` | `docs/reports/ADHOC_TOOLS_REFACTORING.md` | 52 | Referenced repository path not found: docs/CLAUDE.md |  |
| `repo_paths` | `docs/reports/COMPLETION_REPORT.md` | 49 | Referenced repository path not found: ipfs_datasets_py/data_processing/processor.py |  |
| `repo_paths` | `docs/reports/COMPLETION_REPORT.md` | 94 | Referenced repository path not found: ipfs_datasets_py/storage/manager.py |  |
| `repo_paths` | `docs/reports/COMPLETION_REPORT.md` | 142 | Referenced repository path not found: ipfs_datasets_py/workflow_engine/ |  |
| `repo_paths` | `docs/reports/COMPLETION_REPORT.md` | 182 | Referenced repository path not found: ipfs_datasets_py/ipfs_client/gateway.py |  |
| `repo_paths` | `docs/reports/COMPLETION_REPORT.md` | 193 | Referenced repository path not found: ipfs_datasets_py/dataset_management/ |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 52 | Referenced repository path not found: docs/misc_markdown/GPU_RUNNER_SETUP.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 61 | Referenced repository path not found: migration_docs/MIGRATION_VERIFICATION_REPORT.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 95 | Referenced repository path not found: docs/FILE_CONVERSION_INTEGRATION.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 96 | Referenced repository path not found: ../ipfs_datasets_py/multimedia/README.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 122 | Referenced repository path not found: ../ipfs_datasets_py/logic_integration/README.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 149 | Referenced repository path not found: implementation_plans/README.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 150 | Referenced repository path not found: implementation_plans/file_conversion_integration_plan.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 151 | Referenced repository path not found: implementation_plans/NOTIMPLEMENTEDERROR_IMPLEMENTATION_PLAN.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 152 | Referenced repository path not found: implementation_plans/symbolicai_fol_integration_plan.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 153 | Referenced repository path not found: implementation_plans/file_converter_complete_summary.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 162 | Referenced repository path not found: misc_markdown/FINANCE_DASHBOARD_IMPLEMENTATION_SUMMARY.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 163 | Referenced repository path not found: misc_markdown/DOCKER_DEPENDENCY_INTEGRATION.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 164 | Referenced repository path not found: misc_markdown/RUNNER_AND_DASHBOARD_VALIDATION.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 165 | Referenced repository path not found: misc_markdown/FINANCE_DASHBOARD_QUICK_START.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 166 | Referenced repository path not found: misc_markdown/simple_mcp_test_summary.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 167 | Referenced repository path not found: misc_markdown/COPILOT_AUTO_FIX_IMPLEMENTATION.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 168 | Referenced repository path not found: misc_markdown/FINAL_IMPLEMENTATION_SUMMARY.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 169 | Referenced repository path not found: misc_markdown/DEPRECATED_SCRIPTS.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 170 | Referenced repository path not found: misc_markdown/IMPLEMENTATION_COMPLETE_SUMMARY.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 182 | Referenced repository path not found: implementation/ACCELERATE_INTEGRATION_COMPLETE.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 190 | Referenced repository path not found: misc_markdown/GPU_RUNNER_SETUP.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 218 | Referenced repository path not found: implementation_plans/p2p_cache_system.md |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 457 | Referenced repository path not found: docs/archive/completed_2024/ |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 457 | Referenced repository path not found: docs/archive/completed_2025/ |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 471 | Referenced repository path not found: guides/infrastructure/auto_healing/ |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 472 | Referenced repository path not found: guides/dashboards/ |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 473 | Referenced repository path not found: guides/domain_specific/ |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 475 | Referenced repository path not found: guides/monitoring/ |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 477 | Referenced repository path not found: archive/completed_202X/ |  |
| `repo_paths` | `docs/reports/COMPREHENSIVE_DOCS_AUDIT_2026_01_31.md` | 599 | Referenced repository path not found: docs/HEALTH.md |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_AUDIT_RESPONSE_2026_01_31.md` | 54 | Referenced repository path not found: migration_docs/MIGRATION_VERIFICATION_REPORT.md |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_AUDIT_RESPONSE_2026_01_31.md` | 57 | Referenced repository path not found: misc_markdown/GPU_RUNNER_SETUP.md |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_AUDIT_RESPONSE_2026_01_31.md` | 95 | Referenced repository path not found: implementation_plans/README.md |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_AUDIT_RESPONSE_2026_01_31.md` | 96 | Referenced repository path not found: implementation_plans/NOTIMPLEMENTEDERROR_IMPLEMENTATION_PLAN.md |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_AUDIT_RESPONSE_2026_01_31.md` | 97 | Referenced repository path not found: implementation_plans/symbolicai_fol_integration_plan.md |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_AUDIT_RESPONSE_2026_01_31.md` | 105 | Referenced repository path not found: misc_markdown/FINANCE_DASHBOARD_IMPLEMENTATION_SUMMARY.md |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_AUDIT_RESPONSE_2026_01_31.md` | 106 | Referenced repository path not found: misc_markdown/DOCKER_DEPENDENCY_INTEGRATION.md |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_AUDIT_RESPONSE_2026_01_31.md` | 107 | Referenced repository path not found: misc_markdown/COPILOT_AUTO_FIX_IMPLEMENTATION.md |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_REFACTORING_2026_01_31.md` | 46 | Referenced repository path not found: docs/implementation_plans/ |  |
| `repo_paths` | `docs/reports/DOCUMENTATION_REFACTORING_2026_01_31.md` | 133 | Referenced repository path not found: ipfs_datasets_py/file_converter/README.md |  |
| `repo_paths` | `docs/reports/ENHANCED_DASHBOARD_SUMMARY.md` | 112 | Referenced repository path not found: ipfs_datasets_py/news_analysis_dashboard.py |  |
| `repo_paths` | `docs/reports/FINAL_COMPLETE_SUMMARY.md` | 33 | Referenced repository path not found: ipfs_datasets_py/multimedia/ffmpeg_wrapper.py |  |
| `repo_paths` | `docs/reports/FINAL_VALIDATION_REPORT.md` | 125 | Referenced repository path not found: docs/ROOT_REORGANIZATION.md |  |
| `repo_paths` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 37 | Referenced repository path not found: ipfs_datasets_py/multimedia/ffmpeg_wrapper.py |  |
| `repo_paths` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 114 | Referenced repository path not found: ipfs_datasets_py/workflow_engine/ |  |
| `repo_paths` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 119 | Referenced repository path not found: ipfs_datasets_py/storage/manager.py |  |
| `repo_paths` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 126 | Referenced repository path not found: ipfs_datasets_py/data_processing/ |  |
| `repo_paths` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 130 | Referenced repository path not found: ipfs_datasets_py/ipfs_client/gateway.py |  |
| `repo_paths` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 134 | Referenced repository path not found: ipfs_datasets_py/dataset_management/ |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 161 | Referenced repository path not found: vector_tools/create_vector_index.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 162 | Referenced repository path not found: vector_tools/search_vector_index.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 177 | Referenced repository path not found: web_archive_tools/create_warc.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 178 | Referenced repository path not found: web_archive_tools/extract_dataset_from_cdxj.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 179 | Referenced repository path not found: web_archive_tools/extract_links_from_warc.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 180 | Referenced repository path not found: web_archive_tools/extract_metadata_from_warc.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 181 | Referenced repository path not found: web_archive_tools/extract_text_from_warc.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 182 | Referenced repository path not found: web_archive_tools/index_warc.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 204 | Referenced repository path not found: ipfs_tools/pin_to_ipfs.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 205 | Referenced repository path not found: ipfs_tools/get_from_ipfs.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 232 | Referenced repository path not found: medical_research_scrapers/medical_research_mcp_tools.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 78 | Referenced repository path not found: ipfs_datasets_py/multimedia/ffmpeg_wrapper.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 91 | Referenced repository path not found: ipfs_datasets_py/workflow_engine/ |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 102 | Referenced repository path not found: ipfs_datasets_py/storage/manager.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 115 | Referenced repository path not found: ipfs_datasets_py/data_processing/processor.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 123 | Referenced repository path not found: ipfs_tools/get_from_ipfs.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 126 | Referenced repository path not found: ipfs_datasets_py/ipfs_client/gateway.py |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 141 | Referenced repository path not found: ipfs_datasets_py/dataset_management/ |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 172 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/analysis_tools/analysis_tools.py.backup |  |
| `repo_paths` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 173 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/analysis_tools/analysis_tools_old.py |  |
| `repo_paths` | `docs/reports/REORGANIZATION_SUMMARY.md` | 43 | Referenced repository path not found: docs/test_results/ |  |
| `repo_paths` | `docs/reports/REORGANIZATION_SUMMARY.md` | 98 | Referenced repository path not found: docs/ROOT_REORGANIZATION.md |  |
| `repo_paths` | `docs/reports/ROOT_REORGANIZATION_2026_02_16.md` | 84 | Referenced repository path not found: ../../OPTIMIZER_FRAMEWORK_IMPROVEMENTS.md |  |
| `repo_paths` | `docs/reports/ROOT_REORGANIZATION_2026_02_16.md` | 85 | Referenced repository path not found: ../../OPTIMIZER_IMPROVEMENTS_QUICKSTART.md |  |
| `repo_paths` | `docs/reports/WEB_SCRAPING_REFACTORING_SUMMARY.md` | 16 | Referenced repository path not found: ipfs_datasets_py/web_text_extractor.py |  |
| `repo_paths` | `docs/reports/WEB_SCRAPING_REFACTORING_SUMMARY.md` | 17 | Referenced repository path not found: ipfs_datasets_py/simple_crawler.py |  |
| `repo_paths` | `docs/reports/WEB_SCRAPING_REFACTORING_SUMMARY.md` | 18 | Referenced repository path not found: ipfs_datasets_py/web_archive_utils.py |  |
| `repo_paths` | `docs/reports/WEB_SCRAPING_REFACTORING_SUMMARY.md` | 22 | Referenced repository path not found: ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/state_scrapers/base_scraper.py |  |
| `repo_paths` | `docs/reports/WEB_SCRAPING_REFACTORING_SUMMARY.md` | 34 | Referenced repository path not found: ipfs_datasets_py/unified_web_scraper.py |  |
| `repo_paths` | `docs/reports/WEB_SCRAPING_REFACTORING_SUMMARY.md` | 121 | Referenced repository path not found: ipfs_datasets_py/scraper_cli.py |  |
| `repo_paths` | `docs/reports/WORKFLOW_IMPROVEMENTS_SUMMARY.md` | 68 | Referenced repository path not found: docs/P2P_CACHE_SYSTEM.md |  |
| `repo_paths` | `docs/reports/WORKFLOW_IMPROVEMENTS_SUMMARY.md` | 98 | Referenced repository path not found: .github/workflows/setup-p2p-cache.yml |  |
| `repo_paths` | `docs/reports/auto_healing_implementation_summary.md` | 15 | Referenced repository path not found: .github/workflows/comprehensive-scraper-validation.yml |  |
| `repo_paths` | `docs/reports/auto_healing_implementation_summary.md` | 52 | Referenced repository path not found: .github/workflows/copilot-agent-autofix.yml |  |
| `repo_paths` | `docs/reports/caching_implementation_summary.md` | 170 | Referenced repository path not found: docs/CLI_CACHING_GUIDE.md |  |
| `repo_paths` | `docs/reports/caching_implementation_summary.md` | 205 | Referenced repository path not found: examples/cli_caching_demo.py |  |
| `repo_paths` | `docs/reports/cicd_setup_complete.md` | 69 | Referenced repository path not found: .github/workflows/ |  |
| `repo_paths` | `docs/reports/cicd_setup_complete.md` | 103 | Referenced repository path not found: ./cicd_help.sh |  |
| `repo_paths` | `docs/reports/cicd_setup_complete.md` | 109 | Referenced repository path not found: docs/RUNNER_SETUP.md |  |
| `repo_paths` | `docs/reports/cicd_setup_complete.md` | 127 | Referenced repository path not found: ./setup_cicd_runner.sh |  |
| `repo_paths` | `docs/reports/cicd_setup_complete.md` | 146 | Referenced repository path not found: ./test_cicd_runner.sh |  |
| `repo_paths` | `docs/reports/cicd_setup_summary.md` | 55 | Referenced repository path not found: docs/RUNNER_SETUP.md |  |
| `repo_paths` | `docs/reports/cicd_setup_summary.md` | 107 | Referenced repository path not found: .github/workflows/ |  |
| `repo_paths` | `docs/reports/cicd_setup_summary.md` | 332 | Referenced repository path not found: ./setup_cicd_runner.sh |  |
| `repo_paths` | `docs/reports/cicd_setup_summary.md` | 333 | Referenced repository path not found: ./test_cicd_runner.sh |  |
| `repo_paths` | `docs/reports/cli_tools_implementation_summary.md` | 43 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/github_cli_tools.py |  |
| `repo_paths` | `docs/reports/cli_tools_implementation_summary.md` | 50 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/gemini_cli_tools.py |  |
| `repo_paths` | `docs/reports/cli_tools_implementation_summary.md` | 56 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/tools/claude_cli_tools.py |  |
| `repo_paths` | `docs/reports/cli_tools_implementation_summary.md` | 85 | Referenced repository path not found: examples/cli_tools_as_data_sources.py |  |
| `repo_paths` | `docs/reports/complete_implementation_summary.md` | 60 | Referenced repository path not found: ipfs_accelerate_py/github_cli/cache.py |  |
| `repo_paths` | `docs/reports/complete_setup_summary.md` | 52 | Referenced repository path not found: .github/workflows/docker-build-test.yml |  |
| `repo_paths` | `docs/reports/complete_setup_summary.md` | 59 | Referenced repository path not found: .github/workflows/gpu-tests.yml |  |
| `repo_paths` | `docs/reports/complete_setup_summary.md` | 168 | Referenced repository path not found: .github/workflows/docker-ci.yml |  |
| `repo_paths` | `docs/reports/complete_setup_summary.md` | 169 | Referenced repository path not found: .github/workflows/self-hosted-runner.yml |  |
| `repo_paths` | `docs/reports/complete_setup_summary.md` | 188 | Referenced repository path not found: docs/RUNNER_SETUP.md |  |
| `repo_paths` | `docs/reports/completion_summary.md` | 38 | Referenced repository path not found: .github/workflows/copilot-agent-autofix.yml |  |
| `repo_paths` | `docs/reports/completion_summary.md` | 43 | Referenced repository path not found: .github/scripts/analyze_workflow_failure.py |  |
| `repo_paths` | `docs/reports/completion_summary.md` | 48 | Referenced repository path not found: .github/scripts/generate_workflow_fix.py |  |
| `repo_paths` | `docs/reports/completion_summary.md` | 53 | Referenced repository path not found: .github/scripts/apply_workflow_fix.py |  |
| `repo_paths` | `docs/reports/completion_summary.md` | 60 | Referenced repository path not found: .github/scripts/test_autohealing_system.py |  |
| `repo_paths` | `docs/reports/completion_summary.md` | 70 | Referenced repository path not found: .github/workflows/VALIDATION_REPORT.md |  |
| `repo_paths` | `docs/reports/completion_summary.md` | 75 | Referenced repository path not found: .github/workflows/QUICKSTART.md |  |
| `repo_paths` | `docs/reports/copilot_queue_implementation_summary.md` | 30 | Referenced repository path not found: ipfs_datasets_py/mcp_dashboard.py |  |
| `repo_paths` | `docs/reports/discord_integration_summary.md` | 212 | Referenced repository path not found: examples/discord_alerts_demo.py |  |
| `repo_paths` | `docs/reports/discord_integration_summary.md` | 260 | Referenced repository path not found: docs/DISCORD_ALERTS_GUIDE.md |  |
| `repo_paths` | `docs/reports/docker_permission_complete_solution.md` | 71 | Referenced repository path not found: .github/workflows/fix-docker-permissions.yml |  |
| `repo_paths` | `docs/reports/docker_permission_fix_summary.md` | 15 | Referenced repository path not found: docs/DOCKER_PERMISSION_FIX.md |  |
| `repo_paths` | `docs/reports/docker_permission_fix_summary.md` | 16 | Referenced repository path not found: docs/DOCKER_PERMISSION_INFRASTRUCTURE_SOLUTIONS.md |  |
| `repo_paths` | `docs/reports/docker_permission_fix_summary.md` | 17 | Referenced repository path not found: docs/RUNNER_SETUP.md |  |
| `repo_paths` | `docs/reports/docker_permission_fix_summary.md` | 28 | Referenced repository path not found: .github/workflows/fix-docker-permissions.yml |  |
| `repo_paths` | `docs/reports/fallback_methods_summary.md` | 348 | Referenced repository path not found: docs/MUNICIPAL_CODES_TOOL_GUIDE.md |  |
| `repo_paths` | `docs/reports/final_cleanup_summary.md` | 22 | Referenced repository path not found: archive/migration_tests/ |  |
| `repo_paths` | `docs/reports/final_cleanup_summary.md` | 25 | Referenced repository path not found: archive/test/ |  |
| `repo_paths` | `docs/reports/final_cleanup_summary.md` | 26 | Referenced repository path not found: archive/test_results/ |  |
| `repo_paths` | `docs/reports/final_cleanup_summary.md` | 27 | Referenced repository path not found: archive/test_visualizations/ |  |
| `repo_paths` | `docs/reports/final_cleanup_summary.md` | 28 | Referenced repository path not found: archive/testing_archive/ |  |
| `repo_paths` | `docs/reports/final_cleanup_summary.md` | 50 | Referenced repository path not found: .github/ |  |
| `repo_paths` | `docs/reports/final_cleanup_summary.md` | 50 | Referenced repository path not found: .gitignore |  |
| `repo_paths` | `docs/reports/final_implementation_summary.md` | 60 | Referenced repository path not found: docs/copilot_auto_fix_all_prs.md |  |
| `repo_paths` | `docs/reports/final_implementation_summary.md` | 83 | Referenced repository path not found: examples/copilot_auto_fix_example.py |  |
| `repo_paths` | `docs/reports/final_verification_100_percent.md` | 144 | Referenced repository path not found: backends/ipfs_backend.py |  |
| `repo_paths` | `docs/reports/final_verification_100_percent.md` | 189 | Referenced repository path not found: embeddings/core.py |  |
| `repo_paths` | `docs/reports/final_verification_100_percent.md` | 190 | Referenced repository path not found: embeddings/chunker.py |  |
| `repo_paths` | `docs/reports/final_verification_100_percent.md` | 196 | Referenced repository path not found: pdf_processing/llm_optimizer.py |  |
| `repo_paths` | `docs/reports/final_verification_100_percent.md` | 197 | Referenced repository path not found: rag/rag_query_optimizer.py |  |
| `repo_paths` | `docs/reports/finance_dashboard_implementation_summary.md` | 389 | Referenced repository path not found: logic_integration/README.md |  |
| `repo_paths` | `docs/reports/followup_implementation_summary.md` | 21 | Referenced repository path not found: .github/workflows/arm64-runner.yml |  |
| `repo_paths` | `docs/reports/followup_implementation_summary.md` | 22 | Referenced repository path not found: docs/ARM64_RUNNER_SETUP.md |  |
| `repo_paths` | `docs/reports/followup_implementation_summary.md` | 42 | Referenced repository path not found: .github/workflows/gpu-tests.yml |  |
| `repo_paths` | `docs/reports/followup_implementation_summary.md` | 43 | Referenced repository path not found: docs/GPU_RUNNER_SETUP.md |  |
| `repo_paths` | `docs/reports/followup_implementation_summary.md` | 64 | Referenced repository path not found: .github/workflows/mcp-dashboard-tests.yml |  |
| `repo_paths` | `docs/reports/followup_implementation_summary.md` | 88 | Referenced repository path not found: .github/workflows/mcp-integration-tests.yml |  |
| `repo_paths` | `docs/reports/github_actions_fix_summary.md` | 185 | Referenced repository path not found: .github/workflows/pdf_processing_ci.yml |  |
| `repo_paths` | `docs/reports/gpu_setup_complete.md` | 10 | Referenced repository path not found: .github/workflows/gpu-tests.yml |  |
| `repo_paths` | `docs/reports/implementation_complete.md` | 302 | Referenced repository path not found: examples/error_reporting_example.py |  |
| `repo_paths` | `docs/reports/integration_progress_summary.md` | 64 | Referenced repository path not found: embeddings/core.py |  |
| `repo_paths` | `docs/reports/integration_progress_summary.md` | 110 | Referenced repository path not found: embeddings/chunker.py |  |
| `repo_paths` | `docs/reports/integration_progress_summary.md` | 116 | Referenced repository path not found: pdf_processing/llm_optimizer.py |  |
| `repo_paths` | `docs/reports/integration_progress_summary.md` | 117 | Referenced repository path not found: rag/rag_query_optimizer.py |  |
| `repo_paths` | `docs/reports/phase_8_complete_multimedia.md` | 104 | Referenced repository path not found: backends/ipfs_backend.py |  |
| `repo_paths` | `docs/security_verification/apalache_tla_solver_lane.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json |  |
| `repo_paths` | `docs/security_verification/apalache_tla_solver_lane.md` | 15 | Referenced repository path not found: security_ir_artifacts/environment/apalache-solver-lane-report.json |  |
| `repo_paths` | `docs/security_verification/appended_task_retention_runbook.md` | 57 | Referenced repository path not found: security_ir_artifacts/recovery/appended-task-retention-report.json |  |
| `repo_paths` | `docs/security_verification/code_to_ir_evidence_matrix.md` | 30 | Referenced repository path not found: ir/schema.py |  |
| `repo_paths` | `docs/security_verification/code_to_ir_evidence_matrix.md` | 82 | Referenced repository path not found: src/common/libs/vault.ts |  |
| `repo_paths` | `docs/security_verification/coq_proof_kernel_solver_lane.md` | 12 | Referenced repository path not found: security_ir_artifacts/environment/coq-solver-lane-report.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_recovery_report.md` | 21 | Referenced repository path not found: security_ir_artifacts/recovery/crypto-exchange-source-audit.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_security_plan.todo.md` | 274 | Referenced repository path not found: security_ir_artifacts/assurance-run/assurance-baseline.md |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_security_plan.todo.md` | 275 | Referenced repository path not found: security_ir_artifacts/assurance-run/proof-baseline.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_security_plan.todo.md` | 276 | Referenced repository path not found: security_ir_artifacts/assurance-run/disproof-baseline.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 777 | Referenced repository path not found: data/crypto_exchange_theorem_prover/state/cxtp_task_state.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1224 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/endpoint-rebound-candidate.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1236 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/daemon-health.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1236 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/bridge-isolation-report.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1260 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/runtime-trace-review.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1260 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/runtime-conformance-report.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1272 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/runtime-trace-template.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1284 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/protocol/resolution-protocol-report.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1296 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/independent-review-packet.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1320 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/native-vault-public-source-assessment.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1336 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/native-vault-rekey-fault-injection-report.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1344 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/counterexample-triage.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1356 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/native-vault/fault-injection-plan.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1368 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/native-vault-android-host-preflight.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1380 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/native-vault/rekey-state-fuzz-report.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1392 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/native-vault-ios-host-preflight.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1404 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/native-vault-ios-host-preflight-blocker.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1416 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/gap-remediation-matrix.json |  |
| `repo_paths` | `docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md` | 1428 | Referenced repository path not found: security_ir_artifacts/environment/optional-solver-install-report.json |  |
| `repo_paths` | `docs/security_verification/cxtp_taskboard_state_reconciliation.md` | 13 | Referenced repository path not found: data/crypto_exchange_theorem_prover/state/cxtp_task_state.json |  |
| `repo_paths` | `docs/security_verification/cxtp_taskboard_state_reconciliation.md` | 14 | Referenced repository path not found: security_ir_artifacts/recovery/cxtp-taskboard-state-reconciliation.json |  |
| `repo_paths` | `docs/security_verification/evidence_promotion_workflow.md` | 19 | Referenced repository path not found: security_ir_artifacts/assurance-run/evidence-review-template.json |  |
| `repo_paths` | `docs/security_verification/independent_prover_backend_promotion.md` | 30 | Referenced repository path not found: runners/cvc5_runner.py |  |
| `repo_paths` | `docs/security_verification/lean_proof_consumer_solver_lane.md` | 10 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json |  |
| `repo_paths` | `docs/security_verification/lean_proof_consumer_solver_lane.md` | 12 | Referenced repository path not found: security_ir_artifacts/environment/lean-solver-lane-report.json |  |
| `repo_paths` | `docs/security_verification/optional_solver_installation.md` | 7 | Referenced repository path not found: security_ir_artifacts/environment/optional-solver-install-report.json |  |
| `repo_paths` | `docs/security_verification/production_blocker_evidence_packets.md` | 10 | Referenced repository path not found: security_ir_artifacts/production/blocker-evidence-packets.json |  |
| `repo_paths` | `docs/security_verification/production_blocker_evidence_packets.md` | 11 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json |  |
| `repo_paths` | `docs/security_verification/production_blocker_status_updater.md` | 7 | Referenced repository path not found: security_ir_artifacts/production/blocker-evidence-packets.json |  |
| `repo_paths` | `docs/security_verification/production_blocker_status_updater.md` | 8 | Referenced repository path not found: security_ir_artifacts/production/evidence-bundle-report.json |  |
| `repo_paths` | `docs/security_verification/production_blocker_status_updater.md` | 9 | Referenced repository path not found: security_ir_artifacts/production/evidence-bundle.json |  |
| `repo_paths` | `docs/security_verification/production_blocker_status_updater.md` | 13 | Referenced repository path not found: security_ir_artifacts/production/blocker-status-update-report.json |  |
| `repo_paths` | `docs/security_verification/production_environment_profile.md` | 38 | Referenced repository path not found: security_ir_artifacts/production/assumption-evidence.json |  |
| `repo_paths` | `docs/security_verification/production_evidence_generation_plan.md` | 40 | Referenced repository path not found: security_ir_artifacts/production/evidence-bundle.json |  |
| `repo_paths` | `docs/security_verification/production_evidence_generation_plan.md` | 190 | Referenced repository path not found: security_ir_artifacts/production/security-model-ir.json |  |
| `repo_paths` | `docs/security_verification/production_release_decision_policy.md` | 5 | Referenced repository path not found: security_ir_artifacts/policies/security-decision-policy.json |  |
| `repo_paths` | `docs/security_verification/proof_receipt_consumer_policy.md` | 126 | Referenced repository path not found: security_ir_artifacts/assurance-run/security-ir-schema.ts |  |
| `repo_paths` | `docs/security_verification/protocol_solver_lanes.md` | 11 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json |  |
| `repo_paths` | `docs/security_verification/protocol_solver_lanes.md` | 13 | Referenced repository path not found: security_ir_artifacts/environment/protocol-solver-lane-report.json |  |
| `repo_paths` | `docs/security_verification/release_gate_runbook.md` | 13 | Referenced repository path not found: security_ir_artifacts/production/production-security-model.json |  |
| `repo_paths` | `docs/security_verification/release_gate_runbook.md` | 15 | Referenced repository path not found: security_ir_artifacts/production/assumption-evidence.json |  |
| `repo_paths` | `docs/security_verification/release_gate_runbook.md` | 16 | Referenced repository path not found: security_ir_artifacts/production/accepted-assumptions.json |  |
| `repo_paths` | `docs/security_verification/release_gate_runbook.md` | 17 | Referenced repository path not found: security_ir_artifacts/production/evidence-review.json |  |
| `repo_paths` | `docs/security_verification/release_gate_runbook.md` | 53 | Referenced repository path not found: security_ir_artifacts/assurance-run/assurance-baseline.md |  |
| `repo_paths` | `docs/security_verification/release_gate_runbook.md` | 124 | Referenced repository path not found: security_ir_artifacts/production-baseline/proof-baseline.json |  |
| `repo_paths` | `docs/security_verification/release_gate_runbook.md` | 125 | Referenced repository path not found: security_ir_artifacts/production-baseline/disproof-baseline.json |  |
| `repo_paths` | `docs/security_verification/release_gate_runbook.md` | 126 | Referenced repository path not found: security_ir_artifacts/production-baseline/assurance-baseline.md |  |
| `repo_paths` | `docs/security_verification/release_gate_runbook.md` | 169 | Referenced repository path not found: .github/workflows/security-logic-ci.yml |  |
| `repo_paths` | `docs/security_verification/security_ir_v1_compatibility.md` | 214 | Referenced repository path not found: ir/schema.py |  |
| `repo_paths` | `docs/security_verification/security_ir_v1_compatibility.md` | 214 | Referenced repository path not found: runners/z3_runner.py |  |
| `repo_paths` | `docs/security_verification/supervisor_recovery_stability_runbook.md` | 21 | Referenced repository path not found: security_ir_artifacts/recovery/supervisor-stability-report.json |  |
| `repo_paths` | `docs/security_verification/taskboard_artifact_retention_policy.md` | 22 | Referenced repository path not found: security_ir_artifacts/recovery/artifact-retention-baseline.json |  |
| `repo_paths` | `docs/security_verification/taskboard_preflight_ci.md` | 22 | Referenced repository path not found: .github/workflows/crypto-exchange-security-verification.yml |  |
| `repo_paths` | `docs/security_verification/typescript_solver_dependency_remediation.md` | 35 | Referenced repository path not found: security_ir_artifacts/environment/solver-dependency-probe.json |  |
| `repo_paths` | `docs/security_verification/xaman_assurance_packet.md` | 9 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/assurance-packet.json |  |
| `repo_paths` | `docs/security_verification/xaman_corpus_profile.md` | 13 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_corpus_profile.md` | 34 | Referenced repository path not found: Makefile |  |
| `repo_paths` | `docs/security_verification/xaman_corpus_profile.md` | 41 | Referenced repository path not found: .gitignore |  |
| `repo_paths` | `docs/security_verification/xaman_corpus_profile.md` | 52 | Referenced repository path not found: ios/Podfile.lock |  |
| `repo_paths` | `docs/security_verification/xaman_corpus_profile.md` | 61 | Referenced repository path not found: android/app/src/main/assets/security.txt |  |
| `repo_paths` | `docs/security_verification/xaman_corpus_profile.md` | 62 | Referenced repository path not found: ios/security.txt |  |
| `repo_paths` | `docs/security_verification/xaman_counterexample_triage.md` | 6 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/counterexample-triage.json |  |
| `repo_paths` | `docs/security_verification/xaman_counterexample_triage.md` | 48 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/gap-remediation-matrix.json |  |
| `repo_paths` | `docs/security_verification/xaman_environment_assumptions.md` | 26 | Referenced repository path not found: ios/Podfile.lock |  |
| `repo_paths` | `docs/security_verification/xaman_firebase_disabled_testnet.md` | 96 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_native_vault_android_host_preflight.md` | 12 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/native-vault-android-host-preflight.json |  |
| `repo_paths` | `docs/security_verification/xaman_native_vault_ios_host_preflight.md` | 12 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/native-vault-ios-host-preflight.json |  |
| `repo_paths` | `docs/security_verification/xaman_native_vault_public_source_assessment.md` | 9 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/native-vault-public-source-assessment.json |  |
| `repo_paths` | `docs/security_verification/xaman_native_vault_rekey_fault_injection.md` | 15 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/native-vault/fault-injection-plan.json |  |
| `repo_paths` | `docs/security_verification/xaman_native_vault_rekey_fault_injection.md` | 16 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/native-vault-rekey-fault-injection-template.json |  |
| `repo_paths` | `docs/security_verification/xaman_opam_proof_toolchain.md` | 9 | Referenced repository path not found: security_ir_artifacts/environment/opam-proof-toolchain-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_payload_lifecycle_model.md` | 5 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json |  |
| `repo_paths` | `docs/security_verification/xaman_payload_lifecycle_model.md` | 12 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_payload_lifecycle_model.md` | 14 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-coverage.json |  |
| `repo_paths` | `docs/security_verification/xaman_payload_lifecycle_model.md` | 30 | Referenced repository path not found: src/common/libs/payload/object.ts |  |
| `repo_paths` | `docs/security_verification/xaman_payload_lifecycle_model.md` | 35 | Referenced repository path not found: src/common/libs/payload/types.ts |  |
| `repo_paths` | `docs/security_verification/xaman_payload_lifecycle_model.md` | 41 | Referenced repository path not found: src/services/LinkingService.ts |  |
| `repo_paths` | `docs/security_verification/xaman_payload_lifecycle_model.md` | 43 | Referenced repository path not found: src/services/PushNotificationsService.ts |  |
| `repo_paths` | `docs/security_verification/xaman_payload_lifecycle_model.md` | 86 | Referenced repository path not found: src/common/libs/ledger/types/methods/submit.ts |  |
| `repo_paths` | `docs/security_verification/xaman_proof_consumer_invariants.md` | 10 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_protocol_model.md` | 10 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_assessment_profile.md` | 5 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/public-source-assessment.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_assessment_profile.md` | 26 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_assessment_profile.md` | 27 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_assessment_profile.md` | 28 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_code_first_formal_analysis_plan.md` | 30 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/code-first/formalization-profile.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_testnet_assurance_verdict.md` | 11 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/public-source-testnet-assurance-bundle.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_testnet_assurance_verdict.md` | 13 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/public-source-testnet-assurance-verdict.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_testnet_assurance_verdict.md` | 37 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_testnet_assurance_verdict.md` | 38 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_testnet_assurance_verdict.md` | 39 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/public-source-assessment.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_testnet_assurance_verdict.md` | 40 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_testnet_assurance_verdict.md` | 41 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json |  |
| `repo_paths` | `docs/security_verification/xaman_public_source_testnet_assurance_verdict.md` | 43 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/public-build-reproduction.json |  |
| `repo_paths` | `docs/security_verification/xaman_release_decision.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/assurance-packet.json |  |
| `repo_paths` | `docs/security_verification/xaman_release_r8_dependency_analysis.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/release-r8-dependency-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_release_r8_dependency_analysis.md` | 9 | Referenced repository path not found: docs/211_SERVICE_NAVIGATION_PORTAL_PLAN.md |  |
| `repo_paths` | `docs/security_verification/xaman_runtime_trace_assumptions.md` | 5 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_runtime_trace_assumptions.md` | 25 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_runtime_trace_assumptions.md` | 26 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/environment-probe.json |  |
| `repo_paths` | `docs/security_verification/xaman_runtime_trace_assumptions.md` | 27 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json |  |
| `repo_paths` | `docs/security_verification/xaman_runtime_trace_assumptions.md` | 28 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json |  |
| `repo_paths` | `docs/security_verification/xaman_runtime_trace_assumptions.md` | 29 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json |  |
| `repo_paths` | `docs/security_verification/xaman_security_claims.md` | 5 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/security-claims.json |  |
| `repo_paths` | `docs/security_verification/xaman_security_model_ir.md` | 5 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/security-model-ir.json |  |
| `repo_paths` | `docs/security_verification/xaman_security_model_ir.md` | 13 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_self_hosted_endpoint_rebind_candidate.md` | 28 | Referenced repository path not found: src/common/constants/endpoints.ts |  |
| `repo_paths` | `docs/security_verification/xaman_self_hosted_endpoint_rebind_candidate.md` | 29 | Referenced repository path not found: src/common/constants/network.ts |  |
| `repo_paths` | `docs/security_verification/xaman_self_hosted_endpoint_rebind_candidate.md` | 30 | Referenced repository path not found: src/services/NetworkService.ts |  |
| `repo_paths` | `docs/security_verification/xaman_self_hosted_endpoint_rebind_candidate.md` | 39 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/endpoint-rebound-candidate.json |  |
| `repo_paths` | `docs/security_verification/xaman_self_hosted_testnet_prerequisites.md` | 130 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/daemon-health.json |  |
| `repo_paths` | `docs/security_verification/xaman_self_hosted_testnet_prerequisites.md` | 135 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/bridge-isolation-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_source_claim_coverage.md` | 13 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_source_claim_coverage.md` | 14 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-coverage.json |  |
| `repo_paths` | `docs/security_verification/xaman_source_claim_coverage.md` | 15 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-claim-map.json |  |
| `repo_paths` | `docs/security_verification/xaman_source_claim_coverage.md` | 16 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/native-boundary-coverage.json |  |
| `repo_paths` | `docs/security_verification/xaman_tamarin_runtime.md` | 9 | Referenced repository path not found: security_ir_artifacts/environment/tamarin-runtime-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_adversarial_fuzzing.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/fuzz/campaign-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_adversarial_fuzzing.md` | 8 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/fuzz/counterexamples/manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_adversarial_fuzzing.md` | 19 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_adversarial_fuzzing.md` | 21 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_adversarial_fuzzing.md` | 55 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_apalache.md` | 8 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/tla/apalache-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_device_trial.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_fuzzing.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_fuzzing.md` | 18 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_fuzzing.md` | 20 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_kernel_proofs.md` | 9 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/lean-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_kernel_proofs.md` | 10 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/coq-coverage-decision.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_leanstral_policy.md` | 12 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/leanstral-assistant-lock.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_leanstral_policy.md` | 13 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/leanstral-candidate-audit.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_model_review.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_model_review.md` | 9 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_model_review.md` | 10 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_model_review.md` | 20 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-lifecycle-evidence.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_model_review.md` | 21 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-trial-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_model_review.md` | 22 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_model_review.md` | 23 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_model_review.md` | 24 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_native_firebase_boundary.md` | 34 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_network_selection.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_protocol_verification.md` | 9 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/protocol/protocol-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_public_build_reproduction.md` | 11 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_public_build_reproduction.md` | 12 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/public-build-environment.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_public_build_reproduction.md` | 13 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/public-build-reproduction.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_conformance.md` | 9 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_conformance.md` | 10 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/runtime-conformance-trace-map.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_conformance.md` | 11 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_conformance.md` | 13 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_conformance.md` | 14 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-trial-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_mapping.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-monitor-mapping.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_mapping.md` | 26 | Referenced repository path not found: runtime/testnet-telemetry-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_mapping.md` | 27 | Referenced repository path not found: runtime/testnet-device-trial-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_mapping.md` | 28 | Referenced repository path not found: runtime/testnet-network-selection-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_runtime_mapping.md` | 29 | Referenced repository path not found: runtime/testnet-transaction-trial-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_smt_results.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/proof-reports/z3-cvc5-differential.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_smt_results.md` | 24 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/proof-worker-lock.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_smt_results.md` | 25 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/cvc5-runner-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_smt_worker.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/proof-worker-lock.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_smt_worker.md` | 8 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/cvc5-runner-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_smt_worker.md` | 17 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_solver_portfolio.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_solver_portfolio.md` | 8 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_solver_portfolio.md` | 22 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/proof-reports/z3-cvc5-differential.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_solver_portfolio.md` | 23 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/tla/apalache-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_solver_portfolio.md` | 24 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/protocol/protocol-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_solver_portfolio.md` | 26 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/lean-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_solver_portfolio.md` | 27 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/coq-coverage-decision.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_solver_portfolio.md` | 28 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_transaction_trial.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-trial-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_testnet_transaction_trial.md` | 11 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-lifecycle-evidence.json |  |
| `repo_paths` | `docs/security_verification/xaman_tla_workflow.md` | 16 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_tla_workflow.md` | 17 | Referenced repository path not found: security_ir_artifacts/environment/apalache-solver-lane-report.json |  |
| `repo_paths` | `docs/security_verification/xaman_to_production_blocker_bridge.md` | 9 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/production-blocker-bridge.json |  |
| `repo_paths` | `docs/security_verification/xaman_to_production_blocker_bridge.md` | 10 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/assurance-packet.json |  |
| `repo_paths` | `docs/security_verification/xaman_vendor_evidence_request.md` | 5 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/vendor-evidence-intake-template.json |  |
| `repo_paths` | `docs/security_verification/xaman_vendor_evidence_review.md` | 18 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/vendor-evidence-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_vendor_evidence_review.md` | 19 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/vendor-evidence-review-template.json |  |
| `repo_paths` | `docs/security_verification/xaman_vendor_evidence_review.md` | 31 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/vendor-evidence-review-verification.json |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 5 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 12 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-manifest.json |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 14 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/source-coverage.json |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 22 | Referenced repository path not found: src/store/repositories/account.ts |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 30 | Referenced repository path not found: src/store/models/objects/account.ts |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 30 | Referenced repository path not found: src/store/models/objects/accountDetails.ts |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 34 | Referenced repository path not found: src/common/libs/vault.ts |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 36 | Referenced repository path not found: src/store/storage.ts |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 40 | Referenced repository path not found: src/services/AuthenticationService.ts |  |
| `repo_paths` | `docs/security_verification/xaman_wallet_auth_model.md` | 54 | Referenced repository path not found: src/common/libs/ledger/mixin/Sign.mixin.ts |  |
| `repo_paths` | `docs/security_verification/xaman_xrpl_testnet_assurance_verdict.md` | 11 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/assurance-bundle.json |  |
| `repo_paths` | `docs/security_verification/xaman_xrpl_testnet_assurance_verdict.md` | 13 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/assurance-verdict.json |  |
| `repo_paths` | `docs/security_verification/xaman_xrpl_testnet_assurance_verdict.md` | 28 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json |  |
| `repo_paths` | `docs/security_verification/xaman_xrpl_transaction_model.md` | 7 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json |  |
| `repo_paths` | `docs/security_verification/xaman_xrpl_transaction_model.md` | 8 | Referenced repository path not found: security_ir_artifacts/corpora/xaman-app/xrpl-transaction-coverage.json |  |
| `repo_paths` | `docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md` | 210 | Referenced repository path not found: ./faiss_index |  |
| `repo_paths` | `docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md` | 210 | Referenced repository path not found: ./faiss_metadata |  |
| `repo_paths` | `docs/tutorials/security_tutorial.md` | 562 | Referenced repository path not found: examples/rag_audit_integration_example.py |  |
| `python_modules` | `docs/ARCHITECTURE_VALIDATION_QUICK_START.md` | 425 | Python module not found on tree: ipfs_datasets_py.module.class | origin=prose |
| `python_modules` | `docs/ARCHITECTURE_VALIDATION_REPORT.md` | 152 | Python module not found on tree: ipfs_datasets_py.graph | origin=import |
| `python_modules` | `docs/CHANGELOG.md` | 8 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=backtick |
| `python_modules` | `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | 476 | Python module not found on tree: ipfs_datasets_py.auth | origin=import |
| `python_modules` | `docs/DOCS_DRIFT_AUDIT_REPORT.md` | 92 | Python module not found on tree: ipfs_datasets_py.mcp_server.tools.admin_tools.system_health | origin=import |
| `python_modules` | `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | 66 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.unified_graphrag | origin=import |
| `python_modules` | `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | 455 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | 468 | Python module not found on tree: ipfs_datasets_py.processors.graphrag | origin=prose |
| `python_modules` | `docs/LEGAL_SCRAPERS_COMMON_CRAWL_GUIDE.md` | 438 | Python module not found on tree: ipfs_datasets_py.logic_integration | origin=import |
| `python_modules` | `docs/MCP_ARCHITECTURE_DIAGRAM.md` | 216 | Python module not found on tree: ipfs_datasets_py.datasets.loader.DatasetLoader | origin=prose |
| `python_modules` | `docs/MCP_ARCHITECTURE_DIAGRAM.md` | 230 | Python module not found on tree: ipfs_datasets_py.datasets.loader | origin=import |
| `python_modules` | `docs/MCP_ARCHITECTURE_DIAGRAM.md` | 323 | Python module not found on tree: ipfs_datasets_py.datasets | origin=import |
| `python_modules` | `docs/MCP_QUICKSTART.md` | 74 | Python module not found on tree: ipfs_datasets_py.your_module.your_logic.YourFeature | origin=prose |
| `python_modules` | `docs/MCP_QUICKSTART.md` | 87 | Python module not found on tree: ipfs_datasets_py.your_module.your_logic | origin=import |
| `python_modules` | `docs/MCP_QUICKSTART.md` | 183 | Python module not found on tree: ipfs_datasets_py.module | origin=import |
| `python_modules` | `docs/MCP_REFACTORING_PLAN.md` | 146 | Python module not found on tree: ipfs_datasets_py.datasets.loader.DatasetLoader | origin=prose |
| `python_modules` | `docs/MCP_REFACTORING_PLAN.md` | 148 | Python module not found on tree: ipfs_datasets_py.datasets.loader | origin=import |
| `python_modules` | `docs/MCP_REFACTORING_SUMMARY.md` | 167 | Python module not found on tree: ipfs_datasets_py.datasets | origin=import |
| `python_modules` | `docs/MCP_TOOLS_GUIDE.md` | 514 | Python module not found on tree: ipfs_datasets_py.mcp_server.tools.category.your_tool | origin=import |
| `python_modules` | `docs/MCP_TOOLS_GUIDE.md` | 541 | Python module not found on tree: ipfs_datasets_py.processors.module_name | origin=prose |
| `python_modules` | `docs/PERFORMANCE_TUNING_GUIDE.md` | 531 | Python module not found on tree: ipfs_datasets_py.optimizers.tests.performance.benchmarks.benchmark_datasets | origin=import |
| `python_modules` | `docs/PERFORMANCE_TUNING_GUIDE.md` | 534 | Python module not found on tree: ipfs_datasets_py.optimizers.tests.performance.benchmarks.benchmark_harness | origin=import |
| `python_modules` | `docs/QUICK_START_NEW_ARCHITECTURE.md` | 24 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/QUICK_START_NEW_ARCHITECTURE.md` | 79 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization | origin=import |
| `python_modules` | `docs/QUICK_START_NEW_ARCHITECTURE.md` | 97 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/QUICK_START_NEW_ARCHITECTURE.md` | 119 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/QUICK_START_NEW_ARCHITECTURE.md` | 129 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/QUICK_START_NEW_ARCHITECTURE.md` | 132 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=import |
| `python_modules` | `docs/THIRD_PARTY_INTEGRATION.md` | 16 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/analysis/complete_individual_scan_evidence.md` | 138 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=prose |
| `python_modules` | `docs/analysis/complete_individual_scan_evidence.md` | 139 | Python module not found on tree: ipfs_datasets_py.cache | origin=prose |
| `python_modules` | `docs/analysis/complete_individual_scan_evidence.md` | 140 | Python module not found on tree: ipfs_datasets_py.web_archive | origin=prose |
| `python_modules` | `docs/analysis/complete_individual_scan_evidence.md` | 141 | Python module not found on tree: ipfs_datasets_py.libp2p_kit | origin=prose |
| `python_modules` | `docs/analysis/complete_individual_scan_evidence.md` | 142 | Python module not found on tree: ipfs_datasets_py.discord_cli | origin=prose |
| `python_modules` | `docs/analysis/complete_individual_scan_evidence.md` | 143 | Python module not found on tree: ipfs_datasets_py.graphrag_integration | origin=prose |
| `python_modules` | `docs/analysis/complete_individual_scan_evidence.md` | 144 | Python module not found on tree: ipfs_datasets_py.p2p_peer_registry | origin=prose |
| `python_modules` | `docs/analysis/complete_native_implementation.md` | 355 | Python module not found on tree: ipfs_datasets_py.file_converter.cli | origin=prose |
| `python_modules` | `docs/analysis/logic_tools_verification.md` | 25 | Python module not found on tree: ipfs_datasets_py.mcp_server.tools.dataset_tools.__init__.py | origin=backtick |
| `python_modules` | `docs/api/domains/CORE_AND_DATA.md` | 434 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.dataset_serialization | origin=backtick |
| `python_modules` | `docs/api/domains/MCP_AND_RUNTIME.md` | 561 | Python module not found on tree: ipfs_datasets_py.config.py | origin=backtick |
| `python_modules` | `docs/architecture/DEPENDENCY_AND_INITIALIZATION.md` | 141 | Python module not found on tree: ipfs_datasets_py.initialize | origin=prose |
| `python_modules` | `docs/architecture/END_TO_END_DATA_FLOW.md` | 110 | Python module not found on tree: ipfs_datasets_py.core_operations.dataset_loader.DatasetLoader.load | origin=backtick |
| `python_modules` | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | 142 | Python module not found on tree: ipfs_datasets_py.vector_tools | origin=import |
| `python_modules` | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | 213 | Python module not found on tree: ipfs_datasets_py.logic_integration | origin=prose |
| `python_modules` | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | 225 | Python module not found on tree: ipfs_datasets_py.module | origin=prose |
| `python_modules` | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | 245 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=import |
| `python_modules` | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | 246 | Python module not found on tree: ipfs_datasets_py.graphrag | origin=import |
| `python_modules` | `docs/architecture/RUNTIME_ENTRYPOINTS.md` | 63 | Python module not found on tree: ipfs_datasets_py.initialize | origin=backtick |
| `python_modules` | `docs/architecture/RUNTIME_ENTRYPOINTS.md` | 64 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=backtick |
| `python_modules` | `docs/architecture/SYSTEM_CONTEXT.md` | 63 | Python module not found on tree: ipfs_datasets_py.initialize | origin=prose |
| `python_modules` | `docs/architecture/SYSTEM_CONTEXT.md` | 206 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=backtick |
| `python_modules` | `docs/architecture/github_actions_infrastructure.md` | 118 | Python module not found on tree: ipfs_datasets_py.codeql_cache | origin=import |
| `python_modules` | `docs/architecture/github_actions_infrastructure.md` | 154 | Python module not found on tree: ipfs_datasets_py.credential_manager | origin=import |
| `python_modules` | `docs/architecture/submodule_fix.md` | 47 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/deployment/DOCKER_DEPLOYMENT_GUIDE.md` | 22 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/developer_guide.md` | 108 | Python module not found on tree: ipfs_datasets_py.ipfs_kit | origin=prose |
| `python_modules` | `docs/developer_guides/TROUBLESHOOTING.md` | 119 | Python module not found on tree: ipfs_datasets_py.__file__ | origin=prose |
| `python_modules` | `docs/examples/README.md` | 41 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=import |
| `python_modules` | `docs/examples/README.md` | 42 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/examples/README.md` | 55 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 33 | Python module not found on tree: ipfs_datasets_py.data_integration | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 34 | Python module not found on tree: ipfs_datasets_py.duckdb_connector | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 91 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 98 | Python module not found on tree: ipfs_datasets_py.ipld | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 271 | Python module not found on tree: ipfs_datasets_py.ipld_storage | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 272 | Python module not found on tree: ipfs_datasets_py.ipfs_knn_index | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 273 | Python module not found on tree: ipfs_datasets_py.knowledge_graph | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 411 | Python module not found on tree: ipfs_datasets_py.llm.llm_graphrag | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 414 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 517 | Python module not found on tree: ipfs_datasets_py.federated_search | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 519 | Python module not found on tree: ipfs_datasets_py.resilient_operations | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 600 | Python module not found on tree: ipfs_datasets_py.llm.llm_reasoning_tracer | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 676 | Python module not found on tree: ipfs_datasets_py.arrow_ipld | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 677 | Python module not found on tree: ipfs_datasets_py.streaming | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 788 | Python module not found on tree: ipfs_datasets_py.distributed | origin=import |
| `python_modules` | `docs/examples/advanced_examples.md` | 910 | Python module not found on tree: ipfs_datasets_py.data_provenance | origin=import |
| `python_modules` | `docs/examples/discord_usage_examples.md` | 18 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia.discord_wrapper | origin=backtick |
| `python_modules` | `docs/examples/discord_usage_examples.md` | 21 | Python module not found on tree: ipfs_datasets_py.discord_dashboard | origin=backtick |
| `python_modules` | `docs/examples/discord_usage_examples.md` | 53 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/examples/discord_usage_examples.md` | 93 | Python module not found on tree: ipfs_datasets_py.admin_dashboard | origin=prose |
| `python_modules` | `docs/examples/email_usage_examples.md` | 246 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/examples/finance_usage_examples.md` | 18 | Python module not found on tree: ipfs_datasets_py.finance | origin=backtick |
| `python_modules` | `docs/examples/integration_examples.md` | 10 | Python module not found on tree: ipfs_datasets_py.cross_document_lineage | origin=import |
| `python_modules` | `docs/examples/integration_examples.md` | 11 | Python module not found on tree: ipfs_datasets_py.data_provenance_enhanced | origin=import |
| `python_modules` | `docs/examples/workflow_examples.md` | 13 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/examples/workflow_examples.md` | 16 | Python module not found on tree: ipfs_datasets_py.optimizer_alert_system | origin=import |
| `python_modules` | `docs/examples/workflow_examples.md` | 17 | Python module not found on tree: ipfs_datasets_py.unified_monitoring_dashboard | origin=import |
| `python_modules` | `docs/examples/workflow_examples.md` | 171 | Python module not found on tree: ipfs_datasets_py.alert_handlers | origin=import |
| `python_modules` | `docs/getting_started.md` | 61 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=prose |
| `python_modules` | `docs/guides/BEST_PRACTICES.md` | 50 | Python module not found on tree: ipfs_datasets_py.streaming_data_loader | origin=import |
| `python_modules` | `docs/guides/BEST_PRACTICES.md` | 199 | Python module not found on tree: ipfs_datasets_py.database | origin=import |
| `python_modules` | `docs/guides/COMPREHENSIVE_MCP_DASHBOARD.md` | 218 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=prose |
| `python_modules` | `docs/guides/DEPLOYMENT_GUIDE.md` | 409 | Python module not found on tree: ipfs_datasets_py.fastapi_service | origin=prose |
| `python_modules` | `docs/guides/DEPLOYMENT_GUIDE_NEW.md` | 125 | Python module not found on tree: ipfs_datasets_py.server | origin=prose |
| `python_modules` | `docs/guides/DEPLOYMENT_GUIDE_NEW.md` | 512 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/guides/ERROR_REPORTING.md` | 184 | Python module not found on tree: ipfs_datasets_py.docker_error_wrapper | origin=prose |
| `python_modules` | `docs/guides/FAQ.md` | 199 | Python module not found on tree: ipfs_datasets_py.mcp_server.tools.base | origin=import |
| `python_modules` | `docs/guides/FINANCE_INTEGRATION_GUIDE.md` | 155 | Python module not found on tree: ipfs_datasets_py.finance_cli | origin=prose |
| `python_modules` | `docs/guides/IPFS_ACCELERATE_INTEGRATION.md` | 184 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=import |
| `python_modules` | `docs/guides/IPFS_ACCELERATE_INTEGRATION.md` | 238 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/guides/IPFS_KIT_INTEGRATION.md` | 93 | Python module not found on tree: ipfs_datasets_py.ipfs_kit_integration | origin=import |
| `python_modules` | `docs/guides/IPFS_KIT_INTEGRATION.md` | 208 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=import |
| `python_modules` | `docs/guides/IPFS_KIT_PY_SUBMODULE_INTEGRATION.md` | 89 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/guides/JSONNET_IMPLEMENTATION.md` | 111 | Python module not found on tree: ipfs_datasets_py.jsonnet_utils | origin=import |
| `python_modules` | `docs/guides/JSONNET_IMPLEMENTATION.md` | 133 | Python module not found on tree: ipfs_datasets_py.dataset_serialization | origin=import |
| `python_modules` | `docs/guides/JSONNET_IMPLEMENTATION.md` | 148 | Python module not found on tree: ipfs_datasets_py.car_conversion | origin=import |
| `python_modules` | `docs/guides/LEGAL_DEONTIC_LOGIC_USER_GUIDE.md` | 12 | Python module not found on tree: ipfs_datasets_py.logic_integration | origin=import |
| `python_modules` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 65 | Python module not found on tree: ipfs_datasets_py.module_name.core | origin=prose |
| `python_modules` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 67 | Python module not found on tree: ipfs_datasets_py.module_name | origin=import |
| `python_modules` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 93 | Python module not found on tree: ipfs_datasets_py.data_processing | origin=prose |
| `python_modules` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 134 | Python module not found on tree: ipfs_datasets_py.workflow_engine | origin=prose |
| `python_modules` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 216 | Python module not found on tree: ipfs_datasets_py.new_module | origin=prose |
| `python_modules` | `docs/guides/MCP_REFACTORING_QUICK_START.md` | 247 | Python module not found on tree: ipfs_datasets_py.core | origin=prose |
| `python_modules` | `docs/guides/MCP_SYSTEMD_SETUP.md` | 148 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=prose |
| `python_modules` | `docs/guides/PATENT_FEATURE_SUMMARY.md` | 56 | Python module not found on tree: ipfs_datasets_py.admin_dashboard | origin=prose |
| `python_modules` | `docs/guides/QUICK_START_GUIDE.md` | 18 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=prose |
| `python_modules` | `docs/guides/RECAP_IMPLEMENTATION_SUMMARY.md` | 369 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=prose |
| `python_modules` | `docs/guides/REFACTORING_SUMMARY.md` | 80 | Python module not found on tree: ipfs_datasets_py.knowledge_graph_extraction | origin=import |
| `python_modules` | `docs/guides/REFACTORING_SUMMARY.md` | 101 | Python module not found on tree: ipfs_datasets_py.vector_tools | origin=import |
| `python_modules` | `docs/guides/REFACTORING_SUMMARY.md` | 237 | Python module not found on tree: ipfs_datasets_py.ipfs_kit_integration | origin=import |
| `python_modules` | `docs/guides/RELEASE_CHECKLIST.md` | 66 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=prose |
| `python_modules` | `docs/guides/RELEASE_NOTES.md` | 79 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/guides/THEOREM_PROVER_INTEGRATION_GUIDE.md` | 62 | Python module not found on tree: ipfs_datasets_py.logic_integration | origin=import |
| `python_modules` | `docs/guides/WEB_SCRAPING_GUIDE.md` | 233 | Python module not found on tree: ipfs_datasets_py.advanced_web_archiving | origin=import |
| `python_modules` | `docs/guides/comprehensive_workflow_guide.md` | 43 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/guides/comprehensive_workflow_guide.md` | 83 | Python module not found on tree: ipfs_datasets_py.optimizer_alert_system | origin=import |
| `python_modules` | `docs/guides/comprehensive_workflow_guide.md` | 116 | Python module not found on tree: ipfs_datasets_py.unified_monitoring_dashboard | origin=import |
| `python_modules` | `docs/guides/comprehensive_workflow_guide.md` | 329 | Python module not found on tree: ipfs_datasets_py.monitoring.exporters | origin=import |
| `python_modules` | `docs/guides/comprehensive_workflow_guide.md` | 359 | Python module not found on tree: ipfs_datasets_py.alert_handlers | origin=import |
| `python_modules` | `docs/guides/data_provenance.md` | 9 | Python module not found on tree: ipfs_datasets_py.data_provenance | origin=import |
| `python_modules` | `docs/guides/data_provenance.md` | 55 | Python module not found on tree: ipfs_datasets_py.data_provenance_enhanced | origin=import |
| `python_modules` | `docs/guides/data_provenance.md` | 322 | Python module not found on tree: ipfs_datasets_py.cross_document_lineage | origin=import |
| `python_modules` | `docs/guides/data_provenance.md` | 562 | Python module not found on tree: ipfs_datasets_py.ipld.storage | origin=import |
| `python_modules` | `docs/guides/data_provenance.md` | 878 | Python module not found on tree: ipfs_datasets_py.cross_document_lineage_enhanced | origin=import |
| `python_modules` | `docs/guides/deployment/docker_deployment.md` | 61 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=prose |
| `python_modules` | `docs/guides/deployment/graphrag_production_deployment_guide.md` | 27 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/guides/deployment/graphrag_production_deployment_guide.md` | 40 | Python module not found on tree: ipfs_datasets_py.scripts.init_database | origin=prose |
| `python_modules` | `docs/guides/distributed_features.md` | 242 | Python module not found on tree: ipfs_datasets_py.resilient_operations | origin=import |
| `python_modules` | `docs/guides/installation/CAPABILITY_INSTALLATION.md` | 48 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/guides/installation/CAPABILITY_INSTALLATION.md` | 400 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=prose |
| `python_modules` | `docs/guides/ipld_optimization.md` | 30 | Python module not found on tree: ipfs_datasets_py.ipld.optimized_codec | origin=import |
| `python_modules` | `docs/guides/ipld_optimization.md` | 95 | Python module not found on tree: ipfs_datasets_py.ipld.storage | origin=import |
| `python_modules` | `docs/guides/ipld_optimization.md` | 121 | Python module not found on tree: ipfs_datasets_py.ipld | origin=import |
| `python_modules` | `docs/guides/ipld_optimization.md` | 224 | Python module not found on tree: ipfs_datasets_py.ipld.dag_processor | origin=import |
| `python_modules` | `docs/guides/ipld_optimization.md` | 314 | Python module not found on tree: ipfs_datasets_py.data_provenance_enhanced | origin=import |
| `python_modules` | `docs/guides/ipld_optimization.md` | 404 | Python module not found on tree: ipfs_datasets_py.car_conversion | origin=import |
| `python_modules` | `docs/guides/ipld_optimization.md` | 496 | Python module not found on tree: ipfs_datasets_py.ipld.schema | origin=import |
| `python_modules` | `docs/guides/ipld_optimization.md` | 516 | Python module not found on tree: ipfs_datasets_py.ipld.monitoring | origin=import |
| `python_modules` | `docs/guides/ipld_optimization.md` | 538 | Python module not found on tree: ipfs_datasets_py.ipld.benchmarks | origin=import |
| `python_modules` | `docs/guides/javascript_error_auto_healing.md` | 310 | Python module not found on tree: ipfs_datasets_py.admin_dashboard | origin=import |
| `python_modules` | `docs/guides/knowledge_graph_large_block_fix.md` | 107 | Python module not found on tree: ipfs_datasets_py.ipld | origin=import |
| `python_modules` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_LINEAGE_FAQ.md` | 351 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=prose |
| `python_modules` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md` | 541 | Python module not found on tree: ipfs_datasets_py.__file__ | origin=prose |
| `python_modules` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_REFACTOR_BACKLOG.md` | 3 | Python module not found on tree: ipfs_datasets_py.ipfs_datasets_py.knowledge_graphs | origin=backtick |
| `python_modules` | `docs/guides/pdf_processing.md` | 102 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 32 | Python module not found on tree: ipfs_datasets_py.streaming_data_loader | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 72 | Python module not found on tree: ipfs_datasets_py.arrow_utils | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 131 | Python module not found on tree: ipfs_datasets_py.ipfs_knn_index | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 186 | Python module not found on tree: ipfs_datasets_py.ipld.optimized_codec | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 204 | Python module not found on tree: ipfs_datasets_py.ipld.storage | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 222 | Python module not found on tree: ipfs_datasets_py.query_optimizer | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 242 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 363 | Python module not found on tree: ipfs_datasets_py.batch_processor | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 382 | Python module not found on tree: ipfs_datasets_py.vector_ops | origin=import |
| `python_modules` | `docs/guides/performance_optimization.md` | 398 | Python module not found on tree: ipfs_datasets_py.parallel | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` | 155 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.unified_graphrag | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` | 196 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` | 199 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` | 554 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` | 568 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md` | 573 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md` | 541 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md` | 542 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 197 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=prose |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 298 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization | origin=prose |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 359 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipfs_formats | origin=prose |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 400 | Python module not found on tree: ipfs_datasets_py.data_transformation.ucan | origin=prose |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 790 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 791 | Python module not found on tree: ipfs_datasets_py.data_transformation.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md` | 804 | Python module not found on tree: ipfs_datasets_py.data_transformation.unixfs | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_SUMMARY.md` | 293 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md` | 75 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md` | 91 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md` | 92 | Python module not found on tree: ipfs_datasets_py.data_transformation.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md` | 93 | Python module not found on tree: ipfs_datasets_py.data_transformation.dataset_serialization | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md` | 98 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md` | 99 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md` | 100 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.dataset_serialization | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md` | 109 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_QUICK_REFERENCE.md` | 125 | Python module not found on tree: ipfs_datasets_py.processors.graphrag | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 315 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=prose |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 316 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=prose |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_TASKS.md` | 409 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_VISUAL_SUMMARY.md` | 215 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_VISUAL_SUMMARY.md` | 230 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_VISUAL_SUMMARY.md` | 236 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_VISUAL_SUMMARY.md` | 245 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_VISUAL_SUMMARY.md` | 260 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_INTEGRATION_VISUAL_SUMMARY.md` | 263 | Python module not found on tree: ipfs_datasets_py.processors.graphrag | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md` | 189 | Python module not found on tree: ipfs_datasets_py.processors.graphrag | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md` | 212 | Python module not found on tree: ipfs_datasets_py.processors.specialized.multimedia | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_REFACTORING_SUMMARY_2026.md` | 187 | Python module not found on tree: ipfs_datasets_py.processors.graphrag | origin=prose |
| `python_modules` | `docs/guides/processors/PROCESSORS_REFACTORING_SUMMARY_2026.md` | 196 | Python module not found on tree: ipfs_datasets_py.processors.specialized.multimedia | origin=prose |
| `python_modules` | `docs/guides/provenance_reporting.md` | 201 | Python module not found on tree: ipfs_datasets_py.provenance_report_example | origin=prose |
| `python_modules` | `docs/guides/query_optimization.md` | 32 | Python module not found on tree: ipfs_datasets_py.ipfs_knn_index | origin=import |
| `python_modules` | `docs/guides/query_optimization.md` | 127 | Python module not found on tree: ipfs_datasets_py.knowledge_graph | origin=import |
| `python_modules` | `docs/guides/query_optimization.md` | 200 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/guides/query_optimization.md` | 490 | Python module not found on tree: ipfs_datasets_py.federated_search | origin=import |
| `python_modules` | `docs/guides/query_optimization.md` | 569 | Python module not found on tree: ipfs_datasets_py.query_optimizer | origin=import |
| `python_modules` | `docs/guides/reference/api_reference.md` | 410 | Python module not found on tree: ipfs_datasets_py.exceptions | origin=import |
| `python_modules` | `docs/guides/security/AUDIT_PROVENANCE_AND_INCIDENTS.md` | 141 | Python module not found on tree: ipfs_datasets_py.wallet.audit.append_audit_event | origin=backtick |
| `python_modules` | `docs/guides/security/README.md` | 48 | Python module not found on tree: ipfs_datasets_py.auth | origin=import |
| `python_modules` | `docs/guides/security/audit_logging.md` | 202 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_visualization | origin=import |
| `python_modules` | `docs/guides/security/audit_logging.md` | 310 | Python module not found on tree: ipfs_datasets_py.data_provenance | origin=import |
| `python_modules` | `docs/guides/security/audit_logging.md` | 407 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/guides/security/audit_reporting.md` | 294 | Python module not found on tree: ipfs_datasets_py.admin_dashboard | origin=import |
| `python_modules` | `docs/guides/security/security_governance.md` | 306 | Python module not found on tree: ipfs_datasets_py.data_provenance_enhanced | origin=import |
| `python_modules` | `docs/guides/security/security_governance.md` | 307 | Python module not found on tree: ipfs_datasets_py.cross_document_lineage | origin=import |
| `python_modules` | `docs/guides/security/security_governance.md` | 1147 | Python module not found on tree: ipfs_datasets_py.cross_document_lineage_enhanced | origin=import |
| `python_modules` | `docs/guides/tools/caselaw_dashboard_guide.md` | 52 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=prose |
| `python_modules` | `docs/guides/tools/cli_install_guide.md` | 19 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/guides/tools/patent_scraper_guide.md` | 141 | Python module not found on tree: ipfs_datasets_py.admin_dashboard | origin=prose |
| `python_modules` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_COMPLETE.md` | 44 | Python module not found on tree: ipfs_datasets_py.ipfs_embeddings_py | origin=import |
| `python_modules` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_COMPLETE.md` | 64 | Python module not found on tree: ipfs_datasets_py.llm.llm_interface | origin=import |
| `python_modules` | `docs/implementation/plans/file_conversion_integration_plan.md` | 35 | Python module not found on tree: ipfs_datasets_py.file_converter | origin=backtick |
| `python_modules` | `docs/implementation/plans/file_conversion_integration_plan.md` | 579 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/implementation/plans/file_conversion_pros_cons.md` | 223 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia.convert_to_txt_based_on_mime_type | origin=import |
| `python_modules` | `docs/implementation/plans/file_conversion_pros_cons.md` | 224 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/implementation/plans/file_conversion_systems_analysis.md` | 322 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia.convert_to_txt_based_on_mime_type | origin=import |
| `python_modules` | `docs/implementation/plans/file_conversion_systems_analysis.md` | 326 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/implementation/plans/graphrag_website_implementation_plan.md` | 555 | Python module not found on tree: ipfs_datasets_py.website_graphrag_processor | origin=import |
| `python_modules` | `docs/implementation/plans/graphrag_website_implementation_plan.md` | 557 | Python module not found on tree: ipfs_datasets_py.multimodal_processor | origin=import |
| `python_modules` | `docs/implementation/plans/graphrag_website_implementation_plan.md` | 1245 | Python module not found on tree: ipfs_datasets_py.maintenance.cleanup_jobs | origin=prose |
| `python_modules` | `docs/implementation/plans/module_consolidation_plan.md` | 44 | Python module not found on tree: ipfs_datasets_py.file_converter | origin=backtick |
| `python_modules` | `docs/implementation/plans/module_consolidation_plan.md` | 45 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipfs_formats | origin=backtick |
| `python_modules` | `docs/implementation/plans/module_consolidation_plan.md` | 46 | Python module not found on tree: ipfs_datasets_py.ipfs_formats | origin=backtick |
| `python_modules` | `docs/implementation/plans/module_consolidation_plan.md` | 47 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=backtick |
| `python_modules` | `docs/implementation/plans/module_consolidation_plan.md` | 66 | Python module not found on tree: ipfs_datasets_py.graphrag | origin=prose |
| `python_modules` | `docs/implementation/plans/module_consolidation_plan.md` | 66 | Python module not found on tree: ipfs_datasets_py.rag | origin=prose |
| `python_modules` | `docs/implementation/plans/module_consolidation_plan.md` | 127 | Python module not found on tree: ipfs_datasets_py.graphrag.integrations | origin=prose |
| `python_modules` | `docs/implementation/plans/p2p_workflow_scheduler.md` | 70 | Python module not found on tree: ipfs_datasets_py.p2p_workflow_scheduler | origin=import |
| `python_modules` | `docs/implementation/scrapers/UNIFIED_SCRAPER_IMPLEMENTATION.md` | 78 | Python module not found on tree: ipfs_datasets_py.scraper_cli | origin=prose |
| `python_modules` | `docs/implementation/scrapers/UNIFIED_SCRAPER_QUICKSTART.md` | 18 | Python module not found on tree: ipfs_datasets_py.unified_web_scraper | origin=import |
| `python_modules` | `docs/implementation/scrapers/UNIFIED_SCRAPER_QUICKSTART.md` | 33 | Python module not found on tree: ipfs_datasets_py.scraper_cli | origin=prose |
| `python_modules` | `docs/implementation/scrapers/UNIFIED_SCRAPER_README.md` | 93 | Python module not found on tree: ipfs_datasets_py.scraper_cli | origin=prose |
| `python_modules` | `docs/installation.md` | 36 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=prose |
| `python_modules` | `docs/installation.md` | 42 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/knowledge_graphs/ARCHITECTURE.md` | 822 | Python module not found on tree: ipfs_datasets_py.search.graphrag | origin=import |
| `python_modules` | `docs/knowledge_graphs/CONTRIBUTING.md` | 22 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/knowledge_graphs/DEFERRED_FEATURES.md` | 356 | Python module not found on tree: ipfs_datasets_py.ml.llm.llm_router | origin=prose |
| `python_modules` | `docs/logic/API_VERSIONING.md` | 169 | Python module not found on tree: ipfs_datasets_py.logic.common._internal | origin=import |
| `python_modules` | `docs/logic/CEC/CEC_SYSTEM_GUIDE.md` | 631 | Python module not found on tree: ipfs_datasets_py.logic.native | origin=import |
| `python_modules` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 42 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/logic/CEC/QUICKSTART.md` | 35 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/logic/CEC/QUICKSTART.md` | 167 | Python module not found on tree: ipfs_datasets_py.logic.CEC.native.dcec_knowledge_base | origin=import |
| `python_modules` | `docs/logic/CONTRIBUTING.md` | 63 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/logic/CONTRIBUTING.md` | 294 | Python module not found on tree: ipfs_datasets_py.logic.converters.my_converter | origin=import |
| `python_modules` | `docs/logic/CONTRIBUTING.md` | 454 | Python module not found on tree: ipfs_datasets_py.logic.external_provers.my_prover_bridge | origin=import |
| `python_modules` | `docs/logic/CONTRIBUTING.md` | 591 | Python module not found on tree: ipfs_datasets_py.logic.TDFOL.inference_rules.my_rule | origin=import |
| `python_modules` | `docs/logic/DEPLOYMENT_GUIDE.md` | 118 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/logic/FEATURES.md` | 118 | Python module not found on tree: ipfs_datasets_py.logic.integration.ipfs_proof_cache | origin=import |
| `python_modules` | `docs/logic/FEATURES.md` | 466 | Python module not found on tree: ipfs_datasets_py.logic.integration.ipld_logic_storage | origin=import |
| `python_modules` | `docs/logic/INTEGRATION_GUIDE.md` | 93 | Python module not found on tree: ipfs_datasets_py.logic.integration.proof_execution_engine | origin=import |
| `python_modules` | `docs/logic/LOGIC_PORT_DAEMON.md` | 17 | Python module not found on tree: ipfs_datasets_py.llm_router.generate_text | origin=prose |
| `python_modules` | `docs/logic/TDFOL/README_security_validator.md` | 521 | Python module not found on tree: ipfs_datasets_py.logic.TDFOL.prover | origin=import |
| `python_modules` | `docs/logic/TROUBLESHOOTING.md` | 242 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.phase7_complete_integration | origin=prose |
| `python_modules` | `docs/logic/USAGE_EXAMPLES.md` | 259 | Python module not found on tree: ipfs_datasets_py.logic.integration.proof_execution_engine | origin=import |
| `python_modules` | `docs/logic/USAGE_EXAMPLES.md` | 260 | Python module not found on tree: ipfs_datasets_py.tools.deontic_logic_core | origin=import |
| `python_modules` | `docs/logic/integration/CHANGELOG.md` | 238 | Python module not found on tree: ipfs_datasets_py.logic_integration | origin=import |
| `python_modules` | `docs/logic/itp_hammer_receipts.md` | 161 | Python module not found on tree: ipfs_datasets_py.ipfs_backend_router.get_ipfs_backend | origin=prose |
| `python_modules` | `docs/logic/itp_hammer_security_model.md` | 116 | Python module not found on tree: ipfs_datasets_py.logic.hammers.models.HammerResult.__post_init__ | origin=backtick |
| `python_modules` | `docs/logic/itp_hammer_user_guide.md` | 65 | Python module not found on tree: ipfs_datasets_py.logic.hammers.policy.known_solver_names | origin=prose |
| `python_modules` | `docs/logic/zkp/INTEGRATION_GUIDE.md` | 153 | Python module not found on tree: ipfs_datasets_py.logic.temporal | origin=import |
| `python_modules` | `docs/logic/zkp/INTEGRATION_GUIDE.md` | 258 | Python module not found on tree: ipfs_datasets_py.logic.datalog | origin=import |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 119 | Python module not found on tree: ipfs_datasets_py.ipfs_knn_index | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 121 | Python module not found on tree: ipfs_datasets_py.knowledge_graph | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 122 | Python module not found on tree: ipfs_datasets_py.knowledge_graph_extraction | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 123 | Python module not found on tree: ipfs_datasets_py.llm.llm_graphrag | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 124 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 125 | Python module not found on tree: ipfs_datasets_py.duckdb_connector | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 126 | Python module not found on tree: ipfs_datasets_py.data_provenance | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 128 | Python module not found on tree: ipfs_datasets_py.logic_integration | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 129 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 131 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=prose |
| `python_modules` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` | 132 | Python module not found on tree: ipfs_datasets_py.ipfs_kit | origin=backtick |
| `python_modules` | `docs/maintenance/EXAMPLE_VERIFICATION.md` | 230 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=backtick |
| `python_modules` | `docs/modules/file_converter/README.md` | 86 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/optimizers/GRAPHRAG_QUICK_START.md` | 230 | Python module not found on tree: ipfs_datasets_py.optimizers.graphrag.cli | origin=prose |
| `python_modules` | `docs/optimizers/PHASES_3_6_8_IMPLEMENTATION_SUMMARY.md` | 67 | Python module not found on tree: ipfs_datasets_py.llm_router.generate_text | origin=backtick |
| `python_modules` | `docs/optimizers/agentic/DEPLOYMENT_GUIDE.md` | 79 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/optimizers/docs/SEMANTIC_DEDUPLICATION_GUIDE.md` | 289 | Python module not found on tree: ipfs_datasets_py.optimizers.agentic.feature_flags | origin=import |
| `python_modules` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 667 | Python module not found on tree: ipfs_datasets_py.processors.graphrag | origin=import |
| `python_modules` | `docs/optimizers/logic_theorem_optimizer/PHASE2_COMPLETE.md` | 1197 | Python module not found on tree: ipfs_datasets_py.rag.logic_integration | origin=import |
| `python_modules` | `docs/rag_optimizer/README.md` | 48 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 268 | Python module not found on tree: ipfs_datasets_py.car_conversion | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 269 | Python module not found on tree: ipfs_datasets_py.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 270 | Python module not found on tree: ipfs_datasets_py.dataset_serialization | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 273 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 274 | Python module not found on tree: ipfs_datasets_py.data_transformation.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 275 | Python module not found on tree: ipfs_datasets_py.data_transformation.dataset_serialization | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 282 | Python module not found on tree: ipfs_datasets_py.knowledge_graph_extraction | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 283 | Python module not found on tree: ipfs_datasets_py.cross_document_lineage | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 284 | Python module not found on tree: ipfs_datasets_py.cross_document_reasoning | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 296 | Python module not found on tree: ipfs_datasets_py.web_archive | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 297 | Python module not found on tree: ipfs_datasets_py.simple_crawler | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 298 | Python module not found on tree: ipfs_datasets_py.unified_web_scraper | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 310 | Python module not found on tree: ipfs_datasets_py.p2p_workflow_scheduler | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 311 | Python module not found on tree: ipfs_datasets_py.p2p_peer_registry | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 312 | Python module not found on tree: ipfs_datasets_py.libp2p_kit | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 324 | Python module not found on tree: ipfs_datasets_py.query_optimizer | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 325 | Python module not found on tree: ipfs_datasets_py.vector_tools | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 336 | Python module not found on tree: ipfs_datasets_py.data_provenance | origin=import |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 400 | Python module not found on tree: ipfs_datasets_py.data_transformation | origin=prose |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 404 | Python module not found on tree: ipfs_datasets_py.reasoning | origin=prose |
| `python_modules` | `docs/reorganization/DEEP_REORGANIZATION.md` | 405 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipfs_formats | origin=prose |
| `python_modules` | `docs/reorganization/FINAL_CLEANUP.md` | 102 | Python module not found on tree: ipfs_datasets_py.integrations | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 60 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 61 | Python module not found on tree: ipfs_datasets_py.admin_dashboard | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 74 | Python module not found on tree: ipfs_datasets_py.discord_cli | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 75 | Python module not found on tree: ipfs_datasets_py.email_cli | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 88 | Python module not found on tree: ipfs_datasets_py.cache | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 89 | Python module not found on tree: ipfs_datasets_py.distributed_cache | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 102 | Python module not found on tree: ipfs_datasets_py.graphrag_integration | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 105 | Python module not found on tree: ipfs_datasets_py.integrations.graphrag_integration | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 108 | Python module not found on tree: ipfs_datasets_py.integrations | origin=import |
| `python_modules` | `docs/reorganization/PACKAGE_REORGANIZATION.md` | 114 | Python module not found on tree: ipfs_datasets_py.graphrag_processor | origin=import |
| `python_modules` | `docs/reports/COMPLETION_REPORT.md` | 72 | Python module not found on tree: ipfs_datasets_py.data_processing | origin=import |
| `python_modules` | `docs/reports/COMPLETION_REPORT.md` | 165 | Python module not found on tree: ipfs_datasets_py.workflow_engine | origin=import |
| `python_modules` | `docs/reports/COMPLETION_REPORT.md` | 227 | Python module not found on tree: ipfs_datasets_py.core_module | origin=import |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 40 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 43 | Python module not found on tree: ipfs_datasets_py.mcp_investigation_dashboard | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 46 | Python module not found on tree: ipfs_datasets_py.news_analysis_dashboard | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 49 | Python module not found on tree: ipfs_datasets_py.provenance_dashboard | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 52 | Python module not found on tree: ipfs_datasets_py.unified_monitoring_dashboard | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 66 | Python module not found on tree: ipfs_datasets_py.streaming_data_loader | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 69 | Python module not found on tree: ipfs_datasets_py.ipfs_knn_index | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 70 | Python module not found on tree: ipfs_datasets_py.embeddings.ipfs_knn_index | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 72 | Python module not found on tree: ipfs_datasets_py.jsonnet_utils | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 75 | Python module not found on tree: ipfs_datasets_py.libp2p_kit | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 95 | Python module not found on tree: ipfs_datasets_py.optimizer_visualization_integration | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 98 | Python module not found on tree: ipfs_datasets_py.data_provenance_enhanced | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 118 | Python module not found on tree: ipfs_datasets_py.data_provenance | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 121 | Python module not found on tree: ipfs_datasets_py.admin_dashboard | origin=prose |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 167 | Python module not found on tree: ipfs_datasets_py.investigation_mcp_client | origin=backtick |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 207 | Python module not found on tree: ipfs_datasets_py.llm.llm_graphrag | origin=import |
| `python_modules` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 208 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/reports/FINAL_COMPLETE_SUMMARY.md` | 230 | Python module not found on tree: ipfs_datasets_py.core | origin=import |
| `python_modules` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 42 | Python module not found on tree: ipfs_datasets_py.legal_scrapers | origin=backtick |
| `python_modules` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 43 | Python module not found on tree: ipfs_datasets_py.embeddings.core | origin=backtick |
| `python_modules` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 48 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=backtick |
| `python_modules` | `docs/reports/MCP_REFACTORING_FINAL_SUMMARY.md` | 185 | Python module not found on tree: ipfs_datasets_py.core_module | origin=import |
| `python_modules` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 157 | Python module not found on tree: ipfs_datasets_py.vector_tools | origin=import |
| `python_modules` | `docs/reports/MCP_TOOLS_FIXES_COMPLETE.md` | 224 | Python module not found on tree: ipfs_datasets_py.logic_integration.medical_theorem_framework | origin=import |
| `python_modules` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 11 | Python module not found on tree: ipfs_datasets_py.core_module | origin=import |
| `python_modules` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 65 | Python module not found on tree: ipfs_datasets_py.legal_scrapers | origin=backtick |
| `python_modules` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 66 | Python module not found on tree: ipfs_datasets_py.embeddings.core | origin=backtick |
| `python_modules` | `docs/reports/MCP_TOOLS_REFACTORING_STATUS.md` | 71 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=backtick |
| `python_modules` | `docs/reports/TEST_IMPORT_VERIFICATION_COMPLETE.md` | 69 | Python module not found on tree: ipfs_datasets_py.mcp_server.tools.admin_tools.system_health | origin=import |
| `python_modules` | `docs/reports/TEST_IMPORT_VERIFICATION_COMPLETE.md` | 93 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/reports/WEB_SCRAPING_REFACTORING_SUMMARY.md` | 64 | Python module not found on tree: ipfs_datasets_py.unified_web_scraper | origin=prose |
| `python_modules` | `docs/reports/WEB_SCRAPING_REFACTORING_SUMMARY.md` | 205 | Python module not found on tree: ipfs_datasets_py.scraper_cli | origin=prose |
| `python_modules` | `docs/reports/cicd_setup_complete.md` | 97 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/reports/cicd_setup_summary.md` | 158 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/reports/final_individual_scan_summary.md` | 63 | Python module not found on tree: ipfs_datasets_py.mcp_dashboard | origin=prose |
| `python_modules` | `docs/reports/final_individual_scan_summary.md` | 64 | Python module not found on tree: ipfs_datasets_py.cache | origin=prose |
| `python_modules` | `docs/reports/final_individual_scan_summary.md` | 65 | Python module not found on tree: ipfs_datasets_py.web_archive | origin=prose |
| `python_modules` | `docs/reports/final_individual_scan_summary.md` | 66 | Python module not found on tree: ipfs_datasets_py.libp2p_kit | origin=prose |
| `python_modules` | `docs/reports/final_individual_scan_summary.md` | 67 | Python module not found on tree: ipfs_datasets_py.discord_cli | origin=prose |
| `python_modules` | `docs/reports/final_individual_scan_summary.md` | 68 | Python module not found on tree: ipfs_datasets_py.graphrag_integration | origin=prose |
| `python_modules` | `docs/reports/final_individual_scan_summary.md` | 68 | Python module not found on tree: ipfs_datasets_py.integrations.graphrag_integration | origin=prose |
| `python_modules` | `docs/reports/final_individual_scan_summary.md` | 69 | Python module not found on tree: ipfs_datasets_py.p2p_peer_registry | origin=prose |
| `python_modules` | `docs/reports/phase_2_completion_summary.md` | 293 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/reports/v0_4_0_final_summary.md` | 386 | Python module not found on tree: ipfs_datasets_py.file_converter | origin=import |
| `python_modules` | `docs/security_verification/evidence_promotion_workflow.md` | 22 | Python module not found on tree: ipfs_datasets_py.logic.security_models.crypto_exchange.evidence_promotion.evaluate_evidence_promotion_workflow | origin=backtick |
| `python_modules` | `docs/security_verification/production_release_decision_policy.md` | 6 | Python module not found on tree: ipfs_datasets_py.logic.security_models.crypto_exchange.release_policy.build_security_decision_policy | origin=backtick |
| `python_modules` | `docs/security_verification/security_ir_v1_compatibility.md` | 109 | Python module not found on tree: ipfs_datasets_py.utils.cid_utils.cid_for_bytes | origin=backtick |
| `python_modules` | `docs/tutorials/graphrag_tutorial.md` | 49 | Python module not found on tree: ipfs_datasets_py.ipfs_knn_index | origin=import |
| `python_modules` | `docs/tutorials/graphrag_tutorial.md` | 51 | Python module not found on tree: ipfs_datasets_py.knowledge_graph_extraction | origin=import |
| `python_modules` | `docs/tutorials/graphrag_tutorial.md` | 52 | Python module not found on tree: ipfs_datasets_py.llm.llm_graphrag | origin=import |
| `python_modules` | `docs/tutorials/graphrag_tutorial.md` | 124 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=import |
| `python_modules` | `docs/tutorials/graphrag_tutorial.md` | 382 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/tutorials/graphrag_website_processing_tutorial.md` | 21 | Python module not found on tree: ipfs_datasets_py.website_graphrag_processor | origin=import |
| `python_modules` | `docs/tutorials/graphrag_website_processing_tutorial.md` | 90 | Python module not found on tree: ipfs_datasets_py.multimodal_processor | origin=import |
| `python_modules` | `docs/tutorials/graphrag_website_processing_tutorial.md` | 136 | Python module not found on tree: ipfs_datasets_py.knowledge_graph_extraction | origin=import |
| `python_modules` | `docs/tutorials/graphrag_website_processing_tutorial.md` | 174 | Python module not found on tree: ipfs_datasets_py.website_graphrag_system | origin=import |
| `python_modules` | `docs/tutorials/media_scraping_tutorial.md` | 47 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/tutorials/security_compliance_tutorial.md` | 213 | Python module not found on tree: ipfs_datasets_py.data_provenance_enhanced | origin=import |
| `python_modules` | `docs/tutorials/security_compliance_tutorial.md` | 214 | Python module not found on tree: ipfs_datasets_py.cross_document_lineage | origin=import |
| `python_modules` | `docs/tutorials/security_tutorial.md` | 56 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/tutorials/security_tutorial.md` | 139 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_visualization | origin=import |
| `python_modules` | `docs/tutorials/security_tutorial.md` | 578 | Python module not found on tree: ipfs_datasets_py.examples.rag_audit_integration_example | origin=prose |
| `python_modules` | `docs/unified_dashboard.md` | 64 | Python module not found on tree: ipfs_datasets_py.unified_monitoring_dashboard | origin=import |
| `python_modules` | `docs/unified_dashboard.md` | 66 | Python module not found on tree: ipfs_datasets_py.optimizer_alert_system | origin=import |
| `python_modules` | `docs/unified_dashboard.md` | 210 | Python module not found on tree: ipfs_datasets_py.rag.rag_query_optimizer | origin=import |
| `python_modules` | `docs/user_guide.md` | 154 | Python module not found on tree: ipfs_datasets_py.__version__ | origin=prose |
| `python_modules` | `docs/user_guide.md` | 257 | Python module not found on tree: ipfs_datasets_py.ipfs_knn_index | origin=prose |
| `python_modules` | `docs/user_guide.md` | 259 | Python module not found on tree: ipfs_datasets_py.knowledge_graph | origin=prose |
| `metadata` | `docs/CHANGELOG.md` |  | Status=canonical page missing required metadata: Owner, Source / Source of truth, Audience |  |
| `metadata` | `docs/FEATURES.md` |  | Status=canonical page missing required metadata: Owner, Source / Source of truth, Audience |  |
| `metadata` | `docs/developer_guides/REPOSITORY_MAP.md` |  | Status=canonical page missing required metadata: Last verified |  |
| `metadata` | `docs/getting_started.md` |  | Status=canonical page missing required metadata: Source / Source of truth |  |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-074.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |  |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-090.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |  |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-091.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |  |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-092.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |  |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-093.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |  |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-095.md` |  | Status=evidence page missing required metadata: Source / Source of truth, Last verified |  |
| `metadata` | `docs/tutorials/FIRST_DATASET_WORKFLOW.md` |  | Status=canonical page missing required metadata: Source / Source of truth |  |
| `metadata` | `docs/tutorials/LOGIC_AND_PROOF_WORKFLOW.md` |  | Status=canonical page missing required metadata: Source / Source of truth |  |
| `metadata` | `docs/tutorials/MCP_CLIENT_WORKFLOW.md` |  | Status=canonical page missing required metadata: Source / Source of truth |  |
| `metadata` | `docs/tutorials/RETRIEVAL_AND_KNOWLEDGE_WORKFLOW.md` |  | Status=canonical page missing required metadata: Source / Source of truth |  |
| `metadata` | `docs/user_guide.md` |  | Status=canonical page missing required metadata: Source / Source of truth |  |
| `duplicates` | `docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md` |  | Duplicate canonical Interface declaration: 'RetrievalArchitecture@1' used by 3 pages | docs/architecture/retrieval/EMBEDDINGS_AND_INDEXING.md; docs/architecture/retrieval/SEARCH_AND_QUERY.md; docs/architecture/retrieval/VECTOR_STORES.md |
| `python_syntax` | `docs/CLI_MCP_ALIGNMENT.md` | 47 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/CLI_MCP_ALIGNMENT.md` | 124 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/CLI_MCP_ALIGNMENT_ANALYSIS.md` | 342 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/DOCUMENTATION_INDEX_COMPLETE.md` | 275 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/ENHANCEMENT_12_MCP_COMPLETION.md` | 254 | Fenced Python block has syntax error | invalid syntax (line 10) |
| `python_syntax` | `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | 467 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | 484 | Fenced Python block has syntax error | unterminated string literal (detected at line 1) (line 1) |
| `python_syntax` | `docs/GRAPHRAG_CONSOLIDATION_GUIDE.md` | 505 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | 698 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | 703 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | 712 | Fenced Python block has syntax error | expected ':' (line 4) |
| `python_syntax` | `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | 747 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | 757 | Fenced Python block has syntax error | invalid syntax (line 6) |
| `python_syntax` | `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | 859 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/IPLD_VECTOR_DATABASE_GUIDE.md` | 873 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/IPLD_VECTOR_DATABASE_PRODUCTION_POLISH_PLAN.md` | 443 | Fenced Python block has syntax error | invalid syntax. Perhaps you forgot a comma? (line 2) |
| `python_syntax` | `docs/MCP_ARCHITECTURE_DIAGRAM.md` | 315 | Fenced Python block has syntax error | invalid syntax (line 5) |
| `python_syntax` | `docs/MCP_REFACTORING_PLAN.md` | 42 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/MCP_REFACTORING_SUMMARY.md` | 132 | Fenced Python block has syntax error | invalid syntax (line 8) |
| `python_syntax` | `docs/MCP_TESTING_GUIDE.md` | 94 | Fenced Python block has syntax error | invalid syntax (line 11) |
| `python_syntax` | `docs/MULTIMEDIA_ARCHITECTURE_ANALYSIS.md` | 185 | Fenced Python block has syntax error | unexpected indent (line 2) |
| `python_syntax` | `docs/PHASE3C4_CIRCUIT_IMPLEMENTATION.md` | 280 | Fenced Python block has syntax error | invalid syntax (line 9) |
| `python_syntax` | `docs/PHASE3C5_GOLDEN_VECTOR_COMPLETION.md` | 31 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/PHASE3C5_GOLDEN_VECTOR_COMPLETION.md` | 233 | Fenced Python block has syntax error | expected an indented block after function definition on line 5 (line 12) |
| `python_syntax` | `docs/PHASE3C6_COMPLETION_REPORT.md` | 162 | Fenced Python block has syntax error | expected an indented block after function definition on line 13 (line 16) |
| `python_syntax` | `docs/PHASE3C6_COMPLETION_REPORT.md` | 183 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 5) |
| `python_syntax` | `docs/PHASE3C6_COMPLETION_REPORT.md` | 215 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 9) |
| `python_syntax` | `docs/PHASE3C6_COMPLETION_REPORT.md` | 238 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 9) |
| `python_syntax` | `docs/PHASE3C6_ONCHAIN_INTEGRATION_PLAN.md` | 91 | Fenced Python block has syntax error | invalid decimal literal (line 1) |
| `python_syntax` | `docs/PHASE3C_COMPLETION_1_2.md` | 125 | Fenced Python block has syntax error | invalid decimal literal (line 5) |
| `python_syntax` | `docs/PHASE3C_COMPLETION_1_2.md` | 168 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/PHASE3C_COMPLETION_1_2.md` | 186 | Fenced Python block has syntax error | invalid syntax (line 9) |
| `python_syntax` | `docs/PHASE3D_4_PLUS_ROADMAP.md` | 317 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/PHASES_5_8_STATUS.md` | 304 | Fenced Python block has syntax error | expected an indented block after 'except' statement on line 4 (line 5) |
| `python_syntax` | `docs/PHASE_5_COMPLETE.md` | 49 | Fenced Python block has syntax error | expected an indented block after 'except' statement on line 4 (line 5) |
| `python_syntax` | `docs/PHASE_9_COMPLETION_REPORT.md` | 290 | Fenced Python block has syntax error | invalid syntax (line 10) |
| `python_syntax` | `docs/TESTING_STRATEGY.md` | 294 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/analysis/search_api_classes.md` | 172 | Fenced Python block has syntax error | ':' expected after dictionary key (line 6) |
| `python_syntax` | `docs/api/domains/CORE_AND_DATA.md` | 106 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/CORE_AND_DATA.md` | 151 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/CORE_AND_DATA.md` | 185 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/CORE_AND_DATA.md` | 219 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/CORE_AND_DATA.md` | 264 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/CORE_AND_DATA.md` | 299 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/CORE_AND_DATA.md` | 384 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/CORE_AND_DATA.md` | 463 | Fenced Python block has syntax error | expected ':' (line 3) |
| `python_syntax` | `docs/api/domains/CORE_AND_DATA.md` | 542 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md` | 148 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md` | 212 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md` | 255 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md` | 447 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/api/domains/KNOWLEDGE_LOGIC_AND_PROOF.md` | 484 | Fenced Python block has syntax error | expected ':' (line 10) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 129 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 145 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 175 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 229 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 273 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 302 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 332 | Fenced Python block has syntax error | invalid syntax (line 8) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 362 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 392 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 421 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 472 | Fenced Python block has syntax error | expected ':' (line 3) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 515 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/MCP_AND_RUNTIME.md` | 552 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 89 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 233 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 240 | Fenced Python block has syntax error | expected ':' (line 7) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 260 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 301 | Fenced Python block has syntax error | expected ':' (line 9) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 325 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 338 | Fenced Python block has syntax error | invalid character '…' (U+2026) (line 2) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 424 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 443 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 479 | Fenced Python block has syntax error | expected ':' (line 6) |
| `python_syntax` | `docs/api/domains/OPERATIONS_AND_INTEGRATIONS.md` | 523 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/api/domains/PROCESSING_AND_RETRIEVAL.md` | 62 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/PROCESSING_AND_RETRIEVAL.md` | 169 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/PROCESSING_AND_RETRIEVAL.md` | 211 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/PROCESSING_AND_RETRIEVAL.md` | 292 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/api/domains/PROCESSING_AND_RETRIEVAL.md` | 328 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/PROCESSING_AND_RETRIEVAL.md` | 361 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/api/domains/PROCESSING_AND_RETRIEVAL.md` | 406 | Fenced Python block has syntax error | expected ':' (line 7) |
| `python_syntax` | `docs/api/domains/PROCESSING_AND_RETRIEVAL.md` | 464 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | 190 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | 243 | Fenced Python block has syntax error | invalid syntax (line 11) |
| `python_syntax` | `docs/architecture/MCP_TOOLS_ARCHITECTURE.md` | 261 | Fenced Python block has syntax error | invalid syntax (line 10) |
| `python_syntax` | `docs/architecture/github_actions_infrastructure.md` | 186 | Fenced Python block has syntax error | positional argument follows keyword argument (line 15) |
| `python_syntax` | `docs/architecture/github_actions_infrastructure.md` | 318 | Fenced Python block has syntax error | positional argument follows keyword argument (line 12) |
| `python_syntax` | `docs/architecture/mcp_tools_technical_reference.md` | 75 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/architecture/mcp_tools_technical_reference.md` | 171 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/architecture/mcp_tools_technical_reference.md` | 263 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/architecture/mcp_tools_technical_reference.md` | 315 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/architecture/mcp_tools_technical_reference.md` | 347 | Fenced Python block has syntax error | expected ':' (line 9) |
| `python_syntax` | `docs/architecture/mcp_tools_technical_reference.md` | 396 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/architecture/mcp_tools_technical_reference.md` | 517 | Fenced Python block has syntax error | expected ':' (line 6) |
| `python_syntax` | `docs/architecture/mcp_tools_technical_reference.md` | 586 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/architecture/mcp_tools_technical_reference.md` | 617 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/developer_guides/CREATING_TOOLS.md` | 179 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/developer_guides/CREATING_TOOLS.md` | 193 | Fenced Python block has syntax error | invalid syntax (line 5) |
| `python_syntax` | `docs/developer_guides/REPOSITORY_MAP.md` | 256 | Fenced Python block has syntax error | invalid syntax (line 6) |
| `python_syntax` | `docs/guides/CI_CD_ANALYSIS.md` | 261 | Fenced Python block has syntax error | unterminated string literal (detected at line 2) (line 2) |
| `python_syntax` | `docs/guides/CLI_TOOL_MERGE.md` | 212 | Fenced Python block has syntax error | expected an indented block after function definition on line 8 (line 11) |
| `python_syntax` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 111 | Fenced Python block has syntax error | illegal target for annotation (line 2) |
| `python_syntax` | `docs/guides/DOCUMENTATION_UPDATE_CURRENT.md` | 86 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 2) |
| `python_syntax` | `docs/guides/HOW_TO_USE_COPILOT_AUTO_FIX.md` | 226 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 3) |
| `python_syntax` | `docs/guides/IPFS_KIT_INTEGRATION.md` | 408 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/guides/IPFS_KIT_INTEGRATION.md` | 420 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/guides/SCRAPER_FIX_SUMMARY.md` | 77 | Fenced Python block has syntax error | invalid syntax (line 7) |
| `python_syntax` | `docs/guides/UNIFIED_TOOLS_SUITE.md` | 188 | Fenced Python block has syntax error | invalid syntax (line 10) |
| `python_syntax` | `docs/guides/UNIFIED_TOOLS_SUITE.md` | 206 | Fenced Python block has syntax error | invalid syntax (line 11) |
| `python_syntax` | `docs/guides/UNIFIED_TOOLS_SUITE.md` | 225 | Fenced Python block has syntax error | invalid syntax (line 11) |
| `python_syntax` | `docs/guides/UNIFIED_TOOLS_SUITE.md` | 244 | Fenced Python block has syntax error | invalid syntax (line 12) |
| `python_syntax` | `docs/guides/UNIFIED_TOOLS_SUITE.md` | 264 | Fenced Python block has syntax error | invalid syntax (line 18) |
| `python_syntax` | `docs/guides/biomolecule_discovery_integration.md` | 57 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/guides/infrastructure/vscode_cli_integration.md` | 350 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/guides/knowledge_graph_large_block_fix.md` | 16 | Fenced Python block has syntax error | invalid syntax. Perhaps you forgot a comma? (line 4) |
| `python_syntax` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md` | 106 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md` | 144 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md` | 176 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md` | 235 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md` | 313 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md` | 336 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_NEXT_STEPS.md` | 194 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONER_API_AND_PROOF_SCHEMA.md` | 132 | Fenced Python block has syntax error | invalid syntax (line 6) |
| `python_syntax` | `docs/guides/p2p/P2P_CACHE_FINAL_STATUS.md` | 21 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/guides/processors/PROCESSORS_IMPLEMENTATION_SUMMARY.md` | 195 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 12) |
| `python_syntax` | `docs/guides/processors/PROCESSORS_QUICK_REFERENCE.md` | 239 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/guides/processors/PROCESSORS_REFACTORING_QUICK_REFERENCE.md` | 150 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/guides/tools/cli_caching_guide.md` | 347 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/guides/tools/cli_caching_guide.md` | 364 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/guides/tools/cli_caching_guide.md` | 382 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_COMPLETE.md` | 137 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_PLAN.md` | 380 | Fenced Python block has syntax error | invalid syntax (line 5) |
| `python_syntax` | `docs/implementation/plans/DEONTIC_LOGIC_IMPLEMENTATION_PLAN.md` | 34 | Fenced Python block has syntax error | expected ':' (line 11) |
| `python_syntax` | `docs/implementation/plans/DEONTIC_LOGIC_IMPLEMENTATION_PLAN.md` | 55 | Fenced Python block has syntax error | expected ':' (line 20) |
| `python_syntax` | `docs/implementation/plans/DEONTIC_LOGIC_IMPLEMENTATION_PLAN.md` | 119 | Fenced Python block has syntax error | expected ':' (line 4) |
| `python_syntax` | `docs/implementation/plans/NOTIMPLEMENTEDERROR_IMPLEMENTATION_PLAN.md` | 35 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/implementation/plans/NOTIMPLEMENTEDERROR_IMPLEMENTATION_PLAN.md` | 44 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/implementation/plans/file_conversion_merge_feasibility.md` | 595 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 29 | Fenced Python block has syntax error | invalid syntax (line 4) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 51 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 76 | Fenced Python block has syntax error | invalid syntax (line 4) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 102 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 128 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 140 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 169 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 199 | Fenced Python block has syntax error | invalid syntax (line 4) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 212 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 231 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 258 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 310 | Fenced Python block has syntax error | invalid syntax (line 6) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 329 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 416 | Fenced Python block has syntax error | invalid syntax (line 4) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 429 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 519 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 544 | Fenced Python block has syntax error | invalid syntax (line 4) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 557 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 645 | Fenced Python block has syntax error | invalid syntax (line 10) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 697 | Fenced Python block has syntax error | invalid syntax (line 4) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 758 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 765 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 812 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 819 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/knowledge_graphs/API_REFERENCE.md` | 835 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 23 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 85 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 123 | Fenced Python block has syntax error | expected ':' (line 4) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 161 | Fenced Python block has syntax error | expected ':' (line 3) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 224 | Fenced Python block has syntax error | expected ':' (line 12) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 253 | Fenced Python block has syntax error | expected ':' (line 7) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 270 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 296 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 317 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 325 | Fenced Python block has syntax error | expected ':' (line 7) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 339 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 374 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 383 | Fenced Python block has syntax error | expected ':' (line 6) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 393 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 418 | Fenced Python block has syntax error | expected ':' (line 6) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 431 | Fenced Python block has syntax error | expected ':' (line 6) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 459 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 468 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 483 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 497 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 532 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 541 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 556 | Fenced Python block has syntax error | expected ':' (line 6) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 584 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/logic/API_REFERENCE.md` | 593 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/logic/ARCHITECTURE.md` | 506 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/logic/BEST_PRACTICES.md` | 31 | Fenced Python block has syntax error | positional argument follows keyword argument (line 2) |
| `python_syntax` | `docs/logic/CEC/CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` | 213 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/CEC/CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` | 225 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/CEC/CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` | 385 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 220 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 232 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 240 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 250 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 259 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 779 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 789 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/CEC/EXTENDED_NL_SUPPORT_ROADMAP.md` | 113 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md` | 93 | Fenced Python block has syntax error | expected ':' (line 3) |
| `python_syntax` | `docs/logic/COMPREHENSIVE_LOGIC_REFACTORING_PLAN_2026_v2.md` | 131 | Fenced Python block has syntax error | expected ':' (line 9) |
| `python_syntax` | `docs/logic/TDFOL/FORMULA_DEPENDENCY_GRAPH.md` | 108 | Fenced Python block has syntax error | expected ':' (line 6) |
| `python_syntax` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 194 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 226 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 292 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 319 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 415 | Fenced Python block has syntax error | invalid character '└' (U+2514) (line 13) |
| `python_syntax` | `docs/logic/TDFOL/UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md` | 436 | Fenced Python block has syntax error | invalid syntax (line 5) |
| `python_syntax` | `docs/logic/TDFOL/countermodel_visualizer_README.md` | 127 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/logic/TDFOL/countermodel_visualizer_README.md` | 171 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/logic/TDFOL/proof_tree_visualizer_README.md` | 220 | Fenced Python block has syntax error | expected ':' (line 8) |
| `python_syntax` | `docs/logic/TDFOL/proof_tree_visualizer_README.md` | 286 | Fenced Python block has syntax error | expected ':' (line 6) |
| `python_syntax` | `docs/logic/TROUBLESHOOTING.md` | 109 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/TROUBLESHOOTING.md` | 199 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/TROUBLESHOOTING.md` | 254 | Fenced Python block has syntax error | invalid character '⚠' (U+26A0) (line 1) |
| `python_syntax` | `docs/logic/logic_API_REFERENCE.md` | 15 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 308 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 644 | Fenced Python block has syntax error | invalid syntax (line 5) |
| `python_syntax` | `docs/modules/file_converter/README.md` | 147 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/optimizers/ARCHITECTURE_DIAGRAM.md` | 62 | Fenced Python block has syntax error | ':' expected after dictionary key (line 4) |
| `python_syntax` | `docs/optimizers/ARCHITECTURE_DIAGRAM.md` | 264 | Fenced Python block has syntax error | ':' expected after dictionary key (line 6) |
| `python_syntax` | `docs/optimizers/COMMON_PITFALLS.md` | 36 | Fenced Python block has syntax error | ':' expected after dictionary key (line 9) |
| `python_syntax` | `docs/optimizers/COMMON_PITFALLS.md` | 115 | Fenced Python block has syntax error | ':' expected after dictionary key (line 3) |
| `python_syntax` | `docs/optimizers/COMMON_PITFALLS.md` | 135 | Fenced Python block has syntax error | ':' expected after dictionary key (line 4) |
| `python_syntax` | `docs/optimizers/COMMON_PITFALLS.md` | 767 | Fenced Python block has syntax error | invalid syntax (line 9) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 19 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 25 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 39 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 45 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 60 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 66 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 80 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 87 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 102 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 110 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 125 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 132 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 161 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 167 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 181 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/EXCEPTION_HANDLING_IMPROVEMENTS.md` | 187 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/STANDARDIZATION_SUMMARY.md` | 60 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/optimizers/graphrag/CONFIGURATION_REFERENCE.md` | 619 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/optimizers/graphrag/PHASE3_COMPLETE.md` | 40 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/optimizers/graphrag/PHASE3_COMPLETE.md` | 100 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/optimizers/graphrag/PHASE3_COMPLETE.md` | 418 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/optimizers/graphrag/PHASE5_6_COMPLETE.md` | 71 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/optimizers/graphrag/PHASE5_6_COMPLETE.md` | 80 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/optimizers/graphrag/PHASE5_6_COMPLETE.md` | 90 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/optimizers/graphrag/PHASE5_6_COMPLETE.md` | 100 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/optimizers/graphrag/PHASE5_6_COMPLETE.md` | 109 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/optimizers/logic_theorem_optimizer/QUICK_START.md` | 145 | Fenced Python block has syntax error | f-string: single '}' is not allowed (line 14) |
| `python_syntax` | `docs/optimizers/optimizer_learning_metrics_stubs.md` | 21 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/optimizers/optimizer_learning_metrics_stubs.md` | 109 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/profiling/INFER_RELATIONSHIPS_PERFORMANCE_ANALYSIS.md` | 165 | Fenced Python block has syntax error | expected an indented block after 'for' statement on line 2 (line 3) |
| `python_syntax` | `docs/profiling/INFER_RELATIONSHIPS_PERFORMANCE_ANALYSIS.md` | 252 | Fenced Python block has syntax error | expected an indented block after 'for' statement on line 16 (line 16) |
| `python_syntax` | `docs/rag_optimizer/learning_metrics_implementation.md` | 25 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 38 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 3) |
| `python_syntax` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 65 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 88 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/reports/EXAMPLES_UPDATE_REPORT.md` | 114 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/reports/WORKFLOW_IMPROVEMENTS_SUMMARY.md` | 51 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/reports/discord_integration_summary.md` | 281 | Fenced Python block has syntax error | illegal target for annotation (line 1) |
| `python_syntax` | `docs/reports/final_individual_scan_summary.md` | 61 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/reports/final_verification_100_percent.md` | 58 | Fenced Python block has syntax error | invalid syntax (line 5) |
| `python_syntax` | `docs/reports/finance_dashboard_implementation_summary.md` | 48 | Fenced Python block has syntax error | positional argument follows keyword argument (line 2) |
| `python_syntax` | `docs/reports/finance_dashboard_implementation_summary.md` | 118 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 3) |
| `python_syntax` | `docs/reports/finance_dashboard_implementation_summary.md` | 125 | Fenced Python block has syntax error | invalid character '×' (U+00D7) (line 1) |
| `python_syntax` | `docs/reports/finance_dashboard_implementation_summary.md` | 132 | Fenced Python block has syntax error | invalid character '≈' (U+2248) (line 1) |
| `python_syntax` | `docs/reports/finance_dashboard_implementation_summary.md` | 139 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 1) |
| `python_syntax` | `docs/reports/finance_dashboard_implementation_summary.md` | 146 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/reports/finance_dashboard_implementation_summary.md` | 159 | Fenced Python block has syntax error | ':' expected after dictionary key (line 15) |
| `python_syntax` | `docs/reports/readme_audit_complete.md` | 42 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 1) |

### warning (7)

| Check | Path | Line | Message | Detail |
| --- | --- | ---: | --- | --- |
| `metadata` | `docs/implementation/runbooks/logic_intent_legal_gate_rollout.md` |  | Metadata present but Status missing or not a known lifecycle value | raw=None |
| `metadata` | `docs/maintenance/CURRENT_STATE_BASELINE.md` |  | Metadata present but Status missing or not a known lifecycle value | raw=None |
| `metadata` | `docs/maintenance/DRIFT_AND_CLAIM_MATRIX.md` |  | Metadata present but Status missing or not a known lifecycle value | raw=None |
| `metadata` | `docs/maintenance/completion_receipts/IPFSDOC-064.md` |  | Metadata present but Status missing or not a known lifecycle value | raw=None |
| `python_syntax` | `docs/MCP_TESTING_GUIDE.md` | 80 | Incomplete Python snippet failed parse (warning) | invalid syntax (line 2) |
| `python_syntax` | `docs/optimizers/QUERY_OPTIMIZER_OPTIMIZATION_PLAN.md` | 108 | Incomplete Python snippet failed parse (warning) | invalid syntax (line 1) |
| `python_syntax` | `docs/reports/gpu_setup_complete.md` | 87 | Incomplete Python snippet failed parse (warning) | expected an indented block after function definition on line 17 (line 18) |

### allowlisted (1926)

| Check | Path | Line | Message | Detail |
| --- | --- | ---: | --- | --- |
| `links` | `docs/archive/README.md` | 53 | Relative link target missing: ../implementation_plans/ | ../implementation_plans/ |
| `links` | `docs/archive/completion_reports/DOCUMENTATION_CONSOLIDATION_COMPLETE.md` | 79 | Relative link target missing: ../DOCUMENTATION_INDEX.md | ../DOCUMENTATION_INDEX.md |
| `links` | `docs/archive/completion_reports/DOCUMENTATION_CONSOLIDATION_COMPLETE.md` | 80 | Relative link target missing: ./modules/logic/README.md | ./modules/logic/README.md |
| `links` | `docs/archive/completion_reports/DOCUMENTATION_CONSOLIDATION_COMPLETE.md` | 81 | Relative link target missing: ./guides/ | ./guides/ |
| `links` | `docs/archive/completion_reports/DOCUMENTATION_CONSOLIDATION_COMPLETE.md` | 82 | Relative link target missing: ./implementation/ | ./implementation/ |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 216 | Relative link target missing: ./PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md | ./PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 219 | Relative link target missing: ./MIGRATION_GUIDE_V2.md | ./MIGRATION_GUIDE_V2.md |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 220 | Relative link target missing: ./DEPRECATION_TIMELINE.md | ./DEPRECATION_TIMELINE.md |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 221 | Relative link target missing: ./GRAPHRAG_CONSOLIDATION_GUIDE.md | ./GRAPHRAG_CONSOLIDATION_GUIDE.md |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 222 | Relative link target missing: ./MULTIMEDIA_MIGRATION_GUIDE.md | ./MULTIMEDIA_MIGRATION_GUIDE.md |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 225 | Relative link target missing: ./TASK_1_2_CLEANUP_COMPLETE_REPORT.md | ./TASK_1_2_CLEANUP_COMPLETE_REPORT.md |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 226 | Relative link target missing: ./PHASE_2_SERIALIZATION_COMPLETE.md | ./PHASE_2_SERIALIZATION_COMPLETE.md |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 228 | Relative link target missing: ./PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md | ./PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 229 | Relative link target missing: ./PHASE_6_TESTING_VALIDATION_COMPLETE.md | ./PHASE_6_TESTING_VALIDATION_COMPLETE.md |
| `links` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 422 | Relative link target missing: ./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md | ./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md |
| `links` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 423 | Relative link target missing: ./KNOWLEDGE_GRAPHS_CURRENT_STATUS.md | ./KNOWLEDGE_GRAPHS_CURRENT_STATUS.md |
| `links` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 424 | Relative link target missing: ./KNOWLEDGE_GRAPHS_NEXT_STEPS.md | ./KNOWLEDGE_GRAPHS_NEXT_STEPS.md |
| `links` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 425 | Relative link target missing: ./MIGRATION_TOOLS_USER_GUIDE.md | ./MIGRATION_TOOLS_USER_GUIDE.md |
| `links` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 426 | Relative link target missing: ./KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md | ./KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md |
| `anchors` | `docs/archive/completion_reports/phases/PHASES_11_14_COMPREHENSIVE_PLAN.md` | 38 | In-page anchor not found: #phase-12-testing--validation | archive-prefix:docs/archive/ |
| `links` | `docs/archive/completion_reports/phases/PHASE_2_SERIALIZATION_COMPLETE.md` | 18 | Relative link target missing: ./TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md | ./TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md |
| `links` | `docs/archive/completion_reports/phases/PHASE_2_SERIALIZATION_COMPLETE.md` | 30 | Relative link target missing: ./TASK_2_2_IMPORTS_UPDATE_COMPLETE.md | ./TASK_2_2_IMPORTS_UPDATE_COMPLETE.md |
| `links` | `docs/archive/completion_reports/phases/PHASE_2_SERIALIZATION_COMPLETE.md` | 114 | Relative link target missing: ./TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md | ./TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md |
| `links` | `docs/archive/completion_reports/phases/PHASE_2_SERIALIZATION_COMPLETE.md` | 115 | Relative link target missing: ./TASK_2_2_IMPORTS_UPDATE_COMPLETE.md | ./TASK_2_2_IMPORTS_UPDATE_COMPLETE.md |
| `links` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_1_COMPLETE.md` | 339 | Relative link target missing: ./KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md | ./KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md |
| `links` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_KNOWLEDGE_GRAPHS_PLAN_REVIEW.md` | 355 | Relative link target missing: ./KNOWLEDGE_GRAPHS_CURRENT_STATUS.md | ./KNOWLEDGE_GRAPHS_CURRENT_STATUS.md |
| `links` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_KNOWLEDGE_GRAPHS_PLAN_REVIEW.md` | 356 | Relative link target missing: ./KNOWLEDGE_GRAPHS_NEXT_STEPS.md | ./KNOWLEDGE_GRAPHS_NEXT_STEPS.md |
| `links` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_KNOWLEDGE_GRAPHS_PLAN_REVIEW.md` | 357 | Relative link target missing: ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md | ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md |
| `links` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_KNOWLEDGE_GRAPHS_PLAN_REVIEW.md` | 358 | Relative link target missing: ./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md | ./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md |
| `links` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_KNOWLEDGE_GRAPHS_PLAN_REVIEW.md` | 359 | Relative link target missing: ./KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md | ./KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md |
| `links` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 106 | Relative link target missing: ./MULTIMEDIA_MIGRATION_GUIDE.md | ./MULTIMEDIA_MIGRATION_GUIDE.md |
| `links` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 107 | Relative link target missing: ./PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md | ./PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 7 | Relative link target missing: getting_started_new.md | getting_started_new.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 8 | Relative link target missing: ../examples/ | ../examples/ |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 9 | Relative link target missing: api_reference.md | api_reference.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 10 | Relative link target missing: guides/DEPLOYMENT_GUIDE.md | guides/DEPLOYMENT_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 15 | Relative link target missing: guides/THEOREM_PROVER_INTEGRATION_GUIDE.md | guides/THEOREM_PROVER_INTEGRATION_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 16 | Relative link target missing: guides/GRAPHRAG_PRODUCTION_GUIDE.md | guides/GRAPHRAG_PRODUCTION_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 17 | Relative link target missing: guides/KNOWLEDGE_GRAPH_GUIDE.md | guides/KNOWLEDGE_GRAPH_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 18 | Relative link target missing: data_provenance.md | data_provenance.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 21 | Relative link target missing: guides/MCP_TOOLS_COMPREHENSIVE_REFERENCE.md | guides/MCP_TOOLS_COMPREHENSIVE_REFERENCE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 22 | Relative link target missing: guides/TESTING_GUIDE.md | guides/TESTING_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 23 | Relative link target missing: developer_guide.md | developer_guide.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 24 | Relative link target missing: performance_optimization.md | performance_optimization.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 27 | Relative link target missing: guides/MULTIMEDIA_PROCESSING_GUIDE.md | guides/MULTIMEDIA_PROCESSING_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 28 | Relative link target missing: comprehensive_web_scraping_guide.md | comprehensive_web_scraping_guide.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 29 | Relative link target missing: guides/MEDIA_TOOLS_GUIDE.md | guides/MEDIA_TOOLS_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 32 | Relative link target missing: guides/DEPLOYMENT_GUIDE.md | guides/DEPLOYMENT_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 33 | Relative link target missing: security_governance.md | security_governance.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 34 | Relative link target missing: unified_dashboard.md | unified_dashboard.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 35 | Relative link target missing: integration_examples.md | integration_examples.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 40 | Relative link target missing: guides/IPFS_GUIDE.md | guides/IPFS_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 41 | Relative link target missing: ipld_optimization.md | ipld_optimization.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 42 | Relative link target missing: performance_optimization.md | performance_optimization.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 45 | Relative link target missing: guides/EMBEDDINGS_GUIDE.md | guides/EMBEDDINGS_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 46 | Relative link target missing: guides/GRAPHRAG_GUIDE.md | guides/GRAPHRAG_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 47 | Relative link target missing: guides/LLM_INTEGRATION_GUIDE.md | guides/LLM_INTEGRATION_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 50 | Relative link target missing: guides/DATASET_GUIDE.md | guides/DATASET_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 51 | Relative link target missing: FILE_CONVERSION_PROS_CONS.md | FILE_CONVERSION_PROS_CONS.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 52 | Relative link target missing: FILE_CONVERSION_SYSTEMS_ANALYSIS.md | FILE_CONVERSION_SYSTEMS_ANALYSIS.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 53 | Relative link target missing: FILE_CONVERSION_MERGE_FEASIBILITY.md | FILE_CONVERSION_MERGE_FEASIBILITY.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 54 | Relative link target missing: FILE_CONVERSION_INTEGRATION_PLAN.md | FILE_CONVERSION_INTEGRATION_PLAN.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 55 | Relative link target missing: guides/PIPELINE_GUIDE.md | guides/PIPELINE_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 56 | Relative link target missing: guides/ANALYTICS_GUIDE.md | guides/ANALYTICS_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 59 | Relative link target missing: guides/AUTH_GUIDE.md | guides/AUTH_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 60 | Relative link target missing: audit_logging.md | audit_logging.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 61 | Relative link target missing: guides/SECURITY_GUIDE.md | guides/SECURITY_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 66 | Relative link target missing: tutorials/ | tutorials/ |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 67 | Relative link target missing: tutorials/video_guides.md | tutorials/video_guides.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 68 | Relative link target missing: ../examples/ | ../examples/ |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 71 | Relative link target missing: guides/MATHEMATICAL_FOUNDATIONS.md | guides/MATHEMATICAL_FOUNDATIONS.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 72 | Relative link target missing: distributed_features.md | distributed_features.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 73 | Relative link target missing: guides/HPC_GUIDE.md | guides/HPC_GUIDE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 76 | Relative link target missing: workflow_examples.md | workflow_examples.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 77 | Relative link target missing: guides/INDUSTRY_APPLICATIONS.md | guides/INDUSTRY_APPLICATIONS.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 78 | Relative link target missing: guides/RESEARCH_APPLICATIONS.md | guides/RESEARCH_APPLICATIONS.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 83 | Relative link target missing: api_reference.md | api_reference.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 84 | Relative link target missing: guides/MCP_TOOLS_API.md | guides/MCP_TOOLS_API.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 85 | Relative link target missing: guides/ANALYTICS_API.md | guides/ANALYTICS_API.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 88 | Relative link target missing: guides/CONFIGURATION_REFERENCE.md | guides/CONFIGURATION_REFERENCE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 89 | Relative link target missing: docker_deployment.md | docker_deployment.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 90 | Relative link target missing: guides/CLOUD_DEPLOYMENT.md | guides/CLOUD_DEPLOYMENT.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 93 | Relative link target missing: guides/TROUBLESHOOTING.md | guides/TROUBLESHOOTING.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 94 | Relative link target missing: guides/FAQ.md | guides/FAQ.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 95 | Relative link target missing: guides/KNOWN_ISSUES.md | guides/KNOWN_ISSUES.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 100 | Relative link target missing: implementation_notes/SYSTEM_ARCHITECTURE.md | implementation_notes/SYSTEM_ARCHITECTURE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 101 | Relative link target missing: implementation_notes/COMPONENT_DESIGN.md | implementation_notes/COMPONENT_DESIGN.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 102 | Relative link target missing: implementation_notes/DATA_FLOW.md | implementation_notes/DATA_FLOW.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 105 | Relative link target missing: implementation_notes/TESTING_STRATEGY.md | implementation_notes/TESTING_STRATEGY.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 106 | Relative link target missing: implementation_notes/CODE_STANDARDS.md | implementation_notes/CODE_STANDARDS.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 107 | Relative link target missing: implementation_notes/RELEASE_PROCESS.md | implementation_notes/RELEASE_PROCESS.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 111 | Relative link target missing: PROJECT_STRUCTURE.md | PROJECT_STRUCTURE.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 112 | Relative link target missing: ../RELEASE_NOTES.md | ../RELEASE_NOTES.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 113 | Relative link target missing: guides/ROADMAP.md | guides/ROADMAP.md |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 114 | Relative link target missing: ../CHANGELOG.md | ../CHANGELOG.md |
| `links` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 413 | Relative link target missing: KNOWLEDGE_GRAPHS_LINEAGE_MIGRATION.md | KNOWLEDGE_GRAPHS_LINEAGE_MIGRATION.md |
| `links` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 414 | Relative link target missing: KNOWLEDGE_GRAPHS_LINEAGE_FAQ.md | KNOWLEDGE_GRAPHS_LINEAGE_FAQ.md |
| `links` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 415 | Relative link target missing: KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md | KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md |
| `links` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 416 | Relative link target missing: PHASE_2_TASK_2_2_USAGE_ANALYSIS.md | PHASE_2_TASK_2_2_USAGE_ANALYSIS.md |
| `links` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 417 | Relative link target missing: PHASE_2_SESSIONS_7_8_COMPLETE.md | PHASE_2_SESSIONS_7_8_COMPLETE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 1038 | Relative link target missing: ./PATH_A_IMPLEMENTATION_COMPLETE.md | ./PATH_A_IMPLEMENTATION_COMPLETE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 1039 | Relative link target missing: ./PATH_B_FINAL_STATUS.md | ./PATH_B_FINAL_STATUS.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 1040 | Relative link target missing: ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md | ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_CURRENT_STATUS.md` | 332 | Relative link target missing: ./KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md | ./KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_CURRENT_STATUS.md` | 333 | Relative link target missing: ./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md | ./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_CURRENT_STATUS.md` | 334 | Relative link target missing: ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md | ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_CURRENT_STATUS.md` | 335 | Relative link target missing: ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md | ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 387 | Relative link target missing: ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md | ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 389 | Relative link target missing: ./PHASE_2_3_IMPLEMENTATION_PLAN.md | ./PHASE_2_3_IMPLEMENTATION_PLAN.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 393 | Relative link target missing: ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md | ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 395 | Relative link target missing: ./SESSION_PHASE_2_CRITICAL_IMPLEMENTATION_COMPLETE.md | ./SESSION_PHASE_2_CRITICAL_IMPLEMENTATION_COMPLETE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 480 | Relative link target missing: ./PHASE_2_3_IMPLEMENTATION_PLAN.md | ./PHASE_2_3_IMPLEMENTATION_PLAN.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 484 | Relative link target missing: ./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md | ./KNOWLEDGE_GRAPHS_PHASE_1_COMPLETE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 485 | Relative link target missing: ./SESSION_PHASE_2_CRITICAL_IMPLEMENTATION_COMPLETE.md | ./SESSION_PHASE_2_CRITICAL_IMPLEMENTATION_COMPLETE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 488 | Relative link target missing: ./KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md | ./KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 489 | Relative link target missing: ./KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md | ./KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 492 | Relative link target missing: ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md | ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 493 | Relative link target missing: ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md | ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 494 | Relative link target missing: ./KNOWLEDGE_GRAPHS_NEXT_STEPS.md | ./KNOWLEDGE_GRAPHS_NEXT_STEPS.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 7 | Relative link target missing: ./KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md | ./KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 8 | Relative link target missing: ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md | ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 548 | Relative link target missing: ./KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md | ./KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 553 | Relative link target missing: ./KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md | ./KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 557 | Relative link target missing: ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md | ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_PLAN_INDEX.md` | 17 | Relative link target missing: ./KNOWLEDGE_GRAPHS_6_WEEK_TIMELINE.md | ./KNOWLEDGE_GRAPHS_6_WEEK_TIMELINE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_PLAN_INDEX.md` | 66 | Relative link target missing: ./KNOWLEDGE_GRAPHS_6_WEEK_TIMELINE.md | ./KNOWLEDGE_GRAPHS_6_WEEK_TIMELINE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_PLAN_INDEX.md` | 88 | Relative link target missing: ./PATH_A_IMPLEMENTATION_COMPLETE.md | ./PATH_A_IMPLEMENTATION_COMPLETE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_PLAN_INDEX.md` | 89 | Relative link target missing: ./PATH_B_FINAL_STATUS.md | ./PATH_B_FINAL_STATUS.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_PLAN_INDEX.md` | 92 | Relative link target missing: ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md | ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_PLAN_INDEX.md` | 93 | Relative link target missing: ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md | ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_PLAN_INDEX.md` | 94 | Relative link target missing: ./KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md | ./KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_PLAN_INDEX.md` | 205 | Relative link target missing: ./KNOWLEDGE_GRAPHS_6_WEEK_TIMELINE.md | ./KNOWLEDGE_GRAPHS_6_WEEK_TIMELINE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_SUMMARY.md` | 303 | Relative link target missing: ./PATH_A_IMPLEMENTATION_COMPLETE.md | ./PATH_A_IMPLEMENTATION_COMPLETE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_SUMMARY.md` | 304 | Relative link target missing: ./PATH_B_FINAL_STATUS.md | ./PATH_B_FINAL_STATUS.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPROVEMENT_SUMMARY.md` | 305 | Relative link target missing: ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md | ./KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md |
| `anchors` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_MASTER_REFACTORING_PLAN_2026_02_16.md` | 22 | In-page anchor not found: #timeline--resources | archive-prefix:docs/archive/ |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 40 | Relative link target missing: ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md | ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 205 | Relative link target missing: ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md | ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md |
| `links` | `docs/archive/knowledge_graphs/session_reports/KNOWLEDGE_GRAPHS_PHASE_3_PROGRESS.md` | 224 | Relative link target missing: ./KNOWLEDGE_GRAPHS_MASTER_REFACTORING_PLAN_2026_02_16.md | ./KNOWLEDGE_GRAPHS_MASTER_REFACTORING_PLAN_2026_02_16.md |
| `links` | `docs/archive/knowledge_graphs/session_reports/KNOWLEDGE_GRAPHS_PHASE_3_PROGRESS.md` | 225 | Relative link target missing: ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE_2026_02_16.md | ./KNOWLEDGE_GRAPHS_QUICK_REFERENCE_2026_02_16.md |
| `links` | `docs/archive/knowledge_graphs/session_reports/KNOWLEDGE_GRAPHS_PHASE_3_PROGRESS.md` | 226 | Relative link target missing: ./KNOWLEDGE_GRAPHS_IMPLEMENTATION_GUIDE_2026_02_16.md | ./KNOWLEDGE_GRAPHS_IMPLEMENTATION_GUIDE_2026_02_16.md |
| `links` | `docs/archive/knowledge_graphs/session_reports/KNOWLEDGE_GRAPHS_PHASE_3_PROGRESS.md` | 227 | Relative link target missing: ./KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md | ./KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md |
| `anchors` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 43 | In-page anchor not found: #phase-4-documentation--examples | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 44 | In-page anchor not found: #phase-5-testing--quality | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 39 | In-page anchor not found: #5-migration--compatibility | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 44 | In-page anchor not found: #10-timeline--resources | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 69 | In-page anchor not found: #6-migration--compatibility | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 74 | In-page anchor not found: #11-timeline--resources | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 42 | In-page anchor not found: #problems--opportunities | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 47 | In-page anchor not found: #timeline--phases | archive-prefix:docs/archive/ |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 19 | Relative link target missing: ./PROCESSORS_PLAN_QUICK_REFERENCE.md | ./PROCESSORS_PLAN_QUICK_REFERENCE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 26 | Relative link target missing: ./PROCESSORS_VISUAL_SUMMARY.md | ./PROCESSORS_VISUAL_SUMMARY.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 35 | Relative link target missing: ./PROCESSORS_PHASES_1_7_COMPLETE.md | ./PROCESSORS_PHASES_1_7_COMPLETE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 41 | Relative link target missing: ./PROCESSORS_REFACTORING_COMPLETE.md | ./PROCESSORS_REFACTORING_COMPLETE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 46 | Relative link target missing: ./PROCESSORS_MIGRATION_GUIDE.md | ./PROCESSORS_MIGRATION_GUIDE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 98 | Relative link target missing: ./PROCESSORS_VISUAL_SUMMARY.md | ./PROCESSORS_VISUAL_SUMMARY.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 104 | Relative link target missing: ./PROCESSORS_PLAN_QUICK_REFERENCE.md | ./PROCESSORS_PLAN_QUICK_REFERENCE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 107 | Relative link target missing: ./PROCESSORS_MIGRATION_GUIDE.md | ./PROCESSORS_MIGRATION_GUIDE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 110 | Relative link target missing: ./PROCESSORS_PHASES_1_7_COMPLETE.md | ./PROCESSORS_PHASES_1_7_COMPLETE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 161 | Relative link target missing: ./PROCESSORS_VISUAL_SUMMARY.md | ./PROCESSORS_VISUAL_SUMMARY.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 162 | Relative link target missing: ./PROCESSORS_PLAN_QUICK_REFERENCE.md | ./PROCESSORS_PLAN_QUICK_REFERENCE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 163 | Relative link target missing: ./PROCESSORS_MIGRATION_GUIDE.md | ./PROCESSORS_MIGRATION_GUIDE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 168 | Relative link target missing: ./PROCESSORS_PLAN_QUICK_REFERENCE.md | ./PROCESSORS_PLAN_QUICK_REFERENCE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 169 | Relative link target missing: ./PROCESSORS_PHASES_1_7_COMPLETE.md | ./PROCESSORS_PHASES_1_7_COMPLETE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 173 | Relative link target missing: ./PROCESSORS_VISUAL_SUMMARY.md | ./PROCESSORS_VISUAL_SUMMARY.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 178 | Relative link target missing: ./PROCESSORS_MIGRATION_GUIDE.md | ./PROCESSORS_MIGRATION_GUIDE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_DOCUMENTATION_INDEX.md` | 179 | Relative link target missing: ./PROCESSORS_PLAN_QUICK_REFERENCE.md | ./PROCESSORS_PLAN_QUICK_REFERENCE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 12 | Relative link target missing: PROCESSORS_REFACTORING_SUMMARY_2026.md | PROCESSORS_REFACTORING_SUMMARY_2026.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 13 | Relative link target missing: PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md | PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 14 | Relative link target missing: PROCESSORS_REFACTORING_VISUAL_ROADMAP_2026.md | PROCESSORS_REFACTORING_VISUAL_ROADMAP_2026.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 26 | Relative link target missing: PROCESSORS_REFACTORING_SUMMARY_2026.md | PROCESSORS_REFACTORING_SUMMARY_2026.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 29 | Relative link target missing: PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md | PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 32 | Relative link target missing: PROCESSORS_REFACTORING_VISUAL_ROADMAP_2026.md | PROCESSORS_REFACTORING_VISUAL_ROADMAP_2026.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 35 | Relative link target missing: PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md | PROCESSORS_REFACTORING_QUICK_REFERENCE_2026.md#quick-migration-guide |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 41 | Relative link target missing: PROCESSORS_REFACTORING_SUMMARY_2026.md | PROCESSORS_REFACTORING_SUMMARY_2026.md#-critical-issues-identified |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 180 | Relative link target missing: PROCESSORS_STATUS_2026_02_16.md | PROCESSORS_STATUS_2026_02_16.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 181 | Relative link target missing: PROCESSORS_ENGINES_GUIDE.md | PROCESSORS_ENGINES_GUIDE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 182 | Relative link target missing: PROCESSORS_MIGRATION_GUIDE.md | PROCESSORS_MIGRATION_GUIDE.md |
| `links` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_INDEX_2026.md` | 183 | Relative link target missing: PROCESSORS_CHANGELOG.md | PROCESSORS_CHANGELOG.md |
| `links` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 5 | Relative link target missing: PHASES_STATUS.md | PHASES_STATUS.md |
| `anchors` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 37 | In-page anchor not found: #5-phase-c-observability--diagnostics | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 38 | In-page anchor not found: #6-phase-d-api-versioning--stability | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 42 | In-page anchor not found: #10-timeline--prioritisation | archive-prefix:docs/archive/ |
| `links` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 402 | Relative link target missing: PHASES_STATUS.md | PHASES_STATUS.md |
| `links` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 336 | Relative link target missing: PHASES_STATUS.md | PHASES_STATUS.md |
| `anchors` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v7.md` | 36 | In-page anchor not found: #3-phase-m-flask-removal | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v7.md` | 37 | In-page anchor not found: #4-phase-n-anyio-migration-validation | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v7.md` | 38 | In-page anchor not found: #5-phase-o-docker-image-refresh | archive-prefix:docs/archive/ |
| `anchors` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 35 | In-page anchor not found: #3-critical-issues--code-analysis-results | archive-prefix:docs/archive/ |
| `links` | `docs/archive/reorganization/root_reorganization.md` | 179 | Relative link target missing: archive/deprecated/claude.md | archive/deprecated/claude.md |
| `links` | `docs/archive/reorganization/root_reorganization.md` | 180 | Relative link target missing: ../scripts/README.md | ../scripts/README.md |
| `links` | `docs/archive/reorganization/root_reorganization.md` | 181 | Relative link target missing: ../tests/README.md | ../tests/README.md |
| `links` | `docs/archived_stubs/README.md` | 34 | Relative link target missing: ../PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md | ../PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md |
| `links` | `docs/archived_stubs/README.md` | 35 | Relative link target missing: ../PROCESSORS_IMPLEMENTATION_CHECKLIST.md | ../PROCESSORS_IMPLEMENTATION_CHECKLIST.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 261 | Relative link target missing: ./QUICKSTART.md | ./QUICKSTART.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 262 | Relative link target missing: ./FEATURE_MATRIX.md | ./FEATURE_MATRIX.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 263 | Relative link target missing: ../../docs/knowledge_graphs/USER_GUIDE.md | ../../docs/knowledge_graphs/USER_GUIDE.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 264 | Relative link target missing: ./IMPLEMENTATION_STATUS.md | ./IMPLEMENTATION_STATUS.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 267 | Relative link target missing: ./ROADMAP.md | ./ROADMAP.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 268 | Relative link target missing: ./DEFERRED_FEATURES.md | ./DEFERRED_FEATURES.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 269 | Relative link target missing: ../../docs/knowledge_graphs/CONTRIBUTING.md | ../../docs/knowledge_graphs/CONTRIBUTING.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 273 | Relative link target missing: ./FEATURE_MATRIX.md | ./FEATURE_MATRIX.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 274 | Relative link target missing: ./COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md | ./COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 275 | Relative link target missing: ./IMPLEMENTATION_STATUS.md | ./IMPLEMENTATION_STATUS.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY_2026_02_18.md` | 276 | Relative link target missing: ./ROADMAP.md | ./ROADMAP.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 216 | Relative link target missing: INDEX.md | INDEX.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 217 | Relative link target missing: IMPLEMENTATION_STATUS.md | IMPLEMENTATION_STATUS.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 220 | Relative link target missing: ../../docs/knowledge_graphs/USER_GUIDE.md | ../../docs/knowledge_graphs/USER_GUIDE.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 221 | Relative link target missing: ../../docs/knowledge_graphs/API_REFERENCE.md | ../../docs/knowledge_graphs/API_REFERENCE.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 224 | Relative link target missing: ../../docs/knowledge_graphs/CONTRIBUTING.md | ../../docs/knowledge_graphs/CONTRIBUTING.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 225 | Relative link target missing: ROADMAP.md | ROADMAP.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 226 | Relative link target missing: ../../tests/knowledge_graphs/TEST_STATUS.md | ../../tests/knowledge_graphs/TEST_STATUS.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 229 | Relative link target missing: IMPLEMENTATION_STATUS.md | IMPLEMENTATION_STATUS.md |
| `links` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 230 | Relative link target missing: CHANGELOG_KNOWLEDGE_GRAPHS.md | CHANGELOG_KNOWLEDGE_GRAPHS.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/FEATURE_MATRIX.md` | 205 | Relative link target missing: ROADMAP.md | ROADMAP.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 101 | Relative link target missing: ../../tests/knowledge_graphs/TEST_STATUS.md | ../../tests/knowledge_graphs/TEST_STATUS.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 181 | Relative link target missing: CHANGELOG_KNOWLEDGE_GRAPHS.md | CHANGELOG_KNOWLEDGE_GRAPHS.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 199 | Relative link target missing: ROADMAP.md | ROADMAP.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 207 | Relative link target missing: ../../docs/knowledge_graphs/USER_GUIDE.md | ../../docs/knowledge_graphs/USER_GUIDE.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 208 | Relative link target missing: ../../docs/knowledge_graphs/API_REFERENCE.md | ../../docs/knowledge_graphs/API_REFERENCE.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 211 | Relative link target missing: ROADMAP.md | ROADMAP.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 212 | Relative link target missing: ../../docs/knowledge_graphs/CONTRIBUTING.md | ../../docs/knowledge_graphs/CONTRIBUTING.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 213 | Relative link target missing: CHANGELOG_KNOWLEDGE_GRAPHS.md | CHANGELOG_KNOWLEDGE_GRAPHS.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 216 | Relative link target missing: ../../docs/knowledge_graphs/MIGRATION_GUIDE.md | ../../docs/knowledge_graphs/MIGRATION_GUIDE.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 217 | Relative link target missing: ../../docs/knowledge_graphs/ARCHITECTURE.md | ../../docs/knowledge_graphs/ARCHITECTURE.md |
| `links` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_STATUS.md` | 218 | Relative link target missing: INDEX.md | INDEX.md |
| `anchors` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 27 | In-page anchor not found: #2-high-priority---code-quality | archive-prefix:docs/knowledge_graphs/archive/ |
| `anchors` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 28 | In-page anchor not found: #3-medium-priority---code-cleanup | archive-prefix:docs/knowledge_graphs/archive/ |
| `links` | `docs/logic/CEC/ARCHIVE/CEC_REFACTORING_EXECUTIVE_SUMMARY.md` | 173 | Relative link target missing: ./STATUS.md | ./STATUS.md |
| `links` | `docs/logic/CEC/ARCHIVE/CEC_REFACTORING_EXECUTIVE_SUMMARY.md` | 178 | Relative link target missing: ./PERFORMANCE_OPTIMIZATION_PLAN.md | ./PERFORMANCE_OPTIMIZATION_PLAN.md |
| `links` | `docs/logic/CEC/ARCHIVE/CEC_REFACTORING_EXECUTIVE_SUMMARY.md` | 179 | Relative link target missing: ./EXTENDED_NL_SUPPORT_ROADMAP.md | ./EXTENDED_NL_SUPPORT_ROADMAP.md |
| `links` | `docs/logic/CEC/ARCHIVE/CEC_REFACTORING_EXECUTIVE_SUMMARY.md` | 180 | Relative link target missing: ./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md | ./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md |
| `links` | `docs/logic/CEC/ARCHIVE/CEC_REFACTORING_EXECUTIVE_SUMMARY.md` | 181 | Relative link target missing: ./API_INTERFACE_DESIGN.md | ./API_INTERFACE_DESIGN.md |
| `links` | `docs/logic/CEC/ARCHIVE/CEC_REFACTORING_EXECUTIVE_SUMMARY_2026.md` | 343 | Relative link target missing: ./CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md | ./CEC_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md |
| `links` | `docs/logic/CEC/ARCHIVE/CEC_REFACTORING_EXECUTIVE_SUMMARY_2026.md` | 353 | Relative link target missing: ./STATUS.md | ./STATUS.md |
| `links` | `docs/logic/CEC/ARCHIVE/IMPLEMENTATION_QUICK_START.md` | 201 | Relative link target missing: ./STATUS.md | ./STATUS.md |
| `links` | `docs/logic/CEC/ARCHIVE/IMPLEMENTATION_QUICK_START.md` | 202 | Relative link target missing: ./API_REFERENCE.md | ./API_REFERENCE.md |
| `links` | `docs/logic/CEC/ARCHIVE/IMPLEMENTATION_QUICK_START.md` | 203 | Relative link target missing: ./CEC_SYSTEM_GUIDE.md | ./CEC_SYSTEM_GUIDE.md |
| `links` | `docs/logic/CEC/ARCHIVE/NATIVE_INTEGRATION.md` | 223 | Relative link target missing: ../../scripts/demo/demonstrate_native_dcec.py | ../../scripts/demo/demonstrate_native_dcec.py |
| `links` | `docs/logic/CEC/ARCHIVE/NATIVE_INTEGRATION.md` | 224 | Relative link target missing: ../../scripts/demo/demonstrate_native_integration.py | ../../scripts/demo/demonstrate_native_integration.py |
| `links` | `docs/logic/CEC/ARCHIVE/NATIVE_MIGRATION_SUMMARY.md` | 134 | Relative link target missing: ./CEC_SYSTEM_GUIDE.md | ./CEC_SYSTEM_GUIDE.md |
| `links` | `docs/logic/CEC/ARCHIVE/NATIVE_MIGRATION_SUMMARY.md` | 170 | Relative link target missing: ./CEC_SYSTEM_GUIDE.md | ./CEC_SYSTEM_GUIDE.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 325 | Relative link target missing: ./STATUS.md | ./STATUS.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 330 | Relative link target missing: ./QUICKSTART.md | ./QUICKSTART.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 331 | Relative link target missing: ./API_REFERENCE.md | ./API_REFERENCE.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 332 | Relative link target missing: ./CEC_SYSTEM_GUIDE.md | ./CEC_SYSTEM_GUIDE.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 335 | Relative link target missing: ./DEVELOPER_GUIDE.md | ./DEVELOPER_GUIDE.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 336 | Relative link target missing: ./MIGRATION_GUIDE.md | ./MIGRATION_GUIDE.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 339 | Relative link target missing: ./API_INTERFACE_DESIGN.md | ./API_INTERFACE_DESIGN.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 340 | Relative link target missing: ./PERFORMANCE_OPTIMIZATION_PLAN.md | ./PERFORMANCE_OPTIMIZATION_PLAN.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 341 | Relative link target missing: ./EXTENDED_NL_SUPPORT_ROADMAP.md | ./EXTENDED_NL_SUPPORT_ROADMAP.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 342 | Relative link target missing: ./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md | ./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md |
| `links` | `docs/logic/CEC/ARCHIVE/PHASE_3_TRACKER.md` | 334 | Relative link target missing: ./STATUS.md | ./STATUS.md |
| `links` | `docs/logic/CEC/ARCHIVE/REFACTORING_QUICK_REFERENCE.md` | 21 | Relative link target missing: ./API_INTERFACE_DESIGN.md | ./API_INTERFACE_DESIGN.md |
| `links` | `docs/logic/CEC/ARCHIVE/REFACTORING_QUICK_REFERENCE.md` | 28 | Relative link target missing: ./PERFORMANCE_OPTIMIZATION_PLAN.md | ./PERFORMANCE_OPTIMIZATION_PLAN.md |
| `links` | `docs/logic/CEC/ARCHIVE/REFACTORING_QUICK_REFERENCE.md` | 35 | Relative link target missing: ./EXTENDED_NL_SUPPORT_ROADMAP.md | ./EXTENDED_NL_SUPPORT_ROADMAP.md |
| `links` | `docs/logic/CEC/ARCHIVE/REFACTORING_QUICK_REFERENCE.md` | 42 | Relative link target missing: ./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md | ./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md |
| `links` | `docs/logic/CEC/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 861 | Relative link target missing: ./STATUS.md | ./STATUS.md |
| `links` | `docs/logic/CEC/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 863 | Relative link target missing: ./PERFORMANCE_OPTIMIZATION_PLAN.md | ./PERFORMANCE_OPTIMIZATION_PLAN.md |
| `links` | `docs/logic/CEC/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 864 | Relative link target missing: ./EXTENDED_NL_SUPPORT_ROADMAP.md | ./EXTENDED_NL_SUPPORT_ROADMAP.md |
| `links` | `docs/logic/CEC/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 865 | Relative link target missing: ./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md | ./ADDITIONAL_THEOREM_PROVERS_STRATEGY.md |
| `links` | `docs/logic/CEC/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 866 | Relative link target missing: ./API_INTERFACE_DESIGN.md | ./API_INTERFACE_DESIGN.md |
| `links` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 11 | Relative link target missing: ./STATUS_2026.md | ./STATUS_2026.md |
| `links` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 48 | Relative link target missing: ./STATUS_2026.md | ./STATUS_2026.md |
| `links` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 254 | Relative link target missing: ./STATUS_2026.md | ./STATUS_2026.md |
| `links` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 293 | Relative link target missing: ./STATUS_2026.md | ./STATUS_2026.md |
| `anchors` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` | 50 | In-page anchor not found: #phase-1-code-consolidation | archive-path-segment |
| `anchors` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` | 51 | In-page anchor not found: #phase-2-architecture-improvements | archive-path-segment |
| `anchors` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` | 52 | In-page anchor not found: #phase-3-documentation--testing | archive-path-segment |
| `anchors` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` | 53 | In-page anchor not found: #phase-4-performance--optimization | archive-path-segment |
| `links` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_EXECUTIVE_SUMMARY_2026.md` | 326 | Relative link target missing: ./STATUS_2026.md | ./STATUS_2026.md |
| `links` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_EXECUTIVE_SUMMARY_2026_REVISED.md` | 292 | Relative link target missing: ./STATUS_2026.md | ./STATUS_2026.md |
| `links` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_EXECUTIVE_SUMMARY_2026_REVISED.md` | 293 | Relative link target missing: ./UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md | ./UNIFIED_REFACTORING_ROADMAP_2026_REVISED.md |
| `links` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 27 | Relative link target missing: ./STATUS_2026.md | ./STATUS_2026.md |
| `anchors` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 43 | In-page anchor not found: #deployment--operations | archive-path-segment |
| `anchors` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 46 | In-page anchor not found: #timeline--resources | archive-path-segment |
| `links` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 805 | Relative link target missing: ./STATUS_2026.md | ./STATUS_2026.md |
| `links` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 807 | Relative link target missing: ./TRACK3_PRODUCTION_READINESS.md | ./TRACK3_PRODUCTION_READINESS.md |
| `links` | `docs/logic/archive/REFACTORING_STATUS_FINAL.md` | 451 | Relative link target missing: ./UNIFIED_CONVERTER_GUIDE.md | ./UNIFIED_CONVERTER_GUIDE.md |
| `links` | `docs/logic/archive/REFACTORING_STATUS_FINAL.md` | 452 | Relative link target missing: ./MIGRATION_GUIDE.md | ./MIGRATION_GUIDE.md |
| `links` | `docs/logic/archive/REFACTORING_STATUS_FINAL.md` | 453 | Relative link target missing: ./zkp/README.md | ./zkp/README.md |
| `links` | `docs/logic/docs/archive/phases_2026/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 408 | Relative link target missing: ./DEPLOYMENT_GUIDE.md | ./DEPLOYMENT_GUIDE.md |
| `links` | `docs/logic/docs/archive/phases_2026/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 409 | Relative link target missing: ./SECURITY_GUIDE.md | ./SECURITY_GUIDE.md |
| `links` | `docs/logic/docs/archive/phases_2026/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 410 | Relative link target missing: ./DEPLOYMENT_GUIDE.md | ./DEPLOYMENT_GUIDE.md |
| `links` | `docs/logic/docs/archive/phases_2026/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 411 | Relative link target missing: ./PERFORMANCE_TUNING.md | ./PERFORMANCE_TUNING.md |
| `links` | `docs/logic/docs/archive/phases_2026/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 412 | Relative link target missing: ./TROUBLESHOOTING.md | ./TROUBLESHOOTING.md |
| `links` | `docs/logic/docs/archive/phases_2026/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 413 | Relative link target missing: ./API_VERSIONING.md | ./API_VERSIONING.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 643 | Relative link target missing: ./KNOWN_LIMITATIONS.md | ./KNOWN_LIMITATIONS.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 644 | Relative link target missing: ./INFERENCE_RULES_INVENTORY.md | ./INFERENCE_RULES_INVENTORY.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 408 | Relative link target missing: ./DEPLOYMENT_GUIDE.md | ./DEPLOYMENT_GUIDE.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 409 | Relative link target missing: ./SECURITY_GUIDE.md | ./SECURITY_GUIDE.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 410 | Relative link target missing: ./DEPLOYMENT_GUIDE.md | ./DEPLOYMENT_GUIDE.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 411 | Relative link target missing: ./PERFORMANCE_TUNING.md | ./PERFORMANCE_TUNING.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 412 | Relative link target missing: ./TROUBLESHOOTING.md | ./TROUBLESHOOTING.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_COMPLETION_REPORT.md` | 413 | Relative link target missing: ./API_VERSIONING.md | ./API_VERSIONING.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 102 | Relative link target missing: ./KNOWN_LIMITATIONS.md | ./KNOWN_LIMITATIONS.md |
| `links` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 143 | Relative link target missing: ./KNOWN_LIMITATIONS.md | ./KNOWN_LIMITATIONS.md |
| `links` | `docs/logic/zkp/ARCHIVE/ANALYSIS_NAVIGATION.md` | 300 | Relative link target missing: QUICKSTART.md | QUICKSTART.md |
| `links` | `docs/logic/zkp/ARCHIVE/ANALYSIS_NAVIGATION.md` | 301 | Relative link target missing: EXAMPLES.md | EXAMPLES.md |
| `links` | `docs/logic/zkp/ARCHIVE/ANALYSIS_NAVIGATION.md` | 304 | Relative link target missing: ARCHIVE/ | ARCHIVE/ |
| `links` | `docs/logic/zkp/ARCHIVE/COMPREHENSIVE_REFACTORING_PLAN_2026_02_18_NEW.md` | 295 | Relative link target missing: file.md | file.md |
| `repo_paths` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 309 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md | migration-substring:migration |
| `repo_paths` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 310 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md | migration-substring:migration |
| `repo_paths` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 311 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md | migration-substring:migration |
| `repo_paths` | `docs/DEPRECATION_SCHEDULE.md` | 155 | Referenced repository path not found: examples/file_converter/ | migration-substring:deprecat |
| `repo_paths` | `docs/DEPRECATION_TIMELINE.md` | 233 | Referenced repository path not found: data_transformation/car_conversion.py | migration-substring:deprecat |
| `repo_paths` | `docs/DEPRECATION_TIMELINE.md` | 234 | Referenced repository path not found: data_transformation/jsonl_to_parquet.py | migration-substring:deprecat |
| `repo_paths` | `docs/DEPRECATION_TIMELINE.md` | 235 | Referenced repository path not found: data_transformation/dataset_serialization.py | migration-substring:deprecat |
| `repo_paths` | `docs/DEPRECATION_TIMELINE.md` | 236 | Referenced repository path not found: data_transformation/ipfs_parquet_to_car.py | migration-substring:deprecat |
| `repo_paths` | `docs/FILE_CONVERTER_MIGRATION_GUIDE.md` | 246 | Referenced repository path not found: examples/file_converter/basic_usage.py | migration-substring:migration |
| `repo_paths` | `docs/FILE_CONVERTER_MIGRATION_GUIDE.md` | 247 | Referenced repository path not found: examples/file_converter/batch_processing.py | migration-substring:migration |
| `repo_paths` | `docs/FILE_CONVERTER_MIGRATION_GUIDE.md` | 248 | Referenced repository path not found: examples/file_converter/custom_backend.py | migration-substring:migration |
| `repo_paths` | `docs/MIGRATION_CHANGELOG.md` | 33 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md | migration-substring:migration |
| `repo_paths` | `docs/MIGRATION_CHANGELOG.md` | 34 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md | migration-substring:migration |
| `repo_paths` | `docs/MIGRATION_CHANGELOG.md` | 36 | Referenced repository path not found: docs/FINAL_STATUS_REPORT.md | migration-substring:migration |
| `repo_paths` | `docs/MIGRATION_CHANGELOG.md` | 37 | Referenced repository path not found: docs/PHASE_7_TESTING_COMPLETE.md | migration-substring:migration |
| `repo_paths` | `docs/MIGRATION_TOOLS_USER_GUIDE.md` | 493 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md | migration-substring:migration |
| `repo_paths` | `docs/MIGRATION_TOOLS_USER_GUIDE.md` | 494 | Referenced repository path not found: docs/examples/migration/ | migration-substring:migration |
| `repo_paths` | `docs/architecture/submodule_deprecation.md` | 15 | Referenced repository path not found: ipfs_datasets_py/data_transformation/multimedia/omni_converter_mk2/ | migration-substring:deprecat |
| `repo_paths` | `docs/architecture/submodule_deprecation.md` | 16 | Referenced repository path not found: ipfs_datasets_py/data_transformation/multimedia/convert_to_txt_based_on_mime_type/ | migration-substring:deprecat |
| `repo_paths` | `docs/architecture/submodule_deprecation.md` | 22 | Referenced repository path not found: ipfs_datasets_py/file_converter/ | migration-substring:deprecat |
| `repo_paths` | `docs/archive/completion_reports/COMPREHENSIVE_REFACTORING_DOCUMENTATION_UPDATED.md` | 5 | Referenced repository path not found: .github/scripts | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/COMPREHENSIVE_REFACTORING_DOCUMENTATION_UPDATED.md` | 316 | Referenced repository path not found: .github/scripts/test_autohealing_system_refactored.py:81 | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/COMPREHENSIVE_REFACTORING_DOCUMENTATION_UPDATED.md` | 321 | Referenced repository path not found: ipfs_datasets_py/utils/workflows/fixer.py:210 | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/DOCUMENTATION_CONSOLIDATION_COMPLETE.md` | 26 | Referenced repository path not found: guides/cicd/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/DOCUMENTATION_CONSOLIDATION_COMPLETE.md` | 37 | Referenced repository path not found: docs/modules/logic/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/DOCUMENTATION_CONSOLIDATION_COMPLETE.md` | 40 | Referenced repository path not found: docs/modules/logic/archive/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/GITHUB_OPTIMIZERS_REFACTORING_SUMMARY.md` | 9 | Referenced repository path not found: .github/scripts | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/GITHUB_OPTIMIZERS_REFACTORING_SUMMARY.md` | 362 | Referenced repository path not found: docs/REFACTORING_PLAN_GITHUB_UTILS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/GITHUB_OPTIMIZERS_REFACTORING_SUMMARY.md` | 363 | Referenced repository path not found: docs/UTILS_REFACTORING_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/IMPLEMENTATION_SUMMARY_REFACTORING.md` | 5 | Referenced repository path not found: .github/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/IMPLEMENTATION_SUMMARY_REFACTORING.md` | 74 | Referenced repository path not found: .github/scripts/github_api_counter_thin.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/IMPLEMENTATION_SUMMARY_REFACTORING.md` | 75 | Referenced repository path not found: .github/scripts/copilot_workflow_helper_thin.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/IMPLEMENTATION_SUMMARY_REFACTORING.md` | 97 | Referenced repository path not found: docs/REFACTORING_PLAN_GITHUB_UTILS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/IMPLEMENTATION_SUMMARY_REFACTORING.md` | 388 | Referenced repository path not found: docs/IMPLEMENTATION_SUMMARY_REFACTORING.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md` | 21 | Referenced repository path not found: web_archiving/common_crawl_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md` | 23 | Referenced repository path not found: state_scrapers/base_scraper.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md` | 80 | Referenced repository path not found: legal_scrapers/common_crawl_scraper.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md` | 112 | Referenced repository path not found: legal_scrapers/registry.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md` | 461 | Referenced repository path not found: docs/PROCESSORS_ROOT_FILES_INVENTORY_2026.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 120 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/storage/backend.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 121 | Referenced repository path not found: tests/unit/knowledge_graphs/test_multi_database.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 212 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/cypher/types.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 214 | Referenced repository path not found: tests/unit/knowledge_graphs/test_spatial_functions.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 215 | Referenced repository path not found: tests/unit/knowledge_graphs/test_temporal_functions.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 216 | Referenced repository path not found: tests/unit/knowledge_graphs/test_math_functions.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 283 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/jsonld/vocabularies/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 288 | Referenced repository path not found: tests/unit/knowledge_graphs/test_vocabularies.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 372 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/jsonld/shacl_validator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 373 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/jsonld/shacl_shapes.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 374 | Referenced repository path not found: tests/unit/knowledge_graphs/test_shacl_validation.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 450 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/jsonld/turtle_writer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 451 | Referenced repository path not found: tests/unit/knowledge_graphs/test_rdf_serialization.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md` | 22 | Referenced repository path not found: processors/graphrag/unified_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md` | 26 | Referenced repository path not found: processors/graphrag/complete_advanced_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md` | 31 | Referenced repository path not found: processors/graphrag/integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md` | 32 | Referenced repository path not found: processors/graphrag/phase7_complete_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md` | 33 | Referenced repository path not found: processors/graphrag/enhanced_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md` | 34 | Referenced repository path not found: processors/graphrag/website_system.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md` | 179 | Referenced repository path not found: processors/graphrag/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_6_BATCH_1_EXECUTION_PLAN.md` | 44 | Referenced repository path not found: utils/workflows/applier.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_6_BATCH_1_EXECUTION_PLAN.md` | 62 | Referenced repository path not found: utils/workflows/validator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_6_ROADMAP.md` | 38 | Referenced repository path not found: utils/workflows/validator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PHASE_6_ROADMAP.md` | 39 | Referenced repository path not found: utils/workflows/applier.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PR_REVIEW_COMMENTS_RESOLUTION.md` | 13 | Referenced repository path not found: .github/scripts/test_autohealing_system_refactored.py:81 | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PR_REVIEW_COMMENTS_RESOLUTION.md` | 37 | Referenced repository path not found: ipfs_datasets_py/utils/workflows/fixer.py:210 | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/PR_REVIEW_COMMENTS_RESOLUTION.md` | 176 | Referenced repository path not found: .github/scripts/test_autohealing_system_refactored.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 5 | Referenced repository path not found: .github/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 39 | Referenced repository path not found: scripts/github_api_counter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 40 | Referenced repository path not found: scripts/copilot_workflow_helper.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 41 | Referenced repository path not found: scripts/github_api_counter_thin.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 42 | Referenced repository path not found: scripts/copilot_workflow_helper_thin.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 110 | Referenced repository path not found: .github/scripts/github_api_counter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 264 | Referenced repository path not found: utils/github/api_client.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 283 | Referenced repository path not found: utils/cli_tools/claude.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 284 | Referenced repository path not found: utils/cli_tools/vscode.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 285 | Referenced repository path not found: utils/cli_tools/gemini.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 298 | Referenced repository path not found: utils/workflows/helpers.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 299 | Referenced repository path not found: utils/workflows/metrics.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 300 | Referenced repository path not found: utils/workflows/logging_utils.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 301 | Referenced repository path not found: utils/workflows/error_handling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 343 | Referenced repository path not found: .github/scripts/github_api_counter_thin.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 344 | Referenced repository path not found: .github/scripts/copilot_helper_thin.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 345 | Referenced repository path not found: .github/scripts/workflow_helper_thin.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 378 | Referenced repository path not found: tests/unit_tests/utils/cache/test_local_cache.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 379 | Referenced repository path not found: tests/unit_tests/utils/cache/test_p2p_cache.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 380 | Referenced repository path not found: tests/unit_tests/utils/cache/test_github_cache.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 381 | Referenced repository path not found: tests/unit_tests/utils/github/test_api_client.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 382 | Referenced repository path not found: tests/unit_tests/utils/github/test_cli_wrapper.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 383 | Referenced repository path not found: tests/unit_tests/utils/github/test_counter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 384 | Referenced repository path not found: tests/unit_tests/utils/cli_tools/test_base.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 385 | Referenced repository path not found: tests/unit_tests/utils/cli_tools/test_copilot.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 390 | Referenced repository path not found: tests/integration/test_cache_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 391 | Referenced repository path not found: tests/integration/test_github_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 392 | Referenced repository path not found: tests/integration/test_cli_tools_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 393 | Referenced repository path not found: tests/integration/test_workflow_utils_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 398 | Referenced repository path not found: .github/workflows/test-unified-cache.yml | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 399 | Referenced repository path not found: .github/workflows/test-thin-wrappers.yml | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 406 | Referenced repository path not found: docs/REFACTORING_PLAN_GITHUB_UTILS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 411 | Referenced repository path not found: docs/guides/UNIFIED_UTILS_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/REFACTORING_PLAN_GITHUB_UTILS.md` | 412 | Referenced repository path not found: docs/guides/MIGRATION_GUIDE_GITHUB_UTILS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/SESSIONS_4_8_SUMMARY.md` | 31 | Referenced repository path not found: extraction/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/SESSIONS_4_8_SUMMARY.md` | 32 | Referenced repository path not found: extraction/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/UTILS_REFACTORING_COMPLETE.md` | 269 | Referenced repository path not found: .github/cache-config.yml | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/UTILS_REFACTORING_PHASE1_COMPLETE.md` | 9 | Referenced repository path not found: docs/REFACTORING_PLAN_GITHUB_UTILS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/UTILS_REFACTORING_PHASE1_COMPLETE.md` | 33 | Referenced repository path not found: .github/cache-config.yml | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/UTILS_REFACTORING_PHASE1_COMPLETE.md` | 225 | Referenced repository path not found: .github/scripts/github_api_counter_thin.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/UTILS_REFACTORING_PHASE1_COMPLETE.md` | 226 | Referenced repository path not found: .github/scripts/copilot_workflow_helper_thin.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/UTILS_REFACTORING_PHASE1_COMPLETE.md` | 275 | Referenced repository path not found: docs/IMPLEMENTATION_SUMMARY_REFACTORING.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/UTILS_REFACTORING_PHASE1_COMPLETE.md` | 276 | Referenced repository path not found: ipfs_datasets_py/optimizers/GITHUB_INTEGRATION.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASES_11_14_COMPREHENSIVE_PLAN.md` | 108 | Referenced repository path not found: legal_scrapers/registry.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_2_SESSIONS_7_8_COMPLETE.md` | 26 | Referenced repository path not found: docs/PHASE_2_TASK_2_2_USAGE_ANALYSIS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md` | 125 | Referenced repository path not found: processors/graphrag/enhanced_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md` | 163 | Referenced repository path not found: processors/graphrag/phase7_complete_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_5_SCRIPT_1_COMPLETE.md` | 130 | Referenced repository path not found: utils/workflows/testing.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_6_TESTING_VALIDATION_COMPLETE.md` | 65 | Referenced repository path not found: data_transformation/multimedia/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_6_TESTING_VALIDATION_COMPLETE.md` | 240 | Referenced repository path not found: processors/graphrag/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_7_TESTING_COMPLETE.md` | 173 | Referenced repository path not found: serialization/dataset_serialization.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_7_TESTING_COMPLETE.md` | 178 | Referenced repository path not found: ipfs/formats/ipfs_multiformats.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_8_COMPLETE.md` | 237 | Referenced repository path not found: .git/index.lock | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/phases/PHASE_9_10_PROGRESS_REPORT.md` | 22 | Referenced repository path not found: infrastructure/monitoring.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_FINAL_STATUS.md` | 22 | Referenced repository path not found: processors/graphrag/adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_1_COMPLETE.md` | 203 | Referenced repository path not found: processors/graphrag/integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_1_COMPLETE.md` | 235 | Referenced repository path not found: processors/graphrag/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 13 | Referenced repository path not found: processors/graphrag/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 41 | Referenced repository path not found: processors/graphrag/adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 105 | Referenced repository path not found: docs/PATH_B_SESSION_1_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 106 | Referenced repository path not found: docs/PATH_B_SESSION_2_PROGRESS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 107 | Referenced repository path not found: docs/PATH_B_SESSION_2_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 273 | Referenced repository path not found: processors/graphrag/integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_PROGRESS.md` | 95 | Referenced repository path not found: ipfs_datasets_py/processors/graphrag/adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_PROGRESS.md` | 345 | Referenced repository path not found: processors/graphrag/integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_PHASE_2_CRITICAL_PREP.md` | 604 | Referenced repository path not found: tests/unit/knowledge_graphs/test_multi_database.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_PHASE_2_CRITICAL_PREP.md` | 671 | Referenced repository path not found: tests/unit/knowledge_graphs/test_cypher_functions.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_READY_TO_IMPLEMENT_PHASE_2_3.md` | 97 | Referenced repository path not found: tests/unit/knowledge_graphs/test_multi_database.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_READY_TO_IMPLEMENT_PHASE_2_3.md` | 269 | Referenced repository path not found: tests/unit/knowledge_graphs/test_math_functions.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_READY_TO_IMPLEMENT_PHASE_2_3.md` | 489 | Referenced repository path not found: tests/unit/knowledge_graphs/test_vocabularies.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_READY_TO_IMPLEMENT_PHASE_2_3.md` | 553 | Referenced repository path not found: cypher/functions.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_READY_TO_IMPLEMENT_PHASE_2_3.md` | 561 | Referenced repository path not found: jsonld/context.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_KNOWLEDGE_GRAPHS_PLAN_REVIEW.md` | 12 | Referenced repository path not found: ipfs_datasets_py/docs/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_KNOWLEDGE_GRAPHS_PLAN_REVIEW.md` | 248 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_CURRENT_STATUS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_KNOWLEDGE_GRAPHS_PLAN_REVIEW.md` | 249 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_NEXT_STEPS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_KNOWLEDGE_GRAPHS_PLAN_REVIEW.md` | 252 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_DOCUMENTATION_INDEX.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_1_1_MULTIMEDIA_AUDIT_REPORT.md` | 62 | Referenced repository path not found: processors/multimedia/converters/omni_converter/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_1_1_MULTIMEDIA_AUDIT_REPORT.md` | 68 | Referenced repository path not found: processors/multimedia/converters/mime_converter/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_1_1_MULTIMEDIA_AUDIT_REPORT.md` | 76 | Referenced repository path not found: ipfs_datasets_py/data_transformation/multimedia/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_1_1_MULTIMEDIA_AUDIT_REPORT.md` | 169 | Referenced repository path not found: data_transformation/multimedia/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_1_2_CLEANUP_COMPLETE_REPORT.md` | 91 | Referenced repository path not found: data_transformation/multimedia/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 35 | Referenced repository path not found: data_transformation/car_conversion.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 36 | Referenced repository path not found: data_transformation/jsonl_to_parquet.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 37 | Referenced repository path not found: data_transformation/dataset_serialization.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 38 | Referenced repository path not found: data_transformation/ipfs_parquet_to_car.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 79 | Referenced repository path not found: data_transformation/car_conversion.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 80 | Referenced repository path not found: data_transformation/jsonl_to_parquet.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 81 | Referenced repository path not found: data_transformation/dataset_serialization.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 82 | Referenced repository path not found: data_transformation/ipfs_parquet_to_car.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 51 | Referenced repository path not found: ipfs_datasets_py/admin_dashboard.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 59 | Referenced repository path not found: tests/test_admin_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 60 | Referenced repository path not found: tests/test_analysis_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 61 | Referenced repository path not found: tests/test_auth_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 62 | Referenced repository path not found: tests/test_background_task_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 63 | Referenced repository path not found: tests/test_cache_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 64 | Referenced repository path not found: tests/test_comprehensive_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 65 | Referenced repository path not found: tests/test_embedding_search_storage_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 66 | Referenced repository path not found: tests/test_embedding_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 67 | Referenced repository path not found: tests/test_fastapi_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 68 | Referenced repository path not found: tests/test_fio.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 69 | Referenced repository path not found: tests/test_monitoring_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 70 | Referenced repository path not found: tests/test_test_e2e.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 71 | Referenced repository path not found: tests/test_vector_store_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 72 | Referenced repository path not found: tests/test_vector_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 73 | Referenced repository path not found: tests/test_workflow_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/claude.md` | 93 | Referenced repository path not found: tests/_example_test_format.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 30 | Referenced repository path not found: ipfs_datasets_py/dataset_serialization.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 34 | Referenced repository path not found: ipfs_datasets_py/pdf_processing/ocr_engine.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 38 | Referenced repository path not found: ipfs_datasets_py/logic_integration/interactive_fol_constructor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 42 | Referenced repository path not found: ipfs_datasets_py/llm/llm_semantic_validation.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 49 | Referenced repository path not found: ipfs_datasets_py/query_optimizer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 50 | Referenced repository path not found: ipfs_datasets_py/libp2p_kit.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 51 | Referenced repository path not found: ipfs_datasets_py/vector_tools_simple.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 52 | Referenced repository path not found: ipfs_datasets_py/fastapi_service.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 54 | Referenced repository path not found: ipfs_datasets_py/resilient_operations.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 57 | Referenced repository path not found: ipfs_datasets_py/graphrag_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/deprecated/stub_coverage_analysis_report.md` | 58 | Referenced repository path not found: ipfs_datasets_py/ipfs_knn_index.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/KNOWLEDGE_GRAPHS_EXTRACTION_API.md` | 808 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_EXTRACTION_API.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/README.md` | 30 | Referenced repository path not found: /docs/modules/knowledge_graphs/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/README.md` | 31 | Referenced repository path not found: /docs/examples/knowledge_graphs/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASES_4_5_COMPLETE.md` | 23 | Referenced repository path not found: jsonld/types.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASES_4_5_COMPLETE.md` | 30 | Referenced repository path not found: jsonld/context.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASES_4_5_COMPLETE.md` | 35 | Referenced repository path not found: jsonld/translator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASES_4_5_COMPLETE.md` | 43 | Referenced repository path not found: jsonld/validation.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASES_4_5_COMPLETE.md` | 100 | Referenced repository path not found: indexing/types.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASES_4_5_COMPLETE.md` | 106 | Referenced repository path not found: indexing/btree.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASES_4_5_COMPLETE.md` | 115 | Referenced repository path not found: indexing/specialized.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASES_4_5_COMPLETE.md` | 121 | Referenced repository path not found: indexing/manager.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASES_4_5_COMPLETE.md` | 128 | Referenced repository path not found: constraints/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 84 | Referenced repository path not found: docs/PHASE_2_TASK_2_2_USAGE_ANALYSIS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 91 | Referenced repository path not found: docs/PHASE_2_SESSIONS_7_8_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 98 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_LINEAGE_MIGRATION.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 105 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_LINEAGE_FAQ.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 112 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_LINEAGE_TROUBLESHOOTING.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md` | 120 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_PHASE_2_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_3_SESSION_COMPLETE.md` | 250 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_PHASE_3_SESSION_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 105 | Referenced repository path not found: lineage/core.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 105 | Referenced repository path not found: lineage/enhanced.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 105 | Referenced repository path not found: lineage/visualization.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 112 | Referenced repository path not found: query/unified_engine.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 113 | Referenced repository path not found: core/query_executor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 178 | Referenced repository path not found: processors/graphrag/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 685 | Referenced repository path not found: docs/_example_docstring_format.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 1021 | Referenced repository path not found: jsonld/shacl_validator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_16.md` | 1038 | Referenced repository path not found: jsonld/turtle_serializer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 359 | Referenced repository path not found: processors/graphrag/integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 363 | Referenced repository path not found: tests/unit/knowledge_graphs/test_unified_engine.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 446 | Referenced repository path not found: processors/graphrag/content_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 524 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/jsonld/vocabularies/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 558 | Referenced repository path not found: jsonld/context.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 568 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/jsonld/shacl_validator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 645 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/jsonld/turtle_serializer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP_2026_02_16.md` | 831 | Referenced repository path not found: cypher/functions.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 247 | Referenced repository path not found: jsonld/context.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 248 | Referenced repository path not found: jsonld/translator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 249 | Referenced repository path not found: jsonld/types.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_STATUS_2026_02_16.md` | 250 | Referenced repository path not found: jsonld/validation.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 171 | Referenced repository path not found: cypher/ast.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 172 | Referenced repository path not found: cypher/parser.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 173 | Referenced repository path not found: cypher/compiler.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 174 | Referenced repository path not found: core/query_executor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_NEO4J_REFACTORING_PLAN.md` | 36 | Referenced repository path not found: processors/graphrag/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_PHASES_3_4_COMPREHENSIVE_PLAN.md` | 62 | Referenced repository path not found: extraction/extractor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_PHASES_3_4_COMPREHENSIVE_PLAN.md` | 97 | Referenced repository path not found: extraction/validator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_PHASES_3_4_COMPREHENSIVE_PLAN.md` | 133 | Referenced repository path not found: extraction/patterns.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 127 | Referenced repository path not found: core/query_executor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 237 | Referenced repository path not found: knowledge_graphs/optimization/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 238 | Referenced repository path not found: knowledge_graphs/optimization/cost_estimator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 239 | Referenced repository path not found: knowledge_graphs/optimization/plan_cache.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 240 | Referenced repository path not found: knowledge_graphs/optimization/index_selector.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 316 | Referenced repository path not found: knowledge_graphs/neo4j_compat/pool.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 345 | Referenced repository path not found: knowledge_graphs/protocol/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 346 | Referenced repository path not found: knowledge_graphs/protocol/ipld_bolt.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 347 | Referenced repository path not found: knowledge_graphs/protocol/serialization.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 348 | Referenced repository path not found: knowledge_graphs/protocol/auth.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 425 | Referenced repository path not found: knowledge_graphs/apoc/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 426 | Referenced repository path not found: knowledge_graphs/apoc/algorithms.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 427 | Referenced repository path not found: knowledge_graphs/apoc/data.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 428 | Referenced repository path not found: knowledge_graphs/apoc/utilities.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 429 | Referenced repository path not found: knowledge_graphs/apoc/import_export.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 466 | Referenced repository path not found: scripts/migrate_neo4j_to_ipfs.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 539 | Referenced repository path not found: knowledge_graphs/jsonld/shacl_shapes.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 564 | Referenced repository path not found: knowledge_graphs/rdf/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 565 | Referenced repository path not found: knowledge_graphs/rdf/turtle.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 566 | Referenced repository path not found: knowledge_graphs/rdf/ntriples.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 567 | Referenced repository path not found: knowledge_graphs/rdf/rdfxml.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 590 | Referenced repository path not found: processors/graphrag/integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 641 | Referenced repository path not found: knowledge_graphs/query/graphrag_executor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 679 | Referenced repository path not found: data_transformation/ipld/knowledge_graph.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 711 | Referenced repository path not found: processors/graphrag/content_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 712 | Referenced repository path not found: processors/graphrag/entity_extractor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 757 | Referenced repository path not found: knowledge_graphs/distributed/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 758 | Referenced repository path not found: knowledge_graphs/distributed/coordinator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 759 | Referenced repository path not found: knowledge_graphs/distributed/participant.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 760 | Referenced repository path not found: knowledge_graphs/distributed/consensus.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 761 | Referenced repository path not found: knowledge_graphs/distributed/replication.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 799 | Referenced repository path not found: knowledge_graphs/replication/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 800 | Referenced repository path not found: knowledge_graphs/replication/master.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 801 | Referenced repository path not found: knowledge_graphs/replication/slave.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 802 | Referenced repository path not found: knowledge_graphs/replication/consistency.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 803 | Referenced repository path not found: knowledge_graphs/replication/conflict_resolution.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 844 | Referenced repository path not found: knowledge_graphs/indexing/adaptive.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 882 | Referenced repository path not found: knowledge_graphs/monitoring/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 883 | Referenced repository path not found: knowledge_graphs/monitoring/profiler.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 884 | Referenced repository path not found: knowledge_graphs/monitoring/metrics.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 885 | Referenced repository path not found: knowledge_graphs/monitoring/dashboard.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 933 | Referenced repository path not found: docs/knowledge_graphs/OPERATOR_MANUAL.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 934 | Referenced repository path not found: docs/knowledge_graphs/NEO4J_MIGRATION.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 966 | Referenced repository path not found: examples/knowledge_graphs/social_network/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 967 | Referenced repository path not found: examples/knowledge_graphs/knowledge_base/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 968 | Referenced repository path not found: examples/knowledge_graphs/fraud_detection/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 1214 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_PLAN.md` | 1215 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 324 | Referenced repository path not found: ipfs_datasets_py/processors/graphrag/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 325 | Referenced repository path not found: ipfs_datasets_py/search/graphrag_query/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 326 | Referenced repository path not found: ipfs_datasets_py/data_transformation/ipld/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/session_reports/KNOWLEDGE_GRAPHS_PATH_C_SUMMARY.md` | 83 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_PATH_C_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/session_reports/KNOWLEDGE_GRAPHS_PHASES_3_4_SESSION_SUMMARY.md` | 56 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_PHASES_3_4_COMPREHENSIVE_PLAN.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/session_reports/KNOWLEDGE_GRAPHS_PHASE_3_PROGRESS.md` | 37 | Referenced repository path not found: extraction/types.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/session_reports/KNOWLEDGE_GRAPHS_PHASE_3_PROGRESS.md` | 42 | Referenced repository path not found: extraction/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_4_COMPLETE_WITH_TESTS.md` | 127 | Referenced repository path not found: tests/unit/test_extraction_package.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_4_SESSION_2_SUMMARY.md` | 16 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_USAGE_EXAMPLES.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_4_SESSION_2_SUMMARY.md` | 55 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_QUERY_API.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_4_SESSION_2_SUMMARY.md` | 376 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_PHASE_3_4_SESSION_2_SUMMARY.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_4_SESSION_CONTINUATION.md` | 133 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_EXTRACTION_API.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_4_SESSION_CONTINUATION.md` | 140 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_QUERY_ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_4_SESSION_CONTINUATION.md` | 152 | Referenced repository path not found: extraction/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_TASKS_5_7_COMPLETE.md` | 18 | Referenced repository path not found: extraction/extractor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_TASKS_5_7_COMPLETE.md` | 26 | Referenced repository path not found: extraction/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_TASKS_5_7_COMPLETE.md` | 31 | Referenced repository path not found: extraction/validator.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/knowledge_graphs/sessions/KNOWLEDGE_GRAPHS_PHASE_3_TASKS_5_7_COMPLETE.md` | 51 | Referenced repository path not found: extraction/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/ARCHIVE_INDEX.md` | 33 | Referenced repository path not found: ipfs_datasets_py/processors/graphrag/complete_advanced_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/ARCHIVE_INDEX.md` | 66 | Referenced repository path not found: ipfs_datasets_py/processors/graphrag/enhanced_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/ARCHIVE_INDEX.md` | 97 | Referenced repository path not found: ipfs_datasets_py/processors/graphrag/phase7_complete_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_ASYNC_COMPLETE_SUMMARY.md` | 227 | Referenced repository path not found: docs/PROCESSORS_ASYNC_ANYIO_REFACTORING_PLAN.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_ASYNC_COMPLETE_SUMMARY.md` | 228 | Referenced repository path not found: docs/PROCESSORS_ASYNC_COMPLETE_SUMMARY.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASE7_DEVEX_COMPLETE.md` | 103 | Referenced repository path not found: ipfs_datasets_py.processors/profiling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASE7_DEVEX_COMPLETE.md` | 214 | Referenced repository path not found: docs/PROCESSORS_CHANGELOG.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASE7_DEVEX_COMPLETE.md` | 226 | Referenced repository path not found: docs/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASE7_DEVEX_COMPLETE.md` | 227 | Referenced repository path not found: docs/PROCESSORS_ASYNC_COMPLETE_SUMMARY.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASE7_DEVEX_COMPLETE.md` | 237 | Referenced repository path not found: docs/PROCESSORS_BREAKING_CHANGES.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_6_7_COMPLETE.md` | 28 | Referenced repository path not found: engines/llm/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_6_7_COMPLETE.md` | 29 | Referenced repository path not found: engines/query/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_6_7_COMPLETE.md` | 30 | Referenced repository path not found: engines/relationship/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_6_7_COMPLETE.md` | 31 | Referenced repository path not found: engines/llm/optimizer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_6_7_COMPLETE.md` | 32 | Referenced repository path not found: engines/query/engine.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_6_7_COMPLETE.md` | 33 | Referenced repository path not found: engines/relationship/analyzer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_6_7_COMPLETE.md` | 271 | Referenced repository path not found: scripts/migrate_processors_imports.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_6_7_COMPLETE.md` | 272 | Referenced repository path not found: docs/PROCESSORS_ENGINES_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_6_7_COMPLETE.md` | 273 | Referenced repository path not found: docs/PROCESSORS_PLAN_QUICK_REFERENCE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_8_10_COMPLETE_SUMMARY.md` | 33 | Referenced repository path not found: processors/graphrag/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_8_10_COMPLETE_SUMMARY.md` | 91 | Referenced repository path not found: infrastructure/monitoring.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 198 | Referenced repository path not found: adapters/multimodal_advanced_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 217 | Referenced repository path not found: adapters/batch_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 255 | Referenced repository path not found: adapters/ipfs_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 299 | Referenced repository path not found: adapters/web_archive_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 315 | Referenced repository path not found: adapters/specialized_scraper_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 345 | Referenced repository path not found: adapters/geospatial_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 709 | Referenced repository path not found: docs/API_REFERENCE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 736 | Referenced repository path not found: docs/MIGRATION_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 787 | Referenced repository path not found: tests/integration/test_universal_processor_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 858 | Referenced repository path not found: tests/e2e/test_complete_workflows.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 889 | Referenced repository path not found: tests/performance/test_processor_performance.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 919 | Referenced repository path not found: tests/unit/test_edge_cases.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md` | 1128 | Referenced repository path not found: scripts/cli/processor_cli.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 279 | Referenced repository path not found: core/processor_registry.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 281 | Referenced repository path not found: core/registry.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 316 | Referenced repository path not found: core/input_detection.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 469 | Referenced repository path not found: tests/integration/test_specialized_processors.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 470 | Referenced repository path not found: tests/integration/test_cross_module.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 471 | Referenced repository path not found: tests/integration/test_backward_compat.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 472 | Referenced repository path not found: tests/integration/test_migration_paths.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 605 | Referenced repository path not found: docs/archived/processors/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 748 | Referenced repository path not found: tests/data/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 853 | Referenced repository path not found: scripts/migrate_processors_imports.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 30 | Referenced repository path not found: processors/graphrag/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 221 | Referenced repository path not found: specialized/pdf/pdf_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 222 | Referenced repository path not found: specialized/pdf/pdf_processing.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 250 | Referenced repository path not found: infrastructure/error_handling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 264 | Referenced repository path not found: infrastructure/monitoring.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 280 | Referenced repository path not found: infrastructure/caching.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 463 | Referenced repository path not found: specialized/pdf/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 594 | Referenced repository path not found: core/di_container.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 646 | Referenced repository path not found: core/exceptions.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 677 | Referenced repository path not found: domains/legal/base.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 1334 | Referenced repository path not found: docs/coverage/processors/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 1338 | Referenced repository path not found: docs/PROCESSORS_ARCHITECTURE_DIAGRAMS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 101 | Referenced repository path not found: file_converter/batch_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 110 | Referenced repository path not found: graphrag/unified_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 111 | Referenced repository path not found: graphrag/integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 112 | Referenced repository path not found: graphrag/website_system.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 113 | Referenced repository path not found: graphrag/complete_advanced_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 125 | Referenced repository path not found: core/protocol.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 126 | Referenced repository path not found: core/processor_registry.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 442 | Referenced repository path not found: adapters/graphrag_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 488 | Referenced repository path not found: specialized/pdf/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 635 | Referenced repository path not found: adapters/batch_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 636 | Referenced repository path not found: specialized/batch/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 751 | Referenced repository path not found: multimedia/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 752 | Referenced repository path not found: multimedia/ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 753 | Referenced repository path not found: multimedia/omni_converter_mk2/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1139 | Referenced repository path not found: specialized/graphrag/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1140 | Referenced repository path not found: specialized/graphrag/integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1141 | Referenced repository path not found: specialized/graphrag/website_system.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1145 | Referenced repository path not found: specialized/multimodal/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1148 | Referenced repository path not found: infrastructure/caching.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1149 | Referenced repository path not found: infrastructure/monitoring.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1150 | Referenced repository path not found: infrastructure/error_handling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1151 | Referenced repository path not found: infrastructure/profiling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1152 | Referenced repository path not found: infrastructure/debug_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1153 | Referenced repository path not found: infrastructure/cli.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1154 | Referenced repository path not found: domains/patent/dataset_api.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1155 | Referenced repository path not found: domains/patent/scraper.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1156 | Referenced repository path not found: domains/geospatial/analysis.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 231 | Referenced repository path not found: tests/unit/processors/core/test_registry.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 297 | Referenced repository path not found: tests/integration/processors/test_universal_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 314 | Referenced repository path not found: ipfs_datasets_py/processors/graphrag/unified_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 333 | Referenced repository path not found: tests/unit/processors/graphrag/test_unified_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 367 | Referenced repository path not found: tests/unit/processors/adapters/test_graphrag_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 412 | Referenced repository path not found: ipfs_datasets_py/data_transformation/multimedia/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 444 | Referenced repository path not found: scripts/migrations/update_multimedia_imports.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 496 | Referenced repository path not found: tests/unit/processors/adapters/test_multimedia_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 504 | Referenced repository path not found: adapters/pdf_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 509 | Referenced repository path not found: adapters/legal_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 514 | Referenced repository path not found: adapters/wikipedia_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 519 | Referenced repository path not found: adapters/geospatial_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 524 | Referenced repository path not found: adapters/patent_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 529 | Referenced repository path not found: adapters/multimodal_adapter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 577 | Referenced repository path not found: ipfs_datasets_py/processors/core/errors.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 603 | Referenced repository path not found: ipfs_datasets_py/processors/core/cache.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 624 | Referenced repository path not found: ipfs_datasets_py/processors/core/parallel.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_MASTER_PLAN.md` | 294 | Referenced repository path not found: docs/archive/pr948/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 11 | Referenced repository path not found: ipfs_datasets_py/data_transformation/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 80 | Referenced repository path not found: processors/graphrag/complete_advanced_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 427 | Referenced repository path not found: processors/graphrag/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 659 | Referenced repository path not found: data_transformation/multimedia/media_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 709 | Referenced repository path not found: processors/batch/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 1008 | Referenced repository path not found: tests/integration/multimedia/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_ROOT_FILES_INVENTORY_2026.md` | 165 | Referenced repository path not found: engines/llm/optimizer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_ROOT_FILES_INVENTORY_2026.md` | 166 | Referenced repository path not found: engines/query/engine.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_ROOT_FILES_INVENTORY_2026.md` | 167 | Referenced repository path not found: engines/relationship/analyzer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_ROOT_FILES_INVENTORY_2026.md` | 176 | Referenced repository path not found: domains/patent/patent_scraper.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_ROOT_FILES_INVENTORY_2026.md` | 183 | Referenced repository path not found: core/corpus_query_api.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_ROOT_FILES_INVENTORY_2026.md` | 184 | Referenced repository path not found: core/relationship_analysis_api.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_UPDATED_IMPLEMENTATION_PLAN.md` | 72 | Referenced repository path not found: docs/archive/pr948/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_UPDATED_IMPLEMENTATION_PLAN.md` | 168 | Referenced repository path not found: graphrag/complete_advanced_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/planning/PROCESSORS_UPDATED_IMPLEMENTATION_PLAN.md` | 320 | Referenced repository path not found: docs/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/session_reports/PROCESSORS_SESSION_STATUS.md` | 118 | Referenced repository path not found: docs/PROCESSORS_COMPREHENSIVE_IMPROVEMENT_PLAN.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK1_PROGRESS.md` | 392 | Referenced repository path not found: docs/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK1_PROGRESS.md` | 393 | Referenced repository path not found: docs/PROCESSORS_QUICK_REFERENCE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK1_PROGRESS.md` | 394 | Referenced repository path not found: docs/PROCESSORS_ARCHITECTURE_DIAGRAMS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK2_PHASE2_SESSION_SUMMARY.md` | 57 | Referenced repository path not found: adapters/auto_register.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK2_PHASE2_SESSION_SUMMARY.md` | 61 | Referenced repository path not found: adapters/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK2_PHASE2_SESSION_SUMMARY.md` | 74 | Referenced repository path not found: docs/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v10.md` | 27 | Referenced repository path not found: docs/spec/transport-mcp-p2p.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v11.md` | 29 | Referenced repository path not found: tools/logic_tools/policy_management_tool.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 9 | Referenced repository path not found: docs/tools/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 9 | Referenced repository path not found: docs/api/tool-reference.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 9 | Referenced repository path not found: docs/adr/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 13 | Referenced repository path not found: .github/workflows/mcp-benchmarks.yml | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v5.md` | 352 | Referenced repository path not found: mcplusplus/result_cache.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 86 | Referenced repository path not found: docs/architecture/DUAL_RUNTIME_ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 87 | Referenced repository path not found: docs/testing/DUAL_RUNTIME_TESTING_STRATEGY.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 93 | Referenced repository path not found: docs/api/tool-reference.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 121 | Referenced repository path not found: _setup_databases_and_files/TODO.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 121 | Referenced repository path not found: citation_validator/TODO.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 122 | Referenced repository path not found: generate_reports/TODO.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 122 | Referenced repository path not found: results_analyzer/TODO.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 122 | Referenced repository path not found: stratified_sampler/TODO.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 129 | Referenced repository path not found: docs/history/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 333 | Referenced repository path not found: security_tools/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 334 | Referenced repository path not found: audit_tools/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 335 | Referenced repository path not found: analysis_tools/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 336 | Referenced repository path not found: search_tools/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v6.md` | 337 | Referenced repository path not found: admin_tools/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v7.md` | 101 | Referenced repository path not found: mcplusplus/executor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v7.md` | 103 | Referenced repository path not found: docs/architecture/DUAL_RUNTIME_ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v7.md` | 134 | Referenced repository path not found: tools/legal_dataset_tools/PLAYWRIGHT_SETUP.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v7.md` | 135 | Referenced repository path not found: tools/legal_dataset_tools/CRON_SETUP_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v7.md` | 136 | Referenced repository path not found: tools/legal_dataset_tools/COURTLISTENER_API_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v7.md` | 137 | Referenced repository path not found: docs/adr/ADR-002-dual-runtime.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v9.md` | 27 | Referenced repository path not found: docs/spec/mcp-idl.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v9.md` | 28 | Referenced repository path not found: docs/spec/cid-native-artifacts.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v9.md` | 29 | Referenced repository path not found: docs/spec/ucan-delegation.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v9.md` | 30 | Referenced repository path not found: docs/spec/temporal-deontic-policy.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v9.md` | 31 | Referenced repository path not found: docs/spec/event-dag-ordering.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v9.md` | 32 | Referenced repository path not found: docs/spec/risk-scheduling.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v9.md` | 35 | Referenced repository path not found: docs/spec/transport-mcp-p2p.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 246 | Referenced repository path not found: tools/mcplusplus_taskqueue_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 247 | Referenced repository path not found: tools/mcplusplus_peer_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 248 | Referenced repository path not found: tools/legal_dataset_tools/.../hugging_face_pipeline.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 249 | Referenced repository path not found: tools/dashboard_tools/tdfol_performance_tool.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 250 | Referenced repository path not found: tools/investigation_tools/data_ingestion_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 251 | Referenced repository path not found: tools/finance_data_tools/embedding_correlation.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 252 | Referenced repository path not found: tools/investigation_tools/geospatial_analysis_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 253 | Referenced repository path not found: tools/development_tools/github_cli_server_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 254 | Referenced repository path not found: tools/vector_store_tools/enhanced_vector_store_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 255 | Referenced repository path not found: tools/development_tools/linting_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 256 | Referenced repository path not found: tools/development_tools/codebase_search.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 257 | Referenced repository path not found: tools/session_tools/enhanced_session_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 258 | Referenced repository path not found: tools/legacy_mcp_tools/temporal_deontic_logic_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 526 | Referenced repository path not found: dashboard_tools/tdfol_performance_tool.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 526 | Referenced repository path not found: ipfs_datasets_py/dashboard/tdfol_perf.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 527 | Referenced repository path not found: investigation_tools/data_ingestion_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 527 | Referenced repository path not found: ipfs_datasets_py/ingestion/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 528 | Referenced repository path not found: finance_data_tools/embedding_correlation.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 528 | Referenced repository path not found: ipfs_datasets_py/finance/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 576 | Referenced repository path not found: docs/history/archive/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 993 | Referenced repository path not found: docs/history/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/comprehensive_documentation_update.md` | 64 | Referenced repository path not found: docs/test_results/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_improvement_report.md` | 15 | Referenced repository path not found: ipfs_datasets_py/embeddings/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_improvement_report.md` | 16 | Referenced repository path not found: ipfs_datasets_py/rag/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_improvement_report.md` | 18 | Referenced repository path not found: ipfs_datasets_py/pdf_processing/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_improvement_report.md` | 19 | Referenced repository path not found: ipfs_datasets_py/mcp_tools/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_improvement_report.md` | 32 | Referenced repository path not found: docs/api_reference.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_improvement_report.md` | 79 | Referenced repository path not found: docs/auto_generated/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_improvement_report.md` | 101 | Referenced repository path not found: ipfs_datasets_py/llm/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_improvement_report.md` | 102 | Referenced repository path not found: ipfs_datasets_py/multimedia/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_improvement_report.md` | 103 | Referenced repository path not found: ipfs_datasets_py/ipld/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_reorganization.md` | 8 | Referenced repository path not found: test/learning_metrics_implementation.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_reorganization.md` | 9 | Referenced repository path not found: test/rag_optimizer_integration_plan.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_reorganization.md` | 11 | Referenced repository path not found: docs/implementation_notes/audit_system.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_reorganization.md` | 18 | Referenced repository path not found: docs/implementation_notes/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/documentation_reorganization.md` | 24 | Referenced repository path not found: docs/implementation_notes/index.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/reorganization/root_reorganization.md` | 36 | Referenced repository path not found: .github/workflows/example-cached-workflow.yml | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md` | 370 | Referenced repository path not found: integration/deontic_logic_converter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md` | 407 | Referenced repository path not found: tools/text_to_fol.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ARCHITECTURE_REVIEW_LOGIC_COMPLETE.md` | 442 | Referenced repository path not found: tools/legal_text_to_deontic.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ARCHITECTURE_REVIEW_TDFOL_EXTERNAL_PROVERS.md` | 478 | Referenced repository path not found: TDFOL/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ARCHITECTURE_REVIEW_TDFOL_EXTERNAL_PROVERS.md` | 479 | Referenced repository path not found: external_provers/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/CHANGELOG_LOGIC.md` | 45 | Referenced repository path not found: .gitignore | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/CHANGELOG_LOGIC.md` | 73 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/utils/deontic_parser.py:228-234 | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/CHANGELOG_LOGIC_COMPLETE.md` | 249 | Referenced repository path not found: /docs/LOGIC_API_REFERENCE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/CRITICAL_GAPS_RESOLVED.md` | 370 | Referenced repository path not found: ipfs_datasets_py/logic/integration/neurosymbolic_api.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_FINAL_SUMMARY.md` | 47 | Referenced repository path not found: external_provers/formula_analyzer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_FINAL_SUMMARY.md` | 81 | Referenced repository path not found: integration/tdfol_grammar_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_FINAL_SUMMARY.md` | 113 | Referenced repository path not found: integration/tdfol_cec_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_FINAL_SUMMARY.md` | 154 | Referenced repository path not found: integration/tdfol_shadowprover_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_FINAL_SUMMARY.md` | 193 | Referenced repository path not found: TDFOL/tdfol_prover.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_FINAL_SUMMARY.md` | 224 | Referenced repository path not found: CEC/cec_framework.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROGRESS.md` | 100 | Referenced repository path not found: integration/tdfol_grammar_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROGRESS.md` | 142 | Referenced repository path not found: integration/tdfol_cec_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROGRESS.md` | 186 | Referenced repository path not found: integration/tdfol_shadowprover_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROGRESS.md` | 243 | Referenced repository path not found: TDFOL/tdfol_prover.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROGRESS.md` | 297 | Referenced repository path not found: CEC/cec_framework.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROJECT_SUMMARY.md` | 30 | Referenced repository path not found: external_provers/formula_analyzer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROJECT_SUMMARY.md` | 52 | Referenced repository path not found: integration/tdfol_grammar_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROJECT_SUMMARY.md` | 75 | Referenced repository path not found: integration/tdfol_cec_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROJECT_SUMMARY.md` | 98 | Referenced repository path not found: integration/tdfol_shadowprover_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROJECT_SUMMARY.md` | 127 | Referenced repository path not found: TDFOL/tdfol_prover.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_PROJECT_SUMMARY.md` | 155 | Referenced repository path not found: CEC/cec_framework.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_SESSION_SUMMARY.md` | 28 | Referenced repository path not found: external_provers/formula_analyzer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_SESSION_SUMMARY.md` | 79 | Referenced repository path not found: integration/tdfol_grammar_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_SESSION_SUMMARY.md` | 130 | Referenced repository path not found: TDFOL/tdfol_prover.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_SESSION_SUMMARY.md` | 225 | Referenced repository path not found: integration/tdfol_cec_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_SESSION_SUMMARY.md` | 244 | Referenced repository path not found: integration/tdfol_shadowprover_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_SESSION_SUMMARY.md` | 264 | Referenced repository path not found: CEC/cec_framework.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 26 | Referenced repository path not found: ipfs_datasets_py/rag/logic_aware_entity_extractor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 353 | Referenced repository path not found: ipfs_datasets_py/rag/logic_knowledge_graph.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 614 | Referenced repository path not found: ipfs_datasets_py/rag/logic_enhanced_rag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 714 | Referenced repository path not found: tests/unit_tests/rag/test_logic_enhanced_rag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 774 | Referenced repository path not found: examples/graphrag/logic_enhanced_rag_demo.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 845 | Referenced repository path not found: docs/GRAPHRAG_INTEGRATION.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/IMPLEMENTATION_PROGRESS.md` | 80 | Referenced repository path not found: .gitignore | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 23 | Referenced repository path not found: external_provers/smt/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 39 | Referenced repository path not found: external_provers/prover_router.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 54 | Referenced repository path not found: integration/tdfol_grammar_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 74 | Referenced repository path not found: integration/tdfol_cec_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 95 | Referenced repository path not found: integration/tdfol_shadowprover_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 110 | Referenced repository path not found: TDFOL/tdfol_prover.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 129 | Referenced repository path not found: CEC/cec_framework.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 148 | Referenced repository path not found: tools/modal_logic_extension_stubs.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 149 | Referenced repository path not found: tools/symbolic_fol_bridge_stubs.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 150 | Referenced repository path not found: tools/symbolic_logic_primitives_stubs.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_FOLDER_REVIEW_COMPLETE.md` | 166 | Referenced repository path not found: integration/TODO.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_IMPROVEMENT_INDEX.md` | 144 | Referenced repository path not found: ipfs_datasets_py/logic/deontic/utils/deontic_parser.py:228-234 | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/LOGIC_INTEGRATION_COMPLETE.md` | 385 | Referenced repository path not found: logic/TDFOL/PHASE1-6_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/NEUROSYMBOLIC_ARCHITECTURE_PLAN.md` | 1093 | Referenced repository path not found: logic/neurosymbolic/symai_tdfol_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/NEUROSYMBOLIC_ARCHITECTURE_PLAN.md` | 1118 | Referenced repository path not found: logic/neurosymbolic/symai_proof_guide.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/NEUROSYMBOLIC_ARCHITECTURE_PLAN.md` | 1136 | Referenced repository path not found: logic/neurosymbolic/symai_formula_embedder.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/NEUROSYMBOLIC_ARCHITECTURE_PLAN.md` | 1178 | Referenced repository path not found: graphrag/logic_integration/symai_graph_builder.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/OPTIMIZER_IMPROVEMENTS_SESSION_COMPLETE.md` | 88 | Referenced repository path not found: logic_theorem_optimizer/cli_wrapper.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/OPTIMIZER_IMPROVEMENTS_SESSION_COMPLETE.md` | 93 | Referenced repository path not found: graphrag/cli_wrapper.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/OPTIMIZER_IMPROVEMENTS_SESSION_COMPLETE.md` | 99 | Referenced repository path not found: agentic/cli.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/OPTIMIZER_REFACTORING_COMPLETE.md` | 54 | Referenced repository path not found: methods/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/OPTIMIZER_REFACTORING_COMPLETE.md` | 55 | Referenced repository path not found: agentic/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/OPTIMIZER_REFACTORING_COMPLETE.md` | 200 | Referenced repository path not found: ipfs_datasets_py/optimizers/IMPLEMENTATION_SUMMARY.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/OPTIMIZER_REFACTORING_COMPLETE.md` | 201 | Referenced repository path not found: ipfs_datasets_py/optimizers/COMPLETE_IMPLEMENTATION_REPORT.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/OPTIMIZER_REFACTORING_COMPLETE.md` | 202 | Referenced repository path not found: ipfs_datasets_py/optimizers/ARCHITECTURE_AGENTIC_OPTIMIZERS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/OPTIMIZER_REFACTORING_COMPLETE.md` | 203 | Referenced repository path not found: docs/IMPLEMENTATION_SUMMARY_REFACTORING.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE7_TESTING_PROGRESS.md` | 217 | Referenced repository path not found: tests/unit_tests/logic/CEC/test_cec_framework.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE7_TESTING_PROGRESS.md` | 247 | Referenced repository path not found: tests/integration/test_enhancement_todos_integration.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE7_TESTING_PROGRESS.md` | 290 | Referenced repository path not found: ipfs_datasets_py/logic/integration/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_1_6_IMPLEMENTATION_SUMMARY.md` | 33 | Referenced repository path not found: infrastructure/profiling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_1_6_IMPLEMENTATION_SUMMARY.md` | 34 | Referenced repository path not found: infrastructure/error_handling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_1_6_IMPLEMENTATION_SUMMARY.md` | 55 | Referenced repository path not found: multimedia/convert_to_txt_based_on_mime_type/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_1_6_IMPLEMENTATION_SUMMARY.md` | 56 | Referenced repository path not found: multimedia/omni_converter_mk2/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_3_6_IMPLEMENTATION_STATUS.md` | 45 | Referenced repository path not found: core/registry.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_3_6_IMPLEMENTATION_STATUS.md` | 178 | Referenced repository path not found: docs/PROCESSORS_ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_3_6_IMPLEMENTATION_STATUS.md` | 231 | Referenced repository path not found: specialized/pdf/pdf_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_3_6_IMPLEMENTATION_STATUS.md` | 232 | Referenced repository path not found: specialized/batch/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_3_6_IMPLEMENTATION_STATUS.md` | 233 | Referenced repository path not found: specialized/graphrag/unified_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASES_3_6_IMPLEMENTATION_STATUS.md` | 285 | Referenced repository path not found: benchmarks/processors_anyio_benchmark.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 91 | Referenced repository path not found: pools/system_resources/system_resources_pool_template.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 92 | Referenced repository path not found: pools/non_system_resources/file_path_pool/file_path_pool.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 93 | Referenced repository path not found: pools/non_system_resources/core_functions_pool/analyze_functions_in_directory/function_analyzer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 94 | Referenced repository path not found: pools/non_system_resources/core_functions_pool/core_functions_pool.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 95 | Referenced repository path not found: converter_system/conversion_pipeline/functions/core.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 96 | Referenced repository path not found: converter_system/conversion_pipeline/functions/pipeline.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 97 | Referenced repository path not found: converter_system/conversion_pipeline/functions/optimize.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 98 | Referenced repository path not found: converter_system/core_resource_manager/core_resource_manager.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 99 | Referenced repository path not found: converter_system/file_path_queue/file_path_queue.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 101 | Referenced repository path not found: utils/common/stopwatch.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 102 | Referenced repository path not found: utils/common/asyncio_coroutine.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 103 | Referenced repository path not found: utils/converter_system/monads/monad.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 104 | Referenced repository path not found: utils/converter_system/monads/async_.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 105 | Referenced repository path not found: utils/converter_system/run_in_parallel_with_concurrency_limiter.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 106 | Referenced repository path not found: utils/converter_system/run_in_thread_pool.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 107 | Referenced repository path not found: test/test_core/test_core.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 108 | Referenced repository path not found: test/test_external_interface/test_file_manager.py/test_file_manager.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 109 | Referenced repository path not found: external_interface/file_paths_manager/file_paths_manager.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_1_IMPLEMENTATION_PROGRESS.md` | 110 | Referenced repository path not found: multimedia/media_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_2_IMPLEMENTATION_PLAN.md` | 195 | Referenced repository path not found: file_converter/README.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_2_IMPLEMENTATION_PLAN.md` | 247 | Referenced repository path not found: examples/file_converter/ | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_2_IMPLEMENTATION_PLAN.md` | 290 | Referenced repository path not found: convert_to_txt_based_on_mime_type/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PHASE_2_IMPLEMENTATION_PLAN.md` | 291 | Referenced repository path not found: omni_converter_mk2/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PRIORITY_4_PHASE_1_COMPLETE.md` | 261 | Referenced repository path not found: docs/optimizers/PERFORMANCE_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PRIORITY_4_PHASE_1_COMPLETE.md` | 262 | Referenced repository path not found: ipfs_datasets_py/optimizers/agentic/PERFORMANCE_TUNING.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PRIORITY_5_MIGRATION_PLAN.md` | 97 | Referenced repository path not found: logic_theorem_optimizer/unified_optimizer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PRIORITY_5_MIGRATION_PLAN.md` | 226 | Referenced repository path not found: graphrag/unified_optimizer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PRIORITY_5_WEEK_1_PHASE_1_COMPLETE.md` | 13 | Referenced repository path not found: logic_theorem_optimizer/unified_optimizer.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_ANYIO_QUICK_REFERENCE.md` | 452 | Referenced repository path not found: /docs/ASYNCIO_TO_ANYIO_MIGRATION.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 208 | Referenced repository path not found: docs/ASYNCIO_TO_ANYIO_MIGRATION.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 253 | Referenced repository path not found: file_converter/backends/omni_backend.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 256 | Referenced repository path not found: file_converter/batch_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 257 | Referenced repository path not found: infrastructure/monitoring.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 262 | Referenced repository path not found: convert_to_txt_based_on_mime_type/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 263 | Referenced repository path not found: omni_converter_mk2/__init__.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 286 | Referenced repository path not found: specialized/multimodal/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 337 | Referenced repository path not found: infrastructure/caching.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 338 | Referenced repository path not found: infrastructure/cli.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 339 | Referenced repository path not found: infrastructure/debug_tools.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 340 | Referenced repository path not found: infrastructure/error_handling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 342 | Referenced repository path not found: infrastructure/profiling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 343 | Referenced repository path not found: core/protocol.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 344 | Referenced repository path not found: core/registry.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 362 | Referenced repository path not found: scripts/migrate_imports.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 369 | Referenced repository path not found: docs/MIGRATION_GUIDE_V2_TO_V3.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 370 | Referenced repository path not found: docs/ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 454 | Referenced repository path not found: tests/architecture/test_dependencies.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 479 | Referenced repository path not found: specialized/batch/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 480 | Referenced repository path not found: specialized/pdf/pdf_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 481 | Referenced repository path not found: specialized/graphrag/unified_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 482 | Referenced repository path not found: specialized/media/advanced_processing.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 483 | Referenced repository path not found: specialized/multimodal/multimodal_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 484 | Referenced repository path not found: specialized/web_archive/advanced_archiving.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 485 | Referenced repository path not found: domains/patent/patent_scraper.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 486 | Referenced repository path not found: domains/patent/patent_dataset_api.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 487 | Referenced repository path not found: domains/geospatial/geospatial_analysis.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 488 | Referenced repository path not found: domains/ml/classify_with_llm.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 519 | Referenced repository path not found: docs/PROCESSORS_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 520 | Referenced repository path not found: docs/ADDING_PROCESSORS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 522 | Referenced repository path not found: docs/MIGRATION_V2_TO_V3.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 528 | Referenced repository path not found: examples/processors/basic_usage.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 529 | Referenced repository path not found: examples/processors/batch_processing.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 530 | Referenced repository path not found: examples/processors/custom_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 531 | Referenced repository path not found: examples/processors/anyio_patterns.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_CHECKLIST.md` | 532 | Referenced repository path not found: examples/processors/error_handling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_COMPLETE.md` | 135 | Referenced repository path not found: docs/PROCESSORS_ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_INDEX.md` | 247 | Referenced repository path not found: docs/ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_INDEX.md` | 248 | Referenced repository path not found: docs/PROCESSORS_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 275 | Referenced repository path not found: docs/ASYNCIO_TO_ANYIO_MIGRATION.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 412 | Referenced repository path not found: specialized/batch/processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 413 | Referenced repository path not found: specialized/batch/file_converter_batch.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 414 | Referenced repository path not found: file_converter/batch_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 435 | Referenced repository path not found: specialized/pdf/pdf_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 466 | Referenced repository path not found: specialized/multimodal/multimodal_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 608 | Referenced repository path not found: docs/ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 609 | Referenced repository path not found: docs/MIGRATION_GUIDE_V2_TO_V3.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 631 | Referenced repository path not found: scripts/migrate_imports.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 883 | Referenced repository path not found: core/universal_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 888 | Referenced repository path not found: tests/architecture/test_dependencies.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 1037 | Referenced repository path not found: specialized/graphrag/unified_graphrag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 1038 | Referenced repository path not found: specialized/media/advanced_processing.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 1040 | Referenced repository path not found: specialized/web_archive/advanced_archiving.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 1117 | Referenced repository path not found: docs/PROCESSORS_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 1118 | Referenced repository path not found: docs/ADDING_PROCESSORS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 1120 | Referenced repository path not found: docs/MIGRATION_V2_TO_V3.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_SUMMARY.md` | 74 | Referenced repository path not found: infrastructure/profiling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_SUMMARY.md` | 75 | Referenced repository path not found: infrastructure/error_handling.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_SUMMARY.md` | 113 | Referenced repository path not found: file_converter/batch_processor.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_SUMMARY.md` | 243 | Referenced repository path not found: docs/ARCHITECTURE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_SUMMARY.md` | 244 | Referenced repository path not found: docs/PROCESSORS_GUIDE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_SUMMARY.md` | 245 | Referenced repository path not found: docs/ADDING_PROCESSORS.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_SUMMARY.md` | 246 | Referenced repository path not found: docs/ASYNCIO_TO_ANYIO_MIGRATION.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_SUMMARY.md` | 247 | Referenced repository path not found: docs/MIGRATION_V2_TO_V3.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PRODUCTION_READINESS_PLAN.md` | 617 | Referenced repository path not found: tests/performance/test_load.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROJECT_COMPLETE.md` | 247 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROJECT_COMPLETE.md` | 249 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROJECT_COMPLETE.md` | 256 | Referenced repository path not found: docs/FINAL_STATUS_REPORT.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROJECT_COMPLETE.md` | 257 | Referenced repository path not found: docs/PHASE_7_TESTING_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/PROJECT_COMPLETE.md` | 258 | Referenced repository path not found: docs/PHASE_8_FINAL_CLEANUP_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/SYMBOLICAI_INTEGRATION_ANALYSIS.md` | 171 | Referenced repository path not found: logic/neurosymbolic/symai_tdfol_bridge.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/SYMBOLICAI_INTEGRATION_ANALYSIS.md` | 234 | Referenced repository path not found: logic/neurosymbolic/symai_proof_guide.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/SYMBOLICAI_INTEGRATION_ANALYSIS.md` | 290 | Referenced repository path not found: logic/neurosymbolic/symai_formula_embedder.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/SYMBOLICAI_INTEGRATION_ANALYSIS.md` | 386 | Referenced repository path not found: graphrag/logic_integration/symai_graph_builder.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/TDFOL_IMPROVEMENT_SUMMARY.md` | 151 | Referenced repository path not found: graphrag/logic_integration/logic_aware_graph.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/TDFOL_IMPROVEMENT_SUMMARY.md` | 152 | Referenced repository path not found: graphrag/logic_integration/theorem_augmented_rag.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/TDFOL_IMPROVEMENT_SUMMARY.md` | 153 | Referenced repository path not found: graphrag/logic_integration/temporal_graph_reasoning.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/TDFOL_IMPROVEMENT_SUMMARY.md` | 154 | Referenced repository path not found: graphrag/logic_integration/consistency_checker.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/TDFOL_IMPROVEMENT_SUMMARY.md` | 256 | Referenced repository path not found: logic/TDFOL/PHASE2_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/TDFOL_IMPROVEMENT_SUMMARY.md` | 257 | Referenced repository path not found: logic/TDFOL/PHASE3_COMPLETE.md | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/TEST_COVERAGE_PROGRESS_REPORT.md` | 164 | Referenced repository path not found: logic/integration/proof_execution_engine.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/TEST_COVERAGE_PROGRESS_REPORT.md` | 168 | Referenced repository path not found: logic/integration/deontic_query_engine.py | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/archive/root_status_reports/WEEK1_SUMMARY.md` | 153 | Referenced repository path not found: .gitignore | archive-prefix:docs/archive/ |
| `repo_paths` | `docs/guides/DEPRECATED_SCRIPTS.md` | 29 | Referenced repository path not found: .github/workflows/copilot-agent-autofix.yml | migration-substring:deprecat |
| `repo_paths` | `docs/guides/DEPRECATED_SCRIPTS.md` | 30 | Referenced repository path not found: .github/workflows/comprehensive-scraper-validation.yml | migration-substring:deprecat |
| `repo_paths` | `docs/guides/DEPRECATED_SCRIPTS.md` | 38 | Referenced repository path not found: .github/workflows/continuous-queue-management.yml | migration-substring:deprecat |
| `repo_paths` | `docs/guides/DEPRECATED_SCRIPTS.md` | 56 | Referenced repository path not found: .github/workflows/enhanced-pr-completion-monitor.yml | migration-substring:deprecat |
| `repo_paths` | `docs/guides/DEPRECATED_SCRIPTS.md` | 57 | Referenced repository path not found: .github/workflows/pr-copilot-monitor.yml | migration-substring:deprecat |
| `repo_paths` | `docs/guides/DEPRECATED_SCRIPTS.md` | 69 | Referenced repository path not found: .github/workflows/issue-to-draft-pr.yml | migration-substring:deprecat |
| `repo_paths` | `docs/guides/DEPRECATED_SCRIPTS.md` | 81 | Referenced repository path not found: .github/workflows/pr-completion-monitor.yml | migration-substring:deprecat |
| `repo_paths` | `docs/guides/infrastructure/anyio_migration_guide.md` | 378 | Referenced repository path not found: docs/FILE_CONVERSION_INTEGRATION_PLAN.md | migration-substring:migration |
| `repo_paths` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md` | 544 | Referenced repository path not found: examples/knowledge_graphs/social_network/ | migration-substring:migration |
| `repo_paths` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md` | 545 | Referenced repository path not found: examples/knowledge_graphs/neo4j_migration/ | migration-substring:migration |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 145 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md | migration-substring:migration |
| `repo_paths` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 146 | Referenced repository path not found: docs/PROCESSORS_DATA_TRANSFORMATION_INTEGRATION_PLAN_V2.md | migration-substring:migration |
| `repo_paths` | `docs/implementation/plans/IPFS_EMBEDDINGS_MIGRATION_PLAN.md` | 34 | Referenced repository path not found: ipfs_datasets_py/fastapi_service.py | migration-substring:migration |
| `repo_paths` | `docs/implementation/plans/IPFS_EMBEDDINGS_MIGRATION_PLAN.md` | 54 | Referenced repository path not found: tests/test_embedding_tools.py | migration-substring:migration |
| `repo_paths` | `docs/implementation/plans/IPFS_EMBEDDINGS_MIGRATION_PLAN.md` | 55 | Referenced repository path not found: tests/test_vector_tools.py | migration-substring:migration |
| `repo_paths` | `docs/implementation/plans/IPFS_EMBEDDINGS_MIGRATION_PLAN.md` | 56 | Referenced repository path not found: tests/test_admin_tools.py | migration-substring:migration |
| `repo_paths` | `docs/implementation/plans/IPFS_EMBEDDINGS_MIGRATION_PLAN.md` | 57 | Referenced repository path not found: tests/test_cache_tools.py | migration-substring:migration |
| `repo_paths` | `docs/implementation/plans/IPFS_EMBEDDINGS_MIGRATION_PLAN.md` | 58 | Referenced repository path not found: tests/test_fastapi_integration.py | migration-substring:migration |
| `repo_paths` | `docs/implementation/plans/IPFS_EMBEDDINGS_MIGRATION_PLAN.md` | 59 | Referenced repository path not found: tests/test_comprehensive_integration.py | migration-substring:migration |
| `repo_paths` | `docs/implementation/plans/migration_plan.md` | 53 | Referenced repository path not found: docs/ipfs_embeddings_py/src/mcp_server/tools/ | migration-substring:migration |
| `repo_paths` | `docs/knowledge_graphs/MIGRATION_GUIDE.md` | 88 | Referenced repository path not found: migration/formats.py | migration-substring:migration |
| `repo_paths` | `docs/knowledge_graphs/MIGRATION_GUIDE.md` | 146 | Referenced repository path not found: extraction/extractor.py | migration-substring:migration |
| `repo_paths` | `docs/knowledge_graphs/MIGRATION_GUIDE.md` | 148 | Referenced repository path not found: extraction/srl.py | migration-substring:migration |
| `repo_paths` | `docs/knowledge_graphs/MIGRATION_GUIDE.md` | 149 | Referenced repository path not found: reasoning/cross_document.py | migration-substring:migration |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY.md` | 42 | Referenced repository path not found: extraction/extractor.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY.md` | 43 | Referenced repository path not found: core/query_executor.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY.md` | 306 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/REFACTORING_IMPROVEMENT_PLAN.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY.md` | 314 | Referenced repository path not found: .gitignore | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY.md` | 317 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/cross_document_lineage.py.backup | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY.md` | 318 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/cross_document_lineage_enhanced.py.backup | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/EXECUTIVE_SUMMARY.md` | 319 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/cypher/parser.py.backup | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/PHASE_1_PROGRESS_2026_02_17.md` | 271 | Referenced repository path not found: /ipfs_datasets_py/knowledge_graphs/PHASE_1_PROGRESS_2026_02_17.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/PHASE_2_COMPLETE_SESSION_5_SUMMARY.md` | 142 | Referenced repository path not found: indexing/btree.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/PHASE_2_COMPLETE_SESSION_5_SUMMARY.md` | 159 | Referenced repository path not found: indexing/specialized.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/PHASE_2_COMPLETE_SESSION_5_SUMMARY.md` | 177 | Referenced repository path not found: transactions/manager.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/REFACTORING_PHASE_1_SUMMARY.md` | 69 | Referenced repository path not found: archive/refactoring_history/ | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/REFACTORING_PHASE_1_SUMMARY.md` | 85 | Referenced repository path not found: archive/superseded_plans/ | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 140 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/IMPLEMENTATION_STATUS.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 141 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/ROADMAP.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 143 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 144 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/REFACTORING_PHASE_1_SUMMARY.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 147 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/VALIDATION_REPORT.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/refactoring_history/VALIDATION_REPORT.md` | 150 | Referenced repository path not found: ipfs_datasets_py/knowledge_graphs/INDEX.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 336 | Referenced repository path not found: cypher/compiler.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 459 | Referenced repository path not found: tests/integration/knowledge_graphs/TEST_GUIDE.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` | 90 | Referenced repository path not found: archive/refactoring_history/ | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_CHECKLIST.md` | 288 | Referenced repository path not found: cypher/README.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_CHECKLIST.md` | 294 | Referenced repository path not found: core/README.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_CHECKLIST.md` | 299 | Referenced repository path not found: neo4j_compat/README.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_CHECKLIST.md` | 305 | Referenced repository path not found: lineage/README.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_CHECKLIST.md` | 310 | Referenced repository path not found: indexing/README.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_CHECKLIST.md` | 316 | Referenced repository path not found: jsonld/README.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/IMPLEMENTATION_CHECKLIST.md` | 344 | Referenced repository path not found: migration/formats.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 49 | Referenced repository path not found: extraction/extractor.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 50 | Referenced repository path not found: core/query_executor.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 159 | Referenced repository path not found: .gitignore | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 302 | Referenced repository path not found: extraction/validator.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 324 | Referenced repository path not found: transactions/wal.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 325 | Referenced repository path not found: query/unified_engine.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 326 | Referenced repository path not found: neo4j_compat/session.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 446 | Referenced repository path not found: jsonld/context.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 456 | Referenced repository path not found: transactions/types.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 459 | Referenced repository path not found: cypher/compiler.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 482 | Referenced repository path not found: constraints/__init__.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 484 | Referenced repository path not found: lineage/types.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 485 | Referenced repository path not found: cypher/ast.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 488 | Referenced repository path not found: migration/formats.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 552 | Referenced repository path not found: extraction/README.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 728 | Referenced repository path not found: migration/schema_checker.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 729 | Referenced repository path not found: migration/integrity_verifier.py | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 1172 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_INTEGRATION_GUIDE.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 1173 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_PHASE_3_4_FINAL_SUMMARY.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/knowledge_graphs/archive/superseded_plans/REFACTORING_IMPROVEMENT_PLAN.md` | 1183 | Referenced repository path not found: docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md | archive-prefix:docs/knowledge_graphs/archive/ |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/CEC_PHASES_4_8_EXECUTION_GUIDE.md` | 316 | Referenced repository path not found: ipfs_datasets_py/logic/CEC/api/ | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md` | 555 | Referenced repository path not found: utils/validation.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md` | 556 | Referenced repository path not found: utils/formatting.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md` | 557 | Referenced repository path not found: utils/conversion.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN.md` | 558 | Referenced repository path not found: utils/caching.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/GAPS_ANALYSIS.md` | 239 | Referenced repository path not found: .github/ | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/IMPLEMENTATION_QUICK_START.md` | 127 | Referenced repository path not found: tests/unit_tests/logic/CEC/test_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/IMPLEMENTATION_QUICK_START.md` | 171 | Referenced repository path not found: docs/_example_test_format.md | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/NATIVE_MIGRATION_SUMMARY.md` | 4 | Referenced repository path not found: ipfs_datasets_py/logic/native | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/NATIVE_MIGRATION_SUMMARY.md` | 154 | Referenced repository path not found: ipfs_datasets_py/logic/native/ | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/NATIVE_MIGRATION_SUMMARY.md` | 158 | Referenced repository path not found: tests/unit_tests/logic/native/ | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/NEXT_SESSION_GUIDE.md` | 280 | Referenced repository path not found: /ipfs_datasets_py/logic/CEC/DCEC_Library/cleaning.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/NEXT_SESSION_GUIDE.md` | 281 | Referenced repository path not found: /ipfs_datasets_py/logic/CEC/DCEC_Library/highLevelParsing.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/NEXT_SESSION_GUIDE.md` | 282 | Referenced repository path not found: /ipfs_datasets_py/logic/CEC/DCEC_Library/prototypes.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 205 | Referenced repository path not found: utils/validation.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 206 | Referenced repository path not found: utils/formatting.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 207 | Referenced repository path not found: utils/conversion.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 208 | Referenced repository path not found: utils/caching.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_3_TRACKER.md` | 149 | Referenced repository path not found: tests/unit_tests/logic/CEC/test_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_3_TRACKER.md` | 202 | Referenced repository path not found: tests/performance/logic/CEC/bench_formula_creation.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_3_TRACKER.md` | 211 | Referenced repository path not found: tests/performance/logic/CEC/bench_proving.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_3_TRACKER.md` | 220 | Referenced repository path not found: tests/performance/logic/CEC/bench_nl_conversion.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_3_TRACKER.md` | 239 | Referenced repository path not found: .github/workflows/cec-tests.yml | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_3_TRACKER.md` | 240 | Referenced repository path not found: .github/workflows/cec-performance.yml | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/PHASE_3_TRACKER.md` | 241 | Referenced repository path not found: ipfs_datasets_py/logic/CEC/DEVELOPER_GUIDE.md | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/SUBMODULE_REIMPLEMENTATION_AUDIT.md` | 250 | Referenced repository path not found: python/EngDCEC.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/WEEK_0_CACHE_TESTS_COMPLETE.md` | 83 | Referenced repository path not found: ipfs_datasets_py/logic/CEC/native/cec_proof_cache.py:320 | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/WEEK_0_ZKP_CACHING_COMPLETION.md` | 211 | Referenced repository path not found: TDFOL/zkp_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/CEC/ARCHIVE/WEEK_0_ZKP_CACHING_COMPLETION.md` | 217 | Referenced repository path not found: common/proof_cache.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 539 | Referenced repository path not found: api/main.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 540 | Referenced repository path not found: api/routers/parsing.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 541 | Referenced repository path not found: api/routers/proving.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 542 | Referenced repository path not found: api/routers/conversion.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 543 | Referenced repository path not found: api/routers/visualization.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 544 | Referenced repository path not found: api/models/requests.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 545 | Referenced repository path not found: api/models/responses.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 546 | Referenced repository path not found: api/middleware/auth.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 547 | Referenced repository path not found: api/middleware/rate_limiting.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 571 | Referenced repository path not found: nl/es/tdfol_nl_patterns_es.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 572 | Referenced repository path not found: nl/es/tdfol_nl_generator_es.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 573 | Referenced repository path not found: nl/fr/tdfol_nl_patterns_fr.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 574 | Referenced repository path not found: nl/fr/tdfol_nl_generator_fr.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 575 | Referenced repository path not found: nl/de/tdfol_nl_patterns_de.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 576 | Referenced repository path not found: nl/de/tdfol_nl_generator_de.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 577 | Referenced repository path not found: nl/domains/medical_patterns.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 578 | Referenced repository path not found: nl/domains/financial_patterns.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 579 | Referenced repository path not found: nl/domains/regulatory_patterns.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 603 | Referenced repository path not found: atps/z3_adapter.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 604 | Referenced repository path not found: atps/vampire_adapter.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 605 | Referenced repository path not found: atps/e_prover_adapter.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 606 | Referenced repository path not found: atps/atp_coordinator.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 628 | Referenced repository path not found: graphrag_integration/logic_aware_kg.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 629 | Referenced repository path not found: graphrag_integration/theorem_rag.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 630 | Referenced repository path not found: graphrag_integration/hybrid_reasoning.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 652 | Referenced repository path not found: acceleration/gpu_prover.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 653 | Referenced repository path not found: distributed/distributed_prover.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE2_TASK22_COMPLETION.md` | 164 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/nl/llm_nl_converter.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE2_TASK22_COMPLETION.md` | 165 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/nl/llm_nl_prompts.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE2_TASK22_COMPLETION.md` | 166 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/nl/cache_utils.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE2_TASK22_COMPLETION.md` | 167 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/nl/spacy_utils.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE2_TASK22_COMPLETION.md` | 170 | Referenced repository path not found: tests/unit_tests/logic/TDFOL/nl/test_llm_nl_converter.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE2_TASK22_COMPLETION.md` | 171 | Referenced repository path not found: tests/unit_tests/logic/TDFOL/nl/test_cache_utils.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE3_TASK31_PROGRESS_REPORT.md` | 28 | Referenced repository path not found: strategies/__init__.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE3_TASK31_PROGRESS_REPORT.md` | 32 | Referenced repository path not found: strategies/base.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE3_TASK31_PROGRESS_REPORT.md` | 41 | Referenced repository path not found: strategies/forward_chaining.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE3_TASK31_SESSION2_SUMMARY.md` | 219 | Referenced repository path not found: strategies/modal_tableaux.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE3_TASK31_SESSION2_SUMMARY.md` | 220 | Referenced repository path not found: strategies/cec_delegate.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE3_TASK31_SESSION2_SUMMARY.md` | 221 | Referenced repository path not found: strategies/strategy_selector.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE3_TASK31_SESSION2_SUMMARY.md` | 224 | Referenced repository path not found: tests/.../strategies/test_modal_tableaux.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE3_TASK31_SESSION2_SUMMARY.md` | 225 | Referenced repository path not found: tests/.../strategies/test_cec_delegate.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE3_TASK31_SESSION2_SUMMARY.md` | 226 | Referenced repository path not found: tests/.../strategies/test_strategy_selector.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE7_PROGRESS.md` | 64 | Referenced repository path not found: nl/__init__.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE_2_AND_3_SUMMARY.md` | 187 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/PHASE2_TASK22_COMPLETION.md | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE_2_AND_3_SUMMARY.md` | 188 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/PHASE3_IMPLEMENTATION_PLAN.md | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE_2_AND_3_SUMMARY.md` | 189 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/PHASE3_WEEK1_PROGRESS.md | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/PHASE_2_AND_3_SUMMARY.md` | 190 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/PHASE3_WEEK1_COMPLETE.md | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/QUICK_REFERENCE_2026_02_18.md` | 67 | Referenced repository path not found: nl/spacy_utils.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` | 351 | Referenced repository path not found: strategies/base.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` | 441 | Referenced repository path not found: examples/strategy_usage.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_AND_IMPROVEMENT_PLAN_FINAL.md` | 497 | Referenced repository path not found: visualization/common.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_PLAN_2026_02_18.md` | 108 | Referenced repository path not found: nl/tdfol_nl_context.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_PLAN_2026_02_18.md` | 326 | Referenced repository path not found: nl/tdfol_nl_preprocessor.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_PLAN_2026_02_18.md` | 326 | Referenced repository path not found: nl/tdfol_nl_patterns.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/REFACTORING_QUICK_REF.md` | 56 | Referenced repository path not found: strategies/base.py | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/SECURITY_VALIDATOR_SUMMARY.md` | 108 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/README_security_validator.md | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/TASK_11.3_COMPLETE.md` | 41 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/countermodel_visualizer_README.md | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/TASK_12.1_COMPLETE.md` | 99 | Referenced repository path not found: ipfs_datasets_py/logic/TDFOL/performance_profiler_README.md | archive-path-segment |
| `repo_paths` | `docs/logic/TDFOL/ARCHIVE/TRACK1_COMPLETION_REPORT.md` | 144 | Referenced repository path not found: nl/spacy_utils.py | archive-path-segment |
| `repo_paths` | `docs/logic/archive/ENHANCED_REFACTORING_PLAN.md` | 12 | Referenced repository path not found: common/converters.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/ENHANCED_REFACTORING_PLAN.md` | 734 | Referenced repository path not found: tools/deontic_logic_core.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/ENHANCED_REFACTORING_PLAN.md` | 734 | Referenced repository path not found: integration/deontic_logic_core.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/ENHANCED_REFACTORING_PLAN.md` | 766 | Referenced repository path not found: fol/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/ENHANCED_REFACTORING_PLAN.md` | 784 | Referenced repository path not found: deontic/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/ENHANCED_REFACTORING_PLAN.md` | 867 | Referenced repository path not found: integration/deontic_logic_converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/ENHANCED_REFACTORING_PLAN.md` | 868 | Referenced repository path not found: integration/modal_logic_extension.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/IMPLEMENTATION_STATUS.md` | 24 | Referenced repository path not found: fol/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/IMPLEMENTATION_STATUS.md` | 31 | Referenced repository path not found: deontic/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/IMPLEMENTATION_STATUS.md` | 149 | Referenced repository path not found: fol/text_to_fol_original.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/IMPLEMENTATION_STATUS.md` | 150 | Referenced repository path not found: deontic/legal_text_to_deontic_original.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/IMPLEMENTATION_STATUS.md` | 161 | Referenced repository path not found: fol/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/IMPLEMENTATION_STATUS.md` | 162 | Referenced repository path not found: fol/text_to_fol.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/IMPLEMENTATION_STATUS.md` | 163 | Referenced repository path not found: deontic/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/IMPLEMENTATION_STATUS.md` | 164 | Referenced repository path not found: deontic/legal_text_to_deontic.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE2_COMPLETE.md` | 243 | Referenced repository path not found: logic/neurosymbolic/reasoning_coordinator.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE2_COMPLETE.md` | 244 | Referenced repository path not found: logic/neurosymbolic/neural_guided_search.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE2_COMPLETE.md` | 245 | Referenced repository path not found: logic/neurosymbolic/embedding_prover.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE2_COMPLETE.md` | 246 | Referenced repository path not found: logic/neurosymbolic/hybrid_confidence.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE3_COMPLETE.md` | 54 | Referenced repository path not found: logic/integration/neurosymbolic/reasoning_coordinator.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE3_COMPLETE.md` | 90 | Referenced repository path not found: logic/integration/neurosymbolic/embedding_prover.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE3_COMPLETE.md` | 127 | Referenced repository path not found: logic/integration/neurosymbolic/hybrid_confidence.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 20 | Referenced repository path not found: ipfs_datasets_py/rag/logic_integration/logic_aware_entity_extractor.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 47 | Referenced repository path not found: ipfs_datasets_py/rag/logic_integration/logic_aware_knowledge_graph.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 74 | Referenced repository path not found: ipfs_datasets_py/rag/logic_integration/theorem_augmented_rag.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 92 | Referenced repository path not found: ipfs_datasets_py/rag/logic_integration/logic_enhanced_rag.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 117 | Referenced repository path not found: ipfs_datasets_py/rag/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 118 | Referenced repository path not found: ipfs_datasets_py/rag/logic_integration/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 126 | Referenced repository path not found: tests/unit_tests/rag/logic_integration/test_logic_aware_entity_extractor.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 148 | Referenced repository path not found: tests/unit_tests/rag/logic_integration/test_logic_aware_knowledge_graph.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 173 | Referenced repository path not found: tests/unit_tests/rag/logic_integration/test_logic_enhanced_rag.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE4_COMPLETE.md` | 256 | Referenced repository path not found: ipfs_datasets_py/processors/graphrag/ | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE6_COMPLETE.md` | 26 | Referenced repository path not found: tests/unit_tests/rag/logic_integration/ | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE_REPORTS/PHASE6_PROGRESS_REPORT.md` | 44 | Referenced repository path not found: bridges/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE_REPORTS/PHASE6_PROGRESS_REPORT.md` | 46 | Referenced repository path not found: reasoning/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE_REPORTS/PHASE6_PROGRESS_REPORT.md` | 47 | Referenced repository path not found: converters/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE_REPORTS/PHASE6_PROGRESS_REPORT.md` | 48 | Referenced repository path not found: domain/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE_REPORTS/PHASE6_PROGRESS_REPORT.md` | 49 | Referenced repository path not found: interactive/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE_REPORTS/PHASE6_PROGRESS_REPORT.md` | 50 | Referenced repository path not found: symbolic/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/PHASE_REPORTS/PHASE6_PROGRESS_REPORT.md` | 51 | Referenced repository path not found: demos/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 159 | Referenced repository path not found: ipfs_datasets_py/logic/FEATURES.md | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 296 | Referenced repository path not found: fol/text_to_fol.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 297 | Referenced repository path not found: fol/utils/fol_parser.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 298 | Referenced repository path not found: fol/utils/predicate_extractor.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 299 | Referenced repository path not found: fol/utils/logic_formatter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 300 | Referenced repository path not found: fol/utils/nlp_predicate_extractor.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 301 | Referenced repository path not found: fol/utils/deontic_parser.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 346 | Referenced repository path not found: deontic/legal_text_to_deontic.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 347 | Referenced repository path not found: deontic/utils/deontic_parser.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 348 | Referenced repository path not found: deontic/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 363 | Referenced repository path not found: common/converters.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 364 | Referenced repository path not found: common/errors.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 489 | Referenced repository path not found: TDFOL/tdfol_proof_cache.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 490 | Referenced repository path not found: external_provers/proof_cache.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 578 | Referenced repository path not found: integration/proof_execution_engine.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 579 | Referenced repository path not found: external_provers/prover_router.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 580 | Referenced repository path not found: TDFOL/tdfol_prover.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 620 | Referenced repository path not found: logic/ml_confidence/train_models.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 691 | Referenced repository path not found: integration/ipfs_proof_cache.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 692 | Referenced repository path not found: integration/ipld_logic_storage.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 744 | Referenced repository path not found: logic/monitoring_dashboard.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/REFACTORING_PLAN.md` | 843 | Referenced repository path not found: integration/api.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-13.md` | 89 | Referenced repository path not found: logic_utils/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-13.md` | 90 | Referenced repository path not found: logic_utils/deontic_parser.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-13.md` | 91 | Referenced repository path not found: logic_utils/fol_parser.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-13.md` | 92 | Referenced repository path not found: logic_utils/logic_formatter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-13.md` | 93 | Referenced repository path not found: logic_utils/predicate_extractor.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-13.md` | 358 | Referenced repository path not found: fol/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-13.md` | 358 | Referenced repository path not found: deontic/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-14_evening.md` | 133 | Referenced repository path not found: deontic/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-14_evening.md` | 133 | Referenced repository path not found: deontic/utils/deontic_nlp_extractor.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-14_evening.md` | 307 | Referenced repository path not found: ipfs_datasets_py/logic/FEATURES.md | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-14_evening.md` | 322 | Referenced repository path not found: fol/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-14_evening.md` | 323 | Referenced repository path not found: common/converters.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-14_evening.md` | 324 | Referenced repository path not found: integration/proof_cache.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/SESSIONS/SESSION_2026-02-14_evening.md` | 325 | Referenced repository path not found: fol/utils/nlp_predicate_extractor.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/code_backups/README.md` | 28 | Referenced repository path not found: fol/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/code_backups/README.md` | 28 | Referenced repository path not found: fol/text_to_fol.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/code_backups/README.md` | 29 | Referenced repository path not found: deontic/converter.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/code_backups/README.md` | 29 | Referenced repository path not found: deontic/legal_text_to_deontic.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 33 | Referenced repository path not found: common/bounded_cache.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 87 | Referenced repository path not found: ipfs_datasets_py/logic/CACHING_ARCHITECTURE.md | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 160 | Referenced repository path not found: ipfs_datasets_py/logic/DOCUMENTATION_INDEX.md | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 291 | Referenced repository path not found: external_provers/proof_cache.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 292 | Referenced repository path not found: TDFOL/tdfol_proof_cache.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 293 | Referenced repository path not found: integration/caching/proof_cache.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 301 | Referenced repository path not found: common/proof_cache.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 303 | Referenced repository path not found: common/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 312 | Referenced repository path not found: docs/archive/code_backups/ | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/IMPLEMENTATION_SUMMARY.md` | 348 | Referenced repository path not found: integration/caching/__init__.py | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/LOGIC_REFACTORING_FINAL_REPORT.md` | 31 | Referenced repository path not found: docs/archive/PHASE_REPORTS/ | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/LOGIC_REFACTORING_FINAL_REPORT.md` | 32 | Referenced repository path not found: docs/archive/SESSIONS/ | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/LOGIC_REFACTORING_FINAL_REPORT.md` | 51 | Referenced repository path not found: docs/archive/code_backups/ | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/archive/status_reports/LOGIC_REFACTORING_FINAL_REPORT.md` | 349 | Referenced repository path not found: docs/archive/code_backups/README.md | archive-prefix:docs/logic/archive/ |
| `repo_paths` | `docs/logic/docs/archive/phases/ANALYSIS_SUMMARY.md` | 126 | Referenced repository path not found: integrations/phase7_complete_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/phases/ANALYSIS_SUMMARY.md` | 127 | Referenced repository path not found: integrations/enhanced_graphrag_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/phases_2026/ANALYSIS_SUMMARY.md` | 126 | Referenced repository path not found: integrations/phase7_complete_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/phases_2026/ANALYSIS_SUMMARY.md` | 127 | Referenced repository path not found: integrations/enhanced_graphrag_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/phases_2026/ARCHIVED_PHASE3_P0_VERIFICATION_REPORT.md` | 189 | Referenced repository path not found: CEC/native/prover_core.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/phases_2026/ARCHIVED_PHASE3_P0_VERIFICATION_REPORT.md` | 190 | Referenced repository path not found: fol/converter.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_CACHING_ARCHITECTURE.md` | 43 | Referenced repository path not found: common/converters.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_CACHING_ARCHITECTURE.md` | 101 | Referenced repository path not found: external_provers/proof_cache.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_CACHING_ARCHITECTURE.md` | 137 | Referenced repository path not found: TDFOL/tdfol_proof_cache.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_CACHING_ARCHITECTURE.md` | 163 | Referenced repository path not found: integration/caching/proof_cache.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_CACHING_ARCHITECTURE.md` | 182 | Referenced repository path not found: integration/caching/ipfs_proof_cache.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_COMPREHENSIVE_REFACTORING_AND_IMPROVEMENT_PLAN_2026.md` | 181 | Referenced repository path not found: integration/TODO.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_COMPREHENSIVE_REFACTORING_PLAN.md` | 67 | Referenced repository path not found: integration/TODO.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_COMPREHENSIVE_REFACTORING_PLAN.md` | 95 | Referenced repository path not found: docs/archive/phases/ | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_COMPREHENSIVE_REFACTORING_PLAN.md` | 173 | Referenced repository path not found: docs/archive/planning/ | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_COMPREHENSIVE_REFACTORING_PLAN.md` | 208 | Referenced repository path not found: CEC/native/prover_core.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_COMPREHENSIVE_REFACTORING_PLAN.md` | 212 | Referenced repository path not found: fol/converter.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 28 | Referenced repository path not found: logic/integration/symbolic/symbolic_fol_bridge.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 773 | Referenced repository path not found: integration/domain/symbolic_contracts.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 774 | Referenced repository path not found: integration/converters/semantic_converter.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 783 | Referenced repository path not found: integration/caching/ipfs_proof_cache.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 784 | Referenced repository path not found: integration/caching/ipld_logic_storage.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 785 | Referenced repository path not found: TDFOL/tdfol_prover.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 786 | Referenced repository path not found: TDFOL/tdfol_dcec_parser.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 789 | Referenced repository path not found: external_provers/smt/z3_prover_bridge.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_FALLBACK_BEHAVIORS.md` | 790 | Referenced repository path not found: external_provers/__init__.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPLEMENTATION_ROADMAP.md` | 238 | Referenced repository path not found: logic/common/runtime.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPLEMENTATION_ROADMAP.md` | 350 | Referenced repository path not found: integration/TODO.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPLEMENTATION_ROADMAP.md` | 356 | Referenced repository path not found: docs/archive/phases/PHASE_6_COMPLETION_SUMMARY.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPLEMENTATION_ROADMAP.md` | 357 | Referenced repository path not found: docs/archive/phases/PHASE_7_SESSION_SUMMARY.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPLEMENTATION_ROADMAP.md` | 358 | Referenced repository path not found: docs/archive/phases/FINAL_STATUS_REPORT.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO.md` | 79 | Referenced repository path not found: types/README.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO.md` | 163 | Referenced repository path not found: types/common_types.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO.md` | 286 | Referenced repository path not found: logic/common/runtime.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO.md` | 314 | Referenced repository path not found: types/public.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO_2026_02_19.md` | 79 | Referenced repository path not found: types/README.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO_2026_02_19.md` | 118 | Referenced repository path not found: logic/zkp/IMPROVEMENT_TODO.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO_2026_02_19.md` | 164 | Referenced repository path not found: types/common_types.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO_2026_02_19.md` | 287 | Referenced repository path not found: logic/common/runtime.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_IMPROVEMENT_TODO_2026_02_19.md` | 315 | Referenced repository path not found: types/public.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_PHASE3_P0_VERIFICATION_REPORT.md` | 189 | Referenced repository path not found: CEC/native/prover_core.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_PHASE3_P0_VERIFICATION_REPORT.md` | 190 | Referenced repository path not found: fol/converter.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_COMPLETION_SUMMARY_2026.md` | 30 | Referenced repository path not found: fol/utils/fol_parser.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_COMPLETION_SUMMARY_2026.md` | 41 | Referenced repository path not found: docs/archive/phases_2026/ | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_COMPLETION_SUMMARY_2026.md` | 41 | Referenced repository path not found: docs/archive/planning/ | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_EXECUTIVE_SUMMARY.md` | 36 | Referenced repository path not found: integration/TODO.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 168 | Referenced repository path not found: docs/archive/HISTORICAL/ | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 176 | Referenced repository path not found: logic/TYPE_SYSTEM_STATUS.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 563 | Referenced repository path not found: logic/FALLBACK_BEHAVIORS.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 600 | Referenced repository path not found: logic/external_provers/z3_prover.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 657 | Referenced repository path not found: integrations/__init__.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 707 | Referenced repository path not found: logic/docs/DEPENDENCY_GRAPH.md | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 758 | Referenced repository path not found: tests/unit_tests/logic/test_fallbacks.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 769 | Referenced repository path not found: tests/unit_tests/logic/test_optional_deps.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 23 | Referenced repository path not found: common/converters.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 24 | Referenced repository path not found: common/utility_monitor.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 25 | Referenced repository path not found: common/errors.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 26 | Referenced repository path not found: fol/converter.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 27 | Referenced repository path not found: deontic/converter.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 41 | Referenced repository path not found: integration/reasoning/deontological_reasoning_types.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 42 | Referenced repository path not found: types/common_types.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 50 | Referenced repository path not found: CEC/native/grammar_engine.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_TYPE_SYSTEM_STATUS.md` | 51 | Referenced repository path not found: CEC/native/shadow_prover.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_VERIFIED_STATUS_REPORT.md` | 55 | Referenced repository path not found: CEC/native/prover_core.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_VERIFIED_STATUS_REPORT.md` | 83 | Referenced repository path not found: fol/converter.py | archive-path-segment |
| `repo_paths` | `docs/logic/docs/archive/planning/ARCHIVED_VERIFIED_STATUS_REPORT_2026.md` | 33 | Referenced repository path not found: integration/bridges/base_prover_bridge.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/COMPREHENSIVE_REFACTORING_PLAN.md` | 536 | Referenced repository path not found: examples/logic/zkp/ | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/COMPREHENSIVE_REFACTORING_PLAN.md` | 542 | Referenced repository path not found: tests/integration/zkp/ | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/FINDINGS_SUMMARY.md` | 64 | Referenced repository path not found: ARCHIVE/README.md | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/GROTH16_IMPLEMENTATION_PLAN.md` | 48 | Referenced repository path not found: logic/zkp/backends/groth16_py_ecc.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/IMPROVEMENT_TODO.md` | 93 | Referenced repository path not found: logic/zkp/GROTH16_IMPLEMENTATION_PLAN.md | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/OPTIONAL_TASKS_COMPLETION_REPORT.md` | 337 | Referenced repository path not found: backends/groth16.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/OPTIONAL_TASKS_COMPLETION_REPORT.md` | 343 | Referenced repository path not found: backends/simulated.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/PHASE3_GROTH16_STACK_SELECTION.md` | 313 | Referenced repository path not found: backends/groth16_ark.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/PHASES_3-5_COMPLETION_REPORT.md` | 386 | Referenced repository path not found: backends/simulated.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/PHASES_3-5_COMPLETION_REPORT.md` | 386 | Referenced repository path not found: backends/groth16.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/REFACTORING_STATUS_2026_02_18.md` | 56 | Referenced repository path not found: examples/zkp_basic_demo.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/REFACTORING_STATUS_2026_02_18.md` | 57 | Referenced repository path not found: examples/zkp_advanced_demo.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/REFACTORING_STATUS_2026_02_18.md` | 58 | Referenced repository path not found: examples/zkp_ipfs_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/SETUP_GUIDE.md` | 23 | Referenced repository path not found: ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/ | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/ZKP_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 49 | Referenced repository path not found: examples/zkp_basic_demo.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/ZKP_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 50 | Referenced repository path not found: examples/zkp_advanced_demo.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/ZKP_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 51 | Referenced repository path not found: examples/zkp_ipfs_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/ZKP_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 54 | Referenced repository path not found: tests/test_zkp_module.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/ZKP_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 55 | Referenced repository path not found: tests/test_zkp_performance.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/ZKP_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 56 | Referenced repository path not found: tests/test_zkp_integration.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/ZKP_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 85 | Referenced repository path not found: backends/__init__.py | archive-path-segment |
| `repo_paths` | `docs/logic/zkp/ARCHIVE/ZKP_COMPREHENSIVE_IMPROVEMENT_PLAN_2026_02_18.md` | 86 | Referenced repository path not found: backends/simulated.py | archive-path-segment |
| `repo_paths` | `docs/maintenance/LEGACY_DISPOSITION.md` | 200 | Referenced repository path not found: retrieval/VECTOR_STORES.md | migration-substring:legacy |
| `repo_paths` | `docs/maintenance/LEGACY_DISPOSITION.md` | 297 | Referenced repository path not found: docs/architecture/decisions/ADR-001 | migration-substring:legacy |
| `repo_paths` | `docs/maintenance/LEGACY_DISPOSITION.md` | 362 | Referenced repository path not found: ipfs_datasets_py/mcp_server/docs/adr/ADR-001 | migration-substring:legacy |
| `repo_paths` | `docs/maintenance/LEGACY_DISPOSITION.md` | 390 | Referenced repository path not found: decisions/ADR-NNN-....md | migration-substring:legacy |
| `repo_paths` | `docs/maintenance/LEGACY_DISPOSITION.md` | 390 | Referenced repository path not found: decisions/ADR_TEMPLATE.md | migration-substring:legacy |
| `repo_paths` | `docs/maintenance/LEGACY_DISPOSITION.md` | 391 | Referenced repository path not found: logic/EXTERNAL_PROVERS.md | migration-substring:legacy |
| `repo_paths` | `docs/maintenance/LEGACY_DISPOSITION.md` | 392 | Referenced repository path not found: security_ir_artifacts/...json | migration-substring:legacy |
| `repo_paths` | `docs/migration_docs/CLAUDES_TOOLBOX_MIGRATION_ROADMAP.md` | 49 | Referenced repository path not found: claudes_toolbox/pyproject.toml | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/CLAUDES_TOOLBOX_MIGRATION_ROADMAP.md` | 67 | Referenced repository path not found: claudes_toolbox/server.py | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/DEVELOPMENT_TOOLS_README.md` | 170 | Referenced repository path not found: .vscode/mcp_settings.json | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/MCP_CONFIGURATION_SUMMARY.md` | 21 | Referenced repository path not found: .vscode/settings.json | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/MCP_CONFIGURATION_SUMMARY.md` | 137 | Referenced repository path not found: ./start_mcp_server.sh | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/MIGRATION_VERIFICATION_COMPLETE_OLD.md` | 33 | Referenced repository path not found: .github/workflows/documentation-maintenance.yml | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/MIGRATION_VERIFICATION_COMPLETE_OLD.md` | 34 | Referenced repository path not found: adhoc_tools/find_documentation.py | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/MIGRATION_VERIFICATION_COMPLETE_OLD.md` | 35 | Referenced repository path not found: adhoc_tools/docstring_audit.py | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/MIGRATION_VERIFICATION_COMPLETE_OLD.md` | 46 | Referenced repository path not found: .vscode/tasks.json | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/MIGRATION_VERIFICATION_COMPLETE_OLD.md` | 71 | Referenced repository path not found: tmp/docstring_report.json | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/PHASE1_COMPLETE.md` | 110 | Referenced repository path not found: .vscode/mcp_settings.json | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/VSCODE_INTEGRATION_TESTING.md` | 15 | Referenced repository path not found: .vscode/mcp_settings.json | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/VSCODE_MCP_GUIDE.md` | 18 | Referenced repository path not found: .vscode/settings.json | migration-substring:migration |
| `repo_paths` | `docs/migration_docs/VSCODE_MCP_GUIDE.md` | 160 | Referenced repository path not found: ./start_mcp_server.sh | migration-substring:migration |
| `python_modules` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 29 | Python module not found on tree: ipfs_datasets_py.data_transformation | origin=prose |
| `python_modules` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 68 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 96 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization | origin=import |
| `python_modules` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 100 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 101 | Python module not found on tree: ipfs_datasets_py.data_transformation.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 121 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipfs_formats | origin=import |
| `python_modules` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 122 | Python module not found on tree: ipfs_datasets_py.data_transformation.unixfs | origin=import |
| `python_modules` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 139 | Python module not found on tree: ipfs_datasets_py.data_transformation.ucan | origin=import |
| `python_modules` | `docs/DATA_TRANSFORMATION_MIGRATION_SUMMARY.md` | 136 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/DATA_TRANSFORMATION_MIGRATION_SUMMARY.md` | 137 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization | origin=import |
| `python_modules` | `docs/DATA_TRANSFORMATION_MIGRATION_SUMMARY.md` | 138 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipfs_formats | origin=import |
| `python_modules` | `docs/DATA_TRANSFORMATION_MIGRATION_SUMMARY.md` | 139 | Python module not found on tree: ipfs_datasets_py.data_transformation.ucan | origin=import |
| `python_modules` | `docs/DEPRECATION_TIMELINE.md` | 62 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/DEPRECATION_TIMELINE.md` | 91 | Python module not found on tree: ipfs_datasets_py.data_transformation | origin=import |
| `python_modules` | `docs/DEPRECATION_TIMELINE.md` | 97 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/DEPRECATION_TIMELINE.md` | 103 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization | origin=import |
| `python_modules` | `docs/DEPRECATION_TIMELINE.md` | 109 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=import |
| `python_modules` | `docs/DEPRECATION_TIMELINE.md` | 129 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.unified_graphrag | origin=import |
| `python_modules` | `docs/DEPRECATION_TIMELINE.md` | 168 | Python module not found on tree: ipfs_datasets_py.tools.migration_checker | origin=prose |
| `python_modules` | `docs/DEPRECATION_TIMELINE.md` | 180 | Python module not found on tree: ipfs_datasets_py.tools.migration_generator | origin=prose |
| `python_modules` | `docs/DEPRECATION_TIMELINE.md` | 185 | Python module not found on tree: ipfs_datasets_py.tools.compatibility_tester | origin=prose |
| `python_modules` | `docs/MIGRATION_CHANGELOG.md` | 50 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 70 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 161 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 162 | Python module not found on tree: ipfs_datasets_py.data_transformation.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 163 | Python module not found on tree: ipfs_datasets_py.data_transformation.dataset_serialization | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 164 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipfs_parquet_to_car | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 167 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 168 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 169 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.dataset_serialization | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 170 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.ipfs_parquet_to_car | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 262 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.unified_graphrag | origin=import |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 605 | Python module not found on tree: ipfs_datasets_py.tools.migration_checker | origin=prose |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 635 | Python module not found on tree: ipfs_datasets_py.tools.migration_generator | origin=prose |
| `python_modules` | `docs/MIGRATION_GUIDE_V2.md` | 648 | Python module not found on tree: ipfs_datasets_py.tools.compatibility_tester | origin=prose |
| `python_modules` | `docs/MULTIMEDIA_MIGRATION_GUIDE.md` | 26 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 209 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 219 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/archive/completion_reports/IMPLEMENTATION_ROADMAP_COMPLETE.md` | 222 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=import |
| `python_modules` | `docs/archive/completion_reports/PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md` | 108 | Python module not found on tree: ipfs_datasets_py.logic_integration | origin=backtick |
| `python_modules` | `docs/archive/completion_reports/PHASE_2_TASK_2_2_USAGE_ANALYSIS.md` | 53 | Python module not found on tree: ipfs_datasets_py.cross_document_lineage_enhanced | origin=import |
| `python_modules` | `docs/archive/completion_reports/PHASE_3_4_GRAPHRAG_CONSOLIDATION_PLAN.md` | 172 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.unified_graphrag | origin=import |
| `python_modules` | `docs/archive/completion_reports/UTILS_REFACTORING_COMPLETE.md` | 193 | Python module not found on tree: ipfs_datasets_py.utils.old_module | origin=prose |
| `python_modules` | `docs/archive/completion_reports/UTILS_REFACTORING_COMPLETE.md` | 194 | Python module not found on tree: ipfs_datasets_py.utils.new_module | origin=prose |
| `python_modules` | `docs/archive/completion_reports/phases/PHASE_2_SERIALIZATION_COMPLETE.md` | 52 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=prose |
| `python_modules` | `docs/archive/completion_reports/phases/PHASE_2_SERIALIZATION_COMPLETE.md` | 53 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=prose |
| `python_modules` | `docs/archive/completion_reports/phases/PHASE_2_SESSIONS_7_8_COMPLETE.md` | 96 | Python module not found on tree: ipfs_datasets_py.cross_document_lineage_enhanced | origin=import |
| `python_modules` | `docs/archive/completion_reports/phases/PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md` | 51 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.unified_graphrag.UnifiedGraphRAGProcessor | origin=prose |
| `python_modules` | `docs/archive/completion_reports/phases/PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md` | 92 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.unified_graphrag.GraphRAGConfiguration | origin=prose |
| `python_modules` | `docs/archive/completion_reports/phases/PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md` | 110 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.unified_graphrag | origin=import |
| `python_modules` | `docs/archive/completion_reports/phases/PHASE_4_GRAPHRAG_IMPLEMENTATION_COMPLETE.md` | 130 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.website_system | origin=import |
| `python_modules` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 115 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.adapter | origin=import |
| `python_modules` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_PROGRESS.md` | 281 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.adapter | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_1_1_MULTIMEDIA_AUDIT_REPORT.md` | 87 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=prose |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_1_2_CLEANUP_COMPLETE_REPORT.md` | 102 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=prose |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 50 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld.storage | origin=backtick |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 51 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.dataset_serialization | origin=backtick |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 95 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 96 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 101 | Python module not found on tree: ipfs_datasets_py.data_transformation | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 102 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 121 | Python module not found on tree: ipfs_datasets_py.data_transformation.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 122 | Python module not found on tree: ipfs_datasets_py.data_transformation.dataset_serialization | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 123 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipfs_parquet_to_car | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 129 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_1_SERIALIZATION_PACKAGE_COMPLETE.md` | 131 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.ipfs_parquet_to_car | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 49 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=prose |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 50 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.car_conversion | origin=prose |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 60 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.dataset_serialization | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 61 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/archive/completion_reports/tasks/TASK_2_2_IMPORTS_UPDATE_COMPLETE.md` | 62 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization.ipfs_parquet_to_car | origin=import |
| `python_modules` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_IMPLEMENTATION_SUMMARY.md` | 570 | Python module not found on tree: ipfs_datasets_py.git | origin=prose |
| `python_modules` | `docs/archive/processors/ARCHIVE_INDEX.md` | 43 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.complete_advanced_graphrag | origin=import |
| `python_modules` | `docs/archive/processors/ARCHIVE_INDEX.md` | 75 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.enhanced_integration | origin=import |
| `python_modules` | `docs/archive/processors/ARCHIVE_INDEX.md` | 106 | Python module not found on tree: ipfs_datasets_py.processors.graphrag.phase7_complete_integration | origin=import |
| `python_modules` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 981 | Python module not found on tree: ipfs_datasets_py.processors.graphrag | origin=import |
| `python_modules` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_INTEGRATION_PLAN_2026_02.md` | 1008 | Python module not found on tree: ipfs_datasets_py.processors.specialized.multimedia | origin=import |
| `python_modules` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 421 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 544 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=prose |
| `python_modules` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 987 | Python module not found on tree: ipfs_datasets_py.processors.graphrag | origin=prose |
| `python_modules` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v37.md` | 244 | Python module not found on tree: ipfs_datasets_py.admin_dashboard | origin=backtick |
| `python_modules` | `docs/archive/reorganization/MASTER_REFACTORING_PLAN_2026_v4.md` | 957 | Python module not found on tree: ipfs_datasets_py.core | origin=import |
| `python_modules` | `docs/archive/reorganization/comprehensive_documentation_update.md` | 100 | Python module not found on tree: ipfs_datasets_py.integrations.graphrag_integration | origin=import |
| `python_modules` | `docs/archive/reorganization/comprehensive_documentation_update.md` | 101 | Python module not found on tree: ipfs_datasets_py.integrations.phase7_complete_integration | origin=import |
| `python_modules` | `docs/archive/reorganization/comprehensive_documentation_update.md` | 108 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/archive/reorganization/comprehensive_documentation_update.md` | 109 | Python module not found on tree: ipfs_datasets_py.data_transformation.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/archive/reorganization/comprehensive_documentation_update.md` | 192 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=import |
| `python_modules` | `docs/archive/reorganization/older_readme_sections_review.md` | 265 | Python module not found on tree: ipfs_datasets_py.logic_integration | origin=import |
| `python_modules` | `docs/archive/reorganization/older_readme_sections_review.md` | 267 | Python module not found on tree: ipfs_datasets_py.pdf_processing | origin=import |
| `python_modules` | `docs/archive/reorganization/older_readme_sections_review.md` | 270 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/archive/reorganization/older_readme_sections_review.md` | 273 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/archive/reorganization/older_sections_update_evidence.md` | 58 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=prose |
| `python_modules` | `docs/archive/reorganization/older_sections_update_evidence.md` | 77 | Python module not found on tree: ipfs_datasets_py.advanced_web_archiving | origin=import |
| `python_modules` | `docs/archive/reorganization/readme_update_summary.md` | 117 | Python module not found on tree: ipfs_datasets_py.integrations.accelerate_integration | origin=prose |
| `python_modules` | `docs/archive/reorganization/readme_update_summary.md` | 120 | Python module not found on tree: ipfs_datasets_py.web_archive_tools | origin=prose |
| `python_modules` | `docs/archive/root_status_reports/EXTERNAL_PROVER_INTEGRATION.md` | 341 | Python module not found on tree: ipfs_datasets_py.logic.external_provers.get_available_provers | origin=prose |
| `python_modules` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 364 | Python module not found on tree: ipfs_datasets_py.rag.logic_aware_entity_extractor | origin=import |
| `python_modules` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 621 | Python module not found on tree: ipfs_datasets_py.rag.logic_knowledge_graph | origin=import |
| `python_modules` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 720 | Python module not found on tree: ipfs_datasets_py.rag.logic_enhanced_rag | origin=import |
| `python_modules` | `docs/archive/root_status_reports/GRAPHRAG_INTEGRATION_DETAILED.md` | 861 | Python module not found on tree: ipfs_datasets_py.rag | origin=prose |
| `python_modules` | `docs/archive/root_status_reports/NEUROSYMBOLIC_ARCHITECTURE_PLAN.md` | 816 | Python module not found on tree: ipfs_datasets_py.graphrag.integrations | origin=import |
| `python_modules` | `docs/archive/root_status_reports/NEUROSYMBOLIC_ARCHITECTURE_PLAN.md` | 1103 | Python module not found on tree: ipfs_datasets_py.logic.neurosymbolic | origin=import |
| `python_modules` | `docs/archive/root_status_reports/OPTIMIZER_FRAMEWORK_IMPROVEMENTS.md` | 597 | Python module not found on tree: ipfs_datasets_py.optimizers.common.logging_config | origin=import |
| `python_modules` | `docs/archive/root_status_reports/PHASE5_FINAL_REPORT.md` | 345 | Python module not found on tree: ipfs_datasets_py.logic.integration.proof_execution_engine | origin=import |
| `python_modules` | `docs/archive/root_status_reports/PHASE5_FINAL_REPORT.md` | 379 | Python module not found on tree: ipfs_datasets_py.logic.integration.ipfs_proof_cache | origin=import |
| `python_modules` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 950 | Python module not found on tree: ipfs_datasets_py.processors.specialized.example | origin=import |
| `python_modules` | `docs/archive/root_status_reports/SYMBOLICAI_INTEGRATION_ANALYSIS.md` | 584 | Python module not found on tree: ipfs_datasets_py.logic.neurosymbolic | origin=import |
| `python_modules` | `docs/archive/root_status_reports/TESTING_STRATEGY.md` | 463 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/guides/infrastructure/anyio_migration_guide.md` | 166 | Python module not found on tree: ipfs_datasets_py.file_converter.deprecation | origin=import |
| `python_modules` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_NEO4J_API_MIGRATION.md` | 376 | Python module not found on tree: ipfs_datasets_py.knowledge_graphs.migration.verify | origin=prose |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 19 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipld | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 35 | Python module not found on tree: ipfs_datasets_py.data_transformation.serialization | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 37 | Python module not found on tree: ipfs_datasets_py.data_transformation.car_conversion | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 38 | Python module not found on tree: ipfs_datasets_py.data_transformation.jsonl_to_parquet | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 39 | Python module not found on tree: ipfs_datasets_py.data_transformation.dataset_serialization | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 53 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipfs_formats | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 54 | Python module not found on tree: ipfs_datasets_py.data_transformation.ipfs_formats.ipfs_multiformats | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 55 | Python module not found on tree: ipfs_datasets_py.data_transformation.unixfs | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 59 | Python module not found on tree: ipfs_datasets_py.processors.ipfs.formats.multiformats | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 67 | Python module not found on tree: ipfs_datasets_py.data_transformation.ucan | origin=import |
| `python_modules` | `docs/guides/processors/PROCESSORS_DATA_TRANSFORMATION_QUICK_MIGRATION.md` | 77 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/logic/CEC/ARCHIVE/CEC_PHASES_4_8_EXECUTION_GUIDE.md` | 362 | Python module not found on tree: ipfs_datasets_py.logic.CEC.api.server | origin=prose |
| `python_modules` | `docs/logic/CEC/ARCHIVE/NATIVE_INTEGRATION.md` | 350 | Python module not found on tree: ipfs_datasets_py.logic.CEC.dcec_wrapper.importlib | origin=prose |
| `python_modules` | `docs/logic/CEC/ARCHIVE/NATIVE_MIGRATION_SUMMARY.md` | 54 | Python module not found on tree: ipfs_datasets_py.logic.native | origin=import |
| `python_modules` | `docs/logic/CEC/ARCHIVE/NATIVE_MIGRATION_SUMMARY.md` | 55 | Python module not found on tree: ipfs_datasets_py.logic.native.dcec_core | origin=import |
| `python_modules` | `docs/logic/CEC/ARCHIVE/NATIVE_MIGRATION_SUMMARY.md` | 56 | Python module not found on tree: ipfs_datasets_py.logic.native.prover_core | origin=import |
| `python_modules` | `docs/logic/MIGRATION_GUIDE.md` | 353 | Python module not found on tree: ipfs_datasets_py.logic.tools.text_to_fol | origin=import |
| `python_modules` | `docs/logic/MIGRATION_GUIDE.md` | 365 | Python module not found on tree: ipfs_datasets_py.logic.tools.deontic_logic_core | origin=import |
| `python_modules` | `docs/logic/MIGRATION_GUIDE.md` | 386 | Python module not found on tree: ipfs_datasets_py.logic.tools.symbolic_fol_bridge | origin=import |
| `python_modules` | `docs/logic/MIGRATION_GUIDE.md` | 397 | Python module not found on tree: ipfs_datasets_py.logic.tools.symbolic_logic_primitives | origin=import |
| `python_modules` | `docs/logic/MIGRATION_GUIDE.md` | 418 | Python module not found on tree: ipfs_datasets_py.logic.tools.modal_logic_extension | origin=import |
| `python_modules` | `docs/logic/MIGRATION_GUIDE.md` | 429 | Python module not found on tree: ipfs_datasets_py.logic.tools.logic_translation_core | origin=import |
| `python_modules` | `docs/logic/MIGRATION_GUIDE.md` | 440 | Python module not found on tree: ipfs_datasets_py.logic.tools.legal_text_to_deontic | origin=import |
| `python_modules` | `docs/logic/MIGRATION_GUIDE.md` | 454 | Python module not found on tree: ipfs_datasets_py.logic.tools.logic_utils | origin=import |
| `python_modules` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 555 | Python module not found on tree: ipfs_datasets_py.logic.TDFOL.api.main | origin=prose |
| `python_modules` | `docs/logic/archive/ENHANCED_REFACTORING_PLAN.md` | 290 | Python module not found on tree: ipfs_datasets_py.logic.integration.ipfs_proof_cache | origin=import |
| `python_modules` | `docs/logic/archive/PHASE4_COMPLETE.md` | 39 | Python module not found on tree: ipfs_datasets_py.rag.logic_integration | origin=import |
| `python_modules` | `docs/logic/archive/PHASE4_COMPLETE.md` | 108 | Python module not found on tree: ipfs_datasets_py.rag | origin=import |
| `python_modules` | `docs/logic/archive/REFACTORING_PLAN.md` | 479 | Python module not found on tree: ipfs_datasets_py.logic.integration.ipfs_proof_cache | origin=import |
| `python_modules` | `docs/logic/archive/REFACTORING_PLAN.md` | 1069 | Python module not found on tree: ipfs_datasets_py.logic.integration.api | origin=import |
| `python_modules` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 557 | Python module not found on tree: ipfs_datasets_py.logic.features | origin=prose |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 7 | Python module not found on tree: ipfs_datasets_py.ipfs_kit | origin=prose |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 8 | Python module not found on tree: ipfs_datasets_py.libp2p_kit | origin=prose |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 142 | Python module not found on tree: ipfs_datasets_py.ipfs_knn_index | origin=import |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 781 | Python module not found on tree: ipfs_datasets_py.duckdb_connector | origin=prose |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 2116 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia | origin=import |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 2327 | Python module not found on tree: ipfs_datasets_py.data_integration | origin=import |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 2386 | Python module not found on tree: ipfs_datasets_py.ipld_storage | origin=import |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 2388 | Python module not found on tree: ipfs_datasets_py.knowledge_graph | origin=import |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 3003 | Python module not found on tree: ipfs_datasets_py.arrow_ipld | origin=import |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 3493 | Python module not found on tree: ipfs_datasets_py.graphrag | origin=import |
| `python_modules` | `docs/migration_docs/CLAUDE.md` | 3533 | Python module not found on tree: ipfs_datasets_py.vector_store | origin=import |
| `python_modules` | `docs/migration_docs/CLAUDES_TOOLBOX_MIGRATION_ROADMAP.md` | 208 | Python module not found on tree: ipfs_datasets_py.mcp_server.tools.base_tool | origin=import |
| `python_modules` | `docs/migration_docs/CLAUDES_TOOLBOX_MIGRATION_ROADMAP.md` | 210 | Python module not found on tree: ipfs_datasets_py.audit_log | origin=import |
| `python_modules` | `docs/migration_docs/MCP_TOOLS_TESTING_GUIDE.md` | 99 | Python module not found on tree: ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.datasets | origin=prose |
| `python_modules` | `docs/migration_docs/MCP_TOOLS_TESTING_GUIDE.md` | 155 | Python module not found on tree: ipfs_datasets_py.web_archive_utils.WebArchiveProcessor | origin=prose |
| `python_modules` | `docs/migration_docs/MODULE_CREATION_SUMMARY.md` | 60 | Python module not found on tree: ipfs_datasets_py.vector_tools | origin=prose |
| `python_modules` | `docs/migration_docs/MODULE_CREATION_SUMMARY.md` | 61 | Python module not found on tree: ipfs_datasets_py.graphrag_processor | origin=prose |
| `python_modules` | `docs/optimizers/common/JSON_LOG_MIGRATION_GUIDE.md` | 35 | Python module not found on tree: ipfs_datasets_py.optimizer_log | origin=prose |
| `python_modules` | `docs/reports/ANYIO_MIGRATION_TEST_RESULTS.md` | 45 | Python module not found on tree: ipfs_datasets_py.data_transformation.multimedia.ytdlp_wrapper | origin=backtick |
| `python_modules` | `docs/reports/ANYIO_MIGRATION_TEST_RESULTS.md` | 46 | Python module not found on tree: ipfs_datasets_py.unified_web_scraper | origin=backtick |
| `python_syntax` | `docs/COMPLETE_MIGRATION_GUIDE.md` | 260 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/DEPRECATION_TIMELINE.md` | 157 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/DEPRECATION_TIMELINE.md` | 199 | Fenced Python block has syntax error | invalid character '╔' (U+2554) (line 1) |
| `python_syntax` | `docs/DEPRECATION_TIMELINE.md` | 339 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/MIGRATION_GUIDE_V2.md` | 439 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/MIGRATION_GUIDE_V2.md` | 751 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/MIGRATION_GUIDE_V2.md` | 766 | Fenced Python block has syntax error | unterminated string literal (detected at line 1) (line 1) |
| `python_syntax` | `docs/MIGRATION_GUIDE_V2.md` | 785 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/MIGRATION_GUIDE_V2.md` | 836 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/MIGRATION_TOOLS_USER_GUIDE.md` | 286 | Fenced Python block has syntax error | invalid syntax (line 10) |
| `python_syntax` | `docs/archive/completion_reports/GITHUB_OPTIMIZERS_REFACTORING_SUMMARY.md` | 82 | Fenced Python block has syntax error | expected '(' (line 7) |
| `python_syntax` | `docs/archive/completion_reports/GITHUB_OPTIMIZERS_REFACTORING_SUMMARY.md` | 137 | Fenced Python block has syntax error | invalid syntax (line 8) |
| `python_syntax` | `docs/archive/completion_reports/GITHUB_OPTIMIZERS_REFACTORING_SUMMARY.md` | 229 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 3) |
| `python_syntax` | `docs/archive/completion_reports/PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md` | 92 | Fenced Python block has syntax error | expected ':' (line 4) |
| `python_syntax` | `docs/archive/completion_reports/PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md` | 122 | Fenced Python block has syntax error | expected ':' (line 4) |
| `python_syntax` | `docs/archive/completion_reports/PHASE_11_COMMON_CRAWL_INTEGRATION_PLAN.md` | 137 | Fenced Python block has syntax error | expected ':' (line 9) |
| `python_syntax` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 78 | Fenced Python block has syntax error | invalid syntax (line 14) |
| `python_syntax` | `docs/archive/completion_reports/PHASE_2_3_IMPLEMENTATION_PLAN.md` | 130 | Fenced Python block has syntax error | expected an indented block after function definition on line 9 (line 10) |
| `python_syntax` | `docs/archive/completion_reports/PR_REVIEW_COMMENTS_RESOLUTION.md` | 44 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/completion_reports/PR_REVIEW_COMMENTS_RESOLUTION.md` | 163 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 2) |
| `python_syntax` | `docs/archive/completion_reports/UTILS_REFACTORING_COMPLETE.md` | 311 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/archive/completion_reports/phases/PHASE_2_SESSIONS_7_8_COMPLETE.md` | 363 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/completion_reports/phases/PHASE_9_10_PROGRESS_REPORT.md` | 32 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/archive/completion_reports/sessions/PATH_A_IMPLEMENTATION_COMPLETE.md` | 168 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 52 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 67 | Fenced Python block has syntax error | expected ':' (line 1) |
| `python_syntax` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_COMPLETE.md` | 159 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/completion_reports/sessions/PATH_B_SESSION_2_PROGRESS.md` | 288 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/archive/completion_reports/sessions/SESSION_PHASE_2_CRITICAL_IMPLEMENTATION_COMPLETE.md` | 61 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/completion_reports/sessions/SESSION_PHASE_2_CRITICAL_PREP.md` | 72 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 10) |
| `python_syntax` | `docs/archive/completion_reports/sessions/SESSION_PHASE_2_CRITICAL_PREP.md` | 86 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 10) |
| `python_syntax` | `docs/archive/completion_reports/sessions/SESSION_PHASE_2_CRITICAL_PREP.md` | 143 | Incomplete Python snippet failed parse (warning) | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/completion_reports/sessions/SESSION_READY_TO_IMPLEMENT_PHASE_2_3.md` | 83 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_PHASE_2_TASK_2_1_PARTS_1_2.md` | 122 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/completion_reports/sessions/SESSION_SUMMARY_PHASE_2_TASK_2_1_PARTS_1_2.md` | 137 | Fenced Python block has syntax error | illegal target for annotation (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/KNOWLEDGE_GRAPHS_EXTRACTION_API.md` | 62 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/KNOWLEDGE_GRAPHS_EXTRACTION_API.md` | 146 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/KNOWLEDGE_GRAPHS_EXTRACTION_API.md` | 206 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/archive/knowledge_graphs/KNOWLEDGE_GRAPHS_EXTRACTION_API.md` | 385 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/KNOWLEDGE_GRAPHS_EXTRACTION_API.md` | 536 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/KNOWLEDGE_GRAPHS_QUERY_API.md` | 48 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/KNOWLEDGE_GRAPHS_QUERY_API.md` | 271 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_3_SESSION_COMPLETE.md` | 89 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 1) |
| `python_syntax` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_3_TASK_3_4_COMPLETE.md` | 77 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/phase_reports/KNOWLEDGE_GRAPHS_PHASE_3_TASK_3_4_COMPLETE.md` | 116 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 3) |
| `python_syntax` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_MASTER_REFACTORING_PLAN_2026_02_16.md` | 558 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_MASTER_REFACTORING_PLAN_2026_02_16.md` | 603 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_NEO4J_REFACTORING_PLAN.md` | 151 | Fenced Python block has syntax error | expected ':' (line 4) |
| `python_syntax` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_NEO4J_REFACTORING_PLAN.md` | 244 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_NEO4J_REFACTORING_PLAN.md` | 300 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_NEO4J_REFACTORING_PLAN.md` | 405 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_NEO4J_REFACTORING_PLAN.md` | 445 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/archive/processors/phase_reports/PROCESSORS_PHASES_8_10_COMPLETE_SUMMARY.md` | 94 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_PLAN_2026.md` | 794 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1164 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 541 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/archive/processors/planning/PROCESSORS_COMPREHENSIVE_REFACTORING_PLAN.md` | 605 | Fenced Python block has syntax error | expected an indented block after function definition on line 4 (line 7) |
| `python_syntax` | `docs/archive/processors/planning/PROCESSORS_MASTER_PLAN.md` | 246 | Fenced Python block has syntax error | positional argument follows keyword argument (line 7) |
| `python_syntax` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 412 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 5) |
| `python_syntax` | `docs/archive/processors/planning/PROCESSORS_REFACTORING_PLAN.md` | 977 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK1_PROGRESS.md` | 53 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK1_PROGRESS.md` | 241 | Fenced Python block has syntax error | expected an indented block after class definition on line 2 (line 3) |
| `python_syntax` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK1_PROGRESS.md` | 431 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/archive/processors/weekly_reports/PROCESSORS_WEEK2_PHASE2_SESSION_SUMMARY.md` | 212 | Fenced Python block has syntax error | positional argument follows keyword argument (line 14) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v21.md` | 52 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 6) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v21.md` | 74 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v22.md` | 32 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 7) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v22.md` | 77 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 7) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v22.md` | 100 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 6) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v23.md` | 32 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 8) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v23.md` | 58 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v24.md` | 58 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v25.md` | 67 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 3) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v27.md` | 30 | Fenced Python block has syntax error | expected an indented block after function definition on line 8 (line 8) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v27.md` | 91 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v28.md` | 60 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 4) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v28.md` | 76 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 4) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v28.md` | 93 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v29.md` | 81 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v30.md` | 47 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 3) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v30.md` | 62 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v30.md` | 75 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archive/reorganization/MASTER_IMPROVEMENT_PLAN_2026_v31.md` | 68 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archive/reorganization/older_readme_sections_review.md` | 175 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/reorganization/older_sections_update_evidence.md` | 44 | Fenced Python block has syntax error | invalid syntax (line 4) |
| `python_syntax` | `docs/archive/reorganization/older_sections_update_evidence.md` | 53 | Fenced Python block has syntax error | invalid syntax (line 9) |
| `python_syntax` | `docs/archive/reorganization/readme_update_summary.md` | 114 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 3) |
| `python_syntax` | `docs/archive/root_status_reports/ARCHITECTURE_REVIEW_TDFOL_EXTERNAL_PROVERS.md` | 234 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/ARCHITECTURE_REVIEW_TDFOL_EXTERNAL_PROVERS.md` | 644 | Fenced Python block has syntax error | invalid syntax (line 40) |
| `python_syntax` | `docs/archive/root_status_reports/ARCHITECTURE_REVIEW_TDFOL_EXTERNAL_PROVERS.md` | 703 | Fenced Python block has syntax error | invalid syntax (line 32) |
| `python_syntax` | `docs/archive/root_status_reports/ARCHITECTURE_REVIEW_TDFOL_EXTERNAL_PROVERS.md` | 838 | Fenced Python block has syntax error | invalid syntax (line 54) |
| `python_syntax` | `docs/archive/root_status_reports/COMPREHENSIVE_LOGIC_MODULE_REVIEW.md` | 232 | Fenced Python block has syntax error | positional argument follows keyword argument (line 42) |
| `python_syntax` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_FINAL_SUMMARY.md` | 184 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 1) |
| `python_syntax` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_SESSION_SUMMARY.md` | 150 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_SESSION_SUMMARY.md` | 167 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/ENHANCEMENT_TODOS_SESSION_SUMMARY.md` | 176 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_IMPROVEMENT_INDEX.md` | 215 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_IMPROVEMENT_INDEX.md` | 223 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_IMPROVEMENT_INDEX.md` | 230 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_IMPROVEMENT_PLAN.md` | 1617 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_IMPROVEMENT_PLAN.md` | 1629 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_IMPROVEMENT_SUMMARY.md` | 305 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_IMPROVEMENT_VISUAL.md` | 214 | Fenced Python block has syntax error | invalid character '─' (U+2500) (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_IMPROVEMENT_VISUAL.md` | 245 | Fenced Python block has syntax error | invalid character '─' (U+2500) (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_MODULE_COMPLETION_SUMMARY.md` | 214 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_MODULE_COMPLETION_SUMMARY.md` | 232 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_MODULE_COMPLETION_SUMMARY.md` | 258 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/LOGIC_MODULE_COMPLETION_SUMMARY.md` | 306 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/NEUROSYMBOLIC_ARCHITECTURE_PLAN.md` | 726 | Fenced Python block has syntax error | invalid decimal literal (line 4) |
| `python_syntax` | `docs/archive/root_status_reports/OPTIMIZER_FRAMEWORK_IMPROVEMENTS.md` | 82 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 3) |
| `python_syntax` | `docs/archive/root_status_reports/OPTIMIZER_FRAMEWORK_IMPROVEMENTS.md` | 359 | Incomplete Python snippet failed parse (warning) | expected an indented block after function definition on line 33 (line 34) |
| `python_syntax` | `docs/archive/root_status_reports/OPTIMIZER_REFACTORING_COMPLETE.md` | 150 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 1) |
| `python_syntax` | `docs/archive/root_status_reports/OPTIMIZER_REFACTORING_COMPLETE.md` | 161 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 1) |
| `python_syntax` | `docs/archive/root_status_reports/PHASE_2_STATUS.md` | 56 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/PHASE_2_STATUS.md` | 81 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/archive/root_status_reports/PRIORITY_5_MIGRATION_PLAN.md` | 22 | Fenced Python block has syntax error | expected ':' (line 5) |
| `python_syntax` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 54 | Fenced Python block has syntax error | expected an indented block after function definition on line 6 (line 7) |
| `python_syntax` | `docs/archive/root_status_reports/PROCESSORS_REFACTORING_PLAN_2026_02_16.md` | 64 | Fenced Python block has syntax error | expected an indented block after function definition on line 6 (line 9) |
| `python_syntax` | `docs/archive/root_status_reports/SESSION_COMPLETE_SUMMARY.md` | 163 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/__main___stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_async_batch_processor_stubs.md` | 34 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_async_batch_processor_stubs.md` | 61 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_async_batch_processor_stubs.md` | 86 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_async_batch_processor_stubs.md` | 234 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_async_batch_processor_stubs.md` | 243 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_async_batch_processor_stubs.md` | 338 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_batch_processor_stubs.md` | 34 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_batch_processor_stubs.md` | 61 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_batch_processor_stubs.md` | 86 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_batch_processor_stubs.md` | 234 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_batch_processor_stubs.md` | 243 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_batch_processor_stubs.md` | 338 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/_batch_result_stubs.md` | 42 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/batch_processor/batch_processor_factory_stubs.md` | 28 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/configs_stubs.md` | 67 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/configs_stubs.md` | 76 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/configs_stubs.md` | 103 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/configs_stubs.md` | 112 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/configs_stubs.md` | 121 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/configs_stubs.md` | 164 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/configs_stubs.md` | 237 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/_pipeline_status_stubs.md` | 31 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/_processing_pipeline_stubs.md` | 57 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/_content_extractor_constants_stubs.md` | 294 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/_content_extractor_constants_stubs.md` | 564 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/_content_extractor_constants_stubs.md` | 585 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/_content_extractor_constants_stubs.md` | 606 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/content_extractor_factory_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/content_extractor_factory_stubs.md` | 18 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/_handler_capabilities_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/_handler_capabilities_stubs.md` | 19 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/_handler_capabilities_stubs.md` | 41 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/_handler_capabilities_stubs.md` | 51 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/_handler_capabilities_stubs.md` | 61 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/_handler_capabilities_stubs.md` | 71 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/_handler_capabilities_stubs.md` | 80 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/_image_handler_stubs.md` | 59 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/handler_factory_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/handlers/handler_factory_stubs.md` | 48 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/_get_dependency_info_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 18 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 62 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 83 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 92 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 101 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 110 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 119 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 183 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 192 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 214 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 223 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 232 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 241 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 325 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 334 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 344 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 353 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_extractor/processors/processor_factory_stubs.md` | 429 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_sanitizer/_constants_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/content_sanitizer/_constants_stubs.md` | 18 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/core_factory_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/output_formatter/_formatted_output_stubs.md` | 31 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/core/output_formatter/_output_formatter_stubs.md` | 125 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 46 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 67 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 76 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 85 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 120 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 130 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 210 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 282 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 292 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 302 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 325 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 335 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 345 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 355 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 378 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 388 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 398 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 408 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 417 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 427 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/dependencies_stubs.md` | 437 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/external_programs_stubs.md` | 34 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/external_programs_stubs.md` | 55 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/file_format_detector/_file_format_detector_stubs.md` | 98 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/interfaces/_cli_stubs.md` | 78 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/interfaces/_object_oriented_python_api_stubs.md` | 45 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/interfaces/options_stubs.md` | 240 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/interfaces/options_stubs.md` | 305 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/logger_stubs.md` | 21 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/logger_stubs.md` | 30 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/logger_stubs.md` | 65 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/main_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/monitors/_constants_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/monitors/_constants_stubs.md` | 18 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/monitors/security_monitor/_security_monitor_stubs.md` | 80 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/protocols_stubs.md` | 45 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/protocols_stubs.md` | 115 | Fenced Python block has syntax error | expected an indented block after class definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/protocols_stubs.md` | 210 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/protocols_stubs.md` | 255 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/protocols_stubs.md` | 276 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/protocols_stubs.md` | 297 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/protocols_stubs.md` | 330 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/supported_formats_stubs.md` | 438 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/supported_formats_stubs.md` | 448 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/supported_formats_stubs.md` | 458 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/supported_formats_stubs.md` | 468 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/supported_formats_stubs.md` | 478 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/supported_formats_stubs.md` | 488 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/supported_formats_stubs.md` | 584 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/supported_formats_stubs.md` | 606 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/teardown_stubs.md` | 22 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 21 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 30 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 39 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 48 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 57 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 66 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 75 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 84 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 93 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 102 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 123 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 156 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 165 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 186 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/_resource_pool_stubs.md` | 195 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/common/dependencies/tqdm_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/common/dependencies/tqdm_stubs.md` | 18 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/common/dependencies/tqdm_stubs.md` | 28 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/common/dependencies/tqdm_stubs.md` | 60 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/common/dependencies/tqdm_stubs.md` | 70 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/common/try_except_decorator_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/common/try_except_decorator_stubs.md` | 19 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/common/try_except_decorator_stubs.md` | 55 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/for_tests/calculate_structural_similarity_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/for_tests/calculate_structural_similarity_stubs.md` | 18 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/for_tests/calculate_structural_similarity_stubs.md` | 27 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/for_tests/calculate_structural_similarity_stubs.md` | 36 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/for_tests/get_words_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/for_tests/simple_bleu_approximation_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/handlers/_can_handle_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/hardware_stubs.md` | 55 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/hardware_stubs.md` | 64 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/hardware_stubs.md` | 73 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/hardware_stubs.md` | 82 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/llm/factory_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/main_/process_directory_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/main_/process_directory_stubs.md` | 18 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/plugin_discovery_stubs.md` | 21 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/plugin_discovery_stubs.md` | 30 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/plugin_discovery_stubs.md` | 39 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/plugin_discovery_stubs.md` | 48 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/software_stubs.md` | 55 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/software_stubs.md` | 64 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/software_stubs.md` | 73 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/omni_converter_mk2/utils/software_stubs.md` | 82 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/multimedia/ytdlp_wrapper_stubs.md` | 641 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/dag_pb_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/dag_pb_stubs.md` | 42 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/dag_pb_stubs.md` | 51 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/dag_pb_stubs.md` | 80 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/dag_pb_stubs.md` | 114 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/knowledge_graph_stubs.md` | 541 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/optimized_codec_stubs.md` | 27 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/optimized_codec_stubs.md` | 285 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/optimized_codec_stubs.md` | 369 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/storage_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/storage_stubs.md` | 117 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/storage/ipld/storage_stubs.md` | 127 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/archived_stubs/wikipedia_x/install/install_datasets_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/wikipedia_x/install/install_datasets_stubs.md` | 18 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/wikipedia_x/install/install_datasets_stubs.md` | 27 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/archived_stubs/wikipedia_x/install/install_datasets_stubs.md` | 36 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/guides/processors/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md` | 167 | Fenced Python block has syntax error | positional argument follows keyword argument (line 15) |
| `python_syntax` | `docs/guides/processors/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md` | 186 | Fenced Python block has syntax error | positional argument follows keyword argument (line 19) |
| `python_syntax` | `docs/guides/processors/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md` | 211 | Fenced Python block has syntax error | positional argument follows keyword argument (line 9) |
| `python_syntax` | `docs/guides/processors/PROCESSORS_PROTOCOL_MIGRATION_GUIDE.md` | 224 | Fenced Python block has syntax error | positional argument follows keyword argument (line 11) |
| `python_syntax` | `docs/knowledge_graphs/archive/refactoring_history/PHASE_2_COMPLETE_SESSION_5_SUMMARY.md` | 111 | Fenced Python block has syntax error | invalid syntax (line 10) |
| `python_syntax` | `docs/logic/CEC/ARCHIVE/NATIVE_INTEGRATION.md` | 97 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/CEC/ARCHIVE/NATIVE_INTEGRATION.md` | 116 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/CEC/ARCHIVE/NATIVE_INTEGRATION.md` | 135 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/CEC/ARCHIVE/NEXT_SESSION_GUIDE.md` | 200 | Fenced Python block has syntax error | Missing parentheses in call to 'print'. Did you mean print(...)? (line 2) |
| `python_syntax` | `docs/logic/CEC/ARCHIVE/PHASE_1_2_COMPLETION_SUMMARY.md` | 116 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/CEC/MIGRATION_GUIDE.md` | 81 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/CEC/MIGRATION_GUIDE.md` | 277 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/CEC/MIGRATION_GUIDE.md` | 290 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/CEC/MIGRATION_GUIDE.md` | 305 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/COMPREHENSIVE_REFACTORING_IMPROVEMENT_PLAN.md` | 1194 | Incomplete Python snippet failed parse (warning) | expected an indented block after function definition on line 7 (line 8) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/IMPLEMENTATION_QUICK_START_2026.md` | 184 | Fenced Python block has syntax error | invalid syntax (line 10) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/PHASE1_TASK11_COMPLETION.md` | 32 | Fenced Python block has syntax error | expected ':' (line 17) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/PHASE2_TASK22_COMPLETION.md` | 36 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/PHASE2_TASK22_COMPLETION.md` | 61 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/PHASE8_WEEK4_COMPLETION.md` | 172 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/PHASE9_WEEK8_COMPLETION.md` | 486 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/QUICK_REFERENCE_2026_02_18.md` | 167 | Fenced Python block has syntax error | expected an indented block after 'for' statement on line 3 (line 4) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/QUICK_REFERENCE_2026_02_18.md` | 553 | Fenced Python block has syntax error | expected an indented block after 'for' statement on line 4 (line 8) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/SECURITY_VALIDATOR_SUMMARY.md` | 182 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/SECURITY_VALIDATOR_SUMMARY.md` | 188 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/SECURITY_VALIDATOR_SUMMARY.md` | 198 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TASK_11.3_COMPLETE.md` | 177 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TASK_11.3_COMPLETE.md` | 203 | Fenced Python block has syntax error | expected ':' (line 3) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TASK_12.1_COMPLETE.md` | 39 | Fenced Python block has syntax error | invalid syntax (line 5) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TRACK1_COMPLETION_REPORT.md` | 64 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TRACK1_COMPLETION_REPORT.md` | 76 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TRACK1_COMPLETION_REPORT.md` | 356 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TRACK1_COMPLETION_REPORT.md` | 366 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TRACK1_COMPLETION_REPORT.md` | 373 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TRACK1_COMPLETION_REPORT.md` | 382 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/TRACK1_COMPLETION_REPORT.md` | 388 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 140 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 172 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 209 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 230 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 245 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 265 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 297 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 368 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 399 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 421 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 435 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 461 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 567 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 589 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 609 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 630 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 692 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 713 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 734 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 792 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 941 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 955 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 963 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 971 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 1007 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 1019 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 1031 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 1043 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 1081 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 1093 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 1105 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 1144 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/TDFOL/ARCHIVE/UNIFIED_REFACTORING_ROADMAP_2026.md` | 1156 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 2) |
| `python_syntax` | `docs/logic/archive/COMPLETE_IMPLEMENTATION_REPORT.md` | 102 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 6) |
| `python_syntax` | `docs/logic/archive/COMPLETE_IMPLEMENTATION_REPORT.md` | 112 | Fenced Python block has syntax error | expected an indented block after class definition on line 2 (line 8) |
| `python_syntax` | `docs/logic/archive/ENHANCED_REFACTORING_PLAN.md` | 28 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/archive/PHASE4_API_REFERENCE.md` | 714 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 6) |
| `python_syntax` | `docs/logic/archive/PHASE4_COMPLETE.md` | 266 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/logic/archive/PHASE4_COMPLETE.md` | 275 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/logic/archive/PHASE4_COMPLETE.md` | 288 | Fenced Python block has syntax error | expected ':' (line 2) |
| `python_syntax` | `docs/logic/archive/PHASE4_TUTORIAL.md` | 603 | Fenced Python block has syntax error | invalid syntax (line 3) |
| `python_syntax` | `docs/logic/archive/PHASE5_COMPLETE.md` | 94 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 2) |
| `python_syntax` | `docs/logic/archive/PHASE5_COMPLETE.md` | 170 | Fenced Python block has syntax error | expected ':' (line 7) |
| `python_syntax` | `docs/logic/archive/PHASE_REPORTS/PHASE6_COMPLETION_REPORT.md` | 44 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/logic/archive/PHASE_REPORTS/PHASE6_COMPLETION_REPORT.md` | 195 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/logic/archive/PHASE_REPORTS/PHASE7_5_FINAL_VALIDATION.md` | 107 | Fenced Python block has syntax error | invalid character '├' (U+251C) (line 3) |
| `python_syntax` | `docs/logic/archive/REFACTORING_PLAN.md` | 317 | Fenced Python block has syntax error | cannot assign to ellipsis (line 18) |
| `python_syntax` | `docs/logic/archive/SESSIONS/SESSION_2026-02-13.md` | 130 | Fenced Python block has syntax error | invalid character '✓' (U+2713) (line 1) |
| `python_syntax` | `docs/logic/archive/modal_logic_extension_stubs.md` | 21 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/modal_logic_extension_stubs.md` | 68 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/modal_logic_extension_stubs.md` | 77 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/modal_logic_extension_stubs.md` | 331 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/status_reports/FINAL_STATUS_REPORT.md` | 120 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |
| `python_syntax` | `docs/logic/archive/status_reports/REFACTORING_COMPLETE.md` | 19 | Fenced Python block has syntax error | invalid character '✅' (U+2705) (line 3) |
| `python_syntax` | `docs/logic/archive/symbolic_fol_bridge_stubs.md` | 9 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_fol_bridge_stubs.md` | 44 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_fol_bridge_stubs.md` | 69 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_fol_bridge_stubs.md` | 95 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_fol_bridge_stubs.md` | 272 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 38 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 47 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 56 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 65 | Fenced Python block has syntax error | unterminated string literal (detected at line 1) (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 84 | Fenced Python block has syntax error | unterminated string literal (detected at line 1) (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 110 | Fenced Python block has syntax error | unterminated string literal (detected at line 1) (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 127 | Fenced Python block has syntax error | unterminated string literal (detected at line 1) (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 252 | Fenced Python block has syntax error | unterminated string literal (detected at line 1) (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 265 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 275 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 285 | Fenced Python block has syntax error | unterminated string literal (detected at line 1) (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 298 | Fenced Python block has syntax error | unterminated string literal (detected at line 1) (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 316 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 341 | Fenced Python block has syntax error | expected an indented block after class definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 369 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 378 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 453 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 463 | Fenced Python block has syntax error | expected an indented block after function definition on line 2 (line 2) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 511 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 583 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/archive/symbolic_logic_primitives_stubs.md` | 592 | Fenced Python block has syntax error | expected an indented block after function definition on line 1 (line 1) |
| `python_syntax` | `docs/logic/docs/archive/phases/PHASE_7_SESSION_SUMMARY.md` | 92 | Incomplete Python snippet failed parse (warning) | expected an indented block after 'for' statement on line 11 (line 12) |
| `python_syntax` | `docs/logic/docs/archive/phases_2026/PHASE_7_SESSION_SUMMARY.md` | 92 | Incomplete Python snippet failed parse (warning) | expected an indented block after 'for' statement on line 11 (line 12) |
| `python_syntax` | `docs/logic/docs/archive/planning/ARCHIVED_REFACTORING_IMPROVEMENT_PLAN.md` | 457 | Fenced Python block has syntax error | invalid syntax. Perhaps you forgot a comma? (line 21) |
| `python_syntax` | `docs/logic/docs/archive/planning/ARCHIVED_VERIFIED_STATUS_REPORT_2026.md` | 65 | Fenced Python block has syntax error | invalid syntax (line 2) |
| `python_syntax` | `docs/logic/zkp/ARCHIVE/COMPREHENSIVE_REFACTORING_PLAN.md` | 332 | Fenced Python block has syntax error | invalid syntax (line 1) |
| `python_syntax` | `docs/reports/ANYIO_MIGRATION_REPORT.md` | 39 | Fenced Python block has syntax error | invalid character '→' (U+2192) (line 2) |

### info (273)

| Check | Path | Line | Message | Detail |
| --- | --- | ---: | --- | --- |
| `markdown_paths` | `docs` |  | Scanned 1570 Markdown file(s) under scan root |  |
| `links` | `docs/DEPRECATION_TIMELINE.md` | 337 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/GRAPH_STORAGE_INTEGRATION.md` | 227 | External link skipped (no network fetch) | https://github.com/your-repo/issues |
| `links` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 484 | External link skipped (no network fetch) | https://ipld.io/ |
| `links` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 485 | External link skipped (no network fetch) | https://github.com/facebookresearch/faiss/wiki |
| `links` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 486 | External link skipped (no network fetch) | https://qdrant.tech/documentation/ |
| `links` | `docs/IPLD_VECTOR_STORE_IMPROVEMENT_PLAN.md` | 487 | External link skipped (no network fetch) | https://ipld.io/specs/transport/car/ |
| `links` | `docs/IPLD_VECTOR_STORE_PLANNING_SESSION_SUMMARY.md` | 243 | External link skipped (no network fetch) | https://ipld.io/ |
| `links` | `docs/IPLD_VECTOR_STORE_PLANNING_SESSION_SUMMARY.md` | 244 | External link skipped (no network fetch) | https://ipld.io/specs/transport/car/ |
| `links` | `docs/IPLD_VECTOR_STORE_PLANNING_SESSION_SUMMARY.md` | 245 | External link skipped (no network fetch) | https://github.com/facebookresearch/faiss/wiki |
| `links` | `docs/IPLD_VECTOR_STORE_PLANNING_SESSION_SUMMARY.md` | 246 | External link skipped (no network fetch) | https://qdrant.tech/documentation/ |
| `links` | `docs/MULTIMEDIA_MIGRATION_GUIDE.md` | 244 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/PHASE3C6_ONCHAIN_INTEGRATION_PLAN.md` | 173 | External link skipped (no network fetch) | https://github.com/iden3/snarkjs |
| `links` | `docs/PHASE3C6_ONCHAIN_INTEGRATION_PLAN.md` | 174 | External link skipped (no network fetch) | https://eips.ethereum.org/EIPS/eip-197 |
| `links` | `docs/PHASE3C6_ONCHAIN_INTEGRATION_PLAN.md` | 175 | External link skipped (no network fetch) | https://eprint.iacr.org/2016/260 |
| `links` | `docs/PHASE3C6_ONCHAIN_INTEGRATION_PLAN.md` | 178 | External link skipped (no network fetch) | https://github.com/OpenZeppelin/openzeppelin-contracts |
| `links` | `docs/PHASE3C6_ONCHAIN_INTEGRATION_PLAN.md` | 179 | External link skipped (no network fetch) | https://docs.soliditylang.org/en/latest/gas-optimization.html |
| `links` | `docs/PHASE3C6_ONCHAIN_INTEGRATION_PLAN.md` | 182 | External link skipped (no network fetch) | https://www.alchemy.com/faucets/ethereum-sepolia |
| `links` | `docs/PHASE3C6_ONCHAIN_INTEGRATION_PLAN.md` | 183 | External link skipped (no network fetch) | https://goerlifaucet.com/ |
| `links` | `docs/TESTING_STRATEGY.md` | 210 | External link skipped (no network fetch) | https://docs.pytest.org/ |
| `links` | `docs/TESTING_STRATEGY.md` | 211 | External link skipped (no network fetch) | https://pytest-asyncio.readthedocs.io/ |
| `links` | `docs/TESTING_STRATEGY.md` | 212 | External link skipped (no network fetch) | https://docs.python.org/3/library/unittest.mock.html |
| `links` | `docs/analysis/complete_integration_summary.md` | 438 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py |
| `links` | `docs/architecture/github_actions_infrastructure.md` | 333 | External link skipped (no network fetch) | https://docs.github.com/en/rest/overview/resources-in-the-rest-api#rate-limiting |
| `links` | `docs/architecture/github_actions_infrastructure.md` | 334 | External link skipped (no network fetch) | https://codeql.github.com/docs/ |
| `links` | `docs/architecture/github_actions_infrastructure.md` | 335 | External link skipped (no network fetch) | https://docs.libp2p.io/ |
| `links` | `docs/architecture/github_actions_infrastructure.md` | 336 | External link skipped (no network fetch) | https://multiformats.io/ |
| `links` | `docs/archive/completion_reports/IMPLEMENTATION_SUMMARY_REFACTORING.md` | 20 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/pull/941 |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 121 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/discussions |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 122 | External link skipped (no network fetch) | mailto:starworks5@gmail.com |
| `links` | `docs/archive/deprecated/master_documentation_index.md` | 123 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 251 | External link skipped (no network fetch) | https://neo4j.com/docs/cypher-manual/ |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 252 | External link skipped (no network fetch) | https://neo4j.com/docs/python-manual/ |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 253 | External link skipped (no network fetch) | https://docs.ipfs.tech/ |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 254 | External link skipped (no network fetch) | https://ipld.io/specs/ |
| `links` | `docs/archive/knowledge_graphs/planning/KNOWLEDGE_GRAPHS_REFACTORING_SUMMARY.md` | 255 | External link skipped (no network fetch) | https://www.w3.org/TR/json-ld11/ |
| `links` | `docs/archive/root_status_reports/CHANGELOG_LOGIC.md` | 5 | External link skipped (no network fetch) | https://keepachangelog.com/en/1.0.0/ |
| `links` | `docs/archive/root_status_reports/CHANGELOG_LOGIC.md` | 6 | External link skipped (no network fetch) | https://semver.org/spec/v2.0.0.html |
| `links` | `docs/archive/root_status_reports/PHASE_2_STATUS.md` | 220 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/pull/924 |
| `links` | `docs/archive/root_status_reports/PHASE_2_STATUS.md` | 221 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/pull/926 |
| `links` | `docs/archive/root_status_reports/TEST_COVERAGE_PLAN.md` | 275 | External link skipped (no network fetch) | https://docs.pytest.org/ |
| `links` | `docs/archive/root_status_reports/TEST_COVERAGE_PLAN.md` | 276 | External link skipped (no network fetch) | https://coverage.readthedocs.io/ |
| `links` | `docs/examples/discord_usage_examples.md` | 51 | External link skipped (no network fetch) | https://github.com/Tyrrrz/DiscordChatExporter/blob/master/.docs/Token-and-IDs.md |
| `links` | `docs/examples/discord_usage_examples.md` | 184 | External link skipped (no network fetch) | https://github.com/Tyrrrz/DiscordChatExporter |
| `links` | `docs/examples/discord_usage_examples.md` | 185 | External link skipped (no network fetch) | https://discord.com/developers/docs/intro |
| `links` | `docs/examples/discord_usage_examples.md` | 186 | External link skipped (no network fetch) | https://github.com/Tyrrrz/DiscordChatExporter/blob/master/.docs/Message-filters.md |
| `links` | `docs/examples/discord_usage_examples.md` | 187 | External link skipped (no network fetch) | https://github.com/Tyrrrz/DiscordChatExporter/blob/master/.docs/Token-and-IDs.md |
| `links` | `docs/examples/discord_usage_examples.md` | 193 | External link skipped (no network fetch) | https://github.com/Tyrrrz/DiscordChatExporter |
| `links` | `docs/examples/discord_usage_examples.md` | 194 | External link skipped (no network fetch) | https://discord.com/developers/docs |
| `links` | `docs/examples/email_usage_examples.md` | 40 | External link skipped (no network fetch) | https://support.google.com/accounts/answer/185833 |
| `links` | `docs/guides/CICD_RUNNER_SETUP_GUIDE.md` | 212 | External link skipped (no network fetch) | https://docs.github.com/en/actions/hosting-your-own-runners |
| `links` | `docs/guides/CICD_RUNNER_SETUP_GUIDE.md` | 213 | External link skipped (no network fetch) | https://docs.github.com/en/actions |
| `links` | `docs/guides/CICD_RUNNER_SETUP_GUIDE.md` | 214 | External link skipped (no network fetch) | https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions |
| `links` | `docs/guides/COPILOT_AUTO_FIX_IMPLEMENTATION.md` | 185 | External link skipped (no network fetch) | https://docs.github.com/en/copilot |
| `links` | `docs/guides/COPILOT_AUTO_FIX_IMPLEMENTATION.md` | 186 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/COPILOT_AUTO_FIX_IMPLEMENTATION.md` | 187 | External link skipped (no network fetch) | https://cli.github.com/manual/ |
| `links` | `docs/guides/COPILOT_INVOCATION_GUIDE.md` | 120 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/make-changes-to-an-existing-pr |
| `links` | `docs/guides/COPILOT_INVOCATION_GUIDE.md` | 124 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/COPILOT_TASK.md` | 46 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/actions/runs/18993344802 |
| `links` | `docs/guides/DISTRIBUTED_CACHE.md` | 168 | External link skipped (no network fetch) | https://docs.libp2p.io/ |
| `links` | `docs/guides/DISTRIBUTED_CACHE.md` | 169 | External link skipped (no network fetch) | https://multiformats.io/ |
| `links` | `docs/guides/DISTRIBUTED_CACHE.md` | 170 | External link skipped (no network fetch) | https://docs.github.com/en/rest/overview/rate-limits-for-the-rest-api |
| `links` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 155 | External link skipped (no network fetch) | https://docs.github.com/en/actions |
| `links` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 156 | External link skipped (no network fetch) | https://docs.docker.com/build/building/multi-platform/ |
| `links` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 157 | External link skipped (no network fetch) | https://docs.github.com/en/actions/hosting-your-own-runners |
| `links` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 158 | External link skipped (no network fetch) | https://docs.docker.com/compose/ |
| `links` | `docs/guides/DOCKER_GITHUB_ACTIONS_SETUP.md` | 180 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/actions |
| `links` | `docs/guides/ENHANCED_AUTO_HEALING_GUIDE.md` | 325 | External link skipped (no network fetch) | https://docs.github.com/en/actions |
| `links` | `docs/guides/ENHANCED_AUTO_HEALING_GUIDE.md` | 326 | External link skipped (no network fetch) | https://docs.github.com/en/copilot |
| `links` | `docs/guides/FAQ.md` | 122 | External link skipped (no network fetch) | https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md |
| `links` | `docs/guides/FAQ.md` | 299 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/discussions |
| `links` | `docs/guides/FAQ.md` | 300 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/guides/FAQ.md` | 301 | External link skipped (no network fetch) | mailto:starworks5@gmail.com |
| `links` | `docs/guides/FAQ.md` | 333 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/discussions |
| `links` | `docs/guides/FAQ.md` | 333 | External link skipped (no network fetch) | mailto:starworks5@gmail.com |
| `links` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 17 | External link skipped (no network fetch) | https://github.blog/news-insights/company-news/welcome-home-agents/ |
| `links` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 18 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 19 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/code-review |
| `links` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 259 | External link skipped (no network fetch) | https://github.blog/news-insights/company-news/welcome-home-agents/ |
| `links` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 260 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/GITHUB_COPILOT_INTEGRATION.md` | 261 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/code-review |
| `links` | `docs/guides/HOW_TO_USE_COPILOT_AUTO_FIX.md` | 185 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/guides/PR_AUTOMATION_SYSTEM.md` | 118 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/PR_AUTOMATION_SYSTEM.md` | 239 | External link skipped (no network fetch) | https://github.blog/news-insights/company-news/welcome-home-agents/ |
| `links` | `docs/guides/PR_AUTOMATION_SYSTEM.md` | 240 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/PR_AUTOMATION_SYSTEM.md` | 241 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/code-review |
| `links` | `docs/guides/WORKFLOW_FIXES_COMPLETE_SUMMARY.md` | 243 | External link skipped (no network fetch) | https://cli.github.com/manual/gh_auth_login |
| `links` | `docs/guides/WORKFLOW_FIXES_COMPLETE_SUMMARY.md` | 244 | External link skipped (no network fetch) | https://github.com/features/copilot/cli |
| `links` | `docs/guides/WORKFLOW_FIXES_COMPLETE_SUMMARY.md` | 245 | External link skipped (no network fetch) | https://docs.github.com/en/actions/hosting-your-own-runners |
| `links` | `docs/guides/WORKFLOW_FIXES_COMPLETE_SUMMARY.md` | 246 | External link skipped (no network fetch) | https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token |
| `links` | `docs/guides/WORKFLOW_FIXES_COMPLETE_SUMMARY.md` | 247 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent |
| `links` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 72 | External link skipped (no network fetch) | https://cli.github.com/manual/gh |
| `links` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 73 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/github-copilot-in-the-cli |
| `links` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 74 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli |
| `links` | `docs/guides/WORKFLOW_FIXES_SUMMARY.md` | 75 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/deployment/docker_permission_fix.md` | 90 | External link skipped (no network fetch) | https://docs.docker.com/engine/install/linux-postinstall/ |
| `links` | `docs/guides/deployment/docker_permission_fix.md` | 91 | External link skipped (no network fetch) | https://docs.github.com/en/actions/hosting-your-own-runners/about-self-hosted-runners#self-hosted-runner-security |
| `links` | `docs/guides/deployment/docker_permission_fix.md` | 92 | External link skipped (no network fetch) | https://docs.docker.com/engine/security/rootless/ |
| `links` | `docs/guides/deployment/docker_permission_infrastructure_solutions.md` | 89 | External link skipped (no network fetch) | https://docs.docker.com/engine/install/linux-postinstall/ |
| `links` | `docs/guides/deployment/docker_permission_infrastructure_solutions.md` | 90 | External link skipped (no network fetch) | https://docs.github.com/en/actions/hosting-your-own-runners |
| `links` | `docs/guides/deployment/docker_permission_infrastructure_solutions.md` | 91 | External link skipped (no network fetch) | https://www.freedesktop.org/software/systemd/man/systemd.service.html |
| `links` | `docs/guides/deployment/docker_permission_infrastructure_solutions.md` | 92 | External link skipped (no network fetch) | https://docs.docker.com/engine/security/ |
| `links` | `docs/guides/deployment/runner_authentication_setup.md` | 172 | External link skipped (no network fetch) | https://cli.github.com/manual/gh_auth_login |
| `links` | `docs/guides/deployment/runner_authentication_setup.md` | 173 | External link skipped (no network fetch) | https://github.com/features/copilot/cli |
| `links` | `docs/guides/deployment/runner_authentication_setup.md` | 174 | External link skipped (no network fetch) | https://docs.github.com/en/actions/hosting-your-own-runners |
| `links` | `docs/guides/deployment/runner_authentication_setup.md` | 175 | External link skipped (no network fetch) | https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token |
| `links` | `docs/guides/deployment/runner_authentication_setup.md` | 176 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent |
| `links` | `docs/guides/deployment/runner_setup.md` | 137 | External link skipped (no network fetch) | https://docs.github.com/en/actions/hosting-your-own-runners |
| `links` | `docs/guides/deployment/runner_setup.md` | 138 | External link skipped (no network fetch) | https://docs.docker.com/engine/install/ |
| `links` | `docs/guides/deployment/runner_setup.md` | 139 | External link skipped (no network fetch) | https://docs.github.com/en/actions/learn-github-actions/best-practices-for-github-actions |
| `links` | `docs/guides/deployment/runner_setup.md` | 145 | External link skipped (no network fetch) | https://docs.github.com/en/actions |
| `links` | `docs/guides/infrastructure/automated_pr_review_guide.md` | 20 | External link skipped (no network fetch) | https://github.blog/news-insights/company-news/welcome-home-agents/ |
| `links` | `docs/guides/infrastructure/automated_pr_review_guide.md` | 21 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/infrastructure/automated_pr_review_guide.md` | 22 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/code-review |
| `links` | `docs/guides/infrastructure/copilot_auto_fix_all_prs.md` | 261 | External link skipped (no network fetch) | https://docs.github.com/en/copilot |
| `links` | `docs/guides/infrastructure/copilot_auto_fix_all_prs.md` | 262 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/infrastructure/copilot_auto_fix_all_prs.md` | 263 | External link skipped (no network fetch) | https://cli.github.com/manual/ |
| `links` | `docs/guides/infrastructure/copilot_auto_fix_all_prs.md` | 264 | External link skipped (no network fetch) | https://github.com/github/gh-copilot |
| `links` | `docs/guides/infrastructure/copilot_invocation_update.md` | 82 | External link skipped (no network fetch) | https://cli.github.com/manual/gh_agent-task |
| `links` | `docs/guides/infrastructure/copilot_invocation_update.md` | 83 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent |
| `links` | `docs/guides/infrastructure/copilot_invocation_update.md` | 84 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli |
| `links` | `docs/guides/infrastructure/copilot_invocation_update.md` | 85 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/about-copilot-cli |
| `links` | `docs/guides/infrastructure/copilot_invocation_update.md` | 86 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management |
| `links` | `docs/guides/infrastructure/copilot_queue_integration.md` | 210 | External link skipped (no network fetch) | https://docs.github.com/en/copilot/github-copilot-in-the-cli |
| `links` | `docs/guides/infrastructure/github_cli_rate_limiting.md` | 190 | External link skipped (no network fetch) | https://docs.github.com/en/rest/overview/resources-in-the-rest-api#rate-limiting |
| `links` | `docs/guides/infrastructure/github_cli_rate_limiting.md` | 191 | External link skipped (no network fetch) | https://cli.github.com/manual/ |
| `links` | `docs/guides/infrastructure/github_cli_rate_limiting.md` | 192 | External link skipped (no network fetch) | https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#jobsjob_idstrategymax-parallel |
| `links` | `docs/guides/infrastructure/runners/SELF_HOSTED_RUNNER_SETUP.md` | 143 | External link skipped (no network fetch) | https://docs.github.com/en/actions/hosting-your-own-runners |
| `links` | `docs/guides/installation/CAPABILITY_INSTALLATION.md` | 172 | External link skipped (no network fetch) | https://rustup.rs |
| `links` | `docs/guides/javascript_error_auto_healing.md` | 197 | External link skipped (no network fetch) | https://cli.github.com/manual/ |
| `links` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md` | 183 | External link skipped (no network fetch) | https://neo4j.com/docs/cypher-manual/ |
| `links` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md` | 184 | External link skipped (no network fetch) | https://docs.ipfs.tech/ |
| `links` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md` | 185 | External link skipped (no network fetch) | https://www.w3.org/TR/json-ld11/ |
| `links` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md` | 188 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_README.md` | 301 | External link skipped (no network fetch) | https://neo4j.com/docs/ |
| `links` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_README.md` | 302 | External link skipped (no network fetch) | https://neo4j.com/docs/cypher-manual/ |
| `links` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_README.md` | 303 | External link skipped (no network fetch) | https://docs.ipfs.tech/ |
| `links` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_README.md` | 304 | External link skipped (no network fetch) | https://ipld.io/specs/ |
| `links` | `docs/guides/knowledge_graphs/KNOWLEDGE_GRAPHS_README.md` | 305 | External link skipped (no network fetch) | https://www.w3.org/TR/json-ld11/ |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 9 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1164 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 10 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1165 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 11 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1166 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 12 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1167 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 13 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1168 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 14 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1169 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 15 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1170 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 16 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1171 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 17 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1172 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 18 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1173 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 19 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1174 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 20 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1175 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 52 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1179 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 53 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1180 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 54 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1181 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 55 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1182 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 56 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1183 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 57 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1184 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 58 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1185 |
| `links` | `docs/guides/legal_data/guides_HYBRID_LEGAL_REASONING_TODO.md` | 59 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues/1186 |
| `links` | `docs/guides/processors/PROCESSORS_CHANGELOG.md` | 5 | External link skipped (no network fetch) | https://keepachangelog.com/en/1.0.0/ |
| `links` | `docs/guides/processors/PROCESSORS_CHANGELOG.md` | 6 | External link skipped (no network fetch) | https://semver.org/spec/v2.0.0.html |
| `links` | `docs/guides/security/auto_healing_security.md` | 266 | External link skipped (no network fetch) | https://docs.github.com/en/actions/security-guides |
| `links` | `docs/guides/security/auto_healing_security.md` | 267 | External link skipped (no network fetch) | https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions |
| `links` | `docs/guides/security/auto_healing_security.md` | 268 | External link skipped (no network fetch) | https://docs.github.com/en/actions/security-guides/automatic-token-authentication |
| `links` | `docs/guides/security/auto_healing_security.md` | 271 | External link skipped (no network fetch) | https://owasp.org/www-project-devsecops-guideline/ |
| `links` | `docs/guides/security/auto_healing_security.md` | 272 | External link skipped (no network fetch) | https://www.cisecurity.org/ |
| `links` | `docs/guides/tools/cli_error_auto_healing.md` | 177 | External link skipped (no network fetch) | https://cli.github.com/manual/ |
| `links` | `docs/guides/tools/discord_alerts_guide.md` | 52 | External link skipped (no network fetch) | https://discord.com/developers/applications |
| `links` | `docs/guides/tools/patent_scraper_guide.md` | 261 | External link skipped (no network fetch) | https://patentsview.org/apis/purpose |
| `links` | `docs/guides/tools/patent_scraper_guide.md` | 262 | External link skipped (no network fetch) | https://www.cooperativepatentclassification.org/ |
| `links` | `docs/guides/tools/patent_scraper_guide.md` | 263 | External link skipped (no network fetch) | https://www.wipo.int/classifications/ipc/en/ |
| `links` | `docs/guides/tools/patent_scraper_guide.md` | 268 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/implementation/accelerate/ACCELERATE_INTEGRATION_SUMMARY.md` | 208 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_accelerate_py |
| `links` | `docs/implementation/accelerate/ACCELERATE_QUICKSTART.md` | 85 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_accelerate_py |
| `links` | `docs/implementation/plans/p2p_cache_system.md` | 150 | External link skipped (no network fetch) | https://docs.github.com/en/rest/overview/resources-in-the-rest-api#rate-limiting |
| `links` | `docs/implementation/plans/p2p_cache_system.md` | 151 | External link skipped (no network fetch) | https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows |
| `links` | `docs/implementation/plans/p2p_cache_system.md` | 152 | External link skipped (no network fetch) | https://docs.libp2p.io/ |
| `links` | `docs/implementation/plans/p2p_cache_system.md` | 153 | External link skipped (no network fetch) | https://cli.github.com/manual/ |
| `links` | `docs/implementation/plans/p2p_workflow_scheduler.md` | 162 | External link skipped (no network fetch) | https://arxiv.org/abs/1905.13064 |
| `links` | `docs/implementation/plans/p2p_workflow_scheduler.md` | 163 | External link skipped (no network fetch) | https://en.wikipedia.org/wiki/Fibonacci_heap |
| `links` | `docs/implementation/plans/p2p_workflow_scheduler.md` | 164 | External link skipped (no network fetch) | https://en.wikipedia.org/wiki/Hamming_distance |
| `links` | `docs/implementation/plans/p2p_workflow_scheduler.md` | 165 | External link skipped (no network fetch) | https://github.com/libp2p/specs |
| `links` | `docs/implementation/plans/p2p_workflow_scheduler.md` | 166 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_accelerate_py/pull/61 |
| `links` | `docs/implementation/plans/symbolicai_fol_integration_plan.md` | 9 | External link skipped (no network fetch) | https://github.com/ExtensityAI/symbolicai |
| `links` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 5 | External link skipped (no network fetch) | https://keepachangelog.com/en/1.0.0/ |
| `links` | `docs/knowledge_graphs/CHANGELOG_KNOWLEDGE_GRAPHS.md` | 6 | External link skipped (no network fetch) | https://semver.org/spec/v2.0.0.html |
| `links` | `docs/knowledge_graphs/INDEX.md` | 342 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py |
| `links` | `docs/knowledge_graphs/QUICKSTART.md` | 89 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/knowledge_graphs/ROADMAP.md` | 380 | External link skipped (no network fetch) | https://semver.org/ |
| `links` | `docs/knowledge_graphs/ROADMAP.md` | 471 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py |
| `links` | `docs/logic/API_VERSIONING.md` | 23 | External link skipped (no network fetch) | https://semver.org/ |
| `links` | `docs/logic/ARCHITECTURE.md` | 233 | External link skipped (no network fetch) | https://en.wikipedia.org/wiki/First-order_logic |
| `links` | `docs/logic/ARCHITECTURE.md` | 234 | External link skipped (no network fetch) | https://plato.stanford.edu/entries/logic-deontic/ |
| `links` | `docs/logic/ARCHITECTURE.md` | 235 | External link skipped (no network fetch) | https://spacy.io/ |
| `links` | `docs/logic/ARCHITECTURE.md` | 236 | External link skipped (no network fetch) | https://xgboost.readthedocs.io/ |
| `links` | `docs/logic/CEC/API_REFERENCE.md` | 373 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/logic/CEC/API_REFERENCE.md` | 374 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/discussions |
| `links` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 442 | External link skipped (no network fetch) | https://pep8.org/ |
| `links` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 443 | External link skipped (no network fetch) | https://www.python.org/dev/peps/pep-0484/ |
| `links` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 444 | External link skipped (no network fetch) | https://www.python.org/dev/peps/pep-0257/ |
| `links` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 445 | External link skipped (no network fetch) | https://pytest.org/ |
| `links` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 449 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 450 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/discussions |
| `links` | `docs/logic/CEC/DEVELOPER_GUIDE.md` | 451 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/pulls |
| `links` | `docs/logic/CEC/QUICKSTART.md` | 153 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/logic/CEC/QUICKSTART.md` | 155 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/discussions |
| `links` | `docs/logic/CEC/QUICKSTART.md` | 234 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/logic/CEC/QUICKSTART.md` | 235 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/discussions |
| `links` | `docs/logic/CEC/STATUS.md` | 330 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/logic/CEC/STATUS.md` | 331 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/discussions |
| `links` | `docs/logic/CONTRIBUTING.md` | 237 | External link skipped (no network fetch) | https://black.readthedocs.io/ |
| `links` | `docs/logic/CONTRIBUTING.md` | 238 | External link skipped (no network fetch) | https://flake8.pycqa.org/ |
| `links` | `docs/logic/CONTRIBUTING.md` | 239 | External link skipped (no network fetch) | http://mypy-lang.org/ |
| `links` | `docs/logic/CONTRIBUTING.md` | 240 | External link skipped (no network fetch) | https://pytest.org/ |
| `links` | `docs/logic/CONTRIBUTING.md` | 243 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/logic/CONTRIBUTING.md` | 244 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/discussions |
| `links` | `docs/logic/CONTRIBUTING.md` | 245 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/pulls |
| `links` | `docs/logic/ERROR_REFERENCE.md` | 442 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/logic/QUICKSTART.md` | 160 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/logic/SECURITY_GUIDE.md` | 254 | External link skipped (no network fetch) | https://owasp.org/www-project-top-ten/ |
| `links` | `docs/logic/SECURITY_GUIDE.md` | 255 | External link skipped (no network fetch) | https://cwe.mitre.org/top25/ |
| `links` | `docs/logic/SECURITY_GUIDE.md` | 256 | External link skipped (no network fetch) | https://python.readthedocs.io/en/latest/library/security_warnings.html |
| `links` | `docs/logic/SECURITY_GUIDE.md` | 259 | External link skipped (no network fetch) | https://github.com/pyupio/safety |
| `links` | `docs/logic/SECURITY_GUIDE.md` | 260 | External link skipped (no network fetch) | https://github.com/PyCQA/bandit |
| `links` | `docs/logic/SECURITY_GUIDE.md` | 261 | External link skipped (no network fetch) | https://owasp.org/www-project-dependency-check/ |
| `links` | `docs/logic/TDFOL/ARCHIVE/QUICK_REFERENCE_2026_02_18.md` | 346 | External link skipped (no network fetch) | https://plato.stanford.edu/entries/logic-deontic/ |
| `links` | `docs/logic/TDFOL/ARCHIVE/QUICK_REFERENCE_2026_02_18.md` | 347 | External link skipped (no network fetch) | https://johanvanbenthemamsterdamorg/ |
| `links` | `docs/logic/TDFOL/ARCHIVE/QUICK_REFERENCE_2026_02_18.md` | 348 | External link skipped (no network fetch) | https://docs.pytest.org/ |
| `links` | `docs/logic/TDFOL/ARCHIVE/QUICK_REFERENCE_2026_02_18.md` | 349 | External link skipped (no network fetch) | https://mypy.readthedocs.io/ |
| `links` | `docs/logic/TDFOL/INDEX.md` | 474 | External link skipped (no network fetch) | https://plato.stanford.edu/entries/logic-deontic/ |
| `links` | `docs/logic/TDFOL/INDEX.md` | 475 | External link skipped (no network fetch) | https://plato.stanford.edu/entries/logic-modal/ |
| `links` | `docs/logic/TDFOL/INDEX.md` | 476 | External link skipped (no network fetch) | https://en.wikipedia.org/wiki/Linear_temporal_logic |
| `links` | `docs/logic/TDFOL/README_security_validator.md` | 342 | External link skipped (no network fetch) | https://owasp.org/www-project-top-ten/ |
| `links` | `docs/logic/TDFOL/README_security_validator.md` | 343 | External link skipped (no network fetch) | https://cwe.mitre.org/top25/ |
| `links` | `docs/logic/TDFOL/README_security_validator.md` | 344 | External link skipped (no network fetch) | https://www.nist.gov/cyberframework |
| `links` | `docs/logic/TDFOL/README_security_validator.md` | 345 | External link skipped (no network fetch) | https://eprint.iacr.org/ |
| `links` | `docs/logic/integration/CHANGELOG.md` | 5 | External link skipped (no network fetch) | https://keepachangelog.com/en/1.0.0/ |
| `links` | `docs/logic/integration/CHANGELOG.md` | 6 | External link skipped (no network fetch) | https://semver.org/spec/v2.0.0.html |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 64 | External link skipped (no network fetch) | https://eprint.iacr.org/2016/260 |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 65 | External link skipped (no network fetch) | https://arxiv.org/abs/1906.07221 |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 66 | External link skipped (no network fetch) | https://github.com/ethereum/py_ecc |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 67 | External link skipped (no network fetch) | https://github.com/zcash/zips/ |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 311 | External link skipped (no network fetch) | https://github.com/ethereum/py_ecc |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 312 | External link skipped (no network fetch) | https://github.com/zkcrypto/bellman |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 313 | External link skipped (no network fetch) | https://github.com/iden3/snarkjs |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 317 | External link skipped (no network fetch) | https://eprint.iacr.org/2016/260 |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 318 | External link skipped (no network fetch) | https://github.com/ethereum/EIPs/blob/master/EIPS/eip-197.md |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 319 | External link skipped (no network fetch) | https://github.com/zcash/zips/blob/master/protocol/sapling.pdf |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 323 | External link skipped (no network fetch) | https://medium.com/@VitalikButerin/zk-snarks-under-the-hood-b33151a013f6 |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 324 | External link skipped (no network fetch) | https://blog.ethereum.org/2016/12/05/zksnarks-in-a-nutshell/ |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 328 | External link skipped (no network fetch) | https://github.com/iden3/circom |
| `links` | `docs/logic/zkp/PRODUCTION_UPGRADE_PATH.md` | 329 | External link skipped (no network fetch) | https://github.com/Zokrates/ZoKrates |
| `links` | `docs/logic/zkp/QUICKSTART.md` | 165 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/issues |
| `links` | `docs/logic/zkp/SECURITY_CONSIDERATIONS.md` | 326 | External link skipped (no network fetch) | https://github.com/endomorphosis/ipfs_datasets_py/security |
| `links` | `docs/logic/zkp/SECURITY_CONSIDERATIONS.md` | 390 | External link skipped (no network fetch) | https://z.cash/technology/zksnarks/ |
| `links` | `docs/logic/zkp/SECURITY_CONSIDERATIONS.md` | 391 | External link skipped (no network fetch) | https://eprint.iacr.org/2016/260 |
| `links` | `docs/logic/zkp/SECURITY_CONSIDERATIONS.md` | 392 | External link skipped (no network fetch) | https://arxiv.org/abs/1906.07221 |
| `links` | `docs/logic/zkp/SECURITY_CONSIDERATIONS.md` | 396 | External link skipped (no network fetch) | https://github.com/trailofbits/zkp-audit-guide |
| `links` | `docs/logic/zkp/SECURITY_CONSIDERATIONS.md` | 397 | External link skipped (no network fetch) | https://www.bearssl.org/ctmul.html |
| `links` | `docs/logic/zkp/SECURITY_CONSIDERATIONS.md` | 401 | External link skipped (no network fetch) | https://gdpr-info.eu/art-32-gdpr/ |
| `links` | `docs/logic/zkp/SECURITY_CONSIDERATIONS.md` | 402 | External link skipped (no network fetch) | https://www.hhs.gov/hipaa/for-professionals/security/ |
| `links` | `docs/optimizers/CHANGELOG.md` | 5 | External link skipped (no network fetch) | https://keepachangelog.com/en/1.0.0/ |
| `links` | `docs/optimizers/CHANGELOG.md` | 6 | External link skipped (no network fetch) | https://semver.org/spec/v2.0.0.html |
| `links` | `docs/optimizers/docs/SEMANTIC_DEDUPLICATION_GUIDE.md` | 180 | External link skipped (no network fetch) | https://arxiv.org/abs/1908.10084 |
| `links` | `docs/optimizers/graphrag/IMPLEMENTATION_PLAN.md` | 5 | External link skipped (no network fetch) | https://github.com/endomorphosis/complaint-generator |
| `links` | `docs/optimizers/graphrag/PHASE1_COMPLETE.md` | 13 | External link skipped (no network fetch) | https://github.com/endomorphosis/complaint-generator |
| `links` | `docs/optimizers/logic_theorem_optimizer/ARCHITECTURE.md` | 5 | External link skipped (no network fetch) | https://github.com/endomorphosis/complaint-generator/blob/master/adversarial_harness/README.md |
| `links` | `docs/optimizers/logic_theorem_optimizer/IMPLEMENTATION_SUMMARY.md` | 5 | External link skipped (no network fetch) | https://github.com/endomorphosis/complaint-generator |
| `links` | `docs/optimizers/logic_theorem_optimizer/PHASE2_COMPLETE.md` | 456 | External link skipped (no network fetch) | https://github.com/endomorphosis/complaint-generator |
| `links` | `docs/reports/cicd_setup_complete.md` | 167 | External link skipped (no network fetch) | https://docs.github.com/en/actions |
| `links` | `docs/reports/cicd_setup_complete.md` | 168 | External link skipped (no network fetch) | https://docs.github.com/en/actions/hosting-your-own-runners |
| `links` | `docs/tutorials/index.md` | 30 | External link skipped (no network fetch) | https://github.com/your-organization/ipfs_datasets_py/issues |
| `links` | `docs/tutorials/index.md` | 34 | External link skipped (no network fetch) | https://github.com/your-organization/ipfs_datasets_py/blob/main/CONTRIBUTING.md |
