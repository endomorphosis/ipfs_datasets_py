# Patent Legal Intelligence Supervisor Task Board

This reviewed board is the executable projection of
[`patent_legal_intelligence.objectives.md`](patent_legal_intelligence.objectives.md)
and the
[`USPTO Submission Assurance and Patent Legal Intelligence Plan`](PATENT_LEGAL_INTELLIGENCE_PLAN.md).

Program invariants:

- Board namespace: `patent-legal-intelligence-v1`.
- Merge target: `feature/patent-legal-intelligence`.
- Public ODP and authorized private import are separate providers/trust zones.
- Never automate Patent Center login/MFA, sign, pay, file, or expose private
  artifacts to public IPFS, public datasets, prompts, logs, or telemetry.
- Missing/unsupported/failed legal checks yield `unknown` and review, never a
  vacuous pass.
- Every task owns only its listed outputs while concurrent. Shared package
  exports, CLI/MCP registries, and final integration belong to `PATLAW-060` or
  a later dependent task.
- The plan, objective heap, this board, supervisor config, validator, launcher,
  and status tool are protected operator inputs and must not be task outputs.
- A task is complete only after its validation passes in its implementation
  worktree and the shared merge train records a successful target integration.

## PATLAW-002 Decide and test the canonical processor contract

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: processor-runtime
- Depends on:
- Goal id: PATLAW-G011
- Outputs: docs/architecture/PATENT_LEGAL_PROCESSOR_PROTOCOL_ADR.md, tests/unit/processors/core/test_protocol_unification.py, tests/integration/processors/test_public_processor_surface.py
- Validation: python -m pytest tests/unit/processors/core/test_protocol_unification.py tests/integration/processors/test_public_processor_surface.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/runtime
- Parallel lane: patlaw-runtime
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 9000
- Predicted files: docs/architecture/PATENT_LEGAL_PROCESSOR_PROTOCOL_ADR.md, tests/unit/processors/core/test_protocol_unification.py, tests/integration/processors/test_public_processor_surface.py
- Allow concurrent with: PATLAW-004, PATLAW-005, PATLAW-006, PATLAW-011
- Conflict policy: Own the protocol ADR and contract tests only; do not change PDF, USPTO, legal-analysis, or source modules.
- Preconditions: Audit both existing processor protocols and all public import surfaces.
- Effects: Declare `processors/core/protocol.py` ProcessingContext/can_handle semantics canonical; specify explicit legacy adaptation and result conversion; add executable conformance tests.
- Acceptance: ADR inventories incompatible behaviors and names one canonical runtime; tests fail for implicit mixed routing and define compatibility behavior without deleting supported public imports.

## PATLAW-003 Consolidate the registry and UniversalProcessor routing

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: processor-runtime
- Depends on: PATLAW-002
- Goal id: PATLAW-G011
- Outputs: ipfs_datasets_py/processors/core/registry.py, ipfs_datasets_py/processors/core/universal_processor.py, ipfs_datasets_py/processors/core/processor_registry.py, ipfs_datasets_py/processors/adapters/legacy_protocol_adapter.py, tests/unit/processors/core/test_canonical_registry.py, tests/integration/processors/test_universal_processor_routing.py
- Validation: python -m pytest tests/unit/processors/core/test_canonical_registry.py tests/integration/processors/test_universal_processor_routing.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/runtime
- Parallel lane: patlaw-runtime
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/processors/core/registry.py, ipfs_datasets_py/processors/core/universal_processor.py, ipfs_datasets_py/processors/core/processor_registry.py, ipfs_datasets_py/processors/adapters/legacy_protocol_adapter.py, tests/unit/processors/core/test_canonical_registry.py, tests/integration/processors/test_universal_processor_routing.py
- Allow concurrent with: PATLAW-004, PATLAW-005, PATLAW-006, PATLAW-011
- Conflict policy: Own core registry/universal routing and the explicit legacy adapter; root compatibility shims may change only when the ADR requires them.
- Preconditions: PATLAW-002 is merged and its conformance tests define the contract.
- Effects: Route registration, discovery, capability checks, execution, and result conversion through one registry; deprecate duplicate registry behavior explicitly.
- Acceptance: No runtime-checkable/isinstance failure; a legacy adapter and a core processor both route deterministically; no silent empty processor set; existing supported imports have tested behavior.

## PATLAW-004 Repair OCR, page coverage, text merge, and disclosure behavior

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: document-foundation
- Depends on:
- Goal id: PATLAW-G012
- Outputs: ipfs_datasets_py/processors/specialized/pdf/text_layer_merge.py, ipfs_datasets_py/processors/specialized/pdf/pdf_processor.py, ipfs_datasets_py/processors/specialized/pdf/ocr_engine.py, tests/unit/processors/specialized/pdf/test_text_layer_merge.py, tests/integration/processors/test_scanned_legal_pdf_pipeline.py, tests/security/test_private_pdf_non_disclosure.py, tests/fixtures/uspto/pdf
- Validation: python -m pytest tests/unit/processors/specialized/pdf/test_text_layer_merge.py tests/integration/processors/test_scanned_legal_pdf_pipeline.py tests/security/test_private_pdf_non_disclosure.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/pdf
- Parallel lane: patlaw-pdf
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/specialized/pdf/text_layer_merge.py, ipfs_datasets_py/processors/specialized/pdf/pdf_processor.py, ipfs_datasets_py/processors/specialized/pdf/ocr_engine.py, tests/unit/processors/specialized/pdf/test_text_layer_merge.py, tests/integration/processors/test_scanned_legal_pdf_pipeline.py, tests/security/test_private_pdf_non_disclosure.py, tests/fixtures/uspto/pdf
- Allow concurrent with: PATLAW-002, PATLAW-005, PATLAW-006, PATLAW-011
- Conflict policy: Own generic specialized PDF implementation and synthetic PDF fixtures; do not add USPTO semantics or edit adapters/core.
- Preconditions: Reproduce sync/async OCR, embedded-image-only OCR, quality-score, and content-disclosure defects with synthetic fixtures.
- Effects: OCR rendered pages when native coverage is low; attempt only available engines; merge native/rendered/embedded-image text with page/bounding-box origin; remove stdout/debug/full-content disclosures.
- Acceptance: Rotated and scanned pages have coverage/provenance; unavailable OCR and low confidence are explicit; missing OCR is not scored as high confidence; document content is absent from stdout, ordinary logs, telemetry, and working-directory debug files.

## PATLAW-005 Make legal and form verification fail closed

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: assurance-foundation
- Depends on:
- Goal id: PATLAW-G013
- Outputs: ipfs_datasets_py/processors/form_requirements_verifier.py, ipfs_datasets_py/processors/legal_data/neurosymbolic.py, tests/unit/processors/test_patent_compliance_fail_closed.py
- Validation: python -m pytest tests/unit/processors/test_patent_compliance_fail_closed.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/analysis-foundation
- Parallel lane: patlaw-analysis
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 9000
- Predicted files: ipfs_datasets_py/processors/form_requirements_verifier.py, ipfs_datasets_py/processors/legal_data/neurosymbolic.py, tests/unit/processors/test_patent_compliance_fail_closed.py
- Allow concurrent with: PATLAW-002, PATLAW-004, PATLAW-006, PATLAW-011
- Conflict policy: Narrowly repair result aggregation and proof-status semantics; do not add patent-specific requirements in generic court/form code.
- Preconditions: Add regressions for empty requirements, no evidence, skipped proof, unsupported semantics, timeout, and prover error.
- Effects: Introduce explicit unknown/review outcomes and prevent overall success unless all mandatory checks execute and succeed with evidence.
- Acceptance: Every absent/unsupported/skipped/errored case yields unknown or review_required; no empty input can produce `overall_pass=True`; existing supported satisfied/failed behavior remains compatible.

## PATLAW-006 Define USPTO contracts, artifact manifests, and privacy policy

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: uspto-foundation
- Depends on:
- Goal id: PATLAW-G013
- Outputs: ipfs_datasets_py/processors/domains/uspto/contracts.py, ipfs_datasets_py/processors/domains/uspto/privacy.py, ipfs_datasets_py/processors/domains/uspto/artifact_manifest.py, tests/unit/processors/domains/uspto/test_contracts.py, tests/security/test_uspto_public_private_isolation.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_contracts.py tests/security/test_uspto_public_private_isolation.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/uspto-foundation
- Parallel lane: patlaw-uspto
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/contracts.py, ipfs_datasets_py/processors/domains/uspto/privacy.py, ipfs_datasets_py/processors/domains/uspto/artifact_manifest.py, tests/unit/processors/domains/uspto/test_contracts.py, tests/security/test_uspto_public_private_isolation.py
- Allow concurrent with: PATLAW-002, PATLAW-004, PATLAW-005, PATLAW-011
- Conflict policy: Own new USPTO value contracts/privacy hooks only; do not create shared package exports or provider implementations.
- Preconditions: Use immutable/versioned records and enumerate public, confidential, privileged, export-review, and prohibited classifications.
- Effects: Define source receipts, artifact/span/requirement/fact/assessment/date/bundle records; classify before dispatch; deny private artifacts to public sinks and external prompts by default.
- Acceptance: Contracts round-trip deterministically; unknown classification quarantines; tests prove private bytes, text, embeddings, and CIDs cannot enter public IPFS, public datasets, caches, prompts, logs, or telemetry; credentials vault is not used as a document vault.

## PATLAW-007 Connect the generic adapter to the real PDF pipeline

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: document-foundation
- Depends on: PATLAW-003, PATLAW-004
- Goal id: PATLAW-G012
- Outputs: ipfs_datasets_py/processors/adapters/pdf_adapter.py, tests/unit/processors/adapters/test_pdf_adapter_real_pipeline.py
- Validation: python -m pytest tests/unit/processors/adapters/test_pdf_adapter_real_pipeline.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/runtime
- Parallel lane: patlaw-runtime
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 7000
- Predicted files: ipfs_datasets_py/processors/adapters/pdf_adapter.py, tests/unit/processors/adapters/test_pdf_adapter_real_pipeline.py
- Allow concurrent with: PATLAW-005, PATLAW-006, PATLAW-011
- Conflict policy: Own only the generic PDF adapter and its focused tests; consume the canonical registry and specialized PDF interfaces without redesigning them.
- Preconditions: PATLAW-003 and PATLAW-004 are merged; real PDF results expose page/text/layout/provenance and partial/error status.
- Effects: Remove placeholder output and delegate through the real processor; convert its result to the canonical runtime contract without dropping warnings/provenance.
- Acceptance: Adapter output contains actual fixture text and page provenance; placeholder strings are impossible; partial and error states propagate; private content is not logged.

## PATLAW-008 Prove the Phase 0 processor foundation end to end

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: foundation-integration
- Depends on: PATLAW-005, PATLAW-006, PATLAW-007
- Goal id: PATLAW-G010
- Outputs: tests/integration/processors/test_uspto_processor_foundation.py
- Validation: python -m pytest tests/integration/processors/test_uspto_processor_foundation.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/integration
- Parallel lane: patlaw-integration
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 7000
- Predicted files: tests/integration/processors/test_uspto_processor_foundation.py
- Allow concurrent with: PATLAW-012, PATLAW-013, PATLAW-014, PATLAW-015
- Conflict policy: Integration test only; repair failures in owning modules through a follow-up task, not broad opportunistic edits.
- Preconditions: Canonical routing, real PDF extraction, fail-closed aggregation, and USPTO classification/private boundary are merged.
- Effects: Route a synthetic confidential scanned office action through classification and real PDF extraction into a deliberately incomplete legal check.
- Acceptance: One canonical processor path runs; page/span provenance survives; result is unknown/review rather than pass; no confidential fixture content reaches a forbidden sink.

## PATLAW-011 Define the patent authority source and receipt registry

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: source-acquisition
- Depends on:
- Goal id: PATLAW-G021
- Outputs: ipfs_datasets_py/processors/legal_data/patent_authority_sources.py, tests/unit/processors/legal_data/test_patent_authority_sources.py
- Validation: python -m pytest tests/unit/processors/legal_data/test_patent_authority_sources.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/authority
- Parallel lane: patlaw-authority
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 8000
- Predicted files: ipfs_datasets_py/processors/legal_data/patent_authority_sources.py, tests/unit/processors/legal_data/test_patent_authority_sources.py
- Allow concurrent with: PATLAW-002, PATLAW-004, PATLAW-005, PATLAW-006
- Conflict policy: Own the reusable source/authority/receipt contract; do not implement connector network calls or USPTO matter providers.
- Preconditions: Inventory existing U.S. Code/Federal Register scraper contracts and the provenance model from PATLAW-006 without importing USPTO-specific types.
- Effects: Define official-base, official-change, unofficial-current, guidance, and candidate tiers plus version/effective/retrieval/signature fields and common retry/cache behavior.
- Acceptance: Registry rejects hard-coded “latest” editions and missing authority tier; fixtures serialize deterministically; connectors can preserve both official artifact and derived presentation identities.

## PATLAW-012 Implement current and historical Title 37 CFR acquisition

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: source-acquisition
- Depends on: PATLAW-011
- Goal id: PATLAW-G021
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/ecfr_crosscheck_processor.py, ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/cfr_annual_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_cfr_patent_sources.py, tests/fixtures/legal_data/patent_authorities/cfr
- Validation: python -m pytest tests/unit/processors/legal_scrapers/federal_scrapers/test_cfr_patent_sources.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/authority-cfr
- Parallel lane: patlaw-authority
- Resource class: network-small
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/ecfr_crosscheck_processor.py, ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/cfr_annual_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_cfr_patent_sources.py, tests/fixtures/legal_data/patent_authorities/cfr
- Allow concurrent with: PATLAW-013, PATLAW-014, PATLAW-015, PATLAW-008
- Conflict policy: Own only eCFR/annual CFR connector modules and CFR fixtures; consume the shared source contract unchanged.
- Preconditions: PATLAW-011 is merged; use recorded fixtures in tests and keep live network tests opt-in.
- Effects: Fetch Title 37 structure/full XML/version history by date and official annual GovInfo artifacts; retain `up_to_date_as_of`, amendment/effective metadata, hashes, and authority labels.
- Acceptance: Current and historical fixtures replay; eCFR is labeled unofficial presentation; annual official artifact identity remains separate; pagination/retry/429/schema failures are typed.

## PATLAW-013 Implement Title 35 U.S. Code release-point acquisition

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: source-acquisition
- Depends on: PATLAW-011
- Goal id: PATLAW-G021
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/uscode_release_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_uscode_patent_source.py, tests/fixtures/legal_data/patent_authorities/uscode
- Validation: python -m pytest tests/unit/processors/legal_scrapers/federal_scrapers/test_uscode_patent_source.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/authority-usc
- Parallel lane: patlaw-authority
- Resource class: network-small
- Token class: medium
- Estimated tokens: 10000
- Predicted files: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/uscode_release_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_uscode_patent_source.py, tests/fixtures/legal_data/patent_authorities/uscode
- Allow concurrent with: PATLAW-012, PATLAW-014, PATLAW-015, PATLAW-008
- Conflict policy: Own OLRC/GovInfo release-point connector and Title 35 fixtures; do not alter shared federal scraper exports.
- Preconditions: PATLAW-011 is merged; inventory existing US Code scraper for reuse and preserve exact release-point exceptions.
- Effects: Acquire USLM/XML/PDF metadata and source receipts for Title 35; expose uncodified/slip-law classification gaps instead of pretending the current codification is complete.
- Acceptance: Exact release point and exclusions are recorded; 35 USC 122 and 181–188 fixtures resolve; source format differences do not change stable section identity; missing release data yields unknown.

## PATLAW-014 Implement Federal Register discovery and GovInfo verification

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: source-acquisition
- Depends on: PATLAW-011
- Goal id: PATLAW-G021
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/govinfo_client.py, ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/federal_register_change_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_patent_rule_changes.py, tests/fixtures/legal_data/patent_authorities/federal_register
- Validation: python -m pytest tests/unit/processors/legal_scrapers/federal_scrapers/test_patent_rule_changes.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/authority-fr
- Parallel lane: patlaw-authority
- Resource class: network-small
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/govinfo_client.py, ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/federal_register_change_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_patent_rule_changes.py, tests/fixtures/legal_data/patent_authorities/federal_register
- Allow concurrent with: PATLAW-012, PATLAW-013, PATLAW-015, PATLAW-008
- Conflict policy: Own GovInfo client and patent-rule change connector; reuse existing Federal Register scraper behavior without changing unrelated legal corpora.
- Preconditions: PATLAW-011 is merged; tests use recorded unofficial discovery plus official GovInfo artifact fixtures.
- Effects: Discover USPTO rules/notices and capture proposed/final/interim/correction/withdrawal/delay events; bind official PDF/XML/package/granule metadata and signature result when available.
- Acceptance: Unofficial API text never masquerades as official edition; proposed and withdrawn rules remain nonbinding; effective/compliance dates and corrections survive replay; retry/schema/signature failures are explicit.

## PATLAW-015 Ingest versioned MPEP, forms, fees, and later guidance

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: source-acquisition
- Depends on: PATLAW-011
- Goal id: PATLAW-G021
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/mpep_guidance_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_mpep_guidance_source.py, tests/fixtures/legal_data/patent_authorities/guidance
- Validation: python -m pytest tests/unit/processors/legal_scrapers/federal_scrapers/test_mpep_guidance_source.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/authority-guidance
- Parallel lane: patlaw-authority
- Resource class: network-small
- Token class: medium
- Estimated tokens: 10000
- Predicted files: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/mpep_guidance_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_mpep_guidance_source.py, tests/fixtures/legal_data/patent_authorities/guidance
- Allow concurrent with: PATLAW-012, PATLAW-013, PATLAW-014, PATLAW-008
- Conflict policy: Own guidance connector/fixtures only; do not label guidance as binding or edit shared package exports.
- Preconditions: PATLAW-011 is merged; record MPEP edition/revision/cutoff and separately listed post-cutoff publications.
- Effects: Acquire section/form-paragraph anchors, forms, fee schedules, examination guidance, and later publications as lower-tier versioned artifacts.
- Acceptance: Guidance tier/cutoff is visible in every record; later guidance can supersede inconsistent manual text without elevating either to law; unavailable or changed documents yield explicit freshness gaps.

## PATLAW-016 Build the patent temporal authority graph and as-of resolver

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: authority-resolution
- Depends on: PATLAW-012, PATLAW-013, PATLAW-014, PATLAW-015, PATLAW-018
- Goal id: PATLAW-G022
- Outputs: ipfs_datasets_py/processors/legal_data/patent_authority_registry.py, tests/unit/processors/legal_data/test_patent_temporal_authority.py, tests/integration/legal_data/test_patent_authority_temporal_replay.py
- Validation: python -m pytest tests/unit/processors/legal_data/test_patent_temporal_authority.py tests/integration/legal_data/test_patent_authority_temporal_replay.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/authority-resolution
- Parallel lane: patlaw-authority
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/processors/legal_data/patent_authority_registry.py, tests/unit/processors/legal_data/test_patent_temporal_authority.py, tests/integration/legal_data/test_patent_authority_temporal_replay.py
- Allow concurrent with: PATLAW-022, PATLAW-023, PATLAW-024
- Conflict policy: Own temporal authority registry only; connector modules are inputs and must not be changed in this task.
- Preconditions: All four source connector tasks are merged with pinned fixtures.
- Effects: Materialize authority tier and amendment/supersession/correction/withdrawal/stay/effective edges; resolve exact mailing-date and response-date views.
- Acceptance: Historical replay is deterministic; proposed/future/withdrawn text is excluded unless explicitly requested; conflicts and missing intervals return unknown with competing sources; official and derived views remain separate.

## PATLAW-017 Resolve and validate patent-law citations and quotations

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: authority-resolution
- Depends on: PATLAW-016
- Goal id: PATLAW-G022
- Outputs: ipfs_datasets_py/processors/legal_data/patent_citation_resolver.py, tests/unit/processors/legal_data/test_patent_citation_resolver.py
- Validation: python -m pytest tests/unit/processors/legal_data/test_patent_citation_resolver.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/authority-resolution
- Parallel lane: patlaw-authority
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/processors/legal_data/patent_citation_resolver.py, tests/unit/processors/legal_data/test_patent_citation_resolver.py
- Allow concurrent with: PATLAW-025, PATLAW-030, PATLAW-031
- Conflict policy: Own patent citation resolution/quote validation only; extend existing citation extraction through composition, not broad rewrites.
- Preconditions: PATLAW-016 exposes as-of source spans and authority tiers.
- Effects: Parse/resolve 35 USC, 37 CFR, Federal Register, MPEP, form-paragraph, form, fee, and Examination Guide references; compare quoted text to the exact temporal source.
- Acceptance: Exact and ambiguous citations have typed results; quote mismatch exposes both spans; unresolved version or source never becomes verified; authority tier is independent of relevance/confidence.

## PATLAW-020 Normalize patent application identity and matter events

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: public-uspto
- Depends on: PATLAW-006
- Goal id: PATLAW-G031
- Outputs: ipfs_datasets_py/processors/domains/uspto/identifiers.py, ipfs_datasets_py/processors/domains/uspto/matter_events.py, tests/unit/processors/domains/uspto/test_identifiers.py, tests/unit/processors/domains/uspto/test_matter_events.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_identifiers.py tests/unit/processors/domains/uspto/test_matter_events.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/uspto-model
- Parallel lane: patlaw-uspto
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 9000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/identifiers.py, ipfs_datasets_py/processors/domains/uspto/matter_events.py, tests/unit/processors/domains/uspto/test_identifiers.py, tests/unit/processors/domains/uspto/test_matter_events.py
- Allow concurrent with: PATLAW-003, PATLAW-004, PATLAW-011
- Conflict policy: Own identifier and event value modules only; no provider network or shared exports.
- Preconditions: PATLAW-006 immutable contracts and classification types are merged.
- Effects: Parse and normalize application/publication/patent/confirmation/customer identifiers without conflation; model filing, status, transaction, document, response, appeal, abandonment, allowance, and grant events without lossy flags.
- Acceptance: Ambiguous/invalid identifiers are rejected or returned unresolved; formatting round-trips; event ordering preserves source time and retrieval time; application status is not reduced to a single rejected flag.

## PATLAW-021 Implement the ODP Patent File Wrapper client

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: public-uspto
- Depends on: PATLAW-006, PATLAW-020
- Goal id: PATLAW-G031
- Outputs: ipfs_datasets_py/processors/domains/uspto/providers/base.py, ipfs_datasets_py/processors/domains/uspto/providers/patent_file_wrapper.py, tests/unit/processors/domains/uspto/providers/test_patent_file_wrapper.py, tests/fixtures/uspto/odp/http
- Validation: python -m pytest tests/unit/processors/domains/uspto/providers/test_patent_file_wrapper.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/uspto-public-provider
- Parallel lane: patlaw-uspto
- Resource class: network-small
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/providers/base.py, ipfs_datasets_py/processors/domains/uspto/providers/patent_file_wrapper.py, tests/unit/processors/domains/uspto/providers/test_patent_file_wrapper.py, tests/fixtures/uspto/odp/http
- Allow concurrent with: PATLAW-012, PATLAW-013, PATLAW-014, PATLAW-015
- Conflict policy: Own the ODP provider and recorded HTTP fixtures; no authenticated Patent Center or UI code and no shared exports.
- Preconditions: Use current `https://api.uspto.gov` and `X-Api-Key` contract from official docs; inject endpoint/key/transport/rate policy; never put keys in receipts.
- Effects: Implement sanitized requests, pagination, bounded retries/jitter, Retry-After, circuit breaker, conditional caching, response/schema validation, and resumable page checkpoints.
- Acceptance: Recorded 200/401/403/404/429/5xx, pagination, malformed/schema-drift, cancellation, and retry-budget cases have typed results; no rate constant is invented; secrets never reach errors/logs/artifacts.

## PATLAW-022 Process public application status and transactions

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: public-uspto
- Depends on: PATLAW-021
- Goal id: PATLAW-G031
- Outputs: ipfs_datasets_py/processors/domains/uspto/application_status_processor.py, tests/unit/processors/domains/uspto/test_application_status_processor.py, tests/integration/processors/domains/uspto/test_public_status_sync.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_application_status_processor.py tests/integration/processors/domains/uspto/test_public_status_sync.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/uspto-status
- Parallel lane: patlaw-uspto
- Resource class: network-small
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/application_status_processor.py, tests/unit/processors/domains/uspto/test_application_status_processor.py, tests/integration/processors/domains/uspto/test_public_status_sync.py
- Allow concurrent with: PATLAW-023, PATLAW-024, PATLAW-016
- Conflict policy: Own status/transaction normalization only; provider transport and document downloader are inputs.
- Preconditions: PATLAW-021 provider and PATLAW-020 identities/events are merged.
- Effects: Fetch and normalize front-page/application/status/transaction data while retaining raw upstream fields, source receipt, freshness, and unknown status codes.
- Acceptance: Public-access limitations are explicit; status/event snapshots are versioned; unknown codes are preserved; stale or missing API data is not reported as proof of filing/nonreceipt; repeated sync is idempotent.

## PATLAW-023 Synchronize public file-wrapper document metadata and bytes

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: public-uspto
- Depends on: PATLAW-021
- Goal id: PATLAW-G031
- Outputs: ipfs_datasets_py/processors/domains/uspto/document_sync_processor.py, tests/unit/processors/domains/uspto/test_document_sync_processor.py, tests/fixtures/uspto/odp/documents
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_document_sync_processor.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/uspto-doc-sync
- Parallel lane: patlaw-uspto
- Resource class: network-medium
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/document_sync_processor.py, tests/unit/processors/domains/uspto/test_document_sync_processor.py, tests/fixtures/uspto/odp/documents
- Allow concurrent with: PATLAW-022, PATLAW-024, PATLAW-016
- Conflict policy: Own document metadata/download/checkpoint logic and ODP document fixtures; no semantic parsing.
- Preconditions: PATLAW-021 provider and PATLAW-006 artifact manifest are merged.
- Effects: Compare metadata/upstream update markers before downloading; stream to bounded quarantine, verify media/hash/size, classify, and store immutable versions; checkpoint each artifact.
- Acceptance: Same source ID+hash deduplicates; changed bytes create a version; partial downloads never become admitted artifacts; unavailable NPL/private documents are explicit; delayed inventory is a freshness gap, not nonreceipt.

## PATLAW-024 Import authorized Patent Center exports into encrypted storage

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: private-uspto
- Depends on: PATLAW-006, PATLAW-020
- Goal id: PATLAW-G032
- Outputs: ipfs_datasets_py/processors/domains/uspto/providers/patent_center_export.py, ipfs_datasets_py/processors/domains/uspto/private_store.py, tests/unit/processors/domains/uspto/providers/test_patent_center_export.py, tests/security/test_uspto_private_import.py, tests/fixtures/uspto/private_import
- Validation: python -m pytest tests/unit/processors/domains/uspto/providers/test_patent_center_export.py tests/security/test_uspto_private_import.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/uspto-private-import
- Parallel lane: patlaw-uspto
- Resource class: io-medium
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/providers/patent_center_export.py, ipfs_datasets_py/processors/domains/uspto/private_store.py, tests/unit/processors/domains/uspto/providers/test_patent_center_export.py, tests/security/test_uspto_private_import.py, tests/fixtures/uspto/private_import
- Allow concurrent with: PATLAW-022, PATLAW-023, PATLAW-016
- Conflict policy: Own local authorized-import/private-store modules and synthetic fixtures; do not access browsers, network login, shared credentials, or public sinks.
- Preconditions: PATLAW-006 privacy contract and PATLAW-020 identity normalization are merged; use a pluggable encryption backend and synthetic material only.
- Effects: Validate explicit manifest/import root, reject symlink/path/archive escape and prohibited content, classify, encrypt before durable storage, and record authorization/source receipt.
- Acceptance: No Patent Center scraping/MFA/session code exists; credentials/payment-card material is rejected; wrong tenant/key cannot read content; import is restartable/idempotent; private artifact/text/CID never leaves authorized storage.

## PATLAW-025 Reconcile originals, converted files, receipts, status, and versions

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: matter-ledger
- Depends on: PATLAW-022, PATLAW-023, PATLAW-024
- Goal id: PATLAW-G032
- Outputs: ipfs_datasets_py/processors/domains/uspto/matter_ledger.py, tests/unit/processors/domains/uspto/test_matter_ledger.py, tests/integration/processors/domains/uspto/test_matter_sync.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_matter_ledger.py tests/integration/processors/domains/uspto/test_matter_sync.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/uspto-ledger
- Parallel lane: patlaw-uspto
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/matter_ledger.py, tests/unit/processors/domains/uspto/test_matter_ledger.py, tests/integration/processors/domains/uspto/test_matter_sync.py
- Allow concurrent with: PATLAW-017, PATLAW-030, PATLAW-031
- Conflict policy: Own matter-ledger reconciliation only; providers, raw artifacts, and parsers are immutable inputs.
- Preconditions: Public status/doc sync and private import are merged with original/derived/receipt relationship metadata.
- Effects: Reconcile original DOCX, converted PDF, GUI/export metadata, acknowledgement/payment receipts, file-wrapper inventory, status/events, amendments, and current claim-set versions.
- Acceptance: Conflicts and missing/delayed items remain explicit; authoritative original versus derivative is preserved; wrong matter identifiers are quarantined; replay yields the same ledger and never overwrites history.

## PATLAW-030 Classify USPTO artifacts and authoritative relationships

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: document-extraction
- Depends on: PATLAW-007, PATLAW-020
- Goal id: PATLAW-G041
- Outputs: ipfs_datasets_py/processors/domains/uspto/document_classifier.py, tests/unit/processors/domains/uspto/test_document_classifier.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_document_classifier.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/document-classification
- Parallel lane: patlaw-analysis
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 9000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/document_classifier.py, tests/unit/processors/domains/uspto/test_document_classifier.py
- Allow concurrent with: PATLAW-017, PATLAW-025
- Conflict policy: Own USPTO artifact classification only; generic media detection and privacy policy are inputs.
- Preconditions: Real PDF adapter and identifier/event types are merged.
- Effects: Classify office actions, notices, submissions, DOCX/PDF conversions, declarations, forms, acknowledgements, payment receipts, citations, and unknown artifacts; link authoritative/derivative/supplemental roles.
- Acceptance: Classification includes confidence/reasons/source; conflicting MIME/description/content or wrong matter ID yields quarantine/review; unknown artifacts are retained and not silently ignored.

## PATLAW-031 Extract PDF, DOCX, layout, and filing metadata with provenance

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: document-extraction
- Depends on: PATLAW-007, PATLAW-030
- Goal id: PATLAW-G041
- Outputs: ipfs_datasets_py/processors/domains/uspto/document_extraction_processor.py, tests/unit/processors/domains/uspto/test_document_extraction.py, tests/fixtures/uspto/documents
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_document_extraction.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/document-extraction
- Parallel lane: patlaw-analysis
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/document_extraction_processor.py, tests/unit/processors/domains/uspto/test_document_extraction.py, tests/fixtures/uspto/documents
- Allow concurrent with: PATLAW-025, PATLAW-017
- Conflict policy: Own domain extraction orchestration and synthetic documents; generic PDF internals and semantic analyzers are out of scope.
- Preconditions: Classifier and real PDF pipeline are merged; define bounded untrusted-document execution.
- Effects: Extract native/rendered/OCR page spans, layout, tables/forms/annotations/checkmarks/stamps/signature-presence, DOCX structure, and metadata; compare authoritative DOCX to converted PDF.
- Acceptance: Every page and extracted item has artifact/page/character/bounding-box provenance; differences and unsupported features are explicit; corrupt/password/oversize/archive cases are bounded; low coverage yields review.

## PATLAW-032 Parse office actions and government instructions

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: patent-document-semantics
- Depends on: PATLAW-031
- Goal id: PATLAW-G042
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/office_action_processor.py, tests/unit/processors/domains/uspto/analysis/test_office_action_processor.py, tests/fixtures/uspto/office_actions
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_office_action_processor.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/office-action-analysis
- Parallel lane: patlaw-analysis
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/office_action_processor.py, tests/unit/processors/domains/uspto/analysis/test_office_action_processor.py, tests/fixtures/uspto/office_actions
- Allow concurrent with: PATLAW-033, PATLAW-034
- Conflict policy: Own office-action semantics and fixtures; no submission parsing, authority resolution, or shared exports.
- Preconditions: PATLAW-031 returns validated spans; reuse citation extraction for candidates without asserting authority.
- Effects: Section office actions/notices; extract claim ranges, objections/rejections, cited references, form paragraphs, fees/forms, informalities, response instructions, alternatives, exceptions, and uncompiled language.
- Acceptance: Every candidate points to exact spans; claim ranges and citations retain ambiguity; rescinded/reissued and malformed actions are represented; model candidates never enter verified layer without deterministic validation.

## PATLAW-033 Parse submissions, amendments, metadata, and receipts

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: patent-document-semantics
- Depends on: PATLAW-031
- Goal id: PATLAW-G042
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/submission_processor.py, tests/unit/processors/domains/uspto/analysis/test_submission_processor.py, tests/fixtures/uspto/submissions
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_submission_processor.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/submission-analysis
- Parallel lane: patlaw-analysis
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/submission_processor.py, tests/unit/processors/domains/uspto/analysis/test_submission_processor.py, tests/fixtures/uspto/submissions
- Allow concurrent with: PATLAW-032, PATLAW-034
- Conflict policy: Own submission/receipt semantics and fixtures; no office-action or proof aggregation logic.
- Preconditions: PATLAW-031 returns DOCX/PDF/receipt spans and authoritative/derivative links.
- Effects: Extract claims, amendment instructions, remarks, declarations/forms, fee/signature presence, attachments, document descriptions, application metadata, acknowledgement identifiers, and payment receipt evidence.
- Acceptance: Original DOCX stays authoritative where applicable; extracted facts point to exact versions/spans; signature presence is never reusable signing data; missing/mismatched metadata/receipts and DOCX/PDF differences are explicit.

## PATLAW-034 Validate span coverage, readability, and extraction disagreements

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: document-extraction
- Depends on: PATLAW-031
- Goal id: PATLAW-G041
- Outputs: ipfs_datasets_py/processors/domains/uspto/span_validator.py, tests/unit/processors/domains/uspto/test_span_validator.py, tests/integration/processors/domains/uspto/test_span_provenance.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_span_validator.py tests/integration/processors/domains/uspto/test_span_provenance.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/span-assurance
- Parallel lane: patlaw-analysis
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 9000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/span_validator.py, tests/unit/processors/domains/uspto/test_span_validator.py, tests/integration/processors/domains/uspto/test_span_provenance.py
- Allow concurrent with: PATLAW-032, PATLAW-033
- Conflict policy: Own provenance/coverage validation only; do not reinterpret document semantics.
- Preconditions: PATLAW-031 emits page coverage, native/OCR origins, render hashes, and bounding boxes.
- Effects: Verify span bounds/source hashes, page coverage, reading order, native/OCR discrepancies, quote round-trip, and minimum readability/coverage policy.
- Acceptance: Invalid/stale spans and unaccounted pages fail validation; disagreement is retained; low readability creates unknown/review; no semantic result can cite a missing or mismatched artifact version.

## PATLAW-040 Compile government instructions into typed requirements

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: compliance-analysis
- Depends on: PATLAW-016, PATLAW-017, PATLAW-032
- Goal id: PATLAW-G051
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/requirement_processor.py, tests/unit/processors/domains/uspto/analysis/test_requirement_processor.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_requirement_processor.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/requirements
- Parallel lane: patlaw-analysis
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/requirement_processor.py, tests/unit/processors/domains/uspto/analysis/test_requirement_processor.py
- Allow concurrent with: PATLAW-041, PATLAW-043, PATLAW-044
- Conflict policy: Own typed requirement compilation only; authority and office-action records are immutable inputs.
- Preconditions: Exact office-action spans and as-of citation/authority resolver are merged.
- Effects: Compile conditional, alternative, conjunctive, disjunctive, claim-specific, form/fee, and document requirements with applicability, exceptions, legal source, proposed date rule, and unsupported clauses.
- Acceptance: Compiler never drops uncompiled text; every admitted predicate has an instruction span and resolved authority/applicability state; missing/ambiguous authority yields unknown; output is deterministic and versioned.

## PATLAW-041 Build submission facts and exact support/counter-evidence maps

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: compliance-analysis
- Depends on: PATLAW-033, PATLAW-034
- Goal id: PATLAW-G051
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/submission_evidence.py, tests/unit/processors/domains/uspto/analysis/test_submission_evidence.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_submission_evidence.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/submission-evidence
- Parallel lane: patlaw-analysis
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/submission_evidence.py, tests/unit/processors/domains/uspto/analysis/test_submission_evidence.py
- Allow concurrent with: PATLAW-040, PATLAW-043, PATLAW-044
- Conflict policy: Own submission fact admission and support-map integration only; no top-level compliance aggregation.
- Preconditions: Submission parser and span validator are merged; reuse SupportMap through a typed patent adapter.
- Effects: Admit validated submission facts, reconstruct affected claim/document versions, and map exact supporting and contradicting spans without treating summaries as evidence.
- Acceptance: Every fact/evidence edge round-trips to the correct artifact version/span; stale/invalid/ambiguous evidence is excluded with reason; empty submissions produce no implicit support.

## PATLAW-042 Implement fail-closed submission compliance analysis

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: compliance-analysis
- Depends on: PATLAW-005, PATLAW-040, PATLAW-041
- Goal id: PATLAW-G051
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/submission_compliance_processor.py, tests/unit/processors/domains/uspto/analysis/test_submission_compliance_processor.py, tests/integration/processors/domains/uspto/test_submission_compliance.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_submission_compliance_processor.py tests/integration/processors/domains/uspto/test_submission_compliance.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/compliance-engine
- Parallel lane: patlaw-analysis
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 18000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/submission_compliance_processor.py, tests/unit/processors/domains/uspto/analysis/test_submission_compliance_processor.py, tests/integration/processors/domains/uspto/test_submission_compliance.py
- Allow concurrent with: PATLAW-043, PATLAW-044
- Conflict policy: Own compliance orchestration/aggregation; consume fail-closed generic verifier, requirements, facts, SupportMap, and Legal IR without changing their owners.
- Preconditions: PATLAW-005, PATLAW-040, and PATLAW-041 are merged with explicit unknown states.
- Effects: Evaluate each requirement against exact evidence/counter-evidence and applicable authority; emit satisfied/unsatisfied/unknown/not_applicable plus proof execution receipts and reviewer action.
- Acceptance: No-requirement, no-evidence, unsupported, skipped, timeout, error, contradiction, and missing-authority fixtures fail closed; top-level result cannot pass with a mandatory unknown; explanations cite all source spans and versions.

## PATLAW-043 Map rejections, claims, statutory bases, and cited references

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: legal-explanation
- Depends on: PATLAW-017, PATLAW-032, PATLAW-034
- Goal id: PATLAW-G052
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/rejection_mapping_processor.py, tests/unit/processors/domains/uspto/analysis/test_rejection_mapping.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_rejection_mapping.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/rejection-analysis
- Parallel lane: patlaw-analysis
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/rejection_mapping_processor.py, tests/unit/processors/domains/uspto/analysis/test_rejection_mapping.py
- Allow concurrent with: PATLAW-040, PATLAW-041, PATLAW-044
- Conflict policy: Own rejection/claim/reference mapping only; no prior-art conclusion or broad patentability opinion.
- Preconditions: Office-action/citation spans and span validation are merged.
- Effects: Map 35 USC 101/102/103/112 and other stated bases to exact claims/limitations, examiner statements, cited references, and later disposition while preserving alternatives/ambiguity.
- Acceptance: Claim ranges and references are never guessed; rescinded/reissued/amended claim cases retain history; missing claim set yields unknown/review; output states it is an examiner-statement map, not a patentability determination.

## PATLAW-044 Calculate review-only response-date candidates

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-explanation
- Depends on: PATLAW-016, PATLAW-022, PATLAW-032
- Goal id: PATLAW-G052
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/deadline_processor.py, tests/unit/processors/domains/uspto/analysis/test_deadline_processor.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_deadline_processor.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/deadline-analysis
- Parallel lane: patlaw-analysis
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/deadline_processor.py, tests/unit/processors/domains/uspto/analysis/test_deadline_processor.py
- Allow concurrent with: PATLAW-040, PATLAW-041, PATLAW-043
- Conflict policy: Own candidate-date reasoning only; never write docket entries or make final deadline assertions.
- Preconditions: Status events, instruction spans, and temporal rule resolver are merged.
- Effects: Build candidate dates from mailing/notification event, rule chain, periods, weekends/holidays, time zone, entity/extension/fee assumptions, and exceptions; expose conflicts.
- Acceptance: Every candidate is labeled review-only with assumptions and source spans; missing facts or conflicting rules yield unknown/multiple candidates; named human confirmation is required before any docket export.

## PATLAW-045 Compare government instructions to applicable authority

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-explanation
- Depends on: PATLAW-017, PATLAW-040, PATLAW-042
- Goal id: PATLAW-G052
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/instruction_consistency_processor.py, tests/unit/processors/domains/uspto/analysis/test_instruction_consistency.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_instruction_consistency.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/instruction-analysis
- Parallel lane: patlaw-analysis
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/instruction_consistency_processor.py, tests/unit/processors/domains/uspto/analysis/test_instruction_consistency.py
- Allow concurrent with: PATLAW-043, PATLAW-044
- Conflict policy: Own instruction/authority comparison only; no conclusive legality label and no modification of source or proof records.
- Preconditions: Typed requirements, exact citation resolver, and fail-closed assessments are merged.
- Effects: Produce examiner/instruction span to exact temporal authority/applicability reasoning with consistent/potential_inconsistency/unknown and a human-review question.
- Acceptance: A potential inconsistency is reproducible from exact source spans/versions; competing authority and uncertainty are shown; model summary is never substituted for government or governing text; no output declares unlawful conduct.

## PATLAW-050 Orchestrate a versioned application dossier

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: workflow
- Depends on: PATLAW-025, PATLAW-034, PATLAW-042, PATLAW-043, PATLAW-044, PATLAW-045
- Goal id: PATLAW-G060
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/analysis_bundle.py, ipfs_datasets_py/processors/domains/uspto/dossier_processor.py, tests/unit/processors/domains/uspto/test_dossier_processor.py, tests/integration/processors/domains/uspto/test_dossier_workflow.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_dossier_processor.py tests/integration/processors/domains/uspto/test_dossier_workflow.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/workflow
- Parallel lane: patlaw-workflow
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 17000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/analysis_bundle.py, ipfs_datasets_py/processors/domains/uspto/dossier_processor.py, tests/unit/processors/domains/uspto/test_dossier_processor.py, tests/integration/processors/domains/uspto/test_dossier_workflow.py
- Allow concurrent with: PATLAW-070
- Conflict policy: Own immutable bundle/dossier orchestration only; source processors and analysis records are inputs and remain unchanged.
- Preconditions: Matter ledger, span validation, compliance, rejection, date, and instruction analyses are merged.
- Effects: Bind input artifact manifest, status/events, current claim set, instructions, requirements, submission evidence, assessments, authorities, candidate dates, warnings, versions, and validation receipts into one replayable dossier.
- Acceptance: Bundle digest changes for any material input/version; all facts and conclusions trace to artifacts/authority; unsupported and missing checks appear in warnings; private classification propagates to every derived record.

## PATLAW-051 Render the explainable requirement/evidence gap report

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: workflow
- Depends on: PATLAW-050
- Goal id: PATLAW-G060
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/gap_report.py, tests/unit/processors/domains/uspto/analysis/test_gap_report.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_gap_report.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/workflow
- Parallel lane: patlaw-workflow
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 9000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/gap_report.py, tests/unit/processors/domains/uspto/analysis/test_gap_report.py
- Allow concurrent with: PATLAW-070
- Conflict policy: Own deterministic report projection only; do not recompute hidden legal logic or edit dossier inputs.
- Preconditions: PATLAW-050 versioned dossier contract is merged.
- Effects: Render matter summary, artifact/receipt inventory, each government demand and authority, exact evidence/counter-evidence, status, gap, uncertainty, candidate date, and reviewer action in machine-readable and human-readable forms.
- Acceptance: Report round-trips to the same bundle; every statement exposes source links; unknowns are prominent; private text is redacted according to output policy; no “all clear” label appears when mandatory review remains.

## PATLAW-052 Implement the pre-submission workflow and mandatory human gate

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: workflow
- Depends on: PATLAW-051, PATLAW-095
- Goal id: PATLAW-G060
- Outputs: ipfs_datasets_py/processors/domains/uspto/workflow_processor.py, tests/unit/processors/domains/uspto/test_workflow_processor.py, tests/integration/processors/domains/uspto/test_submission_preflight.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_workflow_processor.py tests/integration/processors/domains/uspto/test_submission_preflight.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/workflow
- Parallel lane: patlaw-workflow
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/workflow_processor.py, tests/unit/processors/domains/uspto/test_workflow_processor.py, tests/integration/processors/domains/uspto/test_submission_preflight.py
- Allow concurrent with: PATLAW-060
- Conflict policy: Own preflight state machine and review receipt; no Patent Center browser, signature, payment, or filing action.
- Preconditions: Explainable gap report is merged and all unresolved states have typed reviewer actions.
- Effects: Run package preflight, require explicit resolution/acceptance of each unknown/gap/date, bind named human review to an immutable bundle digest, and allow export of a reviewed package manifest only.
- Acceptance: Workflow cannot sign/pay/file or mark itself submitted; changed inputs invalidate review; final filing remains external; acknowledgement/payment receipts are imported afterward as new evidence, never fabricated.

## PATLAW-060 Register processors and expose one Python/CLI API

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: product-integration
- Depends on: PATLAW-008, PATLAW-025, PATLAW-050, PATLAW-052, PATLAW-094, PATLAW-102
- Goal id: PATLAW-G070
- Outputs: ipfs_datasets_py/processors/domains/uspto/__init__.py, ipfs_datasets_py/processors/domains/uspto/providers/__init__.py, ipfs_datasets_py/processors/domains/uspto/analysis/__init__.py, ipfs_datasets_py/processors/domains/uspto/api.py, ipfs_datasets_py/processors/adapters/uspto_adapter.py, ipfs_datasets_py/cli/uspto.py, tests/unit/processors/domains/uspto/test_api.py, tests/cli/test_uspto_commands.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_api.py tests/cli/test_uspto_commands.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/integration
- Parallel lane: patlaw-integration
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 17000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/__init__.py, ipfs_datasets_py/processors/domains/uspto/providers/__init__.py, ipfs_datasets_py/processors/domains/uspto/analysis/__init__.py, ipfs_datasets_py/processors/domains/uspto/api.py, ipfs_datasets_py/processors/adapters/uspto_adapter.py, ipfs_datasets_py/cli/uspto.py, tests/unit/processors/domains/uspto/test_api.py, tests/cli/test_uspto_commands.py
- Allow concurrent with: PATLAW-052, PATLAW-070
- Conflict policy: Serialized owner of all new package exports/processor registration/CLI registration; do not redesign domain logic.
- Preconditions: Phase 0 route, matter ledger, and dossier are merged; inspect current CLI/registry conventions before edits.
- Effects: Register USPTO processors once through the canonical registry; expose typed status/sync/import/analyze/preflight/explain SDK and CLI operations with injected client/store/policy.
- Acceptance: Public imports and CLI help are stable; all surfaces return canonical contracts; credentials are references, not arguments/results; private import requires tenant/path/classification; no command signs, pays, files, or automates a browser.

## PATLAW-061 Add read-only USPTO MCP tools

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: product-integration
- Depends on: PATLAW-051, PATLAW-060
- Goal id: PATLAW-G070
- Outputs: ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/uspto_tools.py, tests/mcp/unit/test_uspto_tools.py
- Validation: python -m pytest tests/mcp/unit/test_uspto_tools.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/mcp
- Parallel lane: patlaw-integration
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 9000
- Predicted files: ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/uspto_tools.py, tests/mcp/unit/test_uspto_tools.py
- Allow concurrent with: PATLAW-062, PATLAW-071
- Conflict policy: Own one MCP tool module/test only; any shared MCP registry edit must be minimal and serialized after PATLAW-060.
- Preconditions: Typed API and explainable gap report are merged; inventory authorization/redaction conventions in existing legal dataset tools.
- Effects: Expose status, dossier summary, requirement matrix, evidence gaps, citation explanation, and analysis replay as read-only tools with tenant authorization.
- Acceptance: Tool schemas contain no sign/file/pay/session/credential operation; unauthorized/private cross-tenant access is denied; output redaction is policy-driven; tools call the canonical API rather than duplicate analysis.

## PATLAW-062 Add checkpointed polling, change detection, and alerts

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: operations
- Depends on: PATLAW-025, PATLAW-060
- Goal id: PATLAW-G070
- Outputs: ipfs_datasets_py/processors/domains/uspto/scheduler.py, tests/integration/processors/domains/uspto/test_scheduler.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_scheduler.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/scheduler
- Parallel lane: patlaw-integration
- Resource class: network-small
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/scheduler.py, tests/integration/processors/domains/uspto/test_scheduler.py
- Allow concurrent with: PATLAW-061, PATLAW-071
- Conflict policy: Own scheduler/change-alert module only; use canonical API/provider and do not edit shared supervisor code.
- Preconditions: Matter ledger and public API are merged; connector exposes typed auth/rate/outage status.
- Effects: Add bounded per-service/content queues, metadata-before-binary polling, checkpoints, dedupe/change detection, circuit breakers, delayed reschedule, dead-letter review, heartbeat/progress, and redacted alerts.
- Acceptance: Workers release capacity while waiting; 401/403 creates credential-health action, 429 respects Retry-After, repeated 5xx opens a circuit, parse/security failure dead-letters; restart resumes without duplicate alerts/artifacts.

## PATLAW-070 Build the reviewed synthetic/public gold corpus and metrics

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: release-assurance
- Depends on: PATLAW-006, PATLAW-011
- Goal id: PATLAW-G080
- Outputs: tests/fixtures/uspto/gold, tests/fixtures/uspto/GOLD_CORPUS_MANIFEST.json, tests/contract/processors/test_uspto_gold_corpus_contract.py
- Validation: python -m pytest tests/contract/processors/test_uspto_gold_corpus_contract.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/gold-corpus
- Parallel lane: patlaw-assurance
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 14000
- Predicted files: tests/fixtures/uspto/gold, tests/fixtures/uspto/GOLD_CORPUS_MANIFEST.json, tests/contract/processors/test_uspto_gold_corpus_contract.py
- Allow concurrent with: PATLAW-012, PATLAW-013, PATLAW-014, PATLAW-015, PATLAW-021
- Conflict policy: Own synthetic/approved-public gold corpus and manifest only; no private real applications or secrets in git.
- Preconditions: USPTO contracts/privacy and authority source tiers are merged; document every fixture license/source/synthetic recipe and expected spans/results.
- Effects: Add scanned/rotated/forms/tables, DOCX/PDF differences, receipts, wrong identifiers, amendments/current claims, rescinded/reissued actions, delayed docs, authority amendments/corrections, unknowns, and adversarial cases plus metric definitions.
- Acceptance: Manifest hashes every fixture and expected annotation; corpus contains no private/privileged data; requirements/citations/dates/provenance have reviewer-labeled truth; explicit recall/precision/provenance and false-negative gates are machine-readable.

## PATLAW-071 Harden privacy, export-review, and public-sink isolation

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: release-assurance
- Depends on: PATLAW-024, PATLAW-060, PATLAW-070
- Goal id: PATLAW-G080
- Outputs: ipfs_datasets_py/processors/domains/uspto/privacy_sinks.py, tests/security/test_uspto_assurance_boundary.py, tests/security/test_uspto_export_control_gate.py
- Validation: python -m pytest tests/security/test_uspto_assurance_boundary.py tests/security/test_uspto_export_control_gate.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/privacy-assurance
- Parallel lane: patlaw-assurance
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/privacy_sinks.py, tests/security/test_uspto_assurance_boundary.py, tests/security/test_uspto_export_control_gate.py
- Allow concurrent with: PATLAW-061, PATLAW-062, PATLAW-073
- Conflict policy: Own public-sink enforcement adapter and adversarial tests; do not broaden credential, filing, or network permissions.
- Preconditions: Private store, API/CLI, and gold corpus are merged; enumerate every IPFS/dataset/cache/model/log/telemetry sink reachable from processors.
- Effects: Enforce classification and tenant policy at all sinks; gate secrecy-order/export-review unknowns; test public DHT/gateway/pin, public datasets, embeddings, prompts, traces, caches, errors, and cross-tenant access.
- Acceptance: No private byte/text/embedding/CID reaches a forbidden sink under adversarial paths; unknown publication/export state quarantines; external-model use is denied by default; tests inspect outputs/logs/telemetry and not merely return codes.

## PATLAW-072 Prove deterministic offline end-to-end replay

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: release-assurance
- Depends on: PATLAW-052, PATLAW-061, PATLAW-062, PATLAW-070, PATLAW-071, PATLAW-102
- Goal id: PATLAW-G080
- Outputs: tests/e2e/test_uspto_application_analysis.py, tests/e2e/test_uspto_application_analysis_cli_mcp.py, tests/fixtures/uspto/replay
- Validation: python -m pytest tests/e2e/test_uspto_application_analysis.py tests/e2e/test_uspto_application_analysis_cli_mcp.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/e2e
- Parallel lane: patlaw-assurance
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 18000
- Predicted files: tests/e2e/test_uspto_application_analysis.py, tests/e2e/test_uspto_application_analysis_cli_mcp.py, tests/fixtures/uspto/replay
- Allow concurrent with: PATLAW-073
- Conflict policy: End-to-end tests/replay receipts only; repair discovered failures in narrowly scoped owner tasks rather than editing all modules here.
- Preconditions: Workflow, interfaces, scheduler, gold corpus, and privacy gates are merged.
- Effects: Replay public and synthetic private matters from immutable receipts through identity/status/import/extraction/requirements/evidence/authority/compliance/dossier/preflight and compare SDK/CLI/MCP results.
- Acceptance: Network-free replay is deterministic; output binds input/parser/model/ruleset/config/tree; all source spans resolve; unknowns remain unknown; private data isolation holds; no sign/file/pay capability is reachable.

## PATLAW-073 Add operator observability, stall detection, and recovery runbook

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: operations
- Depends on: PATLAW-062
- Goal id: PATLAW-G080
- Outputs: docs/operations/USPTO_SUBMISSION_ASSURANCE_RUNBOOK.md, scripts/ops/uspto/status.py, tests/integration/processors/domains/uspto/test_recovery_operations.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_recovery_operations.py -q && python scripts/ops/uspto/status.py --help >/dev/null
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/operations
- Parallel lane: patlaw-assurance
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 10000
- Predicted files: docs/operations/USPTO_SUBMISSION_ASSURANCE_RUNBOOK.md, scripts/ops/uspto/status.py, tests/integration/processors/domains/uspto/test_recovery_operations.py
- Allow concurrent with: PATLAW-071, PATLAW-072
- Conflict policy: Own domain runtime observability/runbook, not the protected implementation-supervisor launcher/status tool.
- Preconditions: Scheduler state/retry/circuit/dead-letter contracts are merged.
- Effects: Document and test auth expiry, rate backoff, outage, schema drift, corrupt document, private-policy incident, dead letter, stale checkpoint, replay, key rotation, and safe resumption; expose content-free health metrics.
- Acceptance: Operator can distinguish waiting, bounded backoff, active progress, stalled work, policy incident, and completed merge; recovery is idempotent/audited and never requires deleting evidence or exposing document content.

## PATLAW-074 Run the fresh current-tree completion and release gate

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: release-assurance
- Depends on: PATLAW-061, PATLAW-062, PATLAW-072, PATLAW-073, PATLAW-080, PATLAW-102
- Goal id: PATLAW-G080
- Outputs: scripts/ops/uspto/validate_release.py, tests/release/test_uspto_submission_assurance_release.py, data/release/uspto_submission_assurance/.gitkeep
- Validation: python -m pytest tests/release/test_uspto_submission_assurance_release.py -q && python scripts/ops/uspto/validate_release.py --offline
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/release-gate
- Parallel lane: patlaw-integration
- Resource class: cpu-large
- Token class: large
- Estimated tokens: 16000
- Predicted files: scripts/ops/uspto/validate_release.py, tests/release/test_uspto_submission_assurance_release.py, data/release/uspto_submission_assurance/.gitkeep
- Allow concurrent with:
- Conflict policy: Final evidence task only; no feature implementation except a narrowly justified gate repair after owner tests pass.
- Preconditions: All functional, interface, privacy, e2e, and operations tasks are merged to the target branch; working tree is clean.
- Effects: Run current-tree contract/unit/integration/security/e2e gates, validate gold metrics and no-disclosure evidence, inspect merge receipts, and write a content-free signed/digested validation receipt outside tracked source by default.
- Acceptance: Fresh receipt binds git tree, config, fixture/ruleset/parser versions, test results, privacy scan, and merge-queue evidence; target branch contains every prior task; no blocked/unknown mandatory release gate remains; task status alone cannot satisfy this acceptance.

## PATLAW-018 Verify GovInfo printed bases, Public Laws, and daily issue completeness

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: source-verification
- Depends on: PATLAW-012, PATLAW-013, PATLAW-014
- Goal id: PATLAW-G021
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/govinfo_official_verifier.py, ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/public_law_change_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_govinfo_official_verification.py, tests/fixtures/legal_data/patent_authorities/public_laws
- Validation: python -m pytest tests/unit/processors/legal_scrapers/federal_scrapers/test_govinfo_official_verification.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/authority-verification
- Parallel lane: patlaw-authority
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/govinfo_official_verifier.py, ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/public_law_change_processor.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_govinfo_official_verification.py, tests/fixtures/legal_data/patent_authorities/public_laws
- Allow concurrent with: PATLAW-022, PATLAW-023, PATLAW-024
- Conflict policy: Own official verification/Public Law modules and fixtures; do not rewrite the three source connectors, legacy scrapers, or temporal resolver.
- Preconditions: Annual CFR, U.S. Code release-point, and Federal Register connectors emit immutable artifacts and source receipts.
- Effects: Inventory all Title 37 volumes, latest available Title 35 edition, examined Public Law packages, and daily Federal Register granules; verify advertised PDF/XML/MODS/PREMIS fixity, source spans, GPO authentication evidence, and optional human print-page attestations.
- Acceptance: Latest editions are discovered at runtime; every examined Public Law remains in the manifest even when not patent-relevant; House/eCFR/FederalRegister.gov data stays cross-check-only; digital authentication and printed-volume attestation are separate; missing volumes/granules/signatures or text conflicts yield conflict/inconclusive/unverified rather than success.

## PATLAW-019 Repair canonical public-patent imports and legacy compatibility

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: public-patent-foundation
- Depends on: PATLAW-006
- Goal id: PATLAW-G031
- Outputs: ipfs_datasets_py/processors/domains/patent/models.py, ipfs_datasets_py/processors/legal_scrapers/patent_engine.py, ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/patent_engine.py, tests/unit/processors/patent/test_models.py, tests/unit/processors/patent/test_import_compatibility.py
- Validation: python -m pytest tests/unit/processors/patent/test_models.py tests/unit/processors/patent/test_import_compatibility.py tests/test_patent_scraper.py tests/mcp/unit/test_legacy_patent_tools.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/patent-contracts
- Parallel lane: patlaw-patent-public
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/processors/domains/patent/models.py, ipfs_datasets_py/processors/legal_scrapers/patent_engine.py, ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/patent_engine.py, tests/unit/processors/patent/test_models.py, tests/unit/processors/patent/test_import_compatibility.py
- Allow concurrent with: PATLAW-012, PATLAW-013, PATLAW-014, PATLAW-021
- Conflict policy: Retain implementations only under processors.domains.patent; compatibility modules are deprecated re-exports; do not change ODP transport, indexes, or shared package registries.
- Preconditions: USPTO disclosure/artifact contracts exist; audit the missing legal_scrapers.patent_engine lazy import and both drifting PatentsView class implementations.
- Effects: Define strict public patent/application/document/claim/prosecution/rejection/citation models and make all legacy engine paths resolve to one canonical class implementation.
- Acceptance: Baseline tests collect; identical content yields stable IDs independent of retrieval time/path/token/mutable URL; unknown disclosure fails closed; legacy classes have object identity and deprecation warnings; unit tests perform no live network calls.

## PATLAW-080 Add serialized datasets/accelerator upstream synchronization

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: operations
- Depends on: PATLAW-073
- Goal id: PATLAW-G080
- Outputs: scripts/ops/uspto/sync_upstreams.sh, scripts/ops/uspto/check_cross_repo_compatibility.py, tests/integration/processors/domains/uspto/test_cross_repo_sync.py, data/release/uspto_submission_assurance/compatibility_manifest.schema.json
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_cross_repo_sync.py -q && python scripts/ops/uspto/check_cross_repo_compatibility.py --offline
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/sync-operations
- Parallel lane: patlaw-assurance
- Resource class: io-git
- Token class: medium
- Estimated tokens: 10000
- Predicted files: scripts/ops/uspto/sync_upstreams.sh, scripts/ops/uspto/check_cross_repo_compatibility.py, tests/integration/processors/domains/uspto/test_cross_repo_sync.py, data/release/uspto_submission_assurance/compatibility_manifest.schema.json
- Allow concurrent with:
- Conflict policy: Tooling/tests use synthetic temporary repositories; never pull into active lanes, edit the protected supervisor launcher/board/config, update gitlinks recursively, or push.
- Preconditions: Recovery runbook and the cross-package validation surface are merged; lanes can checkpoint and stop new claims.
- Effects: Fetch both origins at startup/every eight hours, serialize twice-daily or release/security integrations on clean branches, test the exact datasets/accelerator SHA pair, atomically write a compatibility receipt, then permit lane resumption.
- Acceptance: Dirty or active work aborts without mutation; conflicts fail closed; no recursive mutual-submodule chase; accepted manifest binds both SHAs and test receipts; startup, eight-hour, twice-daily, pre-release, and security-fix triggers are explicit; no push occurs.

## PATLAW-090 Define source-linked BM25, vector, graph, and evaluation contracts

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: patent-retrieval
- Depends on:
- Goal id: PATLAW-G090
- Outputs: ipfs_datasets_py/processors/domains/patent/retrieval_contracts.py, ipfs_datasets_py/processors/domains/patent/evaluation.py, tests/unit/processors/patent/test_retrieval_contracts.py, tests/unit/processors/patent/test_retrieval_evaluation.py
- Validation: python -m pytest tests/unit/processors/patent/test_retrieval_contracts.py tests/unit/processors/patent/test_retrieval_evaluation.py tests/unit/processors/test_retrieval_primitives.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/retrieval-contracts
- Parallel lane: patlaw-patent-index
- Resource class: cpu-small
- Token class: medium
- Estimated tokens: 9000
- Predicted files: ipfs_datasets_py/processors/domains/patent/retrieval_contracts.py, ipfs_datasets_py/processors/domains/patent/evaluation.py, tests/unit/processors/patent/test_retrieval_contracts.py, tests/unit/processors/patent/test_retrieval_evaluation.py
- Allow concurrent with: PATLAW-002, PATLAW-004, PATLAW-005, PATLAW-006, PATLAW-011, PATLAW-100
- Conflict policy: New contract/evaluation modules only; do not edit existing vector stores, graph engine, patent package exports, or concrete builders.
- Preconditions: Inventory existing BM25/vector/graph primitives and preserve their public compatibility.
- Effects: Define source-linked index rows, field weights, embedding identity, graph ranks, pre-ranking filters, fusion results, qrels, and evaluation receipts.
- Acceptance: Metrics cover recall/ranking/citation/temporal/source coverage/private isolation; receipts bind corpus/model/config/qrels CIDs; generated summaries and candidate edges cannot claim source authority; disclosure/tenant/as-of filters are mandatory before scoring.

## PATLAW-091 Project the patent-law and prosecution knowledge graph

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: patent-retrieval
- Depends on: PATLAW-017, PATLAW-019, PATLAW-023, PATLAW-034
- Goal id: PATLAW-G090
- Outputs: ipfs_datasets_py/knowledge_graphs/adapters/patent.py, tests/unit/processors/patent/test_ontology.py, tests/fixtures/patent/graph/golden_prosecution_case.json
- Validation: python -m pytest tests/unit/processors/patent/test_ontology.py tests/unit/knowledge_graphs/test_graph_engine.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/patent-graph
- Parallel lane: patlaw-patent-index
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/knowledge_graphs/adapters/patent.py, tests/unit/processors/patent/test_ontology.py, tests/fixtures/patent/graph/golden_prosecution_case.json
- Allow concurrent with: PATLAW-040, PATLAW-041, PATLAW-044
- Conflict policy: Own patent graph adapter/ontology fixtures only; shared graph engine and source/event parsers are inputs and remain unchanged.
- Preconditions: Canonical public models, exact legal citations, synchronized documents, and validated extraction spans are merged.
- Effects: Project authority/edition/section/amendment/effective interval and family/application/publication/patent/claim/office action/rejection/response/citation/classification entities plus deterministic provenance-bound edges.
- Acceptance: Every endpoint exists and joins to source CID/span; projection is deterministic; priority/continuation/amendment/rejection/examiner/applicant/legal-authority edges preserve disclosure; LLM-proposed edges remain unverified candidates.

## PATLAW-092 Build fielded BM25, pinned vector, and graph-fusion indexes

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: patent-retrieval
- Depends on: PATLAW-006, PATLAW-018, PATLAW-023, PATLAW-034, PATLAW-090, PATLAW-091
- Goal id: PATLAW-G090
- Outputs: ipfs_datasets_py/processors/domains/patent/indexing.py, ipfs_datasets_py/processors/domains/patent/hybrid_retrieval.py, tests/unit/processors/patent/test_indexing.py, tests/integration/processors/patent/test_hybrid_retrieval.py, tests/fixtures/patent/retrieval/golden_case.json
- Validation: python -m pytest tests/unit/processors/patent/test_indexing.py tests/integration/processors/patent/test_hybrid_retrieval.py tests/unit/processors/test_retrieval_primitives.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/patent-index
- Parallel lane: patlaw-patent-index
- Resource class: cpu-large
- Token class: large
- Estimated tokens: 18000
- Predicted files: ipfs_datasets_py/processors/domains/patent/indexing.py, ipfs_datasets_py/processors/domains/patent/hybrid_retrieval.py, tests/unit/processors/patent/test_indexing.py, tests/integration/processors/patent/test_hybrid_retrieval.py, tests/fixtures/patent/retrieval/golden_case.json
- Allow concurrent with: PATLAW-043, PATLAW-044, PATLAW-045
- Conflict policy: Own concrete patent index/retrieval modules and fixture; consume existing embedding/vector/graph APIs without editing their engines or shared exports.
- Preconditions: Verified legal records, public patent documents/extractions, privacy contracts, retrieval contracts, and patent graph are merged.
- Effects: Chunk claims/legal sections/events atomically; build field-aware BM25 over title/abstract/claims/description/CPC/IPC/citations/numbers/legal bases, pinned embeddings, graph expansion, and measured three-way fusion.
- Acceptance: Legal/patent tokens survive; embedding provider/model/config recorded; every row/node/result joins to source CID; repeat builds identical; authority/as-of/disclosure/tenant filters run first; denied private routes make zero remote embedding calls.

## PATLAW-093 Evaluate retrieval quality, time, citations, and isolation

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: patent-retrieval
- Depends on: PATLAW-070, PATLAW-092
- Goal id: PATLAW-G090
- Outputs: ipfs_datasets_py/processors/domains/patent/retrieval_eval.py, tests/integration/processors/patent/test_retrieval_evaluation.py, tests/fixtures/patent/retrieval/qrels.json
- Validation: python -m pytest tests/integration/processors/patent/test_retrieval_evaluation.py tests/integration/processors/patent/test_hybrid_retrieval.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/retrieval-evaluation
- Parallel lane: patlaw-patent-index
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/processors/domains/patent/retrieval_eval.py, tests/integration/processors/patent/test_retrieval_evaluation.py, tests/fixtures/patent/retrieval/qrels.json
- Allow concurrent with: PATLAW-043, PATLAW-044, PATLAW-045
- Conflict policy: Own evaluation harness/qrels only; do not silently retune gold thresholds or edit builders.
- Preconditions: Reviewed gold corpus and all three index families are merged.
- Effects: Measure each retrieval family and fused ranking for recall, ranking, exact citation grounding, effective-time accuracy, source coverage, reproducibility, latency envelope, and private isolation.
- Acceptance: Versioned thresholds fail loudly on regression; receipt binds corpus/index/model/config/qrels CIDs; source/time errors are enumerated; isolation records denied provider-call counts.

## PATLAW-094 Produce reproducible prior-art plans and claim charts

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: patent-analysis
- Depends on: PATLAW-093
- Goal id: PATLAW-G090
- Outputs: ipfs_datasets_py/processors/domains/patent/prior_art.py, tests/unit/processors/patent/test_prior_art.py, tests/fixtures/patent/prior_art/golden_claim_chart.json
- Validation: python -m pytest tests/unit/processors/patent/test_prior_art.py tests/integration/processors/patent/test_retrieval_evaluation.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/prior-art
- Parallel lane: patlaw-patent-analysis
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/processors/domains/patent/prior_art.py, tests/unit/processors/patent/test_prior_art.py, tests/fixtures/patent/prior_art/golden_claim_chart.json
- Allow concurrent with: PATLAW-043, PATLAW-044, PATLAW-045, PATLAW-101
- Conflict policy: Own prior-art planner/report fixture; do not emit patentability opinions, auto-file an IDS, or reproduce unlicensed NPL text.
- Preconditions: Hybrid retrieval passes reviewed evaluation thresholds.
- Effects: Decompose claims into reviewable limitations, construct keyword/classification queries, search U.S. patents/published applications, expand citations/families, and record exact dated query logs, passages, ranks, cutoffs, and gaps.
- Acceptance: Filing/priority/search dates are explicit; every chart entry cites source CID/span; generated limitations/keywords are candidates; foreign-patent and NPL coverage gaps remain visible; no novelty/obviousness/patentability conclusion is made.

## PATLAW-095 Bind prior-art and current-rule review to filing preflight

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: patent-analysis
- Depends on: PATLAW-017, PATLAW-051, PATLAW-094
- Goal id: PATLAW-G090
- Outputs: ipfs_datasets_py/processors/domains/patent/rules.py, tests/unit/processors/patent/test_rules.py, tests/integration/processors/domains/uspto/test_prior_art_rule_checklist.py
- Validation: python -m pytest tests/unit/processors/patent/test_rules.py tests/integration/processors/domains/uspto/test_prior_art_rule_checklist.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/prior-art-rules
- Parallel lane: patlaw-patent-analysis
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/processors/domains/patent/rules.py, tests/unit/processors/patent/test_rules.py, tests/integration/processors/domains/uspto/test_prior_art_rule_checklist.py
- Allow concurrent with: PATLAW-043, PATLAW-044, PATLAW-045, PATLAW-101
- Conflict policy: Own prior-art/rule checklist integration; do not encode a permanent latest year, elevate guidance, decide legal strategy, sign, pay, file, or submit an IDS.
- Preconditions: Exact temporal citations, explainable dossier gaps, and prior-art chart are merged.
- Effects: Produce pass/fail/review/unknown checklist entries tied to official authority view/as-of/effective interval plus separately labelled forms/fees/guidance, and require human review of search scope before filing preflight.
- Acceptance: Conflicts/missing/stale sources block readiness; every item cites source/span/version/time; checklist is decision support, not advice; preflight cannot claim prior-art search complete without a dated report and explicit human coverage acknowledgment.

## PATLAW-100 Generalize the append-only Hugging Face publication profile

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: public-publication
- Depends on:
- Goal id: PATLAW-G100
- Outputs: ipfs_datasets_py/huggingface/publication_profile.py, ipfs_datasets_py/huggingface/publisher.py, tests/unit/huggingface/test_publication_profiles.py, tests/unit/huggingface/test_generic_publisher.py
- Validation: python -m pytest tests/unit/huggingface/test_publication_profiles.py tests/unit/huggingface/test_generic_publisher.py tests/unit/voice/test_abby_voice_hf_release.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/hf-publisher
- Parallel lane: patlaw-public-release
- Resource class: io-small
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/huggingface/publication_profile.py, ipfs_datasets_py/huggingface/publisher.py, tests/unit/huggingface/test_publication_profiles.py, tests/unit/huggingface/test_generic_publisher.py
- Allow concurrent with: PATLAW-002, PATLAW-004, PATLAW-005, PATLAW-006, PATLAW-011, PATLAW-090
- Conflict policy: Own generic publication profile/publisher tests; preserve byte/wire-compatible legacy publisher profiles; do not build patent shards or perform live uploads.
- Preconditions: Audit the existing append-only publisher and record unrelated baseline failures separately.
- Effects: Parameterize program/goal/schema/repository/release-prefix/pointer/revision/message while preserving add-only planning, approval digest, audited-parent race, verification, canary, rollback, and pinned re-download.
- Acceptance: Patent/legal profiles contain no unrelated program schema strings; legacy behavior remains compatible; dry run cannot call writes; no profile weakens prohibited operations; pointer promotion waits for pinned verification.

## PATLAW-101 Build deterministic, privacy-reviewed JusticeDAO artifacts

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: public-publication
- Depends on: PATLAW-006, PATLAW-018, PATLAW-023, PATLAW-091, PATLAW-092, PATLAW-100
- Goal id: PATLAW-G100
- Outputs: ipfs_datasets_py/processors/domains/patent/release_policy.py, ipfs_datasets_py/processors/domains/patent/hf_release.py, scripts/ops/legal_data/build_patent_hf_release.py, tests/unit/processors/patent/test_release_policy.py, tests/unit/processors/patent/test_hf_release.py
- Validation: python -m pytest tests/unit/processors/patent/test_release_policy.py tests/unit/processors/patent/test_hf_release.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/patent-release
- Parallel lane: patlaw-public-release
- Resource class: io-medium
- Token class: large
- Estimated tokens: 18000
- Predicted files: ipfs_datasets_py/processors/domains/patent/release_policy.py, ipfs_datasets_py/processors/domains/patent/hf_release.py, scripts/ops/legal_data/build_patent_hf_release.py, tests/unit/processors/patent/test_release_policy.py, tests/unit/processors/patent/test_hf_release.py
- Allow concurrent with: PATLAW-043, PATLAW-044, PATLAW-045, PATLAW-094, PATLAW-095
- Conflict policy: Own deterministic release builder/policy/script; no shared registry export or live upload; private/unlicensed inputs are rejected before staging.
- Preconditions: Official verified authorities, public patent documents/graph/indexes, privacy contracts, and generic publication profile are merged.
- Effects: Build configurable CFR/USC/Public Law/FR/projected rules and applications/claims/events/office-actions/citations/graph/BM25/vector-metadata shards with rights/privacy/source manifests.
- Acceptance: Two builds are byte-identical; every artifact has SHA-256/CID/row count/source lineage/classification/rights review; private/mixed input fails before staging; default stops at dry run; no direct HfApi.upload_file path is added.

## PATLAW-102 Verify JusticeDAO publication through the append-only publisher

- Status: todo
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: public-publication
- Depends on: PATLAW-093, PATLAW-101
- Goal id: PATLAW-G100
- Outputs: tests/integration/processors/patent/test_release_publisher.py, tests/fixtures/patent/release/manifest.json, scripts/ops/legal_data/verify_patent_hf_release.py
- Validation: python -m pytest tests/integration/processors/patent/test_release_publisher.py tests/unit/processors/patent/test_hf_release.py tests/unit/huggingface/test_generic_publisher.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/release-integration
- Parallel lane: patlaw-public-release
- Resource class: io-medium
- Token class: large
- Estimated tokens: 12000
- Predicted files: tests/integration/processors/patent/test_release_publisher.py, tests/fixtures/patent/release/manifest.json, scripts/ops/legal_data/verify_patent_hf_release.py
- Allow concurrent with: PATLAW-043, PATLAW-044, PATLAW-045, PATLAW-094, PATLAW-095
- Conflict policy: Own fake-service release integration and verifier; real publication requires a separate operator action approving the exact plan digest.
- Preconditions: Retrieval evaluation and deterministic release artifacts are merged.
- Effects: Exercise configurable JusticeDAO repositories through dry-run, exact approval, add-only publish, audited-parent race check, pinned re-download, canary, pointer promotion, and rollback.
- Acceptance: Fake live flow covers every gate; default is dry-run; repository names remain configurable; no pointer moves before pinned verification; supervisor tests have no real token/network and perform no live upload.
