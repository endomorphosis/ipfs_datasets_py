# Intent and UI candidate fidelity, training and projection coverage

The additive Intent/UI pipeline keeps a model's generated candidate intact,
audits it after inference, and records exactly which native projections the
candidate supports. The new UI adapter preserves the existing frame target and
adds parsed first-order declarations for explicitly supplied component fields.
Neither a source hash, a schema-valid candidate, nor agreement with a bounded
source grammar establishes natural-language truth or complete qualification.

This work reuses the existing fixed-schema 384D structured decoder as a separate
alternative to the autoregressive GRU decoder. Its ridge fitting path reuses
one factorization across regularization candidates and scalar classes. It keeps
the existing checkpoint format and inference runtime. The 8D linguistic lineage,
existing 384D GRU checkpoints, parent weights, and older source contracts are
unchanged.

Related guides: [generated-output GRU fidelity](source384_fidelity_training_v2.md),
[complete structural features](complete_features_and_ui_fidelity.md),
[family routing and refinement](family_routing_and_refinement.md), and
[native semantic projections](native_semantic_projections_v3.md).

## Public entry points

The paths below are under `ipfs_datasets_py.logic.formalization.autoencoder`.

| Module and API | Responsibility |
| --- | --- |
| [structured_source_ridge_path_384.py](../../ipfs_datasets_py/logic/formalization/autoencoder/structured_source_ridge_path_384.py): `train(domain, training_rows, validation_rows, *, parent_projection, config=None)` | Fit the existing structured decoder using a shared eigendecomposition |
| Same module: `train_grouped_source_decoder_384(...)` | Apply explicit leakage-group checks before fitting the same head |
| [structured_source_384.py](../../ipfs_datasets_py/logic/formalization/autoencoder/structured_source_384.py): `Runtime(checkpoint)`, `load_checkpoint(path, *, expected_sha256, expected_domain)` | Read the unchanged structured checkpoint format |
| Same module: `runtime.infer(rows, *, weight_ablation=None)`, `evaluate(checkpoint, rows, *, weight_ablation=None)` | Generate from embeddings; evaluate against separate reference rows |
| [intent_candidate_fidelity.py](../../ipfs_datasets_py/logic/formalization/autoencoder/intent_candidate_fidelity.py): `audit_intent_candidate(source_text, candidate)` | Diagnose complete typed Intent disagreement after generation |
| [ui_source_contract_384_v2.py](../../ipfs_datasets_py/logic/formalization/autoencoder/ui_source_contract_384_v2.py): `prepare_family_targets(source_text, target, requested_families=None)` | Return a v7 family report, typed replay inputs, and a JSON coverage audit |
| Same module: `qualify_source_candidate(...)`, `validate_prepared(prepared, source_text, target)` | Obtain a JSON-only audit or replay its exact source/candidate/symbol binding |
| [intent_ui_candidate_pipeline.py](../../ipfs_datasets_py/logic/formalization/autoencoder/intent_ui_candidate_pipeline.py): `infer_and_audit(runtime, rows, *, requested_families=None, **inference_options)` | Finish target-free inference, then attach source/coverage diagnostics |
| Same module: `audit_candidates(report, source_rows, *, requested_families=None)` | Audit an already generated 384D report without rerunning the model |
| [native_family_lake_v5.py](../../ipfs_datasets_py/logic/formalization/autoencoder/native_family_lake_v5.py): `build_native_family_lake(...)` | Replay original typed inputs and run an actual modality-specific Lake build |

The new candidate pipeline is opt-in. It does not silently change older
`complete_training` or checkpoint-pinned inference APIs. Its current domains
are `intent_ir` and `ui_ux_ir`; a different domain needs its own semantic owner.

## Training the structured head

Each ordinary training or tuning row contains exactly `id`, `source_text`,
`embedding`, and `target`. Embeddings must be genuine 384D vectors from the
verified local semantic encoder. Inference rows omit `target`. Source text is
retained for provenance and later checks; it is not passed to the numerical
head as a second learned input.

The parent must be a trained 384D `modal_latent_formula` Legal checkpoint with
completed optimizer steps. Supply the parent object or its exact local
`{"path", "sha256"}` descriptor. The structured head inherits and freezes its
projection tensors, applies training-only normalization, and learns scalar
class scores. It does not resume a GRU optimizer, update the parent encoder, or
train embedding reconstruction.

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    structured_source_ridge_path_384 as fitting,
    structured_source_384 as readout,
)

# These rows and embedding provenance come from verified local preparation.
result = fitting.train(
    "ui_ux_ir", training_rows, tuning_rows,
    parent_projection={"path": str(local_parent_path), "sha256": parent_sha256},
    config={
        "ridges": [0.0001, 0.001, 0.01, 0.1],
        "embedding_provenance": verified_embedding_provenance,
    },
)
reader = readout.Runtime(result["checkpoint"])
generated = reader.infer(inference_rows)  # id, source_text, embedding only
```

Save the returned checkpoint to a fresh artifact, retain its byte hash and the
fit report, and load it with `readout.load_checkpoint` when reusing it. There is
no automatic Hub upload, DuckDB registration, distributed coordination, model
promotion, or incremental resume in this fitting API.

All targets in a fit must have the same JSON keys, array lengths, and scalar
types. Constant leaves form a training-consensus template; varying leaves get
independent learned classifiers with training-only vocabularies. A fit requires
1–256 varying scalar slots, at most 512 classes per slot, and at most 4,096
classes across slots. The numerical training path accepts at most 2,048 rows;
tuning accepts at most 4,096. Unseen shapes, classes, or changed consensus
constants are outside its decoder coverage. Evaluation retains such rows in the
denominator and reports coverage failures.

This is a useful candidate for a bounded schema, not an arbitrary-document
decoder. Independent scalar choices can combine into an invalid or incorrect
document, so native validation and source fidelity remain necessary. The schema
and scalar vocabularies also represent supervision unavailable to an
unconstrained decoder; comparisons with GRU heads must state that difference.

The optimizer minimizes centered squared class residuals plus ridge-weighted
squared weight norm. It computes one symmetric eigendecomposition of the smaller
primal/dual Gram matrix and reuses it for every ridge and class. Small negative
roundoff eigenvalues are bounded and clipped; materially negative spectra,
nonfinite arrays, or ridges below the numerical stability floor are rejected.
This changes fitting cost without changing the runtime tensor format. It is a
regularized linear solve, not evidence that joint autoencoder optimization has
reached a global minimum.

Tuning selects the ridge by actual generated exact-target count, then correct
variable-leaf count; ties retain the first ridge. The default grid is
`[0.0001, 0.001, 0.01, 0.1]`. No test rows select a ridge. The metrics distinguish
factorization, solve, validation, total fitting and recipe costs; embedding
production is outside fitting throughput. This comparison reuses that existing
numerical algorithm; it does not introduce a new optimizer.

For real corpora, prefer `train_grouped_source_decoder_384`. Its rows additionally
carry `group_id` and `split`, with split labels `train` and `validation`. Keep
related paraphrases, polarity variants, and other leakage-sensitive examples in
one group. Groups are caller declarations, not inferred semantic equivalence.
The recipe rejects overlapping group IDs, source identities, conservatively
normalized text, and numerically identical embeddings across splits. It also
rejects contradictory labels for identical source/numerical inputs. Group and
split metadata never become model features.

## Inference and post-generation checks

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    intent_ui_candidate_pipeline as pipeline,
)

audited = pipeline.infer_and_audit(reader, inference_rows)
```

`infer_and_audit` accepts exactly `id`, `source_text`, and `embedding` in each
input row. It first calls the loaded runtime, then supplies source text to the
audit owner. It does not pass parser outputs, reference targets, or repaired
candidates back to generation. Existing unchanged v1 GRU checkpoints can use
`domain_384_batched_inference.Runtime` with this same pipeline.

For an existing report, call `audit_candidates(report, source_rows)`, where each
source row has exactly `id` and `source_text`. The report must attest
`target_access=False` and `teacher_forcing=False`; IDs, row counts, dimension,
authority flags, and exact source hashes are checked. Invalid candidates remain
in the output and denominator without suppressing valid siblings. The original
report is copied, not rewritten.

Intent auditing compares the generated `intent_rich_ast` envelope against the
existing bounded whole-input grammar. It reports `native_invalid`,
`source_unsupported`, `source_disagreement`, or `source_agreement`, with typed
JSON-pointer differences for the complete candidate. Only grammar agreement
permits subsequent family preparation. Unsupported source language is an
explicit gap; a parser's reference is not general natural-language gold truth.
Agreement is not a repair and never grants proof or execution authority.

UI auditing describes the explicit generated candidate. It does not yet prove
that the candidate agrees with the user's source text. A valid projected UI
candidate receives `projected_candidate`; malformed candidates or missing
component context remain blocked. The pipeline sets `eligible_for_family_preparation`
only for the successful domain-specific disposition, while `qualified`,
`admitted`, `formalized`, `roundtrip_ok`, and authority flags remain false.

## What the UI projection adds

For a component containing all four explicit fields, the new native FOL formula
contains four ground declarations joined by three conjunctions:

| Supplied field | Ground predicate | Interpretation limit |
| --- | --- | --- |
| `component_id` | `UIComponent(identity)` | Declared identity |
| `role` | `UIRole(identity, role)` | Declared role token |
| `privacy_sensitivity` | `UIPrivacy(identity, label)` | Classification only, not a privacy policy |
| `presentation_classification` | `UIPresentation(identity, label)` | Classification only, not observed behavior |

The parser must return exactly the expected predicates, ordered constant
arguments and conjunctions, with no free variables, quantifiers, or modal
operators. This is ground first-order coverage, not quantified reasoning,
authorization, temporal behavior, or the full UI semantics.

Constants use stable category-prefixed UTF-8 hex symbols such as
`ui_privacy:v68696768` for privacy label `high`. The symbol table reverses each
constant to its exact category and value. Different roles, classifications and
identities therefore produce different native AST and formula atoms. Assigning
fresh sequential constants within each candidate would make distinct labels
look identical to projection training; a sidecar alone would not fix that loss
signal. Identity categories remain separate even when their strings coincide.

Only keys present in the original candidate gain classification facts. Omitting
privacy or presentation does not promote the native loader's defaults into
source declarations. Existing frame relationship facts remain unchanged. They
retain an edge's kind, source and target, but do not represent its `edge_id` or
`slot_name`. Child facts express membership without preserving child order.
Retaining the complete candidate in the audit does not make that frame
projection lossless over the full graph. The four-field component benchmark has
none of these additional relationship fields. A dangling component reference
still requires context; labels do not repair the graph.

The audit retains the complete original candidate, exact source and candidate
hashes, native parsed formula, reversible symbols, declaration counts, and
field-level accounting. A full wire document is accepted by its existing owner,
but this adapter projects only its component graph and the explicit fields
above. States, transitions, event declarations, bindings, accessibility,
recovery, guards, effects and other fields remain retained and explicitly
uninterpreted where this adapter lacks a route. It does not infer actors,
timestamps, observed events, consent, policy, or execution.

With the default inventory of **40 requested families**, this four-field
component produces **2 available families: frame logic and first-order logic**.
The other **38 remain missing**. No automatic applicability exemptions reduce
that count. Restricting `requested_families` is an explicitly different scope;
it must not be presented as satisfying the full floor.

`prepare_family_targets` returns:

```python
prepared = ui_source_contract_384_v2.prepare_family_targets(source_text, candidate)
report = prepared["report"]               # Existing v7 report schema
source_inputs = prepared["source_inputs"] # Exact typed kwargs for replay/Lake
audit = prepared["audit"]                 # JSON evidence, no authority
```

The derived typed document identity includes the hash of the entire original
candidate. Thus even a change to an unprojected field changes the source-bound
family report. `validate_prepared` checks replay of the report, original
candidate, source, declarations and symbols. This binding detects substitution;
it does not establish that a declaration faithfully translates its source.

## Actual native Lake checks

Build the exact replayed projections using the installed native Lake executable,
not an Elan shim that might obtain another toolchain:

```python
from ipfs_datasets_py.logic.formalization.autoencoder import (
    ui_source_contract_384_v2 as ui,
    native_family_lake_v5 as lake,
)

prepared = ui.prepare_family_targets(source_text, candidate)
ui.validate_prepared(prepared, source_text, candidate)
execution = lake.build_native_family_lake(
    prepared["report"], source_inputs=prepared["source_inputs"],
    lake_executable="/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake",
    timeout_seconds=60,
    output_directory="/absolute/path/to/fresh-ui-native-build",
)
receipt = execution.to_dict()
```

This launches the literal command `lake build UIUXIR` against the generated
modality library. For an Intent candidate that passed the source audit, prepare
`family_training_v7.prepare_family_training_targets_v7("intent_ir", document=candidate["document"], source_text=source_text)`
and pass those exact original kwargs to the same gate; its command is
`lake build IntentIR`. Legal and Security libraries remain `LegalIR` and
`SecurityIR` respectively. No Mathlib import is introduced.

The gate checks every emitted projection and preserves missing requested
families. A successful build of the supported UI subset is partial evidence,
not complete admission. Parsed ASTs, generated Lean text, native records,
reconstruction scores and optimizer success cannot substitute for the actual
build. Even a complete native build proves neither source fidelity nor the
truth of the modeled facts.

Richer UI sources can reuse the existing typed state, temporal, trace,
interface-binding and explicit confirmation routes. Their inputs must supply
the required semantics. In particular, a declared `UIEvent` is not an observed
`CanonicalInteractionEvent`, and a privacy label is not an authorization rule.
The restricted full-envelope-to-state adapter remains future work here.

## Reproducing the controlled comparison

Run from the canonical pinned `external/ipfs_datasets` tree, ideally a frozen
checkout whose source provenance can remain unchanged:

```bash
PYTHONDONTWRITEBYTECODE=1 python \
  scripts/ops/autoencoder/benchmark_intent_ui_candidate_coverage.py \
  --parent /absolute/path/to/trained-local-384d-parent.json \
  --parent-sha256 EXPECTED_PARENT_SHA256 \
  --output /absolute/path/to/fresh-comparison
```

The script uses verified cached `thenlper/gte-small` embeddings offline and
records local asset hashes. It does not download weights, enlarge the
64-token GRU context, or use test vectors. CPU numerical work uses one thread;
GRU baseline inference uses the existing batched v1 reader with batch size 16.

The authored panel has 96 training, 24 tuning and 24 test compositions per
domain. All varying scalar values occur in training. Test compositions differ,
but lexical values and semantic groups are shared; this does not measure unseen
vocabulary or unrestricted natural-language understanding. Two GRU fits per
domain use seeds 3517 and 3518; the deterministic ridge path fits once per
domain. These are six fits, not two independent repetitions of the ridge model.

All settings, training/tuning artifacts and six checkpoints are sealed before
test texts and embeddings are materialized. Test evaluation does not choose
hyperparameters. The comparison records exact complete outputs, critical scalar
accuracy, native validity, grammar disagreement, embedding reconstruction and
weight/input ablations separately. Ridge reconstruction reflects the inherited
unchanged projection; it cannot demonstrate reconstruction training progress.
Autoregressive token cross-entropy is not compared against ridge scores as a
common optimization objective.

Warm timing uses one warmup followed by ten alternating rounds on each arm's
24 test rows. It includes public readout, input copying, serialization and the
same additional strict native gate. It excludes model loading, embedding
production, gold scoring and post-generation source audits. These are candidate
readout timings, not legal-IR bridge evaluation or end-to-end corpus throughput.

## Results: sealed composition comparison

`comparison-r1` completed all six fits and post-seal evaluations in **74.65 s**.
It used the declared 96/24/24 split per domain and the same cached semantic
encoder assets. Source files, parent weights, cached assets, source inputs and
sealed artifacts remained unchanged. No test row selected a checkpoint.

| Domain | Decoder | Seed | Exact complete targets | Correct critical fields | Native-valid candidates |
| --- | --- | --- | --- | --- | --- |
| Intent | v1 GRU | 3517 | 3/24 | 63/96 | 24/24 |
| Intent | v1 GRU | 3518 | 8/24 | 77/96 | 24/24 |
| Intent | Structured ridge | Deterministic | **24/24** | **96/96** | 24/24 |
| UI | v1 GRU | 3517 | 3/24 | 69/96 | 24/24 |
| UI | v1 GRU | 3518 | 2/24 | 56/96 | 24/24 |
| UI | Structured ridge | Deterministic | **24/24** | **96/96** | 24/24 |

The ridge heads reconstructed all held-out compositions in this panel. This is
evidence for fixed-schema composition reconstruction using known lexical values;
it does not establish arbitrary UI document decoding, unseen vocabulary,
general source understanding or joint autoencoder convergence. The GRU failures
remain real and are not repaired by the audit pipeline.

All candidates passed local native schema validation, illustrating why that
check alone cannot measure fidelity. Intent's post-generation grammar audit
recorded 21/24 and 16/24 disagreements for the GRU seeds, versus 24/24 agreements
for ridge. Seed 3517 recovered every actor and action but only 7/24 modalities
and 8/24 objects. Seed 3518 recovered 24/24 actions, 19/24 actors, 23/24
modalities and 11/24 objects. The audit exposes these slot failures before family
preparation. UI's exact counts are comparisons with the separately authored
reference targets, not a general natural-language source-agreement proof.

Both ridge fits selected `0.0001` from the preregistered tuning grid. Zeroing the
head or shuffling embeddings reduced exact reconstruction to **0/24** in each
domain. Zeroing the inherited residual projection produced **2/24** in each.
That last ablation changes the representation supplied to an already fitted
head and its stored normalizer: it demonstrates dependence on the fitted path,
not an isolated benefit of the inherited features over a separately trained
raw-embedding baseline. Its identity reconstruction MSE of zero is an ablation
property, not a learned reconstruction improvement.

| Domain | Decoder / seed | Public training call, s | Warm median ms/span | Interquartile ms/span |
| --- | --- | --- | --- | --- |
| Intent | v1 / 3517 | 9.999 | 0.573 | 0.572–0.576 |
| Intent | v1 / 3518 | 23.174 | 0.584 | 0.577–0.591 |
| Intent | Ridge | 0.140 | **0.226** | 0.224–0.228 |
| UI | v1 / 3517 | 16.597 | 0.722 | 0.718–0.728 |
| UI | v1 / 3518 | 9.921 | 0.728 | 0.722–0.731 |
| UI | Ridge | 0.141 | **0.326** | 0.322–0.329 |

Public training times are single calls including preparation, tuning, selection
and checkpoint validation; they compare different objectives and model scopes.
Ridge uses a frozen inherited projection and a small linear head, while GRU fits
update the projection and recurrent decoder. The small ridge solve is not a
measurement of faster joint reconstruction training. Warm ridge readout was
about 2.5–2.6 times faster for Intent and 2.2 times faster for UI within the
explicit common-native-validation timing scope above. No bridge evaluation ran.

Peak RSS was **994,432 KiB** for the entire benchmark process, including the
semantic encoder and all phases. It is not an individual-head memory estimate.
The benchmark does not establish fleet scaling or concurrent training capacity.

The release evidence entry point is
[`intent-ui-coverage-20261002/results.json`](../implementation/reports/evidence/intent-ui-coverage-20261002/results.json).
Its archive retains `comparison-r1/summary.json`, `fits.json`, `plan.json`,
`freeze.json`, test-exposure ordering, all candidate/error records, ablations and
source/asset hashes. The six completed fits alone perform no Lake builds,
publication, production promotion or qualification.

### Native coverage follow-up

`native-checks-r1` completed **18 selected candidate attempts** without repairing
predictions or replacing their source text. The installed native Lean/Lake
toolchain was **4.30.0**, using the executable shown above. Four wrong Intent
GRU predictions failed source agreement before family preparation and did not
run Lake. The other **14 actual builds passed**: five `lake build IntentIR`
builds and nine `lake build UIUXIR` builds.

| Selected candidates | Actual builds passed | Reference-exact candidates | Requested-family accounting |
| --- | --- | --- | --- |
| Intent GRU, both seeds | 2/6; four blocked before Lake | 2/6 | Built reports: 10/40 routes, 30 missing |
| Intent ridge | 3/3 | 3/3 | 10/40 routes, 30 missing |
| UI GRU, both seeds | 6/6 | **0/6** | 2/40 routes, 38 missing |
| UI ridge | 3/3 | 3/3 | 2/40 routes, 38 missing |

Every build receipt is **partial** and has
`all_requested_projections_passed=False`. These counts describe emitted native
interpretation routes; individual lowering assumptions and capability-floor
limitations remain in their receipts. They do not establish complete family
semantics or source truth. In particular, the six wrong UI baseline candidates
all built: a structurally valid classification declaration can compile while
describing the wrong role or label. UI projection success therefore cannot
substitute for source fidelity.

The follow-up also executed the public inference/audit pipeline over all
**144 model-row pairs**, preserving every generated output. Intent agreement
remained 3/24 and 8/24 for the GRU seeds and 24/24 for ridge. Each UI arm produced
24/24 `projected_candidate` dispositions; those dispositions leave source
fidelity unknown and do not replace the separate reference comparison.

Native follow-up took **91.095 s**, with two native worker slots. Python-process
peak RSS was **844,980 KiB**, excluding native child-process RSS. These aggregate
costs include the audit and sampled build workflow and are separate from the
warm readout timings above. No external-solver diagnostic ran. Source and input
files remained unchanged, no weights were modified, and no candidate was
qualified, admitted, formalized, or promoted.

The evidence archive retains `native-checks-r1/summary.json`, its fixed
sampling plan, all 18 dispositions, the 14 actual command/build receipts, and
the unchanged-output public-pipeline observations alongside the training
comparison.
