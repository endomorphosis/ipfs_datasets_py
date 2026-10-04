# Joint predicted coverage over frozen retrieval geometries

This experiment compares coherent predicted-triple coverage with the fixed
MMR control from the [retrieval experiment](alignment_retrieval_experiment.md).
It addresses the independent-facet selector's ability to cover the right
values in incompatible candidates. It reuses the existing probe, predictions,
candidate pool, and projection checkpoints without fitting or calibration.
The recipe is a response to exposed development diagnostics; its comparisons
remain development evidence, not a new independent evaluation.

This page specifies the protocol. Measured outcomes belong to each run's
`report.json` and bound geometry artifacts; no results are recorded here.
Independent source fidelity remains unavailable, native useful proof coverage
remains unrun, and no output grants qualification or production admission.

## Run from the datasets repository root

Use a fresh output directory:

~~~bash
python scripts/ops/legal_ir/run_alignment_joint_experiment.py \
  --config configs/autoencoders/alignment_joint_development_v1.json \
  --output-directory /tmp/alignment-joint-retrieval-run-01
~~~

The [CLI](../../scripts/ops/legal_ir/run_alignment_joint_experiment.py)
uses the [joint configuration](../../configs/autoencoders/alignment_joint_development_v1.json),
which binds the completed prior retrieval report by SHA-256. Prior artifacts
resolve within the enclosing workspace; use `--workspace-root` for another
layout. Existing output directories and symlinks are rejected. Changed
configuration, data, or implementation bytes require a fresh run directory.

The [runner](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_joint_experiment.py)
reuses the SHA-bound raw-source ridge probe and prediction distributions.
Predictions are replayed from the existing probe; there is no new fit,
temperature adjustment, or development-based calibration. All prior
projection generations are retained, with no best seed, width, negative
weight, geometry, or policy selected by development results.

The compact `report.json` contains geometry and group/style summaries.
Each completed geometry has a `details` binding with a path, SHA-256, and
byte count for its separate JSON file containing policy rows and selection
traces. A complete 25-geometry run therefore includes 25 detail files.
**Preserve the report and all bound artifacts together.** Follow
`geometries[].details` for exact filenames rather than treating the compact
report as the complete case-level evidence. Listed code bindings remain a
partial dependency manifest.

The default cooperative budget is 180 seconds, checked between geometries.
It does not interrupt an individual ranking or numerical operation. Partial
runs retain completed geometry evidence and label unrun geometries. Execution
uses CPU, with frozen projection heads loaded for inference. No encoder or
LLM is loaded, no assets are downloaded, no weights are retrained, and no
provider or native prover is called. Sealed final-test inputs are not read.

## Fixed comparison and ranking boundary

The source corpus remains 360 training rows and 120 exposed development rows.
The same 90 unique training targets supply candidates, each represented by
the normalized mean of its unit source vectors. Geometry is raw source,
projected source, or projected formal, as defined in the
[projection protocol](alignment_projection_experiment.md). All 12 prior
projection generations contribute both learned geometries: 25 geometries
in total, each evaluated with `mmr`, `hard_joint`, and `soft_joint`.
This fixes 75 geometry-policy comparisons before their outcomes are read.

Every policy uses the same normalized cosine shortlist of 20 within a
geometry and selects five demonstrations. MMR candidate ordering is checked
against the prior retrieval run over the same 3,000 query/geometry cases;
report that replay outcome separately from new-policy quality. The
[joint selector](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_joint_retrieval.py)
accepts query ID, query vector, training candidates, and predicted facets
through `rerank_joint_candidates(..., variant="hard_joint" | "soft_joint")`.
Query authored references are absent from that ranking interface.

The shared predictions come from the existing training-only raw 384D ridge
probe. Training targets supply candidate labels. Development references
never change the probe, prediction masses, shortlist, coverage objective,
relevance weight, or selected candidates; they enter only post-ranking
diagnostics. Keep all configured arms rather than selecting a development
winner as an independent result.

The selector renormalizes admitted marginal sums to remove tiny rounding
error and breaks argmax ties by label order. These fixed numerical
conventions do not constitute probability calibration.

## What the two coverage objectives measure

A candidate supplies an actor triple `(actor, modality, object)` and an
action triple `(action, modality, object)`. Credit requires each coherent
triple to occur in one candidate. A union of correct individual labels
scattered across incompatible candidates does not suffice.

| Variant | Set coverage value `F(S)` |
| --- | --- |
| `hard_joint` | Half a point when the exact predicted argmax actor/modality/object triple occurs in `S`, plus half a point when the exact predicted argmax action/modality/object triple occurs. Each family is credited once. |
| `soft_joint` | Sum the masses of distinct actor triples and distinct action triples covered by `S`, then average the two family sums. A triple's mass is the product of its three corresponding predicted facet masses. Each distinct triple is credited once. |

Both variants greedily score a candidate as
`0.7 × (cosine + 1) / 2 + 0.3 × [F(S ∪ {candidate}) − F(S)]`.
The fixed relevance term remains active after coverage has saturated.
Stable candidate-ID tie handling and the shortlist budget remain unchanged.

Hard coverage reaching 1 establishes both combinations only against the
argmax predictions and training candidate labels. Those predictions can be
wrong. The greedy selector can also miss available predicted support:
a newly covered family adds `0.15` to the score, which can be outweighed by
the relevance difference. Its coverage objective does not guarantee that
both families will be selected even when the shortlist supplies them.

Soft triple products are an **uncalibrated factorized proxy**. Independent
facet masses do not establish a calibrated joint distribution. Wrong
alternatives can still earn coverage credit after the argmax triple is
covered. Actor-family and action-family credit can also occur under
different modality/object contexts. The averaged family coverage is therefore
not the probability of complementary support in one common query context.
Keep that limitation separate from the benefit of requiring internally
coherent triples.

The experiment performs no calibration. A later calibration study may use
grouped training-only folds, keeping wording siblings and related source
groups together. Freeze its recipe before evaluating development; do not
choose temperatures, thresholds, or relevance weights from development
outcomes. Calibration alone would not verify source meaning or independence
of the facet predictions.

## Evidence and outstanding dependencies

After ranking, authored diagnostics measure joint actor/modality/object and
action/modality/object support in the selected set, core-facet relevance,
nDCG, and group/style behavior. Shortlist support remains a separate
post hoc diagnostic of available demonstrations, not selector input.
Unavailable shortlist support and available-but-discarded support are
different failure modes. Neither metric demonstrates that a generator can
compose a faithful complete formal rule from the examples.

Targets remain `synthetic_authored_unreviewed`, cached encoder execution
remains unauthenticated, and only five development groups are present.
Actor-action holdout still limits individual candidate relevance to three
of four core facets. Empty conditions, exceptions, and temporal fields do
not exercise qualifier semantics, binding, or scope. Preserve the formal
lane's small categorical rule codec distinction from a full AST or proof
encoder.

The [review-admission protocol](alignment_retrieval_experiment.md#receive-actual-reviewer-submissions-separately)
remains pending until actual source-only reviewers return annotations and
identity/independence evidence. A blank 40-item handoff is preparation, not
human review. Two agreeing declared identities create only an unauthenticated
preliminary candidate; conflicting reviews stay disputed. Independent
fidelity and useful native proof coverage require their own later evidence.

The inspected [initial study inventory](alignment_study.md#encoder-and-proof-dependencies)
records separate 8D, native 768D, and Leanstral dependencies. Its 768D asset
directories and decoder checkpoint were unconfigured within the inspection
scope; that does not establish their global absence. Leanstral metadata
records a 4096D hidden width with chat-only configuration and no verified
embedding execution. Compatible vectors, checkpoint lineage, pooling and
tokenizer bindings, and actual numerical capability receipts are still
needed before adding those lanes. This experiment supplies none of that
admission evidence and performs no model loading for those dependencies.

All experiment outputs retain `qualified=false` and
`production_admitted=false`. Source-fidelity authority, automatic human
adjudication, and proof authority are not created by coverage improvements.
