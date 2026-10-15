# Fixed-view diagnostic and native384 training probe, 15 October 2026

The new [fixed-vocabulary diagnostic](fixed_view_vocabulary_diagnostics.md)
records a stable raw-view denominator alongside existing training scores. It
does not change proposal acceptance, rollback, decoder arithmetic or the
ordinary evaluator. The code and all observations below are backed by the
[compact receipt](../implementation/reports/evidence/legal_ir_fixed_view_probe_20261015.json),
which retains hashes and locations of the full native reports.

## Verification

All **240 tests passed** across the complete six-file diagnostic, nonview,
proposal-bookkeeping, adaptive-optimizer, family-metric and legacy-calibration
suites. This includes missing/unknown target refusal, declared order and
dimension checks, native-decision parity, caller-target mutation, proposal
scoring before rollback, and visible preservation of existing optional-feature
normalization. The first failed fixture run is retained. Validation used the
explicit private pytest-fixture alias profile under an actual F07 owner; this
is not a strict ordinary-filesystem-profile qualification.

Fresh compiler/decompiler canaries passed on the pinned workspace tree with
parser-supplied string atoms. The deadline preserves `10 days` and `emergency`,
has `within_duration`, and returns no Lean pattern. Prohibition stays a
prohibition. The minimum duration preserves quantity 20 and `at least 20 days`.
Every empty-vocabulary request abstains. No compiler vocabulary fallback was
added. Vocabulary and compiler calls were timed separately in the raw receipt.

## Matched experiment

Eight genuine archived native GTE-small384 US Code inputs produced eight new,
complete targets under the current source generation. The six training and two
tuning source identities are disjoint, but the tuning rows are reused and may
have prior model exposure. They are **not an independent holdout**. Every arm
reloaded the same immutable 7,204,344-byte parent checkpoint. Training used one
epoch, one proposal family, one line-search attempt, learning rate 0.35,
momentum 0, raw-decoder reconstruction and `python_sparse_batch` on CPU.

The explicit seven-ID profile binds the pinned producer's six core components
plus preserved `zkp.circuits` tail. It is independent of sampled support and
sparse learned keys; it is not certification of full legal-family coverage.
The two explicit diagnostic distributions came directly from the freshly
verified target objects. Proposal sidecars were captured before rollback.

| Proposal | Native decision | Fixed-view CE before | Proposed fixed-view CE | Training wall seconds |
| --- | --- | ---: | ---: | ---: |
| Structural decoder features | Accepted | 1.945910 | 1.945910 | 14.224 |
| Global view logits | Rejected | 1.945910 | 1.900527 | 12.947 |
| Feature view logits | Rejected | 1.945910 | 1.897565 | 14.207 |

The structural proposal reduces tuning reconstruction loss from
0.001972491 to 0.001917703 (**2.78%**) and raises embedding cosine from
0.827653 to 0.847531. This reproduces the earlier small feature improvement;
it is not a new independent generalization result. Both rejected view states
roll back exactly to the parent checkpoint. Their committed fixed-view CE
remains 1.945910, even though the temporary proposals improve that diagnostic.

The official view CE starts at 1.589027 with row-dependent support and rises to
1.747088 / 1.744227 for the two view proposals. The fixed-support observation
corroborates the normalization confound. It neither retroactively accepts the
proposals nor replaces their official losses. Candidate updates must still
improve the existing objective and satisfy all existing guards.

## Timing and scope

All measurements use the five bridges `modal_frame_logic`, `deontic_norms`,
`fol_tdfol`, `cec_dcec`, `external_prover_router`; provers false, metric disk
cache 0, one bridge worker, one adapter worker, and sample memory false.

Fresh target bridge preparation is **49.201 s / eight spans = 6.150 s/span**.
The target pipeline is **120.603 s = 15.075 s/span**. Full worker wall time,
including verification and bookkeeping, is **239.839 s = 29.980 s/span**.
Metric and multiview caches were bypassed in a fresh process; OS/dependency
caches were uncontrolled. These measurements do not demonstrate an end-to-end
speedup over historical runs.

The six bridge-on tuning evaluations each score two targets and take
**1.231–1.627 s per evaluate**, or **0.616–0.813 s/span**. They reuse these
verified targets and exclude target compilation, so they are not cold compiler
throughput. The matched probe worker takes 114.936 s and peaks at about 1.10 GB
RSS. Native ownership was finalized after durable results and child drain.

The exact dirty canonical working producer is
`301f5086fe0d0915b045572887c3efe38cdf87ab03027e2fbc6b10ff041f7fc7`
(8,767 Python files), unchanged through preparation, probe and canaries.
These observations are not full qualification of every dependency in the
eventual `origin/main` tree. No model weights were downloaded, checkpoint
overwritten, encoder context increased, Hub output published, or corpus
campaign restarted by this experiment.

## Remaining work

The local rootless Docker server responds, but the pinned snapshot image is
absent. Container descendant custody and aggregate RAM remain unqualified, and
the existing launcher is CPU/offline/finite. The proposed explicit scheduler
binding also needs an old-capsule protocol refusal before it can be deployed.
It was retained as a reviewed, blocked artifact and was not applied here.
Continuous CUDA/Hub census isolation is still unfinished.

This is numeric feature-training evidence. It establishes neither learned
formula fidelity nor legal-semantic correctness. No Lake project ran in this
experiment, and no admission is granted. Only actual `lake build <Lib>` is a
Lean admission. The Constitution remains unformalized.
