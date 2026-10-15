**F17 joint readout retention — completed training, failed scientific acceptance (2026-10-14).**

F17 implements `SpanJointReadoutRetentionAdapterDecoder`, an experimental decoder initialized from the exact F15 parent. Jointly updating actor, modality, conditions boundaries and exception presence improved several component and panel counts, but complete training IR remained **154/168 on both routes**, below the preregistered minimum of 155. Two exposed-panel regressions also violate the loss-ID vetoes. Technical validation passed; scientific success and default promotion are **false**.

The model selects 14 optimizer tensors with 713 active scalars and freezes 28 tensors. It combines inherited supervised losses, an actor ranking hinge and masked KL retention of correct F15 teacher components on the fixed 168 training sources. The retention masks use training labels only. Correct teacher components receive a soft loss; this is not a guarantee that every decoded rule will survive optimization. Nine detached contract tests pass; the default decoder is unchanged.

The table compares F15 with trained F17. Complete IR requires modality and all six roles to match; an abstention is a nonmatch. “Raw” is the direct decoded route; “joint” uses the existing joint selector. These are previously exposed authored engineering diagnostics.

| Scope | Rows | Raw complete IR | Joint complete IR |
| --- | ---: | ---: | ---: |
| training168 | 168 | 154 → 154 | 154 → 154 |
| old_tune | 96 | 94 → 93 | 94 → 93 |
| fresh_tune | 36 | 8 → 9 | 19 → 21 |
| fresh_challenge | 36 | 25 → 26 | 25 → 26 |
| old_authored_eval | 72 | 50 → 52 | 53 → 55 |
| authored_dev | 72 | 45 → 47 | 46 → 48 |
| authored_eval | 72 | 27 → 27 | 34 → 33 |
| fresh_dev | 36 | 0 → 0 | 0 → 0 |
| fresh_test | 36 | 0 → 0 | 0 → 0 |

Training actor exactness improved 156 → 158 on both routes. Raw decoded modality improved 161 → 162; joint modality and the modality head winner improved 162 → 163. These improvements did not create any complete training-IR gain. All 32 protected permission modalities remain correct without abstention, but that does not mean all 32 full rules were retained.

The old-tune actor regression is `native-tuning-calendula-t4-q5-p`, lost on both routes relative to F15 and N11 and already incorrect in frozen F16. A new joint loss, `targeted-loss-authored_eval-condition_exception_duration-0-f-present`, changes exception presence from true positive to false negative. It is a complete-IR loss against all three frozen comparators. Protected exception boundary scores cannot recover an exception removed by the presence decision. Training-only KL does not constrain this exposed evaluation row. Gains elsewhere do not cancel either veto.

One qualified training attempt completed 32 experimental updates. Its separate synthetic gradient fixture used one forward, two synthetic source occurrences and one optimizer step; totals are 1,313 forwards, 1,666 source occurrences and 33 steps. Initial parity and final protected-output checks cover 632 sources. The freeze contains 62 files totaling 80,818,125 bytes. Primary analysis and a separate recount agree across 50 panels, 45 scored sets and 27 paired groups. Shared structural helpers limit their independence; neither replays numerical gradients.

The 20,467,217-byte checkpoint has SHA256 `d38f6481f8cdb35d996d5231d15331855043f20a258180b0af9b1143d477d42e`. The qualified publisher completed with return code 0 and reports all 229 forced raw downloads exact: 94,548,368 payload bytes across nine chunks at [immutable HF revision 290c266](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/290c266d72b8c298ec21db0f9b0857b008914caf/releases/20261014-joint-readout-retention-v1). Its report has 6,076 final paths, preserving all 5,847 old paths and 5,846 old identities; the sole prior-file change is the declared 146-byte checkpoint-specific `.gitattributes` appendix. Payload publication is additive; the overall protocol is not additions-only. Independent publication review confirms the immutable metadata and all 229 byte-exact downloads.

Resource closure preserves all 543 opening record IDs: 541 bodies exact and two observed release transitions; 539 original F16 bodies remain exact. The owned claim is released and its lease absent; no foreign release is approved. Safely deleting one redundant counted archive duplicate reclaimed 149,504,694 apparent bytes with recovery retained. After a retained `-S`/`multiformats` failure, one checked CID wrapper invoked unchanged freezer v4, preserving all 62 hashes without numerical/model calls or retraining.

Latent conditioning was disabled with a 384D placeholder and zero external encoder calls. This run qualifies no active 8D/384D/768D comparison, independently reviewed US Code semantics, new logic family, fresh `lake build legal`, or portable numerical reload. All eight statutory items remain unscored.

A proposed next experiment starts again from exact F15, freezing actor and every presence state, and trains only six modality/conditions tensors with 325 active scalars. It would use a training-only mask for two conditions-only errors. “154 + 2 = 156” is conditional on repairing both while every other field stays correct; it is not a joint ceiling, feasibility proof or result. No additional training has occurred.

The [inference and qualification guide](../autoencoders/inference_and_qualification.md) preserves other agents’ separate grouped-head v1/v2 work, including v2 ordered-byte and learned-support objectives. F17 tests single-rule actor/modality readouts and complements that work; it merges no checkpoints and retrains no grouped model. The grouped work does not establish active 8D/384D/768D conditioning for this experiment.

Evidence: [public summary](https://huggingface.co/Publicus/legal-ir-autoencoder/blob/290c266d72b8c298ec21db0f9b0857b008914caf/releases/20261014-joint-readout-retention-v1/evidence/public-result-summary-v01.json), [independent result review](https://huggingface.co/Publicus/legal-ir-autoencoder/blob/290c266d72b8c298ec21db0f9b0857b008914caf/releases/20261014-joint-readout-retention-v1/evidence/joint-readout-retention-result-independent-review-v01.json). Source integration is tracked in [PR1305](https://github.com/endomorphosis/ipfs_datasets_py/pull/1305).
