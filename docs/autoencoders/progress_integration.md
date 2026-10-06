# Shared autoencoder progress and formalization priorities

The October 6 review combines the Legal decoder experiments with the other
agents' source reconstruction, retrieval, native modality and span-selection
work. The reviewed datasets main is `5171a632c6b9f0ecb2939d29d2ad74992cbfeb11`;
the reviewed workspace main is `3b0162bebe0b7a09727081cb8c5f5c15378caba1`.
The [workspace integration report](https://github.com/endomorphosis/lift_coding/blob/main/implementation_plan/docs/58-autoencoder-progress-integration-2026-10-06.md)
records branch/worktree dispositions, restored dependencies and validation.
Its [16-study evidence matrix](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoencoder-integration-review-20261006/findings/evidence-matrix.json)
binds exact report revisions and hashes. These are observations with different
datasets, objectives and representation contracts; their scores cannot be pooled.

## Preserve the distinct owners

| Owner | Output or representation | How it contributes to text-to-logic |
| --- | --- | --- |
| Protected 8D linguistic teacher | Feature reconstruction and deterministic linguistic IR | Preserve teacher replay and its original training method; verify parser omissions before distillation |
| 8D Legal formula sidecar | Restricted authored rule tokens from historical source features | Tests a separate learned decoder; its weak reconstruction does not measure the teacher's fidelity |
| 384D/768D Legal formula sidecars | Ordered rule structures from cached semantic source inputs | Real generated-output training, field losses, control panels and development selection; limited vocabulary and qualifiers remain gaps |
| Native 4096D decoder heads | Restricted rule tokens from separately authenticated local native vectors | Real head fitting exists; broader exposed development remains 0/12 exact |
| Source-only 8D/384D/768D MLPs | Latent vectors and reconstructed native source vectors | Representation controls and exact numerical resume; no formula decoder or semantic target is implied |
| Native Intent/UI/Security owners | Domain-specific features or native grammar outputs | Keep the appropriate source bindings, logic projections, decoders, loss signals and actual modality Lake checks |
| Source-token/native768 span decoder | Copied symbols and one bounded deontic rule | Retained source-only generation and joint span search; structural proposals require separate fidelity review |

An 8D residual activation inside a 384D checkpoint is another named view. It
retains a 384D skip connection and is neither the historical teacher nor a complete
compressed source encoding. Width alone never selects a checkpoint, decoder or
runtime. Continue to use [explicit version selection](versioned_runtime_interface.md)
and [input/artifact contracts](artifacts_and_inputs.md).

## Read the combined results

The latest [paraphrase modality comparison](../implementation/reports/evidence/decoder-paraphrase-modality-20261004/README.md)
completed four fits and 680 updates. Original development remains 48/48 at both
384D and 768D. Extra modality supervision lowers previously exposed wording CE
by 6.7% and 10.6%, but exact reconstruction changes 20/48→19/48 and 46/48→46/48.
The loss stays opt-in. Both parents already classified all 180 training clauses
correctly; larger relative reductions in that tiny training loss do not establish
better source meaning. All rejected endpoints and control states are retained.

The workspace's separate source-only experiment completed nine expanded MLP fits
over authored TRAIN32/DEV32 source vectors. Its nine selected models improve
development vector MSE over older same-seed models, yet all trail TRAIN-only PCA.
This concerns source-vector geometry. The [frozen downstream comparison](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoformalization-publication-20261004/downstream/summary-01.json)
and [joint conditioning comparison](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoformalization-publication-20261004/joint_conditioning/results-01/summary-01.json)
produce identical raw/PCA/AE formal IR, status and reason on all 192 paired
source/seed occurrences. PCA and AE inverse reconstructions enter the same
raw-trained decoder at full 768D width. This is not a matched decoder-training
comparison or a measurement of reduced-dimensional inference.

The [joint span policy](https://github.com/endomorphosis/lift_coding/blob/main/artifacts/autoformalization-publication-20261004/joint_span/results-02/summary-01.json)
raises raw structural proposals from 10 to 183/192 while preserving the previous
ten proposals. It uses the same native forward scores for both policies with a bounded Top-16/beam-64
search. Actor, modality, qualifier and scope errors remain visible; independent
source fidelity is unmeasured. Proposal coverage, syntax and search scores do not
make these conversions accepted law. Repeated baselines, seeds and publication
copies of the same study remain controls rather than independent confirmation.

Native 4096D source production and decoder fitting supersede the guide's initial
readiness gap. The [conditioning pilot](../implementation/reports/evidence/decoder-conditioning-20261004/results.json)
fits two TRAIN clauses, while the [broader follow-up](../implementation/reports/evidence/decoder-generalization-20261004/results.json)
has 0/12 exact exposed development outputs in both arms. Cohorts and native
profiles differ. Neither selects a production model or establishes convergence.

## Bring each finding into the next training experiment

1. Bind exact source/context identities, representation profiles, decoder schemas
   and label provenance. Separate compiler-generated proposals, teacher outputs,
   independent reviewed targets and disagreements. Agreement between shared
   compiler paths is diagnostic evidence.
2. Prepare admitted TRAIN-only pairs covering roles, modality/negation, qualifier
   presence and attachment, operators, repeated mentions and multiple rules.
   Preserve unsupported and ambiguous requests. Reserve fresh evaluation groups
   before fitting; exposed R6/v3/composition cohorts remain development evidence.
3. Check that the decoder can represent the complete target before training.
   Fixed vocabularies, one-rule literal copying and short native grammars have
   different limits. A representation improvement cannot repair an incompatible
   output contract by itself.
4. Compare raw, PCA, learned reconstruction and source-only decoders with matched
   initialization, training/selection examples, completed updates and decoding
   budgets. Record exact generated rules and every semantic field alongside CE.
   Reduced latents and 4096D capacity require their own measured cost comparisons.
5. Reuse [shared target preparation and synchronization](control_plane_and_sync.md)
   through the existing owner interfaces. Bind any cache to source generation,
   target, producer and policy; keep required live admission checks. Preparation
   and repeated validation are substantial costs in the existing modality fits.
6. Evaluate source fidelity and family-specific semantics before promotion. Route
   solvers only to supported profiles and preserve the [logic-family requirements](logic_output_requirements.md).
   Actual `lake build <Lib>` remains the only Lean admission path; a model loss,
   syntax pass, compiler row or branch merge cannot replace it.

The domain Lake floor extends beyond Legal: IntentIR, UIUXIR and SecurityIR have
scoped native-build evidence in the existing work. That does not establish all
families, every source target or natural-language fidelity. The restricted October
4 head comparisons execute no Lake build. The US Constitution remains unformalized.

## Keep progress present after merges

The review found retained commits whose files had disappeared from `main` during
later source-tree restoration. Read history and the effective tree separately.
The reusable workspace command
[`review_autoencoder_progress.py`](https://github.com/endomorphosis/lift_coding/blob/main/scripts/review_autoencoder_progress.py)
compares selected source files with an immutable target commit and reports
identical, modified and missing paths. It performs no model or proof execution.
Modified files need review against later improvements; missing live dependencies
need tested restoration. Historical evidence can be recovered with exact source
hashes and a bounded scope without reactivating old training or promotion policy.
