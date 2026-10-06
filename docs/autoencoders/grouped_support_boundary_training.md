# Matched grouped support-boundary continuation

The source-only grouped v2 head now has a bounded continuation study targeting a specific data gap: original negatives removed all modal heads, while partially malformed sources can retain the other modal heads. Both arms restore the same published model and full Adam state, execute 200 additional updates with identical positive batches and learning rate 0.0005, and retain the fixed support gate at 0.5. The targeted arm replaces four of eight negative rows per batch with one-clause modal deletion or misspelling. No architecture, original checkpoint, source-pinned producer, default runtime or 8D/384D/768D model is changed.

| Fresh final authored cases | Original-negative control | Position-local negatives |
| --- | ---: | ---: |
| Exact positive requests | 56/64 | 55/64 |
| Learned unsupported-profile refusals | 21/64 | 54/64 |
| Incidental validation blocks on negatives | 20/64 | 3/64 |
| Unsupported requests emitted | 23/64 | 7/64 |
| Exact positive or learned refusal | 77/128 (60.2%) | 109/128 (85.2%) |

This is a substantial refusal improvement with one fewer exact positive than the control; seven unsupported requests remain. All remaining emissions are in the misspelling slice. Selection chooses the control at 100 additional updates and the targeted arm at 200; both recipes completed 200. These are one-seed recipe results, not a claim about architecture or dimensionality. Each evaluation split has 38 correlated source-parent groups. Sources and actor/action lexemes are distinct from the parent corpus and between new selection/final splits; target creation and the recipe were fixed before fitting, and both selected checkpoints were durable before final references were parsed. This final panel is now exposed.

On the old exposed selection/final regression, the targeted checkpoint retains all 128 positive requests and learned-refuses all 128 unsupported cases. The control retains all 128 positives and learned-refuses 124/128. All fourteen probes of seven previously exposed official paragraphs still refuse. No real-law formalization coverage or independently reviewed legal accuracy is demonstrated. Unsupported labels mean outside this narrow repeated-modal profile, not legally false text.

The [immutable experimental release](https://huggingface.co/Publicus/legal-ir-autoencoder/tree/27667843f4a6cfda36f4763b27d08a080cad9fd3/experiments/grouped-boundary-20261006/run-01) includes both selected model/Adam checkpoints, actual losses, presentation schedule, sealed references, every fresh prediction and source snapshots. The targeted SHA256 is `0174d11019a0a4eb894337f7f3d79a9dec7a2e11b0e406832d27312cee05daba`. It loads through the existing explicit `legal_ir:source_conditioned_grouped_v2` reader using the exact local checkpoint digest. All four checkpoint-bound producers retain their bytes. This remains CPU float32/Torch 2.13.0+cu130, raw source text plus explicit caller scope, deontic FOL only.

All 571 combined interface tests pass without skips. A separate process restores exact state and reproduces all 256 fresh predictions. Actual `lake build legal` accepts an eight-member scope witness from generated selection outputs and rejects the deliberately false narrow-scope claim. Those checks establish reproducibility and constructed native structure, not a statute's meaning or proof authority for every prediction. See the [compact evidence](../implementation/reports/evidence/grouped-support-boundary-20261006/summary.json).

## Preserve qualifiers before fitting them

`logic/formalization/autoencoder/legal_scope_span_proposal.py` adds `propose_scope_from_spans(source_text, prediction, expected_source_sha256=...)`. It transports one declared O/P/F rule with explicit modality/actor/action and nullable object/condition occurrence coordinates into the existing `canonical-normative-scope-declaration/v1`. It copies opaque terms and caller-declared rule-versus-statement attachment, validates exact Unicode character anchors, external source bytes, token boundaries and nonoverlap, and never obtains endpoints from a parser or target. Equal text at different coordinates retains distinct occurrence identity.

Prediction fields are closed: `schema=legal-scope-span-prediction/v1`, `interpretation_profile=opaque_condition_attachment/v1`, `modality`, `spans={modality,actor,action,object,condition}` and `condition_attachment`. An occurrence is an explicit half-open `[start,end]` character pair; object and condition can be `None`. A condition requires explicit `rule` or `statement` attachment. No condition requires `None` attachment.

This adapter is untrained proposal transport. The current grouped v2 head cannot supply its extra modality/object/condition endpoints. It emits no formula/AST/Lean, does not interpret an opaque condition as material implication, and leaves all five admission masks zero. Source coverage is unassessed, context is unavailable and the full source retains a review-required marker. Modal class and attachment can be wrong even when their transport is valid; they receive no semantic qualification. Broad families, shared/nested qualifiers, explicit quantifier/binder meaning and reviewed source targets remain further work.

The fresh Dataset Viewer audit observes 372 `formal_logic_text` rows, all marked `training_qualified=false`, `independent_validation=false`, `admitted=false` and `producer_origin=source_bridge_target`. The open-US-law default view is a 51-jurisdiction census. These observations were not used as reviewed semantic gold. Future qualifier training should reuse the existing statement-scope, review-intake and lane/contrastive owners with separately qualified occurrence targets.
