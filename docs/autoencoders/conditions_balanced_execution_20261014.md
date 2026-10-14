# LegalIR class-balanced conditions experiment, 2026-10-14

The prepared F12 experiment has now completed one actual bounded run. Its
outputs and independent recount pass technical checks, but the candidate fails
the preregistered scientific acceptance rule and is not promoted.

## Results

| Exposed joint exact-IR diagnostic | N10 | N11 | Balanced candidate |
| --- | ---: | ---: | ---: |
| Training /168 | 153 | 154 | 153 |
| Authored dev /72 | 45 | 46 | 46 |
| Authored eval /72 | 33 | 33 | 33 |
| Fresh dev /36 | 0 | 0 | 0 |
| Fresh test /36 | 0 | 0 | 0 |

The candidate recovers two of the four conditions false negatives added by N11.
The remaining two occur in authored eval and fresh dev. Across all nine scored
scopes, no new conditions false positives, positive-head ambiguities, or
complete-IR loss IDs occur relative to N10. It loses N11's training gain
`matched-temporal-train-plain_deadline-1-p-present` in raw and joint decoding.
All 632 initial full-head and final protected-head comparisons pass, and all
32 legacy permissions remain intact. The independent analyzer and independent
recount agree on the complete 40-panel, 36-score-set comparison.

These are exposed development diagnostics. The statutory eight examples remain
unscored; no independently reviewed statutory semantic reference is asserted.
Latent conditioning is disabled and no external embedding encoder ran. Genuine
8D/384D/768D latent decoding, broader logic-family support, and compilation with
`lake build legal` remain separate unqualified work.

## Execution and storage

The experiment retains the exact F12 model, donor, 168 training sources, order,
seed, class weights, and evaluation contract. It starts from trained N10 rather
than N11 and performs 32 fresh-Adam updates with batch size 12 and seed 1729.
Absent/present weights are 7/8 and 7/6; cross entropy averages weighted losses
over the fixed 12 rows. Forty parent tensors are frozen; two conditions-presence
tensors contain 130 active and 390 inactive copied scalars.

The restarted temporary root had a different inode. A reviewed transaction
backed up the ledger privately, changed only that stored root identity, and
verified the result using the native lock, atomic write, and strict read-after
path. All 538 existing reservation bodies, charges, and statuses were preserved.
The 145,000,000,000-byte cap was unchanged. No cleanup or claim release was used
to make capacity fit.

A fresh qualified capacity check charged observed bytes, all 44,381,777,216
outstanding reservation bytes, the 200 MB request, and another 200 MB future
output allowance: 140,040,787,504 bytes, leaving 4,959,212,496 bytes under the cap.
The actual successful run adds one released record, giving 539 records, while
preserving every prior record and the same outstanding charge total. The
terminal audit reports 87.465 seconds and sampled group RSS of 774,926,336 bytes;
this is an observation, not an absolute peak or a kernel memory limit.

There are 62 frozen result files totaling 64,172,658 bytes, including actual
weights and training traces. Actual calls are 1,280 inference forwards plus
32 training forwards, with 1,664 total source occurrences. Six N10 capture files
are copied without new comparator calls.

## Source and evaluation corrections

The relocated bootstrap originally omitted an attention recipe that is hashed
by the actor-feature implementation. The admitted closure now includes the
39 module owners plus that exact supplemental recipe: 40 raw algorithm sources,
15 actually loaded modules, and seven mandatory owners. Package-relative source
paths are required in the new Hub archive. Source coverage does not establish
an isolated numerical reload from that archive.

The first scoring attempt refused because its closed joint-schema list omitted
the authenticated N11 comparator format. V02 adds that exact format while
retaining the same source-ID, bounded-search, and pure joint replay checks.
Twelve focused compatibility controls pass. The original source, gate, and
refusal are retained; trained outputs and the acceptance rule did not change.
Stable cross-entropy checks include huge equal logits, for which the loss must
remain log(2). All scoring occurs after the complete qualified output freeze.

## Concurrent progress and next work

The incoming source main at `4e3930f7dca099ce9727512e6fba400209224652`
includes the new source-alignment, parent-occurrence, candidate-context, and
review-handoff adapters. All 40 experiment source blobs are unchanged relative
to the execution snapshot. Root main at
`6c7c63225513598d9b4ca4710d04e01994b36077` includes the source-worker handoff
and indexed proof-context plan. Publication must preserve these changes and
the incoming gitlinks.

A later source refresh advanced the publication parent to
`b114fc385a9eff043cae01cdd47c4d25d189d934`, incorporating the fenced span-ingest
runtime, existing scheduler adapter, resource-owner improvements, and associated
documentation and tests. All 40 algorithm blobs and ten historical resource
producer pins remain unchanged. The publication preserves the complete incoming
tree and all ten source gitlinks; the completed experiment continues to be
qualified against its original historical resource producers.

Active and older owned worktrees disappeared during preparation. The execution
source was restored as an independent checkout with its own Git metadata;
41 historical source files were restored as exact raw artifacts. This does not
assert continuous custody or restore the historical worktree registrations.
Canonical HEAD and index files remain unchanged by this phase.

Further presence-only weighting cannot repair the frozen actor and condition
boundaries. The next training design should target those boundaries using
training-only supervision and explicit retention checks, with separate
experiments for the conditions false-negative tradeoff. The upstream source
adapters can support a separately reviewed statutory reference set once edition,
governing context, ambiguity, and gold-label obligations are resolved. A future
latent experiment must use actual encoder outputs and text/latent mismatch
controls. Logic-family validation and Lean compilation need their own concrete
export/build evidence.

Actual public receipts are retained under
`artifacts/legal-balanced-execution-20261014-01`. Hub and Git publication
completion is recorded in the accompanying completion receipts.

The actual comparison weights and 175 accompanying files are published at
[immutable Hub revision 77e33d1](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/77e33d1c07b09a421b272e3ccb0af229933a7f82/releases/20261014-conditions-balanced-v1).
All 176 files, totaling 74,081,975 bytes, passed immutable CLI byte readback;
all 5,269 older Hub identities were preserved through seven additive commits.
This publication does not change the default decoder.

The fresh history review verifies all 22 selected source commits and ten root
commits remain integrated in the publication parents. All five recovery refs
and registrations remain exact, with branch-only counts 48/50/5/4/6. Three
historical selected refs are now absent; their immutable commits remain
integrated. No lost commit objects or continuous-custody claim is reported.
The proposed next actor-boundary experiment is recorded separately in
`next-experiment-gaps-v01.json`; it has not been implemented or trained.
