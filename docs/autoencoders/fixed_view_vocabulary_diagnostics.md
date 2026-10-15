# Fixed view vocabulary diagnostics

`modal_autoencoder_view_diagnostic.FixedViewVocabulary` declares raw view IDs
for one modality, schema and model lineage. `score_fixed_view_vocabulary` scores
explicit target distributions against those same IDs with sample memory off.
The declaration is caller supplied: its coverage and lineage labels are not
authenticated by this diagnostic. Bind the declaration, source, checkpoint and
teacher-target hashes in the experiment receipt. Use separately reviewed
declarations for legal, intent, security and UI schemas and each dimensional
lineage. The seven aggregate legal reporting families are not raw view IDs.
The helper requires the current numeric raw-view head API. Labeling a profile
does not give a modality adapter a missing projection or decoder capability.

This addresses an observed comparison problem: a baseline can normalize one
row over four target views and another over six, while a sparse update inserts
six global head keys and expands both denominators. Historical native scores
continue to use their existing support. A fixed six-class **controlled test**
has uniform cross entropy `ln(6)` before and after zero global keys are inserted;
six observed legal views do not establish an exhaustive legal schema.

## Training usage

Pass `projection_view_vocabulary_diagnostic=vocabulary` and
`projection_view_diagnostic_targets={sample_id: distribution, ...}` to
`AdaptiveModalAutoencoder.train_generalizable_projection`, or forward them
through the existing gated training interface. The targets must exactly cover
the validation rows (training rows if no separate validation split exists).
Use the explicit distributions from the prepared bridge target payload and
retain its producer provenance. No extra bridge pass is run by the diagnostic.
The diagnostic neither consults stale caches nor substitutes a model prior.

Targets are copied and validated before updates. Missing targets, unknown IDs
(including zero-valued unknown entries), nonfinite values, invalid probability
mass, duplicate sample IDs, embedding-dimension mismatch and modal-label
collisions refuse the request. Numeric scoring uses the existing head method
with `use_sample_memory=False`; it preserves declared ID order. Unlisted head
keys are excluded by the declaration; their absence from a score is no coverage
claim. Expanding the vocabulary creates a different profile hash and experiment.

The optional `fixed_view_diagnostic` report contains baseline and committed final
scores. Each evaluated proposal includes its score while the proposal is still
applied, before rejection/rollback. Composed refinement validation is covered
too. Invalid candidate logits are reported as unavailable while the existing
native metric and rollback checks still decide the outcome. An invalid baseline
refuses before parameter updates. With the option absent there are no added
scores, parameter hashes, bridge evaluations or report fields.
Diagnostic work consumes part of the existing training deadline; enable it for
bounded experiments and measure that overhead before using it in long runs.

## Interpretation and limits

The sidecar is excluded from the optimizer objective, Pareto guards, legal-IR
loss dictionary and admission checks. A better sidecar score cannot accept a
rejected proposal. It is not proof of convergence, held-out generalization,
formula fidelity or formalization. No checkpoint format, 8D linguistic decoder,
encoder context window or inference scorer is changed. Only an actual
`lake build <Lib>` grants the corresponding Lean admission; this diagnostic
runs no Lake project and grants no admission.

Fixed support removes the softmax-denominator confound, but preserves existing
feature arithmetic. In particular, an active optional feature with a nonempty
zero-valued map currently counts toward learned-feature normalization and can
rescale another feature's nonzero logits. The tests document this behavior;
this change does not silently fix or mask it. No semantic or throughput gain
is claimed from the controlled numeric tests.
