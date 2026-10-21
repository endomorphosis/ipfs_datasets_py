# Compact LegalIR decision inventory and saved-score diagnostics

This additive module explains the existing compact decoder's supervision by
position. It reuses the public compact token encoder and prefix grammar; it
does not introduce a grammar, change the trainer or execute a model.

`prepare_compact_content_decisions_v1` accepts a complete target, independently
supplied context, fixed codec and their exact commitments. It validates the
target through the existing encoder, aligns typed-tree annotations to the
encoder's canonical lexical sequence, and queries the existing prefix owner
at every supervised position. BOS is an input; all following target tokens,
including EOS, remain in the inventory.

Each position retains its prefix, allowed IDs, target membership, tree path
and role: transport, constructor, modal letter, predicate reference, variable
reference, binder declaration or EOS. Forced versus multiple-choice is a
separate dimension. A forced predicate or binder still carries structural
meaning; an integer token alone does not identify its role. Allowed next IDs
are local grammar constraints, not a proof of eventual completion or fidelity
to source law. The first version supports only the existing all-predicates
compact codec; sharing a vocabulary does not admit an optional-catalog profile.

`analyze_compact_saved_scores_v1` additionally accepts exact saved-score packet
bytes and their hash, independently expected checkpoint and conditioning
hashes, and explicit positive bounded forced/choice weights. A packet has the
closed schema `legal-compact-saved-score-population/v1` with fields `schema`,
`target_raw_sha256`, `context_raw_sha256`, `codec_sha256`, `checkpoint_sha256`,
`conditioning_sha256` and `rows`. Each row contains `prefix_ids`, all 537
`logits`, `logits_sha256` and `source_observation_sha256`. Increasing prefix
lengths must match exact prefixes of the target. Duplicate, reordered or
misbound observations refuse; missing observations remain missing.

The diagnostic reports full-vocabulary NLL separately from NLL normalized over
the allowed set, probability assigned outside that set, and raw/constrained
argmax behavior. It groups results by role and forced/choice status. A singleton
allowed set has zero conditional NLL automatically; its full-vocabulary loss
remains visible. These scalar reductions do not authenticate the producer of
the scores. A source-observation hash is a commitment, and its originating
record must be joined independently.

The default weights are both one, matching the arithmetic of an equal-weight
full-vocabulary mean. Explicit weights describe a hypothetical scalar
objective; no optimizer receives them. An incomplete score population has no
complete-target objective. Its observed subset statistics retain a separate
denominator, with every missing target position reported.

The current baseline trainer's equal-weight full-537 cross-entropy and the
separate gated-conditioning comparison stay unchanged. Applying a different
objective requires a separately versioned training/checkpoint contract,
gradient and exact-resume checks, and a controlled experiment. This diagnostic
does not establish that weighting improves reconstruction.

All data is target-exposed teacher-forced analysis. Inventory and score bindings
do not qualify source meaning, permitted context, legal gold, checkpoint
compatibility, graph assertions or Lean declarations. Semantic authority and
training/evaluation-gold masks remain false/zero. No source encoder, model,
optimizer, solver or provider is invoked by these APIs.

The parent workspace's `artifacts/legal-ir-decision-loss-diagnostics-20261018-01/`
retains the selected engineering cohort, original qualification and independent
readback. Source presence alone is not an execution result. The earlier
incomplete BOS reconstructions remain separate observations.
