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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: private-uspto
- Depends on: PATLAW-006, PATLAW-020
- Goal id: PATLAW-G032
- Outputs: ipfs_datasets_py/processors/domains/uspto/providers/patent_center_export.py, ipfs_datasets_py/processors/domains/uspto/private_store.py, tests/unit/processors/domains/uspto/providers/test_patent_center_export.py, tests/security/test_uspto_private_import.py, tests/fixtures/uspto/private_import
- Proposal artifact envelope: {"allow_archives":true,"allow_binary":true,"max_file_bytes":1048576,"max_output_bytes":2500000,"max_patch_bytes":2000000,"paths":["ipfs_datasets_py/processors/domains/uspto/private_store.py","ipfs_datasets_py/processors/domains/uspto/providers/patent_center_export.py","tests/fixtures/uspto/private_import/authorization.json","tests/fixtures/uspto/private_import/export_manifest.json","tests/fixtures/uspto/private_import/package/acknowledgement_receipt.txt","tests/fixtures/uspto/private_import/package/converted_specification.pdf","tests/fixtures/uspto/private_import/package/original_specification.docx","tests/fixtures/uspto/private_import/package/payment_receipt.txt","tests/fixtures/uspto/private_import/prohibited/credential_blob.txt","tests/fixtures/uspto/private_import/prohibited/payment_card_sample.txt","tests/security/test_uspto_private_import.py","tests/unit/processors/domains/uspto/providers/test_patent_center_export.py"],"schema":"ipfs_accelerate_py/agent-supervisor/task-artifact-envelope@3"}
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

- Status: completed
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

## PATLAW-110 Resolve validation retry-budget failure for PATLAW-019

- Status: completed
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: operations
- Depends on:
- Goal id: PATLAW-G080
- Outputs: data/agent_supervisor/patent_legal_intelligence/retry_repairs/PATLAW-019.json
- Validation: python -m pytest tests/unit/processors/patent/test_models.py tests/unit/processors/patent/test_import_compatibility.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/retry-repair
- Parallel lane: patlaw-operations
- Resource class: cpu-small
- Token class: small
- Estimated tokens: 1000
- Predicted files: data/agent_supervisor/patent_legal_intelligence/retry_repairs/PATLAW-019.json
- Allow concurrent with:
- Conflict policy: Release only the exhausted validation-attempt budget after the supervisor policy fix; do not alter task state files or claim implementation completion.
- Preconditions: The task-owned synthetic-canary policy and bounded failure-diagnostic fix are reviewed and tested.
- Effects: Record one board-visible retry-repair receipt so every lane clears only PATLAW-019's display/canonical attempt counters and queue cooldown.
- Generated by: ipfs_accelerate_py.agent_supervisor.retry-budget-repair@1
- Retry repair source: PATLAW-019
- Retry failure kind: validation
- Acceptance: The reviewed proposal-gate false positive is fixed and tested; release PATLAW-019 from strategy blocked_tasks without editing durable task state directly.

## PATLAW-111 Resolve validation retry-budget failure for PATLAW-022

- Status: completed
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: operations
- Depends on:
- Goal id: PATLAW-G080
- Outputs: data/agent_supervisor/patent_legal_intelligence/retry_repairs/PATLAW-022.json
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_application_status_processor.py tests/integration/processors/domains/uspto/test_public_status_sync.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/retry-repair
- Parallel lane: patlaw-operations
- Resource class: cpu-small
- Token class: small
- Estimated tokens: 1000
- Predicted files: data/agent_supervisor/patent_legal_intelligence/retry_repairs/PATLAW-022.json
- Allow concurrent with:
- Conflict policy: Release only the exhausted validation-attempt budget after the supervisor policy fix; do not alter task state files or claim implementation completion.
- Preconditions: The task-owned synthetic-canary policy and bounded failure-diagnostic fix are reviewed and tested.
- Effects: Record one board-visible retry-repair receipt so every lane clears only PATLAW-022's display/canonical attempt counters and queue cooldown.
- Generated by: ipfs_accelerate_py.agent_supervisor.retry-budget-repair@1
- Retry repair source: PATLAW-022
- Retry failure kind: validation
- Acceptance: The reviewed proposal-gate false positive is fixed and tested; release PATLAW-022 from strategy blocked_tasks without editing durable task state directly.

## PATLAW-112 Resolve validation retry-budget failure for PATLAW-024

- Status: completed
- Completion: manual
- Is schedulable: false
- Review only: true
- Priority: P0
- Track: operations
- Depends on:
- Goal id: PATLAW-G080
- Outputs: data/agent_supervisor/patent_legal_intelligence/retry_repairs/PATLAW-024.json
- Validation: python -m pytest tests/unit/processors/domains/uspto/providers/test_patent_center_export.py tests/security/test_uspto_private_import.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/retry-repair
- Parallel lane: patlaw-operations
- Resource class: cpu-small
- Token class: small
- Estimated tokens: 1000
- Predicted files: data/agent_supervisor/patent_legal_intelligence/retry_repairs/PATLAW-024.json
- Allow concurrent with:
- Conflict policy: Release only the exhausted validation-attempt budget after the exact artifact-envelope policy fix; do not alter task state files or claim implementation completion.
- Preconditions: The task-bound binary/archive envelope, synthetic-canary policy, and bounded failure-diagnostic fix are reviewed and tested.
- Effects: Record one board-visible retry-repair receipt so every lane clears only PATLAW-024's display/canonical attempt counters and queue cooldown.
- Generated by: ipfs_accelerate_py.agent_supervisor.retry-budget-repair@1
- Retry repair source: PATLAW-024
- Retry failure kind: validation
- Acceptance: The reviewed proposal-gate archive/fixture false positives are fixed and tested; release PATLAW-024 from strategy blocked_tasks without editing durable task state directly.

## PATLAW-120 Add bounded production HTTP transport and credential references

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-acquisition
- Depends on:
- Goal id: PATLAW-G111
- Outputs: ipfs_datasets_py/processors/domains/uspto/providers/http_transport.py, ipfs_datasets_py/processors/domains/uspto/providers/credential_resolver.py, tests/unit/processors/domains/uspto/providers/test_http_transport.py, tests/security/test_uspto_credential_resolution.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/providers/test_http_transport.py tests/security/test_uspto_credential_resolution.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-production-transport
- Parallel lane: patlaw-v2-lane-0
- Resource class: io-medium
- Token class: large
- Estimated tokens: 14000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/providers/http_transport.py, ipfs_datasets_py/processors/domains/uspto/providers/credential_resolver.py, tests/unit/processors/domains/uspto/providers/test_http_transport.py, tests/security/test_uspto_credential_resolution.py
- Allow concurrent with: PATLAW-121, PATLAW-122, PATLAW-123
- Conflict policy: Own the concrete transport and credential-reference adapter only; do not edit provider package exports, supervisor files, store secrets, log authorization headers, or bypass the existing host/rate/privacy policy.
- Preconditions: Existing ODP client contracts, retry/rate-limit policy, privacy boundary, artifact receipts, and recorded transport tests are treated as immutable inputs.
- Effects: Implement a reusable HTTPS transport with allowlisted hosts, explicit timeouts, bounded retries/backoff, response-size limits, conditional requests, cancellation, structured quota/error classification, and vault/environment credential references resolved only at request time.
- Acceptance: Recorded and fake-server tests cover success, pagination, 304, 401/403, 404, 429/quota, 5xx, timeout, oversized body, cancellation, and redacted diagnostics; secrets never enter artifacts or logs; no live network is required by default.

## PATLAW-121 Bridge USPTO documents to the specialized PDF/OCR stack

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: document-understanding
- Depends on:
- Goal id: PATLAW-G121
- Outputs: ipfs_datasets_py/processors/domains/uspto/pdf_ocr_bridge.py, ipfs_datasets_py/processors/domains/uspto/structured_filing_bridge.py, tests/unit/processors/domains/uspto/test_pdf_ocr_bridge.py, tests/unit/processors/domains/uspto/test_structured_filing_bridge.py, tests/integration/processors/domains/uspto/test_private_ocr_bridge.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_pdf_ocr_bridge.py tests/unit/processors/domains/uspto/test_structured_filing_bridge.py tests/integration/processors/domains/uspto/test_private_ocr_bridge.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-pdf-ocr-bridge
- Parallel lane: patlaw-v2-lane-1
- Resource class: cpu-large
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/pdf_ocr_bridge.py, ipfs_datasets_py/processors/domains/uspto/structured_filing_bridge.py, tests/unit/processors/domains/uspto/test_pdf_ocr_bridge.py, tests/unit/processors/domains/uspto/test_structured_filing_bridge.py, tests/integration/processors/domains/uspto/test_private_ocr_bridge.py
- Allow concurrent with: PATLAW-120, PATLAW-122, PATLAW-123
- Conflict policy: Own the USPTO-to-specialized-PDF adapter only; do not fork generic PDF processors, alter encrypted artifact stores, or send private pages to a remote OCR/model provider without an explicit approved route.
- Preconditions: Existing document bytes, classification, extraction/span contracts, specialized PDF processors, and private-compute policy are available as stable inputs.
- Effects: Route born-digital PDFs through layout/text extraction and image-only or low-confidence pages through a configurable local OCR backend while retaining page geometry, reading order, tables, signatures/stamps, confidence, and byte/page provenance; add bounded TXT, XML, image, PCT ZIP, Web ADS/bibliographic, and ST.26 XML dispatch with pinned local schema/DTD validation and external-entity/network resolution disabled.
- Acceptance: Native and scanned fixtures yield deterministic normalized spans linked to source CID/page/bounds; OCR fallback is confidence-gated and resumable; corrupt/encrypted/unsupported PDFs fail closed; XML/XXE and archive-bomb cases fail safely; every structured format is validated or explicitly unsupported; private fixtures prove zero unauthorized provider calls and zero plaintext persistence.

## PATLAW-122 Define exact USPTO span, authority, fact, and Legal IR contracts

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-logic-assurance
- Depends on:
- Goal id: PATLAW-G131
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/legal_ir_contracts.py, tests/unit/processors/domains/uspto/analysis/test_legal_ir_contracts.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_legal_ir_contracts.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-legal-ir-contracts
- Parallel lane: patlaw-v2-lane-2
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 12000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/legal_ir_contracts.py, tests/unit/processors/domains/uspto/analysis/test_legal_ir_contracts.py
- Allow concurrent with: PATLAW-120, PATLAW-121, PATLAW-123
- Conflict policy: Own the versioned boundary contracts only; do not modify the shared Legal IR/compiler/proof engine, infer missing source spans, or represent guidance as binding authority.
- Preconditions: Existing USPTO extraction spans, citation resolver, temporal authority records, requirements, evidence graph, and legal/logic APIs have been inventoried.
- Effects: Define lossless mappings for source spans, normalized propositions, actors, modalities, conditions, deadlines, exceptions, citations, authority rank/effective time, submission facts, proof obligations, assumptions, counterevidence, and tri-state outcomes.
- Acceptance: Round trips preserve exact source identity and temporal/disclosure metadata; invalid or ambiguous mappings are rejected or marked unknown; schemas distinguish quoted text, deterministic normalization, model candidates, human findings, and proven conclusions.

## PATLAW-123 Make gold-corpus metrics executable and receipt-bound

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: evaluation-release
- Depends on:
- Goal id: PATLAW-G151
- Outputs: ipfs_datasets_py/processors/domains/uspto/evaluation.py, tests/integration/processors/domains/uspto/test_gold_metric_evaluator.py, tests/fixtures/uspto/gold/metrics/observed_metrics.schema.json
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_gold_metric_evaluator.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-gold-metrics
- Parallel lane: patlaw-v2-lane-3
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/evaluation.py, tests/integration/processors/domains/uspto/test_gold_metric_evaluator.py, tests/fixtures/uspto/gold/metrics/observed_metrics.schema.json
- Allow concurrent with: PATLAW-120, PATLAW-121, PATLAW-122
- Conflict policy: Own metric computation and observed-result schema only; do not rewrite gold labels, silently relax thresholds, claim official provenance, or replace existing release gates with schema/hash presence checks.
- Preconditions: Existing synthetic gold cases, metric threshold manifest, dossier schemas, and evaluation contracts are readable without network access.
- Effects: Compute document classification, span, semantic field, citation, obligation, contradiction, deadline, privacy, determinism, and end-to-end completeness metrics from actual processor outputs and emit content-addressed evaluation receipts.
- Acceptance: Intentionally degraded outputs fail their corresponding metric; thresholds are versioned and compared to observed values; receipts bind corpus/parser/ruleset/model/config identities; missing labels or unmeasurable cases produce explicit unknown/not-applicable counts rather than passes.

## PATLAW-124 Bootstrap ODP clients and durable matter state

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-acquisition
- Depends on: PATLAW-120
- Goal id: PATLAW-G111
- Outputs: ipfs_datasets_py/processors/domains/uspto/runtime.py, ipfs_datasets_py/processors/domains/uspto/durable_stores.py, ipfs_datasets_py/processors/domains/uspto/status_vocabulary.py, ipfs_datasets_py/processors/domains/uspto/providers/odp_contract_monitor.py, ipfs_datasets_py/processors/domains/uspto/providers/patent_file_wrapper.py, ipfs_datasets_py/processors/domains/uspto/application_status_processor.py, tests/integration/processors/domains/uspto/test_live_runtime_bootstrap.py, tests/integration/processors/domains/uspto/test_durable_matter_state.py, tests/integration/processors/domains/uspto/test_odp_family_status_contract.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_live_runtime_bootstrap.py tests/integration/processors/domains/uspto/test_durable_matter_state.py tests/integration/processors/domains/uspto/test_odp_family_status_contract.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-runtime-state
- Parallel lane: patlaw-v2-lane-0
- Resource class: io-large
- Token class: large
- Estimated tokens: 18000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/runtime.py, ipfs_datasets_py/processors/domains/uspto/durable_stores.py, ipfs_datasets_py/processors/domains/uspto/status_vocabulary.py, ipfs_datasets_py/processors/domains/uspto/providers/odp_contract_monitor.py, ipfs_datasets_py/processors/domains/uspto/providers/patent_file_wrapper.py, ipfs_datasets_py/processors/domains/uspto/application_status_processor.py, tests/integration/processors/domains/uspto/test_live_runtime_bootstrap.py, tests/integration/processors/domains/uspto/test_durable_matter_state.py, tests/integration/processors/domains/uspto/test_odp_family_status_contract.py
- Allow concurrent with: PATLAW-125, PATLAW-126, PATLAW-127
- Conflict policy: Own runtime construction and durable store implementations only; do not edit CLI/API registries, persist credentials, invent Patent Center scraping, or weaken tenant/disclosure checks.
- Preconditions: Production transport and existing ODP status/document clients, checkpoint contracts, matter ledger, artifact manifest, and private store interfaces are available.
- Effects: Construct production or recorded clients from explicit profiles; retrieve application, transaction, document, continuity, and foreign-priority records; normalize only a versioned protected ODP status vocabulary while retaining unknown raw codes; probe the announced 2026 sign-in/profile contract; and add transactional status, document, cursor/checkpoint, matter-ledger, idempotency, and key-reference stores with schema versioning, locking, crash recovery, and tenant-scoped encryption metadata.
- Acceptance: Ordinary configured API/CLI paths no longer require a fixture recipe; continuity/foreign-priority facts are immutable and source-bound; unknown numeric status codes return unknown/quarantine rather than known; opt-in canaries distinguish 401/403 authentication/profile drift from quota/outage/empty results; restart tests resume without duplicate events/downloads; key references remain stable across CLI invocations; tenant separation and least-privilege file modes are enforced.

## PATLAW-125 Add a checkpointed USPTO document processing job

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: document-understanding
- Depends on: PATLAW-121, PATLAW-124
- Goal id: PATLAW-G121
- Outputs: ipfs_datasets_py/processors/domains/uspto/document_pipeline_processor.py, tests/integration/processors/domains/uspto/test_document_pipeline_processor.py, tests/integration/processors/domains/uspto/test_document_pipeline_recovery.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_document_pipeline_processor.py tests/integration/processors/domains/uspto/test_document_pipeline_recovery.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-document-pipeline
- Parallel lane: patlaw-v2-lane-1
- Resource class: cpu-large
- Token class: large
- Estimated tokens: 18000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/document_pipeline_processor.py, tests/integration/processors/domains/uspto/test_document_pipeline_processor.py, tests/integration/processors/domains/uspto/test_document_pipeline_recovery.py
- Allow concurrent with: PATLAW-126, PATLAW-127
- Conflict policy: Own the new orchestration processor and its tests only; consume classifiers/extractors/validators/stores through public contracts and do not edit their implementations or shared registries.
- Preconditions: Durable matter state and the specialized PDF/OCR bridge are merged; existing classification, artifact, extraction, and span-validation APIs remain available.
- Effects: Execute classify, authorize, decrypt in memory, extract/OCR, normalize, validate spans, persist encrypted derived artifacts, and checkpoint each immutable stage with deterministic idempotency keys and quarantine routes.
- Acceptance: Mixed PDF/DOCX fixtures complete through every stage; restart from each injected failure does not repeat committed work; corrupt, untrusted, or policy-denied inputs quarantine with diagnostics; processor success reflects domain outcome rather than exception absence.

## PATLAW-126 Execute Legal IR compilation and proofs inside the privacy boundary

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-logic-assurance
- Depends on: PATLAW-122
- Goal id: PATLAW-G131
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/legal_ir_proof_executor.py, tests/unit/processors/domains/uspto/analysis/test_legal_ir_proof_executor.py, tests/security/test_uspto_private_proof_non_disclosure.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_legal_ir_proof_executor.py tests/security/test_uspto_private_proof_non_disclosure.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-legal-proof
- Parallel lane: patlaw-v2-lane-2
- Resource class: cpu-large
- Token class: large
- Estimated tokens: 17000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/legal_ir_proof_executor.py, tests/unit/processors/domains/uspto/analysis/test_legal_ir_proof_executor.py, tests/security/test_uspto_private_proof_non_disclosure.py
- Allow concurrent with: PATLAW-124, PATLAW-125, PATLAW-127
- Conflict policy: Own the USPTO adapter to LegalIRCompilerAPI and ProofExecutionEngine only; do not modify either shared engine, allow generated text to become authority, or disclose private propositions to an unapproved remote provider.
- Preconditions: Versioned Legal IR boundary contracts and shared compiler/proof APIs are available; allowed local execution routes and resource ceilings are explicit.
- Effects: Compile normalized office-action rules and submission facts, invoke bounded proofs, capture assumptions/derivations/countermodels/timeouts, and translate engine results into provenance-linked proved/disproved/unknown/error outcomes.
- Acceptance: Known satisfiable, contradictory, incomplete, and timeout fixtures map correctly; every conclusion cites its premises and engine/config identity; unavailable or unsupported logic returns unknown; private tests observe zero remote calls and no plaintext logs.

## PATLAW-127 Add a common live legal-source fetch and receipt layer

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-acquisition
- Depends on: PATLAW-120
- Goal id: PATLAW-G112
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/patent_source_transport.py, ipfs_datasets_py/processors/legal_data/patent_authority_contracts_v2.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_patent_source_transport.py, tests/unit/processors/legal_data/test_patent_authority_contracts_v2.py
- Validation: python -m pytest tests/unit/processors/legal_scrapers/federal_scrapers/test_patent_source_transport.py tests/unit/processors/legal_data/test_patent_authority_contracts_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-authority-transport
- Parallel lane: patlaw-v2-lane-3
- Resource class: io-medium
- Token class: large
- Estimated tokens: 13000
- Predicted files: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/patent_source_transport.py, ipfs_datasets_py/processors/legal_data/patent_authority_contracts_v2.py, tests/unit/processors/legal_scrapers/federal_scrapers/test_patent_source_transport.py, tests/unit/processors/legal_data/test_patent_authority_contracts_v2.py
- Allow concurrent with: PATLAW-124, PATLAW-125, PATLAW-126
- Conflict policy: Own the legal-source fetch adapter and receipt contract only; do not alter individual source parsers, scrape non-allowlisted sites, or mark transport success as source authenticity.
- Preconditions: Bounded HTTP transport, official-source allowlist, artifact-manifest contract, and existing federal source processors are available.
- Effects: Add conditional-download, pagination, content-type/size validation, fixity, cache, retry-after, robots/terms metadata, source timestamp, and immutable acquisition receipts; define independent authority kind, tier, rendition legal status, jurisdiction, edition/release point and exclusions, document/package/granule IDs, media type, signature/fixity evidence, and full temporal-role contracts shared by live CFR, GovInfo, Federal Register, and USPTO guidance processors.
- Acceptance: Fake-server tests cover unchanged, changed, truncated, mislabeled, throttled, and unavailable sources; bytes and receipts are content-addressed; statute, regulation, adjudicatory authority, guidance, editorial aid, and extracted candidates cannot collapse into one tier; parser input is never accepted without an acquisition outcome; network use remains explicit and bounded.

## PATLAW-128 Acquire live eCFR and annual CFR authority snapshots

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-acquisition
- Depends on: PATLAW-127
- Goal id: PATLAW-G112
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/live_cfr_source_processor.py, tests/integration/legal_data/test_live_cfr_acquisition.py, tests/fixtures/legal_data/patent_authorities/live/cfr_recipe.json
- Validation: python -m pytest tests/integration/legal_data/test_live_cfr_acquisition.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-cfr-acquisition
- Parallel lane: patlaw-v2-lane-0
- Resource class: io-large
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/live_cfr_source_processor.py, tests/integration/legal_data/test_live_cfr_acquisition.py, tests/fixtures/legal_data/patent_authorities/live/cfr_recipe.json
- Allow concurrent with: PATLAW-129, PATLAW-131, PATLAW-132
- Conflict policy: Own the live CFR acquisition wrapper and replay recipe only; do not rewrite existing eCFR/annual parsers, hard-code a latest edition, or treat eCFR editorial text as authenticated annual print.
- Preconditions: Common legal-source transport and the existing eCFR/annual CFR processors, source ranking, temporal model, and official-verification contracts are available.
- Effects: Discover and fetch relevant Title 37 current/effective snapshots and annual editions, preserve edition/granule/source metadata, feed recorded bytes to existing parsers, and reconcile current editorial text with annual official baselines.
- Acceptance: Recorded integration covers pagination, point-in-time lookup, annual edition rollover, changed/removed sections, missing granules, and conflicting text; every provision has source CID/span/effective interval and separate authority/authentication status.

## PATLAW-129 Parse layout-aware office-action semantics v2

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: document-understanding
- Depends on: PATLAW-125
- Goal id: PATLAW-G122
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/office_action_semantics_v2.py, tests/unit/processors/domains/uspto/analysis/test_office_action_semantics_v2.py, tests/fixtures/uspto/office_actions/semantic_v2_recipe.json
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_office_action_semantics_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-office-action-semantics
- Parallel lane: patlaw-v2-lane-1
- Resource class: cpu-large
- Token class: large
- Estimated tokens: 19000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/office_action_semantics_v2.py, tests/unit/processors/domains/uspto/analysis/test_office_action_semantics_v2.py, tests/fixtures/uspto/office_actions/semantic_v2_recipe.json
- Allow concurrent with: PATLAW-128, PATLAW-131, PATLAW-132
- Conflict policy: Own the v2 semantic parser and fixtures only; do not overwrite the v1 parser, promote model candidates without deterministic validation, or detach findings from page/span provenance.
- Preconditions: Validated layout/OCR spans are available from the checkpointed document job; v1 office-action and citation contracts define compatibility requirements.
- Effects: Parse headers, mailing/notification dates, response periods, examiner contacts, claim groupings, objections, rejections, allowances, requirements, statutory/regulatory citations, forms, attachments, signatures, tables, and cross-page continuations into confidence-scored candidate semantics across missing-parts/omitted-item/no-filing-date, restriction/election, Quayle, advisory, sequence-compliance, allowance/issue-fee, appeal/pre-appeal, petition, rescinded/reissued, non-final, and final communication families.
- Acceptance: Gold fixtures cover every named family, document-code drift, and noisy scans; each field retains exact supporting spans; deterministic rules validate identifiers/dates/citations and flag contradictions; model output remains a candidate until admitted; missing, unknown-family, or ambiguous content stays unknown/review-required.

## PATLAW-130 Bind obligations to specific submission evidence and proofs

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-logic-assurance
- Depends on: PATLAW-126, PATLAW-129, PATLAW-133
- Goal id: PATLAW-G131
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/semantic_compliance_processor.py, tests/unit/processors/domains/uspto/analysis/test_semantic_compliance_processor.py, tests/integration/processors/domains/uspto/test_semantic_submission_compliance.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_semantic_compliance_processor.py tests/integration/processors/domains/uspto/test_semantic_submission_compliance.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-semantic-compliance
- Parallel lane: patlaw-v2-lane-2
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 22000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/semantic_compliance_processor.py, tests/unit/processors/domains/uspto/analysis/test_semantic_compliance_processor.py, tests/integration/processors/domains/uspto/test_semantic_submission_compliance.py
- Allow concurrent with: PATLAW-128, PATLAW-131, PATLAW-132
- Conflict policy: Own obligation-specific matching/proof orchestration only; do not edit source parsers, accept broad fact-category presence as compliance, or convert lack of counterevidence into proof.
- Preconditions: Office-action v2 semantics, submission-package v2 semantics, and privacy-safe Legal IR proof execution are merged.
- Effects: Normalize each government demand into atomic obligations and bind it to exact responsive document/claim/argument/amendment/declaration/fee/form evidence, required conditions, exceptions, contradictions, and proof results.
- Acceptance: Unrelated remarks cannot satisfy a rejection response; partial/conditional/contradictory evidence yields incomplete/unknown/fail as appropriate; every result has obligation, evidence, authority, and proof provenance; model similarity can rank candidates but cannot establish satisfaction.

## PATLAW-131 Acquire and verify GovInfo, U.S. Code, Public Law, and Federal Register sources

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-acquisition
- Depends on: PATLAW-127
- Goal id: PATLAW-G112
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/live_official_patent_authority_processor.py, tests/integration/legal_data/test_live_official_patent_authorities.py, tests/fixtures/legal_data/patent_authorities/live/official_authorities_recipe.json
- Validation: python -m pytest tests/integration/legal_data/test_live_official_patent_authorities.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-official-authority-acquisition
- Parallel lane: patlaw-v2-lane-3
- Resource class: io-large
- Token class: xlarge
- Estimated tokens: 22000
- Predicted files: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/live_official_patent_authority_processor.py, tests/integration/legal_data/test_live_official_patent_authorities.py, tests/fixtures/legal_data/patent_authorities/live/official_authorities_recipe.json
- Allow concurrent with: PATLAW-128, PATLAW-129, PATLAW-132
- Conflict policy: Own the live multi-source acquisition/verification wrapper and replay recipe only; consume existing source processors/verifiers and never infer official authentication from HTTPS or a secondary mirror.
- Preconditions: Common legal-source transport and existing GovInfo, USLM/U.S. Code, Public Law change, Federal Register, fixity, signature, and source-authority processors are available.
- Effects: Discover relevant Title 35 OLRC release points and declared exclusions, Statutes at Large/Public Laws, Title 37 annual materials, and Federal Register issues/notices/rules; download official packages/renditions and metadata; verify fixity/authentication where available; distinguish GovInfo official electronic Federal Register artifacts from FederalRegister.gov discovery representations; cross-link amendments and effective dates.
- Acceptance: Recorded cases cover edition rollover, release-point exclusions, amended/renumbered provisions, missing package/granule, bad fixity, unavailable signature, delayed issue, and source conflict; adjudicatory coverage is explicitly present or recorded as a blocking research gap; unverified or incomplete sources remain usable only with explicit degraded status.

## PATLAW-132 Acquire live MPEP, forms, fees, and examination guidance

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: production-acquisition
- Depends on: PATLAW-127
- Goal id: PATLAW-G112
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/live_uspto_guidance_processor.py, tests/integration/legal_data/test_live_uspto_guidance.py, tests/fixtures/legal_data/patent_authorities/live/uspto_guidance_recipe.json
- Validation: python -m pytest tests/integration/legal_data/test_live_uspto_guidance.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-uspto-guidance-acquisition
- Parallel lane: patlaw-v2-lane-0
- Resource class: io-large
- Token class: large
- Estimated tokens: 17000
- Predicted files: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers/live_uspto_guidance_processor.py, tests/integration/legal_data/test_live_uspto_guidance.py, tests/fixtures/legal_data/patent_authorities/live/uspto_guidance_recipe.json
- Allow concurrent with: PATLAW-128, PATLAW-129, PATLAW-131
- Conflict policy: Own live USPTO guidance acquisition and replay data only; do not classify the MPEP, forms, fee schedules, FAQs, or examination guides as statutes/regulations, and do not automate filing or payment.
- Preconditions: Common legal-source transport, existing USPTO guidance parsers, source hierarchy, and temporal authority registry are available.
- Effects: Discover dated MPEP editions/revisions, official forms/instructions, fee schedules, and examination guidance; acquire immutable bytes/metadata; detect replacements; and preserve the guidance/nonbinding authority class and applicable dates.
- Acceptance: Recorded rollover/removal/conflict fixtures retain old and new versions; every item has source CID/span/retrieved/published/effective metadata where supplied; unavailable dates and supersession remain explicit; links never silently select latest.

## PATLAW-133 Parse submission-package semantics v2

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: document-understanding
- Depends on: PATLAW-125
- Goal id: PATLAW-G122
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/submission_package_semantics_v2.py, tests/unit/processors/domains/uspto/analysis/test_submission_package_semantics_v2.py, tests/fixtures/uspto/submissions/semantic_v2_recipe.json
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_submission_package_semantics_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-submission-semantics
- Parallel lane: patlaw-v2-lane-1
- Resource class: cpu-large
- Token class: large
- Estimated tokens: 19000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/submission_package_semantics_v2.py, tests/unit/processors/domains/uspto/analysis/test_submission_package_semantics_v2.py, tests/fixtures/uspto/submissions/semantic_v2_recipe.json
- Allow concurrent with: PATLAW-128, PATLAW-131, PATLAW-132
- Conflict policy: Own the v2 package parser and fixtures only; do not overwrite v1 parsing, infer a filed document that is absent, or treat filenames/document codes as sufficient semantic evidence.
- Preconditions: Validated layout/OCR spans and synchronized submission document manifests are available; v1 submission/fact/evidence contracts define compatibility requirements.
- Effects: Parse package inventory, bibliographic/ADS and benefit identifiers, claims and amendments, specification/drawings, arguments mapped to issues/claims/citations, declarations, signatures-as-present, certifications, forms, fee assertions, sequence-listing applicability, attachments, replacement-page instructions, submitted DOCX, feedback document, converted/auxiliary/split PDFs, and warnings/errors with cross-document links; distinguish transmission attempt, Electronic Submission Receipt, payment receipt, official/corrected Filing Receipt, and first ODP appearance.
- Acceptance: Gold fixtures cover complete, partial, duplicate, inconsistent, scanned, and conversion-warning packages; every normalized fact cites exact document/page/span or structured-field anchor; hashes and effects for every receipt/rendering type remain distinct; inventory and internal-content discrepancies are reported; candidate associations remain confidence-scored and reviewable.

## PATLAW-134 Verify government instructions against authority and logic

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-logic-assurance
- Depends on: PATLAW-126, PATLAW-129, PATLAW-135
- Goal id: PATLAW-G131
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/semantic_instruction_consistency_processor.py, tests/unit/processors/domains/uspto/analysis/test_semantic_instruction_consistency.py, tests/integration/processors/domains/uspto/test_instruction_logic_assurance.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_semantic_instruction_consistency.py tests/integration/processors/domains/uspto/test_instruction_logic_assurance.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-instruction-consistency
- Parallel lane: patlaw-v2-lane-2
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 22000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/semantic_instruction_consistency_processor.py, tests/unit/processors/domains/uspto/analysis/test_semantic_instruction_consistency.py, tests/integration/processors/domains/uspto/test_instruction_logic_assurance.py
- Allow concurrent with: PATLAW-137, PATLAW-138, PATLAW-139
- Conflict policy: Own semantic instruction checking only; do not mark an instruction consistent merely because a citation resolves, substitute MPEP/guidance for controlling law, or make a final legal determination without review.
- Preconditions: Office-action v2 semantics, privacy-safe proof execution, and temporally materialized authority snapshots are merged.
- Effects: Compare each instruction, deadline basis, required act, exception, and cited proposition with exact quoted authority spans, hierarchy/effective date, derived Legal IR, conflicts, and counterexamples; distinguish clerical mismatch, unsupported instruction, ambiguity, and verified consistency.
- Acceptance: Exact-citation-but-wrong-proposition fixtures fail or require review; superseded/conflicting/missing authority cannot pass; consistent results require proposition-level support plus proof or a documented deterministic rule; findings expose sources, assumptions, confidence, and human-review boundary.

## PATLAW-135 Materialize scheduled temporal patent-authority snapshots

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-acquisition
- Depends on: PATLAW-128, PATLAW-131, PATLAW-132
- Goal id: PATLAW-G112
- Outputs: ipfs_datasets_py/processors/legal_data/patent_authority_materializer.py, tests/integration/legal_data/test_patent_authority_materializer.py, tests/fixtures/legal_data/patent_authorities/live/temporal_materialization_recipe.json
- Validation: python -m pytest tests/integration/legal_data/test_patent_authority_materializer.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-authority-materialization
- Parallel lane: patlaw-v2-lane-3
- Resource class: io-large
- Token class: xlarge
- Estimated tokens: 22000
- Predicted files: ipfs_datasets_py/processors/legal_data/patent_authority_materializer.py, tests/integration/legal_data/test_patent_authority_materializer.py, tests/fixtures/legal_data/patent_authorities/live/temporal_materialization_recipe.json
- Allow concurrent with: PATLAW-129, PATLAW-133
- Conflict policy: Own the new materializer, its replay fixture, and tests only; do not rewrite source acquisitions, mutate prior snapshots, or collapse conflicting authority records into a fabricated consensus.
- Preconditions: Live CFR, official statutory/rulemaking, and USPTO guidance acquisition processors are merged with existing temporal resolver and canonical legal corpora interfaces.
- Effects: Run incremental acquisitions on explicit schedules, normalize/cross-link versions, build immutable as-of views and freshness manifests, retain conflicts and gaps, and publish local content-addressed snapshot references for downstream analysis.
- Acceptance: Replaying identical inputs is byte-stable; changed sources create new snapshots without mutating old ones; as-of queries never leak later law; statute/regulation/adjudicatory/guidance/editorial tiers and rendition status persist; absent adjudicatory coverage is a visible blocking research gap; stale/missing/conflicting mandatory sources block an authoritative-ready state.

## PATLAW-136 Orchestrate resumable matter analysis end to end

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: product-workflow
- Depends on: PATLAW-124, PATLAW-125, PATLAW-129, PATLAW-130, PATLAW-133, PATLAW-134, PATLAW-135
- Goal id: PATLAW-G141
- Outputs: ipfs_datasets_py/processors/domains/uspto/matter_analysis_processor.py, tests/integration/processors/domains/uspto/test_matter_analysis_processor.py, tests/integration/processors/domains/uspto/test_matter_analysis_resume.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_matter_analysis_processor.py tests/integration/processors/domains/uspto/test_matter_analysis_resume.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-matter-analysis
- Parallel lane: patlaw-v2-lane-0
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 24000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/matter_analysis_processor.py, tests/integration/processors/domains/uspto/test_matter_analysis_processor.py, tests/integration/processors/domains/uspto/test_matter_analysis_resume.py
- Allow concurrent with: PATLAW-137, PATLAW-138, PATLAW-139
- Conflict policy: Own the new matter-level orchestrator and tests only; call leaf processors through stable interfaces, do not edit shared API/CLI/MCP registries, and never perform filing, payment, signature, or legal-strategy selection.
- Preconditions: Durable ODP/matter state, document processing, office-action/submission semantics, compliance, instruction consistency, and temporal authority materialization are merged.
- Effects: Given a tenant and matter reference, incrementally sync authorized status/documents, process changed artifacts, select the correct as-of authority view, run semantic/legal/logic checks, assemble a versioned dossier, and checkpoint a stage/result DAG.
- Acceptance: One call handles a new matter and a later delta; retries resume exactly; unchanged stages are reused by input digest; partial, quarantined, stale-authority, proof-unknown, and review-required states propagate to the top-level result instead of reporting unconditional success.

## PATLAW-137 Build versioned baseline filing-obligation packs

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-logic-assurance
- Depends on: PATLAW-133, PATLAW-135
- Goal id: PATLAW-G132
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/filing_obligation_processor.py, ipfs_datasets_py/processors/domains/uspto/analysis/filing_rule_packs.py, tests/unit/processors/domains/uspto/analysis/test_filing_obligation_processor.py, tests/fixtures/uspto/filing_rules/baseline_rules.json
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_filing_obligation_processor.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-filing-obligations
- Parallel lane: patlaw-v2-lane-1
- Resource class: cpu-medium
- Token class: xlarge
- Estimated tokens: 21000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/filing_obligation_processor.py, ipfs_datasets_py/processors/domains/uspto/analysis/filing_rule_packs.py, tests/unit/processors/domains/uspto/analysis/test_filing_obligation_processor.py, tests/fixtures/uspto/filing_rules/baseline_rules.json
- Allow concurrent with: PATLAW-134, PATLAW-138, PATLAW-139
- Conflict policy: Own baseline rule-pack contracts/processor/fixture only; do not encode matter-specific legal strategy, silently update rules, claim exhaustive coverage, or treat form instructions as controlling law.
- Preconditions: Submission-package semantics and authoritative as-of snapshots are available; supported filing/response scenarios and human rule-review workflow are explicitly bounded.
- Effects: Compile reviewed, versioned obligation packs for utility, design under 37 CFR 1.151–1.155, and plant under 37 CFR 1.161–1.167 application and office-action response components, keyed by filing date, AIA/pre-AIA regime, prosecution stage/finality, and entity status, including signatures/certifications, ADS/benefit claims, claim amendments, attachments, sequence listings, fees/forms, identifiers, and conditional exceptions, each linked to exact authority and guidance provenance.
- Acceptance: Rules identify jurisdiction, application type, scenario, applicability/effective interval, required evidence, exceptions, citations, reviewer/version, and tests; provisional, PCT national-stage, reissue, continuation, divisional, and CIP cases have an explicit reviewed profile or return out-of-scope/unknown; unsupported scenarios return coverage gaps; a pack cannot become active until source digests and human approval are recorded.

## PATLAW-138 Build authoritative deadline and closure-calendar snapshots

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: legal-logic-assurance
- Depends on: PATLAW-135
- Goal id: PATLAW-G132
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/authoritative_deadline_calendar.py, tests/unit/processors/domains/uspto/analysis/test_authoritative_deadline_calendar.py, tests/fixtures/uspto/deadlines/closure_calendar_recipe.json
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_authoritative_deadline_calendar.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-authoritative-deadlines
- Parallel lane: patlaw-v2-lane-2
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/analysis/authoritative_deadline_calendar.py, tests/unit/processors/domains/uspto/analysis/test_authoritative_deadline_calendar.py, tests/fixtures/uspto/deadlines/closure_calendar_recipe.json
- Allow concurrent with: PATLAW-134, PATLAW-137, PATLAW-139
- Conflict policy: Own closure-calendar snapshots and enhanced deadline computation only; do not replace docketing counsel, assume extensions, infer service dates, or mutate the v1 calculator.
- Preconditions: Temporal authority snapshots, parsed mailing/notification dates, and existing deadline/event contracts are available.
- Effects: Materialize sourced federal/USPTO closure and emergency-relief calendars, compute rule-specific base/extension/maximum dates and uncertainty bounds, and retain timezone, service channel, trigger, authority, and as-of provenance.
- Acceptance: Weekend/holiday/closure/emergency/extension/conflicting-date fixtures are deterministic; missing trigger or calendar provenance blocks a definitive deadline; output separates calculated dates, source-stated dates, assumptions, and human confirmation requirements.

## PATLAW-139 Add an approved-public-official USPTO evaluation corpus

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: evaluation-release
- Depends on: PATLAW-124, PATLAW-129, PATLAW-133, PATLAW-135
- Goal id: PATLAW-G151
- Outputs: tests/fixtures/uspto/gold/public_official/README.md, tests/fixtures/uspto/gold/public_official/manifest.json, tests/contract/processors/test_uspto_public_official_corpus.py
- Validation: python -m pytest tests/contract/processors/test_uspto_public_official_corpus.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-public-official-corpus
- Parallel lane: patlaw-v2-lane-3
- Resource class: io-medium
- Token class: xlarge
- Estimated tokens: 22000
- Predicted files: tests/fixtures/uspto/gold/public_official/README.md, tests/fixtures/uspto/gold/public_official/manifest.json, tests/contract/processors/test_uspto_public_official_corpus.py
- Allow concurrent with: PATLAW-134, PATLAW-137, PATLAW-138
- Conflict policy: Own only reviewed public-official corpus metadata and its contract test; do not include confidential/unpublished submissions, redistribute unreviewed documents, or label synthetic material official.
- Preconditions: Authorized public document acquisition and source snapshots work; licensing/redistribution, privacy, PII, provenance, and reviewer criteria are documented.
- Effects: Curate diverse publicly available USPTO/government document references and immutable permitted artifacts with human-reviewed labels for layout, fields, instructions, citations, obligations, submission evidence, deadlines, and expected uncertainty.
- Acceptance: Manifest distinguishes official bytes from annotations and synthetic supplements; every artifact has source URL/CID, public status, rights/privacy review, acquisition date, label reviewer/version, and split assignment; leakage and duplicate-family checks pass.

## PATLAW-140 Expose a serialized submission-assurance workflow through API and CLI

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: product-workflow
- Depends on: PATLAW-060, PATLAW-136, PATLAW-137, PATLAW-138
- Goal id: PATLAW-G141
- Outputs: ipfs_datasets_py/processors/domains/uspto/submission_assurance_processor.py, ipfs_datasets_py/processors/domains/uspto/api.py, ipfs_datasets_py/processors/adapters/uspto_adapter.py, ipfs_datasets_py/processors/domains/uspto/__init__.py, ipfs_datasets_py/cli/uspto.py, tests/cli/test_uspto_assurance_commands.py, tests/integration/processors/domains/uspto/test_submission_assurance_processor.py
- Validation: python -m pytest tests/cli/test_uspto_assurance_commands.py tests/integration/processors/domains/uspto/test_submission_assurance_processor.py tests/unit/processors/domains/uspto/test_api.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-submission-assurance
- Parallel lane: patlaw-v2-lane-0
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 26000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/submission_assurance_processor.py, ipfs_datasets_py/processors/domains/uspto/api.py, ipfs_datasets_py/processors/adapters/uspto_adapter.py, ipfs_datasets_py/processors/domains/uspto/__init__.py, ipfs_datasets_py/cli/uspto.py, tests/cli/test_uspto_assurance_commands.py, tests/integration/processors/domains/uspto/test_submission_assurance_processor.py
- Allow concurrent with:
- Conflict policy: This task is the serialized owner of USPTO API/adapter/package-export/CLI integration surfaces for v2; preserve v1 compatibility, do not edit MCP/scheduler surfaces, and require explicit opt-in for live/private operations.
- Preconditions: Matter analysis, filing-obligation packs, authoritative deadlines, and the completed v1 serialized integration task are merged; no other active task owns the reserved integration files.
- Effects: Add a one-shot and resumable processor/API/CLI flow that accepts a tenant/matter plus authorized source profile, derives classification from admitted artifacts with unknown/quarantine as the default, runs the actual pipeline, compares submission contents with government instructions and baseline obligations, distinguishes transport execution from domain assurance disposition, and exports a redacted or encrypted assurance dossier.
- Acceptance: Recorded E2E commands work without hand-built middle-stage objects; adapter/core success cannot conceal outage, quarantine, incomplete analysis, or mandatory review; result status reflects sync/extraction/authority/proof/compliance coverage; output lists satisfied/missing/contradictory/unknown/review items with exact provenance; no command files, pays, signs, or claims legal advice.

## PATLAW-141 Add read-only MCP assurance queries and delta alerts

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P1
- Track: product-workflow
- Depends on: PATLAW-061, PATLAW-062, PATLAW-140
- Goal id: PATLAW-G142
- Outputs: ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/uspto_tools.py, ipfs_datasets_py/processors/domains/uspto/scheduler.py, tests/mcp/unit/test_uspto_persisted_assurance_tools.py, tests/integration/processors/domains/uspto/test_assurance_delta_scheduler.py
- Validation: python -m pytest tests/mcp/unit/test_uspto_persisted_assurance_tools.py tests/integration/processors/domains/uspto/test_assurance_delta_scheduler.py tests/mcp/unit/test_uspto_tools.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-mcp-alerts
- Parallel lane: patlaw-v2-lane-1
- Resource class: io-medium
- Token class: large
- Estimated tokens: 18000
- Predicted files: ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/uspto_tools.py, ipfs_datasets_py/processors/domains/uspto/scheduler.py, tests/mcp/unit/test_uspto_persisted_assurance_tools.py, tests/integration/processors/domains/uspto/test_assurance_delta_scheduler.py
- Allow concurrent with:
- Conflict policy: This task is the serialized v2 owner of existing USPTO MCP/scheduler surfaces; preserve tenant authorization and v1 compatibility, expose read-only operations only, and never include private document text in alerts by default.
- Preconditions: Submission assurance is integrated and completed v1 MCP/scheduler tasks are merged; durable dossier and checkpoint stores are available.
- Effects: Query persisted dossier summaries/findings/provenance through tenant-scoped MCP tools and schedule incremental status/document/authority refreshes that emit deduplicated metadata-only alerts for meaningful state, deadline, instruction, compliance, or source changes.
- Acceptance: Unauthorized tenants receive no existence oracle; MCP does not trigger filing/payment or implicit live sync; unchanged runs emit no duplicate alert; alert payloads identify matter by configured opaque reference and link to a protected dossier rather than embedding content.

## PATLAW-142 Exercise every processor in true offline E2E and an optional live canary

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: evaluation-release
- Depends on: PATLAW-123, PATLAW-139, PATLAW-140, PATLAW-141
- Goal id: PATLAW-G152
- Outputs: tests/e2e/test_uspto_full_processor_pipeline_v2.py, tests/fixtures/uspto/replay/full_pipeline_v2_recipe.json, tests/integration/processors/domains/uspto/test_live_contract_canary.py
- Validation: python -m pytest tests/e2e/test_uspto_full_processor_pipeline_v2.py tests/integration/processors/domains/uspto/test_live_contract_canary.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-full-pipeline-e2e
- Parallel lane: patlaw-v2-lane-2
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 26000
- Predicted files: tests/e2e/test_uspto_full_processor_pipeline_v2.py, tests/fixtures/uspto/replay/full_pipeline_v2_recipe.json, tests/integration/processors/domains/uspto/test_live_contract_canary.py
- Allow concurrent with:
- Conflict policy: Own the v2 replay recipe and E2E/canary tests only; do not hand-construct dossier middle stages, embed credentials, make live tests mandatory, or mutate production/private matter state.
- Preconditions: Executable metrics, public-official corpus, serialized assurance API/CLI, MCP queries, and scheduler alerts are merged.
- Effects: Replay recorded ODP/legal-source responses and real permitted fixture documents through transport, stores, sync, extraction/OCR, semantics, authority materialization, Legal IR/proofs, obligations/compliance/deadlines, dossier, API/CLI/MCP, scheduler, and metric evaluator; add a separately gated minimal public live-contract probe.
- Acceptance: Test fails if any named processor is bypassed; output and metric receipts bind all versions/digests; injected quota/timeout/corruption/stale-law/restart cases propagate correctly; default suite is deterministic/offline and the canary is read-only, opt-in, bounded, and secret-redacted.

## PATLAW-143 Seal adversarial, migration, and release evidence for v2

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: evaluation-release
- Depends on: PATLAW-142
- Goal id: PATLAW-G152
- Outputs: tests/security/test_uspto_v2_adversarial_assurance.py, tests/property/test_uspto_v2_pipeline_properties.py, tests/release/test_uspto_v2_submission_assurance_release.py, scripts/ops/uspto/validate_v2_release.py, data/release/uspto_submission_assurance/v2_receipt.schema.json
- Validation: python -m pytest tests/security/test_uspto_v2_adversarial_assurance.py tests/property/test_uspto_v2_pipeline_properties.py tests/release/test_uspto_v2_submission_assurance_release.py -q && python scripts/ops/uspto/validate_v2_release.py --offline
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-release-assurance
- Parallel lane: patlaw-v2-lane-3
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 24000
- Predicted files: tests/security/test_uspto_v2_adversarial_assurance.py, tests/property/test_uspto_v2_pipeline_properties.py, tests/release/test_uspto_v2_submission_assurance_release.py, scripts/ops/uspto/validate_v2_release.py, data/release/uspto_submission_assurance/v2_receipt.schema.json
- Allow concurrent with:
- Conflict policy: Own v2 adversarial/property/migration/release tests, offline validator, and receipt schema only; do not edit protected supervisor artifacts, weaken thresholds, publish data, or declare release readiness from task status alone.
- Preconditions: The true full-processor E2E suite and all functional tasks are merged; v1 persisted-state fixtures and versioned schemas are available for migration tests.
- Effects: Exercise malicious PDFs/XML/archives, XXE/schema attacks, prompt injection, spoofed citations, hostile metadata, tenant crossover, credential leakage, oversized inputs, retry storms, contradictory law, corrupt checkpoints, schema migrations, key rotation, retention/deletion, backup/restore, deterministic rebuilds, and rollback; aggregate evidence into a content-free release receipt and a separately signed independent legal-review receipt.
- Acceptance: Security/property/privacy-lifecycle/migration/release gates pass on the exact tree; no-disclosure and provider-call evidence is explicit; v1 state either migrates transactionally or fails without mutation; receipt binds code/config/corpus/rules/parser/compiler/prover/model/test/metric digests and supervisor merge receipts, includes independent human legal-review scope and exceptions, and leaves every unknown mandatory gate blocking; task completion alone cannot reconcile goal status.

## PATLAW-144 Define persistent content-addressed index snapshot contracts

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-indexes
- Depends on: PATLAW-090, PATLAW-091, PATLAW-092, PATLAW-124, PATLAW-135
- Goal id: PATLAW-G161
- Outputs: ipfs_datasets_py/processors/domains/patent/index_store.py, ipfs_datasets_py/processors/domains/patent/index_snapshot_contracts.py, tests/unit/processors/patent/test_index_store.py
- Validation: python -m pytest tests/unit/processors/patent/test_index_store.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-index-contracts
- Parallel lane: patlaw-v2-lane-0
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/processors/domains/patent/index_store.py, ipfs_datasets_py/processors/domains/patent/index_snapshot_contracts.py, tests/unit/processors/patent/test_index_store.py
- Allow concurrent with: PATLAW-145, PATLAW-161
- Conflict policy: Own new persistent snapshot/store contracts and tests only; do not edit v1 indexing implementations, package exports, release builders, or authority materializers.
- Preconditions: Canonical retrieval, graph, and index contracts plus durable matter and temporal-authority snapshots are merged and treated as immutable inputs.
- Effects: Define append-only corpus/index manifests, CID joins, schema/model/config/code identities, checkpoints, tombstones, compaction roots, rollback pointers, disclosure and tenant partitions, and crash-safe local persistence interfaces.
- Acceptance: Round trips are deterministic; corrupt or cross-tenant manifests fail closed; every record joins to a source CID and version; resume, tombstone, compaction and rollback retain immutable prior roots; unknown model or schema versions cannot open a snapshot.

## PATLAW-145 Add a pinned local production embedding runtime

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-indexes
- Depends on: PATLAW-092, PATLAW-120
- Goal id: PATLAW-G161
- Outputs: ipfs_datasets_py/processors/domains/patent/embedding_runtime.py, tests/unit/processors/patent/test_embedding_runtime.py, tests/security/test_private_embedding_runtime.py
- Validation: python -m pytest tests/unit/processors/patent/test_embedding_runtime.py tests/security/test_private_embedding_runtime.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-embedding-runtime
- Parallel lane: patlaw-v2-lane-1
- Resource class: accelerator-optional
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/domains/patent/embedding_runtime.py, tests/unit/processors/patent/test_embedding_runtime.py, tests/security/test_private_embedding_runtime.py
- Allow concurrent with: PATLAW-144, PATLAW-161
- Conflict policy: Own the new embedding runtime and focused tests only; do not choose a model at runtime without a pinned revision, call an external provider for denied content, or edit shared accelerator/provider policy.
- Preconditions: V1 embedding metadata contracts and production bounded transport/privacy policy are available; approved local model artifacts are referenced by immutable identity.
- Effects: Implement deterministic batching, normalized input hashing, pinned model/tokenizer revision, device selection, bounded resource use, cache identity, cancellation, and an audited policy decision before any nonlocal route.
- Acceptance: Same inputs and pinned runtime produce stable vectors within declared tolerance; receipts bind model/tokenizer/code/config; unavailable hardware falls back explicitly or blocks; confidential tests make zero external calls and disclose no text, vectors, or CIDs.

## PATLAW-146 Build persistent incremental BM25, vector, and graph snapshots

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-indexes
- Depends on: PATLAW-144, PATLAW-145
- Goal id: PATLAW-G161
- Outputs: ipfs_datasets_py/processors/domains/patent/persistent_index_builder.py, tests/integration/processors/patent/test_persistent_index_builder.py, tests/fixtures/patent/index_snapshots/golden_manifest.json
- Validation: python -m pytest tests/integration/processors/patent/test_persistent_index_builder.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-persistent-index-build
- Parallel lane: patlaw-v2-lane-2
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 22000
- Predicted files: ipfs_datasets_py/processors/domains/patent/persistent_index_builder.py, tests/integration/processors/patent/test_persistent_index_builder.py, tests/fixtures/patent/index_snapshots/golden_manifest.json
- Allow concurrent with: PATLAW-148, PATLAW-152, PATLAW-156, PATLAW-161
- Conflict policy: Own the new persistent builder and golden snapshot fixture only; consume v1 BM25/vector/graph projectors through public contracts and do not edit them or shared exports.
- Preconditions: Snapshot/store contracts and local embedding runtime are merged; canonical legal, public-patent, prosecution, and authorized private partitions are available by immutable manifests.
- Effects: Build fielded BM25 documents/postings, vector mappings/indexes, and provenance graph nodes/edges incrementally; checkpoint per shard; verify count parity and CID referential integrity; support compaction, tombstones and rollback.
- Acceptance: Full and incremental builds converge on the same logical root; interrupted builds resume; every vector/BM25/graph record has one allowed source join; private partitions remain encrypted and unpublishable; zero-orphan and deterministic-manifest tests pass.

## PATLAW-147 Implement explainable hybrid retrieval and real-corpus evaluation

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-indexes
- Depends on: PATLAW-123, PATLAW-139, PATLAW-146
- Goal id: PATLAW-G161
- Outputs: ipfs_datasets_py/processors/domains/patent/hybrid_retrieval_v2.py, ipfs_datasets_py/processors/domains/patent/retrieval_evaluation_v2.py, tests/integration/processors/patent/test_persistent_hybrid_retrieval.py, tests/fixtures/patent/retrieval/qrels_v2.json
- Validation: python -m pytest tests/integration/processors/patent/test_persistent_hybrid_retrieval.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-hybrid-evaluation
- Parallel lane: patlaw-v2-lane-3
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 22000
- Predicted files: ipfs_datasets_py/processors/domains/patent/hybrid_retrieval_v2.py, ipfs_datasets_py/processors/domains/patent/retrieval_evaluation_v2.py, tests/integration/processors/patent/test_persistent_hybrid_retrieval.py, tests/fixtures/patent/retrieval/qrels_v2.json
- Allow concurrent with: PATLAW-152, PATLAW-156, PATLAW-161
- Conflict policy: Own v2 fusion/evaluation modules, qrels, and focused tests only; do not tune on held-out labels, bypass pre-retrieval access/time filters, or elevate generated text or candidate graph edges to authority.
- Preconditions: Persistent snapshots and executable gold-metric infrastructure are merged; public-official held-out cases have reviewed qrels and coverage labels.
- Effects: Apply tenant/disclosure/as-of filters first, fuse fielded BM25, dense similarity, CPC/IPC, citations, families and graph paths, expose per-component contributions, and compute recall, ranking, citation, temporal, provenance, coverage and isolation metrics.
- Acceptance: Versioned thresholds fail on intentionally degraded retrieval; each result exposes source spans and score contributions; receipts bind snapshot/model/config/qrels; isolation tests count zero denied calls/results; missing source coverage is reported rather than scored as searched.

## PATLAW-148 Add a live public-patent prior-art search adapter and journal

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: prior-art-operations
- Depends on: PATLAW-124, PATLAW-144
- Goal id: PATLAW-G162
- Outputs: ipfs_datasets_py/processors/domains/patent/prior_art_runtime.py, ipfs_datasets_py/processors/domains/patent/search_journal.py, tests/integration/processors/patent/test_public_prior_art_runtime.py
- Validation: python -m pytest tests/integration/processors/patent/test_public_prior_art_runtime.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-prior-art-runtime
- Parallel lane: patlaw-v2-lane-0
- Resource class: io-large
- Token class: xlarge
- Estimated tokens: 21000
- Predicted files: ipfs_datasets_py/processors/domains/patent/prior_art_runtime.py, ipfs_datasets_py/processors/domains/patent/search_journal.py, tests/integration/processors/patent/test_public_prior_art_runtime.py
- Allow concurrent with: PATLAW-146, PATLAW-152, PATLAW-156, PATLAW-161
- Conflict policy: Own new public search runtime/journal modules and tests only; do not scrape authenticated USPTO interfaces, claim Patent Public Search is an API, query private matters, or edit hybrid retrieval implementation.
- Preconditions: Production ODP/public patent access and persistent index contracts are available; official interactive verification remains a documented human step.
- Effects: Execute bounded local/ODP public searches from explicit query plans, record keywords/classifications/filters/cutoffs/results/scores/retries and source snapshots, and emit replayable content-addressed search journals.
- Acceptance: Recorded transports and local snapshots replay identically; every query identifies database, time and cutoff; failures and rate limits remain explicit; journal cannot represent foreign or NPL sources as searched unless a named adapter actually ran.

## PATLAW-149 Decompose claims into reviewed limitations and search plans

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: prior-art-operations
- Depends on: PATLAW-122, PATLAW-134, PATLAW-147
- Goal id: PATLAW-G162
- Outputs: ipfs_datasets_py/processors/domains/patent/claim_search_planner_v2.py, tests/unit/processors/patent/test_claim_search_planner_v2.py
- Validation: python -m pytest tests/unit/processors/patent/test_claim_search_planner_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-claim-search-plan
- Parallel lane: patlaw-v2-lane-1
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 15000
- Predicted files: ipfs_datasets_py/processors/domains/patent/claim_search_planner_v2.py, tests/unit/processors/patent/test_claim_search_planner_v2.py
- Allow concurrent with: PATLAW-150, PATLAW-152, PATLAW-156, PATLAW-161
- Conflict policy: Own the v2 claim/search-plan module and tests only; do not overwrite claims, infer an invention date, produce a patentability conclusion, or admit model candidates without deterministic and human review.
- Preconditions: Exact claim/source contracts, instruction assurance, and evaluated hybrid retrieval are merged; the user supplies or confirms relevant dates and jurisdictions.
- Effects: Version claim text, propose atomic limitations, synonyms, concepts, CPC/IPC candidates, date/jurisdiction filters and query families, retain candidate origin/confidence, and require explicit reviewer acceptance before execution.
- Acceptance: Every limitation and query maps to exact claim spans and version; amendments invalidate stale plans; ambiguous constructions remain alternatives; negative tests prevent omitted limitations, invented dates and unreviewed candidate promotion.

## PATLAW-150 Expand citations, families, foreign patents, and NPL coverage

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: prior-art-operations
- Depends on: PATLAW-124, PATLAW-148
- Goal id: PATLAW-G162
- Outputs: ipfs_datasets_py/processors/domains/patent/prior_art_coverage.py, ipfs_datasets_py/processors/domains/patent/prior_art_adapters.py, tests/integration/processors/patent/test_prior_art_coverage.py
- Validation: python -m pytest tests/integration/processors/patent/test_prior_art_coverage.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-prior-art-coverage
- Parallel lane: patlaw-v2-lane-2
- Resource class: io-large
- Token class: xlarge
- Estimated tokens: 21000
- Predicted files: ipfs_datasets_py/processors/domains/patent/prior_art_coverage.py, ipfs_datasets_py/processors/domains/patent/prior_art_adapters.py, tests/integration/processors/patent/test_prior_art_coverage.py
- Allow concurrent with: PATLAW-149, PATLAW-152, PATLAW-156, PATLAW-161
- Conflict policy: Own coverage/adapters and tests only; require approved public or licensed sources, preserve terms and access receipts, and never redistribute restricted NPL or misstate a source as searched after adapter failure.
- Preconditions: Reproducible public search journals and family/continuity facts are available; each additional source has an explicit rights, authentication and retention policy.
- Effects: Traverse backward/forward citations, priority and continuation families, add approved foreign-patent and NPL metadata/search adapters, normalize identifiers, deduplicate families, and emit searched/unsearched/failed coverage declarations.
- Acceptance: Coverage records every adapter, query, timestamp, cutoff, rights status and result count; inaccessible or unlicensed sources remain named gaps; citation/family traversal is cycle-safe; NPL content cannot enter a public release without separate rights approval.

## PATLAW-151 Produce source-quoted claim charts and an IDS review queue

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: prior-art-operations
- Depends on: PATLAW-147, PATLAW-149, PATLAW-150
- Goal id: PATLAW-G162
- Outputs: ipfs_datasets_py/processors/domains/patent/claim_chart_v2.py, ipfs_datasets_py/processors/domains/patent/ids_review_queue.py, tests/integration/processors/patent/test_prior_art_review_v2.py
- Validation: python -m pytest tests/integration/processors/patent/test_prior_art_review_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-claim-chart-review
- Parallel lane: patlaw-v2-lane-3
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 22000
- Predicted files: ipfs_datasets_py/processors/domains/patent/claim_chart_v2.py, ipfs_datasets_py/processors/domains/patent/ids_review_queue.py, tests/integration/processors/patent/test_prior_art_review_v2.py
- Allow concurrent with: PATLAW-152, PATLAW-156, PATLAW-161
- Conflict policy: Own v2 claim-chart and IDS-review modules/tests only; do not file an IDS, make a legal materiality or patentability determination, omit negative evidence, or copy unlicensed NPL text.
- Preconditions: Reviewed claim-search plans, evaluated hybrid retrieval, and explicit source-coverage declarations are merged.
- Effects: Align accepted claim limitations with exact patent/NPL source spans, record supporting and contradictory passages, rankings and reviewer dispositions, route possible references to a human IDS queue, and require a signed searched/gap acknowledgement.
- Acceptance: Every chart cell links claim and evidence spans or says not found/unknown; coverage gaps remain prominent; reviewer changes are versioned; no reference enters an IDS-ready state without natural-person relevance/materiality review and no output claims an exhaustive search.

## PATLAW-152 Build an authorized tenant-isolated portfolio review service

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: portfolio-review
- Depends on: PATLAW-124, PATLAW-125, PATLAW-136
- Goal id: PATLAW-G171
- Outputs: ipfs_datasets_py/processors/domains/uspto/portfolio_service.py, tests/integration/processors/domains/uspto/test_portfolio_review.py, tests/security/test_private_portfolio_isolation.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_portfolio_review.py tests/security/test_private_portfolio_isolation.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-portfolio-review
- Parallel lane: patlaw-v2-lane-0
- Resource class: io-medium
- Token class: xlarge
- Estimated tokens: 21000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/portfolio_service.py, tests/integration/processors/domains/uspto/test_portfolio_review.py, tests/security/test_private_portfolio_isolation.py
- Allow concurrent with: PATLAW-146, PATLAW-149, PATLAW-150, PATLAW-151, PATLAW-156, PATLAW-161
- Conflict policy: Own the new portfolio service and focused tests only; do not edit shared API/CLI/MCP registries, enumerate an authenticated Patent Center account, store credentials/cookies, or expose private matter existence across tenants.
- Preconditions: Durable matter runtime, document jobs, and resumable analysis are merged; access is limited to known public identifiers and explicit user-authorized local imports.
- Effects: Reconcile public ODP facts and encrypted imported exports into tenant-scoped matter summaries, lifecycle, Office Action, claim-rejection, submission, receipt, gap and reviewer-action views while preserving source and observed-time identity.
- Acceptance: Public/private versions reconcile without disclosure downgrade; rejected is not treated as terminal; delayed or absent upstream records remain unknown; authorization and tenant isolation tests expose no record, count, timing or search oracle to an unauthorized caller.

## PATLAW-153 Compile a rule- and prior-art-aware filing package

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: filing-handoff
- Depends on: PATLAW-133, PATLAW-137, PATLAW-138, PATLAW-151, PATLAW-152
- Goal id: PATLAW-G172
- Outputs: ipfs_datasets_py/processors/domains/uspto/filing_package.py, tests/unit/processors/domains/uspto/test_filing_package.py, tests/fixtures/uspto/filing_package/golden_manifest.json
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_filing_package.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-filing-package
- Parallel lane: patlaw-v2-lane-1
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 24000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/filing_package.py, tests/unit/processors/domains/uspto/test_filing_package.py, tests/fixtures/uspto/filing_package/golden_manifest.json
- Allow concurrent with: PATLAW-156, PATLAW-161
- Conflict policy: Own the package compiler, manifest fixture and tests only; do not edit source documents in place, select legal strategy, sign, pay, file, or claim unsupported Patent Center validation.
- Preconditions: Submission semantics, approved filing-obligation packs, authoritative candidate dates, prior-art coverage signoff, and authorized portfolio facts are available as immutable reviewed inputs.
- Effects: Assemble original DOCX/PDF, drawings inventory, proposed ADS fields, forms/fees checklist, priority/inventorship/new-matter/nonpublication/export/IDS review items, warnings, source roots and exact content digests without asserting human certifications.
- Acceptance: Any material input change invalidates approval; missing or stale mandatory rules, unresolved prior-art coverage, digest mismatch or required human confirmation blocks validated state; output distinguishes proposed metadata, original files, rendered derivatives and operator checklist.

## PATLAW-154 Implement the human Patent Center handoff state machine

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: filing-handoff
- Depends on: PATLAW-153
- Goal id: PATLAW-G172
- Outputs: ipfs_datasets_py/processors/domains/uspto/patent_center_handoff.py, tests/integration/processors/domains/uspto/test_patent_center_handoff.py, docs/operations/PATENT_CENTER_HUMAN_HANDOFF.md
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_patent_center_handoff.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-patent-center-handoff
- Parallel lane: patlaw-v2-lane-2
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/patent_center_handoff.py, tests/integration/processors/domains/uspto/test_patent_center_handoff.py, docs/operations/PATENT_CENTER_HUMAN_HANDOFF.md
- Allow concurrent with: PATLAW-156, PATLAW-161
- Conflict policy: Own the handoff state machine, test and runbook only; no browser control, login, MFA, credential, signature, payment, filing, or fabricated training/live receipt capability may be introduced.
- Preconditions: A validated, exact-digest filing package exists and named inventor/practitioner review responsibilities are explicit.
- Effects: Record draft, validated, human-approved, exported, user-submitted and receipt-verified transitions; generate content-free instructions for training and live Patent Center review; require the user to record the submitted digest and download official artifacts.
- Acceptance: Invalid transitions fail; system cannot advance past exported without an external human assertion and cannot advance to receipt-verified without verified official artifacts; tests prove no network/browser/session/payment interface exists.

## PATLAW-155 Reconcile official filing receipts and converted artifacts

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: filing-handoff
- Depends on: PATLAW-124, PATLAW-154
- Goal id: PATLAW-G172
- Outputs: ipfs_datasets_py/processors/domains/uspto/filing_receipt_reconciler.py, tests/integration/processors/domains/uspto/test_filing_receipt_reconciler.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_filing_receipt_reconciler.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-filing-receipts
- Parallel lane: patlaw-v2-lane-3
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 17000
- Predicted files: ipfs_datasets_py/processors/domains/uspto/filing_receipt_reconciler.py, tests/integration/processors/domains/uspto/test_filing_receipt_reconciler.py
- Allow concurrent with: PATLAW-156, PATLAW-161
- Conflict policy: Own the new receipt reconciler and tests only; do not edit the durable store implementation, treat a payment receipt alone as filing acknowledgement, or log private content.
- Preconditions: Human handoff recorded an approved/submitted package digest; acknowledgement, payment and USPTO-converted artifacts arrive only through explicit authorized import.
- Effects: Parse and cross-check application/customer/confirmation identifiers, submitted filenames/digests, timestamps, document counts, conversion differences, acknowledgement and payment evidence, then append immutable reconciliation events to the matter ledger.
- Acceptance: Exact and expected conversion cases verify with disclosed differences; wrong matter, missing acknowledgement, mismatched files, partial submission or payment-only cases remain conflicting/incomplete; filed status requires the authoritative acknowledgement rule defined by the reviewed policy.

## PATLAW-156 Define Viewer-compatible JusticeDAO layouts and migration metadata

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: hub-build
- Depends on: PATLAW-100, PATLAW-101, PATLAW-102, PATLAW-135, PATLAW-139
- Goal id: PATLAW-G181
- Outputs: ipfs_datasets_py/processors/domains/patent/hf_layout_v2.py, docs/architecture/JUSTICEDAO_PATENT_LEGAL_LAYOUT.md, tests/unit/processors/patent/test_hf_layout_v2.py
- Validation: python -m pytest tests/unit/processors/patent/test_hf_layout_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-hub-layout
- Parallel lane: patlaw-v2-lane-0
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 16000
- Predicted files: ipfs_datasets_py/processors/domains/patent/hf_layout_v2.py, docs/architecture/JUSTICEDAO_PATENT_LEGAL_LAYOUT.md, tests/unit/processors/patent/test_hf_layout_v2.py
- Allow concurrent with: PATLAW-146, PATLAW-149, PATLAW-150, PATLAW-151, PATLAW-152, PATLAW-161
- Conflict policy: Own the new layout contract, architecture note and tests only; do not rename/delete existing Hub repositories, upload, edit the generic publisher, or embed a token.
- Preconditions: V1 local release profiles, temporal authority snapshots and approved public corpus manifests are available; current JusticeDAO repository inventory and Viewer failures are captured as immutable operator inputs.
- Effects: Define lowercase organization/repository identities, corpus and separate vector/BM25/knowledge-graph configs, root Parquet patterns, JSON-LD/manifests, dataset cards, version tags, migration pointers, coverage/current-through fields and CID joins compatible with Dataset Viewer.
- Acceptance: Generated cards/configs enumerate sources, licenses, official-edition cutoffs, freshness, gaps, parser/model versions and responsible use; Viewer file patterns resolve; old repositories can point forward without data deletion; private configs cannot be declared.

## PATLAW-157 Build deterministic public corpus, index, and graph release artifacts

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: hub-build
- Depends on: PATLAW-146, PATLAW-147, PATLAW-151, PATLAW-156
- Goal id: PATLAW-G181
- Outputs: ipfs_datasets_py/processors/domains/patent/hf_release_v2.py, scripts/ops/legal_data/build_patent_hf_release_v2.py, tests/unit/processors/patent/test_hf_release_v2.py
- Validation: python -m pytest tests/unit/processors/patent/test_hf_release_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-hub-release-build
- Parallel lane: patlaw-v2-lane-1
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 24000
- Predicted files: ipfs_datasets_py/processors/domains/patent/hf_release_v2.py, scripts/ops/legal_data/build_patent_hf_release_v2.py, tests/unit/processors/patent/test_hf_release_v2.py
- Allow concurrent with: PATLAW-161
- Conflict policy: Own the v2 builder, build script and tests only; retain dry-run default, do not authenticate/upload, and do not reuse private, mixed, unreviewed or unlicensed inputs.
- Preconditions: Viewer layout, persistent public indexes, evaluated retrieval and reviewed prior-art/public corpus manifests are merged.
- Effects: Build deterministic Parquet corpus/config shards, vector mappings/artifacts, BM25 documents/terms/postings, graph nodes/edges/JSON-LD, cards, coverage/quality reports and a release manifest binding source/index/evaluation roots.
- Acceptance: Repeat builds are byte-stable; counts and CIDs agree across projections; no orphan joins; authoritative and AI-derived fields remain separate; every artifact carries rights/privacy/source review; private or mixed input fails before any filesystem staging.

## PATLAW-158 Enforce public-release DLP, rights, and Dataset Viewer gates

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: hub-build
- Depends on: PATLAW-157
- Goal id: PATLAW-G181
- Outputs: ipfs_datasets_py/processors/domains/patent/hf_release_policy_v2.py, scripts/ops/legal_data/verify_patent_hf_viewer.py, tests/security/test_patent_hf_release_v2.py
- Validation: python -m pytest tests/security/test_patent_hf_release_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-hub-release-gates
- Parallel lane: patlaw-v2-lane-2
- Resource class: cpu-medium
- Token class: large
- Estimated tokens: 17000
- Predicted files: ipfs_datasets_py/processors/domains/patent/hf_release_policy_v2.py, scripts/ops/legal_data/verify_patent_hf_viewer.py, tests/security/test_patent_hf_release_v2.py
- Allow concurrent with: PATLAW-161
- Conflict policy: Own v2 release policy, Viewer verifier and security tests only; do not authenticate, upload, approve rights, weaken v1 policy, or treat a successful HTTP response as a valid dataset.
- Preconditions: Deterministic v2 release artifacts and their classification/rights/source manifests are available in a local staging directory.
- Effects: Scan artifact bytes, metadata, cards, embeddings, graph and manifests for forbidden classifications/identifiers/content; verify rights receipts, source/current-through disclosure, count parity and Hub Dataset Viewer is-valid/splits/rows/parquet/size/statistics response contracts against a fake service.
- Acceptance: Private/mixed/unknown rights, orphan rows, missing cards/configs, invalid Parquet, stale mandatory sources, inconsistent counts or failed Viewer features block admission before credentials are resolved; adversarial encoded/private leakage fixtures fail.

## PATLAW-159 Stage an authenticated Hub PR with exact human approval

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: hub-publication
- Depends on: PATLAW-158
- Goal id: PATLAW-G182
- Outputs: ipfs_datasets_py/processors/domains/patent/hf_publisher_v2.py, scripts/ops/legal_data/stage_patent_hf_release.py, tests/integration/processors/patent/test_hf_publication_v2.py
- Validation: python -m pytest tests/integration/processors/patent/test_hf_publication_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-hub-stage-publish
- Parallel lane: patlaw-v2-lane-3
- Resource class: io-large
- Token class: xlarge
- Estimated tokens: 23000
- Predicted files: ipfs_datasets_py/processors/domains/patent/hf_publisher_v2.py, scripts/ops/legal_data/stage_patent_hf_release.py, tests/integration/processors/patent/test_hf_publication_v2.py
- Allow concurrent with: PATLAW-161
- Conflict policy: Own the v2 publisher, staging command and fake-service integration tests only; no direct-main upload, embedded token, unattended approval, supervisor self-approval, repository deletion, or pointer promotion is allowed.
- Preconditions: Release candidate passed local DLP/rights/Viewer gates; a scoped Hub token is resolved only by the operator command; target owner/repositories and expected base revisions are explicit.
- Effects: Create an add-only branch or pull request against exact base revisions, upload only manifest-enumerated artifacts, return a staged diff and commit identity, require a separate operator-signed approval binding the release root and diff, and then perform the approved promotion transaction.
- Acceptance: Missing/wrong approval, changed base, changed artifact, conflict, partial upload, auth error or race cannot publish main/pointers; fake service proves credentials stay out of receipts; the implementation agent cannot generate the operator approval it consumes.

## PATLAW-160 Verify pinned Hub downloads and exercise rollback

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: hub-publication
- Depends on: PATLAW-159
- Goal id: PATLAW-G182
- Outputs: scripts/ops/legal_data/verify_patent_hf_release_v2.py, docs/operations/PATENT_HF_RELEASE_V2.md, tests/release/test_patent_hf_release_v2.py
- Validation: python -m pytest tests/release/test_patent_hf_release_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-hub-verify-rollback
- Parallel lane: patlaw-v2-lane-0
- Resource class: io-large
- Token class: large
- Estimated tokens: 19000
- Predicted files: scripts/ops/legal_data/verify_patent_hf_release_v2.py, docs/operations/PATENT_HF_RELEASE_V2.md, tests/release/test_patent_hf_release_v2.py
- Allow concurrent with: PATLAW-162
- Conflict policy: Own pinned verifier, release/rollback runbook and tests only; do not alter released bytes, delete commits, silently select latest, or promote/roll back without an exact operator receipt.
- Preconditions: A staged or promoted Hub commit and local canonical release manifest are available; fake-service tests cover all network paths and live verification remains explicit/operator-invoked.
- Effects: Redownload every manifest file at the exact Hub commit SHA, verify SHA/CID/size/schema/counts, query Viewer endpoints, record canary outcome, and exercise an approval-bound pointer rollback that preserves both releases and audit evidence.
- Acceptance: Any missing/changed artifact, unpinned request, Viewer failure or manifest mismatch blocks promotion; successful receipt binds repository IDs, Hub SHA, release CID, all artifact hashes and Viewer results; rollback changes only the reviewed pointer and is itself pinned and verifiable.

## PATLAW-161 Implement safe paired-repository integration worktrees

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: cross-repo-integration
- Depends on: PATLAW-080
- Goal id: PATLAW-G191
- Outputs: scripts/ops/uspto/integrate_upstreams.py, scripts/ops/uspto/sync_upstreams.sh, tests/integration/processors/domains/uspto/test_cross_repo_integration_v2.py, data/release/uspto_submission_assurance/paired_revision_receipt.schema.json
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_cross_repo_integration_v2.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-cross-repo-integration
- Parallel lane: patlaw-v2-lane-1
- Resource class: io-medium
- Token class: xlarge
- Estimated tokens: 22000
- Predicted files: scripts/ops/uspto/integrate_upstreams.py, scripts/ops/uspto/sync_upstreams.sh, tests/integration/processors/domains/uspto/test_cross_repo_integration_v2.py, data/release/uspto_submission_assurance/paired_revision_receipt.schema.json
- Allow concurrent with: PATLAW-144, PATLAW-145, PATLAW-146, PATLAW-147, PATLAW-148, PATLAW-149, PATLAW-150, PATLAW-151, PATLAW-152, PATLAW-153, PATLAW-154, PATLAW-155, PATLAW-156, PATLAW-157, PATLAW-158, PATLAW-159
- Conflict policy: This task is the sole v2 owner of cross-repository integration logic and the existing sync wrapper; it may not edit the accelerator repository, run pull in active worktrees, recurse mutual submodules, auto-resolve conflicts with an LLM, or push.
- Preconditions: Completed PATLAW-080 behavior and paired-repository test contracts are present; remote default branches, clean/active indicators, merge queue state and accelerator capability pin are explicit.
- Effects: Fetch exact remote tips, create isolated maintenance worktrees, merge and test the accelerator tip first through its reviewed workflow, merge/test the datasets tip against that accelerator SHA, quarantine conflicts, and emit a paired revision/test/merge disposition receipt.
- Acceptance: Dirty/active/locked/conflicting/missing-branch states abort without mutation; tests prove exact merge ordering, no active-worktree pull and no push; accepted receipt binds before/remote/integrated SHAs for both repositories, capability pin, test results, trigger and lock identity.

## PATLAW-162 Install recurring fetch, integration, and release triggers

- Status: completed
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: cross-repo-integration
- Depends on: PATLAW-161
- Goal id: PATLAW-G191
- Outputs: scripts/ops/uspto/sync_upstreams.sh, scripts/ops/uspto/install_sync_schedule.py, tests/integration/processors/domains/uspto/test_cross_repo_sync_schedule.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_cross_repo_sync_schedule.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-cross-repo-schedule
- Parallel lane: patlaw-v2-lane-2
- Resource class: io-small
- Token class: large
- Estimated tokens: 15000
- Predicted files: scripts/ops/uspto/sync_upstreams.sh, scripts/ops/uspto/install_sync_schedule.py, tests/integration/processors/domains/uspto/test_cross_repo_sync_schedule.py
- Allow concurrent with: PATLAW-160
- Conflict policy: Own schedule-template installation and the serialized sync wrapper after PATLAW-161; do not install without operator opt-in, overlap integration locks, edit user crontabs directly in tests, push, or weaken fail-closed active/dirty checks.
- Preconditions: Paired integration workflow is merged and its triggers/lock/receipt schema are stable.
- Effects: Provide idempotent systemd/cron template generation for eight-hour fetch, twice-daily integration, wave-boundary, pre-release and security-fix triggers; serialize all through one program-family lock and expose dry-run/uninstall/status commands.
- Acceptance: Fake-clock tests prove cadence, mutual exclusion, missed-run recovery and pre-release blocking; repeated install is idempotent; operator must explicitly activate generated templates; every run produces or references a paired-revision receipt and never pushes.

## PATLAW-163 Add content-free production freshness and release observability

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-assurance
- Depends on: PATLAW-135, PATLAW-147, PATLAW-155, PATLAW-160, PATLAW-162
- Goal id: PATLAW-G192
- Outputs: scripts/ops/patent_legal_intelligence/production_status.py, tests/integration/processors/domains/uspto/test_production_status.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_production_status.py -q
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-production-status
- Parallel lane: patlaw-v2-lane-3
- Resource class: cpu-small
- Token class: large
- Estimated tokens: 16000
- Predicted files: scripts/ops/patent_legal_intelligence/production_status.py, tests/integration/processors/domains/uspto/test_production_status.py
- Allow concurrent with:
- Conflict policy: Own the new production status surface and tests only; do not edit the protected supervisor status tool, expose document/query content, infer legal readiness from task counts, or mutate sources, indexes, matters, Hub or sync state.
- Preconditions: Authority snapshots, evaluated indexes, filing receipts, Hub verification and paired-repository schedules emit stable content-free receipts.
- Effects: Aggregate freshness/current-through watermarks, source gaps/conflicts, matter polling lag, index roots/age, isolation incidents, filing-handoff states, Hub commit/Viewer health, sync pair age, merge queue and supervisor drained/completed state into machine-readable health.
- Acceptance: Healthy, stale, degraded, blocked, active, drained and completed are distinguished; stopped drained shards are not falsely unhealthy; missing mandatory receipt blocks readiness; output contains safe IDs/digests/counts/timestamps only and remains tenant/nonexistence-safe.

## PATLAW-164 Run the exact-tree patent legal production completion gate

- Status: pending
- Completion: manual
- Is schedulable: true
- Review only: false
- Priority: P0
- Track: production-assurance
- Depends on: PATLAW-143, PATLAW-151, PATLAW-155, PATLAW-160, PATLAW-163
- Goal id: PATLAW-G192
- Outputs: scripts/ops/uspto/validate_production_release.py, tests/release/test_patent_legal_production_release.py, data/release/patent_legal_intelligence/production_receipt.schema.json, docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md
- Validation: python -m pytest tests/release/test_patent_legal_production_release.py -q && python scripts/ops/uspto/validate_production_release.py --offline
- Board namespace: patent-legal-intelligence-v1
- Bundle: patlaw/v2-production-gate
- Parallel lane: patlaw-v2-lane-0
- Resource class: cpu-large
- Token class: xlarge
- Estimated tokens: 26000
- Predicted files: scripts/ops/uspto/validate_production_release.py, tests/release/test_patent_legal_production_release.py, data/release/patent_legal_intelligence/production_receipt.schema.json, docs/operations/PATENT_LEGAL_PRODUCTION_RELEASE.md
- Allow concurrent with:
- Conflict policy: Own the final production gate, test, receipt schema and runbook only; do not modify implementation modules, accept task status as evidence, skip declared suites, fabricate live receipts, or relax a mandatory unknown/failed gate.
- Preconditions: V2 functional release evidence, reviewed prior-art coverage, filing receipt workflow, verified Hub release and production status are merged on the exact target tree; independent human legal/publication approvals are supplied separately where required.
- Effects: Execute the declared offline suites, validate optional live canary receipts when claimed, bind official source roots/current-through values, corpus/index/model/qrels roots, retrieval metrics, private isolation/provider-call counts, filing handoff/receipt results, Hub commit/Viewer verification, paired repository SHAs, supervisor merge receipts, config and git tree.
- Acceptance: One content-free immutable receipt proves every mandatory gate on the current tree; mismatched/stale/missing/unknown evidence blocks; no legal opinion, patentability guarantee, filing claim or publication claim appears without the corresponding reviewed evidence; root goal remains active until this receipt and every child receipt validate.
