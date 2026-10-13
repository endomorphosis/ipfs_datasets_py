# LegalIR temporal-presence adapter comparison, 2026-10-13

Two fixed source-only adapters completed 32 updates each from the split-feature parent. Both recover one exposed legacy case, reaching 95/96 whole-rule exact correctness with greedy and joint readout. Neither reaches the declared 96/96 retention gate; no candidate was selected or promoted.

| Exposed panel | Parent greedy/joint | CE greedy/joint | Margin greedy/joint |
|---|---:|---:|---:|
| Legacy 96 |94/94|95/95|95/95|
| Fresh tuning 36 |8/19|8/19|8/19|
| Challenge 36 |25/25|25/25|25/25|
| Earlier authored evaluation 72 |48/51|48/50|47/49|
| Authored development 72 |44/45|44/45|44/45|
| Authored evaluation 72 |26/32|26/32|26/32|

Both adapters preserve all 32 legacy permissions with zero permission-to-obligation/prohibition conversions or permission abstentions. The recovered case is `native-tuning-calendula-t6-q7-o`; its permission counterpart `native-tuning-calendula-t6-q7-p` still has a temporal false negative. Authored development and evaluation whole-rule results remain unchanged, while the earlier evaluation regresses. The margin objective supplies no measured advantage over the CE control in this comparison.

Final temporal-presence training classification is 168/168 for both candidates. This measures one binary output head, not whole-rule training accuracy. There was no initial 168-source training capture, so no training-accuracy gain is claimed. Each cell uses 168 distinct training examples, the same 384 training row occurrences, seed/order 1729, batch 12, fresh two-parameter Adam at 0.001, and 32 completed updates. No old optimizer moments were resumed.

The model has 36 tensors: 34 frozen parent tensors and a copied presence weight/bias pair. Only temporal rows train. Initial 392-source full-head scores match the parent; final 392-source modality, start/end and three non-temporal presence heads remain bit-identical. Source conditioning follows the existing two feature paths. The 384-dimensional placeholder is disabled: there are zero external encoder calls and no qualification of genuine 8D, 384D or 768D latent semantics.

The [immutable weight archive](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/0a89f3bfaa9db3ff028801b06fe6ee68ad73be19/releases/20261013-temporal-adapter-v1) contains 151 files and 80,118,257 bytes, including both checkpoints, all 90 frozen result files and 26 public runtime wrappers. All 4,344 prior Hub file identities and root attributes are preserved. Every new file was downloaded at the immutable revision and verified against its exact prepared bytes. Separate parent files were not copied; checkpoints retain embedded parent provenance. The versioned publisher repair is covered by a pre-SDK regression control; the original local failure made no network call.

The source trainer is `ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_span_temporal_adapter`. Its `build_checkpoint`, `train_decoder`, `SpanTemporalPresenceAdapterDecoder`, `save_checkpoint` and `load_checkpoint` interfaces require matching parent/data contracts. The 16 direct standard-library contract tests passed. Two real bounded training runs and independent saved-output/runtime recounts also passed their technical checks. The checked-in recipes retain experiment provenance paths; they are not a portable one-command training installation.

All 384 scored diagnostic references were previously exposed and share authored templates. Eight real-law sources remain unreviewed and unscored. No independently reviewed US Code fidelity, broad logic-family compatibility or `lake build legal` result is established here.

The next proposed comparison retains the frozen parent and tests mean pooling against learned temporal token attention, with a declared parameter/compute budget and fresh source/template-aware development partitions. Saved scores suggest contextual generalization concerns but cannot prove that frozen features are insufficient or exclude calibration. Do not choose a threshold or add an ID exception to rescue the known diagnostic row. The proposal in the evidence directory remains unexecuted. Independently reviewed statutory references, typed family-specific output validation and actual Lean compilation remain separate required qualifications.
