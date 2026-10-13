# LegalIR actor ranking experiment — 2026-10-13

This opt-in span-pointer adapter completed 32 updates using actor cross-entropy plus the existing compatible-span hinge (coefficient 0.25, margin 1). It produced **no complete-IR accuracy gain over the frozen CE experiment**. The weights are archived as a reproducible experiment; no decoder is promoted to the default.

| Exposed authored measure | Frozen CE | CE + hinge |
|---|---:|---:|
| Training complete IR, raw and joint | 153/168 | 153/168 |
| Training joint actor exact | 155/168 | 155/168 |
| Training gold actor top1 | 156/168 | 156/168 |
| Training gold actor top8 | 168/168 | 168/168 |
| Training actor rank sum, lower is better | 206 | 208 |
| Training filtered hinge mean | 0.2569550673 | 0.2554120279 |
| Authored evaluation complete joint IR | 33/72 | 33/72 |
| Authored evaluation actor top1 | 64/72 | 63/72 |
| Older authored evaluation complete joint IR | 51/72 | 51/72 |
| Legacy complete IR | 94/96 | 94/96 |
| Fresh development complete joint IR | 0/36 | 0/36 |
| Fresh test complete joint IR | 0/36 | 0/36 |

Complete IR compares modality, actor, action, object, conditions, exceptions and temporal fields. Across nine paired authored populations, both raw and joint complete-IR gains and losses against CE are zero. Actor ranks worsen on two training IDs, and one authored evaluation gold actor leaves top1. The filtered hinge penalty improves slightly on training while rank results remain mixed.

## Model and training

`SpanActorRankingAdapterDecoder` is implemented in `source/legal_span_actor_ranking.py`. The original 34 split-feature tensors remain frozen. Four full six-row start/end copies preserve the parent's projection geometry; actor row 0 supplies 130 active scalars. The other 650 copied scalars retain their values, zero gradients and zero Adam moments.

Both experiments start from the same N4 checkpoint, raw SHA256 `95bd50a7cc6e25381ad126e3d955f0816c31470ec469fb22ceca297e35115035`. The candidate starts with fresh Adam: learning rate 0.001, betas 0.9/0.999, epsilon 1e-8, no weight decay, gradient clip 5, seed and order seed 1729, batch size 12. Its 32 updates use 384 occurrences of the same 168 training rows. The frozen CE control requires zero new updates or forwards. Equal FLOPs are not claimed.

The hinge enumerates valid source-token spans in row-major order, excluding exact gold actor and spans overlapping present gold nonactor facets. It reuses the existing stable argmax, float32 score arithmetic and batch denominator. Only 30 of 384 completed training occurrences activate this term; none has an empty negative domain.

The checkpoint is `cells/actor-ranking-hinge/results/cell-checkpoint.json`, 6,454,161 bytes, SHA256 `782b107b6b46a0294e2ea247b62074fad684048be5486d79ca9d61a6fb0f9101`.

## Validation and scope

All 18 detached trainer contracts pass. The actual 632-source initial full-head parity and final protected-head retention gates pass. All 632 actor vectors change; original modality, presence and nonactor score vectors stay bit-exact. The independent stdlib recount agrees with the analyzer on 33 panel summaries, 30 authored score sets, both nine-panel comparisons, complete seven-field IR, actor ranks/topK, and filtered-domain hinge/margin diagnostics.

There are 62 frozen outputs totaling 61,920,577 bytes. The run records 1,520 inference forwards plus 32 training batch forwards, 384 training occurrences and 1,904 total source occurrences. The owned resource claim is released, all 535 prior records are unchanged, and the terminal ledger has 536 records. Historical proof-refusal metadata and normal foreign scheduler occupancy are supported by local wrappers; capacity settings and original admission guards remain unchanged.

All scored references are previously exposed authored engineering examples. Eight statutory examples remain unscored. Configured 384D vectors are dormant API placeholders, latent conditioning is disabled, and external encoder calls are zero. Independent US Code semantic fidelity, broader logic-family compliance, `lake build legal`, and genuine 8D/384D/768D latent semantics remain separate qualification tasks.

## Remaining work

All 15 training complete-IR failures remain: five selected actor-only failures, six modality-plus-actor failures, one actor/object/exceptions failure, two conditions failures and one abstention. All training gold actors are already in top8. Fresh full gold assignments remain outside the retained domain on both 36-row panels.

The next proposed experiment combines the earlier temporal attention design's feature adaptation with the copied actor boundary head. Modality, optional presence and broader candidate coverage need separate measured corrections. These proposals have not run in this release.

See `evidence/public-result-summary-v01.json`, `evidence/result-independent-review-v01.json`, `evidence/next-experiment-gaps-v01.json`, and the versioned recipes. Matching retained source owners are included under `source/datasets/`. The shared N4 parent is already archived under `releases/20261013-split-feature-v1`; this checkpoint contains its inherited state.

## Archive and implementation

[Immutable weights and evidence](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/3c430bdb412a6bd0871f813a944dfec5b2f4c8e9/releases/20261013-actor-ranking-v1) contain 165 additions totaling 84,502,852 bytes; all 4,766 earlier Hub file identities are preserved.

[Decoder implementation](../../ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_actor_ranking.py), [independent result review](../implementation/reports/evidence/legal-actor-ranking-20261013-01/result-independent-review-v01.json), [public result summary](../implementation/reports/evidence/legal-actor-ranking-20261013-01/public-result-summary-v01.json), and [next measured gaps](../implementation/reports/evidence/legal-actor-ranking-20261013-01/next-experiment-gaps-v01.json) retain the experiment. The measured recipes retain workspace paths and pinned dependencies; reruns require reconstructing that layout or a reviewed adaptation.
