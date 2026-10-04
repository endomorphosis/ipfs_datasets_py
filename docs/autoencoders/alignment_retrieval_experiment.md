# Fixed retrieval policies and review admission

This experiment compares inference-available retrieval policies over the
frozen generations from the [projection experiment](alignment_projection_experiment.md).
It keeps the [initial study's](alignment_study.md) exposed development corpus
and the projection experiment's 90-target training candidate pool. Its only new fit
is a training-only ridge probe over cached raw 384D source vectors.
No measured outcomes are recorded on this page; inspect the `report.json`
of the particular run for its results and integrity bindings.

## Run from the datasets repository root

Use a fresh output directory:

~~~bash
python scripts/ops/legal_ir/run_alignment_retrieval_experiment.py \
  --config configs/autoencoders/alignment_retrieval_development_v1.json \
  --output-directory /tmp/alignment-retrieval-run-01
~~~

The [CLI](../../scripts/ops/legal_ir/run_alignment_retrieval_experiment.py)
uses the [retrieval configuration](../../configs/autoencoders/alignment_retrieval_development_v1.json),
which pins the completed prior projection report by SHA-256. Input artifact
paths resolve within the enclosing workspace; supply `--workspace-root` for
a different layout. The
[runner](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_retrieval_experiment.py)
checks the prior report, checkpoints, corpus, candidate pool, and recorded
implementation bindings. Listed bindings remain a partial dependency
manifest, not a complete reproducibility closure.

Existing output directories and symlinks are rejected. Each run writes
`report.json`, `facet_probe.json`, `source_predictions.json`, and
`review_admission.json`; preserve these together and use a new directory for
changed inputs or settings. Exit 0 means every geometry completed; exit 3
preserves a partial deadline run with unrun geometries labeled explicitly.
Neither exit status establishes source fidelity or production admission.

The default budget is 180 seconds, checked cooperatively between geometries.
It does not interrupt a single geometry evaluation or numerical operation.
Execution uses CPU and one PyTorch thread. Existing projection checkpoints
are loaded for inference; their weights are never retrained. The source
encoder and LLMs are not loaded, no assets are downloaded, and no provider
or native prover is called. Sealed final-test inputs are not accessed.

## One frozen probe across every retrieval geometry

The [probe and reranking implementation](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_retrieval.py)
fits core-facet labels using training rows only. The probe takes unit raw
384D source vectors and uses a CPU float64 ridge solve with fixed
regularization `0.01` and an unregularized intercept. Its objective uses the
sum of squared residuals plus the weight penalty. Training targets define
the modality, actor, action, and object vocabularies; development references
do not extend these vocabularies or tune the regularization.

Per-facet softmax converts the ridge scores to normalized masses. These
scores are **uncalibrated predictions**, not semantic confidence estimates.
The same frozen raw-source probe and source-only predictions serve every
retrieval geometry, including the projected geometries. No probe is refitted
for a particular checkpoint, policy, or development result.

All 12 prior projection generations are retained. Each supplies projected
source candidates and projected formal candidates, with queries passed
through its source head. Together with raw source geometry, this gives
25 geometries and 75 configured geometry-policy comparisons. No checkpoint,
seed, negative weight, policy, or hyperparameter is selected by development
performance. Report the full panel, including incomplete runs.

Candidate IDs and membership are unchanged: each of the 90 unique training
targets has a representative formed by normalizing the mean of its unit
source vectors. Each geometry produces its own cosine shortlist of 20
candidates, and every policy selects five from that shortlist.

| Policy | Inference-time selection rule |
| --- | --- |
| `cosine` | Select by descending query-candidate cosine similarity. |
| `mmr` | Select the first item by cosine, then balance query relevance against the maximum similarity to an already selected item, with weight `0.7` on relevance. |
| `facet_cover` | Balance normalized query cosine against newly covered predicted facet-label mass, with weight `0.7` on relevance. Each facet-label pair receives coverage credit once. |

For `mmr`, the subsequent score is `0.7 × cosine − 0.3 × redundancy`.
For `facet_cover`, it is `0.7 × (cosine + 1) / 2 + 0.3 × marginal coverage`;
marginal coverage averages the uncovered candidate-label prediction masses
across the four facets. The policies use different score scales even though
they share the configured relevance weight. Candidate labels come from
training demonstrations. Query reference labels never enter prediction,
shortlisting, or selection.

## Interpret coverage as a demonstration diagnostic

Individual facet coverage does not guarantee joint support. A set containing
the predicted actor, modality, and object in separate candidates need not
contain any one candidate with that combination. The same limitation applies
to action/modality/object support. The selector therefore does not guarantee
the complementary actor/action support used by the post-ranking evaluation,
and coverage of predicted values does not certify their agreement with the
source.

The report joins synthetic authored references only after rankings are fixed.
It retains core-facet agreement, nDCG, complementary support, group/style
breakdowns, and the support present in the 20-item shortlist. Shortlist
support is a separate post hoc diagnostic of the available demonstrations;
it never supplies labels or an oracle choice to the selector. Probe authored
facet accuracy is likewise scored after fitting and ranking.

The actor-action holdout still limits a single candidate to at most three
of four core-facet matches. Pool-normalized nDCG can reach 1 under that
constraint. These comparisons do not measure formalization generation,
source-faithful reconstruction, or useful proofs. The targets remain
`synthetic_authored_unreviewed`, cached encoder execution remains
unauthenticated, and five development groups support descriptive comparisons.
The closed probe vocabulary and empty qualifier fields leave unseen atoms,
conditions, exceptions, temporal meaning, binding, and scope unqualified.

## Receive actual reviewer submissions separately

The retrieval run stages the original blank 40-item reviewer payload through
the [review-admission helper](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_review_admission.py).
Its `review_admission.json` remains pending. This records the empty handoff;
it supplies no human annotations, reviewer identity evidence, or attestation.
Hand reviewers only `reviewer_items.json` from the projection run. Keep
`review_bundle.json` and admission receipts private with the organizer.

For genuine returned reviewer files, the
[admission CLI](../../scripts/ops/legal_ir/admit_alignment_reviews.py)
accepts an explicitly bound organizer bundle and repeated bound submissions:

~~~bash
python scripts/ops/legal_ir/admit_alignment_reviews.py \
  --review-bundle /tmp/alignment-projection-run-01/review_bundle.json \
  --expected-bundle-sha256 "$ALIGNMENT_BUNDLE_SHA256" \
  --submission /path/to/reviewer-a.json "$ALIGNMENT_REVIEWER_A_SHA256" \
  --submission /path/to/reviewer-b.json "$ALIGNMENT_REVIEWER_B_SHA256" \
  --output-directory /tmp/alignment-review-admission-01
~~~

Set the example digest variables to the expected SHA-256 of the exact file
bytes and replace submission paths with the returned files. Each
`--submission PATH SHA` can be repeated; the output directory must be fresh.
The reader rejects duplicate JSON keys, nonfinite values, byte-limit
violations, and digest mismatches. The helper enforces the known closed
schema and unchanged source text, source digest, item ID, group pseudonym,
and evaluation role. Unknown items and duplicate reviews are rejected.

Completed annotations require modality `O`, `P`, or `F`, actor/action/object
strings, qualifier lists, explicit Boolean ambiguity and unsupported-meaning
flags, a reviewer ID, and a valid UTC timestamp. Empty qualifier lists record
reviewed absence; blank or incomplete slots stay pending. Item subsets and
reordering are accepted. Conflicting completed annotations remain disputed
without resolution against authored references. Unambiguous agreement from
two distinct declared reviewer IDs creates only a preliminary adjudication
candidate: JSON does not authenticate their identities or independence from
the source author.

Authored-target agreement is computed only after accepting an undisputed,
unambiguous annotation and remains a separate authored-reference diagnostic.
No submitted labels create a review signoff automatically. Independent
fidelity stays unavailable, native useful proof coverage stays unrun, and
every receipt and experiment retains `qualified=false`,
`proof_authority=false` where applicable, and `production_admitted=false`.
