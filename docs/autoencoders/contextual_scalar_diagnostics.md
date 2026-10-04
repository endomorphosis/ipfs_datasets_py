# Observing source and recurrent decoder decisions

Use `generated_scalar_observation.py` to explain scalar-token decisions made by the experimental contextual formula decoders. It records the source guidance and recurrent readout used at each actual generated actor, action, modality and object site. It does not change the model, inference policy, training objective or qualification rules.

The supported schemas are the Legal clause-source, action-factorized clause-source and ordered-clause recurrent experiments at native widths 8, 384 and 768. This is not a decoder or family-qualification adapter for Security, Intent or UI IRs.

This fills a gap in the preceding [generated-replay comparison](generated_replay_training.md): correct source-head predictions did not always produce correct formulas, but the saved reports lacked the combined logits at those decisions. A recurrent readout already includes paragraph, clause and generated-history effects. These observations separate the additive scalar guidance from that readout; they do not isolate the causal effect of an individual source feature or recurrent component.

## API and execution

The module is under `ipfs_datasets_py/logic/formalization/autoencoder/` and provides two separate operations:

1. `collect_source_scalar_trace` accepts closed source-only rows, their explicit clause contexts, a checked contextual model, codec and input transform. It runs the existing greedy generation with a temporary read-only hook on the recurrent output layer. Applied source logits come from the existing state cache. Every scalar event retains all vocabulary coordinates for the recurrent, source and combined logits, together with its consumed-prefix position and source-slot provenance.
2. `score_scalar_trace` validates the completed trace before accepting references. It reports full-vocabulary cross-entropy, target margins and argmax results separately for the source, recurrent and combined logits. The caller must explicitly label the split `training` or `exposed_development`; this label alone is not independent evidence of split provenance.

No model copy, extra model forward, second source-head evaluation, forced token, syntax mask or reference prefix is used during collection. Float32 addition must exactly reconstruct the observed combined logits. The same source-only greedy policy still chooses every token. Temporary hooks are removed on success or failure, and caller weights, gradients, modes and random state are checked for preservation. The caller must have exclusive use of the observed model; pre-existing hooks on its recurrent readout are refused.

Missing source slots are recorded as unavailable, and reference sites that generation never visits remain unvisited. They are not counted as correct. Positional source-clause/reference-rule alignment is an explicit authored-fixture contract, not inferred statutory semantics. All vocabulary tokens remain eligible competitors.

The collector has a cooperative deadline and a trace-retention memory estimate. That estimate excludes the existing model, imports, Python allocator and process RSS; an outer resource guardian is still required for campaign execution. Neither API returns a differentiable training loss.

## Replaying published states

`scripts/ops/autoencoder/diagnose_contextual_scalar_margins.py` authenticates the published generated-replay study, restores its saved final attempts and checks reconstructed preprocessing against the archived inputs. It performs one observed greedy rollout per panel and requires exact equality with the archived generation, including token IDs and termination status, before reference scoring.

The frozen runner explicitly registers its contextual-boundary and generated-field dependencies before importing the observer. An import-only preflight checks that closure with the pinned dependency package path unchanged and forbids importing Torch. The first guarded attempt exposed a missing registration before observation began; its failed receipt and retained storage claim are preserved separately from the retry.

The fixed plan covers all 18 saved states: widths 8/384/768, seeds 1729/2718 and three replay recipes. Each state is observed on 48 training and 48 exposed development rows, giving 36 panels. These are repeated observations of the same authored examples, not 1,728 independent holdout documents. Selected checkpoints remain distinct from the final attempts being diagnosed.

The historical 8D linguistic teacher is untouched. The experimental 8D formula sidecar uses nonsemantic linguistic-feature hashes; the larger sidecars use authenticated cached semantic embeddings. There is no encoder execution, download, context-window increase or training in this diagnostic. Temperature remains zero and the output ceiling remains 512 tokens.

Numerical decomposition, formula syntax and reconstruction scores grant no Lean admission. Only the applicable successful `lake build <Lib>` can do that. This diagnostic runs no Lake build or native family qualification and promotes no checkpoint. The Constitution remains unformalized.

## Interpreting a training gap

Inspect training and development results separately. Source-correct/combined-wrong events show an additive override at a particular actual prefix. They do not establish that removing the recurrent component would repair a complete formula. Source-wrong/combined-correct events show why blindly forcing source-head answers can also be harmful.

A future consistency objective would need a training-only eligibility rule, an execution-matched zero-weight control, a bounded gradient policy and fresh evaluation. The diagnostic must not turn familiar development errors into training labels or declare a new default from a few repeated examples. In particular, exact training reconstruction can make first-wrong supervision inactive while differences between the source and combined distributions remain measurable.

## Measured results

The completed diagnostic restored all 18 final attempts and observed all 36 panels. Generated tokens and termination statuses matched the archived predictions exactly. Every visited, available source-logit vector also matched the previously saved raw source-head readout. The independent audit checked the additive decomposition, causal slot routing, full-vocabulary scores and missing-site accounting. This is evidence about unchanged inference, not a new reconstruction improvement.

The table counts repeated scalar-site observations across six models per width and split. A panel contains the same 48 authored documents; these totals are not distinct held-out examples.

| Width | Split | Scored scalar sites | Source correct | Combined correct | Source error corrected | Correct source overturned |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 8 | Training | 4,292 | 3,611 | 3,705 | 139 | 45 |
| 8 | Exposed development | 4,320 | 2,499 | 2,476 | 169 | 192 |
| 384 | Training | 4,320 | 4,320 | 4,320 | 0 | 0 |
| 384 | Exposed development | 4,296 | 4,296 | 4,293 | 0 | 3 |
| 768 | Training | 4,320 | 4,320 | 4,320 | 0 | 0 |
| 768 | Exposed development | 4,320 | 4,320 | 4,305 | 0 | 15 |

There are also 28 unvisited reference scalar sites in 8D training and 24 in 384D development. They remain gaps outside the scored-site denominators. All 18 higher-width development overturns are action decisions. These include the seven baseline errors diagnosed in the preceding study; the observations confirm their additive conflict rather than introducing new errors.

All 12 higher-width training panels reconstruct 48/48 documents exactly. At their 8,640 scalar sites, source and combined argmax are both correct, even though the recurrent readout prefers a different token at 5,112 sites. That disagreement is not itself a defect: the components are trained to work together. In 8D training, recurrence corrects 139 source mistakes while overturning 45 correct source decisions. An unconditional penalty that forces agreement with source logits could remove useful corrections.

The next experiment should distinguish reduced source-correct margins from merely different component argmaxes, retain ordinary reconstruction losses, and exclude source-wrong sites from any proposed source-teacher penalty. This diagnostic neither selects a loss coefficient nor establishes that such a penalty will generalize. A new blind test set is needed; the current development cohort has been repeatedly inspected. The 8D formula sidecar's source-readout weakness also needs separate treatment from higher-width action crossings. None of these numbers measures the historical linguistic teacher.

A separate training-only assessment found reduced target-versus-best-other margins at 2,902 of the 8,640 higher-width source-correct sites, including 164 of the 2,160 action sites. None had a positive combined margin below half its source margin. That half-margin threshold is descriptive, not a chosen hyperparameter; a penalty activated only below it would have no signal at these higher-width training endpoints. The margin-preservation eligibility excludes source-wrong sites, and the assessment reads no development traces. Margins against different best competitors must not be added as though they were a common token pair.

## Timing and validation scope

| Width | Observation plus posthoc scoring per 48-row panel | Wall time per span |
| --- | ---: | ---: |
| 8 | 0.428–0.546 s | 8.92–11.38 ms |
| 384 | 0.695–0.822 s | 14.48–17.13 ms |
| 768 | 0.963–1.095 s | 20.06–22.81 ms |

These timings include trace validation and reference scoring; they are not bare inference throughput. The successful diagnostic process took 36.427 seconds including restoration and source preparation. Its guarded wrapper took 125.833 seconds including admission and accounting. The failed first attempt took 90.237 seconds and stopped at import before any observation panel completed.

Every panel used one CPU worker, batch size 8 and 48 samples. Bridge names were `[]`, provers were disabled and the legal-IR metric disk cache was disabled. Source embeddings were already cached; no source encoder or cold natural-language compiler was timed. No bridge-on evaluation ran, so this is not a legal-IR bridge speedup measurement. The shared host and added diagnostic work also prevent a throughput comparison with the prior training study.

The successful attempt retained 83,297,988 bytes under a 300,000,000-byte reservation and a 4,096 MiB memory reservation. Maximum sampled live RSS was 811,409,408 bytes, based on two samples; this is not an absolute peak. Its 40 active lease observations had a maximum observed gap of 1.010 seconds. Child and guardian exited successfully and resource accounting finalized normally. The first attempt's failed 300 MB claim remains retained; no foreign claim or storage cap was changed.

Validation passed: 2,899 frozen regression tests, 73 guardian tests, 70 actual-package cold-import checks and 843,949 independent numerical/resource checks. Sixteen inherited setup cases for an incompatible retained 384D release remain excluded and are not counted as passes. No native family validator or Lake build ran; no weights or optimizer defaults changed.

Complete traces, scores, failed-attempt receipts, scripts, frozen sources and exact references to the original states are retained in the [evidence manifest](../implementation/reports/evidence/decoder-contextual-margins-20261004/manifest.json) and [results](../implementation/reports/evidence/decoder-contextual-margins-20261004/results.json).
