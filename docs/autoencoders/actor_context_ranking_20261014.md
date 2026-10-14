# Actor context ranking continuation: model sources reviewed; runtime update pending

This is the untrained candidate in draft source PR [1304](https://github.com/endomorphosis/ipfs_datasets_py/pull/1304). It combines the trained F15 differentiable actor context with the retained filtered ranking hinge. No F16 checkpoint, accuracy result, main merge or new Hugging Face weight release exists.

The latest trained donor remains F15: 154/168 complete training IR matches in both decoding views. Its immutable experimental release is [1622817fd804ff5333fce7dc8d04433e4acef2e4](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/1622817fd804ff5333fce7dc8d04433e4acef2e4/releases/20261014-actor-refinement-v1). Those are exposed engineering diagnostics, not an independently established statutory semantic accuracy.

## Candidate and validation

The candidate copies all 42 trained F15 tensors, freezes the 36 nonactor tensors including the learned conditions head, and trains six actor/query/gate tensors with fresh Adam. The existing main loss normalization remains unchanged; the additional term is the full filtered actor hinge with coefficient 0.25 and margin 1. The fixed recipe remains one 32-update attempt, batch 12, seed/order 1729, learning rate 0.001 and latent input disabled. There is no hyperparameter search or automatic promotion.

Independent review found and resolved an exact-type validation gap: returned training indices must be integers, excluding Boolean and decimal aliases. The earlier draft bytes and finding are retained. The current module is 57,479 bytes, SHA256 `6f37e5295ab09fe5f61215ab0445e6348d2972551c6bee1719e1c3c2ce2bd1aa`.

Completed checks are recorded in the adjacent evidence directory:

- Independent model review: the 11 original detached controls replayed against the current module, plus 19 independently authored scalar-graph, domain and policy controls. These do not establish actual Torch behavior.
- Training harness: 11 author controls and six additional independent membership refusal cases. Every recorded ranking row must join the exact authenticated training text, index, gold spans and complete filtered domain.
- Actual qualified import-only bootstrap: 40 declared modules, 17 measured loaded modules and nine mandatory imports. The supplemental attention file makes 41 raw algorithm sources. No model or numerical library was imported by this smoke check.
- Evaluators: 55 detached controls independently replayed. Both frozen N11 and F15 comparators are covered across nine scored groups in raw and joint views. The analyzer and recounter share an author; a different agent reviewed both. Actual scoring remains prohibited until the full output freeze and actual runtime bindings exist.
- Resource source checks and synthetic controls passed; they do not establish current compatibility, capacity or admission.

All 40 retained algorithm source files remain byte-exact. The package change is the added hybrid module and its reviewed validation hardening. Earlier findings, superseded drafts and failed observations remain evidence, not successful qualifications.

## Actual runtime prerequisite gap

The first bounded resource collection stopped on the guardian's read-only compatibility check, before sampling, census, admission, a reservation or model work. A separately reviewed one-shot diagnostic reproduced the identical 1,283-byte stderr identity and safely disclosed the exact error: `exact complete persisted scheduler configuration required; unknown/missing keys refused`.

A qualified private copy and a separately reviewed config-only inspector established that the existing scheduler now has 24 source-declared configuration fields instead of the older adapter's 19. There are no unknown or missing configuration keys. The five additions concern the proof profile and recovery; recovery is disabled in the sampled configuration. Existing global capacities also differ from the historical policy: 16 CPU slots, 99,688 MiB and 16 child slots, with proof memory headroom 24,922 MiB. The second independently reviewed inspector authenticated the same private copy and disclosed lane values only after matching source-declared lane names and a closed integer schema: the validation lane reserves two CPU slots and zero MiB. All 24 sampled configuration values are now available in the public inspection receipt; its canonical configuration SHA256 is `f07cb14289fcb6275e4497dcc36be0dcf8bfc3dc87531ff7a9537eb85fdcc661`.

These observations do not authorize resetting shared configuration. The next work is to qualify an adapter for the newer scheduler and preserve its current native safeguards, including PID headroom and cancellation/draining during lease release. Adding the five schema fields to the old adapter alone would omit newer native behavior, so that shortcut is not qualified. The experiment's own request stays two CPU slots, 1,536 MiB, one child, 300 seconds and 200 MB, with the same 145 GB native storage cap and four counted physical roots. Current ledger totals, root compatibility, storage fit and admission remain unqualified. No foreign state, capacity, claim or lease was changed by this phase.

## Fixed acceptance and remaining work

Before update zero, all 632 source rows must reproduce F15's full binary32 heads, greedy decisions and joint decisions. After training, modality, all four presence heads and all nonactor boundaries must remain bit-equal. Scientific success additionally requires at least 155/168 complete training IR matches in both views, zero complete-IR loss IDs versus **both** frozen comparators across all nine scored groups and both views, and retention of all 32 permission cases without abstention. A failed scientific result is archived without a retry or promotion.

The guarded run, complete 62-file freeze, actual independent scoring/recount, experimental weight publication and final integration are still pending. Selected training scalars cannot independently prove the complete preupdate argmax or live gradient graph. This phase does not qualify active 8D/384D/768D latent semantics, independent US Code semantic gold, broader logic-family correctness, portable numerical reload or `lake build legal`.
