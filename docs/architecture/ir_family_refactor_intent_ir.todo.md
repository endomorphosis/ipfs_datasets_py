# IR Family Refactor and Intent IR Task Board

This is the hand-reviewed execution board for
`IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md`. Paths are relative to the
`ipfs_datasets_py` repository root. All tasks use manual completion: output
existence alone is not evidence that code, semantics, security, or proof
contracts pass.

Run this board with task prefix `IRF-`. Parallel-lane labels are descriptive;
the declared files, interfaces, dependencies, and observed changes determine
real conflict edges.

## IRF-001 Freeze the Security IR public surface

- Status: completed
- Completion: manual
- Priority: P0
- Track: quality
- Depends on:
- Goal id: IRF-G010
- Outputs: docs/security_verification/security_ir_v1_compatibility.md, tests/unit/logic/security_models/crypto_exchange/test_public_api_freeze.py
- Validation: python -m pytest tests/unit/logic/security_models/crypto_exchange/test_public_api_freeze.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/security-freeze
- Parallel lane: security-freeze
- Resource class: cpu-small
- Predicted files: docs/security_verification/security_ir_v1_compatibility.md, tests/unit/logic/security_models/crypto_exchange/test_public_api_freeze.py
- Interfaces: SecurityIRLegacyCompatibility@1
- Conflict policy: Add an API inventory and contract test only; do not edit production Security IR modules, package exports, the submodule registry, or artifacts.
- Preconditions: Inspect current package exports, CLI entry points, reports, receipts, and registry declarations.
- Effects: Public import and CLI compatibility becomes executable and reviewable.
- Evidence subset: Security IR public-surface freeze receipt
- Token class: medium
- Estimated tokens: 6000
- Acceptance: Inventory and test `SecurityModelIR`, canonicalization/CID functions, proof reports/receipts, monitors, projector, runners, validators, policies, example claims, CLI exit behavior, and `submodule_registry` discovery without changing their behavior.

## IRF-002 Create the Security IR v1 golden corpus

- Status: completed
- Completion: manual
- Priority: P0
- Track: quality
- Depends on: IRF-001
- Goal id: IRF-G010
- Outputs: tests/fixtures/security_ir/v1/manifest.json, tests/fixtures/security_ir/v1/exchange_model.json, tests/fixtures/security_ir/v1/xaman_model.json, tests/unit/logic/security_models/crypto_exchange/test_legacy_golden_contract.py
- Validation: python -m pytest tests/unit/logic/security_models/crypto_exchange/test_legacy_golden_contract.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/security-freeze
- Parallel lane: security-golden
- Resource class: cpu-small
- Predicted files: tests/fixtures/security_ir/v1/manifest.json, tests/fixtures/security_ir/v1/exchange_model.json, tests/fixtures/security_ir/v1/xaman_model.json, tests/unit/logic/security_models/crypto_exchange/test_legacy_golden_contract.py
- Interfaces: SecurityIRLegacyGoldenCorpus@1
- Conflict policy: Own only the new v1 fixture tree and golden test; do not regenerate or overwrite promoted `security_ir_artifacts`.
- Preconditions: IRF-001 defines the compatibility surface.
- Effects: Canonical bytes, both environment-dependent legacy identifier forms, validation failures, reports, and receipts have frozen examples.
- Evidence subset: Security IR golden-corpus receipt
- Token class: medium
- Estimated tokens: 6500
- Acceptance: Include representative valid exchange and Xaman payloads, invalid payloads, mutable-input regression fixtures, collection-order cases, and solver-availability metadata; assert exact expectations without treating a skipped solver as success.

## IRF-003 Inventory Security IR artifacts without deleting files

- Status: completed
- Completion: manual
- Priority: P0
- Track: data
- Depends on:
- Goal id: IRF-G040
- Outputs: tools/security_ir/inventory_artifacts.py, docs/security_verification/security_ir_artifact_inventory.json, tests/unit/tools/test_security_ir_artifact_inventory.py
- Validation: python -m pytest tests/unit/tools/test_security_ir_artifact_inventory.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/security-artifacts
- Parallel lane: artifact-inventory
- Resource class: io-artifact
- Predicted files: tools/security_ir/inventory_artifacts.py, docs/security_verification/security_ir_artifact_inventory.json, tests/unit/tools/test_security_ir_artifact_inventory.py
- Interfaces: SecurityArtifactInventory@1
- Conflict policy: Read `security_ir_artifacts` only; do not rename, move, delete, rebuild, or modify any existing artifact.
- Preconditions: None.
- Effects: Every tracked artifact is classified as source, golden, run output, promoted evidence, environment record, transient compiler output, ambiguous, or unknown.
- Evidence subset: read-only artifact-inventory receipt
- Token class: medium
- Estimated tokens: 6000
- Acceptance: Emit a deterministic inventory with paths, hashes, sizes, detected formats, likely producers, legacy IDs, ambiguity reasons, and recommendations; identify temporary and `-new` variants without choosing an authority.

## IRF-010 Implement deterministic shared canonicalization and identity

- Status: completed
- Completion: manual
- Priority: P0
- Track: platform
- Depends on:
- Goal id: IRF-G020
- Outputs: ipfs_datasets_py/logic/ir_core/canonical.py, ipfs_datasets_py/logic/ir_core/identity.py, tests/unit/logic/ir_core/test_identity.py
- Validation: python -m pytest tests/unit/logic/ir_core/test_identity.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/core
- Parallel lane: core-identity
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/logic/ir_core/canonical.py, ipfs_datasets_py/logic/ir_core/identity.py, tests/unit/logic/ir_core/test_identity.py
- Interfaces: IRCanonicalIdentity@1
- Conflict policy: Own only the two leaf modules and one test file; do not edit package exports or domain canonicalizers.
- Preconditions: Review current Legal modal IR and Security canonical/CID behavior.
- Effects: All domains can opt into one explicit, versioned, dependency-independent identity profile.
- Evidence subset: canonical-byte and identity-vector receipt
- Token class: medium
- Estimated tokens: 7000
- Acceptance: Define canonical UTF-8 JSON, fixed digest/CID profile, schema/domain separation, and declared ordered/set-like/multiset collection semantics; golden output must be identical with optional CID dependencies installed or absent.

## IRF-011 Implement core provenance, evidence, and diagnostics

- Status: completed
- Completion: manual
- Priority: P0
- Track: platform
- Depends on:
- Goal id: IRF-G020
- Outputs: ipfs_datasets_py/logic/ir_core/provenance.py, ipfs_datasets_py/logic/ir_core/evidence.py, ipfs_datasets_py/logic/ir_core/diagnostics.py, tests/unit/logic/ir_core/test_provenance_diagnostics.py
- Validation: python -m pytest tests/unit/logic/ir_core/test_provenance_diagnostics.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/core
- Parallel lane: core-provenance
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/logic/ir_core/provenance.py, ipfs_datasets_py/logic/ir_core/evidence.py, ipfs_datasets_py/logic/ir_core/diagnostics.py, tests/unit/logic/ir_core/test_provenance_diagnostics.py
- Interfaces: IRProvenance@1, IRDiagnostics@1
- Conflict policy: Reuse Legal IR patterns by adaptation or composition; do not move or edit Legal modules in this task.
- Preconditions: Inspect Legal source maps, diagnostics, and proof-carrying artifacts.
- Effects: Semantic nodes, evidence, and diagnostics can bind immutable sources and spans without embedding source bodies.
- Evidence subset: source-map and diagnostic round-trip receipt
- Token class: medium
- Estimated tokens: 7000
- Acceptance: Add immutable source references, spans, producer/config bindings, evidence references, stable diagnostic codes/severity, canonical serialization, cross-reference validation, and mutation-after-construction tests.

## IRF-012 Implement the core schema and migration registry

- Status: completed
- Completion: manual
- Priority: P0
- Track: platform
- Depends on:
- Goal id: IRF-G020
- Outputs: ipfs_datasets_py/logic/ir_core/schema_registry.py, tests/unit/logic/ir_core/test_schema_registry.py
- Validation: python -m pytest tests/unit/logic/ir_core/test_schema_registry.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/core
- Parallel lane: core-schema
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/logic/ir_core/schema_registry.py, tests/unit/logic/ir_core/test_schema_registry.py
- Interfaces: IRSchemaRegistry@1
- Conflict policy: Own only the registry protocol and its test; do not register domain schemas or edit exports.
- Preconditions: Review Legal IR schema-evolution behavior.
- Effects: Domain decoders can negotiate exact versions and execute explicit migrations.
- Evidence subset: schema compatibility and migration receipt
- Token class: small
- Estimated tokens: 4500
- Acceptance: Require exact schema IDs, compatibility declarations, deterministic migration paths, loss reports, unknown-version rejection, cycle detection, and migration receipts bound to source and destination digests.

## IRF-013 Implement solver-neutral claims and result authority

- Status: completed
- Completion: manual
- Priority: P0
- Track: platform
- Depends on:
- Goal id: IRF-G020
- Outputs: ipfs_datasets_py/logic/ir_core/claims.py, ipfs_datasets_py/logic/ir_core/protocols.py, tests/unit/logic/ir_core/test_claims_protocols.py
- Validation: python -m pytest tests/unit/logic/ir_core/test_claims_protocols.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/core
- Parallel lane: core-claims
- Resource class: cpu-proof-type-check
- Predicted files: ipfs_datasets_py/logic/ir_core/claims.py, ipfs_datasets_py/logic/ir_core/protocols.py, tests/unit/logic/ir_core/test_claims_protocols.py
- Interfaces: IRClaim@1, ProofBackend@1, ResultAuthority@1
- Conflict policy: Define backend/domain-neutral contracts only; import no solver and edit no current claim implementation.
- Preconditions: Audit Legal proof artifacts and Security `compile_to_z3` claims.
- Effects: Claims lower through backend adapters and proof, monitor, evidence-gate, and policy results become non-interchangeable.
- Evidence subset: claim/result authority adversarial receipt
- Token class: medium
- Estimated tokens: 7000
- Acceptance: Add immutable claims, assumptions, obligations, backend requests, attempts, bounded results, authority kinds, and receipts; tests must reject treating satisfiability, runtime monitoring, evidence readiness, or policy approval as theorem proof.

## IRF-014 Implement immutable artifact and run manifests

- Status: completed
- Completion: manual
- Priority: P0
- Track: data
- Depends on: IRF-010, IRF-011
- Goal id: IRF-G020
- Outputs: ipfs_datasets_py/logic/ir_core/artifacts.py, tests/unit/logic/ir_core/test_artifact_manifest.py
- Validation: python -m pytest tests/unit/logic/ir_core/test_artifact_manifest.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/core
- Parallel lane: core-artifacts
- Resource class: io-artifact
- Predicted files: ipfs_datasets_py/logic/ir_core/artifacts.py, tests/unit/logic/ir_core/test_artifact_manifest.py
- Interfaces: IRArtifactManifest@1
- Conflict policy: Own only the manifest module and test; do not migrate Security or fetch SkillCenter data here.
- Preconditions: IRF-010 and IRF-011 define identities and provenance.
- Effects: Pipeline runs bind inputs, producers, configurations, parents, outputs, diagnostics, and deterministic versus observational metadata.
- Evidence subset: artifact integrity and tamper-detection receipt
- Token class: medium
- Estimated tokens: 5500
- Acceptance: Manifest construction is deterministic; integrity verification detects missing, changed, duplicate, and unbound artifacts; timing/environment data cannot perturb deterministic output identity.

## IRF-020 Define immutable Security IR v1 and a legacy adapter

- Status: completed
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: IRF-002, IRF-010, IRF-011, IRF-012, IRF-013
- Goal id: IRF-G030
- Outputs: ipfs_datasets_py/logic/security_ir/model.py, ipfs_datasets_py/logic/security_ir/adapter.py, tests/unit/logic/security_ir/test_legacy_adapter.py
- Validation: python -m pytest tests/unit/logic/security_ir/test_legacy_adapter.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/security-model
- Parallel lane: security-v1
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/security_ir/model.py, ipfs_datasets_py/logic/security_ir/adapter.py, tests/unit/logic/security_ir/test_legacy_adapter.py
- Interfaces: SecurityIR@1, SecurityIRLegacyAdapter@1
- Conflict policy: Add new modules and tests only; do not edit legacy Security IR files, exports, or registry.
- Preconditions: Golden corpus and shared contracts pass.
- Effects: Legacy models adapt to immutable typed declarations whose identity excludes verification output.
- Evidence subset: lossless Security legacy/v1 round-trip receipt
- Token class: large
- Estimated tokens: 10000
- Acceptance: Defensively copy inputs; type principals, assets, trust zones, channels, policies, state machines, assumptions, claims, sources, and extensions; emit explicit loss/unsupported diagnostics; running verification data must not change declaration identity.

## IRF-021 Isolate the crypto-exchange Security adapter

- Status: todo
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: IRF-020
- Goal id: IRF-G030
- Outputs: ipfs_datasets_py/logic/security_ir/exchange/adapter.py, ipfs_datasets_py/logic/security_ir/exchange/vocabulary.py, tests/unit/logic/security_ir/exchange/test_adapter.py
- Validation: python -m pytest tests/unit/logic/security_ir/exchange/test_adapter.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/security-model
- Parallel lane: security-exchange
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/security_ir/exchange/adapter.py, ipfs_datasets_py/logic/security_ir/exchange/vocabulary.py, tests/unit/logic/security_ir/exchange/test_adapter.py
- Interfaces: ExchangeSecurityAdapter@1
- Conflict policy: Own only the new exchange adapter/vocabulary and test; leave Xaman, legacy modules, and shared exports untouched.
- Preconditions: IRF-020 defines Security IR v1.
- Effects: Exchange assumptions, wallet/deposit/withdrawal vocabulary, validators, policies, and default claims stop masquerading as shared core semantics.
- Evidence subset: exchange adapter conformance receipt
- Token class: medium
- Estimated tokens: 7500
- Acceptance: Namespaced versioned vocabulary validates consistently, adapters round trip the golden exchange model, semantic mutations change expected claims, and unknown extensions fail closed unless a declared adapter is present.

## IRF-022 Isolate the Xaman Security adapter

- Status: todo
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: IRF-020
- Goal id: IRF-G030
- Outputs: ipfs_datasets_py/logic/security_ir/xaman/adapter.py, ipfs_datasets_py/logic/security_ir/xaman/config.py, tests/unit/logic/security_ir/xaman/test_adapter.py
- Validation: python -m pytest tests/unit/logic/security_ir/xaman/test_adapter.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/security-model
- Parallel lane: security-xaman
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/security_ir/xaman/adapter.py, ipfs_datasets_py/logic/security_ir/xaman/config.py, tests/unit/logic/security_ir/xaman/test_adapter.py
- Interfaces: XamanSecurityAdapter@1
- Conflict policy: Own only new Xaman adapter/config and test; do not change existing artifact paths, reports, `prove_all.py`, or shared exports.
- Preconditions: IRF-020 defines Security IR v1.
- Effects: Xaman vocabulary, task IDs, source configuration, and artifact-path knowledge are isolated behind one adapter.
- Evidence subset: Xaman adapter and configuration receipt
- Token class: medium
- Estimated tokens: 7500
- Acceptance: Adapt the golden Xaman declaration with explicit source/config bindings; represent blockers as evidence requirements; do not assign proof authority or hardcode mutable repository state in the shared model.

## IRF-023 Add side-effect-free proof backend adapters

- Status: completed
- Completion: manual
- Priority: P0
- Track: runtime
- Depends on: IRF-013
- Goal id: IRF-G040
- Outputs: ipfs_datasets_py/logic/backends/registry.py, ipfs_datasets_py/logic/backends/z3/compiler.py, ipfs_datasets_py/logic/backends/cvc5/compiler.py, tests/unit/logic/backends/test_registry.py
- Validation: python -m pytest tests/unit/logic/backends/test_registry.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/backends
- Parallel lane: proof-backends
- Resource class: cpu-proof-translate
- Predicted files: ipfs_datasets_py/logic/backends/registry.py, ipfs_datasets_py/logic/backends/z3/compiler.py, ipfs_datasets_py/logic/backends/cvc5/compiler.py, tests/unit/logic/backends/test_registry.py
- Interfaces: ProofBackendRegistry@1
- Conflict policy: Add new backend modules and fake-runner tests; do not edit existing Security runners or install packages during tests.
- Preconditions: Solver-neutral claim and backend protocols pass.
- Effects: Obligations compile through explicit registered capabilities with bounded requests and complete attempt records.
- Evidence subset: backend discovery and compiler contract receipt
- Token class: large
- Estimated tokens: 9000
- Acceptance: Capability checks perform no installation or writes; fake backends cover success, counterexample, unsupported, unavailable, timeout, and malformed output; optional scheduled tests compare real Z3/cvc5 without making them unit-test requirements.

## IRF-024 Separate Security verification result families

- Status: todo
- Completion: manual
- Priority: P0
- Track: quality
- Depends on: IRF-020, IRF-023
- Goal id: IRF-G040
- Outputs: ipfs_datasets_py/logic/security_ir/results.py, ipfs_datasets_py/logic/security_ir/result_policy.py, tests/unit/logic/security_ir/test_result_authority.py
- Validation: python -m pytest tests/unit/logic/security_ir/test_result_authority.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/security-proof
- Parallel lane: security-results
- Resource class: cpu-proof-type-check
- Predicted files: ipfs_datasets_py/logic/security_ir/results.py, ipfs_datasets_py/logic/security_ir/result_policy.py, tests/unit/logic/security_ir/test_result_authority.py
- Interfaces: SecurityResultAuthority@1
- Conflict policy: Own only new result/policy modules and test; consume Xaman data through interfaces and do not edit its adapter.
- Preconditions: Security IR v1 and backend registry exist.
- Effects: Proof, runtime-monitor, evidence-gate, release-policy, and disproof outputs are distinct and deterministically selected.
- Evidence subset: result non-substitution adversarial receipt
- Token class: medium
- Estimated tokens: 7000
- Acceptance: Map legacy outputs with explicit diagnostics; prove that Xaman blocker satisfiability is an evidence gate, solver order cannot silently change accepted verdict, and no non-proof result can construct a proof receipt.

## IRF-025 Create the Security artifact migration manifest

- Status: todo
- Completion: manual
- Priority: P1
- Track: data
- Depends on: IRF-003, IRF-014, IRF-020, IRF-024
- Goal id: IRF-G040
- Outputs: ipfs_datasets_py/logic/security_ir/artifact_migration.py, security_ir_artifacts/migrations/manifest.json, tests/unit/logic/security_ir/test_artifact_migration.py
- Validation: python -m pytest tests/unit/logic/security_ir/test_artifact_migration.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/security-artifacts
- Parallel lane: artifact-migration
- Resource class: io-artifact
- Predicted files: ipfs_datasets_py/logic/security_ir/artifact_migration.py, security_ir_artifacts/migrations/manifest.json, tests/unit/logic/security_ir/test_artifact_migration.py
- Interfaces: SecurityArtifactMigration@1
- Conflict policy: Add one migration manifest and code; never delete or rewrite a legacy artifact, and never choose an ambiguous authority without an explicit reviewed decision.
- Preconditions: Read-only inventory and shared manifest contracts pass.
- Effects: Legacy identifiers and paths map to classified v1 artifact/run records with integrity checks.
- Evidence subset: legacy artifact migration integrity receipt
- Token class: large
- Estimated tokens: 8500
- Acceptance: Preserve every legacy hash/ID, identify source/golden/run/promoted/archive classes, flag unknown and transient files, separate deterministic from observational fields, and make migration idempotent and reversible.

## IRF-030 Harden Intent IR v1 schema and versioned decoding

- Status: completed
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: IRF-010, IRF-011, IRF-012
- Goal id: IRF-G060
- Outputs: ipfs_datasets_py/logic/intent_ir/schema.py, ipfs_datasets_py/logic/intent_ir/decoder.py, ipfs_datasets_py/logic/intent_ir/intent_ir.schema.json, tests/unit/logic/intent_ir/test_schema_versioning.py
- Validation: python -m pytest tests/unit/logic/intent_ir/test_schema.py tests/unit/logic/intent_ir/test_schema_versioning.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-schema
- Parallel lane: intent-schema
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/logic/intent_ir/schema.py, ipfs_datasets_py/logic/intent_ir/decoder.py, ipfs_datasets_py/logic/intent_ir/intent_ir.schema.json, tests/unit/logic/intent_ir/test_schema_versioning.py
- Interfaces: IntentIR@1
- Conflict policy: Own the existing schema and new versioning artifacts; do not edit source adapters, package exports, GraphRAG, or formalizer files.
- Preconditions: Shared identity, provenance, and schema-registry contracts pass.
- Effects: The v0.1 scaffold gains an exact v1 decoder, migration behavior, JSON Schema, explicit collection semantics, and extension policy.
- Evidence subset: Intent IR schema/migration receipt
- Token class: large
- Estimated tokens: 9000
- Acceptance: Preserve current source-grounded concepts; reject unknown versions and references; distinguish grounded versus inferred nodes; declare ordered and set-like collections; add canonical vectors, migration loss diagnostics, and immutable decode tests.

## IRF-031 Implement pinned SkillCenter snapshots and offline cache

- Status: todo
- Completion: manual
- Priority: P0
- Track: data
- Depends on: IRF-014
- Goal id: IRF-G050
- Outputs: ipfs_datasets_py/logic/intent_ir/source_adapters/snapshot.py, tests/unit/logic/intent_ir/test_skillcenter_snapshot.py
- Validation: python -m pytest tests/unit/logic/intent_ir/test_skillcenter_snapshot.py tests/unit/logic/intent_ir/test_skillcenter_source.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-ingestion
- Parallel lane: skillcenter-snapshot
- Resource class: io-artifact
- Predicted files: ipfs_datasets_py/logic/intent_ir/source_adapters/snapshot.py, tests/unit/logic/intent_ir/test_skillcenter_snapshot.py
- Interfaces: SkillCenterSnapshot@1
- Conflict policy: Add downloader/cache orchestration only; do not change the existing SQLite reader or commit downloaded bundles.
- Preconditions: Shared artifact manifest is available.
- Effects: Dataset revision, repository file, size, hash, CID, cache path, and download producer are bound in a resumable snapshot manifest.
- Evidence subset: pinned snapshot and tamper-detection receipt
- Token class: medium
- Estimated tokens: 7000
- Acceptance: Reject mutable `main`, hash/size mismatch, partial files, path traversal, and stale cache aliases; support an injected offline fetcher; use atomic promotion; record the inspected pilot revision without making network access a unit-test requirement.

## IRF-032 Enforce SkillCenter license and hostile-content policy

- Status: todo
- Completion: manual
- Priority: P0
- Track: privacy
- Depends on: IRF-011, IRF-031
- Goal id: IRF-G050
- Outputs: ipfs_datasets_py/logic/intent_ir/source_adapters/policy.py, tests/unit/logic/intent_ir/test_skillcenter_policy.py
- Validation: python -m pytest tests/unit/logic/intent_ir/test_skillcenter_policy.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-ingestion
- Parallel lane: skillcenter-policy
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/logic/intent_ir/source_adapters/policy.py, tests/unit/logic/intent_ir/test_skillcenter_policy.py
- Interfaces: SkillSourcePolicy@1
- Conflict policy: Own policy and fixtures only; do not execute, rewrite, or silently sanitize skill content.
- Preconditions: Snapshot and provenance contracts exist.
- Effects: Every source record receives an explicit license, trust, secret/PII, hostile-input, and allowed-use decision.
- Evidence subset: source-policy adversarial receipt
- Token class: medium
- Estimated tokens: 6500
- Acceptance: Define allow-train/publish, internal-evaluation, metadata-only, quarantined-unknown, and excluded decisions; fail closed on unknown/contradictory licenses; detect representative secrets, personal data, prompt injection, tool directives, and unsafe metadata without treating text as instructions.

## IRF-033 Normalize SkillCenter records into grounded Intent IR

- Status: todo
- Completion: manual
- Priority: P0
- Track: data
- Depends on: IRF-030, IRF-032
- Goal id: IRF-G060
- Outputs: ipfs_datasets_py/logic/intent_ir/normalize/skill.py, tests/unit/logic/intent_ir/test_normalize_skill.py
- Validation: python -m pytest tests/unit/logic/intent_ir/test_normalize_skill.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-semantics
- Parallel lane: intent-normalizer
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/intent_ir/normalize/skill.py, tests/unit/logic/intent_ir/test_normalize_skill.py
- Interfaces: IntentNormalizer@1
- Conflict policy: Own normalizer and test only; no GraphRAG, model runtime, shell execution, or package-export edits.
- Preconditions: Intent v1 schema and source policy pass.
- Effects: Bounded source records become validated goals, modalities, conditions, actions, effects, failures, verification criteria, and control flow with exact grounding.
- Evidence subset: normalization grounding and ambiguity receipt
- Token class: large
- Estimated tokens: 10000
- Acceptance: Provide a deterministic structural baseline and an injectable untrusted model-candidate interface; validate every candidate; preserve ambiguity/unsupported diagnostics; never allow retrieved/source text to modify instructions, assumptions, trust, license, or provenance.

## IRF-034 Build the corpus-evidence GraphRAG ontology and projector

- Status: todo
- Completion: manual
- Priority: P0
- Track: graphrag
- Depends on: IRF-011, IRF-031, IRF-032
- Goal id: IRF-G060
- Outputs: ipfs_datasets_py/logic/intent_ir/graphrag/ontology.py, ipfs_datasets_py/logic/intent_ir/graphrag/corpus_projector.py, tests/unit/logic/intent_ir/graphrag/test_corpus_projector.py
- Validation: python -m pytest tests/unit/logic/intent_ir/graphrag/test_corpus_projector.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-graph
- Parallel lane: corpus-graph
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/intent_ir/graphrag/ontology.py, ipfs_datasets_py/logic/intent_ir/graphrag/corpus_projector.py, tests/unit/logic/intent_ir/graphrag/test_corpus_projector.py
- Interfaces: IntentCorpusGraph@1
- Conflict policy: Own ontology and corpus projector; wrap stable existing storage/GraphRAG primitives and do not edit their monolithic implementations.
- Preconditions: Snapshot, source policy, and provenance contracts pass.
- Effects: Bundles, skills, source documents/spans, repositories, licenses, domains, mentions, citations, and duplicate/source-family relationships form a deterministic evidence graph.
- Evidence subset: corpus graph ontology/provenance receipt
- Token class: large
- Estimated tokens: 9000
- Acceptance: Version node/edge vocabulary; bind every node and edge to source and graph digests; use current IPLD storage adapters rather than deprecated `knowledge_graphs/ipld.py`; keep source bodies and embeddings separately addressed.

## IRF-035 Project validated Intent IR into a semantic graph

- Status: todo
- Completion: manual
- Priority: P0
- Track: graphrag
- Depends on: IRF-033, IRF-034
- Goal id: IRF-G060
- Outputs: ipfs_datasets_py/logic/intent_ir/graphrag/semantic_projector.py, tests/unit/logic/intent_ir/graphrag/test_semantic_projector.py
- Validation: python -m pytest tests/unit/logic/intent_ir/graphrag/test_semantic_projector.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-graph
- Parallel lane: semantic-graph
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/intent_ir/graphrag/semantic_projector.py, tests/unit/logic/intent_ir/graphrag/test_semantic_projector.py
- Interfaces: SemanticIntentGraph@1
- Conflict policy: Own semantic projector and test; consume but do not edit ontology, schema, normalizer, or storage internals.
- Preconditions: Validated Intent IR and corpus graph exist.
- Effects: Goals, statements, actions, tools, inputs, outputs, failures, verification, and control edges project into a digest-bound semantic graph.
- Evidence subset: semantic graph conformance receipt
- Token class: medium
- Estimated tokens: 7000
- Acceptance: Reject ungrounded or dangling projections; distinguish semantic edges from similarity edges; preserve modalities and control-edge kinds; deterministic rebuilds yield the same graph artifact identity.

## IRF-036 Add a bounded two-bundle SkillCenter pilot

- Status: todo
- Completion: manual
- Priority: P1
- Track: data
- Depends on: IRF-031, IRF-032, IRF-033, IRF-034, IRF-035
- Goal id: IRF-G050
- Outputs: ipfs_datasets_py/logic/intent_ir/source_adapters/pilot.py, tests/fixtures/intent_ir/skillcenter/manifest.json, tests/integration/logic/intent_ir/test_pilot_ingest.py
- Validation: python -m pytest tests/integration/logic/intent_ir/test_pilot_ingest.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-ingestion
- Parallel lane: skillcenter-pilot
- Resource class: io-artifact
- Predicted files: ipfs_datasets_py/logic/intent_ir/source_adapters/pilot.py, tests/fixtures/intent_ir/skillcenter/manifest.json, tests/integration/logic/intent_ir/test_pilot_ingest.py
- Interfaces: SkillCenterPilot@1
- Conflict policy: Commit only tiny synthetic/metadata fixtures and manifest hashes; store downloaded SQLite, graphs, embeddings, and run outputs in lane state, not Git.
- Preconditions: Snapshot, policy, normalizer, and both graph projectors pass.
- Effects: Security-lite and GitHub-lite profiles exercise rich generated metadata and thin community metadata under one reproducible pilot contract.
- Evidence subset: two-bundle pilot reproducibility receipt
- Token class: large
- Estimated tokens: 8500
- Acceptance: Start with bounded samples, then support the full two small bundles; record immutable revision and hashes; report counts, policy decisions, grounding, failures, time, and memory; prohibit expansion to GitHub-all until rollout gates pass.

## IRF-037 Add bounded GraphRAG retrieval and partition isolation

- Status: todo
- Completion: manual
- Priority: P1
- Track: graphrag
- Depends on: IRF-034, IRF-035
- Goal id: IRF-G060
- Outputs: ipfs_datasets_py/logic/intent_ir/graphrag/retrieval.py, tests/unit/logic/intent_ir/graphrag/test_retrieval.py
- Validation: python -m pytest tests/unit/logic/intent_ir/graphrag/test_retrieval.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-graph
- Parallel lane: intent-retrieval
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/intent_ir/graphrag/retrieval.py, tests/unit/logic/intent_ir/graphrag/test_retrieval.py
- Interfaces: IntentGraphRetriever@1
- Conflict policy: Own retrieval facade and test; do not edit ontology/projectors or high-level shared GraphRAG processors.
- Preconditions: Both graphs have versioned deterministic projections.
- Effects: Formalization can request bounded, provenance-preserving neighbors without crossing an evaluation partition.
- Evidence subset: retrieval bound and leakage-isolation receipt
- Token class: medium
- Estimated tokens: 6500
- Acceptance: Enforce fixed `k`, filters, byte/time budgets, source-family exclusions, graph snapshot binding, deterministic tie breaking, adversarial-neighbor isolation, and explicit empty/unsupported results; retrieved premises have no proof authority.

## IRF-040 Extract domain-neutral formalization contracts

- Status: completed
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: IRF-011, IRF-012, IRF-013
- Goal id: IRF-G070
- Outputs: ipfs_datasets_py/logic/formalization/samples.py, ipfs_datasets_py/logic/formalization/views.py, ipfs_datasets_py/logic/formalization/compiler.py, tests/unit/logic/formalization/test_contracts.py
- Validation: python -m pytest tests/unit/logic/formalization/test_contracts.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/formalization
- Parallel lane: formalization-contracts
- Resource class: cpu-proof-type-check
- Predicted files: ipfs_datasets_py/logic/formalization/samples.py, ipfs_datasets_py/logic/formalization/views.py, ipfs_datasets_py/logic/formalization/compiler.py, tests/unit/logic/formalization/test_contracts.py
- Interfaces: FormalizationSample@1, FormalizationArtifact@1
- Conflict policy: Add generic modules and tests; do not edit `LegalSample`, the large Legal modal autoencoder, package exports, or domain adapters.
- Preconditions: Shared provenance, schema, claim, and result contracts pass.
- Effects: Legal, Security, and Intent can provide samples and typed formal views without inheriting another domain's corpus validation.
- Evidence subset: formalization protocol conformance receipt
- Token class: large
- Estimated tokens: 9000
- Acceptance: Define source-grounded samples, symbol tables, view registry, formulas, cross-view links, unsupported diagnostics, proof obligations, compiler configuration, and artifact identity; retain compatible aliases as a later integration concern.

## IRF-041 Implement the deterministic Intent formalizer

- Status: todo
- Completion: manual
- Priority: P0
- Track: platform
- Depends on: IRF-033, IRF-035, IRF-037, IRF-040
- Goal id: IRF-G070
- Outputs: ipfs_datasets_py/logic/intent_ir/formalize/compiler.py, tests/unit/logic/intent_ir/formalize/test_compiler.py
- Validation: python -m pytest tests/unit/logic/intent_ir/formalize/test_compiler.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-formalization
- Parallel lane: intent-compiler
- Resource class: cpu-proof-type-check
- Predicted files: ipfs_datasets_py/logic/intent_ir/formalize/compiler.py, tests/unit/logic/intent_ir/formalize/test_compiler.py
- Interfaces: IntentFormalizationCompiler@1
- Conflict policy: Own deterministic Intent compiler and test only; no model inference, solver invocation, or shared-export edits.
- Preconditions: Intent IR, graph retrieval, and formalization contracts pass.
- Effects: Intent concepts lower into typed facts, intention/deontic, action/Hoare, workflow/temporal, invariant, failure, and verification views.
- Evidence subset: deterministic Intent formalization receipt
- Token class: large
- Estimated tokens: 11000
- Acceptance: Every formula maps to IR nodes and sources; assumptions and retrieved premises are explicit; unsupported semantics are retained as diagnostics; graph context is optional; repeated compilation is byte stable.

## IRF-042 Add Intent proof obligations and semantic decompilation

- Status: todo
- Completion: manual
- Priority: P1
- Track: quality
- Depends on: IRF-013, IRF-023, IRF-041
- Goal id: IRF-G070
- Outputs: ipfs_datasets_py/logic/intent_ir/formalize/obligations.py, ipfs_datasets_py/logic/intent_ir/formalize/decompiler.py, tests/unit/logic/intent_ir/formalize/test_round_trip.py
- Validation: python -m pytest tests/unit/logic/intent_ir/formalize/test_round_trip.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-formalization
- Parallel lane: intent-proof-roundtrip
- Resource class: cpu-proof-solver
- Predicted files: ipfs_datasets_py/logic/intent_ir/formalize/obligations.py, ipfs_datasets_py/logic/intent_ir/formalize/decompiler.py, tests/unit/logic/intent_ir/formalize/test_round_trip.py
- Interfaces: IntentProofObligations@1, IntentDecompiler@1
- Conflict policy: Own obligations/decompiler and test; consume backend interfaces without editing compilers or the deterministic formalizer.
- Preconditions: Backend registry and deterministic Intent artifacts exist.
- Effects: Safety, liveness, modality, control-flow, and verification obligations are explicit and formal views can be compared back to Intent semantics.
- Evidence subset: proof-obligation and semantic-round-trip receipt
- Token class: large
- Estimated tokens: 9500
- Acceptance: Generate bounded obligations with assumptions and authority policy; test positive, counterexample, unsupported, unavailable, and timeout paths; decompile for review and detect goal, modality, action-order, guard, effect, and source-grounding mutations.

## IRF-043 Adapt Legal IR to shared formalization contracts

- Status: todo
- Completion: manual
- Priority: P1
- Track: platform
- Depends on: IRF-040
- Goal id: IRF-G070
- Outputs: ipfs_datasets_py/logic/legal_ir/adapter.py, tests/unit/logic/legal_ir/test_formalization_adapter.py
- Validation: python -m pytest tests/unit/logic/legal_ir/test_formalization_adapter.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/formalization
- Parallel lane: legal-adapter
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/legal_ir/adapter.py, tests/unit/logic/legal_ir/test_formalization_adapter.py
- Interfaces: LegalIRFormalizationAdapter@1
- Conflict policy: Add an adapter and test only; do not move or edit the existing Legal compiler, samples, modal autoencoder, or exports.
- Preconditions: Generic formalization contracts pass.
- Effects: Existing Legal documents and modal artifacts can participate in cross-domain conformance without making US Code validation generic.
- Evidence subset: Legal adapter compatibility receipt
- Token class: medium
- Estimated tokens: 7000
- Acceptance: Map a reviewed Legal fixture losslessly enough for shared provenance/view contracts, retain Legal-only semantics and aliases, surface unsupported fields explicitly, and preserve existing Legal output identity.

## IRF-044 Adapt Security IR to shared formalization contracts

- Status: todo
- Completion: manual
- Priority: P1
- Track: platform
- Depends on: IRF-020, IRF-040
- Goal id: IRF-G070
- Outputs: ipfs_datasets_py/logic/security_ir/formalization_adapter.py, tests/unit/logic/security_ir/test_formalization_adapter.py
- Validation: python -m pytest tests/unit/logic/security_ir/test_formalization_adapter.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/formalization
- Parallel lane: security-formalization-adapter
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/security_ir/formalization_adapter.py, tests/unit/logic/security_ir/test_formalization_adapter.py
- Interfaces: SecurityIRFormalizationAdapter@1
- Conflict policy: Own adapter and test only; do not edit Security declarations, exchange/Xaman adapters, results, or exports.
- Preconditions: Security IR v1 and generic formalization contracts pass.
- Effects: Security declarations generate grounded formal samples and obligations independently of verification-run state.
- Evidence subset: Security formalization adapter receipt
- Token class: medium
- Estimated tokens: 7500
- Acceptance: Cover representative exchange and Xaman declarations; bind threats, policies, transitions, assumptions, and claims to sources; semantic mutations change expected obligations; result artifacts never become declaration features.

## IRF-050 Build source-free features and leakage-safe splits

- Status: todo
- Completion: manual
- Priority: P0
- Track: data
- Depends on: IRF-033, IRF-035, IRF-040
- Goal id: IRF-G080
- Outputs: ipfs_datasets_py/logic/formalization/features.py, ipfs_datasets_py/logic/intent_ir/formalize/features.py, ipfs_datasets_py/logic/intent_ir/evaluation/splits.py, tests/unit/logic/intent_ir/evaluation/test_splits_features.py
- Validation: python -m pytest tests/unit/logic/intent_ir/evaluation/test_splits_features.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-advisor
- Parallel lane: intent-features-splits
- Resource class: cpu-medium
- Predicted files: ipfs_datasets_py/logic/formalization/features.py, ipfs_datasets_py/logic/intent_ir/formalize/features.py, ipfs_datasets_py/logic/intent_ir/evaluation/splits.py, tests/unit/logic/intent_ir/evaluation/test_splits_features.py
- Interfaces: FormalizationFeatures@1, IntentSplitManifest@1
- Conflict policy: Own feature/split files and test; do not train a model, edit compilers, or store raw source text in feature artifacts.
- Preconditions: Intent normalization, semantic graph, and formalization contracts pass.
- Effects: Advisor inputs are versioned and evaluation groups primary sources, repositories, near-duplicates, and generation families.
- Evidence subset: source-free feature and zero-leak split receipt
- Token class: large
- Estimated tokens: 9000
- Acceptance: Exclude raw source bodies, split labels, result/proof leakage, and mutable graph state; keep all source variants in one partition; support held-out domain and time/revision splits; test adversarial duplicates and retrieval partition fences.

## IRF-051 Extract the generic formalization advisor core

- Status: todo
- Completion: manual
- Priority: P1
- Track: runtime
- Depends on: IRF-040, IRF-050
- Goal id: IRF-G080
- Outputs: ipfs_datasets_py/logic/formalization/advisor.py, ipfs_datasets_py/logic/formalization/checkpoints.py, tests/unit/logic/formalization/test_advisor.py
- Validation: python -m pytest tests/unit/logic/formalization/test_advisor.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/formalization-advisor
- Parallel lane: generic-advisor
- Resource class: llm-proof-draft
- Predicted files: ipfs_datasets_py/logic/formalization/advisor.py, ipfs_datasets_py/logic/formalization/checkpoints.py, tests/unit/logic/formalization/test_advisor.py
- Interfaces: FormalizationAdvisor@1, CheckpointManifest@1
- Conflict policy: Add protocols/wrappers and fake models; do not edit the existing Legal autoencoder or import Legal-specific sample validation.
- Preconditions: Generic formalization samples and source-free features exist.
- Effects: Learned systems can propose versioned formula candidates or bounded repairs with domain-separated checkpoints.
- Evidence subset: advisor authority-boundary and checkpoint receipt
- Token class: large
- Estimated tokens: 9500
- Acceptance: Freeze provenance, assumptions, modalities, trust, and license fields; bound candidate size and repair scope; type/schema check all output; record model/config/input identities; keep Legal, Security, and Intent heads/checkpoints namespaced.

## IRF-052 Implement Intent advisor heads and checkpoint policy

- Status: todo
- Completion: manual
- Priority: P1
- Track: runtime
- Depends on: IRF-041, IRF-050, IRF-051
- Goal id: IRF-G080
- Outputs: ipfs_datasets_py/logic/intent_ir/formalize/advisor.py, ipfs_datasets_py/logic/intent_ir/formalize/checkpoint_policy.py, tests/unit/logic/intent_ir/formalize/test_advisor.py
- Validation: python -m pytest tests/unit/logic/intent_ir/formalize/test_advisor.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-advisor
- Parallel lane: intent-advisor
- Resource class: llm-proof-draft
- Predicted files: ipfs_datasets_py/logic/intent_ir/formalize/advisor.py, ipfs_datasets_py/logic/intent_ir/formalize/checkpoint_policy.py, tests/unit/logic/intent_ir/formalize/test_advisor.py
- Interfaces: IntentFormalizationAdvisor@1
- Conflict policy: Own Intent advisor/policy and fake-model tests; no package exports, live network requirement, or shared autoencoder edits.
- Preconditions: Deterministic Intent compiler, features/splits, and generic advisor pass.
- Effects: Intent-specific views receive candidate-only learned assistance after deterministic compilation.
- Evidence subset: bounded Intent advisor repair receipt
- Token class: large
- Estimated tokens: 10000
- Acceptance: Compare no-advisor and candidate paths; reject source/provenance/modality/assumption mutation, unsupported view IDs, oversized output, invalid formula types, stale ontology/checkpoints, and attempts to claim proof or execution authority.

## IRF-053 Build paired formalization benchmarks

- Status: todo
- Completion: manual
- Priority: P1
- Track: quality
- Depends on: IRF-036, IRF-042, IRF-052
- Goal id: IRF-G080
- Outputs: ipfs_datasets_py/logic/intent_ir/evaluation/benchmark.py, tests/benchmarks/logic/test_intent_ir_benchmark.py
- Validation: python -m pytest tests/benchmarks/logic/test_intent_ir_benchmark.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/intent-evaluation
- Parallel lane: intent-benchmark
- Resource class: cpu-large
- Predicted files: ipfs_datasets_py/logic/intent_ir/evaluation/benchmark.py, tests/benchmarks/logic/test_intent_ir_benchmark.py
- Interfaces: IntentFormalizationBenchmark@1
- Conflict policy: Own benchmark implementation and deterministic fixture test; put large/live results in lane state and commit no model weights.
- Preconditions: Pilot, proof/round-trip, and Intent advisor paths pass.
- Effects: Deterministic-only, from-scratch Intent, and Legal-encoder-transfer variants can be compared on identical leak-free partitions.
- Evidence subset: paired held-out-source benchmark receipt
- Token class: large
- Estimated tokens: 10000
- Acceptance: Report grounding, schema/type, view accuracy, modality/control F1, proof-obligation closure, unsupported recall, semantic mutation, round trip, calibration, false-proof count, latency, memory, and cost; require zero leakage and authority violations.

## IRF-060 Add compatibility facades, package exports, and registry wiring

- Status: todo
- Completion: manual
- Priority: P1
- Track: platform
- Depends on: IRF-021, IRF-022, IRF-024, IRF-025, IRF-030, IRF-043, IRF-044
- Goal id: IRF-G090
- Outputs: ipfs_datasets_py/logic/ir_core/__init__.py, ipfs_datasets_py/logic/formalization/__init__.py, ipfs_datasets_py/logic/legal_ir/__init__.py, ipfs_datasets_py/logic/security_ir/__init__.py, ipfs_datasets_py/logic/intent_ir/__init__.py, ipfs_datasets_py/logic/security_models/crypto_exchange/__init__.py, ipfs_datasets_py/logic/submodule_registry.py, tests/integration/logic/test_ir_compatibility_exports.py
- Validation: python -m pytest tests/integration/logic/test_ir_compatibility_exports.py tests/unit/logic/security_models/crypto_exchange/test_public_api_freeze.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/integration
- Parallel lane: integration-exports
- Resource class: cpu-small
- Predicted files: ipfs_datasets_py/logic/ir_core/__init__.py, ipfs_datasets_py/logic/formalization/__init__.py, ipfs_datasets_py/logic/legal_ir/__init__.py, ipfs_datasets_py/logic/security_ir/__init__.py, ipfs_datasets_py/logic/intent_ir/__init__.py, ipfs_datasets_py/logic/security_models/crypto_exchange/__init__.py, ipfs_datasets_py/logic/submodule_registry.py, tests/integration/logic/test_ir_compatibility_exports.py
- Interfaces: IRFamilyExports@1
- Conflict policy: This is the sole task allowed to edit shared package `__init__.py`, legacy Security exports, and `logic/submodule_registry.py`; run only after dependency interfaces freeze.
- Preconditions: Domain adapters, result authority, migration, and shared formalization adapters pass.
- Effects: Reviewed new APIs are discoverable and legacy imports remain compatible with explicit deprecation metadata.
- Evidence subset: shared export and legacy import compatibility receipt
- Token class: large
- Estimated tokens: 9500
- Acceptance: Export only stable reviewed contracts; avoid import cycles and optional-runtime imports; preserve frozen legacy behavior and registry symbols; add deterministic deprecation warnings where appropriate; do not remove shims.

## IRF-061 Add cross-domain conformance and offline Intent end-to-end tests

- Status: todo
- Completion: manual
- Priority: P1
- Track: quality
- Depends on: IRF-036, IRF-042, IRF-043, IRF-044, IRF-052, IRF-060
- Goal id: IRF-G090
- Outputs: tests/integration/logic/test_ir_family_conformance.py, tests/integration/logic/test_intent_ir_pipeline.py
- Validation: python -m pytest tests/integration/logic/test_ir_family_conformance.py tests/integration/logic/test_intent_ir_pipeline.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/integration
- Parallel lane: integration-conformance
- Resource class: cpu-validation
- Predicted files: tests/integration/logic/test_ir_family_conformance.py, tests/integration/logic/test_intent_ir_pipeline.py
- Interfaces: IRFamilyConformance@1, IntentIRPipeline@1
- Conflict policy: Add integration tests only; do not repair implementation by weakening assertions or editing production files in this task.
- Preconditions: Exports and all three domain formalization adapters pass.
- Effects: One fixture suite validates shared contracts and the complete offline SkillCenter-record-to-receipt lineage.
- Evidence subset: cross-domain conformance and offline pipeline receipt
- Token class: large
- Estimated tokens: 9000
- Acceptance: Cover immutable identity, provenance, schema/migration, adapters, result authority, semantic mutation, unavailable backends, source policy, both graphs, deterministic formalization, candidate isolation, proof receipts, artifact lineage, and non-execution of source commands.

## IRF-062 Publish migration, operations, benchmark, and rollout gates

- Status: todo
- Completion: manual
- Priority: P2
- Track: ops
- Depends on: IRF-053, IRF-061
- Goal id: IRF-G090
- Outputs: docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md, docs/guides/IR_FAMILY_OPERATIONS.md, docs/security_verification/SECURITY_IR_MIGRATION.md, tests/integration/logic/test_ir_rollout_contract.py
- Validation: python -m pytest tests/integration/logic/test_ir_rollout_contract.py -q
- Board namespace: ir-family-refactor-intent-ir-v1
- Bundle: ir-family/rollout
- Parallel lane: integration-rollout
- Resource class: cpu-validation
- Predicted files: docs/architecture/IR_FAMILY_REFACTOR_AND_INTENT_IR_PLAN.md, docs/guides/IR_FAMILY_OPERATIONS.md, docs/security_verification/SECURITY_IR_MIGRATION.md, tests/integration/logic/test_ir_rollout_contract.py
- Interfaces: IRFamilyRollout@1
- Conflict policy: Own final plan/runbooks and rollout-contract test; do not remove legacy shims, enable auto-safe model authority, or commit generated run artifacts.
- Preconditions: Paired benchmark and integration conformance pass.
- Effects: Maintainers receive exact supervisor, snapshot, GraphRAG, formalization, verification, migration, rollback, and incident procedures.
- Evidence subset: reviewed rollout-gate and rollback receipt
- Token class: medium
- Estimated tokens: 7500
- Acceptance: Define off/shadow/assist/canary stages, license approval, snapshot pinning, solver capability, source-group split, benchmark thresholds, zero false-proof/authority-violation gates, artifact promotion, Security deprecation window, monitoring, rollback, and explicit decisions requiring human approval.
