# Learned legal formula smoke — 2026-09-30

The new `source_conditioned_formula_v1` GRU learned source-to-formula reconstruction on a small authored fixture: **11/12 held-out formulas matched exactly**, with one dropped exception. This demonstrates bounded learned generation; it does not establish federal-law coverage or semantic qualification. The legacy 8D and current 384D checkpoints were not used or modified.

See the [training guide](learned_legal_formula_training.md), [full receipt and predictions](../implementation/reports/evidence/legal-lineages-20260930/learned-formula-smoke.json), and [authored fixture](../../tests/fixtures/legal_formula_learning/v1.json).

Installed validation passed 312 regression tests and a final 13-case registry
suite after adding two integrity checks. All 23 frozen legacy
modules still match their manifest. See the [integration receipt](../implementation/reports/evidence/legal-lineages-20260930/learned-formula-integration-validation.json).
The [installed CLI receipt](../implementation/reports/evidence/legal-lineages-20260930/learned-formula-cli-smoke.json)
records fresh training, exact-parent resume from 9 to 18 optimizer updates, and
source-only inference matching all three familiar gate examples.

## Measured run

One fixed seed (`1729`), one CPU thread and one interop thread, 100 epochs, 900 Adam updates, learning rate `0.008`, batch size 8. The 120-second limit was a soft batch deadline. Training took **25.2722 seconds**; the complete diagnostic, including ablations and persistence checks, took **28.9120 seconds**.

| Measurement | Result |
|---|---:|
| Training teacher-forced token cross-entropy, before → after | 3.334710664 → 0.0000904768 |
| Tuning teacher-forced token cross-entropy | 0.0000937078 |
| Training exact full-rule matches | 72/72 |
| Tuning exact full-rule matches | 12/12 |
| Held-out exact full-rule matches | 11/12 |
| Previously familiar gate sentences, reported separately | 3/3 |
| Out-of-vocabulary probes | 4/4 abstained |
| Maximum output-head gradient norm | 0.5515373 |
| Held-out inference, 12 source strings | 54.5844 ms; 4.5487 ms/span |
| Model load preceding that inference | 109.1061 ms |

Every held-out row remains in the denominator. Training, tuning and held-out sources and complete target IRs are disjoint; held-out words and atoms occur in training. The three familiar gates do not count as held-out evidence. Configuration was fixed before held-out evaluation; no held-out tuning or hyperparameter sweep was performed. Inference received only source strings, with no teacher forcing or target access.

The codec used 27 source tokens and 28 target tokens in its vocabularies. Observed sequence lengths were at most 14 source tokens and 18 target tokens. Both limits remained **64**, and temperature remained **0**. Targets cover one canonical deontic rule with seven fields; arbitrary legal language and the other logic families were not qualified by this run.

## Preserved semantic failure

Source, case `officer-retain-o-composed-exception`:

> The officer shall retain the file for at least 20 days unless emergency.

Expected:

```json
{"rules":[{"modality":"O","actor":"officer","action":"retain","object":"the file","conditions":[],"exceptions":["emergency"],"temporal":["at least 20 days"]}]}
```

Actual learned output:

```json
{"rules":[{"modality":"O","actor":"officer","action":"retain","object":"the file","conditions":[],"exceptions":[],"temporal":["at least 20 days"]}]}
```

The output satisfies the structural grammar but omits the exception. Its low training loss and successful syntax check do not repair that semantic error. The receipt retains the incorrect prediction unchanged.

## Ablations and persistence

| Held-out arm | Exact matches | Interpretation |
|---|---:|---|
| Same initialization, no updates | 0/12 | All 12 generated structurally valid candidates. |
| Zeroed source embedding and encoder | 0/12 | Removes source conditioning while retaining the trained decoder. |
| Cyclically permuted sources | 0/12 | Predictions are scored against the original, unpermuted targets; there are no fixed points. |
| Zeroed output head | 0/12 | All 12 abstained through the explicit zero-head guard; an integrity check, not independent evidence of learning. |

Replacing external evaluation targets with invalid targets left predictions identical. Passing target-bearing dictionaries into inference was rejected. Parser, compiler and decompiler entry points were patched to raise during inference; no calls occurred. These checks support source-conditioned model generation, but one seeded synthetic run cannot establish broad generalization.

Checkpoint save/load preserved every value and all held-out predictions. A one-epoch resume preserved the exact parent digest and advanced progress from 900 to 909 updates (100 to 101 completed epochs). Resume was a persistence check, not another held-out model-selection trial. Both JSON checkpoints remain local under `workspace/learned-formula-staging/smoke-final-20260930/`:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `checkpoint.json` | 2,826,559 | `4876186f4a5fe3957640a2cff1a4e1b2046bc945d24e08d244973e641733384e` |
| `resumed-checkpoint.json` | 2,826,963 | `4c0619888a39ab98403a5ea2f65f530277a594a4bbafe7c102da4013e6ddef9f` |

## Source provenance and limits

The run loaded the staged learner and codec with canonical workspace dependencies. The compiler, decompiler and parser tree pin resolved to `/home/barberb/lift_coding/external/ipfs_datasets`; no HACC substitution occurred. The checkpoint records these listed-file hashes:

| Source | SHA-256 |
|---|---|
| `legal_formula_learning.py` | `bb5fad7e1410149be8e9fe649c5825ccff931ed2ab89c840c70c141b96c6a425` |
| `legal_formula_codec.py` | `f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290` |
| `canonical_contracts.py` | `d66ecfaa2c967cda40a1cf4b82936a34039e38ccdb3044468697a4f90af2844b` |
| `legal_ir_grammar_decoder.py` | `0b1eae24b00157ae74a2700f23ca95c7f9957dc755078caaf179e64070fdeffd` |
| `tree_pin.py` | `587165942fb06ea9effc836b555e0ac0606c5876b013a374a1e76d25ee069e4d` |

Fixture SHA-256: `89eaedf4e8fb3532e7f4affb7e833d3fba27cd60e623db3b35c15c46e9e057a2`. Full receipt SHA-256: `f3b8037647b60368ca4acc1897e925a418ca2e0f8bbd5185475031d87603fbe1`.

This was **not a bridge-on evaluate**: bridge names were empty, `legal_ir_target_count=0`, external provers were off, and no metric disk cache was used. The inference timing above measures only this source-to-formula head. No weights were downloaded, no provider was called, and no Lake build ran. `admitted`, `qualified`, `formalized`, `roundtrip_ok` and proof authority remain false. These authored examples are neither US Code nor Constitution formalization evidence.
