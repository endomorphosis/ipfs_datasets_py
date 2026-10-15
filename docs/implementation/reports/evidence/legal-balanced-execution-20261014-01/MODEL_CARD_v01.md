---
tags:
  - legal-ir
  - autoformalization
  - experimental
---

# LegalIR conditions-balanced comparison, 2026-10-14

This release archives actual trained comparison weights and their frozen evidence.
The experiment completed successfully, but **failed its preregistered scientific
acceptance rule**. It is not promoted to the default decoder.

The candidate starts from the trained N10 actor-features checkpoint, SHA256
`b4ea8a502789f6dddba6e159eb7ecebb753d8344a833b0afb9109cfd6830bcd3`.
It freezes all 40 parent tensors and trains only two conditions-presence tensors:
520 stored scalars, 130 active scalars, and 390 inactive copied scalars. Fresh
Adam performs 32 updates on the same 168 training sources, with batch size 12,
seed 1729, and 384 training-row occurrences. Absent/present class weights are
7/8 and 7/6. Weighted cross entropy uses the fixed 12-row batch denominator.

| Exposed diagnostic | N10 | N11 unweighted | This balanced candidate |
| --- | ---: | ---: | ---: |
| Training exact IR, joint, /168 | 153 | 154 | 153 |
| Authored dev exact IR, joint, /72 | 45 | 46 | 46 |
| Authored eval exact IR, joint, /72 | 33 | 33 | 33 |
| Fresh dev exact IR, joint, /36 | 0 | 0 | 0 |
| Fresh test exact IR, joint, /36 | 0 | 0 | 0 |

Two of the four conditions false negatives added by N11 are recovered. Two
remain, in authored eval and fresh dev. There are no new conditions false
positives, positive-head ambiguities, or complete-IR loss IDs relative to N10
across the nine scored scopes. The candidate loses N11's training gain
`matched-temporal-train-plain_deadline-1-p-present`, in both raw and joint
decoding. All 632 initial full-head comparisons and final protected-head
comparisons pass. All 32 legacy permissions remain intact.

The independent analyzer and independent recount agree. The archive contains
all 62 frozen candidate result files, including the actual checkpoint and
training traces. Actual execution used 1,280 new inference forwards and 32
training forwards, for 1,312 model forwards and 1,664 source occurrences.
Six saved N10 capture files are copied without new comparator forwards.

The source directory preserves the package-relative paths of 39 admitted module
owners and the supplemental attention recipe, for 40 algorithm source files.
The contract test and current recipes are included. Source coverage is checked;
an isolated numerical reload from this archive has not been demonstrated.
The raw sources use the qualified recipe's namespace bootstrap rather than a
standalone pip package installation. The shared donor and prior comparison
weights remain in their existing immutable releases.

These panels were previously exposed during development. Their numbers are
engineering diagnostics, not a blind generalization estimate. The eight
statutory examples have no independently qualified reference labels and remain
unscored. Latent conditioning is disabled: the 384-dimensional inputs are
placeholders and no external embedding encoder ran. This experiment does not
validate genuine 8D, 384D, or 768D latent decoding, broader logic-family support,
statutory semantic fidelity, or Lean compilation. `lake build legal` was not run.

The latest upstream source-alignment and parent-context adapters are preserved
separately in the source repository. They support future statutory source
review; they supply no new gold labels or semantic authority to this experiment.

The publication is additive. Prior Hub files and their immutable identities are
preserved. Private reservation bodies, scheduler bodies, and the private ledger
backup are excluded.
