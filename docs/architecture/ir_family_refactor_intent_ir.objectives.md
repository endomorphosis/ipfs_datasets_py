# IR Family Refactor and Intent IR Objective Heap

This file is the durable source of intent for the Legal/Security/Intent IR
program. The companion todo board is a reviewed execution projection. Neither
the presence of an evidence ID here nor a drained board proves a goal
complete. Completion requires fresh validation evidence bound to the current
repository tree.

The root is `provisionally_complete` only because this reviewed plan delegates
implementation to its child goals; it cannot become `verified_complete` until
every child and the root conformance gate have fresh evidence.

## IRF-G000 Shared, source-grounded, proof-aware IR family

- Status: provisionally_complete
- Parent:
- Fib priority: 1
- Track: platform
- Priority: P0
- Bundle: ir-family/root
- Parallel lane: integration-rollout
- Resource class: cpu-validation
- Goal: Establish a compatible Legal, Security, and Intent IR family with immutable provenance, deterministic identity, domain-neutral formalization contracts, typed proof authority, and a safe SkillCenter-to-GraphRAG-to-formal-logic pipeline.
- Evidence: 920000000000000000000
- Evidence criteria: 920000000000000000000=all child goals have fresh current-tree validation, the cross-domain conformance and offline Intent pipeline pass, Security compatibility remains green, and no model, GraphRAG result, evidence gate, or task-board statement is promoted to proof authority.
- Evidence source policy: A qualifying root receipt must enumerate every child goal and its fresh terminal receipt, bind the repository tree and policy version, include the complete selected test population, and report zero authority-boundary, license-policy, prompt-execution, or split-leakage violations. This objective document, generated tasks, model output, and semantic similarity are non-qualifying.
- Outputs: docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md, docs/architecture/ir_family_refactor_intent_ir.objectives.md, docs/architecture/ir_family_refactor_intent_ir.todo.md, tests/integration/logic/test_ir_family_conformance.py
- Predicted files: tests/integration/logic/test_ir_family_conformance.py
- Interfaces: IRFamilyConformance@1
- Validation: python -m pytest tests/integration/logic/test_ir_family_conformance.py -q
- Acceptance: Legal, Security, and Intent adapters implement the reviewed shared contracts; declaration identities are stable; every formal assertion is source grounded; result authority is typed; the pinned offline SkillCenter fixture reaches a formal artifact and receipt without executing source instructions.
- Gap task: Close the highest-priority uncovered child goal without weakening provenance, compatibility, licensing, safety, or proof-authority boundaries.
- Refinement: Implement child goals independently and reserve shared package exports, registry edits, cross-domain integration, and rollout documentation for late single-owner tasks.
- Embedding query: legal security intent intermediate representation provenance deterministic CID GraphRAG skills formal logic autoencoder proof receipt compatibility
- AST query: IRDocumentEnvelope SecurityIR IntentIRDocument FormalizationArtifact IRFamilyConformance

## IRF-G010 Freeze and preserve Security IR compatibility

- Status: active
- Parent: IRF-G000
- Fib priority: 1
- Track: quality
- Priority: P0
- Bundle: ir-family/security-freeze
- Parallel lane: security-freeze
- Resource class: cpu-small
- Goal: Freeze the current Security IR public imports, payloads, canonical bytes, identifiers, CLI behavior, reports, and receipts before migrating them.
- Evidence: 920000000000000000010
- Evidence criteria: 920000000000000000010=a current-tree golden compatibility test covers public imports, representative valid and invalid payloads, both legacy identifier representations, CLI exit behavior, reports, and receipts without changing production runtime behavior.
- Evidence source policy: Only the reviewed compatibility manifest plus a fresh passing golden-contract receipt qualifies. Documentation, source inspection, and regenerated output without checked expectations are non-qualifying.
- Outputs: docs/security_verification/security_ir_v1_compatibility.md, tests/fixtures/security_ir/v1/manifest.json, tests/unit/logic/security_models/crypto_exchange/test_legacy_contract_freeze.py
- Predicted files: docs/security_verification/security_ir_v1_compatibility.md, tests/fixtures/security_ir/v1/manifest.json, tests/unit/logic/security_models/crypto_exchange/test_legacy_contract_freeze.py
- Interfaces: SecurityIRLegacyCompatibility@1
- Validation: python -m pytest tests/unit/logic/security_models/crypto_exchange/test_legacy_contract_freeze.py -q
- Acceptance: The selected corpus detects import, serialization, canonical-byte, identifier, CLI, report, and receipt drift and records solver-dependent coverage separately.
- Gap task: Add the smallest missing golden contract or compatibility fixture without editing production Security IR modules.
- Refinement: Keep artifact inventory read-only and keep runtime changes out of the freeze bundle.
- Embedding query: SecurityModelIR crypto exchange Xaman legacy compatibility canonical bytes CID CLI reports receipts
- AST query: SecurityModelIR ProofReport ProofReceipt prove_all submodule_registry

## IRF-G020 Build the shared immutable IR kernel

- Status: active
- Parent: IRF-G000
- Fib priority: 1
- Track: platform
- Priority: P0
- Bundle: ir-family/core
- Parallel lane: core-contracts
- Resource class: cpu-medium
- Goal: Provide domain-neutral immutable envelopes, canonical identity, provenance, diagnostics, schema migration, solver-neutral claims, evidence, and artifact manifests without importing a domain, solver, GraphRAG, or model runtime.
- Evidence: 920000000000000000020
- Evidence criteria: 920000000000000000020=the shared core passes golden identity, mutation, collection-semantics, source-map, diagnostic, migration, claim/result-authority, and artifact-integrity contracts in environments with and without optional CID dependencies.
- Evidence source policy: A fresh complete unit-test receipt covering the public core contracts and import-boundary check qualifies. A passing domain test alone or an identifier string without canonical-byte evidence does not.
- Outputs: ipfs_datasets_py/logic/ir_core/canonical.py, ipfs_datasets_py/logic/ir_core/identity.py, ipfs_datasets_py/logic/ir_core/provenance.py, ipfs_datasets_py/logic/ir_core/diagnostics.py, ipfs_datasets_py/logic/ir_core/schema_registry.py, ipfs_datasets_py/logic/ir_core/claims.py, ipfs_datasets_py/logic/ir_core/evidence.py, ipfs_datasets_py/logic/ir_core/artifacts.py, ipfs_datasets_py/logic/ir_core/protocols.py
- Predicted files: ipfs_datasets_py/logic/ir_core/canonical.py, ipfs_datasets_py/logic/ir_core/identity.py, ipfs_datasets_py/logic/ir_core/provenance.py, ipfs_datasets_py/logic/ir_core/diagnostics.py, ipfs_datasets_py/logic/ir_core/schema_registry.py, ipfs_datasets_py/logic/ir_core/claims.py, ipfs_datasets_py/logic/ir_core/evidence.py, ipfs_datasets_py/logic/ir_core/artifacts.py, ipfs_datasets_py/logic/ir_core/protocols.py
- Interfaces: IRCore@1, IRCanonicalIdentity@1, IRArtifactManifest@1
- Validation: python -m pytest tests/unit/logic/ir_core -q
- Acceptance: Core data is immutable or defensively copied; identity is dependency-independent and declares collection semantics; provenance and diagnostics are source mapped; claims and results are backend neutral; manifests bind all deterministic inputs and outputs.
- Gap task: Implement the highest-priority missing leaf core contract and its exclusive test file.
- Refinement: Split identity, provenance, schema, claims, and artifacts into conflict-free leaf tasks; do not edit any package `__init__.py` in those tasks.
- Embedding query: immutable IR core canonical JSON multihash provenance diagnostics schema migration claim proof obligation artifact manifest
- AST query: IRDocumentEnvelope CanonicalIdentity SourceReference Diagnostic ProofObligation ArtifactManifest

## IRF-G030 Separate and adapt Security IR declarations

- Status: active
- Parent: IRF-G010, IRF-G020
- Fib priority: 2
- Track: platform
- Priority: P0
- Bundle: ir-family/security-model
- Parallel lane: security-model
- Resource class: cpu-medium
- Goal: Represent Security IR as immutable declarations with exchange and Xaman adapters while placing proof runs, runtime traces, disproof vectors, and policy decisions in separate typed artifacts.
- Evidence: 920000000000000000030
- Evidence criteria: 920000000000000000030=the golden legacy corpus losslessly adapts to Security IR v1, verification cannot change declaration identity, exchange and Xaman vocabulary are isolated, and mutation-after-validation tests pass.
- Evidence source policy: A fresh adapter round-trip and semantic-mutation receipt bound to the golden manifest qualifies. Merely re-exporting `SecurityModelIR` or changing module paths does not.
- Outputs: ipfs_datasets_py/logic/security_ir/model.py, ipfs_datasets_py/logic/security_ir/adapter.py, ipfs_datasets_py/logic/security_ir/results.py, ipfs_datasets_py/logic/security_ir/exchange/adapter.py, ipfs_datasets_py/logic/security_ir/xaman/adapter.py
- Predicted files: ipfs_datasets_py/logic/security_ir/model.py, ipfs_datasets_py/logic/security_ir/adapter.py, ipfs_datasets_py/logic/security_ir/results.py, ipfs_datasets_py/logic/security_ir/exchange/adapter.py, ipfs_datasets_py/logic/security_ir/xaman/adapter.py
- Interfaces: SecurityIR@1, SecurityIRLegacyAdapter@1
- Validation: python -m pytest tests/unit/logic/security_ir -q
- Acceptance: Declarative model, verification runs, monitoring, evidence gates, policy decisions, and proof receipts are distinct; domain vocabulary is adapter owned; old data remains readable; unknown extensions fail closed.
- Gap task: Implement the smallest uncovered Security v1 declaration or domain-adapter contract with a golden round-trip test.
- Refinement: Keep exchange and Xaman leaf files exclusive and defer all old import/registry edits to the compatibility integration goal.
- Embedding query: immutable Security IR declaration verification run exchange wallet Xaman domain adapter legacy round trip
- AST query: SecurityIR VerificationRun ExchangeSecurityAdapter XamanSecurityAdapter SecurityIRLegacyAdapter

## IRF-G040 Decouple proof backends and normalize Security artifacts

- Status: active
- Parent: IRF-G020, IRF-G030
- Fib priority: 2
- Track: runtime
- Priority: P0
- Bundle: ir-family/security-proof-artifacts
- Parallel lane: backends-artifacts
- Resource class: cpu-proof-translate
- Goal: Compile solver-neutral obligations through side-effect-free backends, distinguish all result authorities, and migrate Security evidence into immutable run manifests without deleting legacy artifacts.
- Evidence: 920000000000000000040
- Evidence criteria: 920000000000000000040=backend discovery is side-effect free, portfolio results are order independent under policy, Xaman blocker queries are typed as evidence gates, and every promoted fixture has an integrity-checked manifest plus legacy-ID map.
- Evidence source policy: Fresh fake-backend contract receipts, scheduled real-backend receipts when capabilities exist, result-authority adversarial tests, and an integrity-verified artifact inventory qualify. Solver unavailability must be explicit and cannot be reported as proof success.
- Outputs: ipfs_datasets_py/logic/backends/registry.py, ipfs_datasets_py/logic/backends/z3/compiler.py, ipfs_datasets_py/logic/backends/cvc5/compiler.py, ipfs_datasets_py/logic/security_ir/artifact_migration.py, security_ir_artifacts/migrations/manifest.json
- Predicted files: ipfs_datasets_py/logic/backends/registry.py, ipfs_datasets_py/logic/backends/z3/compiler.py, ipfs_datasets_py/logic/backends/cvc5/compiler.py, ipfs_datasets_py/logic/security_ir/artifact_migration.py, security_ir_artifacts/migrations/manifest.json
- Interfaces: ProofBackend@1, SecurityResultAuthority@1, SecurityArtifactMigration@1
- Validation: python -m pytest tests/unit/logic/backends tests/unit/logic/security_ir/test_artifact_migration.py -q
- Acceptance: Capability probes install nothing; attempts and assumptions are recorded; proof, monitor, evidence-gate, and policy results cannot substitute for one another; migration inventories legacy files before any removal.
- Gap task: Close the highest-risk backend, authority, or artifact-integrity gap with a bounded fixture.
- Refinement: Split backend registry, result authority, read-only inventory, and migration implementation into distinct file owners.
- Embedding query: solver neutral Z3 cvc5 SMT result authority evidence gate policy decision security artifact manifest migration
- AST query: ProofBackendRegistry ProofResult MonitorResult EvidenceGateResult PolicyDecision ArtifactMigrationManifest

## IRF-G050 Ingest SkillCenter reproducibly and safely

- Status: active
- Parent: IRF-G020
- Fib priority: 1
- Track: data
- Priority: P0
- Bundle: ir-family/intent-ingestion
- Parallel lane: intent-ingestion
- Resource class: io-artifact
- Goal: Fetch and read SkillCenter SQLite bundles only by immutable revision, bind every record to source and bundle digests, enforce safety bounds, and apply explicit license, secret, personal-data, and hostile-content quarantine policy.
- Evidence: 920000000000000000050
- Evidence criteria: 920000000000000000050=the two pilot bundle profiles and adversarial fixtures ingest deterministically with complete lineage and policy decisions, while mutable revisions, malformed data, oversize text, unsafe metadata, prompt injection, and unknown licenses fail closed.
- Evidence source policy: Offline fixture receipts plus a separately recorded pinned-network snapshot receipt qualify. Network availability is not required for unit tests, and a successful download without hash, license, and quarantine evidence does not qualify.
- Outputs: ipfs_datasets_py/logic/intent_ir/source_adapters/skillcenter.py, ipfs_datasets_py/logic/intent_ir/source_adapters/snapshot.py, ipfs_datasets_py/logic/intent_ir/source_adapters/policy.py, tests/fixtures/intent_ir/skillcenter/manifest.json
- Predicted files: ipfs_datasets_py/logic/intent_ir/source_adapters/skillcenter.py, ipfs_datasets_py/logic/intent_ir/source_adapters/snapshot.py, ipfs_datasets_py/logic/intent_ir/source_adapters/policy.py, tests/fixtures/intent_ir/skillcenter/manifest.json
- Interfaces: SkillCenterSnapshot@1, SkillSourcePolicy@1
- Validation: python -m pytest tests/unit/logic/intent_ir/test_skillcenter_source.py tests/unit/logic/intent_ir/test_skillcenter_policy.py -q
- Acceptance: Reads are immutable, query-only, schema checked, keyset paged, and bounded; commands are never executed; arbitrary YAML construction is impossible; every record has revision, bundle hash, content hash, source identity, review state, and license decision.
- Gap task: Add the smallest missing snapshot, adapter, or policy control and its adversarial offline fixture.
- Refinement: Keep downloader/cache, SQLite adapter, and policy modules separate; generated bundles belong in supervisor state, not Git.
- Embedding query: SkillCenter Hugging Face pinned revision SQLite FTS5 source provenance license prompt injection secrets quarantine
- AST query: SkillCenterBundleReader SkillCenterSnapshot SkillSourcePolicy SourceRef

## IRF-G060 Build source-grounded Intent IR and GraphRAG

- Status: active
- Parent: IRF-G020, IRF-G050
- Fib priority: 2
- Track: graphrag
- Priority: P0
- Bundle: ir-family/intent-semantics
- Parallel lane: intent-graph
- Resource class: cpu-medium
- Goal: Normalize SkillCenter records into versioned Intent IR and build separate corpus-evidence and semantic-intent graphs whose nodes and edges retain exact source grounding.
- Evidence: 920000000000000000060
- Evidence criteria: 920000000000000000060=a reviewed pilot set passes schema, grounding, ontology, deterministic projection, bounded retrieval, duplicate isolation, and adversarial-neighbor tests with no unsupported semantic term silently discarded.
- Evidence source policy: Fresh schema/ontology conformance and retrieval-evaluation receipts over a versioned reviewed fixture qualify. Graph similarity, a model response, or an ungrounded edge does not.
- Outputs: ipfs_datasets_py/logic/intent_ir/schema.py, ipfs_datasets_py/logic/intent_ir/normalize/skill.py, ipfs_datasets_py/logic/intent_ir/graphrag/ontology.py, ipfs_datasets_py/logic/intent_ir/graphrag/corpus_projector.py, ipfs_datasets_py/logic/intent_ir/graphrag/semantic_projector.py
- Predicted files: ipfs_datasets_py/logic/intent_ir/schema.py, ipfs_datasets_py/logic/intent_ir/normalize/skill.py, ipfs_datasets_py/logic/intent_ir/graphrag/ontology.py, ipfs_datasets_py/logic/intent_ir/graphrag/corpus_projector.py, ipfs_datasets_py/logic/intent_ir/graphrag/semantic_projector.py
- Interfaces: IntentIR@1, IntentGraphOntology@1
- Validation: python -m pytest tests/unit/logic/intent_ir/test_schema.py tests/unit/logic/intent_ir/test_normalize_skill.py tests/unit/logic/intent_ir/graphrag -q
- Acceptance: Goals, modalities, conditions, actions, effects, failures, verification, and control flow are typed and source grounded; graph versions and IR digests are bound; retrieval is bounded and cannot cross evaluation partitions.
- Gap task: Implement the smallest missing schema, normalizer, ontology, or graph-projection contract with a grounded fixture.
- Refinement: Give schema, normalizer, corpus graph, and semantic graph exclusive leaf files and tests.
- Embedding query: Intent IR goal action precondition effect verification control flow GraphRAG ontology source grounding
- AST query: IntentIRDocument IntentNormalizer IntentGraphOntology CorpusGraphProjector SemanticIntentGraphProjector

## IRF-G070 Extract domain-neutral deterministic formalization

- Status: active
- Parent: IRF-G020, IRF-G030, IRF-G060
- Fib priority: 3
- Track: platform
- Priority: P1
- Bundle: ir-family/formalization
- Parallel lane: formalization-contracts
- Resource class: cpu-proof-type-check
- Goal: Extract reusable formalization samples, views, compilers, source maps, proof obligations, and decompilation contracts, then implement Legal, Security, and Intent adapters without inheriting one domain's corpus rules.
- Evidence: 920000000000000000070
- Evidence criteria: 920000000000000000070=all three domain adapters emit typed, source-grounded formal artifacts, unsupported semantics remain explicit, semantic mutations affect the expected obligations, and compile/decompile round trips pass the reviewed equivalence policy.
- Evidence source policy: Fresh adapter conformance, semantic-mutation, source-map, and round-trip receipts qualify. Passing syntax checks or model-proposed formulas without deterministic compilation do not.
- Outputs: ipfs_datasets_py/logic/formalization/samples.py, ipfs_datasets_py/logic/formalization/views.py, ipfs_datasets_py/logic/formalization/compiler.py, ipfs_datasets_py/logic/formalization/decompiler.py, ipfs_datasets_py/logic/legal_ir/adapter.py, ipfs_datasets_py/logic/security_ir/formalization_adapter.py, ipfs_datasets_py/logic/intent_ir/formalize/compiler.py
- Predicted files: ipfs_datasets_py/logic/formalization/samples.py, ipfs_datasets_py/logic/formalization/views.py, ipfs_datasets_py/logic/formalization/compiler.py, ipfs_datasets_py/logic/formalization/decompiler.py, ipfs_datasets_py/logic/legal_ir/adapter.py, ipfs_datasets_py/logic/security_ir/formalization_adapter.py, ipfs_datasets_py/logic/intent_ir/formalize/compiler.py
- Interfaces: FormalizationSample@1, FormalizationCompiler@1, FormalizationArtifact@1
- Validation: python -m pytest tests/unit/logic/formalization tests/unit/logic/intent_ir/formalize -q
- Acceptance: Deterministic views cover typed facts, intention/deontic modality, action contracts, temporal/workflow control, invariants, failures, and verification obligations; every formula maps to sources and unsupported constructs are preserved as diagnostics.
- Gap task: Close the smallest uncovered formal view or domain adapter with deterministic and semantic-mutation tests.
- Refinement: Do not edit the large Legal autoencoder in adapter tasks; preserve Legal aliases and move shared behavior behind new protocols.
- Embedding query: formalization sample modal deontic temporal action logic Hoare proof obligation source map decompiler
- AST query: FormalizationSample FormalizationView FormalizationCompiler FormalizationArtifact LegalIRAdapter SecurityIRFormalizationAdapter IntentFormalizer

## IRF-G080 Add a bounded learned formalization advisor

- Status: active
- Parent: IRF-G060, IRF-G070
- Fib priority: 5
- Track: runtime
- Priority: P1
- Bundle: ir-family/intent-advisor
- Parallel lane: learned-advisor
- Resource class: llm-proof-draft
- Goal: Extract a domain-neutral autoencoder/advisor contract, build leakage-safe source-free features and Intent heads, and use learned output only as a typed candidate or bounded repair after deterministic compilation.
- Evidence: 920000000000000000080
- Evidence criteria: 920000000000000000080=held-out-source evaluation compares deterministic-only, from-scratch Intent, and Legal-encoder-transfer variants; checkpoints are domain/version isolated; candidate repairs cannot alter provenance, assumptions, modality, license, or trust; false-proof count is zero.
- Evidence source policy: A fresh paired benchmark receipt with immutable split, graph, feature, code, configuration, and checkpoint identities qualifies. Training loss, random-row evaluation, or a model claim of correctness does not.
- Outputs: ipfs_datasets_py/logic/formalization/advisor.py, ipfs_datasets_py/logic/formalization/features.py, ipfs_datasets_py/logic/intent_ir/formalize/features.py, ipfs_datasets_py/logic/intent_ir/formalize/advisor.py, ipfs_datasets_py/logic/intent_ir/evaluation/splits.py
- Predicted files: ipfs_datasets_py/logic/formalization/advisor.py, ipfs_datasets_py/logic/formalization/features.py, ipfs_datasets_py/logic/intent_ir/formalize/features.py, ipfs_datasets_py/logic/intent_ir/formalize/advisor.py, ipfs_datasets_py/logic/intent_ir/evaluation/splits.py
- Interfaces: FormalizationAdvisor@1, IntentFormalizationAdvisor@1
- Validation: python -m pytest tests/unit/logic/formalization/test_advisor.py tests/unit/logic/intent_ir/formalize/test_advisor.py tests/unit/logic/intent_ir/evaluation/test_splits.py -q
- Acceptance: Features omit raw source text and partition labels; source families and duplicates never cross splits; advisor patches are bounded and type checked; checkpoint manifests bind the domain ontology and view registry.
- Gap task: Implement the smallest missing feature, split, advisor, or checkpoint safeguard with an adversarial test.
- Refinement: Keep generic advisor, Intent features, split policy, and Intent adapter in separate files; live model access is optional and never required by unit tests.
- Embedding query: autoencoder formalization advisor Intent IR source free features group split checkpoint transfer learning bounded repair
- AST query: FormalizationAdvisor FeatureArtifact IntentFormalizationAdvisor DatasetSplitManifest CheckpointManifest

## IRF-G090 Validate, integrate, and roll out safely

- Status: active
- Parent: IRF-G010, IRF-G030, IRF-G040, IRF-G050, IRF-G060, IRF-G070, IRF-G080
- Fib priority: 5
- Track: quality
- Priority: P1
- Bundle: ir-family/integration
- Parallel lane: integration-rollout
- Resource class: cpu-validation
- Goal: Add compatibility facades, shared exports, cross-domain conformance, an offline end-to-end Intent fixture, reproducibility and leakage benchmarks, and staged shadow/canary rollout controls.
- Evidence: 920000000000000000090
- Evidence criteria: 920000000000000000090=one current-tree receipt covers legacy Security imports, all shared/domain adapters, offline SkillCenter-to-formal-artifact lineage, deterministic rebuild, semantic mutation, leakage guards, authority boundaries, and documented shadow/canary rollback gates.
- Evidence source policy: A complete fresh integration and benchmark receipt plus reviewed migration/runbook artifacts qualifies. A drained task board, passing unit subset, or live-model demonstration without offline reproducibility does not.
- Outputs: ipfs_datasets_py/logic/submodule_registry.py, tests/integration/logic/test_ir_family_conformance.py, tests/integration/logic/test_intent_ir_pipeline.py, tests/benchmarks/logic/test_intent_ir_benchmark.py, docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md
- Predicted files: ipfs_datasets_py/logic/submodule_registry.py, tests/integration/logic/test_ir_family_conformance.py, tests/integration/logic/test_intent_ir_pipeline.py, tests/benchmarks/logic/test_intent_ir_benchmark.py
- Interfaces: IRFamilyIntegration@1
- Validation: python -m pytest tests/integration/logic/test_ir_family_conformance.py tests/integration/logic/test_intent_ir_pipeline.py tests/benchmarks/logic/test_intent_ir_benchmark.py -q
- Acceptance: Shared exports have one owner; old Security imports retain behavior; the offline fixture proves full lineage without execution; benchmark splits are leak free; shadow mode is the default; canary promotion requires zero authority violations and a material paired improvement.
- Gap task: Close the highest-risk compatibility, end-to-end, reproducibility, benchmark, or rollout gap after all prerequisite interfaces are stable.
- Refinement: Integrate late, edit shared registries and package exports only in the designated task, and keep generated run artifacts outside Git until a reviewed manifest promotes them.
- Embedding query: cross domain IR conformance SkillCenter GraphRAG Intent formal logic Security compatibility benchmark shadow canary rollback
- AST query: IRFamilyConformance IntentIRPipeline submodule_registry CompatibilityFacade BenchmarkReceipt
