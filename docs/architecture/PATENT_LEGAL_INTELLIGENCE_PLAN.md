# USPTO Submission Assurance and Patent Legal Intelligence Plan

Status: approved for supervised implementation
Checked against official sources: 2026-08-03
Objective root: `PATLAW-G000`
Task prefix: `PATLAW-`
Board namespace: `patent-legal-intelligence-v1`
Implementation branch: `feature/patent-legal-intelligence`

## 1. Outcome

Add a provenance-first family of processors to `ipfs_datasets_py` that can:

1. identify a U.S. patent application without confusing application,
   publication, patent, customer, or confirmation numbers;
2. retrieve public application status, transactions, document metadata, and
   available documents through the supported USPTO Open Data Portal (ODP)
   Patent File Wrapper APIs;
3. import an authorized user's export of nonpublic Patent Center material
   without scraping Patent Center, automating MFA, or sharing credentials;
4. preserve and compare authoritative submission artifacts, including the
   original DOCX, USPTO-converted PDF, application data entered in the filing
   interface, Electronic Acknowledgement Receipt, and payment receipt;
5. extract native and scanned PDFs with page, layout, bounding-box, confidence,
   and byte-level provenance;
6. turn office actions and other government correspondence into typed,
   source-anchored instructions, requirements, cited authorities, claim
   mappings, and candidate response dates;
7. map each government demand to exact evidence in a proposed or submitted
   response and report `satisfied`, `unsatisfied`, or `unknown`; and
8. compare instructions and submissions against the law and guidance that was
   applicable at the relevant time, while preserving a mandatory human legal
   review and filing gate.

The system is decision support. It may flag a reproducible **potential
inconsistency** between an instruction and governing authority; it must not
declare an examiner unlawful, give a conclusive legal opinion, sign, pay, or
file. A responsible natural person or practitioner confirms identity, legal
strategy, signatures, fees, and every deadline.

## 2. Scope and non-goals

### Patent v1 scope

- U.S. utility, design, and plant application identifiers and public Patent
  File Wrapper data.
- Authorized user-provided exports for confidential/unpublished applications.
- Inbound USPTO correspondence, outbound submissions, receipts, and status
  events.
- Statutes, regulations, Federal Register change documents, MPEP guidance,
  forms, fee schedules, and examination guidance needed to explain a result.
- Office-action requirements, claim/rejection mappings, document completeness,
  and candidate response-date review.
- Read-only SDK, CLI, and MCP surfaces; scheduled polling and change alerts.

### Explicit non-goals

- Scraping an authenticated Patent Center session or storing cookies, MFA
  secrets, passwords, payment-card data, or reusable signing credentials.
- Assuming a private Patent Center API exists. None is documented by USPTO as
  a supported interface at the time of this plan.
- Filing, signing, paying, certifying under 37 CFR 11.18, or automatically
  accepting a calculated deadline.
- Treating the MPEP as law, FederalRegister.gov XML as the official edition, or
  a language-model inference as verified evidence.
- Publishing unpublished applications, privileged work product, non-patent
  literature, private embeddings, or private content identifiers to a public
  IPFS DHT/gateway/pin service or public dataset.
- Autonomous patentability opinions, automatic IDS filing, live unattended
  publication, or republication of unlicensed non-patent literature. The
  supervised program includes reproducible public-record prior-art review and
  dry-run/verified public-release infrastructure with explicit coverage,
  rights, privacy, and human-approval gates.
- Trademark ingestion in the v1 completion gate. A later TSDR extension is
  described in section 18.

## 3. Current-state findings that shape the work

The existing package contains useful PDF, legal-data, citation, graph, and
logic components, but they cannot simply be wired together:

- `processors/protocol.py` and `processors/core/protocol.py` define
  incompatible processor/result contracts (`can_process` versus
  `can_handle(ProcessingContext)`). The current universal surface mixes these
  registries and can silently discover no usable processor or raise a runtime
  `isinstance` error.
- `processors/adapters/pdf_adapter.py` returns placeholder text and does not
  call the specialized PDF processor.
- The specialized OCR path has sync/async, rendered-page coverage, OCR/native
  merge, engine-availability, and confidence defects. It also contains stdout,
  debug-file, and full-content logging behavior that is unacceptable for
  confidential filings.
- Existing patent code is oriented to PatentsView publication search. It is
  not an application-status, file-wrapper, office-action, or filing-receipt
  client; its URL adapter references a nonexistent class and ignores some
  requested identifiers.
- Existing form/legal checkers are court- or complaint-oriented and can pass
  vacuously when no requirements exist or proof execution is skipped. Patent
  compliance must fail closed.
- Existing U.S. Code and Federal Register scrapers, citation extraction,
  temporal authority selection, `SupportMap`, and Legal IR compiler are useful
  foundations and should be extended rather than duplicated.

Therefore Wave 0 is a release-blocking processor-foundation repair.

## 4. Supported source and access policy

| Information | Supported source | Authentication | Trust/use rule |
| --- | --- | --- | --- |
| Public patent application data, status, transactions | [ODP Patent File Wrapper application-data API](https://data.uspto.gov/apis/patent-file-wrapper/application-data) | USPTO.gov registration and API key are currently required | Supported public API; capture request/response version and never infer private access |
| Public application document metadata and bytes | [ODP Patent File Wrapper documents API](https://data.uspto.gov/apis/patent-file-wrapper/documents) | USPTO.gov registration and API key | Preserve raw bytes and upstream IDs; ODP may omit confidential records and NPL |
| Private/unpublished application material | User-authorized Patent Center export, downloaded artifacts, and receipts | Interactive user access outside this processor | Import only; no UI scraping, MFA automation, shared account, or unattended retrieval |
| Filing and receipt behavior | [Patent Center](https://www.uspto.gov/patents/apply/patent-center) and its current legal framework | Identity-verified interactive user | Model original DOCX, converted PDF, GUI metadata, acknowledgement, and payment receipt as distinct evidence |
| Current/historical regulations | [eCFR API](https://www.ecfr.gov/developers/documentation/api/v1) | None documented | Temporally useful but unofficial presentation; verify dispositive text against official annual CFR/FR artifacts |
| Official annual CFR and Federal Register artifacts | [GovInfo](https://www.govinfo.gov/developers) | API key for API; bulk endpoints as documented | Preserve official PDF/XML, package/granule metadata, hashes, and signature result |
| Federal Register discovery | [Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1) | No key | Unofficial discovery representation; verify with GovInfo official PDF |
| United States Code | [House OLRC downloads](https://uscode.house.gov/download/download.shtml) and GovInfo release points | As documented | Record exact release point; account for uncodified slip laws and classification gaps |
| Examination guidance | [MPEP](https://www.uspto.gov/web/offices/pac/mpep/index.html), forms, notices, fee schedules, Examination Guides | Public | Label as guidance/operations, record cutoff and later publications, never elevate above statute/regulation |

Legacy PEDS and the legacy USPTO Developer Hub are not implementation targets.
The source registry must discover current endpoints and operational notices; it
must not hard-code a year as “latest.” Numeric rate limits are configurable
unless the official interface publishes a current value. Every connector
honors `Retry-After`, uses bounded exponential backoff with jitter, and opens a
circuit breaker for repeated upstream failures.

## 5. Authority and time model

Every assertion carries an authority tier, jurisdiction, source version,
publication date, effective interval, retrieval time, and exact source span.
The default hierarchy is:

1. enacted statute or applicable uncodified public law;
2. promulgated regulation and applicable final-rule text;
3. binding adjudicatory authority when explicitly supported;
4. MPEP, Examination Guide, form, fee, and agency operational guidance;
5. extracted or model-generated candidate.

The temporal graph preserves `amends`, `supersedes`, `corrects`, `withdraws`,
`stays`, and `delays_effective_date` events. It distinguishes publication,
effective, compliance, applicability, mailing, receipt, filing, and retrieval
dates. It must be possible to ask both:

- “What governed on the correspondence mailing date?” and
- “What governs a response submitted on the proposed filing date?”

A newer web page does not silently rewrite a historical instruction. A
proposed rule is never treated as binding. The current eCFR text is not used to
judge a historical event without an as-of reconstruction.

## 6. Data classification and storage boundary

Each artifact is classified before parsing:

- `public_official`: public government legal or file-wrapper record;
- `public_user`: user material explicitly approved for public use;
- `confidential_application`: unpublished/private application material;
- `privileged_work_product`: analysis or attorney work product;
- `restricted_export_review`: material requiring export-control review;
- `credential_or_payment`: prohibited document-store content.

Raw private bytes, extracted text, embeddings, graphs, prompts, caches, traces,
and content identifiers stay in an encrypted, tenant-isolated private store.
“Private IPFS” means a separately authorized private network/store with no
public DHT announcement, public gateway, or public pin. Credentials use the
existing secrets-vault abstraction; document bytes do not. External model use
over private content defaults to denied and requires an explicit, audited
policy decision.

The ingestion gate checks declared publication state, source access class,
35 USC 122 confidentiality, secrecy-order indicators under 35 USC 181–188,
export-control review state, and tenant policy before any downstream dispatch.
Unknown classification is quarantined, not treated as public.

## 7. Target processor architecture

```text
supported source / authorized export
              |
              v
    identity + privacy gate
              |
              v
 immutable artifact manifest ----> encrypted raw store
              |
              v
 PDF/DOCX/image/receipt extraction
              |
              +----> matter status/event ledger
              +----> government requirement ledger
              +----> submission fact/evidence ledger
                              |
          temporal authority + citation resolver
                              |
                              v
             fail-closed legal/logic comparison
                              |
                              v
       gap matrix + candidate dates + human review gate
```

New domain modules are centered under:

```text
ipfs_datasets_py/processors/domains/uspto/
├── contracts.py
├── identifiers.py
├── privacy.py
├── artifact_manifest.py
├── matter_ledger.py
├── providers/
│   ├── base.py
│   ├── patent_file_wrapper.py
│   └── patent_center_export.py
├── application_status_processor.py
├── document_sync_processor.py
├── document_classifier.py
├── document_extraction_processor.py
├── analysis/
│   ├── office_action_processor.py
│   ├── submission_processor.py
│   ├── requirement_processor.py
│   ├── submission_compliance_processor.py
│   ├── rejection_mapping_processor.py
│   ├── deadline_processor.py
│   ├── instruction_consistency_processor.py
│   └── analysis_bundle.py
├── dossier_processor.py
├── workflow_processor.py
└── api.py
```

The existing `processors/domains/patent/` package remains limited to public
patent/publication and prior-art discovery. Its broken/drifting compatibility
imports and models are repaired by `PATLAW-019`, but it is not treated as an
application-status or private-record source. Matter/submission assurance lives
under the new `processors/domains/uspto/` boundary above.

Reusable authority components remain outside the USPTO domain under
`processors/legal_scrapers/federal_scrapers/` and
`processors/legal_data/patent_authority_registry.py`.

## 8. Canonical records

The implementation introduces versioned, serializable contracts for:

- `ApplicationIdentity`: normalized identifiers, check digits where
  applicable, source, confidence, and unresolved ambiguity;
- `SourceReceipt`: sanitized request, endpoint, retrieval UTC, response status,
  upstream ID/`lastModified`, and retry/cache metadata;
- `ArtifactManifest`: immutable artifact ID, SHA-256, optional private CID,
  media signature, size, classification, encryption namespace, related matter,
  authoritative/derivative relationship, and parser versions;
- `MatterEvent`: filing/status/transaction/document/response/allowance/
  abandonment/appeal/grant event with source and temporal semantics;
- `ExtractedSpan`: artifact/page/character/bounding-box anchor, native/OCR
  origin, reading order, confidence, and image/render digest;
- `GovernmentRequirement`: instruction text, source span, requirement type,
  affected claim/form/fee, legal citations, applicability conditions, proposed
  date rule, exceptions, parser confidence, and review state;
- `SubmissionFact`: exact evidence span, fact type, affected claim/field,
  version, and extraction status;
- `RequirementAssessment`: `satisfied | unsatisfied | unknown`, evidence and
  counter-evidence spans, authority snapshot, proof result, confidence,
  reasons, and required human action;
- `CandidateDeadline`: event basis, rule chain, calendar/time zone, entity and
  extension assumptions, computed candidate, uncertainty, and reviewer
  confirmation; and
- `AnalysisBundle`: immutable input/output manifest plus all warnings,
  unsupported checks, model/ruleset versions, and validation receipts.

Schema changes are additive and versioned. Raw source records are immutable;
new retrievals or parser versions create new derivations.

## 9. Document processing contract

The document pipeline must:

1. validate magic bytes, declared MIME, archive members, size/page limits, and
   cryptographic digest before parsing;
2. isolate untrusted PDF/DOCX/archive parsing with time, memory, recursion, and
   decompression limits;
3. extract native text, forms, annotations, links, signatures/stamps,
   checkboxes, tables, headers/footers, and page geometry;
4. deterministically render every page and use page-level OCR fallback for
   missing or low-quality text, not merely OCR embedded images;
5. merge native and OCR text without duplication while preserving both sources
   and disagreement signals;
6. detect rotated, blank, truncated, corrupt, password-protected, image-only,
   malformed, and unsupported-feature pages;
7. compare authoritative DOCX against the USPTO-converted PDF and disclose
   pagination, equation, table, symbol, font, and content differences;
8. retain page/render digests and span-level provenance for every extracted
   fact; and
9. return `unknown` plus a human-review item whenever readability, coverage, or
   extraction disagreement crosses a configured threshold.

No document text is written to stdout, ordinary logs, telemetry, crash names,
or debug files. Safe logs contain identifiers only after classification and
redaction.

## 10. Matter, status, and synchronization workflow

`ApplicationStatusProcessor` validates identity, requests an ODP snapshot,
normalizes status and transaction records without discarding upstream fields,
and records source freshness. `DocumentSyncProcessor` first compares document
metadata and upstream update markers, then downloads only authorized changed
artifacts. The sync key is source identifier plus content hash; changed bytes
create a new version rather than overwriting history.

The private importer accepts an explicit manifest and user-selected local
artifacts. It checks that all artifacts resolve beneath the authorized import
root, blocks symlink/path traversal and archive escape, classifies before
extraction, encrypts before durable storage, and records the importing user and
authorization receipt. It never reads browser profiles or session storage.

The matter ledger reconciles:

- original submission files;
- converted renderings;
- GUI/exported metadata and document descriptions;
- acknowledgements and payment receipts;
- file-wrapper document inventory;
- transaction/status events; and
- amendments and the current claim set.

Missing or delayed public documents are reported as retrieval freshness gaps,
not proof that USPTO did not receive an item.

## 11. Government-instruction analysis

The office-action processor classifies the document, sections it, extracts
claim ranges, form paragraphs, statutory/regulatory/MPEP citations, cited
references, objections, rejections, informalities, fee/form requests, interview
summaries, and response instructions. Each extraction points to a source span.

The requirement compiler converts those candidates into typed requirements
only after span validation and authority resolution. It supports conditional,
alternative, conjunctive, disjunctive, claim-specific, and document-level
requirements. Unsupported language remains an explicit uncompiled item.

The consistency analyzer produces a comparison packet:

```text
examiner/instruction span
  -> cited and independently resolved authority, exact version
  -> applicability facts and assumptions
  -> consistent / potential inconsistency / unknown
  -> counter-source spans and human-review question
```

It never substitutes an LLM summary for the government text or governing text.

## 12. Submission-completeness analysis

The submission processor extracts claims, amendments, remarks, declarations,
forms, signatures-as-present (never reusable signature material), fee evidence,
attachments, metadata, and receipts. It reconstructs the document/version set
and flags mismatched matter identifiers or document descriptions.

The compliance engine maps every applicable government requirement to exact
submission evidence through the existing support-map and Legal IR machinery.
Outcomes are deliberately fail closed:

- `satisfied`: all necessary predicates have validated evidence and no
  unresolved contradiction;
- `unsatisfied`: at least one necessary predicate is demonstrably absent or
  contradicted in the analyzed package;
- `unknown`: source, extraction, authority, applicability, semantics, or proof
  is incomplete; and
- `not_applicable`: an explicit, source-supported applicability rule excludes
  the requirement.

Absent requirements, empty evidence, parser errors, skipped proofs, timeouts,
unsupported semantics, or missing source versions can never produce an overall
pass. The top-level package result remains `unknown` if any mandatory item is
unknown.

## 13. Candidate-date policy

Dates are review candidates, not docket instructions. A result includes the
mailing/notification event, cited rule chain, response period, calendar and
time zone, weekend/holiday adjustment, entity-status assumption, extension and
fee assumptions, upstream status freshness, and unresolved exceptions. It
must show conflicting candidate dates rather than picking one silently. The UI
requires named human confirmation before a date can be exported to a docket.

## 14. Public interfaces

- Python SDK: typed, async-capable read/analyze operations with injected stores
  and clients.
- CLI: `status`, `sync-public`, `import-private`, `analyze`, `preflight`, and
  `explain` commands. Mutating imports require explicit paths and tenant.
- MCP: read-only/status/analysis tools by default. No sign, file, pay, browser
  session, or credential-returning tool exists.
- Scheduler: bounded per-provider queues, separate metadata/binary rate
  buckets, persisted checkpoints, change alerts, and circuit-breaker state.

Every interface returns the same typed bundle and provenance rather than
maintaining separate compliance logic.

## 15. Supervisor-compliant execution model

The durable objective heap is
[`patent_legal_intelligence.objectives.md`](patent_legal_intelligence.objectives.md).
The executable projection is
[`patent_legal_intelligence.todo.md`](patent_legal_intelligence.todo.md).
Every task declares `Goal id`, dependencies, outputs, validation, acceptance,
bundle, lane, resource/token class, predicted files, and conflict policy.

Four isolated `implementation_supervisor` shards run with:

- explicit non-overlapping execution slices;
- isolated state, log, and worktree roots;
- one shared merge queue and the feature branch above;
- plan, objective heap, task board, launcher, status tool, config, and validator
  protected from implementation-agent edits;
- reviewed-board execution only: objective/codebase refill, goal mutation,
  janitor, and generated repair guardrails disabled;
- authenticated Grok (`grok-4.5`) as primary and Codex
  (`gpt-5.6-terra`, high reasoning) only as a separately receipted fresh
  attempt at the same clean base when the reviewed fallback proof permits it;
- bounded attempts/timeouts and restartable artifact/page checkpoints; and
- health checks over outer and managed PIDs, heartbeat freshness, active worker
  and log progress, dependency readiness, protected-path incidents, merge
  receipts, and target-branch advancement.

The board encodes a DAG, not a sequence. Independent work begins immediately
in the runtime, PDF, legal-analysis, source-authority, and USPTO-contract
bundles. Shared exports, CLI/MCP registration, and final integration are late,
serialized tasks.

## 16. Implementation waves

| Wave | Goals | Parallel result |
| --- | --- | --- |
| 0 | `PATLAW-G010`, `PATLAW-G020`, `PATLAW-G090`, `PATLAW-G100` | In parallel, repair processor/PDF/fail-closed foundations, freeze authority and retrieval contracts, and generalize the dry-run append-only publication profile |
| 1 | `PATLAW-G020`, `PATLAW-G030` | Build verified legal sources while repairing public-patent compatibility and implementing ODP/authorized private import |
| 2 | `PATLAW-G040`, `PATLAW-G090` | Extract correspondence/submissions with provenance while projecting source-bound graph and index inputs |
| 3 | `PATLAW-G050` | Compile requirements/facts and run fail-closed compliance, rejection, instruction, and candidate-date analysis |
| 4 | `PATLAW-G060`, `PATLAW-G090`, `PATLAW-G100` | Assemble dossiers/preflight, evaluate hybrid retrieval/prior-art review, and build deterministic privacy-reviewed public artifacts |
| 5 | `PATLAW-G070`, `PATLAW-G100` | Integrate SDK/CLI/read-only MCP/polling and prove the fake-service, human-approved publication transaction |
| 6 | `PATLAW-G080` | Prove gold fixtures, privacy/adversarial isolation, offline replay, recovery/sync operations, and the current-tree release gate |

Lane ownership is conflict-exclusive while tasks are concurrent:

| Bundle | Primary ownership |
| --- | --- |
| `patlaw/runtime` | `processors/core/`, adapters, legacy compatibility shims |
| `patlaw/pdf` | `processors/specialized/pdf/`, synthetic PDF fixtures |
| `patlaw/uspto` | new USPTO contracts/providers/status/sync/private-import modules |
| `patlaw/authority` | federal source connectors and temporal authority registry |
| `patlaw/analysis` | USPTO document/requirement/compliance analysis modules |
| `patlaw/patent-public` | public-patent model/import compatibility and prosecution-event projection |
| `patlaw/index` | source-linked BM25/vector/graph/fusion and evaluation modules |
| `patlaw/release` | deterministic public shards and generic dry-run-first publication profile |
| `patlaw/integration` | shared `__init__.py`, public exports, CLI, MCP, scheduler, final gates |

## 17. Verification and release gates

Each task ships focused unit/contract tests. Program gates additionally cover:

- canonical processor discovery/routing with no mixed-protocol failure;
- real native and scanned PDF extraction, including rotated pages, forms,
  tables, corrupt pages, native/OCR disagreement, and no-content disclosure;
- public/private namespace isolation and path/archive traversal attacks;
- ODP 200/401/403/404/429/5xx, pagination, schema drift, delayed documents,
  idempotence, and changed-content fixtures without hitting production in CI;
- authoritative DOCX versus converted-PDF differences and receipt/metadata
  reconciliation;
- rescinded/reissued actions, amendments, current-claim reconstruction, wrong
  matter identifiers, and missing documents;
- exact citation/as-of authority resolution, amendments, corrections,
  withdrawals, delayed effective dates, and proposed-rule exclusion;
- requirement and citation recall, evidence precision, provenance completeness,
  and an explicit false-negative budget set from a reviewed gold corpus;
- vacuous-pass, proof-skip, missing-source, unsupported-language, and deadline
  ambiguity tests that must yield `unknown`/review;
- offline deterministic replay from immutable source receipts; and
- zero private bytes/text/embeddings/CIDs in logs, telemetry, public IPFS,
  public caches, or public release surfaces.

The root objective closes only when a fresh validation run on the merged feature
branch binds test receipts, source-fixture versions, configuration digest, git
tree, and supervisor merge receipts. Task status alone is insufficient.

## 18. Program extensions and later sources

The active board includes reproducible public-record prior-art retrieval and
reviewed, dry-run-first public legal/patent release infrastructure. It records
foreign-patent and non-patent-literature coverage gaps rather than silently
treating those sources as searched. PTAB decisions and licensed NPL remain
later source bundles with their own rights and evaluation gates.

After the patent program passes its release gate, add a separate trademark
goal and board using USPTO TSDR public APIs, with separate metadata and PDF/ZIP
rate buckets and last-update checks. Trademark Center remains an interactive
filing surface, not a scraping target.

## 19. Principal risks and mitigations

| Risk | Mitigation |
| --- | --- |
| USPTO endpoint/auth/schema change | Versioned provider contract, schema-drift quarantine, configurable endpoint/rate policy, operational-source freshness check |
| Confidentiality or export-control disclosure | Classify before dispatch, encrypted tenant isolation, public-sink deny hooks, external-model deny default, adversarial non-disclosure tests |
| OCR or parser misses a demand | Page coverage receipts, native/render/OCR comparison, gold recall gates, `unknown` on low readability |
| Incorrect authority version | Effective-time graph, exact release/source receipt, official artifact verification, dual mailing/response-date views |
| Vacuous logic “pass” | Required typed requirement set, explicit unsupported checks, fail-closed aggregation, proof-execution receipts |
| Incorrect deadline reliance | Candidate-only semantics, assumption trace, conflicts shown, human docket confirmation |
| Parallel edit conflicts | Explicit task slices/bundles, predicted-file validation, protected control files, shared merge train |
| Supervisor appears alive but is stalled | PID plus heartbeat/worker/log/readiness/merge checks, bounded log-stall timeout, actionable incident state |

## 20. Definition of done

For at least one synthetic and one approved public application fixture, an
operator can provide an identifier or authorized export and receive a
replayable dossier containing current/as-of status, complete artifact
inventory, extracted correspondence/submission spans, government requirement
matrix, submission evidence matrix, cited-law versions, potential instruction
inconsistencies, candidate dates, and explicit human-review actions. All
results are provenance-bound and fail closed; private-material isolation and
the no-file/no-sign/no-pay boundary are proven by tests; the SDK/CLI/MCP expose
the same result contract; and all supervisor tasks have merged validation
receipts on `feature/patent-legal-intelligence`.
