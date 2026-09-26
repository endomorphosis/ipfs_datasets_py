# U.S. Code autoformalization and versioned proof corpus

Status: architecture and delivery plan, based on a source/metadata audit on 2026-09-24. This document does not claim that the corpus has been autoformalized, that published dataset identities have all been independently verified, or that the inspected storage components are production-durable.

Current implementation sequence: [federal-law end-to-end training](FEDERAL_LAW_END_TO_END_TRAINING_PLAN.md)
adds a 2026-09-25 audit of the destination tree, shared targets, sparse updates,
Arrow weights, and source-to-Lake-to-release milestones. Its current findings
distinguish the existing all-title source-policy contract from the still-limited
live acquisition connector; the original audit provenance below is retained.

Canonical owner: the `ipfs_datasets_py` submodule at `/home/barberb/lift_coding/external/ipfs_datasets`. This entire plan was migrated from `JevOps/US_CODE_AUTOFORMALIZATION_PLAN.md` at the user's request. All implementation, orchestration, tests, training integration and reports for this initiative belong in this submodule; JevOps is an optional verifier/benchmark integration, not the owner of the legal pipeline. The audit findings below retain their original checkout provenance and must not be mistaken for a fresh implementation audit of the destination.

## 1. Intended outcome and boundaries

Build a reproducible pipeline from versioned U.S. Code documents in JusticeDAO's Hugging Face GraphRAG-IR datasets to source-grounded formalizations, checked proof artifacts, and reusable ontology modules. Store proof bytes and their catalog in DuckDB; use IPFS content identities and versioned dependency graphs to preserve lineage. Better models create new candidates and release snapshots, never silently rewrite historical evidence.

The system has four separate questions to answer:

1. **Source:** Which exact document, edition, section, span, and effective-time context was used, and what establishes its provenance?
2. **Interpretation:** Does the formalization faithfully capture the text, including definitions, exceptions, ambiguity, and scope?
3. **Proof:** Does the stated conclusion follow under the explicitly recorded formal semantics and assumptions?
4. **Applicability:** Is that interpretation/proof eligible for this jurisdiction, date, ontology, and release policy?

A Lean kernel check answers the third question within its trusted environment; it cannot establish the other three. A statute's normative assertion is an input with source authority, not a mathematical theorem established merely by encoding it as an axiom. Prove consequences, translation properties, normalization equivalences, and explicitly conditional propositions. Never count “assume the generated claim; prove the generated claim” as successful autoformalization.

Scope initially excludes resolving contested legal interpretations automatically, claiming completeness for all U.S. law, or treating statutory text alone as all applicable authority. Regulations, judicial interpretations, uncodified provisions, and other sources can be explicit future dependencies, with unresolved dependencies visible now. This is a research/formalization system, not an automated legal-advice authority.

Operational constraints: DuckDB for new application databases; no SQLite fallback. Retain existing caches and evidence. Honor the existing 50,000,000,000-byte storage ceiling, including scratch, WAL, checkpoints, model artifacts, and retained caches; reserve headroom and stop before exceeding it. This planning task does not authorize corpus downloads, training, watcher changes, or HF/IPFS publication.

## 2. What the repository and dataset audit established

### Code revisions and integration boundary

The original audit inspected the separate `ipfs_datasets_py` checkout at `/home/barberb/ipfs_datasets_py`, HEAD `7f0d38572f92f5fc0cba7a5ddd4bef28523876f3`. It is a reference checkout, not this initiative's implementation destination. JevOps HEAD at that audit was `2c52171e2f54bfa420177db4338ce29fb3276cb8`, but substantial working-tree code was modified/untracked: HEAD alone does not identify the running implementation.

JevOps' [statement_lock.py](../../../../../JevOps/jevops/statement_lock.py) loads legal tooling from this submodule, `/home/barberb/lift_coding/external/ipfs_datasets`, HEAD `ddf6b79467b68159650df81befc288c8553df664` at migration. The loaded `logic/legal_document.py` and `logic/autoformal/__init__.py` are not the same module layout as the reference checkout. An explicit adapter and pinned dependency manifest must replace assumptions that both checkouts expose one interchangeable API. Bind relevant working-tree content hashes, not just Git HEADs, in every build manifest. Preserve the submodule's existing modified/untracked legal tooling while reconciling APIs; do not replace it wholesale with the reference checkout.

The original audit's upstream paths below are relative to `/home/barberb/ipfs_datasets_py/ipfs_datasets_py` unless stated otherwise. Corresponding implementation paths belong under this submodule's `ipfs_datasets_py/`; verify behavior and version parity here in phase 0 before reusing a finding. Findings concern inspected paths, not a certification of either entire repository. Links into the sibling JevOps checkout are workspace-only background references, not installation requirements.

| Existing component | Useful foundation | Required work / limitation |
| --- | --- | --- |
| `processors/legal_data/canonical_legal_corpora.py` | Registers `justicedao/ipfs_uscode` | Registry's legacy `cid`/`uscode_parquet` assumptions need an adapter for the current release wrapper |
| `processors/legal_scrapers/federal_scrapers/uscode_release_processor.py` | Release/source receipts and OLRC/GovInfo provenance | Inspected connector is Title-35-focused; do not call it a finished all-title acquisition layer |
| `processors/legal_data/reasoner/hybrid_legal_ir.py` | Entities, frames, norms, conditions, exceptions, temporal data | Validate extraction and formal semantics; a populated dataclass is not a faithful interpretation certificate |
| `logic/formalization/` and `logic/families/models.py` | Typed artifacts, views, support/evidence/translation contracts | Route only supported profiles; preserve bounds and unsupported/heuristic statuses |
| `logic/integration/reasoning/legal_ir_*` | Source maps, proof routing, temporal authority, semantic diff, incremental compilation, schema evolution | Integrate policy and durable state; inspected incremental coordination is in-process; semantic diff is not an equivalence proof |
| `logic/ir_core/identity.py` | Versioned canonical identity bytes and raw CIDv1/SHA-256 | Preserve the exact canonicalization profile and distinguish identity payload from full wire bytes |
| `logic/common/duckdb_proof_store.py` | Rich environment-bound proof keys and integrity contracts | Inspected `DuckDBProofStore` keeps entries in an `OrderedDict`; installing DDL does not make its puts durable |
| `logic/proof_corpus/duckdb_repository.py` | Corpus envelopes, indexing, revocation and contradiction contracts | Default blob/index state is process-local; optional SQL mirroring does not establish restart hydration or durable blob retrieval |
| `logic/modal/autoencoder_loop.py`, `optimizers/logic_theorem_optimizer/modal_autoencoder.py` | Modal routing, family/reconstruction losses and trainable advisory heads | Some paths default to mock embeddings; sample-memory behavior must be disabled for generalization tests; not a demonstrated general text-to-proof model |
| JevOps `autoformal_tools.py`, `statement_lock.py` | Narrow rule patterns, statement checks, Lake checks | Limited legal patterns and textual locking; freeze helper definitions/semantics too; default upstream attestation repository is process-local |
| JevOps `arena_lean.py`, `autoencoder_training.py`, `knowledge_*.py`, `duckdb_ingest.py` | Verification, training gates, scoped retrieval and bounded bulk ingestion | Adapt to legal contexts without treating existing bounded KG/functional-IR support as a general legal compiler |

Two older upstream scripts need particular caution. `scripts/ops/legal_data/build_uscode_logic_proof_artifacts.py` can default an unrecognized norm operator to obligation and reads an entire Parquet table into Python objects. Unknown modality must instead abstain, and ingestion must stream. `convert_legal_corpus_to_formal_logic.py` exposes useful conversion/roundtrip records, but roundtrip similarity and theorem-candidate fields do not establish source fidelity. ZK/Groth16 artifacts, where used, attest only their encoded relation and assumptions, not correct interpretation of legislation.

### JusticeDAO HF repositories: the intended document-lineage anchor

Use **`justicedao/ipfs_uscode` as the initial U.S. Code anchor**, not an assumed local `graphrag_ir` checkout. The inspected [pinned dataset card](https://huggingface.co/datasets/justicedao/ipfs_uscode/blob/5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/README.md) and [manifest](https://huggingface.co/datasets/justicedao/ipfs_uscode/blob/5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/manifest.json) describe `publicus-ir-graphrag/v2`, with corpus, sparse-retrieval, vector, and graph families. Relevant recorded identities are:

- HF commit: `5016b86a273ce5e4ffd066c5ae9f5fe494dd417e`.
- Publisher-declared `source_revision`: `006dd603185b283c54648dd4aef3c2cbe650981a`.
- Publisher-declared release point: `us/pl/119/102`.
- Publisher-declared `release_root_cid`: `bafkreifke54eqqlz7vceydibuiw4luypi6utpwjkfnp4x66gxhqxn5iugu`.

The wrapper exposes `entry_cid`, `legal_id`, `family`, `record_json`, and `record_sha256`; the manifest carries per-file descriptors. The default `data/**/*.parquet` pattern includes different record families, so it is not a safe “all source documents” selector. Follow corpus-family descriptors explicitly. The [schema reference](https://huggingface.co/datasets/justicedao/ipfs_uscode/blob/5016b86a273ce5e4ffd066c5ae9f5fe494dd417e/skill/query-hf-graphrag/references/schema.md) documents sparse shard/paging contracts. Pin their versions; validate actual rows before relying on them.

These are publisher assertions until independently checked. In particular, the observed `build_config_cid` is a 64-hex digest, not a self-describing CID string: a field name ending in `_cid` is insufficient validation. Preserve legacy identifiers and add typed identity mappings rather than silently relabeling digests as CIDs. No source Parquet rows or IPFS release closure were downloaded/verified during this audit.

`justicedao/open-us-law-sparse-graphrag` is an optional cross-corpus retrieval source, not the default U.S. Code authority. Its [pinned card](https://huggingface.co/datasets/justicedao/open-us-law-sparse-graphrag/blob/6a8b4c2938693e5bb004c3b48e85f53924eb856c/README.md) distinguishes a non-default `federal_uscode` configuration from other corpora. Its full manifest exceeded the bounded metadata read and was not audited. Do not merge state and federal scope, recovery material, or conflicting snapshots by default. `justicedao/patent-legal-ir-graphrag` was discovered as a potential domain-specific supplement, not certified as a compatible input.

Repository commits, publisher source revisions, release roots, and individual document identities are separate fields. A pinned HF revision makes acquisition reproducible, not legally current or authentic. The [GovInfo U.S. Code guide](https://www.govinfo.gov/help/uscode) distinguishes editions/supplements and positive-law status; preserve those distinctions and provenance to underlying legislative sources instead of treating a dataset upload timestamp as an effective date.

## 3. Architecture and trust boundaries

```text
Pinned HF release + publisher manifests + official-source reconciliation
  -> verified source versions and exact source-span selectors
  -> typed LegalIR candidates + explicit interpretation alternatives
  -> supported logic views + translation contracts + proof obligations
  -> isolated provers / Lean reconstruction + independent admission policy
  -> immutable proof/ontology artifacts + DuckDB release catalog
  -> scoped GraphRAG reuse + impact analysis
  -> reviewed, lineage-split training snapshots
  -> new model candidates -> evaluation -> a new release, never in-place truth
```

Separate proposal, verification, and admission services. LLMs, the autoencoder, and NCA/JeV advisors can propose interpretations, tactics, mappings, or compression; they cannot grant themselves source authority, alter the evaluator, mark their own output reviewed, or publish the production snapshot.

Inject protocols for `SourceProvider`, `ArtifactStore`, `ProofCatalog`, `OntologyResolver`, `FormalizationProposer`, `LogicCompiler`, `Verifier`, `ReviewPolicy`, and `Clock`. Tests use fakes at those boundaries; production configurations bind exact implementations, versions, capabilities, and content digests. Own these contracts and their orchestration in this submodule. A versioned adapter may call JevOps verification/benchmark capabilities without copying legal semantics into JevOps or depending on ambient imports from another `ipfs_datasets_py` checkout.

Keep an orthogonal evidence record, not one overloaded `verified=true`: source-integrity status, source-authority status, semantic-review status, family support, translation guarantee, backend outcome, independent certificate/kernel outcome, applicability, and admission policy. A timeout is not false; unknown is not proved; backend success is not automatically kernel verification.

## 4. Source ingestion, selectors, and efficient GraphRAG access

1. Resolve a configured HF revision once, fetch bounded metadata, record metadata digests, and freeze a source manifest. Reject descriptor paths escaping the dataset namespace, unexpected schemes, unbounded sizes, or manifest/revision mismatches.
2. Select source corpus shards by family and legal scope. Use projected columns, bounded row groups/batches, digest verification, and resumable idempotent inserts. Do not load all Parquet files or `.to_pylist()` the full corpus.
3. Preserve raw source bytes when available, normalized text separately, and exact extraction provenance. If only dataset-derived text is available, state that limitation instead of fabricating original-document availability.
4. Reconcile citation/section identifiers and release provenance with official OLRC/GovInfo material for the admitted pilot. Preserve statutory text, editorial notes, headings, amendments, and effective-date notes as distinct source kinds. Record failed reconciliation as unresolved authority.
5. Encode selectors with source-version identity, byte offsets and encoding, structural USLM path where available, quote hash, and normalization/source-map version. A normalized character offset must not masquerade as a raw XML byte offset. Test that selectors resolve exact content after restart.
6. Model cross-references and incorporated definitions as dependencies. Missing references remain unresolved obligations. Sections can split, merge, be renumbered, or be repealed; maintain explicit many-to-many citation/version mappings.
7. Reuse sparse term ranges, CID lookups, adjacency pages, and bounded vector candidates from the pinned GraphRAG schema. Resolve candidate hits to the exact source/proof snapshot and permissions before use. Similarity edges remain retrieval hints, not entailment edges.
8. Exclude recovery/quarantine families and unintended configurations. Treat the HF `train` split as a packaging label, not approval to include every row in model training.
9. Check capacity before each batch, including worst-case transaction/temporary-file growth. Retain caches; stop with a resumable cursor and receipt when reservation fails. No automatic cleanup to squeeze past the user's ceiling.

Keep the retrieval index rebuildable from immutable artifacts. Sparse postings, embeddings, centroids, and page pointers are accelerators, not legal authority or stable document identities. Bind embedding model/revision, preprocessing, normalization, index parameters and corpus snapshot; never mix vectors merely because dimensions agree.

## 5. Canonical LegalIR, logic families, and ontology reuse

### LegalIR as the stable semantic interface

Extend/adapt the existing hybrid IR rather than immediately generating unconstrained Lean. Each candidate records actors/roles, typed entities, actions and objects, quantifiers/binders, definitions and their scope, norm operator, activation conditions, exceptions/defeaters, temporal intervals/events, arithmetic units, jurisdiction, citations, source selectors, assumptions, unresolved questions, and interpretation branch.

Keep explicit negative information separate from missing information. Distinguish obligation, permission, prohibition, power, and factual assertions; unsupported operators are not coerced into obligation. Preserve conjunction/disjunction, scope of negation, quantifiers, “unless,” inclusive/exclusive thresholds, calendar rules, and applicability conditions. Only domain-reviewed profiles may resolve ambiguous wording automatically.

An interpretation is a versioned assertion about source meaning. Roundtrip text, structural comparison, model confidence, and contrastive examples help reviewers detect errors; none alone proves natural-language equivalence. Provide side-by-side source spans, normalized IR, assumptions, counterexamples, and unresolved references for review. Preserve competing interpretations instead of merging them into an apparently definitive rule.

### Family routing

| Need | Initial representation | Admission boundary |
| --- | --- | --- |
| Definitions and relational conditions | Typed FOL; finite Horn/Datalog subset where appropriate | Explicit domain and open/closed-world policy; no silent negation-as-failure conversion |
| Ontology roles, classes and scoped properties | Frame/F-logic or a selected description-logic profile | Pin profile and inheritance semantics; declaration support is not reasoning support |
| Obligations, permissions, prohibitions and exceptions | Explicit deontic/defeasible profile; TDFOL view where supported | Preserve norm conflict/priority policy; do not infer occurrence from obligation |
| Time, events, deadlines and persistence | Explicit temporal semantics, optionally supported DCEC/event profiles | State trace/calendar bounds and event assumptions; bounded checks stay bounded |
| Quantities, arithmetic, thresholds | Typed arithmetic obligations with units | Checked decision procedure or certificate/Lean reconstruction under declared arithmetic semantics |
| General proof composition | Lean encoding of approved semantics/obligations | Exact statement, definitions, imports, assumptions, axiom policy and toolchain frozen |

Reuse `logic/families/models.py` support levels and translation guarantees. A heuristic or satisfiability-preserving translation must not be promoted to bidirectional semantic equivalence. For each compiler pass record input/output CIDs, semantic profile, implementation digest, applicable preconditions, and either a checked translation witness or an explicit unverified boundary.

### Reusing, extending, and contrasting ontology modules

Use immutable ontology modules with scoped symbol IDs, types, definitions, source bindings and import versions. A symbol's spelling is a search key, not its identity. “Person,” for example, must not be globally unified across differently scoped definitions merely because the text matches.

Candidate reuse proceeds through lexical/sparse retrieval, typed/context filtering, structural matching, and a proof/review gate. Record mappings as typed relations: exact identity, checked equivalence, subsumption in one direction, disjointness, overlap, or unresolved candidate. Each mapping carries scope, assumptions, source/evidence and verification status. Only an admitted relation of the required strength can discharge an obligation.

New definitions create a child module/version; imported modules remain pinned. Propose bridging lemmas for repeated structures, retain counterexamples for false merges, and evaluate reuse against hard negatives with matching vocabulary but different modality, dates, jurisdiction or exceptions. A graph edge named `supports` is not by itself a proof rule: define its formal meaning or keep it as provenance-only metadata.

## 6. Content identity and provenance model

Use stable legal/citation IDs for discovery and versioned content identities for reproducibility. Do not try to make one identifier serve both purposes.

| Identity | Identifies |
| --- | --- |
| `source_blob_cid` | Exact acquired bytes, with codec/chunking profile |
| `source_version_cid` | Canonical source-version record linking blob, release provenance and citation context |
| `text_cid`, `span_cid` | Normalized text and an exact version-bound selector/source map |
| `ir_cid`, `ontology_cid` | Canonical typed interpretation and immutable ontology module |
| `obligation_cid`, `proof_blob_cid` | Exact formal goal/context and exact proof bytes, respectively |
| `verification_cid` | Receipt binding goal, proof, dependencies, environment, checker, outcome and resource observations |
| `training_manifest_cid`, `model_manifest_cid` | Admitted training membership and reproducible model/checkpoint/run metadata |
| `release_manifest_cid` | Immutable selected artifact set, policy, parent release and dependency closure |

Reuse `ir-canonical-identity-v1` for supported small canonical objects: its exact canonical preimage, domain, schema and collection semantics matter. Original source bytes are not normalized in place. For large objects define a separate pinned block/chunking profile; never assume a whole-file SHA-256 equals an IPFS UnixFS root. [IPFS's content-addressing documentation](https://docs.ipfs.tech/concepts/content-addressing/) explains why encoding and layout affect identity.

Important compatibility issue: existing proof-corpus envelopes can compute their logical `content_cid` over an identity projection while storing a larger `to_dict()` wire representation. Record both **`logical_object_cid` and `storage_blob_cid`**, plus the projection/profile mapping. Validate each against its own exact preimage. Do not upload the larger bytes and claim that their block CID is the projection's CID, and do not overwrite historical logical IDs to hide the mismatch.

Canonical raw JSON containing CID strings does not automatically form traversable IPLD links. Initially keep an explicit dependency-closure/pin manifest; optionally add a separately versioned DAG-CBOR link manifest using actual CID links. This creates a new manifest identity, not a silent conversion of the original raw object. See the [DAG-CBOR specification](https://ipld.io/specs/codecs/dag-cbor/spec/).

Provenance edges include `extracted_from`, `formalizes`, `uses_definition`, `compiled_by`, `proved_using`, `verified_by`, `reviewed_by`, `trained_on`, `generated_by`, `supersedes`, and `invalidated_by`. Edge roles/order matter for proof dependencies; retain them rather than storing only untyped pairwise adjacency. Map entities, activities and agents to [W3C PROV-O](https://www.w3.org/TR/prov-o/) where useful, with legal-specific qualified relations.

Keep timestamps and mutable locations in appropriate receipt/version records rather than accidentally changing content identity on every read. Avoid self-referential identity payloads: hash the object first, then attach an envelope/receipt. Distinguish the potentially cyclic citation graph from the acyclic artifact derivation/proof graph.

CID integrity does not establish authorship, legal truth, or availability. Keep source authentication evidence, signer/policy identity, rights/license metadata and pin/retrieval receipts separately. Retain local evidence even if a remote disappears. [IPFS pinning](https://docs.ipfs.tech/how-to/pin-files/) is an availability operation; publishing or pinning to an external service is a separate deployment decision, not implied by computing a CID.

## 7. DuckDB: durable proof bytes, catalog, and release ledger

The application ledger must survive closing the process and reopening the database on its own. The inspected in-memory defaults do not satisfy this requirement. Implement a DuckDB-backed artifact/catalog adapter with no implicit in-memory production fallback. Fakes remain explicit test dependencies.

Store exact proof/IR/receipt bytes in an immutable `artifact_blobs` BLOB table keyed by their genuine storage CID, alongside byte digest, byte length, media type and codec/profile. Large models or original corpora may use verified retained content-addressed files/CAR/IPFS objects with availability records; proof storage must not reduce to a non-durable Python dictionary or an unverified path. Separate small queryable projections from large bytes to avoid scanning blobs for retrieval.

Proposed schema groups (logical design, not a claim that these tables already exist):

| Tables | Essential purpose |
| --- | --- |
| `dataset_releases`, `source_versions`, `source_spans` | HF pin, publisher release, original/normalized identities, legal scope and selectors |
| `artifact_blobs`, `artifact_identities`, `artifact_locations` | Exact bytes, logical-to-storage identity crosswalk, verified availability |
| `ontology_modules`, `symbols`, `ontology_mappings` | Versioned definitions, imports and qualified reuse relations |
| `formalizations`, `formalization_sources` | IR, interpretation branch, source spans, family/profile, assumptions and proposer |
| `proof_obligations`, `proof_artifacts`, `proof_dependencies` | Goals, proof bytes, ordered dependencies and axiom/premise manifests |
| `verification_runs`, `semantic_reviews` | Independent machine and human outcomes; no combined “truth” flag |
| `derivation_edges`, `model_runs`, `training_memberships` | Source-to-model-to-output lineage and reproducible split membership |
| `supersession_events`, `revocations`, `impact_events` | Append-only replacement, invalidation reasons and affected closures |
| `release_manifests`, `release_members`, `admission_events` | Immutable snapshots and their reproducible selection policy |
| `jobs`, `publish_outbox`, `availability_receipts` | Idempotent coordination, external publication reconciliation and retention |

Application-enforced invariants: foreign-key integrity, verified byte/CID mappings, immutable artifact rows, idempotent same-content inserts, conflicting identity rejection, bounded size/codec/schema checks, and no admission with missing dependencies. DuckDB is not itself a cryptographic immutable ledger: restrict writers, hash/sign release manifests as policy requires, and periodically verify stored content.

Use one writer coordinator for the pilot, bounded columnar batches, and explicit transactions. Workers submit artifacts/results through the coordinator instead of independently opening write connections. Queries use coordinated connections in that process or closed immutable reader snapshots, not unsafe assumptions about cross-process access to the live writer file. This deliberately conservative design follows the relevant [DuckDB concurrency constraints](https://duckdb.org/docs/current/connect/concurrency).

The “active” selection is a projection of release/admission events, qualified by source release, legal effective date, ontology version, interpretation branch, policy and as-known-at time. Do not use `MAX(created_at)` as truth. Record legal valid-time separately from system recorded-time; resolve corrections and retroactive applicability through explicit events and new snapshots.

Publication protocol: persist/verify bytes and staged metadata; validate dependency closure and admission; atomically commit a local release and outbox event; then export/pin/replicate and record acknowledgements. If a release promises remote availability, advertise that status only after its required receipts exist. DuckDB and remote IPFS/HF are not one distributed transaction. Crash recovery reconciles outbox state and retained orphan artifacts; it never deletes caches or presents missing blobs as available.

Backups must include proof bytes, manifests, required external blobs and schema/migration versions. Test restore in a fresh process with no warmed Python dictionaries. Test migration rollback on a copy, verify all restored CIDs, and keep both old and new release identities. Avoid hashing the mutable DuckDB file as the sole semantic snapshot: use canonical ordered release membership manifests.

## 8. Safe replacement, archiving, and consistency

Archiving means “not selected in this release,” not “this historical proof was invalid.” Revocation means “do not admit this evidence under the affected policy.” Both are append-only events. Old source versions and proof bytes remain addressable.

| Change | Required gate | Effect on history/dependents |
| --- | --- | --- |
| Shorter proof, unchanged formal goal/definitions/assumptions | Fresh accepted checker result; fixed scoring policy and environment; no dependency/axiom expansion | New proof/receipt, same interpretation; select only in a new release |
| IR normalization claimed equivalent | Checked equivalence/translation certificate in the pinned semantics, plus source review if meaning-bearing fields change | Preserve old IR and bridge; migrate eligible dependents explicitly |
| Corrected interpretation, such as restoring an omitted exception | New source-grounded review and obligations; do not falsely require or assert equivalence | New interpretation version; mark affected downstream selections stale |
| Statutory amendment or changed source release | New source version, effective-time analysis and impact closure | Old proofs remain historical; no automatic application to amended text |
| Ontology, compiler, toolchain, axiom or admission-policy change | Recompute affected keys and recheck required obligations | New environment/receipt versions; reuse only through an explicit compatibility policy |
| Unsound proof, tampered artifact or withdrawn authority | Revoke/quarantine; transitive dependency impact analysis | Prevent new admission/use; retain the original artifact and reason for audit |

Promotion computes the candidate's dependency closure, reviews interpretation changes, revalidates impacted proofs, runs regression/holdout gates, and atomically selects a new release. Historical snapshots remain reproducible; current queries disclose unresolved or stale dependencies. Rollback is a new selection event and cannot reactivate a known-revoked artifact without a new admissibility decision.

Consistency checks have distinct levels: content/referential integrity; typing and scoped definitions; temporal/jurisdiction applicability; translation guarantees; bounded satisfiability/counterexample checks; and review of conflicting interpretations. Record each result and its scope. Arbitrary full-corpus consistency is not generally decidable; “no conflict found under these bounds” is the honest result, not a global guarantee.

Normative conflicts need their own semantics. An obligation and a prohibition are not automatically ordinary factual `P` and `not P`; exploding an inconsistent encoding into arbitrary theorem success would be reward hacking. Detect vacuous obligations and inconsistent assumption sets in supported fragments, preserve conflict sets/unsat cores when available, and quarantine unsupported conflict resolution. A source-citation cycle is permissible; a proof cannot discharge itself through circular premise reuse.

## 9. Autoencoder and recursive improvement, with JevOps integration

The companion [autoencoder control and training plan](AUTOENCODER_DUCKDB_DUCKLAKE_TRAINING_PLAN.md)
specifies versioned language/model variants, parallel workers, existing
DuckDB/Quack and DuckLake interface reuse, immutable Arrow snapshots, touched-row
update persistence, and asynchronous Hugging Face release publication. It records
current durability and legacy tensor-migration gaps and preserves the admission
and evaluation requirements below.

Keep two related but separately evaluated learning tasks:

- **Legal semantic proposal:** source spans and retrieved scoped definitions to family/profile choice, typed IR/AST candidates, uncertainty and clarification needs. Start with the existing deterministic compiler plus advisory heads; add a genuine sequence/tree decoder only as a separately measured implementation.
- **Proof and rewrite optimization:** accepted statements/IR plus checked proof trajectories to shorter/faster proofs, rule selection, structural compression and premise/tactic ranking. This submodule owns experiment orchestration, data and training integration; it may reuse JevOps capabilities through the explicit verifier/benchmark adapter.

The upstream adaptive modal autoencoder explicitly positions itself as a diagnostic/advisory model. Audit which parameters actually train, whether embeddings are real, and whether sample memory is returning known answers. Require no-memory evaluation (`use_sample_memory=False` where supported), unseen-lineage evaluation, and a deterministic baseline before attributing improvement to learned compression.

Initial loss design: masked reconstruction/AST-token cross-entropy, family/slot classification cross-entropy, pinned-embedding cosine/contrastive losses, uncertainty calibration, and supervised proof-action/ranking loss. Track components separately; tune their weights and learning rate on a development split using fixed budgets, gradient/NaN checks, clipping, early stopping and reproducible checkpoints. Missing targets or unsupported families must not produce fabricated zero-loss success.

Cosine similarity is a semantic diagnostic, not proof or legal-fidelity evidence. Hard negatives should differ in one critical feature: negation, norm operator, quantifier, exception, unit, deadline, scope, or effective date. A high-similarity wrong interpretation must still fail admission. Report mock-embedding controls separately; do not market them as semantic generalization.

JeV/fuzzy approximators and neuro-symbolic cellular automata may guide ranking, search or a separately trained differentiable surrogate. Check gradients reach the intended parameters; discrete prover outcomes do not automatically differentiate through Lean. Calibrate guidance against independent outcomes and ablate it. Neither a fuzzy score nor a learned evaluator overrides type checks, kernel verification, source review or policy.

Use compressed outputs as teacher targets only when they retain the same admitted formal meaning, have valid source/ontology lineage, and pass the fixed verifier and scoring policy. Legal semantic training needs independently reviewed labels, not merely proofs of the model's own translations. Keep failed/ambiguous examples as explicitly negative or abstention examples in separate membership classes; never launder them into positive proof supervision.

Freeze training/dev/final-holdout membership before tuning. Group amendments, duplicate sections, paraphrases, proof variants, ontology descendants and other shared-lineage variants together to prevent leakage. Add unseen-title/family and future-release evaluations. Repeatedly inspected canaries become development data; final holdouts remain inaccessible to the outer loop and are refreshed with separately governed releases.

The outer loop, implemented and tested in this submodule, can propose parser/compiler changes, prompt experiments, ontology mappings, tactics and model updates in isolated worktrees. It cannot edit admission rules, holdout answers, trust anchors or benchmark definitions in its own experiment. The inner loop collects full attempts, costs, failures, source/semantic checks and independent verification. Only reviewed changes passing frozen gates enter a candidate release. Budget exhaustion or no improvement ends a run with evidence, not an unbounded self-authorizing process. Integrating JevOps does not transfer ownership of this loop or require relocating the legal pipeline back into JevOps.

Each training manifest binds accepted example CIDs, labels/reviews, split policy, dependencies, model architecture, seeds, hyperparameters, data-selection code and evaluator revisions. If a source/interpretation is revoked later, mark affected manifests/models and prevent contaminated labels from entering future training. Retraining/remediation is explicit; excluding rows from the next manifest does not prove that old weights have unlearned them.

## 10. Evaluation and anti-reward-hacking requirements

Optimize tokens and heartbeats only inside the feasible set defined by unchanged accepted meaning, allowed assumptions/dependencies, verification and review. Keep the existing Lean Refactor Arena compression score separate from legal-autoformalization fidelity/coverage. Better compression on a fixed theorem does not establish better legal translation.

Record the tokenizer/version and count target proof text, new helper declarations/import dependencies, elaborated proof size where available, and shared-library cost under a fixed amortization rule. A one-token reference to a previously stored theorem is retrieval reuse, not evidence that the neural model compressed all source meaning into one token. Report both marginal reuse cost and attributable/full dependency cost; reject circular or held-out theorem lookup.

Record Lean/toolchain/environment, heartbeat settings and measurement boundary, per-attempt and aggregate heartbeats, wall time, verification/search/LLM costs, timeouts, memory and bytes stored. Report cold and warm/cache-hit results separately. Fix worker/isolation settings for comparisons, measure repeated trials where variability exists, and retain denominators and failed attempts. Never improve an average merely by dropping difficult/unsupported provisions.

Pilot dashboard: source lineage completeness; extraction coverage; semantic fidelity by clause/family; critical-error and abstention rates; calibration; unsupported/unresolved counts; conditional proof success; axiom/dependency changes; conflict rates; ontology-reuse precision; compression Pareto frontier; ingestion/retrieval/verification/training cost. Calibrate numeric promotion thresholds after the baseline, not after seeing which candidate wins. Zero tolerated admission-integrity violations is a hard gate, not an accuracy estimate.

Required test suites:

- Identity: canonicalization golden vectors, ordering/Unicode rules, raw CID versus wire identity, digest disguised as CID, corrupted bytes, wrong source revision, unresolved closure and schema migration.
- Persistence: close/reopen without in-memory state, duplicate/conflicting insert, writer contention, crash at every publication stage, WAL/scratch headroom, backup/restore and no accidental SQLite fallback.
- Source: exact selector replay, truncated text, missing subsection/exception, editorial-note confusion, mixed snapshot, amendment/renumbering and unresolved incorporated definitions.
- Semantics: obligation/permission/prohibition swaps, quantifier/negation scope, unless/and/or mutations, deadline versus minimum duration, unit/calendar boundaries, explicit unknowns and conflicting interpretations.
- Proof: unchanged goal with changed helper definition, new axiom/import, `sorry`/admission bypass, fabricated receipt, stale premise, circular reuse, inconsistent assumptions and inappropriate unbounded conclusions from bounded checks.
- Evolution: proof-only replacement, genuinely equivalent IR, non-equivalent correction, temporal amendment, ontology/compiler change, transitive invalidation, historical query and rollback excluding revoked evidence.
- Learning: mock versus real embedding, sample-memory leakage, family/lineage contamination, counterfactual negatives, frozen holdout access, removed-label lineage, and gradients reaching the declared trainable parameters.
- Security: hostile document/prompt content, unsafe paths, malformed/oversized payloads, tool-call injection, generated-code escape attempts, network/credential access and unauthorized catalog/policy mutations.

The opt-out test-seal mechanism can accelerate developer feedback, but mtime is only a hint. Bind content/AST dependencies, fixture/input identities, dependency packages, configuration and relevant environment in the seal; dynamic/unknown dependencies force rerun. Mark a reused result as cached, not newly executed. Release, migration, integrity and final-holdout gates require fresh execution or a narrowly approved independent verification-cache policy, never a bare “emit true.”

Generate machine receipts and large reports programmatically from structured records; use an LLM only for bounded hypotheses or clearly labeled summaries. Preserve receipts even for rejected candidates.

## 11. Delivery sequence and exit gates

| Phase | Deliverable | Exit evidence |
| --- | --- | --- |
| 0. Pin and audit | Pin this submodule and reconcile reference-checkout findings; explicit adapter manifest; pinned HF family/identity adapter; supported semantics matrix | No implicit checkout mixing; existing local legal work preserved; small fixture rows decode correctly; source IDs and storage/logical CIDs independently validated |
| 1. Durable ledger | DuckDB artifact bytes, catalog, release events and coordinated writer | Fresh-process restore, tamper/idempotency tests, crash recovery and storage-cap tests pass |
| 2. Source-grounded pilot | Approximately 100–300 reviewed clauses, stratified across definitions, exceptions, numeric/time conditions and cross-references | Every admitted interpretation has replayable source spans and declared authority/scope; lineage splits frozen |
| 3. LegalIR and family views | Typed candidates, explicit ambiguity/unsupported states, checked or bounded translation profiles | Semantic mutation controls fail appropriately; no unknown-modality coercion; reviewers can inspect discrepancies |
| 4. Proofs and reuse | Isolated proof routing/reconstruction, ontology retrieval and mapping gates | Conditional proofs bind complete contexts; negative reuse controls rejected; baseline cost/fidelity report |
| 5. Version evolution | Supersession, dependency invalidation, temporal queries and release rollback | Amendment/correction/revocation simulations preserve history and block stale current use |
| 6. Controlled learning | Real-embedding/no-memory baselines, reviewed training snapshots, bounded submodule-owned outer-loop experiments with a JevOps adapter where needed | Held-out fidelity/coverage gates hold; improvement survives ablations; scorer/policy untouched |
| 7. Scale and operations | Additional titles/profiles, sparse streaming, monitoring, independent snapshot publication workflow | Measured throughput/cost/capacity, bounded recovery times, audited availability and retained historical releases |

Use the Title-35-focused connector for the first bounded acquisition slice because it already exists, not because patents represent the whole Code. Choose clauses with reviewer availability and a deliberately mixed difficulty profile; reserve other titles and later source versions for generalization tests. The pilot is a risk-discovery exercise, not a statistically sufficient claim of all-Code accuracy.

Implementation ownership is entirely in this `ipfs_datasets_py` submodule. Extend existing packages rather than introducing a parallel `jevops/legal_pipeline/` implementation:

- `ipfs_datasets_py/processors/legal_data/` and the existing legal scraper packages: source releases, manifest adapters, source spans and legal-data ingestion.
- `ipfs_datasets_py/logic/autoformal/`: source-to-IR-to-proof orchestration and small source, ontology, admission, evaluation and verifier-adapter interfaces; preserve and build on its existing work.
- `ipfs_datasets_py/logic/legal_ir/`, `logic/formalization/`, `logic/families/` and `logic/ir_core/`: typed semantics, views, canonical identities and lineage contracts.
- `ipfs_datasets_py/logic/proof_corpus/` and `logic/common/duckdb_proof_store.py`: durable DuckDB artifacts/catalogs, identity mapping, release selection and invalidation.
- Existing modal autoencoder and `optimizers/logic_theorem_optimizer/` components: model adapters, reviewed training membership and loss/evaluation integration.
- `scripts/ops/legal_data/` and `scripts/ops/legal_ir/`: bounded experiment runners, recursive-improvement orchestration and programmatic receipts/reports.
- This repository's `tests/unit/logic/`, corresponding processor tests and integration suites: all new contracts, restart/migration tests, semantic controls and end-to-end fixtures.
- `docs/implementation/plans/` and the existing legal-domain documentation: the canonical plan and implementation guidance.

These are implementation boundaries, not claims that the proposed interfaces already exist. JevOps remains a pinned optional dependency/consumer for proof search, native checks and Arena comparisons. Put new legal-pipeline integration code and tests here; any later change to JevOps itself must be separately scoped rather than implied by this plan. No benchmark receipts, source corpora, caches or existing JevOps implementation are moved by this documentation migration.

The first implementation PR should cover phases 0–1 with synthetic fixtures and a narrowly selected source sample: establish durable bytes and honest identity mapping before adding model complexity. The second should produce one fully auditable chain from an exact source span through reviewed IR to a conditional checked proof, then replace it with a new version and demonstrate historical retrieval and downstream invalidation.

## 12. Decisions still requiring evidence or project ownership

The plan fixes the initial HF anchor, DuckDB storage, immutable lineage, bounded pilot and trust separation. Before production admission, designate legal/domain reviewers, select supported deontic/temporal semantics, specify legal-currentness and external-authority policy, and set explicit evidence/axiom allowlists. Before large runs, agree compute/storage budgets, model hosting/privacy constraints and final benchmark ownership. Before publishing, select IPFS retention/replication, signing keys and HF destination/permissions; source and derived-data rights need separate review.

Known unverified areas: actual current-release Parquet row compatibility and complete CID closure; full-corpus acquisition/currentness; legal-family completeness; durable end-to-end restart behavior; independent fidelity of generated interpretations; and achievable learning/compression improvements. Resolve these with the staged tests above rather than architecture claims.

Related in-repository design: [Hammer/Leanstral LegalIR optimization plan](HAMMER_LEANSTRAL_LEGAL_IR_NEXT_OPTIMIZATION_PLAN.md). Coordinate with its existing implementation rather than creating a competing orchestration stack; this plan adds versioned source authority, durable proof lineage and release-consistency gates.

Optional sibling-workspace background: JevOps' [knowledge graph proof plan](../../../../../JevOps/KNOWLEDGE_GRAPH_PROOF_PLAN.md), [structural autoencoder plan](../../../../../JevOps/STRUCTURAL_AUTOENCODER_PLAN.md), and [token/heartbeat safety plan](../../../../../JevOps/LEAN_TOKEN_HEARTBEAT_SAFETY_PLAN.md). Those separate initiatives remain in JevOps; the full U.S. Code initiative described here lives in this submodule and does not weaken their proof/benchmark boundaries.
