# Patent Legal Intelligence Objective Heap

This heap is the durable goal/subgoal hierarchy for the
[USPTO Submission Assurance and Patent Legal Intelligence Plan](PATENT_LEGAL_INTELLIGENCE_PLAN.md).
The executable task projection is
[`patent_legal_intelligence.todo.md`](patent_legal_intelligence.todo.md).

Program invariants:

- Implementation lands only on `feature/patent-legal-intelligence`.
- Public ODP retrieval and authorized private import are different providers
  and different trust domains.
- No processor logs in to Patent Center, automates MFA, signs, pays, or files.
- Confidential artifacts never enter public IPFS, public datasets, external
  prompts, ordinary logs, or telemetry.
- Legal/compliance aggregation fails closed; uncertainty creates review work.
- Every conclusion binds an exact artifact span and time-versioned authority.
- Goal completion requires fresh current-tree evidence, not task status alone.

## PATLAW-G000 Deliver verified patent-law, public-patent, and USPTO submission assurance

- Status: active
- Parent:
- Fib priority: 1
- Track: patent-legal-intelligence
- Priority: P0
- Bundle: patlaw/root
- Goal: Deliver a safe, replayable processor system that verifies official patent authorities, retrieves public and authorized private USPTO matter records, parses correspondence and submissions, indexes public law/patent/prosecution evidence with BM25/vector/knowledge-graph retrieval, produces reproducible prior-art and filing-review artifacts, publishes approved public shards to JusticeDAO, and preserves mandatory human legal and filing control.
- Evidence: PATLAW-G010, PATLAW-G020, PATLAW-G030, PATLAW-G040, PATLAW-G050, PATLAW-G060, PATLAW-G070, PATLAW-G080, PATLAW-G090, PATLAW-G100
- Outputs: ipfs_datasets_py/processors, ipfs_datasets_py/processors/legal_scrapers/federal_scrapers, ipfs_datasets_py/processors/legal_data, ipfs_datasets_py/knowledge_graphs, ipfs_datasets_py/huggingface, ipfs_datasets_py/mcp_server, ipfs_datasets_py/cli, tests
- Validation: python -m pytest tests/integration/processors tests/e2e/test_uspto_application_analysis.py -q
- Acceptance: Every child goal is complete with fresh evidence on the target tree; reviewed public and synthetic private fixtures replay to provenance-complete authority, status, requirement, evidence, retrieval, prior-art, candidate-date, and human-review reports; approved public release re-downloads verify; private isolation and no-sign/no-file/no-pay boundaries pass.
- Gap task: Implement the highest-priority incomplete child goal without weakening privacy, authority, provenance, or human-review gates.
- Refinement: Phase 0 foundation is mandatory; acquisition and authority work parallelize next; shared exports and final gates are serialized.
- Embedding query: USPTO patent application status office action submission completeness PDF DOCX law CFR Federal Register provenance privacy human review
- AST query: UniversalProcessor PDFProcessor CitationExtractor SupportMapBuilder LegalIRCompilerAPI

## PATLAW-G010 Establish a trustworthy processor and privacy foundation

- Status: active
- Parent: PATLAW-G000
- Fib priority: 1
- Track: foundation
- Priority: P0
- Bundle: patlaw/foundation
- Goal: Unify processor contracts and routing, connect the real PDF pipeline, repair OCR and disclosure defects, make legal verification fail closed, and establish versioned USPTO/privacy contracts before domain processors depend on them.
- Evidence: PATLAW-G011, PATLAW-G012, PATLAW-G013, PATLAW-008
- Outputs: ipfs_datasets_py/processors/core, ipfs_datasets_py/processors/adapters, ipfs_datasets_py/processors/specialized/pdf, ipfs_datasets_py/processors/domains/uspto/contracts.py, ipfs_datasets_py/processors/domains/uspto/privacy.py
- Validation: python -m pytest tests/integration/processors/test_uspto_processor_foundation.py -q
- Acceptance: One canonical runtime contract routes a real PDF through safe extraction; private content does not reach disclosure sinks; empty/failed proof cannot pass; USPTO artifacts cross an explicit classification gate.
- Gap task: Close the next Phase 0 contract, PDF, fail-closed, or privacy-foundation gap with focused tests.
- Refinement: Do not build status or analysis processors on placeholder adapters or implicit legacy routing.
- Embedding query: canonical processor protocol registry PDF OCR fail closed privacy boundary
- AST query: ProcessorProtocol ProcessingContext UniversalProcessor PDFProcessorAdapter FormRequirementsVerifier

## PATLAW-G011 Unify processor contracts and routing

- Status: active
- Parent: PATLAW-G010
- Fib priority: 1
- Track: processor-runtime
- Priority: P0
- Bundle: patlaw/runtime
- Goal: Make the core ProcessingContext/can_handle protocol canonical and preserve legacy public imports only through explicit compatibility adapters and result conversion.
- Evidence: PATLAW-002, PATLAW-003
- Outputs: ipfs_datasets_py/processors/core, ipfs_datasets_py/processors/adapters/legacy_protocol_adapter.py, tests/unit/processors/core, tests/integration/processors/test_universal_processor_routing.py
- Validation: python -m pytest tests/unit/processors/core tests/integration/processors/test_universal_processor_routing.py -q
- Acceptance: Registration, discovery, capability checks, execution, and result conversion use one runtime contract with no isinstance failure or silent empty registry.
- Gap task: Implement the next contract or routing repair and preserve explicit backward compatibility.
- Refinement: Separate protocol decision from registry migration so dependent work can review the ADR first.
- Embedding query: protocol unification can_handle ProcessingContext legacy adapter registry
- AST query: ProcessorProtocol ProcessorRegistry UniversalProcessor

## PATLAW-G012 Make PDF and OCR extraction real, complete, and non-disclosing

- Status: active
- Parent: PATLAW-G010
- Fib priority: 2
- Track: document-foundation
- Priority: P0
- Bundle: patlaw/pdf
- Goal: Repair page rendering, OCR invocation, native/OCR merge, quality scoring, and logging so the adapter returns real page/span provenance without disclosing private text.
- Evidence: PATLAW-004, PATLAW-007
- Outputs: ipfs_datasets_py/processors/specialized/pdf, ipfs_datasets_py/processors/adapters/pdf_adapter.py, tests/fixtures/uspto/pdf
- Validation: python -m pytest tests/unit/processors/specialized/pdf tests/unit/processors/adapters/test_pdf_adapter_real_pipeline.py tests/security/test_private_pdf_non_disclosure.py -q
- Acceptance: Native and scanned pages are extracted through the real pipeline; unavailable engines and low coverage are explicit; no text reaches stdout/log/debug/telemetry sinks.
- Gap task: Repair the next extraction correctness or disclosure gap with a synthetic regression fixture.
- Refinement: OCR repair can proceed in parallel with runtime contract work; adapter wiring follows both.
- Embedding query: scanned legal PDF deterministic rendering OCR merge bounding box privacy logs
- AST query: PDFProcessor MultiEngineOCR PDFProcessorAdapter

## PATLAW-G013 Enforce fail-closed verification and artifact classification

- Status: active
- Parent: PATLAW-G010
- Fib priority: 3
- Track: assurance-foundation
- Priority: P0
- Bundle: patlaw/analysis
- Goal: Replace vacuous success with explicit unknown/review outcomes and require public/private/restricted classification before dispatch or storage.
- Evidence: PATLAW-005, PATLAW-006
- Outputs: ipfs_datasets_py/processors/form_requirements_verifier.py, ipfs_datasets_py/processors/legal_data/neurosymbolic.py, ipfs_datasets_py/processors/domains/uspto/contracts.py, ipfs_datasets_py/processors/domains/uspto/privacy.py, ipfs_datasets_py/processors/domains/uspto/artifact_manifest.py
- Validation: python -m pytest tests/unit/processors/test_patent_compliance_fail_closed.py tests/security/test_uspto_public_private_isolation.py -q
- Acceptance: Missing requirements/evidence, skipped/errored proof, unknown classification, and forbidden sink attempts can never become a pass or public dispatch.
- Gap task: Add the next fail-closed or isolation invariant with an adversarial test.
- Refinement: Reuse the secrets vault for credentials only; private document storage needs a separate encrypted contract.
- Embedding query: fail closed unknown review required private public classification IPFS isolation
- AST query: FormRequirementsVerifier NeurosymbolicMatcher ArtifactManifest

## PATLAW-G020 Build a time-versioned patent authority corpus

- Status: active
- Parent: PATLAW-G000
- Fib priority: 2
- Track: legal-authority
- Priority: P0
- Bundle: patlaw/authority
- Goal: Acquire and reconcile exact release points and effective-time views of statutes, regulations, Federal Register changes, and lower-tier USPTO guidance needed to explain patent requirements.
- Evidence: PATLAW-G021, PATLAW-G022
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers, ipfs_datasets_py/processors/legal_data/patent_authority_registry.py
- Validation: python -m pytest tests/unit/processors/legal_data/test_patent_authority_registry.py tests/integration/legal_data/test_patent_authority_temporal_replay.py -q
- Acceptance: An as-of query distinguishes official base/change sources, derived current text, and guidance; proposed/withdrawn/future rules are not silently applied.
- Gap task: Implement the next official-source or temporal-authority obligation with pinned fixtures.
- Refinement: Source clients parallelize; temporal graph and citation verification follow their contracts.
- Embedding query: Title 35 Title 37 CFR Federal Register GovInfo eCFR MPEP effective date authority
- AST query: FederalRegisterScraper USCodeScraper temporal_authority

## PATLAW-G021 Acquire official and guidance source artifacts

- Status: active
- Parent: PATLAW-G020
- Fib priority: 1
- Track: source-acquisition
- Priority: P0
- Bundle: patlaw/authority
- Goal: Define a source registry and acquire eCFR/annual CFR, House OLRC/GovInfo U.S. Code, Federal Register/GovInfo change artifacts, and current MPEP/forms/fees guidance with immutable receipts.
- Evidence: PATLAW-011, PATLAW-012, PATLAW-013, PATLAW-014, PATLAW-015, PATLAW-018
- Outputs: ipfs_datasets_py/processors/legal_scrapers/federal_scrapers, tests/fixtures/legal_data/patent_authorities
- Validation: python -m pytest tests/unit/processors/legal_scrapers/federal_scrapers/test_patent_source_connectors.py -q
- Acceptance: Each connector is retryable, fixture-driven, version-aware, authority-labeled, and preserves raw artifact identity without hard-coded latest years.
- Gap task: Implement the next connector behind the common source/receipt contract.
- Refinement: Do not couple USPTO matter retrieval to legal-corpus network availability; operate from pinned local receipts.
- Embedding query: source registry eCFR annual CFR OLRC GovInfo Federal Register MPEP fees forms
- AST query: GovInfoClient AuthoritySourceRegistry SourceReceipt

## PATLAW-G022 Resolve temporal authority and exact citations

- Status: active
- Parent: PATLAW-G020
- Fib priority: 2
- Track: authority-resolution
- Priority: P0
- Bundle: patlaw/authority
- Goal: Materialize amendment/correction/withdrawal/effective edges and resolve statute, CFR, FR, MPEP, form-paragraph, and guidance citations to exact applicable source spans.
- Evidence: PATLAW-016, PATLAW-017
- Outputs: ipfs_datasets_py/processors/legal_data/patent_authority_registry.py, ipfs_datasets_py/processors/legal_data/patent_citation_resolver.py
- Validation: python -m pytest tests/unit/processors/legal_data/test_patent_temporal_authority.py tests/unit/processors/legal_data/test_patent_citation_resolver.py -q
- Acceptance: Mailing-date and proposed-response-date views are reproducible; quotes are checked against exact source spans; unresolved or conflicting authority is explicit.
- Gap task: Close the next temporal or citation-resolution case with a historical fixture.
- Refinement: Keep authority tier and applicability separate from semantic relevance score.
- Embedding query: temporal legal graph amendments corrections withdrawal effective citation exact quote
- AST query: CitationExtractor ConstraintSelector TemporalAuthorityGraph

## PATLAW-G030 Acquire authorized USPTO records and maintain a matter ledger

- Status: active
- Parent: PATLAW-G000
- Fib priority: 3
- Track: uspto-acquisition
- Priority: P0
- Bundle: patlaw/uspto
- Goal: Normalize application identity, retrieve public ODP status/events/documents, import authorized private exports, and reconcile all versions into an idempotent matter ledger.
- Evidence: PATLAW-G031, PATLAW-G032
- Outputs: ipfs_datasets_py/processors/domains/uspto/providers, ipfs_datasets_py/processors/domains/uspto/application_status_processor.py, ipfs_datasets_py/processors/domains/uspto/document_sync_processor.py, ipfs_datasets_py/processors/domains/uspto/matter_ledger.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_matter_sync.py -q
- Acceptance: Public and private paths remain separate; status/doc changes are versioned; missing/delayed data is not misreported as nonreceipt; sync resumes without duplicate artifacts.
- Gap task: Implement the next identity, provider, synchronization, or ledger obligation with recorded HTTP/import fixtures.
- Refinement: Supported APIs only; no Patent Center browser automation.
- Embedding query: USPTO ODP Patent File Wrapper status transactions documents private export matter ledger
- AST query: ApplicationStatusProcessor DocumentSyncProcessor PatentFileWrapperClient

## PATLAW-G031 Implement the public Patent File Wrapper provider

- Status: active
- Parent: PATLAW-G030
- Fib priority: 1
- Track: public-uspto
- Priority: P0
- Bundle: patlaw/uspto
- Goal: Implement API-key-authenticated, paginated, bounded, resumable ODP retrieval for application data, status, transactions, document metadata, and authorized public bytes.
- Evidence: PATLAW-019, PATLAW-020, PATLAW-021, PATLAW-022, PATLAW-023
- Outputs: ipfs_datasets_py/processors/domains/uspto/identifiers.py, ipfs_datasets_py/processors/domains/uspto/providers/patent_file_wrapper.py, ipfs_datasets_py/processors/domains/uspto/application_status_processor.py, ipfs_datasets_py/processors/domains/uspto/document_sync_processor.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/providers/test_patent_file_wrapper.py tests/integration/processors/domains/uspto/test_public_status_sync.py -q
- Acceptance: 401/403, 404, 429/Retry-After, 5xx, pagination, schema drift, and content changes have typed outcomes and no invented rate limit.
- Gap task: Add the next ODP contract or status/document normalization behavior with a recorded fixture.
- Refinement: Optional Office Action Citations can supplement but never replace raw file-wrapper documents.
- Embedding query: api.uspto.gov X-Api-Key application data status transactions documents Retry-After
- AST query: PatentFileWrapperClient ApplicationIdentity SourceReceipt

## PATLAW-G032 Import private exports and reconcile the matter ledger

- Status: active
- Parent: PATLAW-G030
- Fib priority: 2
- Track: private-uspto
- Priority: P0
- Bundle: patlaw/uspto
- Goal: Import explicitly authorized local Patent Center artifacts into encrypted tenant storage and reconcile originals, converted files, GUI metadata, receipts, and public wrapper records.
- Evidence: PATLAW-024, PATLAW-025
- Outputs: ipfs_datasets_py/processors/domains/uspto/providers/patent_center_export.py, ipfs_datasets_py/processors/domains/uspto/matter_ledger.py, ipfs_datasets_py/processors/domains/uspto/private_store.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/providers/test_patent_center_export.py tests/security/test_uspto_private_import.py -q
- Acceptance: Imports cannot escape the authorized root or leak; original/derived/receipt relationships are explicit; browser credentials and payment data are rejected.
- Gap task: Close the next secure-import or reconciliation gap with synthetic private fixtures.
- Refinement: Encrypt before durable storage and preserve an authorization receipt without secret material.
- Embedding query: Patent Center authorized export encrypted tenant DOCX PDF acknowledgement payment receipt
- AST query: PatentCenterExportProvider PrivateArtifactStore MatterLedger

## PATLAW-G040 Understand correspondence, submissions, and receipts

- Status: active
- Parent: PATLAW-G000
- Fib priority: 5
- Track: document-understanding
- Priority: P0
- Bundle: patlaw/analysis
- Goal: Classify artifacts and extract page/span-provenanced government instructions, submissions, metadata, receipts, claims, and document-quality signals.
- Evidence: PATLAW-G041, PATLAW-G042
- Outputs: ipfs_datasets_py/processors/domains/uspto/document_classifier.py, ipfs_datasets_py/processors/domains/uspto/document_extraction_processor.py, ipfs_datasets_py/processors/domains/uspto/analysis
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_document_understanding.py -q
- Acceptance: Every extracted item points to validated source spans; unreadable/ambiguous/unsupported content is explicit and reaches review.
- Gap task: Implement the next classifier, extractor, or provenance requirement using synthetic documents.
- Refinement: Deterministic structure and citations precede model-assisted candidate extraction.
- Embedding query: office action submission receipt PDF DOCX document classification extraction provenance
- AST query: OfficeActionProcessor SubmissionProcessor ExtractedSpan

## PATLAW-G041 Classify and extract authoritative document content

- Status: active
- Parent: PATLAW-G040
- Fib priority: 1
- Track: document-extraction
- Priority: P0
- Bundle: patlaw/analysis
- Goal: Build artifact classification, PDF/DOCX/layout extraction, and source-span coverage/readability validation for USPTO materials.
- Evidence: PATLAW-030, PATLAW-031, PATLAW-034
- Outputs: ipfs_datasets_py/processors/domains/uspto/document_classifier.py, ipfs_datasets_py/processors/domains/uspto/document_extraction_processor.py, ipfs_datasets_py/processors/domains/uspto/span_validator.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/test_document_extraction.py tests/integration/processors/domains/uspto/test_span_provenance.py -q
- Acceptance: Artifact type/authority and every page are accounted for; native/OCR differences and missing coverage yield review, not guessed content.
- Gap task: Close the next classification, extraction, or span-coverage gap.
- Refinement: Keep generic PDF fixes outside domain modules and USPTO semantics outside the generic PDF layer.
- Embedding query: artifact classifier PDF DOCX layout source span page coverage readability
- AST query: DocumentClassifier DocumentExtractionProcessor SpanValidator

## PATLAW-G042 Parse office actions, submissions, and filing receipts

- Status: active
- Parent: PATLAW-G040
- Fib priority: 2
- Track: patent-document-semantics
- Priority: P0
- Bundle: patlaw/analysis
- Goal: Extract government instructions/rejections and submission claims/amendments/remarks/forms/fees/receipts while retaining exact source anchors and document versions.
- Evidence: PATLAW-032, PATLAW-033
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/office_action_processor.py, ipfs_datasets_py/processors/domains/uspto/analysis/submission_processor.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_office_action_processor.py tests/unit/processors/domains/uspto/analysis/test_submission_processor.py -q
- Acceptance: Claim ranges, citations, requirements, response instructions, submissions, and receipt identifiers are source-bound; unsupported language is not dropped.
- Gap task: Add the next office-action or submission semantic case with reviewed fixtures.
- Refinement: Parse raw office actions as primary evidence; derived USPTO citation datasets are supplemental only.
- Embedding query: office action rejection objection form paragraph claim amendment remarks receipt
- AST query: OfficeActionProcessor SubmissionProcessor GovernmentRequirement

## PATLAW-G050 Compare requirements, evidence, and governing authority

- Status: active
- Parent: PATLAW-G000
- Fib priority: 8
- Track: legal-logic
- Priority: P0
- Bundle: patlaw/analysis
- Goal: Compile typed government requirements and submission facts, resolve governing authority, and produce fail-closed compliance, rejection, instruction-consistency, and candidate-date results.
- Evidence: PATLAW-G051, PATLAW-G052
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis, ipfs_datasets_py/processors/legal_data/patent_citation_resolver.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_submission_compliance.py -q
- Acceptance: Every applicable demand has an evidence assessment; unsupported proof remains unknown; potential instruction inconsistencies and candidate dates expose exact reasoning and assumptions.
- Gap task: Implement the next typed requirement, evidence, authority, proof, or review obligation.
- Refinement: Use existing SupportMap and Legal IR only after their fail-closed boundary is proven.
- Embedding query: requirement evidence support map legal IR compliance rejection deadline instruction consistency
- AST query: SupportMapBuilder LegalIRCompilerAPI SubmissionComplianceProcessor

## PATLAW-G051 Compile requirements and submission evidence fail closed

- Status: active
- Parent: PATLAW-G050
- Fib priority: 1
- Track: compliance-analysis
- Priority: P0
- Bundle: patlaw/analysis
- Goal: Compile source-anchored instructions into typed predicates, extract submission facts, map support/counter-evidence, and aggregate only validated proof into tri-state results.
- Evidence: PATLAW-040, PATLAW-041, PATLAW-042
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/requirement_processor.py, ipfs_datasets_py/processors/domains/uspto/analysis/submission_compliance_processor.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_submission_compliance_processor.py -q
- Acceptance: No requirements/evidence, unsupported semantics, proof error/skip/timeout, or unresolved contradiction can produce `satisfied` or an overall pass.
- Gap task: Close the next requirement/evidence/proof case with a fail-closed regression.
- Refinement: Preserve extracted candidates separately from admitted facts and proved assessments.
- Embedding query: typed requirement submission fact exact evidence unsatisfied unknown proof fail closed
- AST query: RequirementProcessor SubmissionComplianceProcessor SupportMapBuilder

## PATLAW-G052 Explain rejections, instruction consistency, and candidate dates

- Status: active
- Parent: PATLAW-G050
- Fib priority: 2
- Track: legal-explanation
- Priority: P0
- Bundle: patlaw/analysis
- Goal: Map 35 USC 101/102/103/112 and other rejections to claims/references, compare instructions to exact applicable authority, and calculate review-only response-date candidates.
- Evidence: PATLAW-043, PATLAW-044, PATLAW-045
- Outputs: ipfs_datasets_py/processors/domains/uspto/analysis/rejection_mapping_processor.py, ipfs_datasets_py/processors/domains/uspto/analysis/deadline_processor.py, ipfs_datasets_py/processors/domains/uspto/analysis/instruction_consistency_processor.py
- Validation: python -m pytest tests/unit/processors/domains/uspto/analysis/test_rejection_mapping.py tests/unit/processors/domains/uspto/analysis/test_deadline_processor.py tests/unit/processors/domains/uspto/analysis/test_instruction_consistency.py -q
- Acceptance: Reports quote exact spans/versions, expose applicability and date assumptions, label uncertainty, and require human review rather than making final legal/docket determinations.
- Gap task: Add the next rejection, temporal applicability, inconsistency, or date-rule case.
- Refinement: Do not infer claim coverage or deadline exceptions when identifiers or facts are incomplete.
- Embedding query: patent rejection 101 102 103 112 instruction inconsistency candidate deadline
- AST query: RejectionMappingProcessor DeadlineProcessor InstructionConsistencyProcessor

## PATLAW-G060 Produce a human-reviewable dossier and preflight

- Status: active
- Parent: PATLAW-G000
- Fib priority: 13
- Track: workflow
- Priority: P0
- Bundle: patlaw/workflow
- Goal: Orchestrate acquisition and analysis into an immutable matter dossier, explainable gap matrix, and pre-submission review gate.
- Evidence: PATLAW-050, PATLAW-051, PATLAW-052
- Outputs: ipfs_datasets_py/processors/domains/uspto/dossier_processor.py, ipfs_datasets_py/processors/domains/uspto/workflow_processor.py, ipfs_datasets_py/processors/domains/uspto/analysis/analysis_bundle.py
- Validation: python -m pytest tests/integration/processors/domains/uspto/test_dossier_workflow.py -q
- Acceptance: One replayable bundle links every status, artifact, instruction, requirement, evidence assessment, authority, candidate date, gap, and reviewer action without enabling filing.
- Gap task: Implement the next dossier, report, or human-gate obligation.
- Refinement: Reports consume immutable analysis records and never recompute hidden legal logic in presentation code.
- Embedding query: patent application dossier requirement matrix submission gap report preflight human gate
- AST query: DossierProcessor WorkflowProcessor AnalysisBundle

## PATLAW-G070 Expose safe interfaces and resilient synchronization

- Status: active
- Parent: PATLAW-G000
- Fib priority: 21
- Track: product-integration
- Priority: P1
- Bundle: patlaw/integration
- Goal: Register the processors once and expose consistent read/analyze SDK, CLI, read-only MCP, scheduled polling, and change alerts with checkpointed liveness.
- Evidence: PATLAW-060, PATLAW-061, PATLAW-062
- Outputs: ipfs_datasets_py/processors/adapters/uspto_adapter.py, ipfs_datasets_py/processors/domains/uspto/api.py, ipfs_datasets_py/mcp_server/tools/legal_dataset_tools/uspto_tools.py, ipfs_datasets_py/cli, ipfs_datasets_py/processors/domains/uspto/scheduler.py
- Validation: python -m pytest tests/cli/test_uspto_commands.py tests/mcp/unit/test_uspto_tools.py tests/integration/processors/domains/uspto/test_scheduler.py -q
- Acceptance: All surfaces return the same versioned contracts; MCP is read-only; polling releases worker slots during backoff and reports actionable authentication/rate/outage health.
- Gap task: Implement the next serialized export, interface, or scheduler behavior without duplicating analysis logic.
- Refinement: Shared package exports, CLI registries, and MCP registries are owned by the serialized integration task.
- Embedding query: USPTO SDK CLI MCP read only polling change alert checkpoint circuit breaker
- AST query: USPTOProcessorAdapter USPTOAnalysisAPI USPTOApplicationScheduler

## PATLAW-G080 Prove privacy, correctness, replay, and operations

- Status: active
- Parent: PATLAW-G000
- Fib priority: 34
- Track: release-assurance
- Priority: P0
- Bundle: patlaw/assurance
- Goal: Establish reviewed gold fixtures, privacy/adversarial evidence, offline end-to-end replay, liveness/recovery operations, and a fresh current-tree release gate.
- Evidence: PATLAW-070, PATLAW-071, PATLAW-072, PATLAW-073, PATLAW-074, PATLAW-080
- Outputs: tests/fixtures/uspto, tests/security, tests/e2e/test_uspto_application_analysis.py, docs/operations/USPTO_SUBMISSION_ASSURANCE_RUNBOOK.md, scripts/ops/uspto
- Validation: python -m pytest tests/security/test_uspto_assurance_boundary.py tests/e2e/test_uspto_application_analysis.py -q
- Acceptance: Gold and adversarial suites pass; no private disclosure is observed; replay is deterministic; stalled/retry/outage/import incidents have tested recovery; final receipt binds target tree and merge evidence.
- Gap task: Close the next fixture, adversarial, replay, liveness, or release-evidence gap.
- Refinement: Synthetic/public fixtures only in the repository; approved private fixtures remain encrypted and outside git.
- Embedding query: USPTO gold fixture adversarial privacy deterministic replay observability recovery release gate
- AST query: AnalysisBundle PrivacyPolicy CircuitBreaker

## PATLAW-G090 Build hybrid patent retrieval and reproducible prior-art review

- Status: active
- Parent: PATLAW-G000
- Fib priority: 3
- Track: patent-retrieval
- Priority: P0
- Bundle: patlaw/patent-retrieval
- Goal: Project verified patent authorities and public patent/prosecution events into source-linked fielded BM25, pinned vector, and deterministic knowledge-graph indexes; evaluate three-way fusion and produce reproducible prior-art and current-rule review artifacts.
- Evidence: PATLAW-090, PATLAW-091, PATLAW-092, PATLAW-093, PATLAW-094, PATLAW-095
- Outputs: ipfs_datasets_py/processors/domains/patent/retrieval_contracts.py, ipfs_datasets_py/processors/domains/patent/indexing.py, ipfs_datasets_py/processors/domains/patent/hybrid_retrieval.py, ipfs_datasets_py/processors/domains/patent/prior_art.py, ipfs_datasets_py/knowledge_graphs/adapters/patent.py, tests/integration/processors/patent
- Validation: python -m pytest tests/unit/processors/patent tests/integration/processors/patent -q
- Acceptance: Every index row/node/edge/result joins to a source CID/span; as-of/disclosure/tenant filters precede retrieval; builds and evaluation receipts are deterministic; prior-art charts retain exact dated queries and coverage gaps and never claim patentability.
- Gap task: Implement the highest-priority incomplete retrieval child without bypassing source, temporal, disclosure, tenant, or human-review gates.
- Refinement: Freeze contracts first; graph and source preparation may run in parallel; build/evaluate fusion before prior-art and rule-checklist integration.
- Embedding query: patent claims prosecution BM25 dense vector knowledge graph prior art citation CPC IPC temporal authority hybrid retrieval
- AST query: PatentIndexDocument PatentGraphProjection PatentHybridRetriever PatentRetrievalEvaluator PriorArtSearchPlan ClaimChart

## PATLAW-G100 Publish verified public legal and patent artifacts to JusticeDAO

- Status: active
- Parent: PATLAW-G000
- Fib priority: 5
- Track: public-publication
- Priority: P0
- Bundle: patlaw/public-release
- Goal: Generalize the append-only Hugging Face release boundary and publish only deterministic, rights-reviewed, privacy-scanned official-law and public-patent/index/graph artifacts to configurable JusticeDAO repositories after exact human approval and pinned verification.
- Evidence: PATLAW-100, PATLAW-101, PATLAW-102
- Outputs: ipfs_datasets_py/huggingface/publication_profile.py, ipfs_datasets_py/processors/domains/patent/hf_release.py, scripts/ops/legal_data/build_patent_hf_release.py, scripts/ops/legal_data/verify_patent_hf_release.py, tests/integration/processors/patent/test_release_publisher.py
- Validation: python -m pytest tests/unit/huggingface/test_publication_profiles.py tests/unit/huggingface/test_generic_publisher.py tests/unit/processors/patent/test_hf_release.py tests/integration/processors/patent/test_release_publisher.py -q
- Acceptance: Default is dry-run; all artifacts bind hashes/CIDs/rows/source/classification/rights; private or mixed data fails before staging; add-only approval/race/canary/rollback gates hold; pinned re-download verifies before pointer promotion; no direct upload shortcut or live supervisor publication exists.
- Gap task: Generalize the publisher, build deterministic public shards, then verify the complete fake-service release transaction.
- Refinement: Preserve all legacy publication profiles; keep release building separate from publication and require a later operator-approved live action.
- Embedding query: JusticeDAO Hugging Face append only patent legal corpus BM25 vector graph privacy rights CID approval pinned redownload
- AST query: HuggingFacePublicationProfile HuggingFaceReleasePublisher JusticeDAOPatentRelease ReleasePlan ReleaseReceipt
