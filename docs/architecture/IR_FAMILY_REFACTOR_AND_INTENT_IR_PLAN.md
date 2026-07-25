# IR Family Refactor and Intent IR Plan

Status: proposed implementation plan
Date: 2026-07-24
Scope: `ipfs_datasets_py`, with execution by the
`ipfs_accelerate_py.agent_supervisor`

## Executive decision

Refactor Security IR with a strangler migration and introduce Intent IR as a
new domain adapter over a small shared IR kernel. Do not rename the existing
Security IR package in place, and do not copy the Legal IR autoencoder into a
third domain-specific implementation.

The target flow is:

```text
pinned SkillCenter snapshot
  -> quarantined, bounded source records
  -> source/provenance GraphRAG index
  -> validated Intent IR
  -> semantic intent graph
  -> deterministic formal-logic views
  -> learned formalization advisor
  -> verifier/prover receipts
```

The learned component proposes a formalization or a bounded repair. It is not
the authority for provenance, schema validity, proof, trust, or permission to
execute a skill.

The work is split into three coordinated programs:

1. extract the domain-neutral contracts already present in Legal IR;
2. migrate Security IR behind those contracts while preserving compatibility;
3. build Intent IR, SkillCenter ingestion, GraphRAG, formalization, and
   evaluation on the same contracts.

The companion execution artifacts are:

- `ir_family_refactor_intent_ir.objectives.md`, the durable goal heap; and
- `ir_family_refactor_intent_ir.todo.md`, the reviewed implementation board.

## Outcomes

The program is complete when:

- Legal, Security, and Intent documents share stable envelope, provenance,
  diagnostics, schema-version, identity, artifact-manifest, and formalization
  protocols;
- the existing Security IR imports and serialized v1 artifacts remain
  readable during a documented deprecation window;
- a Security declaration has a stable identity that does not change when a
  solver runs or when optional CID libraries are installed;
- SkillCenter bundles are fetched by immutable revision, hashed, opened
  read-only, bounded, licensed, and treated as hostile data;
- each extracted Intent IR assertion and action is traceable to source bytes;
- GraphRAG artifacts and formal-logic artifacts are independently versioned
  and content addressed;
- deterministic lowering provides a reviewable baseline before any learned
  advisor is used;
- training and evaluation splits cannot leak variants of one source document
  across train and test;
- proof, runtime monitoring, evidence readiness, and release policy have
  distinct result types and authority;
- compatibility, conformance, security, round-trip, and benchmark gates pass.

## Non-goals

This plan does not:

- execute commands found in a skill during ingest, indexing, normalization,
  training, or evaluation;
- treat a model-generated formula as a theorem;
- give GraphRAG retrieval results proof or policy authority;
- infer that a popular or high-scoring skill is safe;
- ingest the full multi-gigabyte corpus before the pilot gates pass;
- delete the current `security_ir_artifacts` tree during the initial audit;
- require Legal, Security, and Intent to use the same domain ontology;
- make network access or a live language model a unit-test dependency.

## Evidence from the current repository

### Legal IR

Legal IR already contains most of the reusable architectural patterns:

- `logic/legal_ir_compiler_api.py` provides a compact compiler contract;
- `logic/legal_ir_pass_manager.py` describes a useful staged pass model;
- `logic/legal_ir_schema_evolution.py`, `legal_ir_source_maps.py`, and
  `legal_ir_diagnostics.py` provide migration, grounding, and diagnostics;
- `logic/legal_ir_proof_carrying_artifacts.py` demonstrates artifact binding;
- `optimizers/logic_theorem_optimizer/modal_ir.py` provides immutable modal
  formulas and stable serialization;
- `logic/integration/reasoning/legal_ir_view_contracts.py` distinguishes
  derived views and repair lanes.

The reusable concepts should move behind domain-neutral interfaces. The
Legal-specific corpus and training classes must remain adapters:

- `LegalSample` requires `source == "us_code"`;
- `LegalModalAutoencoderLoop` and the large modal autoencoder contain
  Legal-specific views, labels, and assumptions;
- the later multiview bridges become US-law-specific.

Intent IR should therefore consume a generic `FormalizationSample` and
`FormalizationAdvisor` contract, not `LegalSample`.

### Security IR

The current package is a crypto-exchange and Xaman verification application
under a nominally generic name:

```text
logic/security_models/crypto_exchange/
```

The main risks are:

- `SecurityModelIR` uses weakly typed `list[dict]` fields and combines shared,
  exchange, wallet, and Xaman vocabulary;
- declarative facts, proof obligations, solver outputs, runtime traces, and
  disproof vectors live in one mutable object;
- running verification can therefore change the model identity;
- `ir/cid.py` emits different identifier forms depending on optional
  dependencies;
- canonicalization has no declared set-like versus ordered-list semantics;
- claims compile directly to Z3 instead of a solver-neutral obligation;
- `prove_all.py` mixes extraction, policy, solver orchestration, reports, CLI,
  and writes;
- a Xaman evidence-readiness query can be reported as theorem proving even
  though its blocking assumptions force satisfiability;
- mutable caller data and shallow-copied nested defaults permit
  mutation-after-validation;
- 269 tracked files under `security_ir_artifacts` mix sources, promoted
  evidence, transient solver/compiler output, and ambiguous `-new` variants;
- public imports are also advertised through `logic/submodule_registry.py`.

Focused existing Security IR tests passed in the audit (`97 passed, 2
solver-dependent skips`), which provides a useful behavior baseline but not a
successful real-solver run.

### SkillCenter

The dataset card currently describes 216,938 skills across 24 SQLite FTS5
bundles and three source populations. The repository includes a small security
bundle and GitHub lite bundle suitable for a pilot, as well as a much larger
GitHub bundle. Dataset Viewer is disabled, so the source adapter must consume
the repository artifacts rather than assuming row-streaming API support.

The initial immutable Hub revision inspected for this plan is:

```text
f9dd4fec3c86d85ebf116c7408ac5ce602c418a1
```

This is a pilot default, not a magic global constant. Every run must record the
chosen revision and file hash.

Sources:

- https://huggingface.co/datasets/Tommysha/skillcenter-bundles
- https://huggingface.co/datasets/Tommysha/skillcenter-bundles/tree/main
- https://github.com/LabRAI/SkillCenter

## Target architecture

Use the following package boundaries:

```text
ipfs_datasets_py/logic/
  ir_core/
    canonical.py
    identity.py
    model.py
    provenance.py
    diagnostics.py
    schema_registry.py
    claims.py
    evidence.py
    artifacts.py
    protocols.py

  formalization/
    samples.py
    views.py
    compiler.py
    advisor.py
    evaluation.py

  legal_ir/
    adapter.py
    views.py
    compatibility.py

  security_ir/
    model.py
    adapter.py
    results.py
    exchange/
    xaman/

  intent_ir/
    schema.py
    canonicalize.py
    protocols.py
    source_adapters/
    normalize/
    graphrag/
    formalize/
    evaluation/

  backends/
    registry.py
    z3/
    cvc5/
    smtlib/
```

The existing Legal and
`logic.security_models.crypto_exchange` locations remain compatibility
facades until downstream imports and artifacts have migrated.

### Dependency direction

The allowed dependency direction is:

```text
domain schema -> ir_core
domain adapter -> domain schema + ir_core + formalization protocols
backend adapter -> backend protocol + optional solver
pipeline/orchestrator -> domain adapters + backends + artifact store
compatibility facade -> new domain package
```

`ir_core` must not import Legal, Security, Intent, GraphRAG, a model runtime, or
a solver. Intent schema code must not import heavyweight GraphRAG or
autoencoder modules. Optional capabilities are discovered without installing
packages as a side effect.

## Shared IR kernel contracts

### Immutable document envelope

The shared envelope should contain:

- domain and schema version;
- stable document identifier;
- canonical declarative payload;
- source-reference identifiers;
- extension vocabulary identifiers;
- producer and configuration identities;
- parent artifact identities;
- review state.

Raw source text, embeddings, model responses, solver logs, runtime traces, and
reports stay in separate artifacts.

### Canonicalization and identity

Define one versioned identity profile with:

- canonical UTF-8 JSON;
- explicit normalization of numbers, strings, nulls, and maps;
- a schema declaration for ordered, set-like, and multiset collections;
- fixed multihash algorithm and multicodec;
- a deterministic textual representation whether optional CID libraries are
  installed or not;
- domain and schema version in the identity preimage;
- golden canonical-byte and identifier vectors.

Legacy Security identifiers are retained as `legacy_id` values in migration
manifests. They are never silently rewritten.

### Provenance and diagnostics

Every assertion, action, relation, and formula must bind to one or more stable
source references. A reference includes:

- source URI and source-native identifier;
- immutable repository revision;
- exact content digest and optional CID;
- containing bundle digest;
- source span when available;
- license expression and review status.

Diagnostics are structured, content addressable, source mapped, and assigned
stable codes. Warnings cannot silently become successful proofs.

### Claims and result authority

Use solver-neutral `Claim` and `ProofObligation` records. Backend compilers
lower those records to Z3, cvc5, SMT-LIB, Lean, Coq, or other targets.

Keep four result families separate:

| Result | Meaning | May claim theorem authority? |
| --- | --- | --- |
| `ProofResult` | A formal property was checked under explicit assumptions | Only under configured proof policy |
| `MonitorResult` | A bounded runtime trace satisfied or violated a monitor | No |
| `EvidenceGateResult` | Required evidence or blockers were present | No |
| `PolicyDecision` | A release/security policy evaluated inputs and evidence | No |

All results bind the immutable declaration identity, obligation identity,
backend/version, assumptions, resource bounds, and output digest.

### Artifact manifest

Each pipeline run has an immutable manifest containing:

- input and parent CIDs/digests;
- schema and ontology versions;
- repository commit;
- tool, model, and solver versions;
- configuration and prompt-template digests;
- deterministic outputs and hashes;
- bounded diagnostics;
- explicitly separated nondeterministic timing/environment observations;
- review, license, and trust decisions.

## Security IR refactor

### Stage S0: freeze the compatibility surface

Before moving code:

1. inventory public Python imports, CLI commands, schema payloads, reports,
   receipts, and `submodule_registry` entries;
2. select a small `security-ir-v1` golden corpus containing a normal exchange
   model, Xaman model, invalid models, and legacy receipts;
3. record canonical bytes and both current CID representations;
4. add mutation-after-validation and collection-order fixtures;
5. write an ADR that separates declarations from derived results;
6. announce a deprecation window for legacy paths.

The freeze is a compatibility contract, not approval of the old semantics.

### Stage S1: introduce `ir_core`

Extract and test:

- immutable envelope and source references;
- diagnostics and source maps based on Legal IR patterns;
- schema registry and migration protocol;
- explicit canonicalization profile and stable identity;
- solver-neutral claims, obligations, evidence, and result envelopes;
- artifact manifests and backend/domain protocols.

Do not change existing Security behavior in this stage.

### Stage S2: define Security IR v1 declarations

Create an immutable, typed `SecurityIR` containing only declarations:

- principals, assets, trust zones, channels, resources;
- policies and state-machine declarations;
- threat-model assumptions;
- source-grounded security claims;
- extension vocabulary identifiers.

Create separate immutable records for:

- `VerificationRun`;
- `RuntimeTrace`;
- `DisproofVector`;
- `EvidenceGateResult`;
- `ReleasePolicyDecision`;
- `ProofReceipt`.

Copy and normalize mutable input at the adapter boundary. Never retain
caller-owned collections.

### Stage S3: isolate domain adapters

Move exchange-specific vocabulary, assumptions, validators, and default claims
to `security_ir/exchange`. Move Xaman task IDs, evidence readiness, artifact
paths, reports, and policies to `security_ir/xaman`.

The Xaman blocker query becomes an evidence gate. A theorem result is possible
only after the underlying security property is actually encoded and checked.

Unknown vocabulary follows one consistent extension protocol:

- a declared vocabulary ID and version;
- namespaced terms;
- adapter validation;
- fail-closed behavior for an unavailable adapter.

### Stage S4: decouple solver backends

Replace `compile_to_z3()` with:

```text
Claim
  -> backend-independent ProofObligation
  -> selected backend compiler
  -> bounded backend invocation
  -> typed result
```

Backend capability checks are side-effect free. Provisioning is explicit.
Portfolio order cannot change the logical verdict: all attempts are recorded,
and policy deterministically selects the accepted result.

### Stage S5: normalize artifacts

Inventory first; delete nothing in the initial migration. Classify existing
files into:

```text
security_ir_artifacts/
  inputs/
  golden/
  runs/<run-id>/
  promoted/
  migrations/
  archive/
```

Create a manifest for every promoted artifact and a migration map for every
legacy ID. Add repository policy that rejects temporary compiler output,
mutable `latest` aliases, ambiguous `-new` files, and unmanifested promoted
evidence.

### Stage S6: compatibility facade and deprecation

Old modules re-export the new types or adapt legacy values. Contract tests
cover:

- old imports;
- old input decoding;
- old report reading;
- CLI exit codes and bounded output;
- registry discovery;
- legacy-to-v1 round trips.

Only one integration task edits package `__init__.py`,
`logic/submodule_registry.py`, or shared CLI registration. Remove shims only
after the documented deprecation window: at least two consecutive minor
releases and 180 days after the first published warning, whichever ends later,
plus measured downstream migration and the removal approvals in
`docs/security_verification/SECURITY_IR_MIGRATION.md`.

## Intent IR scaffold

The initial scaffold lives at `ipfs_datasets_py/logic/intent_ir` and provides:

- immutable, source-grounded `IntentIRDocument` types;
- explicit goal, condition, effect, invariant, failure, verification, action,
  and control-flow concepts;
- deterministic canonical JSON and SHA-256 digest;
- normalizer, GraphRAG projector, formalizer, and artifact-store protocols;
- a bounded read-only SkillCenter SQLite adapter;
- focused schema and adapter tests.

The scaffold intentionally omits production downloading, model-based
normalization, a final ontology, formal lowering, autoencoder integration, and
execution.

### Intent document semantics

An Intent IR document describes what a source says to do, not what the system
has authorized:

- `goal`: desired outcome;
- `precondition`, `guard`, and `assumption`: conditions on applicability;
- `action`: actor, verb, objects, tools, inputs, and outputs;
- `effect` and `postcondition`: expected state changes;
- `invariant`: condition intended to remain true;
- `failure`: explicit failure branch;
- `verification`: claimed check or observable success criterion;
- `control edge`: next, success, failure, conditional, retry, parallel, join;
- `modality`: asserted, intended, required, recommended, permitted,
  prohibited.

Authorization, trust, risk, sandbox policy, and proof status are separate
layers.

### Versioning

Before v1:

- add a strict versioned decoder and migration registry;
- define extension and unknown-term behavior;
- define stable URI/identifier namespaces;
- distinguish ordered action/control sequences from set-like tags/references;
- publish JSON Schema and golden vectors;
- require every semantic node to be grounded or explicitly marked inferred;
- retain normalizer confidence and review state without treating confidence as
  truth.

## SkillCenter ingestion

### Snapshot contract

Every ingestion run requires:

- dataset ID;
- immutable Hub commit/revision;
- repository filename;
- expected or observed file size;
- local SHA-256 and optional IPFS CID;
- bundle metadata and schema profile;
- downloader and adapter version.

Reject mutable `main`, non-SQLite bytes, schema drift, missing joined rows,
declared/actual row-count mismatch, oversized fields, and truncated records.

### Safe SQLite access

Open bundles:

- read-only and immutable;
- with `PRAGMA query_only=ON`;
- with extension loading disabled;
- with expected table/column validation;
- with keyset pagination in stable `skill_id` order;
- with explicit row, text, batch, time, and output bounds.

Do not interpolate user values into SQL. Do not instantiate arbitrary YAML
objects. Read allowlisted scalar metadata or use a safe parser with strict
size/depth/type limits.

### Trust and licensing

Skill text, metadata, URLs, verification commands, and retrieved neighbors are
hostile data. Store and display them as quoted data. They must not change
system prompts, invoke tools, import code, access secrets, or execute shell
commands.

The framework repository license does not override each source skill's
license. Retain per-record license metadata and classify records:

- `allow_train_and_publish`;
- `allow_internal_evaluation`;
- `metadata_only`;
- `quarantined_unknown`;
- `excluded`.

Unknown or contradictory license terms fail closed. Deduplicate before
splitting and retain source lineage even when content is excluded.

Scan for secrets, credentials, personal data, malicious payloads, generated
binary content, and source-fetch anomalies. Quarantine findings; do not
silently scrub and train.

### Pilot sequence

Use two small, structurally different bundles first:

1. `clawskills-bundle-lite-security-v20260227.sqlite` for generated technical
   security procedures with rich provenance; and
2. `github-skillmd-bundle-lite-v20260608.sqlite` for community-authored
   `SKILL.md` variation and thin metadata.

The pilot should use a bounded sample and then the complete two small bundles.
Do not ingest the approximately 2.43 GB GitHub-all bundle until the pilot meets
quality, safety, license, throughput, and reproducibility gates.

## GraphRAG design

Use two related but distinct graphs.

### Corpus evidence graph

Built from source records before final semantic normalization:

Nodes:

- dataset revision, bundle, source document, repository, skill, section,
  source span, license, domain, author/publisher, tool mention, entity mention.

Edges:

- `CONTAINS`, `DERIVED_FROM`, `SAME_PRIMARY_SOURCE`, `DUPLICATE_OF`,
  `MENTIONS`, `HAS_LICENSE`, `HAS_DOMAIN`, `CITES`, `NEIGHBOR_OF`.

This graph supports retrieval and provenance. Retrieval similarity is not a
semantic assertion.

### Semantic intent graph

Projected only from validated Intent IR:

Nodes:

- intent document, goal, statement, action, actor, resource, tool, input,
  output, failure, verification criterion, formal symbol.

Edges:

- `HAS_GOAL`, `REQUIRES`, `GUARDED_BY`, `PERFORMS`, `USES`, `CONSUMES`,
  `PRODUCES`, `CAUSES`, `VERIFIED_BY`, `NEXT`, `ON_SUCCESS`, `ON_FAILURE`,
  `RETRIES`, `PARALLEL_WITH`, `JOINS`, `GROUNDED_IN`, `LOWERS_TO`.

Every semantic node and edge binds the Intent IR digest and source references.
The ontology has its own version and migration rules.

### Storage boundary

Use current `knowledge_graphs/storage/ipld_backend.py` interfaces or a small
adapter around them. Do not add new dependencies on the deprecated
`knowledge_graphs/ipld.py`. Wrap mature GraphRAG primitives behind the
`IntentGraphProjector` protocol because some high-level unified processors are
still placeholders.

Graph artifacts store identities and bounded properties; source bodies and
large embeddings remain separately addressed.

## Formal-logic lowering

Implement deterministic, typed views before training a learned advisor.

| Intent concept | Primary formal view |
| --- | --- |
| entities, types, relations | first-order/F-logic or typed KG facts |
| goal and intended effect | goal/intention modal formula |
| required, permitted, prohibited | deontic modal formula |
| action with pre/effects | action/dynamic logic and Hoare-style contract |
| next, branch, retry, parallel, join | workflow/state-machine and temporal logic |
| invariant and failure | safety/liveness obligation |
| verification criterion | observation/evidence obligation |
| uncertainty or inferred relation | annotated assumption, never an asserted theorem |

The compiler emits a multiview `FormalizationArtifact`:

- normalized symbol table;
- view-specific formulas;
- cross-view links;
- unsupported-semantics diagnostics;
- proof obligations;
- source map;
- compiler/configuration identity.

Unsupported semantics fail explicitly or remain as grounded opaque terms. They
are never silently dropped.

## Autoencoder and learned advisor

### Refactor strategy

Extract a domain-neutral layer from Legal IR:

- `FormalizationSample`;
- source-free feature tensor contract;
- view registry;
- encoder/decoder protocol;
- advisor proposal and bounded-repair protocol;
- checkpoint manifest;
- evaluation receipt.

Keep domain heads and label spaces separate:

```text
shared encoder candidate
  + legal view heads/checkpoint
  + security view heads/checkpoint
  + intent view heads/checkpoint
```

Do not load Legal head weights into Intent heads by default. A shared encoder
transfer experiment is allowed only against a from-scratch baseline and with
separate checkpoint namespaces.

### Authority order

The pipeline order is:

1. validate source and provenance;
2. normalize and validate Intent IR;
3. compile deterministic formal views;
4. ask the learned advisor for a candidate or repair;
5. type-check and schema-check the candidate;
6. compare against deterministic and curated references;
7. run configured solvers/provers;
8. retain all diagnostics and receipts;
9. require human review for promoted gold data or high-risk semantics.

The advisor cannot alter source references, assumptions, declared modalities,
license state, or trust state.

### Data preparation and leakage control

Create examples only after deduplication. Split by groups, not rows:

- `primary_source_id`;
- source repository/document;
- near-duplicate cluster;
- generation prompt/model hash where applicable.

Keep all variants in one split. Add held-out domains and time/revision splits.
Never let GraphRAG retrieve training documents while evaluating a test
document. Record graph and embedding snapshot IDs in each example.

Use three label tiers:

- curated human-reviewed gold;
- deterministic compiler silver;
- model-generated weak labels.

Weak labels may bootstrap an advisor but cannot be evaluation truth or proof
authority.

## Evaluation

### Ingestion

- exact snapshot reproducibility;
- row-count and digest agreement;
- resume/keyset determinism;
- rejection of mutable revision, malformed SQLite, schema drift, oversize
  fields, unsafe metadata, and prompt-injection fixtures;
- license and quarantine coverage.

### Intent IR

- schema validity and canonical round trip;
- source-grounding coverage;
- action/control cross-reference validity;
- deterministic identity;
- mutation resistance;
- unknown-term and migration behavior;
- inter-annotator agreement on a curated sample.

### GraphRAG

- provenance-edge precision;
- retrieval recall at fixed bounded `k`;
- duplicate/source-family leakage rate;
- ontology conformance;
- digest-stable rebuild;
- adversarial retrieval isolation.

### Formalization

- exact formula/view accuracy where feasible;
- symbol grounding and source-map coverage;
- goal/action/condition/modality/control-flow F1;
- type-check rate;
- satisfiable/unsatisfiable agreement;
- proof-obligation closure;
- unsupported-semantics recall;
- decompile/round-trip semantic equivalence;
- semantic mutation sensitivity.

### Learned advisor

- paired result versus deterministic compiler;
- held-out-source and held-out-domain performance;
- from-scratch versus Legal-encoder initialization;
- repair acceptance rate;
- false-proof and false-completion count;
- calibration by review state;
- latency, memory, and token/compute cost.

Promotion requires zero authority-boundary violations and zero test leakage,
not merely a higher aggregate model score.

## Parallel delivery plan

The task board uses four conflict-aware lanes:

```text
lane A: shared contracts and identity
lane B: Security compatibility and domain isolation
lane C: Intent ingest, schema, and GraphRAG
lane D: formalization, evaluation, and rollout
```

The reviewed board has this dependency schedule. A wave becomes eligible when
all prior dependencies are complete; the four-lane resource ceiling may split
one row across multiple supervisor admissions.

| Wave | Eligible tasks | Outcome |
| --- | --- | --- |
| 0 | `IRF-001`, `003`, `010`-`013` | Security freeze/inventory and four independent core contracts |
| 1 | `IRF-002`, `014`, `023`, `030` | golden Security corpus, manifests, backends, Intent v1 schema |
| 2 | `IRF-020`, `031`, `040` | Security v1, pinned snapshots, formalization contracts |
| 3 | `IRF-021`, `022`, `024`, `032`, `043`, `044` | domain adapters, result authority, source policy |
| 4 | `IRF-025`, `033`, `034` | artifact migration, normalization, corpus graph |
| 5 | `IRF-035` | semantic intent graph |
| 6 | `IRF-036`, `037`, `050` | pilot, bounded retrieval, features/splits |
| 7 | `IRF-041`, `051` | deterministic Intent compiler and generic advisor |
| 8 | `IRF-042`, `052`, `060` | obligations/round trip, Intent advisor, compatibility exports |
| 9 | `IRF-053`, `061` | paired benchmark and cross-domain/offline integration |
| 10 | `IRF-062` | reviewed migration, operations, and rollout gates |

Integration files have a single owner. In particular, only the final
compatibility task edits package exports, `logic/submodule_registry.py`, or
shared CLI registration. Agents should prefer new modules and adapters over
concurrent edits to the large Legal autoencoder or `prove_all.py`.

See the task board for file ownership, dependency edges, validation commands,
and acceptance criteria.

## Rollout gates

The operational interface is `IRFamilyRollout@1`. The detailed operator
procedure is in `docs/guides/IR_FAMILY_OPERATIONS.md`; the legacy Security
migration and compatibility policy is in
`docs/security_verification/SECURITY_IR_MIGRATION.md`. A stage change is a
reviewed configuration and manifest change, never an inference from a model
score or a mutable `latest` artifact.

The learned Intent advisor has four ordered stages:

| Stage | Learned path | Consumer-visible effect | Promotion condition |
| --- | --- | --- | --- |
| `off` | Not loaded or invoked | Deterministic compiler output only | Default and rollback target |
| `shadow` | Runs on an allowlisted, bounded sample | Candidate and metrics are audit-only; canonical artifacts and responses are unchanged | Gates 0-4, approved licenses, pinned snapshots, and an artifact manifest |
| `assist` | Produces bounded candidates for named reviewers | A reviewer may accept a candidate into a new review artifact, but it has no proof, policy, trust, license, or execution authority | Shadow benchmark thresholds pass and a human approves the arm, scope, and budget |
| `canary` | Runs for a manifest-bounded source/traffic cohort | A validated candidate may enter the formalization path; deterministic validation, configured verifier/prover, and required human review remain authoritative | All hard gates and paired thresholds pass; explicit release-owner and security approval |

There is no automatic transition and no implicit general-availability stage.
An `assist` acceptance or `canary` result is still an unverified candidate
until the normal compiler, schema/type, source-map, obligation, backend, and
review policies produce their own typed artifacts. Confidence, retrieval,
`EvidenceGateResult`, and `PolicyDecision` never become theorem authority.

### Gate 0: baseline frozen

- public Security API inventory exists;
- golden legacy corpus and identifier vectors pass;
- artifact inventory is read-only and complete enough to select authorities.

### Gate 1: shared core usable

- identity is dependency-independent;
- provenance, diagnostics, migrations, claims, and manifests pass unit tests;
- no domain or optional runtime imports leak into the core.

### Gate 2: Security shadow migration

- legacy and v1 declarations round trip for the golden corpus;
- verification no longer changes declaration identity;
- Xaman evidence gates cannot claim theorem authority;
- existing public imports still work.

### Gate 3: Intent pilot

- both pilot bundles ingest deterministically from a `SkillCenterSnapshot`
  pinned by dataset ID, full immutable revision, repository filename, byte
  size, and SHA-256 digest; mutable `main`/`latest` references fail closed;
- every record has a `SourcePolicyDecision`; unknown, contradictory, or
  unapproved license terms remain quarantined, and only the human-approved
  allowlist can enter training or publication;
- a reviewed pilot set has source-grounded Intent IR and GraphRAG artifacts;
- no source commands execute.

### Gate 4: formalization shadow mode

- deterministic views and proof obligations pass conformance tests;
- learned advisor runs only in shadow;
- examples are deduplicated and split as source groups using primary source,
  repository/document, content/near-duplicate family, generation family, and
  revision/time boundaries;
- the split, graph, and embedding snapshot identities are immutable, the
  retrieval partition fence passes, and leakage count is zero;
- all candidate formulas retain provenance and diagnostics.

### Gate 5: canary

- the complete `deterministic_only`, `intent_from_scratch`, and
  `legal_encoder_transfer` arm matrix runs over identical held-out examples;
- the selected learned arm improves at least one primary metric
  (`view_accuracy`, `modality_f1`, `control_f1`,
  `proof_obligation_closure`, `unsupported_recall`, or
  `round_trip_accuracy`) by at least `0.02` absolute versus
  `deterministic_only`;
- no primary metric regresses by more than `0.01` absolute, and
  each primary metric remains at least `0.95`;
- `grounding_accuracy`, `schema_validity`, `type_validity`, and
  `round_trip_accuracy` remain `1.0`, and `semantic_mutation_rate == 0.0`;
- `false_proof_count == 0`, `false_completion_count == 0`,
  `authority_violation_count == 0`, and `leakage_count == 0` in every arm and
  the aggregate receipt; none of these hard gates can be waived;
- artifact regeneration is deterministic;
- Security compatibility and Legal regression suites remain green;
- the selected backend declares the required logic family and `QueryKind` in
  `BackendCapabilities`, passes an explicit availability probe, and is on the
  human-approved proof-authority allowlist; discovery never installs a solver;
- p95 latency, peak memory, and estimated cost stay inside the
  human-approved canary budget;
- human reviewers sign off licenses, ontology/view versions, the split and
  benchmark receipt, high-risk formal semantics, canary scope, and rollback
  owner.

Canary promotion creates a content-addressed reviewed manifest. It binds the
repository tree, source snapshot, source-policy version, split/graph/embedding
snapshots, compiler/configuration, advisor checkpoint, backend capabilities
and versions, benchmark receipt, approvers, scope, expiry, and parent
artifacts. Run output remains under `runs/<run-id>/` until reviewed; only
manifested immutable artifacts move to `promoted/`. Temporary output, mutable
aliases, ambiguous `-new` files, stale receipts, and unmanifested evidence are
never promotion inputs.

Operators monitor stage and manifest identity, license/quarantine counts,
snapshot/cache integrity, split and retrieval-fence violations, candidate
rejection reasons, false-proof/false-completion and authority-violation
counts, backend availability/result status, proof-receipt validation, p95
latency, memory/cost, artifact digest drift, and Security compatibility
failures. Any hard-gate event or manifest mismatch immediately returns the
advisor to `off`, stops new canary admission, preserves the failed run for
incident review, and resumes deterministic-only service. Rollback does not
delete evidence or remove legacy Security shims.

## Supervisor operation

Run commands from the `ipfs_datasets_py` repository root.

First parse and project the durable goals without launching implementation:

```bash
ipfs-accelerate-agent-objective-daemon \
  --repo-root "$PWD" \
  --objective-path docs/architecture/ir_family_refactor_intent_ir.objectives.md \
  --todo-path data/agent_supervisor/ir_family/generated.todo.md \
  --discovery-dir data/agent_supervisor/ir_family/discovery \
  --bundle-dir data/agent_supervisor/ir_family/objective_bundles \
  --dataset-dir data/agent_supervisor/ir_family/objective_datasets \
  --graph-path data/agent_supervisor/ir_family/objective_graph.json \
  --todo-vector-index-path data/agent_supervisor/ir_family/objective_bundles/todo_vector_index.json \
  --plan-evaluation-path data/agent_supervisor/ir_family/plan_evaluations.json \
  --objective-goal-completion-todo-board \
    docs/architecture/ir_family_refactor_intent_ir.todo.md::IRF- \
  --task-prefix IRG- \
  --max-findings 32 \
  --surplus-findings-per-goal 1 \
  --no-reconcile-goal-completion
```

`IRG-` is intentionally different from the hand-authored board's `IRF-`
prefix. The objective projection produces coarse goal/refill bundles; the
reviewed board contains the 34 bounded implementation tasks. Initial
projection disables lifecycle reconciliation so it cannot rewrite the reviewed
heap. Enable reconciliation later only with reviewed completion-gate and
receipt inputs.

The recommended implementation path is the hand-reviewed board. Inspect it
without invoking an implementation model:

```bash
ipfs-accelerate-agent-implementation-supervisor \
  --once \
  --no-implement \
  --task-prefix "IRF-" \
  --todo-path docs/architecture/ir_family_refactor_intent_ir.todo.md \
  --state-dir data/agent_supervisor/ir_family/state \
  --worktree-root data/agent_supervisor/ir_family/worktrees
```

To run the reviewed board in four shards, invoke the following command in four
separate terminals with `SHARD` set to `0`, `1`, `2`, and `3`. Each shard needs
its own state and worktree roots; all four read the same locked task board.

```bash
SHARD=0
ipfs-accelerate-agent-implementation-supervisor \
  --implement \
  --task-prefix "IRF-" \
  --task-shard-count 4 \
  --task-shard-index "$SHARD" \
  --todo-path docs/architecture/ir_family_refactor_intent_ir.todo.md \
  --state-dir "data/agent_supervisor/ir_family/shards/$SHARD/state" \
  --worktree-root "data/agent_supervisor/ir_family/shards/$SHARD/worktrees"
```

Review the six initially ready tasks and resource capacity before launching.
The board uses exact files and dependency edges to keep those shards
conflict-safe. Do not run the coarse generated bundles at the same time as
the reviewed board.

If the generated objective bundles are preferred for high-level goal
implementation or later evidence-driven refill, plan their lanes first:

```bash
ipfs-accelerate-agent-bundle-supervisor \
  --bundle-index-path data/agent_supervisor/ir_family/objective_bundles/index.json \
  --repo-root "$PWD" \
  --state-root data/agent_supervisor/ir_family/bundles \
  --worktree-root data/agent_supervisor/ir_family/worktrees \
  --log-dir data/agent_supervisor/ir_family/logs \
  --task-prefix IRG- \
  --max-lanes 4 \
  --once \
  --no-implement
```

After inspecting bundle paths, dependencies, validation, and conflict
metadata, launch at most four lanes:

```bash
ipfs-accelerate-agent-bundle-supervisor \
  --bundle-index-path data/agent_supervisor/ir_family/objective_bundles/index.json \
  --repo-root "$PWD" \
  --state-root data/agent_supervisor/ir_family/bundles \
  --worktree-root data/agent_supervisor/ir_family/worktrees \
  --log-dir data/agent_supervisor/ir_family/logs \
  --task-prefix IRG- \
  --start \
  --implement \
  --max-lanes 4
```

Generated tasks and model output are proposals. A drained board does not prove
the objectives complete; the rollout gates require fresh validation evidence
bound to the current repository tree.

## Decisions to approve before the pilot expands

The scaffold and first engineering waves can proceed with conservative
defaults. The following decisions require recorded human approval; automation
may verify an approval artifact but may not create, infer, or waive one:

1. the per-license allowlist, exceptions, training use, and distribution
   policy;
2. every new source domain or bundle, immutable snapshot expansion, and the
   secret/PII quarantine and retention policy;
3. the v1 Intent ontology, formal view set, and high-risk semantic mappings;
4. the authoritative CID/multicodec profile;
5. solver/model provisioning or updates, the solver/backend/version allowlist,
   and which receipts may carry theorem proof authority;
6. gold-set reviewers, minimum size, sampling strategy, and corrections;
7. the source-group split manifest and any held-out-domain or time boundary;
8. the learned arm, paired benchmark receipt, promotion thresholds, and
   latency/memory/cost budget;
9. each transition to `assist` or `canary`, including cohort, duration,
   expiry, monitoring owner, and rollback owner;
10. promotion of an artifact used for release, training, publication, or
    high-risk formal semantics;
11. any incident disposition or policy exception (without waiving the zero
    false-proof, false-completion, leakage, or authority-violation gates);
12. the Security legacy-path removal release after its deprecation window.
