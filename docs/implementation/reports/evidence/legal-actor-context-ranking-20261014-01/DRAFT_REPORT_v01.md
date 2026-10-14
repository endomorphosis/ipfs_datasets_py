# Actor context with filtered ranking: untrained candidate

This draft adds a decoder continuation that combines the trained F15 actor
context with the existing filtered ranking objective. No F16 training, model
inference, checkpoint parsing, resource census, reservation or promotion has
run. Independent qualification is pending: all three collaborating agents reached
the account usage limit during preparation.

The new `SpanActorContextRankingAdapterDecoder` copies all 42 trained F15
tensors. It freezes the 36 nonactor tensors, including every learned conditions
row, and trains the same six actor projection, query and context-gate tensors:
908 stored scalars, 258 active and 650 inactive. It delegates the entire forward
factory to F15, preserving the differentiable actor route and the extra frozen
full-width conditions pass. No inference candidate heuristic is changed.

The objective retains the exact targeted main-loss normalization and adds its
existing actor hinge at coefficient 0.25 and margin 1. The wrong-span domain is
the complete valid source-boundary domain, excluding the exact actor gold span
and spans overlapping present gold nonactor roles. Wrong-span selection uses
detached scores; the chosen wrong and gold scores retain their gradient graph.
Empty domains retain a connected zero and remain in the full batch denominator.
The candidate records source, training-index, gold-coordinate and filtered-domain
identities in its objective trace. Geometry and trace agreement alone do not
establish membership in the authenticated training set; the guarded runner and
independent recount must verify that join against the fixed training manifest.

The fixed proposed recipe is one 32-update run from the exact published F15
checkpoint, with fresh Adam, learning rate 0.001, batch size 12, seed and order
1729, no weight decay and gradient clipping at 5. Latent conditioning remains
disabled with 384-dimensional placeholders. Trained query and gate values are
preserved; no fresh-zero first-step assumption is introduced.

The preregistered acceptance conditions are conjunctive:

- All 632 initial source head vectors and greedy/joint predictions must match
  the trained F15 donor before the first update.
- All 632 final modality, four presence and nonactor boundary score vectors
  must retain their protected binary32 bits.
- Training raw and joint complete IR must both reach at least 155/168.
- Neither route may lose any complete-IR success versus either N11 or F15
  across the nine scored scopes, and all 32 permission cases must remain intact.

The postfreeze comparison has four states: frozen N11, F15 parent, initial
candidate and trained candidate. It scores 36 authored state/scope sets, reports
40 panels including the four unscored statutory panels, and compares two sets
of nine scopes. Saved comparator outputs add no model forwards. Evaluation
reference bodies and the separate postfreeze comparator input file must remain
outside the training child's admitted parsing closure.

Eleven detached stdlib/fake-interface decoder contracts pass. They cover exact
donor and all-tensor identity maps, fresh six-tensor optimizer state, trained
query/gate behavior, protected conditions and inactive rows, factory delegation,
fixed scheduling, and source/gold/domain/hinge trace tampering. Twenty-five
synthetic resource predicates also pass. These checks are author-level source
evidence, not independent source approval, actual Torch validation, a real
resource observation, or evidence of higher training accuracy.

The resource port retains the 145,000,000,000-byte cap and the existing guardian,
adoption and watchdog bytes. Its historical anchor is the completed F15
540-record map; live record counts, outstanding claims, occupancy and capacity
remain unknown. A future qualified observation must preserve every historical
body and fully charge typed additions, including the 200 MB request and 200 MB
future-output allowance. No source or resource gate has been fabricated.

The source checkout starts at merged F15 `b1fd77597867ad31f1687edc8bff090caf3d3b7d`.
All 40 retained algorithm files remain byte-identical; the new candidate adds
the forty-first. The separate root checkout starts at newer incoming main
`729d97881136681e90c05e9d2e0707f57708755d`, retaining another agent's accelerator
advance and repository-proof work. Canonical HEAD and index anchors remain
unchanged. The draft does not change main, any root gitlink, a default decoder,
or the existing published weights.

Before training, finish independent model and resource source review, complete
and qualify the F16 runner/preparer/inert bootstrap and terminal/freezer ports,
obtain a fresh qualified resource baseline, and qualify the concrete run plan.
Only then run the single bounded candidate. Freeze all outputs before executing
the independently reviewed analyzer and recount. Preserve a failed scientific
outcome without a tuning retry or automatic promotion.

Real US Code semantic fidelity, genuine active 8D/384D/768D latent decoding,
broader logic-family qualification, isolated numerical reload and
`lake build legal` remain unqualified.
