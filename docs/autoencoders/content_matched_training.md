# Content-matched modality training

This opt-in experiment tests whether grouping contrasting modalities for the
same content improves the Legal formula sidecar's reconstruction. It trains
384D inputs; it preserves the 8D linguistic teacher and does not train 768D.
The production default remains independent sampling.

## Motivation and controlled change

An audit of the six preceding final endpoints found 184 modality errors across
1,080 exposed-cohort rule positions. Every error changed obligation to
permission, confined to “is obligatory” and “has a duty to” wording. Passive
wording and permission/prohibition clauses passed. These are repeated
observations of the same 180 clauses, not 1,080 independent examples.

The original 180-clause training bank has 30 actor/action/object combinations,
each expressed with three modalities and two wording styles. Both experimental
arms use this entire bank, the same vectors, full 32-token vocabulary, auxiliary
loss weight 0.05, model initialization, optimizer, and selection checks.
The adaptive scheduler configuration is shared; realized learning rates can
differ when the arms' validation losses differ.

The independent control draws one example from each modality/style stratum.
The candidate groups all six examples for one content combination. Its first
330 updates traverse 11 complete content cycles. The final 10 updates use the
original independent sampler's indices. At the complete 340-update budget,
each individual source therefore has exactly the same exposure in both arms.
An early stop does not establish exposure equivalence.

Each fit retains 2,440 paragraph presentations, 225,840 target-token
presentations, 25,600 original scalar-label presentations, and 2,040 auxiliary
clause presentations. Two seeds, 1729 and 2718, give four fits. Both independent
controls must reproduce their published numerical reports, saved tensors, and
control panels, excluding explicitly enumerated timing fields only.

## Entry points

- `source_modality_auxiliary_training.prepare_tensor_cache(...,
  sampler="content_matched_cycles")` validates a complete bank and prepares its
  deterministic content groups.
- `long_span_source_value_training.train(...,
  auxiliary_source_modality_sampler="content_matched_cycles")` enables that
  sampler. The default is `"independent"`; no auxiliary objective is enabled
  unless its bank and positive weight are also supplied.
- `scripts/ops/autoencoder/benchmark_content_matched_modality_training.py`
  executes the sealed comparison and the previously exposed R6 evaluation.
- `authored_modality_holdout_v2.build_holdout` creates source-only records and
  separate references from a sealed recipe, excluding prior source texts.
- `scripts/ops/autoencoder/prepare_content_matched_holdout.py` produces verified
  local 384D embeddings for the fresh cohort. The single-width adapter validates
  the original native producer report without fabricating 8D or 768D inputs.
- `scripts/ops/autoencoder/evaluate_content_matched_holdout.py` restores all
  selected/final states and saves every prediction before loading references.

The runners require explicit dependency/extension roots, hash-bound manifests
and plans, and a fresh output directory. The evidence folder's `launch_phase.py`
wraps `run_reserved.py` to record guardian exits. Its shared scheduler reserves
one CPU slot and 4 GiB for each sequential phase, observes the owned lease,
enforces deadlines, and retains failures and storage claims. A new attempt name
is required for a retry; completed evidence is not overwritten.

## Evaluation and interpretation

Retain initial, selected, and final-attempt weights and nine original control
panels for both evaluated endpoints. Training normalization remains fixed. The
old R6 wording cohort is exposed development evidence and cannot establish fresh
generalization.

The fresh cohort is generated after sealing the recipe: 48 authored paragraphs,
180 unique clauses, and 216 encoder texts, seed 20261005. Its three new wording
families are expletive infinitival, fronted infinitival, and rule-subject
infinitival. The local verified encoder executes only at width 384 with a fixed
512-token limit and no truncation. No weights are downloaded. The evaluator
rejects overlap with prior IDs, normalized source texts, or float32 vectors.
All eight endpoint predictions are persisted before fresh references are read.
Neither the fresh cohort nor the old R6 cohort drives checkpoint selection or
promotion. The unchanged original development panel still controls scheduling
and selection.

Exact ordered reconstruction and modality/action fidelity accompany token
cross-entropy. A lower average token loss alone does not establish faithful
modality reconstruction. Fit rates count paragraph presentations; auxiliary
clause work is reported separately. Greedy seconds per span exclude
teacher-forced scoring. Shared-host sequential timings cannot establish a
hardware speedup.

These are authored-formula diagnostics with one worker, bridge names `[]`,
prover evaluation false, metric disk cache off, temperature 0, and encoder and
decoder limits 512. No bridge-on evaluation runs; `legal_ir_target_count` is not
measured. Cached training vectors and newly produced evaluation vectors have
different cost scopes. This study establishes neither global convergence nor
federal-law formalization. Only `lake build <Lib>` can admit Lean artifacts;
this numerical experiment grants no admission. The Constitution remains
unformalized.

## Completed comparison, 2026-10-04

All four 384D fits completed 340 updates. Both independent controls exactly
reproduced the published tensors, numerical reports, and control predictions.
Every individual auxiliary source had the same 11 or 12 presentations in the
paired arms. The candidate changes neither training exposure nor success gates.

The matched sampler does not justify promotion. Its final development scores
were 46/48 and 47/48, versus 48/48 for both controls. The three incorrect rule positions
replace `approve` with `examine`. Both candidates still produce 180 rules and
48 syntax-valid documents per seed; “extra” and “missing” whole-rule counts
here describe substituted meaning, not additional rule cardinality. The
unchanged per-length nonregression gate therefore retained epoch 0 for both
candidates. The controls selected their final epoch 80. The retained initial
candidate states score zero exact paragraphs on each evaluated cohort.

The following table evaluates **final attempted states**, including rejected
candidates. Each row combines two seeds on the same 48 paragraphs: 96 endpoint
observations, not 96 independent examples. Field counts use 360 rule positions.

| Cohort | Sampler | Exact /96 | Modality /360 | Action /360 | Full-vocabulary CE |
| --- | --- | ---: | ---: | ---: | ---: |
| Original development | Independent | 96 | 360 | 360 | 0.017832 |
| Original development | Content-matched | 93 | 360 | 357 | 0.017202 |
| Exposed R6 | Independent | 58 | 293 | 360 | 0.027700 |
| Exposed R6 | Content-matched | 60 | 293 | 356 | 0.028959 |
| Fresh authored | Independent | 63 | 296 | 356 | 0.033445 |
| Fresh authored | Content-matched | 63 | 297 | 360 | 0.033156 |

Lower average token loss did not improve fresh exact reconstruction or satisfy
selection. The candidate's one-position aggregate modality gain also does not
mean improved obligation recognition: fresh obligation correctness falls from
59/120 to 57/120, while prohibition rises from 117/120 to 120/120. Both methods
miss all 40 obligation positions in the new rule-subject wording family
(“The rule obliges …”). Both pass all 120 positions in the fronted infinitival
family. The wording gap remains, and this cohort is now exposed for future work.
The field deficits of four positions in the table include whole-document
parsing failures; they are not necessarily four independent action substitutions.

| Sampler | Fit seconds, two seeds | Training paragraph presentations/second | Seconds/presented paragraph | Fresh final greedy seconds/span |
| --- | ---: | ---: | ---: | ---: |
| Independent | 131.425 | 37.13 | 0.02693 | 0.00752 |
| Content-matched | 135.322 | 36.06 | 0.02773 | 0.00746 |

Each training numerator is 4,880 paragraph presentations, plus 4,080 auxiliary
clause presentations excluded from that numerator. Fit time includes scheduled
validation; greedy timing covers 96 predictions and excludes teacher-forced
scoring. Shared-host two-seed measurements establish no speed advantage. The
complete training child took 378.499 seconds and its guardian took 412.144
seconds. Fresh preparation took 16.687 seconds (78.661 including the guardian);
evaluation took 16.939 seconds (48.981 including the guardian). Resource
accounting, process lifecycle and serialization therefore matter outside the
fit timings too; those differences are not attributed to a single cause.

Fresh production authenticated all 216 local encoder vectors, with 12–94 tokens
per encoded text, no truncation, and unchanged 512-token limits. Training reused
cached verified vectors. Fresh vectors were produced for new literal source
texts; metric disk caching remained off. All runs used one CPU worker, bridge
names `[]`, prover evaluation false, and temperature 0. No bridge-on timing or
`legal_ir_target_count` was measured. These are formula-sidecar measurements,
not end-to-end legal-IR throughput or successful legal admissions.

The frozen suite and the separate current-main compatibility suite each passed
3,683 tests with no failures, errors, or skips. The same 16 inherited
incompatible setup cases remain outside this scope and are not counted as
passes. An independent saved-data audit completed 33,137 checks with zero
findings. The current pinned compiler also passed the three existing semantic
gates and all three empty-vocabulary abstentions. Those checks execute no Lake
build and grant no admission.

Training's 20 resource samples observed a maximum resident process-group size
of 1,159,155,712 bytes; this is not an absolute peak. Preparation and evaluation
completed too quickly for the guardian's regular RSS observation file, so no
peak is inferred from their 4 GiB reservations. All three successful phases
released their owned leases. Failed attempts and their retained storage claims
remain intact. The protected restart12 checkpoint's bytes, hash, inode and
hardlink count are unchanged.

Two actual integration failures were fixed before the completed comparison:
explicitly separate historical and current helper/trainer registrations, and
retain the small authenticated initialization-parity record while releasing
larger unused reports. A guarded preflight now exercises both seeds' real
initialization checks and the fresh preparation/evaluation import closure.
Test-reporting isolation failures are also retained in the evidence. No model
objective, acceptance tolerance or training budget was relaxed to recover.

Next work should target source-wording coverage while preserving action fidelity,
with a new predeclared comparison and a separate fresh cohort. This experiment
supports keeping independent sampling as the default. It does not establish
8D/768D gains, global convergence, complete logic-family coverage or statutory
formalization.

The [evidence guide](../implementation/reports/evidence/decoder-content-matched-20261004/README.md)
links the full results, saved predictions, references, states, failed attempts,
resource receipts and independent audit.
