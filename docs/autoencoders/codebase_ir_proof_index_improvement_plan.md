# IR family inventories scaling and codebase proof planning

Maintain separate `codebase_ir`, `security_ir`, `legal_ir` and `intent_ir`
inventories, each with independent 8D, 384D and 768D model paths. That gives
12 independently managed cells, each with its own DuckDB databases, DuckLake
catalog/data location and Hugging Face model repository. Each cell contains
task-specific decoder and span profiles rather than one universal decoder.
Shared immutable assets and embeddings remain reusable through authenticated
references.

Build repository-specific Codebase IR from exact captured code and join it to
the other IRs through explicit typed bindings. The IPFS Accelerate symbolic
supervisor grounds desired Intent IR against observed code, applicable Legal
and Security declarations, and checked evidence. Autoencoders propose
representations and formalization candidates. Source correspondence checks and
formal backends determine which properties the planner may use.

The first milestone is a reproducible checkout and model inventory. Then build
a read-only repository and proof index, connect it to planning, and introduce
bounded online adaptation in shadow mode. Retain the independent 8D, 384D and
768D lanes, existing embeddings, decoder weights and historical proof artifacts.
This is an implementation plan; its proposed adapters and acceptance criteria
are not claims that a whole codebase has already been proved or trained.

The companion [work items](codebase_ir_proof_index_work_items.json) and
[inventory directory](ir_family_dimension_inventory_plan.json) record the
12 cells, proposed store/repository locations and implementation dependencies.
The work items record dependencies, owners and acceptance checks. The
[original inspection](../../../../artifacts/codebase-ir-proof-planning-20261002/inspection.json)
pins the codebase and supervisor implementations; the
[family and store inspection](../../../../artifacts/codebase-ir-family-scaling-plan-20261002/inspection.json)
adds the per-family assets and storage/package contracts. Both distinguish
released, local and proposed capabilities. The initial pilot uses declared Python source scopes in
`ipfs_datasets_py`, then its supervisor integration in `ipfs_accelerate_py`.
The same contracts can register other repositories under test explicitly.

The [repository pipeline plan](codebase_ir_repository_pipeline_improvement_plan.md)
specifies the operational handoffs, current-state and post-change intent
bindings, restart behavior and online training policies. Its
[declarative pipeline contract](codebase_ir_repository_pipeline_plan.json)
maps each stage to the work items below without creating runtime stores or jobs.

## Separate IR families dimensions tasks and budgets

An IR family identifies meaning and native schema. A model width identifies a
representation, not the number of fields or tokens in that IR. Keep
`ir_family_id` separate from `logic_family_id`: FOL, TDFOL, DCEC and other
formal logic projections can be produced for different native IR families.
The native IR document can grow independently of a vector's dimension.

| IR family | Native subject and decoder requirements | Progressive source scope to qualify |
| --- | --- | --- |
| [Codebase IR](../../ipfs_datasets_py/logic/software_contracts/codebase_ir.py) | Captured code, exact identifiers, types, expressions, calls, control/effect/dependency structure and contracts; a Codebase-native grammar/head | Expression or supported function, connected functions, module/dependency slice |
| [Security IR](../../ipfs_datasets_py/logic/security_ir/model.py) | Principals, assets, policies, transitions, assumptions and claims; security declaration and program-fragment heads remain distinct | One declaration or code body, complete policy/threat context, connected security slice |
| [Legal IR](../../ipfs_datasets_py/logic/legal_ir/canonical_contracts.py) | Modality, actor/action/object, conditions, exceptions and time; extended schemas and a prose inverse need separate heads | Rule/clause, connected definitions and exceptions, section/document |
| [Intent IR](../../ipfs_datasets_py/logic/intent_ir/schema.py) | Desired goals/procedures, preconditions, effects, guards, verification requirements and workflow edges; graph and instruction inverse heads | Action/clause, guarded action group, complete workflow/specification |

The full 4-by-3 inventory must retain actual evidence states:

| IR family | 8D existing evidence | 384D existing evidence | 768D existing evidence |
| --- | --- | --- | --- |
| Codebase | Trained 53-input/8-latent structural feature model; no learned formal decoder | Released narrow repository wrapper reuses a Security IR numerical payload; independent native Codebase head remains work | No authenticated trained family head in inspected migration |
| Security | Trained compiler-conditional 52-input/8-latent path/value model, plus a richer 289-input variant; not independent text-to-IR | GTE-conditioned GRU and fixed-tree scalar readouts; scope/quality varies by checkpoint | No authenticated trained family head in inspected migration |
| Legal | Historical explicit-8D reconstruction body and separate formula head; original encoder/context provenance incomplete | Source GRU, structured alternatives and published parser-assisted package; keep their tasks separate | Authentic inherited Legal initialization; native trained decoder unavailable in inspected migration |
| Intent | Trained compiler-conditional 12-input/8-latent path/value model; not independent text-to-IR | GTE-conditioned GRU and family-specific structured/rich targets | No authenticated trained family head in inspected migration |

These are scoped inventory findings. An inventory slot can exist while a
desired decoder remains unavailable. The actual 8D checkpoints use different
dimension roles: an eight-dimensional input, an eight-dimensional internal
latent, and a token embedding of width eight are not interchangeable. Record
source input width, latent width, decoder hidden width and token embedding
width separately. The existing Codebase source384 bridge must retain both
owning family `codebase_ir` and numerical payload family `security_ir`, its
bridge implementation and source correspondence. It does not become a general
native Codebase decoder by changing a label.

Within every cell, distinguish source-to-native-IR, structural reconstruction,
native-IR-to-logic, native-IR-to-source-text/code, and retained-source byte
restoration. Each task has a codec, decoder, source-access policy and separate
qualification. The current Legal canonical inverse is model-free; the existing
Intent learned inverse has a narrow single-clause English scope. Neither
qualifies an unrestricted inverse for another family.

| Budget | What the plan records |
| --- | --- |
| Representation | Dimension and role; producer/projection identity; input and latent widths |
| Encoder input | Pinned tokenizer, special tokens, context overhead, actual token count and hard limit |
| Decoder output | Task-specific grammar, vocabulary, lexical-token or typed-node/slot limits, termination and overflow |
| Semantic span | Exact source units, offsets, surrounding dependencies, unresolved references and completeness |
| Runtime resources | Admission leases, rows/steps/time/memory/native-check budgets and cancellation |

GTE-small supplies a 384D/512-input-token profile; the native multilingual
profile supplies 768D/up-to-8192 input tokens. Existing structural or historical
8D paths do not acquire a GTE token budget merely from their width. Freeze
small-source 8D budgets from the actual producer and measured corpus before
fitting. For comparable source-embedding tasks, plan progressively larger
admitted budgets within each family; measure that progression separately from
the encoder's maximum capacity. Numerical 8D source-token limits remain
explicitly undecided where provenance is missing.

Output limits also differ today: the retained Legal 8D formula head and
published parser-assisted Legal 384D package use a 64-token generation limit;
published Security/Intent 384D GRUs use 512. Fixed-tree ridge readouts are bounded
by schema/slots/classes rather than a token loop. Do not use any of those
limits as a global decoder setting. A longer encoder input cannot enlarge an
unchanged decoder grammar or guarantee complete autoformalization.

## Independent inventories databases and model repositories

Use one configuration entry and declarative inventory per family/dimension.
The [inventory directory](ir_family_dimension_inventory_plan.json) links all
12 manifests. Those manifests describe proposed paths and existing read-only
assets; creating them does not create runtime databases or remote repositories.
Resolve `ir_store_root` and the configured Hugging Face namespace when the
store/publication adapter is implemented, and validate the resulting identities.

| Cell | Proposed storage suffix | Proposed Hugging Face model repository suffix |
| --- | --- | --- |
| codebase_ir 8D | `codebase_ir/8d/` | `codebase-ir-autoencoder-8d` |
| codebase_ir 384D | `codebase_ir/384d/` | `codebase-ir-autoencoder-384d` |
| codebase_ir 768D | `codebase_ir/768d/` | `codebase-ir-autoencoder-768d` |
| security_ir 8D | `security_ir/8d/` | `security-ir-autoencoder-8d` |
| security_ir 384D | `security_ir/384d/` | `security-ir-autoencoder-384d` |
| security_ir 768D | `security_ir/768d/` | `security-ir-autoencoder-768d` |
| legal_ir 8D | `legal_ir/8d/` | `legal-ir-autoencoder-8d` |
| legal_ir 384D | `legal_ir/384d/` | `legal-ir-autoencoder-384d` |
| legal_ir 768D | `legal_ir/768d/` | `legal-ir-autoencoder-768d` |
| intent_ir 8D | `intent_ir/8d/` | `intent-ir-autoencoder-8d` |
| intent_ir 384D | `intent_ir/384d/` | `intent-ir-autoencoder-384d` |
| intent_ir 768D | `intent_ir/768d/` | `intent-ir-autoencoder-768d` |

Each cell owns a stable store ID and the following proposed layout:

```text
<ir_store_root>/<ir_family>/<dimension>d/
    inventory.json
    registry.duckdb
    index.duckdb
    lake/catalog.duckdb
    lake/data/
    artifacts/
    runs/<task>/<profile>/<run_id>/
```

Reuse owner implementations with separate instances and configuration.
`registry.duckdb` belongs to AutoencoderRegistry, which rejects foreign tables.
`index.duckdb` belongs to a reviewed common index/connection owner for source
bindings, vectors, native IR, candidates, obligations and proof indexes.
Catalog/evidence wrappers must share that owner's connection/lock instead of
starting independent writers against one file. DuckLake has a separate metadata
catalog and data prefix per cell; its official
[connection contract](https://ducklake.select/docs/stable/duckdb/usage/connecting)
binds those locations explicitly. Existing isolated history implementations are
building blocks, not evidence that these production stores already exist.

Maintain per-cell model heads, writer leases, outboxes/delivery journals,
migrations, backups, retention, compaction and rollback. A lightweight directory
indexes locations and published receipts; it does not become another owner of
all model or proof state. Capture repository bytes once through their canonical
owner; cell indexes reference the admitted source/semantic roots. Keep native
IR identity independent of whichever dimensional model proposed it.

An inventory must enumerate encoders/tokenizers/code assets, source/span
corpora, raw vectors and receipts, native targets, decoder/task profiles,
checkpoint lineage and optimizer/refit state, split/replay cohorts, logic
projections, proof attempts/applicability, metrics and publication records.
Track discovered, authenticated, compatible, trained, evaluated, qualified,
promoted and published as separate stages. Every unavailable or rejected item
retains its reason and requested family/task/profile.

RepositoryCodebaseIndex owns repository-code capture. Legal source/corpus,
Intent instruction/SkillCenter spans, and Security declaration/CVE body and
description corpora retain their separate versioned source owners. A cell may
reference both a family source root and repository roots used for grounding;
neither replaces the other.

Keep the current isolated DuckLake history subnamespace, or add a reviewed path
adapter before using the proposed `lake/catalog.duckdb` layout. Its current
constructor uses `history.ducklake`, a 256 MiB bound and `production=False`.
Bulk vector/proof schemas and production activation require explicit owner
work. Backup/restore must issue a nonrepeating owner incarnation so restored
sequence values cannot revive old leases, permits or currentness receipts.

Share immutable CAS/asset objects only through exact authenticated references.
The prior 2640-row vector inventory has 660 rows each for Legal, Intent,
Security and UIUX; it contains no Codebase source rows. Preserve those old
generations and reuse matching vectors unchanged. New Codebase source needs
matching existing vectors or new production for missing inputs; unrelated legal
vectors cannot become code vectors through relabeling. Identical raw vectors
may be shared across family inventories when the complete input/encoder profile
matches, while targets, decoder predictions, splits and qualification remain
family/task-specific.

Hugging Face model IDs are configured as
`<hf_namespace>/<ir-family>-autoencoder-<dimension>d`, with one repository per
cell. The official [repository contract](https://huggingface.co/docs/huggingface_hub/en/guides/repository)
uses a namespace/name identity. Inventory existing repositories first, preserve
their pinned releases, and map or add the dedicated cell repositories without
renaming or deleting old assets. Shared upstream GTE repositories remain encoder
dependencies; these 12 repositories distribute our family-specific models.
Optional corpus dataset repositories are a separately configured extension.

Publish task/profile releases with actual checkpoint bytes, codecs, schemas,
producer closure, asset references, lineage/replay manifests, measured scope,
budgets and model cards. Retain a manifest digest and full Hub commit in every
load/publication receipt; [pinned downloads](https://huggingface.co/docs/huggingface_hub/en/guides/download)
support immutable commit revisions. Resolve human-facing branch/tag names to a
commit before admission. Local promotion and remote publication remain separate.
The current `checkpoint_hub.py` package/loader is strictly 384D and excludes
Codebase. Add explicit versioned 8D/768D/Codebase package and loader adapters;
preserve its existing guards and do not make a renamed 384D manifest pass.

Adopt existing checkpoints/vectors into new inventory records by digest and
read-only location, then verify clean acquisition. No reencoding, retraining or
physical relocation is needed to prepare the inventories. Only a qualified
replacement may advance the corresponding task/profile head; a different
cell's quality or publication cannot supply that qualification.

## Correct the reconstruction and checkout baseline

The earlier 0/60 result compares generated canonical Legal IR with reference
Legal IR. Its decoder receives a cached 384D embedding and emits typed JSON;
its training losses are IR token loss and embedding reconstruction. It does
not evaluate legal text reconstruction from IR. The actual existing donor
weights were loaded and hash-checked, so this local score was not caused by
silently initializing replacement weights.

For example, the saved model turns “The registrar must preserve the notice.”
into permission to publish an archive. The existing source-withheld canonical
decompiler renders that error as “Registrar may publish archive.” Given the
correct IR, the same decompiler produces “Registrar must preserve notice.”
and recompilation recovers the same IR. The second result preserves the
declared rule but does not recover every original word. The canonical semantic
IR omits articles and original surface form.

Report four different outcomes throughout this project: generated IR accuracy,
critical semantic-field accuracy, source-withheld text or code round-trip
fidelity, and original-byte fidelity. A retained source/CST sidecar may support
lossless restoration, but it must be labeled separately from learned
reconstruction. A matching recompiled IR alone can preserve an incorrect
generated meaning, so compare with independently established source targets
as well. Arbitrary original wording cannot be recovered uniquely from an IR
that discards it. Add a separately specified surface channel if that wording
must survive the round trip, and report what information it retains. A learned
prose inverse needs its own objective and checkpoint; evaluate it with the
original text withheld and surface-channel ablations. Keep direct source/CST
restoration as a separately labeled baseline.
The [existing canonical round trip](../../ipfs_datasets_py/logic/legal_ir/canonical_roundtrip.py)
provides an immediate deterministic baseline.

Do not treat 0/60 as a score for every 384D model. The migration chose a
compatible raw-CE GRU; structured V2/V3 heads, newer formula pilots and the
published Legal package use different architectures and source access.
Compare those assets under their proper tasks and cohorts before choosing
teachers. The compatible `semantic-1729` GRU has an archived 2/60 exact-IR
result on the same cached validation vectors; it is a comparison candidate,
not a qualified teacher. Incompatible scalar classifiers cannot replace a GRU
through its tensor-copy contract. Keep old generations immutable while
registering new selections.

The Git audit also explains why current searches miss existing work. The
active datasets checkout is `d5238def256d1c352793ee7d977e6b17b6d8cbee`.
A fresh fetch observed `origin/main` at
`b86bf9ebeea81b1976696f0f031949a936431a3b`, 37 commits ahead, including
repository source capture, semantic manifests and source-bound 384D
adaptation. During review the remote ref advanced once more to
`ea275ae32779db01c7dc59dc62ce12bcd9841ae2`, now 38 commits ahead, adding
declared UI temporal/cognitive projections without changing those Codebase
modules. The inspection pins both observations. Older decoder/formula release
commits were already merged.
The scoped audit found 107 local GTE additions absent from both pinned remote
tips, including learned-head reuse and saved-generation evaluation. The
inspection records the exact paths and reproducible scope checks.
Checkpoint and vector files under local artifacts are not supplied by a
Git checkout alone. Remote refs may advance after this inspection.

Prepare an isolated integration branch from freshly fetched datasets
`origin/main`; include missing GTE work, reviewed local Codebase training and
proof-cache dependencies, scoped dependent edits and new plan artifacts.
Do not bulk-stage the dirty checkout or merge every
rescue branch. Register actual weights, caches and receipts through immutable
artifact manifests; verify acquisition and explicit runtime selection from
a clean checkout. Integrate the supervisor adapters in their owning repository,
then update the parent repository's submodule pointers from its current main.
Code integration, artifact publication and runtime model promotion are three
separate steps with separate validation.

## Existing components and actual boundaries

| Component to reuse | Existing capability | Boundary to retain |
| --- | --- | --- |
| [RepositoryCodebaseIndex](../../ipfs_datasets_py/logic/software_contracts/codebase_ir.py) and [CodebaseCatalog](../../ipfs_datasets_py/duckdb_control/codebase_catalog.py) | Capture exact source, seal Codebase IR artifacts, publish fenced heads, observe current source | Structural capture is not behavioral proof |
| [DuckDBASTStore](../../ipfs_datasets_py/logic/software_contracts/duckdb_ast_store.py) and [ingestor](../../ipfs_datasets_py/logic/software_contracts/duckdb_ingest.py) | Source files, AST nodes, symbols, references, calls, effects, interfaces and diagnostics | Preserve partial, opaque, failed and unindexed coverage |
| [Semantic index](../../ipfs_datasets_py/logic/software_contracts/semantic_index/index.py) and [semantic state](../../ipfs_datasets_py/logic/software_contracts/semantic_state/api.py) | Stable/versioned symbols, dependency deltas, immutable roots and test/proof selection | Stable symbol identity is different from body/version identity |
| [Released scan policy](https://github.com/endomorphosis/ipfs_datasets_py/blob/b86bf9ebeea81b1976696f0f031949a936431a3b/ipfs_datasets_py/logic/software_contracts/codebase_scan_policy.py) | Declared committed-Git scope, exclusion and completeness accounting | Maximum 256 entries and 64 KiB per source; nested repositories remain boundaries |
| [Released semantic manifest](https://github.com/endomorphosis/ipfs_datasets_py/blob/b86bf9ebeea81b1976696f0f031949a936431a3b/ipfs_datasets_py/logic/software_contracts/codebase_semantic_manifest.py) | Native Program IR, declared integer contracts, effects and verification-condition artifacts | Checked-property count is zero; global dependency graph is not closed |
| [Local source-bound 8D feature training](../../ipfs_datasets_py/logic/software_contracts/codebase_source_training.py) | Private candidates, exact Adam continuation, fixed basis, original root replay and ancestry ledger | Not on inspected origin; feature reconstruction is not a learned formal decoder |
| [Released source384 coordinator](https://github.com/endomorphosis/ipfs_datasets_py/blob/b86bf9ebeea81b1976696f0f031949a936431a3b/ipfs_datasets_py/logic/software_contracts/codebase_source_384.py) | Pinned GTE-small source embeddings and inherited structured Security IR decoder | Narrow scalar-function cohort, frozen projection/vocabulary, ridge head refit; no automatic promotion |
| [Local verification catalog](../../ipfs_datasets_py/duckdb_control/codebase_verification_catalog.py) and [evidence index](../../ipfs_datasets_py/duckdb_control/codebase_evidence_index.py) | Durable conditional evidence refs and exact-key/reverse-dependency lookup | Not on inspected origin; historical receipts are not automatically current proof authority |
| [Canonical proof key](../../ipfs_datasets_py/logic/common/canonical_cache_key.py) | Full semantic and checker/environment identity | Preserve authority ceilings and cross-environment rejection |
| [AutoencoderRegistry](../../ipfs_datasets_py/duckdb_control/autoencoder_registry.py) | Immutable versions, lineage, fenced runs, explicit promotion and outboxes | Registry presence does not establish quality or current source applicability |
| [DuckLake history](../../ipfs_datasets_py/ducklake/autoencoder_history.py) and [delivery](../../ipfs_datasets_py/duckdb_control/autoencoder_ducklake.py) | Native isolated history sink and durable reconciliation journals | Current history events do not transfer model weights or activate a production lake |
| [Supervisor symbolic planner](../../../ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/planning/symbolic_candidate_planner.py) | Bounded backward chaining, hard constraints and candidate ranking | Model nominations cannot become observed facts |
| [DecisionRuntime](../../../ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/context/decision_runtime.py) and [VerificationExecutor](../../../ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/verification/executor.py) | Effect admission, dependency reconciliation and actual check execution | Current tree, scope, environment and evidence must be supplied by observed owners |

The active checkout's `codebase_source_training.py`, `codebase_ir_targets.py`,
`codebase_property_cache.py`, `codebase_verification.py`, verification catalog
and evidence index are local implementations absent from both inspected remote
tips. Inventory and review them explicitly in C00 before reuse. Additional
local layers, `codebase_training_corpus.py`, `codebase_model_generation.py` and
`codebase_scan_policy_live.py`, exist in the release worktree but were also
absent from those tips. Review their clone grouping, finite property receipts,
model-generation reuse and live scope checks before integrating them.

The supervisor audit first inspected the nested
`external/ipfs_datasets/ipfs_accelerate_py` checkout at
`9b5c4e01b4aded11f92089ca216456bd39f7b6ba`, then confirmed the named gaps
in sibling `external/ipfs_accelerate` at
`18e0f79e56def8ba426cafdfad568fe6bf7440b7`. Table links select the sibling
owner. Its planner, compiler and proof-scope index files are modified relative
to HEAD; the inspection pins their actual bytes. Preserve the scope index's
canonical dependency-key invalidation fix during reconciliation.
Its observed `origin/main` is
`5f15211cf581786c1d010d8251df9ffc163c1e83`. Recheck the chosen fresh release
during C00. These checkouts have different lineages; do not interchange planner
files or submodule pointers.

One storage gap is material: the inspected
[DuckDBProofStore](../../ipfs_datasets_py/logic/common/duckdb_proof_store.py)
installs SQL schema when supplied a connection, but its current lookup and put
operate on an in-process dictionary. Implement durable SQL write/read and
restart recovery, or route proof persistence through an already durable owner,
before calling this store a persistent proof cache.

## Architecture and evidence flow

~~~mermaid
flowchart TD
    R[Repository snapshot and environment] --> A[Captured bytes AST and semantic graph]
    A --> I[Native Codebase IR and source correspondence]
    A --> E[Family dimension and task specific representations]
    D[Legal security and intent source declarations] --> E
    E --> M[Family specific adapters and decoders]
    M --> N[Separate native IR candidates and validation]
    I --> J[Typed cross IR and source bindings]
    N --> J
    J --> F[Typed logic projections and obligations]
    F --> V[Trusted checks and scoped outcomes]
    V --> P[Proof artifacts and DuckDB evidence index]
    A --> P
    U[Intent IR desired behavior] --> G[Ground symbols and current facts]
    P --> G
    G --> S[Symbolic supervisor formal work plan]
    S --> W[Isolated workers and measured patches]
    W --> R
    I --> T[Admitted training rows and replay]
    V --> T
    T --> M
    P --> L[Independent cell DuckLake snapshots and history]
~~~

The deterministic path remains usable when a model, embedding or prover is
unavailable. Unknown outcomes remain queryable and produce planning work to
obtain evidence. A trained candidate can reduce search or recommend an
obligation; it does not bypass source validation or checking.

## Repository identity and incremental capture

Register each repository under test with a stable repository ID, exact Git
commit/tree, declared dirty/untracked overlay policy, nested repository roots,
language/frontend versions, dependency locks, build configuration and scan
policy. A branch name, path or timestamp is not sufficient identity. A source
root and a DuckLake snapshot are different identities and both must be recorded.

For the pilot, use an explicitly enforced clean-source gate over the released
Git capture policy. That policy admits both `git-clean` and `git-working`
captures; its committed-Git-root name alone does not exclude dirty overlays.
An overlay deployment must register the exact HEAD/index/working/untracked
capture semantics and bridge the supervisor's forest snapshots explicitly.
Training/proof path selections do not filter the capture inventory: bound all
nonexcluded entries. Preserve symlink/nested-root boundaries and capture
failures. Do not import repository modules merely to scan their ASTs.

Capture exact file bytes into the existing immutable CAS. Build deterministic
AST/native views, source maps, signatures, imports, calls, interfaces, control
flow, effects, tests and declarations. Resolve what the supported frontend can
resolve; retain dynamic dispatch and external effects as unknown dependencies.
Join AST symbol IDs to semantic stable IDs and version CIDs using source CID,
path, qualified name and spans. They are not interchangeable identifiers.

The pilot must declare a bounded subtree and report every in-scope entry. Before
whole-repository rollout, add deterministic paging/shards and a sealed aggregate
manifest: all pages, source counts, exclusions, failures, duplicate ownership
and completeness must reconcile. Raising a memory limit alone cannot remove
the current 256-entry capture contract. An omitted or unsupported file cannot
contribute to a successful whole-codebase coverage claim.

A byte-changed file produces a new source/entry version. A semantic symbol
version changes when its normalized semantic projection changes; a comment or
whitespace edit can preserve that version. Record explicit source and semantic
deltas. Use existing reverse edges for imports, calls, contracts, test fixtures,
proof dependencies and environment bindings. An incomplete dependency graph
requires conservative broader invalidation, not assumed locality.

## Codebase IR and logic family projections

Use the existing native Codebase IR/Program IR owners as canonical targets.
Their repository-specific content is the symbol inventory, source bindings,
contracts, data/control flow and effects. An 8D or 384D vector is a learned
representation of units in that IR, not the complete IR or a proof document.

Start with the supported integer/Boolean Python fragment and explicit declared
contracts. Then extend semantics deliberately: branches and loops, data
structures, exceptions, aliasing, I/O, async behavior and cross-module effects.
Each addition needs a source adapter, typed semantics, counterexamples and
coverage tests. Unknown runtime types, reflection or dependencies remain
unsupported until their interpretation is supplied.

| Projection | Intended properties | Required interpretation |
| --- | --- | --- |
| FOL/TDFOL or SMT | Types, preconditions, arithmetic/data invariants and postconditions | Sorts, bounds, assumptions and source-to-formula correspondence |
| Temporal logic or TLA | Order, state transitions, concurrency, safety and progress | State machine, trace completeness, scheduler and fairness assumptions |
| Deontic/policy views | Permitted tool actions and required authorization | Explicit policy; obligations do not assert an action occurred |
| CEC/DCEC or other supported families | Richer event, belief or policy reasoning | Family-specific typed adapters and declared supported semantics |
| Lean or another checked proof backend | Independently checked claims within admitted encodings | Exact translation, theory/toolchain and proof/checker artifacts |

Compile different family views from the same admitted native subject. Retain
node/path mappings, assumptions and unsupported facets. Do not infer equal
expressiveness or merge incompatible timestep logits, schemas or authorities.
The newer [released UI modal projections](https://github.com/endomorphosis/ipfs_datasets_py/blob/ea275ae32779db01c7dc59dc62ce12bcd9841ae2/docs/autoencoders/ui_modal_projection_coverage.md)
already provide typed authored temporal/TDFOL/DCEC interpretations and native
validation adapters. Reuse their semantics where applicable instead of
recreating them. They do not assert that declared norms or beliefs hold and
do not expand the learned decoder's grammar. Their complete compound targets
currently exceed its 64-token output budget; lossless target representation and
held-out learned reconstruction are still required before a training gate opens.

Tests, finite model checks, conditional SMT evidence and kernel-checked proofs
remain distinct outcomes. A theorem about a translated model also needs source
correspondence before it supports a claim about runtime code.

## DuckDB DuckLake and proof index design

Reuse existing catalog/registry owner implementations through isolated cell
instances, retaining the canonical source-capture owner and proof-key definition.
Add family-specific index schemas under reviewed owner migrations. The following
are proposed logical records/views; final ownership belongs to those owners.

| Record or view | Minimum binding | Main use |
| --- | --- | --- |
| Repository head | Repository ID, generation, source snapshot, semantic root, environment and publication receipt | Currentness fence |
| Unit and symbol version | Source CID/span, AST/native IR CID, stable and versioned symbol IDs, frontend | Exact source retrieval |
| Embedding receipt | Input/chunk CID, encoder/assets, dimension and role, tokenizer/context/span policy, input budget, pooling, normalization, dtype, vector CID | Reuse exact existing vectors |
| Candidate IR | Cell/family/task, unit/source root, vector receipt, decoder/checkpoint/schema/codec, output budget, generation policy and validation | Model-output provenance |
| Obligation | Subject/native IR, family profile, property, assumptions, bounds, translator and dependency closure | Formal check request |
| Proof attempt/outcome | Canonical key, current source binding, checker/environment, artifact/log refs, outcome, scope and authority | Auditable checked evidence |
| Dependency edge | Typed source/symbol/contract/policy/toolchain/obligation/proof/test dependency and resolution status | Invalidation and affected checks |
| Intent binding | Intent IR, desired property/effect, resolved symbols, current repository root, applicability and unresolved requirements | Grounded planning |
| Plan and action evidence | Plan/step IDs, observed roots, preconditions, required receipts, measured diff and post-state | Admission and completion |
| Training/checkpoint event | Cell/family/task, corpus/replay/split roots, actual parents/transfer receipts, profile/budgets, optimizer/refit method, metrics and promotion | Independent adaptation lineage |

A proof key must retain the existing fields: source, expression, formalization,
slice, obligation, assumptions, bounds, translation, provider, environment,
policy, schema, checker, network policy, evidence kind and authority ceiling.
Bind tool binaries/theories and dependencies through those identities.
Checkpoint identity belongs to candidate-generation lineage and to the proof
premises when a model contributes an assumption; do not make an unchanged
checked theorem depend on an unrelated model version unnecessarily.

Index at least `candidate`, `conditional_model_checked`, `kernel_checked`,
`refuted`, `unknown`, `timeout`, `unsupported`, `failed` and `stale` as distinct
conceptual states. Map them to each existing owner's actual enums through
reviewed adapters. A successful solver return cannot set an unsupported
kernel flag. A historical loader authenticates bytes and bindings but does not
authenticate a past solver process. Admit current evidence from trusted check
execution or independently verify a portable certificate.

Use each cell's file-backed DuckDB owners for head transitions, leases,
exact lookup, reverse dependencies and promotion/outbox state. Keep immutable
payloads in CAS with indexed CIDs. DuckLake adds bulk source/IR/vector/proof
history and analytical scans under an explicit schema/snapshot. Its
[transaction contract](https://ducklake.select/docs/stable/duckdb/advanced_features/transactions)
provides snapshot isolation; this does not make an external CAS write and a
control-plane transition one atomic transaction.

Preserve the registry's existing local-owner flow: authenticate durable CAS
artifacts; commit owned DuckDB state/head and its outbox event together; then
reconcile DuckLake history through the delivery owner. The source catalog and
conditional proof owners do not currently have this history outbox; add their
reviewed transactional delivery adapters/migrations in C05. A pending optional
history sink does not block a valid local head. Record pending delivery
explicitly.

For a future published aggregate that references a lake snapshot, authenticate
CAS payloads and commit the lake batch first; validate its snapshot/manifest;
then compare-and-swap the aggregate head with an idempotent publication
operation. That head cannot reference an incomplete lake batch. Readers must
never observe a completed head with missing referenced artifacts. Test crashes
at each boundary in both flows; reconcile orphaned batches and pending outbox
events without replaying model training or solver work.

Use a serialized owner per database file for DuckDB writes. Do not send multiple
processes independent write connections to one native database file. If later
DuckLake workers need a shared metadata service, choose and validate its
supported catalog backend. The official
[catalog guidance](https://ducklake.select/docs/stable/duckdb/usage/choosing_a_catalog_database)
distinguishes single-client DuckDB, local multi-client SQLite and remote
multi-user PostgreSQL. Pin and test the actual deployed versions and ownership
policy; do not assume an extension removes the existing owner's limits.

## Typed joins and federation across the twelve stores

An Intent requirement, a Legal rule, a Security declaration and observed code
retain separate identities. A typed join binds source/target family, native
artifact/node IDs, exact source spans/subjects, relation, bridge implementation,
scope, assumptions and evidence. Codebase-to-Security joins can reuse
[CodeLogicEvidence](../../ipfs_datasets_py/logic/security_ir/code_logic_projection.py),
which checks code-unit/body bindings; it does not establish all runtime
correspondence. A Legal rule becomes an obligation only after an applicability
binding. An Intent goal remains desired behavior until current implementation
evidence satisfies the required checks.

Reuse existing DuckLake endpoint/snapshot contracts where applicable, but add a
reviewed planner federation adapter. Select only required cells. The proposed
federation manifest records store IDs, IR family and dimension, dimension role,
task/profile, both endpoint family-source roots and repository/semantic roots,
applicability revisions, owner epochs and role-specific head
generations, model/checkpoint/codec versions, lake snapshots, exact subjects,
typed joins, proof/applicability refs and unresolved requirements.

Read immutable receipts from each required owner, validate the joins, then
reobserve relevant monotonic generations before publishing the manifest through
a coordinator compare-and-swap. Reobserve the exact typed root bindings again
before effects. An arbitrary matching CID, missing root or root from another
store/family/role cannot satisfy currentness. Harden the inspected
`DecisionRuntime._replacement_is_current` boundary, which can accept an absent
binding and compare against the set of current roots, alongside its existing
effect-time checks.

DuckDB [attached-database transactions](https://duckdb.org/docs/current/sql/statements/attach)
are atomic within a database, not across the attached stores. The manifest and
outbox protocol do not atomically commit all 12 cells, CAS, lakes and Hub
repositories. Keep publication states partial until their required receipts
exist; reconcile retries rather than rerunning training or fabricating rollback
of external history. Local model promotion can proceed without optional Hub
delivery, and a published aggregate cannot reference missing required artifacts.

Separate source-applicability, serving-model and history-delivery heads. An
unrelated appended metric or optional cell update need not invalidate a plan.
Changes to a law, instruction, security declaration or corpus version invalidate
their applicable joins even when repository code is unchanged.
Cross-store dependency edges use qualified store/artifact identities and
idempotent origin-owner/sequence events. Source/policy/contract changes invalidate
the corresponding joins and permits. Effect-time validation remains required
when asynchronous delivery lags. Copies of one certificate across dimension
stores remain one item of proof evidence; three model predictions do not create
three independent proofs.

## Cache reuse and change invalidation

Maintain three independent caches: exact source/AST/native artifacts; embeddings
and learned predictions; checked proof/test evidence. Similarity retrieval may
suggest a relevant theorem or model example but cannot supply an exact proof hit.

The local property/evidence caches bind the complete source snapshot and the
supervisor's verification receipts bind exact trees. Start with those strict
contracts. Unchanged parsed shards and byte/profile-identical embeddings can
be reused while old proof artifacts remain historical. A new tree still needs
current application/admission evidence.

Later, introduce a separately reviewed dependency-slice reuse profile. It must
verify identical subject, assumptions, transitive dependency closure, compiler,
policy, environment and checker; bind an explicit old-to-current applicability
record; and reobserve current roots. Preserve the original proof key and
certificate. Never obtain a faster hit by dropping snapshot/key dimensions or
relabeling old receipts. Unknown import/call effects force broader checks.

Test invalidation for body edits, rename/relocation, deletion, signature or
decorator changes, global constants, imports, lockfile changes, compiler/theory
updates, policy changes and nested repository updates. Include source ABA,
concurrent edits and restart/retry scenarios. Maintain negative outcomes with
the same freshness discipline as positive outcomes.

## Ground Intent IR and admit symbolic plans

Intent IR records desired behavior and constraints; the index records observed
code and admitted evidence. Resolve each intent against current symbol versions,
API contracts, effects and tests. Record ambiguous names or missing symbols
instead of allowing embedding similarity to choose a behavioral interpretation.
The grounding artifact binds the intent version, repository/semantic roots,
target symbols, required effects, policy and unresolved proof obligations.

Build context packs through datasets semantic-state and proof-context owners,
then registered supervisor converters. The existing upstream `RepositoryState`,
`InvalidationPlan`, `SemanticCapsule` and `DatasetsContextPack` types already
exist. Parts of the supervisor adapter still describe them as absent; update
that registration rather than introducing duplicate canonical classes.

Map measured source observations and admitted proof/test receipts to current
`ObservedFact` records. A desired postcondition is a goal, not an already true
fact. Each proof-backed fact needs its subject, root, assumptions, environment,
checker and authority. The planner should query an eligibility view that
excludes stale, unbound, unsupported and insufficient-authority records.

Use the existing IntentConstraintAdapter, obligation graph, bounded symbolic
candidate planner, FormalPlanCompiler/Validator, ProofScopeIndex and
DecisionRuntime. Models may rank candidates, retrieve procedures and propose
subgoals. A hard precondition failure cannot be overridden by their confidence.
The inspected obligation compiler marks unknown facts as REVIEW, and the
symbolic planner rejects review-required graphs. Use a separately admitted
observation/context-resolution request to obtain missing evidence and recompile;
the current compiler does not automatically turn every unknown into a task.

Keep observed current-state facts distinct from desired post-change goals. The
inspected compiler treats an exact false current predicate as CONTRADICTED and
stops producer expansion. A reviewed transition adapter must preserve that fact
and bind a different planned-post subject, producer preconditions/effects and
actual observed post-state before closing a repair goal. Changing a predicate ID
alone does not separate semantic keys. Intent conformance completion IDs must be
derived by the evidence owner from eligible receipts, rather than supplied as
implementation proof by a worker or model.

The inspected adapters need specific hardening before enforced execution:

1. Required IR hook failures currently pass through broad exception handlers
   in planner/compiler/validator paths. Required integrations must reject or
   return unavailable on failure.
2. Some obligation facts accept an empty root or a status string as proof
   evidence. Require actual admitted current receipts before constructing them.
3. Implementation/scope success can be supplied as Booleans, and a world-model
   helper accepts descriptive `current`/`verified` fields. Replace those
   production boundaries with measured diff and exact evidence bundles.
4. Effect-time current values can default to the permit's earlier values.
   Supply fresh observed tree/semantic roots, lease and scope immediately before
   dispatch and observe actual effects/post-roots afterward.

These are gaps in inspected component boundaries, not evidence that every live
entrypoint lacks additional surrounding checks. Add focused regressions to the
existing supervisor suites before selecting an enforced production route.

## Repository training on the fly

Use a frozen shared parent plus a private repository adaptation lineage.
Register a stable continuation variant by repository ID, model task,
IR family/cell, dimension role, representation/basis profile, target codec and
admitted input/output/span budgets. Bind evolving corpus/source
snapshot roots to immutable model versions and runs. If an initial frozen
corpus root identifies a lineage, preserve it across compatible source-successor
continuation; a changed source head alone must not create an unrelated variant.
Training is scheduled, budgeted work with a
single writer; it never mutates the model serving an active planner request.

An inherited run requires a compatible authenticated parent. The existing 8D
trainer can initialize a fresh root when no parent is supplied; the reuse adapter
must make that path unavailable in inherited mode. Its continuation also fixes
cohort paths/contracts/roles and tune/canary data. Expansion needs a reviewed
cohort/basis migration; account for unknown atoms before numerical projection.
Single-writer Adam continuation and federated aggregation remain different
update policies: the current federated path fits current inherited training
paths, uses original replay diagnostically and resets aggregate Adam moments
and progress. Require a separate retention gate and provenance adapter for it.

The registry requires continuation parents to belong to the same variant.
Across cells, widths, families or incompatible task contracts, record an
explicit transfer/distillation edge to immutable donor store/version/checkpoint
receipts and initialize a new variant. Do not pass a foreign variant as a native
resume parent. Preserve authentic learned components that match the new codec
and dimensions through the existing transfer checks.

The existing Codebase prototypes below are subvariants of their respective
cells; the other three families retain their own decoders and inventories.

| Codebase cell | Reuse first | Online work |
| --- | --- | --- |
| 8D | Existing source-bound feature model, basis, compatible saved Adam state, original root replay and ancestry ledger | Bounded structural adaptation; explicit basis migration for new atoms |
| 384D | Existing GTE-small assets/caches and released structured source384 parent/projection/vocabulary | Repository readout/adapter fitting under the actual compatible trainer |
| 768D | Select compatible donors/bridges and build an authenticated Codebase initialization; the existing Legal 768D initialization is only a separately scoped potential donor | New native Codebase codec/head and source/context profile after alignment and fidelity gates; preserve compatible donor bodies initially |

Alibaba's target is **768 dimensions and up to 8192 input tokens**, as recorded
by its [model card](https://huggingface.co/Alibaba-NLP/gte-multilingual-base).
That input budget does not enlarge the decoder vocabulary/output budget or
guarantee that a complete repository can fit in one embedding.

The released source384 trainer currently recomputes GTE embeddings through its
worker. Add a persisted authenticated vector-cache adapter before using it for
the requested reuse workflow: exact source payload/span, context assembly,
encoder/code assets, tokenizer, token count, pooling, normalization and precision
must match. Encode only genuinely missing inputs. Never pad old 384D vectors
and call them native multilingual 768D vectors.

Share exact source units and source maps across lanes, with deterministic AST
boundary chunks and declared surrounding context. Record every chunk's token
count, source spans, overlaps and truncation. Compare 384D and 768D first on
identical short inputs; evaluate longer native 768D context in separate length
bands through 8192 tokens. Large functions require multiple mapped chunks and
an explicit aggregation/obligation profile, not silent token loss. A later
longer-context vector is a new input/profile, even when some source spans recur.

Source384 adaptation is a frozen-projection/vocabulary **ridge head refit**.
It is not the 8D trainer's Adam continuation or gradient averaging. Preserve
actual parent tensors and acquire original training rows/cached vectors or
sufficient statistics for retention. Old head weights alone cannot recover
historical ridge statistics. Its current registered cohort and simple scalar
expression profile also need explicit expansion before general repository use.

The recorded source384 experiment reconstructed 9/9 repository-round development
holdouts in the parent and 0/9 after child adaptation; the child was not
promoted. Independence from parent pretraining is unknown, so this panel is a
retention/regression control rather than an independent teacher qualification.
Do not enable a new model merely because its training rows
fit or because it produced a compilable formula.

Build training rows from exact captured source and deterministic native targets,
reviewed contracts, and separately labeled trusted verification outcomes.
Keep declared intent, observed implementation, test evidence, finite-model
properties and kernel evidence separate. Unchecked model suggestions can be
stored for review, not silently recycled as ground truth. Counterexamples can
produce negative examples and reviewed targeted tests without weakening the
original specification.

Group connected modules, clones/alpha-renames, revision lineage, shared fixtures
and generated variants before splitting. Freeze tuning, canary and independent
evaluation before online fitting. Historical replay rows retain their original
snapshots and do not become assertions about current code. A symbol/version
that contributed evaluation feedback cannot subsequently count as an untouched
independent example.

Proposed objectives are separate measurable terms: typed structural/native IR
reconstruction; critical source-semantic fields; typed family-view consistency;
source-withheld text/code reconstruction where actually supported; retrieval
ranking; and scoped compatible teacher supervision. Normalize per head/unit and
track gradients and variable-field errors so constant grammar tokens cannot
hide semantic collapse. Evaluate decoded candidates independently against
captured source. Do not differentiate through a successful proof status and
call it a source-fidelity loss.

Start with frozen encoders and small readout/adapter updates, bounded steps and
replay. Distill only from evaluated teachers in supported scopes; use matched
codecs/prefixes for soft token KD, or separately aligned fields when outputs
differ. Preserve all original lanes and private weight storage. Broader encoder
fine-tuning invalidates its embedding profile/cache and is a later separately
measured branch.

The current `gte_parallel_paths.py` and its v1 plan accept at most three jobs,
with one unique lane per dimension; their reports cannot identify 12 independent
family jobs. Preserve that contract and add a family/task-aware outer scheduler
or new version. Use composite cell/task/profile/run IDs, disjoint mutable state,
independent availability and promotion, and global resource leases. Twelve
logical paths do not require twelve heavy jobs to run simultaneously.

Keep donor tasks explicit: the structural 8D model can teach matched structural
fields or retrieval behavior, but has no formal token decoder to supervise.
The retained 8D formula head and 384D Legal GRU belong to their own qualified
formula/legal codecs. The released source384 Security IR scalar readout needs
a compatible structured 768D head or field adapter; it cannot be tensor-copied
into an unrelated Legal GRU. Reuse the
[existing donor-transfer contracts](gte_decoder_reuse.md) and
[migration plan](gte_multilingual_migration_plan.md) for compatible body copying
and aligned inputs. Preserve learned components that actually match, and
measure any new adapter/head separately rather than replacing the full decoder
with random weights.

## Progressive span and decoder curriculum per family

Progress through the following stages independently for every family/task/cell:

1. Reproduce the authentic short-span donor task with its original source access,
   vectors, vocabulary, output budget and cohort roles.
2. Qualify one complete supported family unit: code expression/function, security
   declaration/body, legal rule/clause or intent action.
3. Add connected context: calls/imports, threat assumptions, definitions and
   exceptions, or guarded workflow edges. Context-only spans remain distinct
   from the subject being formalized.
4. Qualify a complete supported function, policy, legal section or intent
   workflow under a lossless native target/decoder profile.
5. Add module/document aggregation with sealed chunk coverage and typed
   cross-chunk reference/obligation joins. Missing units and unknown dependencies
   remain explicit rather than becoming whole-document success.

Choose stage limits from measured input and target distributions under pinned
tokenizers/codecs. Freeze numeric budgets before fitting; record UTF-8 bytes,
character offsets, encoder tokens including context/special tokens, decoder
tokens or nodes/slots, and omitted/unsupported spans separately. Reject
overlength or partition explicitly. Never truncate a condition, exception,
guard, code body or target to make a row appear supported. Existing
[text spans](../../ipfs_datasets_py/logic/formalization/text_spans.py),
[Security source spans](../../ipfs_datasets_py/logic/security_ir/cvefixes/source_spans.py)
and [Intent context gates](../../ipfs_datasets_py/logic/intent_ir/formalize/rich_span_targets.py)
provide reusable boundaries, with their existing limits retained.

Longer spans need richer decoders as well as larger encoder context. Preserve
fixed-tree scalar heads for their current task; introduce variable-cardinality,
reference-aware native grammars or hierarchical heads as explicit new variants.
Exact identifiers and source links need a declared copy/reference mechanism or
measured vocabulary coverage. Legal conditions/definitions, Security transition
assumptions, Intent control graphs and Codebase effects require their own
schema-aware handling. An IR-to-prose/code inverse is a separately trained and
evaluated task, with a specified reversible surface channel if original wording
is required.

Use the same short sources first to compare widths; expand native 768D context
in separately reported length/construct bands through its admitted ceiling.
Small teachers may supervise matched short units inside a longer input, with
explicit source/node maps. They cannot certify unseen cross-unit semantics or
act as teachers for unsupported longer targets. Keep shorter-span replay and
parent retention while promoting each larger-span profile independently.

## Supervisor execution and learning loop

1. Capture/observe a declared repository root and resolve the requested intent.
2. Retrieve current symbols, contracts and eligible checked evidence; compile
   missing obligations and the formal work plan.
3. Reserve resource leases and disjoint effect scopes. Run independent analysis,
   proof and test tasks in parallel; serialize shared catalog/head updates.
4. Reobserve exact roots immediately before each effect. Dispatch admitted work
   in isolated branches/worktrees through DecisionRuntime.
5. Measure the actual patch, rebuild changed Codebase IR and invalidate affected
   context, proofs, tests, permits and planning suffixes.
6. Execute verification for the changed tree. Reconcile unknown dependencies
   with broader checks. Record refutations and unsupported obligations.
7. Add eligible source/target/evidence rows to the repository training queue.
   Fit a private candidate and compare it with the frozen parent, zero/rotated
   controls and retained replay. Serving remains on the prior admitted model.
8. If its applicable gates pass, register and explicitly promote the candidate
   for its task/scope. Rebuild candidate indexes under its new identity.
9. Verify the actual rebased/merged target tree and its changed dependencies;
   old branch receipts cannot complete a different merge result.
10. Complete the intent only with the required current postconditions,
    independently measured evidence and existing task-owner acceptance rules.
    Archive all lineage in the control catalog and DuckLake history.

Example pilot: a declared integer-domain function returns `x + 1`, while an
intent requests `x + 2`. The current property becomes an observed conditional
fact and the new property a separately bound planned-post goal. Preserve any
refuted current `x + 2` claim; the transition adapter maps the desired subject
to the measured post-change version. The plan changes the implementation, checks
the source/formula join, verifies the new arithmetic obligation, runs affected
caller/tests and records the new tree. A cached proof of `x + 1` cannot satisfy
the new goal. Reflection or callers outside a closed dependency scope remain
explicit additional work. Declared integer semantics do not claim behavior for
arbitrary Python runtime objects.

## Evaluation and promotion gates

| Gate | Required evidence |
| --- | --- |
| Repository completeness | Every declared-scope entry accounted for; failed/opaque/excluded and unsupported languages visible; paging roots reconcile |
| Source identity | Exact bytes, source maps, schema/toolchain and environment bindings; stale/ABA/concurrent-edit rejection |
| Decoder fidelity | Separate structural, variable-field, exact native IR and source-withheld round-trip metrics; unknown vocabulary and malformed/truncated results retained |
| Proof applicability | Admitted translation and source correspondence; actual checker/certificate; assumptions/bounds/current subject and authority remain explicit |
| Cache correctness | Same-key replay, cross-environment misses, invalidation, restart recovery, interrupted publication and duplicate operation tests |
| Planning correctness | Current grounded intents; forged status/Boolean evidence and required-hook failures rejected; measured effects and actual merged tree checked |
| Online retention | Candidate does not regress preregistered parent/replay/held-out requirements; old weights/caches unchanged; provenance and optimizer/refit method correct |
| Operational benefit | Measured retrieval/scan/proof savings at acceptable coverage and resource use, compared with deterministic and no-adaptation baselines |

Report family-specific semantic fields in addition to common metrics:

| Family | Fields and relationships that must survive |
| --- | --- |
| Codebase | Identifier/case, type/operator/constant, branch/effect/call structure, exact source/symbol versions and dependency scope |
| Security | Allow/deny/require polarity, principal/resource/channel, trust boundary, transition guards/effects, claim assumptions and before/after body bindings |
| Legal | O/P/F, actor/action/object, conditions, exceptions, time and scope; extended definitions and policy authority/objectives |
| Intent | Goal/precondition/effect/assumption roles, modality, actor/tool/object, guards and success/failure/retry/parallel/join edges |

Include switched subjects, inverted operators/modalities, lost exceptions/guards,
truncated outputs, unresolved references and wrong-cell checkpoint/receipt
controls. Evaluate per family, width, dimension role, task, decoder profile and
span stage. A grammar-valid result or agreement among dimensions cannot replace
source fidelity, and one cell's benchmark cannot qualify another.

Freeze numeric fidelity and retention thresholds before model selection. For
the initial controlled arithmetic pilot, require exact critical fields on the
declared supported fixtures and no parent retention regression; do not infer
general Python correctness from that result. Broader repositories need grouped
independent evaluation and explicit absolute fidelity thresholds. Cache and
admission invariants require zero accepted stale/forged cases in the test panel.

Publish metrics per repository, language, construct, function length, logic
family and model lane. Include complete denominators, coverage, unknown atoms,
proof/refutation/unknown counts, conditional versus kernel scope, cold/warm cache
hits, time spent scanning/encoding/checking, peak resources, training cost and
planner repair/replan rate. Tests passing do not upgrade a proof's authority.

## Delivery sequence and concrete work items

| Work item | Scope | Depends on | Completion evidence |
| --- | --- | --- | --- |
| C00 Integration and model inventory | Fresh released checkout, missing GTE and local Codebase dependencies, explicit assets/weights/selectors and clean acquisition | None | Clean clone reproduces selected tasks without missing/random replacement weights |
| C01 Identity and schema joins | Repository forest/head, source/AST/symbol identity, environments and authority mapping | C00 | Closed cross-owner adapters and stale/ABA negatives |
| C02 Incremental repository index | Declared bounded capture, aggregate paging, semantic graph and unsupported coverage | C01 | Complete scope accounting and source-correspondence replay |
| C12 Family task and width contracts | Twelve cells; independent native schemas, dimension roles, task codecs, budgets and readiness inventories | C00 C01 | Every family/width slot is accounted for; wrong-family/role/task contracts reject |
| C15 Isolated stores and routing | Per-cell registry/index databases, lake catalog/data, owner/leases/journals and migration/adoption | C12 | Independent restart/backup/restore/migration; no foreign-table or writer collision |
| C03 Representation and cache lanes | Authenticated vector admission and shared-object refs across independent family/width profiles | C00 C02 C12 C15 | Identical-input reuse and wrong-profile rejection; old caches unchanged |
| C04 Native semantics and projections | Separate native IRs and typed logic obligations with source/applicability joins | C02 C12 | Controlled positive/negative source/formula tests and explicit gaps |
| C05 Durable proof storage | Canonical keys, per-cell SQL durability, outcomes/dependencies and lake publication | C01 C04 C15 | Restart recovery and no candidate-as-proof or missing-artifact completion |
| C06 Invalidation and current reuse | Full-head correctness first; reviewed dependency-slice profile later | C02 C05 | Body/import/policy/toolchain/rebase/concurrency invalidation tests |
| C17 Typed federation and cross IR bindings | Required-cell generation/snapshot vector, exact root types, joins and owner-qualified invalidation | C01 C04 C05 C06 C15 | Wrong-store/role roots reject; partial delivery cannot fabricate complete evidence |
| C07 Intent and planner adapters | Grounding/context packs, registered upstream types, required hooks and admitted facts | C04 C05 C06 C17 | Forged evidence, empty roots and IR exceptions cannot authorize plans |
| C09 Evaluation harness | Frozen family/task groups, budgets, reconstruction/proof/retention and resource baselines | C00 C02 C04 C12 | Preregistered cohorts and separate semantics/surface/proof metrics |
| C13 Family decoder and inverse adapters | Reused compatible heads/bodies; native family grammar and separately scoped text/code inverse | C03 C04 C09 | Correct family/task output codec and budgets; no wrapper-only native-decoder claims |
| C08 Online repository adaptation | Actual inherited weights, family/profile-correct updates/replay and shadow candidates | C03 C04 C09 C13 C15 | Source384 regression reproduced, retention gate enforced, no automatic promotion |
| C14 Progressive span qualification | Complete units, connected context, richer targets and hierarchical aggregation | C06 C09 C13 | Per-cell stage gates and complete span accounting; short-span retention preserved |
| C16 Hugging Face cell packages | Twelve repository mappings, versioned package/load adapters, immutable commits and delivery receipts | C00 C12 C15 | Existing releases preserved; clean pinned acquisition; wrong family/width rejects |
| C10 Supervisor pilot | Read-only planning, effect admission, isolated execution and actual post-tree verification | C05 C06 C07 C09 | One complete witnessed intent-to-checked-change loop, with failure/cancellation cases |
| C11 Packaging and rollout | Clean reproductions, isolated histories, federated receipts, rollback and owner documentation | C08 C10 C14 C16 | Repeatable local package and shadow comparison; separate adoption decision |

C09 starts before fitting so C08 cannot select its own evaluation examples.
Its final candidate reports occur after C08; the prerequisite is the frozen
harness and baseline, not a circular dependency on a trained candidate.

Suggested sequence: first integrate and freeze identities; next deliver the
bounded deterministic scanner and durable read-only proof index; then ground
Intent IR and test planner admission; run the deterministic C10 pilot before or
alongside C08 shadow adaptation; finally package measured results.
Establish the 12 inventories and store/repository mappings before scheduling
family-specific workers. Run compatible 8D and 384D retention work in parallel
across families under resource leases. The November 768D work consumes native receipts
and qualified task-specific targets after those interfaces are stable. Extending
context through 8192 tokens and broader logic families is a staged experiment,
not a prerequisite for the first repository index.

Each family's availability and larger-span adoption is independent. A Legal
768D release need not wait for a Security 768D decoder, and a missing Codebase
768D head must not disable its 8D/384D or deterministic repository paths.

The plan ends with a reviewable local package and integration evidence. Model
training, Git merges, remote artifact publication, default model changes and
supervisor execution require their concrete downstream implementation and
validation; none is reported complete by writing this plan.
