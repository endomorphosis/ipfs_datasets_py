# Hybrid candidate discovery with fixed formal selection

This experiment tests whether source-side discovery can recover demonstrations
excluded by a formal-side shortlist. It extends the
[joint retrieval protocol](alignment_joint_retrieval_experiment.md) while
reusing its frozen checkpoints, probe, predictions, and training candidate
pool. The discovery policies are fixed before their outcomes are read.
No measured results are recorded here; inspect each run's bound artifacts.

The experiment remains an exposed synthetic development diagnostic.
Retrieval support does not establish independently faithful formalization,
successful generation, or useful proofs. No policy, model, or checkpoint
receives qualification or production admission.

## Run and preserve the artifact set

Run from the datasets repository root with a fresh output directory:

~~~bash
python scripts/ops/legal_ir/run_alignment_hybrid_experiment.py \
  --config configs/autoencoders/alignment_hybrid_development_v1.json \
  --output-directory /tmp/alignment-hybrid-retrieval-run-01
~~~

The [CLI](../../scripts/ops/legal_ir/run_alignment_hybrid_experiment.py)
uses the [hybrid configuration](../../configs/autoencoders/alignment_hybrid_development_v1.json),
which binds the completed joint report by SHA-256. Bound inputs resolve
within the enclosing workspace; use `--workspace-root` for another layout.
Existing output directories and symlinks are rejected. Preserve previous
runs and choose a new directory after changing inputs or implementation.

The [runner](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_hybrid_experiment.py)
writes a compact `report.json`, one raw-control detail file, and one detail
file per completed checkpoint pair. A complete run has 13 detail files.
The compact report binds them by exact path, SHA-256, and byte count;
preserve the report and all referenced files together. Follow
`raw_control.details` and `pairs[].details` to inspect case-level rankings
and full discovery/selection traces.

The default cooperative deadline is 180 seconds, checked between checkpoint
pairs. It does not interrupt an individual pair or numerical operation.
Partial runs preserve completed evidence and explicitly mark unrun pairs
and controls. Exit 0 means the configured comparison completed; exit 3
means the deadline left a partial run. Neither status is quality admission.

Execution uses CPU and one PyTorch thread. Existing projection heads are
loaded for inference; no model, probe, or calibration is fitted. Frozen
source predictions are replayed against the existing probe. No source
encoder or LLM is loaded, no asset is downloaded, and no provider or native
prover is called. Sealed final-test inputs are not accessed. The source
bindings are a listed dependency scope, not a complete transitive closure.

## One paired training pool and five fixed policies

The panel remains 360 training and 120 development rows, with 90 unique
training targets. Each candidate retains the existing normalized mean of
its unit source vectors and its paired canonical target. All 12 frozen
projection generations supply both source and formal candidate geometries.
Each pair evaluates five policies; a separately replayed raw hard-joint
control gives 61 configured comparisons in total. There is no best-seed,
width, negative-weight, checkpoint, or development-policy selection.

The [hybrid helper](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_hybrid_retrieval.py)
uses `prepare_hybrid_candidate_pair` to bind both complete geometry maps to
one canonical training pool, including full target hashes and training
membership. Later mutation of caller-owned records cannot change the
prepared pair. Both queries are source-derived; the shared query ID is
checked against training membership. The helper requires the caller to
bind both query vectors to that same original source through provenance,
which the runner supplies through the frozen corpus and checkpoints.

`rerank_hybrid_candidates` selects one policy, while
`rerank_hybrid_policies` evaluates the fixed policy batch. Each discovery
head orders the same 90 training candidates by its normalized query cosine
and exposes a prefix of 20. The final shortlist has 20 candidates and the
selector returns five demonstrations.

| Policy | Discovery membership | Hard-joint selector relevance |
| --- | --- | --- |
| `source_only` | Original source-cosine top 20. | Original source cosine; replays the prior source control. |
| `formal_only` | Original formal-cosine top 20. | Original formal cosine; replays the prior formal control. |
| `source_discovery_formal_select` | Source-cosine top 20. | Formal cosine. |
| `rrf_formal` | Top 20 after equal-weight reciprocal-rank fusion of both prefixes. | Formal cosine, not the fusion score. |
| `quota_formal` | Both heads' first ten ranks, deduplicated, then alternating remaining ranks until 20 unique candidates are retained. | Formal cosine. |

All three new discovery arms use the same hard-joint formal selector:
`0.7 × (formal cosine + 1) / 2 + 0.3 × marginal predicted joint coverage`.
The prediction and coverage definition remain those of the
[joint helper](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_joint_retrieval.py).
Coverage saturates separately for the predicted actor/modality/object and
action/modality/object triples. Predictions can be wrong, and relevance can
outweigh an available support candidate; there is no general support or
source-fidelity guarantee.

Comparing `source_discovery_formal_select` with `formal_only` changes discovery
while holding selector geometry fixed. Comparing it with `source_only`
holds the source shortlist fixed while changing selector geometry. Keep
these comparisons separate when attributing an observed effect.

## Fusion rules and opportunity accounting

Reciprocal-rank fusion uses one-based prefix ranks and the fixed offset 60:
`score(c) = 1 / (60 + source_rank(c)) + 1 / (60 + formal_rank(c))`.
An absent prefix rank contributes zero. Source and formal head weights are
both 1; candidate IDs break score ties. Raw cosine values from different
geometries are not added together. Fusion determines membership only;
formal cosine supplies the selector's relevance score.

At these prefix lengths and offset, a candidate present in both heads
outranks a candidate present in only one. Fusion can therefore favor shared
examples and discard a newly discovered action demonstration. The quota
policy preserves both first-ten prefixes, counting shared IDs once, and
then fills from later ranks in alternating source/formal order. It does
not guarantee ten distinct exclusively source and ten exclusively formal
examples: their memberships can overlap. A useful candidate below the
prefixes or fill cutoff can still be lost.

Two-head discovery has **up to 40 upstream prefix opportunities**, compared
with 20 in a single-head control, even though final shortlist and demonstration
budgets remain 20 and five. This is a resource and opportunity difference;
an improvement cannot be attributed solely to representation quality.
The batch computes both heads once per query for shared evidence, including
control traces. The single-head policy's allowed discovery prefix remains
20; the batch's actual computation must not be described as a standalone
single-head latency measurement.

Full traces retain both head prefixes, the unpruned union and its ranks,
formal/source cosines and fusion scores, the final shortlist, consulted
discovery heads, and selected candidates. Source/formal controls embed
their prior joint-selector traces. The raw control and all 24 paired
single-head controls are replayed against the previous generation.
Inspect replay accounting separately from new-policy quality.

## Diagnose discovery, retention, and selection separately

Only after source-only ranking is fixed does the scorer read authored
development references. The compact report retains each policy's selected
support/relevance scores and its final-shortlist support, plus unpruned
union support for each pair. Group and wording-style breakdowns remain
descriptive. No reference labels, oracle routing, or post hoc choice enter
head discovery, fusion, quota selection, or the hard-joint selector.

Keep three stages distinct: required demonstrations absent from the union;
present in the union but discarded from the final shortlist; or present in
the final shortlist but omitted from the five selections. A larger union
is an opportunity diagnostic, not an available selector oracle. Union
support is reported without comparing its variable-size nDCG to the fixed
five-item policies. Such different-length relevance scores would not
isolate the claimed policy effect.

All targets remain `synthetic_authored_unreviewed`, cached encoder execution
remains unauthenticated, and five development groups cannot establish broad
generalization. The actor/action holdout prevents any individual candidate
from supplying the complete four-facet reference. Empty qualifier lists
leave condition, exception, temporal, binder, and scope semantics untested.
The seven-block formal codec remains a small categorical rule representation,
not a full AST or proof encoder.

The [richer-material inventory](../../../../artifacts/autoformalization-alignment-20261003/richer-material-inventory.md)
records bounded manifest/source inspection, exact file bindings, and richer
authored regression candidates. It identifies no independently reviewed
natural-source corpus within that inspection scope. It does not admit
those candidates to this experiment or authorize opening sealed panels.
The existing 40-item reviewer handoff remains pending; runnable review
ingestion and matching unauthenticated reviewer IDs do not supply independent
fidelity evidence.

Future broader sources, additional logic families, nonempty qualifiers,
native 8D/768D or Leanstral embeddings, generation, and native checker work
require their own compatible input contracts and scoped receipts. This
experiment supplies retrieval diagnostics only. Its primary fidelity value
remains unavailable, useful proof coverage remains unrun, and all outputs
retain `qualified=false` and `production_admitted=false`.
