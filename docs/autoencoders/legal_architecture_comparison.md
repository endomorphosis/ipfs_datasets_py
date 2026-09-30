# Legacy and current legal autoencoder comparison

The available evidence does not establish that either design produces better
legal features. The current legal runner extends the older sparse residual
model; it has not been replaced by the small neural autoencoder recently added
for UI, Security and Intent. The main unresolved questions are retained feature
capacity, which heads actually influence prediction, and performance on an
independent legal evaluation set. Historical reconstruction scores alone cannot
settle those questions because the default safety projection can return the
supplied target embedding.

This audit is dated 2026-09-30. It inspects the pinned Hub metadata, historical
source, current canonical workspace source and existing experiment receipts.
It downloads no weights, starts no training and changes no model configuration.
The [source inventory](../implementation/reports/evidence/legal-architecture-comparison-20260930/source-inventory.json)
records identities and inspection limits. This is a comparison, not a new
architecture benchmark or a semantic qualification receipt.

## Which artifacts are being compared

The [Hub manifest](https://huggingface.co/datasets/justicedao/legal-ir-autoencoder-checkpoints/resolve/94ca549d102e3e31781370aec1247f91365440eb/checkpoints/20260630T221836Z/manifest.json)
at revision `94ca549d102e3e31781370aec1247f91365440eb` identifies a June 30
canonical warm-start: 398,209,746 bytes, 1,205,336 reusable entries and SHA-256
`7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be`.
It is a weighted union of ten source runs. Three declare `legacy_dense_v1`;
seven declare `legacy_unknown`. Its preparation source commit is
`4f8ec909c82504e64efd5572ca50c7fa2e4f92c0`, but that is not a separate producer
pin for every constituent training run. Sample-specific memory was excluded.

Do not confuse that artifact with the archived restart12 checkpoint used by
many September smokes: 25,895,338 bytes and SHA-256
`1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd`.
Its on-disk JSON has no explicit architecture tag. The verified-embedding
feature smokes also used a fresh compatible 384-dimensional parent; those are
another lineage, not continuation of the same legacy model. Checkpoint identity,
input representation and architecture must be separate experiment variables.

The current published source baseline is dataset commit
`290f53edbcdc3bc893e7f7df434ea050c1e55b61`. The shared checkout has an older live
HEAD and additional work. At inspection, the modal model's difference from that
published baseline changes automatic bridge-worker budgeting, not the model
definitions discussed here. No live checkout, index or archived weights were
rewritten for this comparison.

## Architecture and training differences

| Aspect | Legacy Hub lineage | Current legal runner |
| --- | --- | --- |
| Core model | Input-conditioned, additive sparse embedding and logit tables | Same core `AdaptiveModalAutoencoder` with additional optional mechanisms |
| Meaning of the architecture name | `legacy_dense_v1` does not mean a conventional multilayer bottleneck network | `proof_aware_auxiliary_heads_v2` adds proof-related auxiliary state; the tag alone does not establish training |
| Inputs | Legal sample embedding, parser/frame information and reusable structural/lexical features | Same categories; feature mode requires verified local semantic embedding evidence and immutable targets |
| Encoder and decoder | Encoder stores an `embedding_projection`; decoder returns that vector | Still vector reconstruction, not independently generated formal logic or text |
| Reusable heads | Compiler quality, logic signature, round trip, decompiler plan, predicate/argument, lexical, modal family, semantic slot, view and interactions | Legacy tables retained, plus seven objective-isolated proof heads and optional legacy-teacher adapters |
| Reconstruction measurement | Default target-aware safety projection | Formalization default retains it; explicit feature mode uses the preprojection `raw_decoder` objective |
| Optimizer | Guarded head-specific parameter proposals and line search | Same proposal approach, with optional bounded adaptive rates and accepted-step momentum |
| Optimizer meaning | Feature nudges, not established gradients of the full guarded objective | Still not Adam on the full legal objective; adaptive history is job-local |
| Storage and parallelism | Large dictionary checkpoint and historical warm-start merging | Shared targets, private workers, owner-controlled DuckDB/Quack, sparse replay, optional mapped storage; these do not themselves improve representation quality |
| Admission | Loading or reconstructing a checkpoint is not legal admission | Feature mode remains unqualified; formalization uses separate source/compiler/syntax/Lake gates |

Historical code is available directly at the manifest's
[source commit](https://github.com/endomorphosis/ipfs_datasets_py/blob/4f8ec909c82504e64efd5572ca50c7fa2e4f92c0/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py).
The current [model](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py)
and [worker](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_worker.py)
confirm that the legal training path still instantiates the modal model.

The loader accepts a missing architecture tag as legacy and returns a compatible
state tagged `proof_aware_auxiliary_heads_v2`. It does not thereby train any new
head. The seven proof heads cover obligation family, semantic slots, premise
family, proof-route availability, trusted outcome, reconstruction success and
minimal failing contract. They use separate parameters and report primary
objective proof-loss weight zero. Verify populated tables and trusted-feedback
training receipts before claiming that a checkpoint benefits from them.

Several family-classification and view-logit scales default to zero in both
the old and new constructors. This was not a newly introduced removal. It can
make an updated logit table contribute no change to its direct prediction path.
However, some readers also use table keys and row presence, so zero scale alone
does not justify deleting a table or skipping all associated work. Measure
actual output sensitivity for each configured head.

The five ordinary proposal operators are global view logits, view logits,
family logits, decoded embeddings and a combined proposal. Optional structural
and nonview embedding operators are additional update choices. They are not
logic-family counts. The documented recent feature smoke selected
`decoded_embedding_structural`; it did not demonstrate that every available
head trained. The bounded worker uses `python_sparse_batch`; existence of CUDA
code does not mean this route ran CUDA or Adam.

## Logic projections remain but have different meanings

There are three separate catalogs. None is a count of independently validated
learned syntax generators.

| Catalog | Current members | What membership establishes |
| --- | --- | --- |
| Modal classification labels | Alethic, deontic, temporal, epistemic, doxastic, dynamic, conditional normative, frame, hybrid | Available classification labels |
| Legal IR metric groups | `deontic`, `frame_logic`, `tdfol`, `kg`, `cec`, `external_provers`, `decompiler` | Names used to aggregate target and loss observations |
| Required source-bound syntax exports | FOL, deontic FOL, temporal FOL, deontic temporal FOL, deontic cognitive event calculus, frame logic | Separate parser/fragment checks on actual exported artifacts |

Sources: [modal registry](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py),
[model view catalog](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py),
[family qualification](../../ipfs_datasets_py/logic/autoformal/family_qualification.py).

The five bridge adapters remain `modal_frame_logic`, `deontic_norms`,
`fol_tdfol`, `cec_dcec` and `external_prover_router`. FOL/TDFOL variants share
the TDFOL metric group; CEC/DCEC share the CEC group. Knowledge-graph and
decompiler views are additional evidence channels, not substitutes for the six
syntax exports. Current feature intake requires the complete requested bridge
supervision, but that check does not prove its source semantics are correct.

The historical source already had family/view and family/slot/view tables;
the current family-to-view map adds explicit CEC/DCEC and other aliases. There
is no evidence of a blanket removal of the old logic families. There is also
no evidence that their full semantics have all been learned. In the recent
minimum-duration qualification fixtures, the passing artifacts contained
**zero temporal operators and zero event/cognitive atoms**; the FOL and
temporal-FOL projections omitted modality. The
[qualification report](../implementation/reports/AUTOENCODER_SEARCH_20260929.md)
states these limitations explicitly.

The source compiler produces the rule used for those syntax and Lake checks.
It is not a formula decoded from the autoencoder embedding. The
[qualification implementation](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_candidate_qualification.py)
labels this boundary. Only the actual source-locked `lake build Legal` admits
its generated supported numeric theorem. This does not establish whole-rule
equivalence or formalization of the Constitution.

## The substantial capacity change was in feature transfer

The [legacy inventory](../implementation/reports/LEGAL_IR_LEGACY_FEATURE_INVENTORY.md)
binds the exact Hub weight hash to a separately accepted July transfer. It
records 209,759 accepted rows and 995,577 omitted rows out of 1,205,336 legacy
rows. Of the omitted rows, 907,702 were active. That accepted transfer must not
be assumed to be the checkpoint currently selected by a campaign.

| Feature group | Legacy rows | Accepted rows | Omitted rows |
| --- | ---: | ---: | ---: |
| Modal family | 8 | 8 | 0 |
| Family by view | 42 | 42 | 0 |
| Global legal IR view | 19 | 19 | 0 |
| Logic signature | 4,951 | 4,951 | 0 |
| Family by semantic slot | 70,470 | 8,192 | 62,278 |
| Family by slot by view | 298,685 | 22,068 | 276,617 |
| Sparse compiler and lexical features | 544,979 | 41,804 | 503,175 |
| Slot by view | 176,790 | 40,422 | 136,368 |

These are populated feature rows, not scalar parameter counts or distinct logic
languages. The complete inventory includes additional groups. Of the accepted
rows, 209,753 retained exact old values and six scalar view logits were
overridden. Direct legacy embedding activation was deferred. Reported L1 signal
coverage was 98.4643%; that measures parameter magnitude, **not 98.4643% of
semantic performance**. Small rare-feature weights could matter disproportionately
on unusual statutes. Whether that happened is an open empirical question.

The transfer evaluator compares teacher, target and candidate on eight fixed
rows, with aggregate ground metrics and teacher-fidelity guards. It is useful
migration evidence, not a broad architecture-training ablation. The original
transfer/canary JSON files were unavailable at their documented local Portland
paths during this audit, so the report's exact quality values were not rerun.

## What the existing experiments establish

| Evidence | Supported conclusion | Unresolved question |
| --- | --- | --- |
| June Hub load smokes | The merged checkpoint loaded and ran | Their projection receipts have zero legal IR targets and empty bridge losses; no bridge-on superiority claim is supported |
| July transfer inventory and small canary | Selected rows and lineage were reconciled; transfer had bounded checks | Effect of the omitted long tail on unseen law |
| September same-output speed work | Parser/target reuse and execution optimizations reduced cost while retaining measured results | Whether either model architecture learns better features |
| September controlled optimizer experiments | Adaptive/productive search changed the best measured objective and evaluation cost on fixed synthetic fixtures | Architecture superiority or broad generalization |
| September semantic feature smoke | Real local vectors, parallel updates and exact resume worked; raw tuning cosine improved | Performance on an untouched federal-law test set and later compiler distillation |

The [productive-epoch experiment](../implementation/reports/AUTOENCODER_EPOCH_PRODUCTIVITY_20260929.md)
improved the five-epoch tuning objective slightly while taking 22.7–27.5% more
total training time than its adaptive baseline. Its two synthetic canaries
retained the same reconstruction cosine/MSE. It does not justify a general
claim that newer training is faster to useful quality.

The [feature smoke](../implementation/reports/AUTOENCODER_FEATURE_PRETRAINING_20260929.md)
used six diagnostic training rows and two repeatedly consulted tuning rows.
Two private lanes improved raw tuning cosine from 0.196116 to 0.843544 and
0.826895. The untouched canary was not evaluated. Those gains are meaningful
evidence that the residual updates can learn under that setup, not evidence
that the entire legal feature space is better than the June model.

The important measurement correction is `raw_decoder`. Historical safety
projection computes a target point from the supplied embedding and can return
that exact point when its direction test passes. A reported cosine of one and
zero MSE can therefore conceal poor learned reconstruction. Raw mode bypasses
that final projection for both residual updates and selection. Even raw mode
still starts from a scaled/rotated input embedding; it is not an independent
text-to-logic decoder or proof of a useful information bottleneck.

## Other architectures and representations

The [native structural backend](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_projection_features.py)
is a genuinely different small neural model: normalized per-view structural
features, a tanh bottleneck, reconstruction, and actual Adam with retained
moments. It serves the new UI/Security/Intent paths. Its input meaning, objective,
checkpoint and output differ from the legal residual model; it has not replaced
the published legal worker and has no demonstrated legal superiority.

Optional [factorized interaction heads](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_factorized_heads.py)
represent three Cartesian tables using additive factors, a low-rank interaction
and a bounded residual. The
[migration](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder_state_migration.py)
checks reconstruction tolerance and storage reduction. It is not automatically
selected by the audited legal worker. Packed tensors, Arrow mappings and the
older implicit-DCT representation are separate storage/execution choices;
their existence is not a trained architecture comparison.

## The comparison that should determine the next model

Keep the present training infrastructure, but treat architecture selection as
unresolved. Retain the full legacy state as an immutable candidate/teacher;
do not bulk-activate its omitted embeddings or merge it into current weights
on the assumption that either size or historical cosine proves superiority.

First freeze a canonical source generation and a real source-disjoint
train/tune/test partition. Verify the same local embedding model, dimension and
normalization; an eight-dimensional restart12 diagnostic and a fresh
384-dimensional semantic model are not comparable architecture arms. Pin target
bytes, parser/compiler/codec, all constructor scales, bridge settings, candidate
operators, capacity, seeds and parent lineage. If legacy training provenance
cannot exclude a test section, label it potentially contaminated and report
that evaluation separately.

Use the following staged ablations to avoid changing everything at once:

1. **Runtime parity:** same compatible checkpoint and inputs under historical
   and current runtimes. Record projection coverage and preprojection behavior
   separately from any supplied-target safety output.
2. **Capacity:** derive full, pruned and evidence-selected table sets from one
   common compatible parent, preserving identical values/scales for all shared
   coordinates. Use the same objective and compute budget. Evaluate the exact
   historical transfer separately: its six overrides and mixed lineage would
   otherwise confound capacity with parameter changes. Report rare-feature
   coverage, not just L1 magnitude.
3. **New head contribution:** old-compatible residual model versus v2 with
   zero-influence auxiliary heads, then individually enabled, properly trained
   heads. Audit output sensitivity; an enabled flag is not an ablation result.
4. **Learning objective:** safety-projected versus raw-residual training, scored
   under a common independent evaluator. Include an untrained model, an
   input-copy baseline and frozen-feature downstream probes.
5. **Logic supervision:** all supported families versus one removed at a time,
   on cases containing actual temporal scope, exceptions, negation, quantifiers,
   argument binding and event/cognitive structure. Keep FOL modality loss
   explicit. Test family-specific semantic fidelity, not only parsing.
6. **Architecture replacement:** only after the previous baselines exist,
   compare a genuine bottleneck or sequence decoder on an explicit legal input
   and output contract. A UI feature model cannot serve as this arm by renaming
   its modality. Then compare optimizer policies at fixed evaluation and
   wall-time budgets across multiple seeds.

Select hyperparameters and candidate policy on tuning data; retain the existing
qualification thresholds. Then evaluate the sealed candidate once on the
independent test set. Report per-family target presence, active/update
coverage, raw reconstruction and CE/cosine, abstentions, semantic field fidelity,
downstream feature utility, syntax and scoped Lake results separately. Include
model/optimizer bytes and RAM. For each timing retain sample/target counts,
the five exact bridge names, provers false, disk cache flag, worker count and
cold/shared-target/warm status. A zero-target run is not a faster legal IR run.

The architecture decision should follow time to independently measured feature
quality and preservation of legal structure. Faster epochs, lower repeated
tuning loss, more weight rows or a newer architecture tag are insufficient.
No comparison changes Lake-only admission or the Constitution's unformalized
status.
