# Exposed development projection experiment

This experiment extends the [initial alignment study](alignment_study.md)
with trainable source and formal projection heads, a shared candidate pool,
and preparation for candidate-blind human review. Its outputs remain
**unqualified development diagnostics**. Independently adjudicated source
fidelity is unavailable, and native useful proof coverage is unrun.
This page specifies the protocol; measured outcomes belong to each run's
`report.json` and are not reported here.

## Run the pinned development protocol

Run from the datasets repository root using a fresh output directory:

~~~bash
python scripts/ops/legal_ir/run_alignment_projection_experiment.py \
  --config configs/autoencoders/alignment_projection_development_v1.json \
  --output-directory /tmp/alignment-projection-run-01
~~~

The [CLI](../../scripts/ops/legal_ir/run_alignment_projection_experiment.py)
uses the [projection configuration](../../configs/autoencoders/alignment_projection_development_v1.json),
which binds the [base study configuration](../../configs/autoencoders/alignment_study_development_v1.json)
by SHA-256. Base input paths are relative to the enclosing workspace; use
`--workspace-root` for a different layout. Existing output directories and
symlinks are rejected. Preserve each run and choose a new directory after
changing inputs, settings, or implementation bytes.

The [experiment runner](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_experiment.py)
checks the train/development split and pinned files, records source bindings,
and rechecks their bytes before publishing the report. The recorded bindings
are not a complete transitive dependency manifest. `report.json` is the
artifact to inspect for trial status, case-level rankings, training traces,
configuration and checkpoint hashes, runtime, and authority flags.
Exit 0 means all configured trials completed; exit 3 preserves a partial
deadline run. Neither status grants qualification or production admission.

The default run uses CPU float32 and one PyTorch thread, with a cooperative
180-second budget checked between optimizer steps and trials. The budget is
not a hard interrupt of an individual operation. A partial checkpoint is
retained and labeled, but its unfinished trial receives no retrieval score.
The source encoder, existing autoencoders, providers, and provers are never
loaded or called. PyTorch is the optional numerical dependency used to train
the small projection heads. No sealed final-test inputs are accessed.

## Training and comparison boundaries

The pinned Legal IR panel has 360 training rows and 120 exposed development
rows, with 90 unique training targets. Targets are
`synthetic_authored_unreviewed`; the cached GTE encoder execution is
unauthenticated. These records support controlled authored-reference
diagnostics, not independent natural-document fidelity claims.

The 384D source vectors remain frozen. The
[projection implementation](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_projection.py)
fits its formal vocabulary exclusively on training targets and trains two
linear heads: source `384 → d` and formal `22 → d`, for shared widths
`d = 384` and `512`. Both outputs are unit normalized. The 22-feature formal
codec on this panel uses categorical modality/actor/action/object blocks,
bag blocks for conditions/exceptions/temporal qualifiers, and explicit
unknown buckets. It is a small rule-facet codec, not a full AST or proof
encoder. All three qualifier lists are empty in this panel, so this run
does not exercise their semantics, variable binding, or scope.

The configuration fixes seeds `0, 1, 2` and negative weights `1, 2`, giving
12 trials across the two widths. Each trial uses full-batch symmetric
multi-positive contrastive loss, temperature `0.07`, and SGD with learning
rate `0.1`, weight decay `0.0001`, no momentum, and exactly 80 steps when
the deadline permits. Rows sharing an exact target are positives, including
their wording variants. Weight 2 increases only nonpositive denominator
contributions for training pairs with the same modality, actor, and object
but a different action; weight 1 is the control. This weighting uses authored
facets rather than independently verified semantic non-equivalence.

Development references never enter vocabulary fitting, head training,
ranking, early stopping, or checkpoint selection. Only the final fixed-step
checkpoint of each completed trial is evaluated. Report all configured
seeds and arms; do not select a winner on development and present it as an
independent result. Checkpoints bind their training recipe, codec, source
space, and training file, and are numerically replayed after loading.
Optimizer resumption is not supported.

## A common 90-target candidate pool

Each training target supplies one candidate: average its unit source vectors
and normalize the mean. The raw control ranks these 90 source representatives
by cosine similarity. Learned source-to-source retrieval projects each
representative once; learned source-to-formal retrieval encodes each target
with the frozen training codec and applies the formal head. All arms use
the same candidate IDs and top-five budget. Query ranking accepts source
vectors and identities only; authored development targets are read afterward
for scoring.

This pooled raw control differs from the initial B1 pool of 360 individual
source rows. Compare projection arms with this run's pooled raw control;
a change from the earlier B1 also changes candidate multiplicity. Complete
development targets are absent from training, so counterpart recall and
exact nearest-target copy cannot measure the intended retrieval task.

Actor-action pairs are held out. A single candidate therefore cannot match
all four core facets, and the attainable individual core-facet fraction
is at most `3/4 = 0.75` on this panel. The report describes nearest, mean
top-five, and best top-five core-facet agreement. Best-in-five is an offline
authored-reference diagnostic, not an inference-time selection rule.

Complementary actor/action support requires a retrieved candidate matching
actor, modality, and object, and a retrieved candidate matching action,
modality, and object. It measures coverage supplied by demonstrations,
without establishing that a generator can combine them correctly. Core
nDCG uses authored four-facet relevance and an ideal ordering of the same
candidate pool; normalization can reach 1 despite the individual 0.75
ceiling. These metrics do not certify source meaning, formal reconstruction,
proof validity, or useful proof coverage. Five held-out groups permit
descriptive comparisons; they do not establish broad generalization.

## Stage independent review without disclosing candidates

The [review preparation helper](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_review.py)
selects at most 40 development items with deterministic group, modality,
and construction coverage. The run writes two distinct files:

| File in the output directory | Intended recipient and contents |
| --- | --- |
| `reviewer_items.json` | Hand only this file to reviewers. It contains exact sources, source digests, pseudonymous item/group IDs, and empty annotation slots for the seven facets, ambiguity, and notes. |
| `review_bundle.json` | Keep private with the organizer. It includes original row/group mappings, synthetic authored targets, integrity bindings, sampling coverage, and proposed canonical mutants. |

The reviewer payload excludes reference targets, retrieved candidates,
vectors, and compiler outcomes. Reviewer and organizer payloads have separate
digest manifests in the bundle. Preparing or sending the reviewer file does
not constitute adjudication; reviewer identity, annotations, and review
attestation must be supplied independently.

The organizer's mutant proposals change one covered facet at a time while
preserving typed Legal IR contracts. They retain the original source as a
contrast pair and do not automatically rewrite or annotate its meaning.
Mutants are explicitly unreviewed, unencoded, excluded from training and
evaluation gold, and not proof verified. This run's hard-negative training
uses existing training targets, not these proposals. Review them before any
future semantic-negative study, and obtain richer sources before testing
conditions, exceptions, or temporal meaning.

Every output retains `qualified=false` and `production_admitted=false`.
Human review, independently grouped material, and actual native checker
receipts remain prerequisites for the later fidelity and proof evaluations.
