# Source-bound 8D CodebaseIR federation

The additive `codebase_runtime_8d` profile reuses the shared structural-feature
numerical backend and modality contracts. The reviewed original source worker,
federated reducer, binary update codec and local queue dispatcher are reused.
Existing legal/native/384D runtime files and checkpoint identities are unchanged.

This profile reconstructs structural ProgramIR and authored-contract features.
It has no formal decoder or checked-property predictor. It is separate from the
384D source-text decoder and from repository-specific model heads. Fixed local
tuning and canary data are development selection/retention data, not an unseen
benchmark or a claim of runtime correctness.

`train_current_codebase_features` captures native source targets, freezes the
training vocabulary, and fits a private root. Its children resume one exact
parent's optimizer and basis. `train_current_dispatched_codebase_round` prepares
a common parent and complete source/count declarations, publishes inert artifacts
to the existing CAS, and sends bounded jobs through an actual local `TaskQueue`.
The worker opens neither the model registry nor source owner. Queue records bind
the request, worker attempt and complete source/model round fence; the owner
checks liveness before and after work. This entrypoint executes clients sequentially. The separate
`train_current_parallel_dispatched_codebase_round` uses the same artifacts and
reducer, reserving one worker slot per concurrent fit plus a control slot for
source observation. It cancels and joins every local client before releasing
the parent. No remote fleet or speedup measurement is implied by availability.

Each client produces a binary update against the exact committed parameter
layout and feature semantics. The fixed key union is the four encoder/decoder
weight/bias names; unknown keys and independent feature mappings are refused.
Reduction is deterministic and sample weighted. An aggregate starts fresh Adam
moments and progress; private optimizer histories, proof metadata and model heads
are never averaged. Current updates cover the fixed full parameter union rather
than claiming coordinate-sparsity savings.

Source and model owners remain independent. A complete source edit, expired
native lease or changed attempt prevents the current owner from accepting a
stale queue result. Exact queue completion retry and private worker receipts
recover lost replies without another optimizer execution. Historical replay
performs no fitting, and explicitly validates the completed native model, source,
queue snapshots, immutable binary updates and exact numerical reduction.

The optional `codebase_federated_admission.RetentionPolicy` must be installed on
the native registry before promotion. It independently reevaluates actual
candidate, parent and original-root weights on each fixed canary and replay
sample. Every per-sample reconstruction error must retain the parent and origin
within the declared `1e-12` arithmetic tolerance, and parameter bytes must change.
Saved favorable metrics cannot waive that check. `promote_current` also observes
the exact repository source and uses the existing native expected-parent/head
compare-and-swap. No candidate is auto-promoted; numerical retention grants model
selection only. Source and model updates are not one distributed transaction.

The local production path accepts an existing datasets resource lease supplied
by the supervisor's repository resource bridge. The 8D qualification declares a
1024 MiB parent/worker budget, one CPU slot and one child process slot; the
isolated numerical subprocess enforces its RSS/output/wall/cancellation bounds.
The scheduler's real host policy remains authoritative. Gradient synchronization
is explicitly refused by this executor; the shared synchronization contract needs
an independently qualified collective backend and has no federation fallback.

A two-worker qualification declares three CPU/process slots and 3072 MiB total:
1024 MiB per worker plus 1024 MiB for control. It requires observed overlap of
two actual subprocesses, identical reduction to sequential execution, indexed
restart replay, and actual cancellation/reaping before parent release.

The integration qualification uses five captured scalar source files, unequal
client counts of one and two, actual numerical workers and real durable owners.
It also checks exact retry, favorable-metric forgery, fixed canary retention,
stale parent CAS, lost queue replies, unavailable parent bytes and source changes
after fitting. Production qualification is recorded separately from synthetic
protocol/unit controls; retained host admission refusals are not successful runs.
