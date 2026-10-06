# Broader normative wording for decoder training

This experiment tests whether additional TRAIN wording improves modality reconstruction in the 384D and 768D formula decoders. It follows the source/recurrent diagnosis in `paraphrase_modality_diagnostics.md`: several exposed wording failures originated in the source head before recurrent logits were added. The earlier TRAIN bank was already classified perfectly, so increasing confidence on that bank did not establish broader generalization.

The new work preserves the existing numerical training owner and its original update stream. It adds an authenticated TRAIN-only modality auxiliary, separate native source preparation, a prospective wording panel, and a same-pass observer. The 8D linguistic teacher and 4096D lineage are untouched by this comparison. Native encoders remain frozen; this trains decoder heads, not encoder weights.

## Source and reference contracts

`normative_wording_training_sources.build` derives two renderings of each of the original 90 TRAIN rules. All actor, action, modality, object and qualifier fields retain their original provenance. The supported fixtures have empty qualifiers; nonempty qualifiers cause a refusal rather than simplification. A fixed seed packs 180 clauses into 48 paragraphs. Obligations, permissions and prohibitions each contribute 60 clauses, balanced across both wording templates.

The builder requires twelve historical source inventories. The preparation driver and auxiliary profile also require the separately sealed 60-source prospective development inventory; the builder checks that additional inventory when supplied. It refuses any literal or normalized paragraph/clause overlap. Complete paragraph and clause references live in different files from source-only native inputs. No new labels are obtained by asking the compiler to approve a wording.

`prospective_normative_development.build` produces 60 single-clause sources from 30 original DEV rule identities and two separately authored templates. The wording is sealed before fitting, excludes all TRAIN wording, and uses actor/action pairs disjoint from original TRAIN. Its original meanings have already been exposed in previous development runs. This is prospective wording development, not an untouched semantic holdout. No human semantic review or qualification is implied.

The separately published [cached contextual runtime](contextual_legal_reconstruction_runtime.md) restores original 384D/768D assets and reports semantic IR and source prose reconstruction separately. Its 48/48 original-cohort IR replay and 0/48 original prose equality are different observations from this broader-wording fit. This experiment keeps that implementation and its evidence intact, while using the authenticated historical training closure for numerical replay. No automatic registration of these new endpoints in the contextual runtime is implied.

## Owners and entrypoints

| Owner or script | Purpose |
| --- | --- |
| `logic/formalization/autoencoder/normative_wording_training_sources.py` | Balanced TRAIN wording, original-rule provenance, exclusions and complete targets |
| `logic/formalization/autoencoder/prospective_normative_development.py` | Separately sealed development wording and reference contract |
| `logic/formalization/autoencoder/prospective_wording_source_inputs.py` | Source-only native 60-row production using verified existing local encoder assets |
| `logic/formalization/autoencoder/normative_wording_modality_auxiliary.py` | Private rendering profile over the unchanged auxiliary loss/cache/training owners |
| `scripts/ops/autoencoder/prepare_normative_wording_sources.py` | Native TRAIN and development preparation with immediate output retention |
| `scripts/ops/autoencoder/benchmark_normative_wording_training.py` | Compatibility preflight, paired fits and exact zero replay |
| `scripts/ops/autoencoder/evaluate_normative_wording_development.py` | Reference-blind greedy generation, same-pass source traces and posthoc scoring |

Paths in the first four rows are relative to `ipfs_datasets_py/`. Public APIs import without running encoders or optimizers. The native adapter is specific to this closed 60-row experiment; it does not widen the older 48-row source contract.

## Fit and observation recipe

Each width runs a zero auxiliary control and a weight-0.05 auxiliary. Both restore the same selected parent and use seed 1729, learning rate 0.0001, the existing nonaction multiplier, batch 8, and four original curriculum stages. Each arm commits the same 170 original updates, 1,220 original row presentations and 112,920 valid target tokens. Six balanced auxiliary clauses are drawn per update, totaling 1,020 presentations. Targets and all 32 vocabulary entries remain unchanged. Existing original auxiliaries also remain unchanged.

The zero arm must reproduce the archived M2 zero arm exactly: initial, selected and final tensor digests, selection epoch, original batches and original numerical update evidence. Any mismatch is a failed comparison. Private module/function clones keep the new wording profile from changing package aliases or historical helper defaults.

After fitting, both selected and last-attempt endpoints generate all 60 development sources. If endpoints share tensors, they remain explicitly labeled aliases, not independent replications. The observer captures source, recurrent and combined full-vocabulary logits during the same greedy decode. It adds no second forward or model copy. Predictions and traces for all eight requested panels must be durably saved before the development reference JSON is parsed.

Posthoc scoring reports exact formulas, syntax, complete qualifier fidelity, teacher-forced token cross-entropy, four scalar field heads, and head/formula joins. Unvisited scalar sites remain counted with null correctness. Recurrent component argmax is not an independent formula decoder. Native input reconstruction MSE is not observed by this trace and is explicitly marked unmeasured.

## Local execution and provenance

The sealed run is `workspace/test-logs/decoder-normative-wording-r2-20261006`. Workspace evidence, development seals and independent audits are under `artifacts/autoencoder-wording-fit-20261006`. These numerical experiments deliberately use an authenticated historical S/M2 dependency closure. They are not a current pinned-tree compiler benchmark, and the editable HACC install is never used as an implicit substitute.

A fresh preparation binds local model assets and all producer sources. Verified local 384D and 768D encoders execute with batch 4, CPU float32, encoder context 512, no weight downloads and offline flags. TRAIN production returns 216 unique paragraph/clause source vectors; development adds 60. Reports and source inputs are saved immediately after each production phase, before any later comparison can fail. Composition64 sources are included in overlap exclusions, but their prior cached vectors are not compared because their saved input envelope differs. The receipt must retain this incomplete vector-comparison scope.

The reviewed `run_guardian.py` accepts phase, fresh attempt, optional width and an independently passed readiness report. It verifies artifact hashes and delegates admission, accounting, owned-lease monitoring and release to `run_reserved.py`. Run widths concurrently only after independent admission; do not reset the shared scheduler or delete foreign leases. Completed attempts and failed evidence remain immutable.

Example for a freshly sealed and reviewed width:

```bash
python3 workspace/test-logs/decoder-normative-wording-r2-20261006/run_guardian.py \
  --phase preflight --attempt preflight-384-r1 --dimension 384 \
  --review workspace/test-logs/decoder-normative-wording-r2-20261006/review/preflight-384-readiness.json
```

The recorded attempt above is already completed and must not be rerun under that name. A new experiment needs its own source/recipe freeze, fresh names and independently bound readiness. Source inputs, future reference bodies, checkpoint states and terminal receipts remain separately bound; missing cached vectors or labels must not be filled with deterministic test vectors.

## Qualification and metric scope

Temperature stays 0, encoder context and decoder output limit stay 512, prover evaluation is false, bridge names are empty, metric disk cache is disabled, and each owned width uses one CPU worker with CUDA disabled. Decoder fitting uses warm verified source-vector caches. Native preparation performs real local encoder forwards; its operating-system page-cache state is uncontrolled. These encoders differ in architecture, so a width comparison is not a dimension-only ablation.

Report native preparation, decoder training, greedy observation, posthoc scoring and guardian wall times separately. A bridge target count of zero cannot support a faster Legal-IR claim. Exact authored-formula reconstruction does not demonstrate arbitrary legal-text fidelity or global-minimum convergence.

No compiler, decompiler, logic-family projection, external prover or Lake build is run by this experiment. Only the applicable successful `lake build <Lib>` grants Lean admission. No Constitution span becomes formalized or `roundtrip_ok`, and no decoder checkpoint is automatically promoted.

## Completed comparison

The four fits and eight requested endpoint observations completed successfully. Selected and last-attempt tensors are identical for each arm; the table uses selected endpoints and does not treat the repeated alias observation as an independent replication.

| Width | Arm | TRAIN modality | New wording exact | Source modality | Token CE | Fit seconds | Greedy ms/span |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 384D | zero | 121/180 | 55/60 | 55/60 | 0.0083256300 | 40.385 | 3.1855 |
| 384D | 0.05 auxiliary | 180/180 | 60/60 | 60/60 | 0.0025041777 | 40.865 | 3.2234 |
| 768D | zero | 164/180 | 60/60 | 60/60 | 0.0015389897 | 50.369 | 4.4134 |
| 768D | 0.05 auxiliary | 180/180 | 60/60 | 60/60 | 0.0015766217 | 49.578 | 4.4010 |

At 384D the auxiliary fixes five complete formula outputs, with no new error on this panel, and reduces teacher-forced token CE by 69.92%. All five corrections are obligations in the separately authored “bears a duty” template. At 768D the control is already exact on all 60 sources; the auxiliary increases token CE by 2.45%. Actor, action and object fields are correct on all 60 sources in every panel. All generated documents reach EOS and pass the restricted scalar schema syntax check.

For example, `The registrar bears a duty to preserve the archive.` previously decoded as permission (`P`); the new 384D arm emits the following complete authored-rule IR:

```json
{
  "rules": [
    {
      "actor": "registrar",
      "action": "preserve",
      "modality": "O",
      "object": "archive",
      "conditions": [],
      "exceptions": [],
      "temporal": []
    }
  ]
}
```

This is the actual generated scalar-rule representation, with `O` denoting obligation. It is not generated Lean code, a general logic-family projection or a theorem certificate.

Original development formula exactness remains 48/48 for every arm. Its token CE is slightly worse with the auxiliary: +0.0000108385 at 384D and +0.0000049118 at 768D. The new wording result supports a specific 384D generalization gain, not uniform improvement across widths. No checkpoint is promoted.

Native preparation generated 276 verified source vectors per width. TRAIN/DEV encoder wall times were 7.542/1.244 seconds at 384D and 31.092/6.022 seconds at 768D, or 0.0318/0.1345 seconds per unique source across those forwards. The preparation driver took 66.424 seconds and guardian took 108.322 seconds.

Parallel width drivers took 154.457 seconds at 384D and 207.542 seconds at 768D, including compatibility, fit, original control evaluation and saved evidence. Their guardians took 236.424/265.616 seconds. The new-wording observation driver took 28.598 seconds; guardian took 64.891 seconds. Selected-panel greedy time is 0.0032 seconds/span at 384D and 0.0044 seconds/span at 768D; posthoc scoring and resource accounting are additional costs. Original row throughput during the fit call is about 30/s at 384D and 24/s at 768D. Tiny paired timing differences under host sharing are not a measured speedup.

The complete results and immutable archive manifest are under `docs/implementation/reports/evidence/decoder-normative-wording-20261006/`. Final tests cover 297 distinct pure contracts, native source/asset/context joins, exact zero numerical/tensor replay, nine original controls and same-pass full-vocabulary observations.

The next experiment should test exposed v3 wording retention and a separately sealed richer source panel before considering promotion. Preserve complete nonempty qualifiers and the original source/semantic review requirements; this 32-token empty-qualifier grammar cannot establish those capabilities. Reuse verified native caches and original update bindings, and profile validation/copy/accounting overhead before modifying the numerical training owner.
