# Normative decoder retention after the October 6 fits

The four selected endpoints from [paired normative training](normative_wording_training.md) were observed on the earlier exposed-v3 development panel before further fitting. The 384D auxiliary arm reconstructs 31/48 paragraphs exactly versus its zero control's 20/48; the 768D auxiliary arm reconstructs 48/48 versus 46/48. Full-vocabulary teacher-forced token loss decreases on this panel for both widths. These are retained-development observations; the meanings and this panel were previously exposed.

| Width | Zero exact paragraphs | Auxiliary exact paragraphs | Zero token CE | Auxiliary token CE | CE reduction |
| --- | --- | --- | --- | --- | --- |
| 384D | 20/48 | 31/48 | 0.030589255162 | 0.010824199515 | 64.61% |
| 768D | 46/48 | 48/48 | 0.003361466448 | 0.001863383598 | 44.57% |

All four panels emit 180 valid rules in 48 syntactically valid documents and reach EOS on all 48 rows. Evaluation retains every ordered rule, all seven facets and 720 reference scalar sites per panel. Conditions, exceptions and temporal fields are empty on this cohort; their exact scores do not demonstrate nonempty qualifier coverage. The 384D auxiliary arm still has 21 incorrect generated modality values and one incorrect action, counted as 22 whole-rule substitutions. The 768D auxiliary arm is exact on all 180 rules in this particular cohort.

## What the source-head trace adds

One greedy rollout per state retains the full 32-value source, recurrent and combined logits at actually visited scalar sites. There is no second greedy rollout, syntax mask, forced closure, copied model or reference prefix. All four traces and predictions were durable before v3 reference loading. Both new zero controls exactly reproduce their archived M2 token sequences, statuses and EOS outcomes. Selected/last-state aliases within an arm are not separate replications.

The 384D modality source-head argmax improves from 139/180 to 161/180, while generated modality exactness improves from 139/180 to 159/180. Two sites have a correct source-head argmax and an incorrect generated modality. This identifies a small source/combined-readout diagnostic for a later controlled experiment; it does not isolate a causal recurrent effect or justify forcing source predictions. Actor/object fields remain 180/180 and action 179/180. The 768D auxiliary source head and generated fields are all correct on this panel. All 720 sites are visited and available in each panel; unavailable/unvisited sites remain null by contract, and extra sites would remain counted.

One actual generated IR row from the 768D auxiliary arm, retained under source ID `fresh-modality-v3:fc5e287da9b1bef21f873f5a6972bfb9378b2bafefcd77d095f035a2d4502c09`, is:

Source: “The trustee is obligated to preserve the archive.”

```json
{"rules":[{"action":"preserve","actor":"trustee","conditions":[],"exceptions":[],"modality":"O","object":"archive","temporal":[]}]}
```

This is the learned decoder's structured output, scored after generation. The source sentence is evaluation provenance; it is not supplied to the formula codec as a fallback. No native-family or Lean admission is implied by this row.

## Timing, source and resource boundaries

The numerical driver takes 28.500 seconds; the owned reserved wrapper takes 64.370 seconds, and the outer guardian takes 66.364 seconds. The launch-to-reap interval is 34.731 seconds and includes monitoring/accounting. The auxiliary greedy rollout takes 0.50549 seconds for 48 cached 384D paragraphs (10.531 ms/paragraph), and 0.66196 seconds for 48 cached 768D paragraphs (13.791 ms/paragraph). These rollout scopes exclude setup, posthoc scoring, encoder execution and compiler/prover/Lake work. They are not end-to-end legal-IR inference or bridge-on evaluate timings.

The run uses one CPU worker, batch eight, CUDA disabled, verified warm source-vector caches, bridge names `[]`, prover evaluation false and metric disk cache false. Temperature is 0 and both declared context and output limits stay 512. The numerical owners are the explicitly frozen historical S/M2/E experiment trees, not a measurement of the current pinned compiler. No encoder forward, training step, new weights download, Hub transfer or Lake build occurs.

The 100 MB storage/1536 MiB reservation records 14,567,512 bytes at its finalization census and maximum sampled RSS 784,658,432 bytes. The terminal directory totals 14,573,363 bytes; the extra 5,851 bytes are the subsequently written final resource receipt. The child exits 0 and is reaped; the owned process group has no live members at finalization. The own lease is released and the shared configuration remains unchanged. Sampled lease observations do not assert continuous coverage: finalization has a separate observation gap after monitoring stops. The released lease’s terminal `cancelled: true` reflects the scheduler’s missing-lease lookup policy; all 37 present-lease samples had `cancelled: false`. No foreign scheduler or lease state is reset.

## How this joins the other agents' work

The [progress reconciliation](progress_reconciliation_20261006.md) pins the earlier branch/working-copy review. During publication, PR1271 (`0f36163a585a9bf514c41d8eabe202936c000705`) also merged learned grouped v1/v2 raw-source heads and an explicit opt-in grouped v2 runtime. Those heads do not condition on the 8D/384D/768D native vectors and do not replace the linguistic 8D teacher or this four-state experiment. Their correlated/exposed synthetic cohorts, restricted output grammar and separately scoped Lake witness require their own evidence. A passing witness does not grant source-semantic/proof authority to their generated spans.

The follow-up canonical review found 15 published PR1271 files absent locally and the opt-in runtime absent from an older registry owner. Those 15 exact main files are now restored, and the registry advances from its exact published base to the exact PR1271 main body with retained preimage and unchanged Git HEAD/index. Eleven targeted API cases pass for profile discovery, wrong domain/version rejection and malformed JSON refusal. Those cases open no model and execute no native renderer or Lake; full model/phase-one suites were not rerun. Existing local span-boundary changes and our interface test refinements are preserved. The experimental grouped runtime is available by explicit profile and authenticated local checkpoint, with no default activation or qualification.

The new retention result complements the distinct sealed-wording result: 384D improved 55→60/60 there, whereas 768D stayed 60/60 and its CE worsened slightly. Width-specific and cohort-specific behavior must be retained. This observation performs no checkpoint selection or promotion. Fresh reviewed source/formal pairs, complete nonempty qualifier support and applicable modality/family checks remain prerequisites for stronger claims. The 8D linguistic teacher, 4096D lineage and pinned restart12 checkpoint remain unchanged. Convergence to a global minimum is not established.

The companion evidence under `docs/autoencoders/evidence/normative-wording-retention-20261006/` binds the actual summary, four tensors, predictions, traces and independent numerical/resource reviews. The workspace `artifacts/autoencoder-retention-integration-20261006/` retains the complete bounded output archive and publication evidence. Only an applicable actual `lake build <Lib>` grants Lean admission. All semantic/proof/admission/promotion masks for this retention observation are false. The Constitution remains unformalized; no Constitution span is marked `roundtrip_ok`.
