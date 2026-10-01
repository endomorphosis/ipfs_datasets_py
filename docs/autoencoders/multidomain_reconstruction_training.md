# Four-domain native reconstruction training

## Source-style robustness, shared fitting throughput and supervisor consumption

The 21 earlier Security canary failures were all operator errors. Twenty came
from a temporary-variable/comment combination; removing whitespace differences
alone did not improve it. The learned classifier is sensitive to combinations
of temporary names, comments and parentheses even when source semantics match.

`security.source_style_augmentation_384` now creates training-only variants,
crossing three temporary names with four additional source styles. Every variant
is independently checked against its unchanged target using the source binder.
The complete source/embedding/group exclusion audit remains in force.

A fresh authored panel used 21 training groups, seven tuning groups and seven
test groups with new parameter names and compositions. There were 336 baseline
training rows or 1,344 augmented rows, with the same 504 tuning rows. Twelve fits
(two recipes × two numerical algorithms × three repeats) were frozen before
generating the evaluation rows. Test and new-layout canaries share seven groups;
they are not independent semantic populations or natural CVEFixes examples.

| Raw-source decoder | Primary exact /504 | New-layout exact /112 |
|---|---:|---:|
| Baseline source styles | 237 | 59 |
| Crossed training styles | 490 | 69 |

Both numerical algorithms produced identical decisions. The augmented learned
outputs passed actual Lake checks for all 490 source matches in the primary
panel and all 69 canary matches. The remaining 14 and 43 mismatches stayed
blocked. New layout style 10 regressed from 14/28 to 9/28 despite the aggregate
improvement, so this is not evidence of uniform robustness.

A separate successor using the **old vocabulary** was deliberately tested as an
exposed development regression. It achieved 480/480 tuning reconstruction but
regressed from 120 to 118 primary matches and from 39 to 33 canary matches. It
fixed five known failures while breaking eleven previously correct canaries.
That candidate was **not promoted**. Its failures and weights remain archived.

`structured_source_ridge_path_384.train_grouped_source_decoder_384` is a shared,
opt-in trainer for all four domains. It reuses one eigendecomposition of the
smaller primal/dual matrix across penalties and output classes. Both direct and
grouped callers retain canonical numeric/source leakage checks; unstable tiny
penalties are rejected. The trained Legal projection, checkpoint format,
inference runtime and validation selection rules remain unchanged.

Removing duplicated audits was necessary: the first implementation improved
matrix factorization time but regressed complete fitting time. Three subsequent
alternating development-only measurements, including audits, native preflight,
parent validation, fitting, tuning and checkpoint validation, gave:

| Training rows | Original median fit | Optimized median fit | Complete-call throughput gain |
|---:|---:|---:|---:|
| 336 | 0.847 s | 0.592 s | 1.43× |
| 1,344 | 1.693 s | 1.078 s | 1.57× |

Embedding generation and file writes are excluded. Heads were bit-identical to
the corresponding earlier fits, with unchanged validation decisions. Only
Security timing was measured; all four domains have numerical equivalence and
loader tests. The exact trainer source used before the performance refactor is
archived under `producer-snapshots`, and the optimized source has a separate
snapshot and receipt. The timing follow-up read no holdout files.

The accelerator supervisor's `prepare_task_context.py` now accepts
`--security-source-program-config`. Its local JSON configuration selects an
exact checkpoint SHA, optional embedding snapshot and optional bounded Lake
execution. The effective `input_view` is `raw` when omitted; the explicit
`guarded_ast_normalized` option uses the datasets-owned normalization consumer.
Both paths preserve original source hashes, retain mismatches and fail open
when optional inference is unavailable. The raw live smoke used actual CUDA
GTE-small and checkpoint weights: four source matches compiled, and an incorrect
fifth prediction remained blocked. Canonical intent state and source bytes
were unchanged. Advice does not bypass the Doctor's proof/admission contracts.

The normalized input profile uses the existing narrow AST guard to remove
comments/layout and one fresh temporary **before embedding**. It preserves the
function signature, ordered operands and operation, embeds duplicate views once
per batch, and qualifies the learned result against the original source. Model
outputs are never rewritten. Unsupported sources remain unchanged with an
explicit status. This is a hybrid parser-plus-model contract, distinct from raw
autoencoder generalization; it does not extend the supported Python grammar.

Using the unchanged frozen checkpoints, the explicit hybrid path produced:

| Already exposed panel | Raw exact/source matches | Hybrid exact/source matches | Hybrid Lake passed |
|---|---:|---:|---:|
| Original primary | 120/120 | 120/120 | 120/120 |
| Original canaries | 39/60 | 60/60 | 60/60 |
| New-panel primary, augmented head | 490/504 | 504/504 | 504/504 |
| New-panel canaries, augmented head | 69/112 | 112/112 | 112/112 |

All 796 variants compiled across 13 real Lake builds, using CUDA embeddings.
They normalize to 30 original-panel functions and 28 new-panel functions; the
variants are not 796 independent semantic cases. This normalization diagnostic
was designed after those panels were exposed and is **not a fresh holdout score**.
No weights were retrained or output IR corrected for this result. Zeroing the
head reduced original-panel matches to 12/120 and 6/60, and new-panel matches
to 0/504 and 0/112, confirming numerical dependence on the learned head.

The real normalized supervisor context smoke used the same original checkpoint
and five source files as the raw smoke, improving source matches and Lake passes
from 4/5 to 5/5 while leaving intent state and source bytes unchanged. It reused
three embedding views for five inputs. The combined closeout has **252 passing
tests**: 208 datasets training/normalization/regression tests and 44 accelerator
advisor/context tests. General control flow, unknown learned vocabularies,
full Python equivalence and security-specification proofs remain outside this
qualification. No new Terminal-Bench completion score is claimed.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.normalized_source_program_runtime_384 import (
    load_normalized_source_program_decoder_384,
)

runtime = load_normalized_source_program_decoder_384(
    checkpoint_path, expected_sha256=checkpoint_sha256,
)
report = runtime.infer_texts([source_code], snapshot_path=gte_snapshot)
# report["input_view"] == "guarded_ast_normalized"
# Each row retains source_normalization and the original-source source_contract.
```

Evidence: [fresh comparison](../implementation/reports/evidence/security-source-styles-v4-20261001/comparison.json),
[frozen plan](../implementation/reports/evidence/security-source-styles-v4-20261001/plan.json),
[rejected legacy successor](../implementation/reports/evidence/security-source-styles-v4-20261001/legacy-regression.json),
[complete timing comparison](../implementation/reports/evidence/security-source-styles-v4-20261001/throughput.json)
[raw supervisor smoke](../implementation/reports/evidence/security-source-styles-v4-20261001/supervisor-raw.json),
[hybrid normalization checks](../implementation/reports/evidence/security-source-styles-v4-20261001/normalized.json),
[normalized supervisor smoke](../implementation/reports/evidence/security-source-styles-v4-20261001/supervisor-normalized.json)
and [test receipts](../implementation/reports/evidence/security-source-styles-v4-20261001/validation.json).
Full artifacts are in the enclosing workspace under
`artifacts/security-source-styles-v4-20261001`.

## Security source-to-Lean follow-up

The two native Security blockers recorded below now have an explicit, opt-in
path. `security.source_program_binding_384_v2` derives complete command and
function read/write summaries from the checked expression graph. It preserves
other effects, purity and original metadata, with a reversible identity-bound
audit. `native_program_lean_v2` validates the closed metadata schema, source
references, assumptions and audit, then emits them as explicit Lean evidence
alongside the operational definitions. Its internal operational view has a
separate recorded identity; the original ProgramIR is not mutated.

The unchanged augmented Security checkpoint was loaded by exact SHA256 and
replayed without target fields. All 180 candidates and head/projection hashes
matched the archived evaluation. Two real `lake build SecuritySourcePrograms`
calls using Lean 4.34.1 produced:

| Partition | Rows | Source-qualified | Compiled by Lake | Rejected source mismatches |
|---|---:|---:|---:|---:|
| Primary holdout | 120 | 120 | 120 | 0 |
| New-wording canaries | 60 | 39 | 39 | 21 |

Every canary is retained in the result; the canary batch is **partial**, not a
60/60 success. Fresh GTE-small source-text inference on CUDA reproduced all
180 predictions. Zeroing the learned head reduced source matches to 12/120 and
6/60. The source checker did not rewrite wrong model outputs. No retraining,
parameter selection, checkpoint promotion or publication was performed.
The source, effects, metadata, consumer, numerical and embedding regression
suites passed **241 tests**, including an actual Lean check of all nine supported
operators in both direct and temporary-variable forms.

Single-call decode plus source-qualification timings were 0.857 s for 120 rows
and 0.265 s for 60 rows using saved embeddings. Lake preparation, execution and
live verification took 16.47 s and 5.20 s. Source-text embedding, decoding and
qualification took 4.31 s for the first 120-row call including model loading,
then 0.337 s for 60 rows with the loaded encoder. These are workflow diagnostics,
not repeated steady-state throughput comparisons or new training measurements.

Compilation checks mathematical Int/Bool operational definitions and explicit
metadata declarations. It does **not** prove Python runtime equivalence,
annotation enforcement, vulnerability repair, or a security specification.
The narrow source grammar remains unchanged. All proof/admission/execution
authority flags remain false. CodeUnit-remapped provenance and general control
flow are outside this new profile; existing generic family gates remain
conservative. The original training API, numerical modules and checkpoint files
are unchanged.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.source_program_runtime_384 import (
    load_source_program_decoder_384, build_decoded_source_program_lake,
)

runtime = load_source_program_decoder_384(
    checkpoint_path, expected_sha256=checkpoint_sha256,
)
decoded = runtime.infer_texts([source_code], snapshot_path=gte_snapshot)
execution = build_decoded_source_program_lake(
    decoded, [{"id": "input-0", "source_text": source_code}],
    lake_executable=native_lake_path,
)
receipt = execution.to_dict()  # Inspect per-row lake_status and overall status.
```

The [full replay report](../implementation/reports/evidence/source-native-v3-20261001/native-program-v2-report.json)
and [execution evidence](../implementation/reports/evidence/source-native-v3-20261001/native-program-v2-execution.json)
retain input, checkpoint, candidate, producer and tool hashes, build output and
test results. Checkpoints/training artifacts are authenticated by the original
freeze; later evaluation files are archived inputs hashed at replay time.
Producer pins cover named modules and the native Lake/Lean binaries, not the
complete transitive Python or toolchain dependency graph. GTE assets are checked
by the existing embedding runtime. The gate verifies source/candidate semantics;
the outer replay driver separately records actual checkpoint inference.

Reproduce with `scripts/ops/autoencoder/check_source_bound_program_384_v2.py`,
passing the original `--run-directory`, a fresh `--output-directory`, the original
`--freeze-sha256`, an installed native `--lake-executable`, and optionally
`--source-text-replay`. Full replay artifacts are in the enclosing workspace at
`artifacts/source-native-v3-20261001/native-program-v2-01`.

## Native-contract and source-variant follow-up

The new grouped source-training recipe audits groups, IDs, exact/normalized
source hashes, numeric embedding identities and target consistency before
fitting. Group IDs are caller-declared leakage units, not decoder features or
automatically discovered semantic equivalence. All wording, polarity and
function-name variants of a composition stay in the same split. The original
trained Legal projection and numerical checkpoint format remain unchanged.

UI preflight now validates semantic vocabulary in **full documents as well as
component fragments**, and checks full component graphs. Source inference can
emit real F-logic component facts; privacy, behavior, accessibility and temporal
compliance remain outside that structural projection. Invalid predictions are
retained for diagnosis and flagged fail-open instead of relabeled.

Security source qualification independently checks the predicted expression
against the Python AST, exact source hash, ordered operands, annotations,
native references/spans and CFG. A narrow supported case can now produce a
source-bound `ProgramIR` through the existing adapter and syntax bridge:
two explicitly `int`-annotated parameters, one of `+ - * < <= > >= == !=`, and
either a direct return or one fresh temporary assignment. Integer annotations
are input assumptions; Python does not enforce them. Division, arbitrary control
flow, missing types and mismatched predictions abstain without rewriting the
learned output. `verify_source_qualification` replays the exact evidence binding.

Fresh authored groups use different identifiers/compositions from the earlier
panel and corrected native UI vocabulary. Baseline training uses 180 rows with
two source styles; augmented training uses 360 rows with four styles, across the
same 15 groups. Both use 120 tuning rows from five other groups. The primary
holdout has 120 rows from five unseen groups; 60 canaries apply two new styles
to those **same five test groups**. These remain fixed-schema, closed-vocabulary
diagnostics, not natural-corpus generalization or benchmark task completion.

| Domain | Primary exact: baseline → augmented /120 | New styles: baseline → augmented /60 | Native result for augmented primary predictions |
|---|---:|---:|---|
| Intent | 120 → 120 | 60 → 60 | 120 DCEC/TDFOL/parameterized formula projections |
| Security | 69 → 120 | 36 → 39 | 120 source-bound ProgramIR candidates |
| UI/UX | 120 → 120 | **53 → 45** | 120 native F-logic component projections |
| Legal | 120 → 120 | 60 → 60 | 120 native deontic grammar checks |

The Security improvement is substantial on held-out compositions expressed in
trained source styles. Novel style generalization remains poor. **UI augmentation
regressed**, despite equal tuning and primary-test reconstruction, and is not
recommended for promotion from this evidence. UI vocabulary correction itself
eliminates the prior native rejection: all 120 primary components now validate.
No model was promoted, no default published checkpoint changed, and no training
or parameter selection followed holdout exposure.

All 21 inexact augmented Security canaries were independently rejected as source
mismatches. UI F-logic succeeds for even incorrect but well-formed component
labels; its success must not be confused with source fidelity. The qualification
boundary rejects target-bearing source rows and gold-derived evaluation flags;
a separate target-free inference replay feeds the native checks.

Three alternating fits per arm produced identical learned weights. Median
complete grouped-call timing on one CPU thread was:

| Domain | Fit seconds: baseline → augmented | Training variants/s: baseline → augmented | Training groups/s: baseline → augmented |
|---|---:|---:|---:|
| Intent | 0.270 → 0.385 | 665.7 → 934.1 | 55.5 → 38.9 |
| Security | 0.300 → 0.423 | 599.8 → 850.7 | 50.0 → 35.4 |
| UI/UX | 0.307 → 0.440 | 587.0 → 819.0 | 48.9 → 34.1 |
| Legal | 0.499 → 0.690 | 361.1 → 522.0 | 30.1 → 21.7 |

Augmentation doubles the number of training variants and takes about 1.4× the
total time. Higher variant throughput comes from amortizing fitting overhead;
it is **not** more independent groups processed per second. These timings include
audits, native preflight, tuning, numerical fitting and in-memory checkpoint
validation, excluding embedding generation and file writes. Warm decoder
throughput is roughly 8,000–9,100 rows/s for Intent/Security/UI and 3,040 for
Legal, excluding embeddings, loading and postdecode source qualification.
These are medians from five batched calls, not complete workflow throughput.

The public source-text API independently recomputed CPU GTE-small embeddings
and reproduced all **480/480 primary targets** across the four augmented heads;
Security produced 120 qualified source-model bindings and UI 120 structural
projections. The grouped recipe, UI contracts, Security binder, shared API and
benchmark boundary suites passed **195 tests**.

At the original v3 evaluation, native Security Lean compilation was blocked.
Four representative learned
models (Boolean/integer × direct/temporary return) replayed through native family
preparation, but `native_program_lean._Program` rejects their nonempty metadata
with `program_metadata_requires_explicit_semantics_review`. **Zero Security Lake
builds executed**; metadata was preserved. A further code-review finding is that
the existing Python adapter omits expression reads from command effects and the
temporary from function reads. The opt-in follow-up above resolves those two
contracts for the narrow native profile. The successful
Intent Lake checks in the earlier section do not cover these Security models.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.complete_training import (
    train_grouped_source_decoder_384,
    load_structured_source_decoder_384,
    infer_source_texts_384,
)

fit = train_grouped_source_decoder_384(
    "security_ir", grouped_training_rows, grouped_tuning_rows,
    parent_projection={"path": trained_legal_path, "sha256": trained_legal_sha256},
)
# Persist checkpoint JSON and its exact file SHA, then load it explicitly.
runtime = load_structured_source_decoder_384(
    checkpoint_path, expected_sha256=checkpoint_sha256, expected_domain="security_ir",
)
report = infer_source_texts_384(runtime, [source_code], snapshot_path=gte_snapshot)
# Each supported row has source_contract; mismatches remain fail-open.
```

Grouped rows contain exactly `id`, `group_id`, `split`, `source_text`, `embedding`
and `target`. Fit accepts only `train` / `validation` labels. Checkpoint and
grouping provenance are separate, so callers can retain the existing numerical
loader. `qualify_source_candidates_384` also exposes source checks for callers
that already produced embeddings and decoded outputs.

The [comparison](../implementation/reports/evidence/source-native-v3-20261001/report.json),
[frozen plan](../implementation/reports/evidence/source-native-v3-20261001/plan.json),
[freeze](../implementation/reports/evidence/source-native-v3-20261001/freeze.json),
[public API replay](../implementation/reports/evidence/source-native-v3-20261001/public-api-replay.json)
and [blocked native Lean diagnostic](../implementation/reports/evidence/source-native-v3-20261001/native-program-lake.json)
retain the outcomes. Full artifacts live at
`artifacts/source-native-v3-20261001/run-02` in the enclosing workspace.
`run-01` remains an unevaluated pre-review fit; run-02 adds stronger dependency
pins and the enforced gold-free qualification boundary. No holdouts were opened
until all run-02 models were frozen. Source pins cover named producer/native
contract modules, not the complete transitive Python dependency graph.

Reproduce the exposed diagnostic with `benchmark_native_source_v3.py prepare`,
`fit` and `evaluate`, passing a fresh absolute output directory, the trained Legal
parent at preparation, and the printed freeze SHA at evaluation. A subsequent
model-selection campaign must use new sealed groups.

## Source reconstruction follow-up: frozen composition experiment

The shared 384D training API now has two additive paths. `source_training_v2`
adds training-only input centering, greater loss weight on changing semantic
fields, length-bucketed batches, batched generation, and checkpoint selection
using free-running tuning reconstruction. `structured_source_384` instead fits
independent scalar classifiers over the frozen, trained Legal residual
projection. One dual-ridge solve serves all scalar classes at each penalty.
Its JSON structure and constants come from training consensus; its variable
values come from learned scores, without whole-target retrieval.

The structured path is a **fixed-schema decoder over a pretrained autoencoder**,
not a newly trained general sequence autoencoder. It supports the training
scalar vocabulary and one typed JSON tree, including fixed array lengths.
Unknown structures/classes are explicit coverage failures during evaluation.
Input text is embedded using verified GTE-small; the decoder receives those
384D vectors, without a parser, reference metadata, or target document.

All 19 candidate checkpoints were frozen before exposing the test and canary
partitions. Each domain has 180 training rows, 60 tuning rows, 60 test rows and
30 additional-wording canaries. Entire actor/action, operand/operator-family or
component/role combinations are held out, including all polarity and wording
variants. The five test groups per domain recombine vocabulary seen in training.
Canaries use the **same five groups** with a third wording style; they are not
independent held-out groups. These are authored diagnostics, not CVEFixes,
SkillCenter, legal-corpus or browser observations.

| Domain | Sequence reference exact /60 | Structured exact /60 | Structured new wording /30 | Reference → structured full-fit rows/s |
|---|---:|---:|---:|---:|
| Intent | 2 | 60 | 30 | 31.0 → 234.5 |
| Security | 0 | 60 | 20 | 18.0 → 1,043.9 |
| UI/UX | 3 | 60 | 28 | 38.2 → 1,104.1 |
| Legal | 3 | 60 | 30 | 26.4 → 692.8 |

The sequence references for Intent, Security and UI are the existing native v1
implementation, retrained on the same development inputs. Legal uses the new
shared raw-cross-entropy sequence arm: the published Legal runtime also uses
parser-derived features and is **not** an equivalent source-only comparator.
All sequence arms ran 100 epochs / 1,500 optimizer steps with seed 1729 and the
same trained Legal parent. The semantically weighted sequence arm scored
7/60, 0/60, 5/60 and 0/60 respectively; it did not solve the reconstruction gap.
The structured arm used four ridge penalties, selected solely on tuning data.
These limited-budget baselines do not establish the best possible sequence
decoder performance.

Full-fit rows/s means 180 unique rows divided by the complete training call,
including preparation, tuning and in-memory checkpoint validation. It excludes
embedding production and writing the checkpoint file. These are single fits on
one CPU thread, with ordinary process initialization and background activity;
they are not repeated, isolated speed measurements. The observed fit speedups
are 7.6×, 58.1×, 28.9× and 26.2×, for different decoder architectures and
optimization procedures. No optimizer-token throughput is invented for ridge.

Warm target-free inference, including native validation but excluding model
loading and source embedding, used the median of five 60-row calls:

| Domain | Sequence reference rows/s | Structured rows/s |
|---|---:|---:|
| Intent | 417.9 | 8,767.4 |
| Security | 206.0 | 7,724.5 |
| UI/UX | 468.4 | 7,526.8 |
| Legal | 1,526.5 | 2,925.5 |

The new batched sequence runtime itself processes about 1,482–2,938 rows/s
across arms/domains, so some improvement over v1 comes from batching rather
than changing the decoder architecture. CUDA GTE-small development embedding
production measured 1,343.5 rows/s, encoding only, with model loading reported
separately. The model revision is
`17e1f347d17fe144873b1201da91788898c639cd`; no input was truncated.

Ablating the learned scalar heads reduces exact test reconstruction to 0/60 in
every domain. Removing the inherited Legal residual branch reduces it to
9/60, 0/60, 5/60 and 4/60. Cyclic embedding shuffling gives 0/60, 40/60, 0/60
and 0/60; the Security shuffle retains many identical target fragments because
adjacent function-name variants share targets. Thus that particular negative
control is weaker for Security. The inherited projection is numerically used,
and the original Legal parent bytes are unchanged.

The remaining canary errors are substantive: Security confuses operators and
result types after an intermediate assignment is introduced, and UI confuses
`sensitive` with `restricted` privacy. No retraining or selection used these
exposed cases. Security labels are local expression fragments with authored
integer-type assumptions; they require an enclosing symbol/CFG model for full
program validation. Valid JSON/native shape is not evidence of correct meaning.
No checkpoint was promoted or uploaded by this experiment. The prior public
development releases remain explicitly pinned.

Postdecode integration replayed all 240 test predictions from the frozen
weights without target access. Intent's 60 outputs reached native DCEC/TDFOL
parse/reparse and parameterized Lean fixtures; three modality representatives
passed actual Lean 4.34.1 `lake build` calls. Legal's 60 outputs passed the native
deontic grammar. Security's 60 local fragments still lack a complete ProgramIR
and therefore do not establish a program-family projection.

**UI exposed a training-label contract gap:** only 20/60 decoded targets reach
the native F-logic component projection. The other 40 correctly reconstruct
authored labels that the permissive `UIComponent` envelope accepts but
`SemanticComponent` rejects: privacy `sensitive` and presentation
`informational`. Thus 60/60 target reconstruction does not mean 60/60 native
semantic components. New shared training entry points reject such labels before
fitting. Shared inference preserves the candidate as diagnostic evidence but
marks it `fail_open_native_component_invalid`, with planning allowed to continue.
There is no automatic relabeling or silent formula replacement. Frozen low-level
drivers retain the original experiment for reproduction; the public API now
enforces the stricter contract. Corrected UI training needs a new, sealed panel.

Fresh source-text inference through the public API reproduced all 240 target
matches using independently recomputed CPU GTE embeddings and flagged precisely
those 40 UI failures. The [projection receipt](../implementation/reports/evidence/source-reconstruction-20261001/projections-summary.json)
and [public API replay](../implementation/reports/evidence/source-reconstruction-20261001/public-api-replay.json)
record these separate outcomes. Lean validates parameterized syntax/types here,
not source meaning, behavior, or all 60 rows.

Use the additive lazy public API, preserving existing v1 callers:

```python
from ipfs_datasets_py.logic.formalization.autoencoder.complete_training import (
    train_structured_source_decoder_384, load_structured_source_decoder_384,
    infer_source_texts_384,
)

fit = train_structured_source_decoder_384(
    "security_ir", training_rows, tuning_rows,
    parent_projection={"path": trained_legal_path, "sha256": trained_legal_sha256},
)
# Save fit["checkpoint"] as JSON and compute the exact file SHA before loading.
runtime = load_structured_source_decoder_384(
    checkpoint_path, expected_sha256=checkpoint_sha256, expected_domain="security_ir",
)
candidate = infer_source_texts_384(runtime, [source_code], snapshot_path=gte_snapshot)
```

Training rows have exactly `id`, `source_text`, `embedding` and `target` fields.
Inference rows omit `target`; the text helper builds genuine source embeddings.
`train_source_decoder_384_v2` / `load_source_decoder_384_v2` expose the alternative
sequence path for all four domains. All generated candidates remain unqualified
and need independent source-fidelity and proof checks.

Retained [comparison report](../implementation/reports/evidence/source-reconstruction-20261001/report.json),
[structured freeze](../implementation/reports/evidence/source-reconstruction-20261001/structured-freeze.json),
[sequence freeze](../implementation/reports/evidence/source-reconstruction-20261001/sequence-freeze.json),
and [artifact hashes](../implementation/reports/evidence/source-reconstruction-20261001/artifact-inventory.json)
record every arm. Full checkpoints and row-level results are in
`artifacts/source-reconstruction-v2-20261001/{run-01,structured-01}` in the
enclosing workspace. Reproduction uses `benchmark_source_training_v2.py`
`prepare` and `fit`, then `benchmark_structured_source_384.py` `fit` and
`evaluate`; the latter opens both models' heldouts only after both freezes.
These groups are now exposed: future selection needs fresh held-out groups.

The native-family results below concern a **separate structural-feature
training objective**. The new source fragments do not establish all 15/9/8/6
families without their required typed program, temporal, authorization or
interface evidence. No missing family is filled with a placeholder formula.

## Complete-feature update, 2026-10-02

An additive trainer now retains **every training atom** instead of pruning at
4,096 columns. Its codec splits compound identifiers into ordered pieces while
preserving case, delimiters and opaque hashes. Capacity limits fail explicitly;
they never silently discard training features. All 14 held-out rows per domain
remain distinct, including Security, whose previous panel collapsed to two
feature vectors.

The new ridge-path strategy reuses grouped Gram factorizations and selects
decoder blocks on tuning data. It avoids the 24 Adam epochs in the matched
reference. Both arms use the same complete training-only basis, SVD initializer,
masked macro-family objective, and strict per-family tuning nonregression.
Existing trained source decoders, checkpoints and default trainers are preserved.

| Domain | Native families exercised | Adam → ridge rows/s | Full numerical-fit speedup | Held-out loss reduction |
|---|---:|---:|---:|---:|
| Intent | 15 | 1.94 → 5.33 | 2.75× | 0.005496% |
| Security | 9 | 1.98 → 5.11 | 2.58× | 0.002262% |
| UI/UX | 8 | 6.03 → 12.63 | 2.10× | 0.007680% |
| Legal | 6 | 13.20 → 29.58 | 2.24× | 0.003418% |

These are tiny quality changes; the material result is faster fitting. No
measured family regressed. Timing is the median of three alternating paired
fits on one CPU thread, including feature preparation, numerical fitting,
serialization and reload. It excludes the earlier native-target construction,
source embedding, prover execution and Hugging Face I/O. Rows/s counts unique
training rows per full call, not repeated optimizer presentations. Background
system activity was not experimentally isolated.

Each domain used 84 training, 14 tuning and 14 held-out authored rows across
seven held-out composition groups. All 24 candidates were frozen before held-out
target generation. Supplemental native models are explicit authored assumptions;
some fixture structures are reused. Three seeds share the same held-out groups,
so this is neither three independent datasets nor evidence of natural-corpus
generalization. Raw losses cannot be compared to the old pruned feature basis.
No model was promoted from these scores. An earlier, smaller-basis trial had a
small Intent regression and was also left unpromoted.

The full route lists are:

- Intent: authorization, datalog, dcec, deontic, event_calculus, first_order,
  frame_logic, higher_order, horn_chc, intention_agency, program, refinement,
  tdfol, temporal, transition_system.
- Security: authorization, concurrency, cryptographic_protocol, hyperproperty,
  program, refinement, separation_logic, temporal, transition_system.
- UI/UX: authorization, dcec, event_calculus, frame_logic, program, tdfol,
  temporal, transition_system.
- Legal: authorization, deontic, event_calculus, frame_logic, tdfol, temporal.

These are all **currently implemented domain training routes**, not all 40
catalog families. Missing adapters and missing typed inputs remain explicit
frontier entries. Legal event calculus does not establish cognitive DCEC;
family presence does not establish every profile, Lean correctness, TLC model
checking, or source fidelity.

Use the lazy shared API from the logic module:

```python
from pathlib import Path
from ipfs_datasets_py.logic.formalization.autoencoder.complete_training import (
    train_native_families, reconstruct_native_families, native_family_ids,
)

candidate = train_native_families(
    "security_ir", training_rows, tuning_rows,
    output_dir=Path("workspace/security-complete-candidate").resolve(),
    strategy="ridge_path", latent_width=8,
    requested_families=None,
    require_all_native_families=True,
)
score = reconstruct_native_families(candidate["descriptor"], evaluation_rows)
```

The closed source/group/split row contract below also applies here. All native
and split checks run before optimization. The strict complete-family option
requires real training and tuning targets for every registered domain route;
missing models fail instead of creating placeholder formulas. This new recipe
creates a fresh structural head and does not resume a source decoder. Dense
input matrices are bounded to 256 MiB; full checkpoint JSON is also bounded.
For Intent, this new API additionally accepts an exact native
`IntentIRDocument`, including intentions and invariants outside the rich AST
grammar. Its source hashes and spans must match the supplied text. Typed
declarations and rich ASTs use separate panel contracts; neither is asserted to
prove the source's meaning. Group/source exclusion applies to both.

Retained evidence: [report](../implementation/reports/evidence/complete-family-training-20261002/report.json),
[frozen artifact hashes](../implementation/reports/evidence/complete-family-training-20261002/freeze.json).
The original run is retained under `artifacts/ir-training-complete-20261002/run-02`
in the enclosing workspace. A checked-in reproduction driver and authored
fixtures are available:

```bash
python scripts/ops/autoencoder/benchmark_complete_family_training.py prepare --output-directory /absolute/new/run
python scripts/ops/autoencoder/benchmark_complete_family_training.py fit --output-directory /absolute/new/run
# Use the freeze SHA printed by fit:
python scripts/ops/autoencoder/benchmark_complete_family_training.py evaluate --output-directory /absolute/new/run --freeze-sha256 <sha256>
```

This reproduces an exposed diagnostic panel; a subsequent model-selection
campaign needs new sealed groups. The earlier results below remain historical.

## Separate 384D source-decoder development releases

The four opt-in checkpoints are published at
[Publicus/intent-ir-autoencoder](https://huggingface.co/Publicus/intent-ir-autoencoder),
[Publicus/security-ir-autoencoder](https://huggingface.co/Publicus/security-ir-autoencoder),
[Publicus/ui-ux-ir-autoencoder](https://huggingface.co/Publicus/ui-ux-ir-autoencoder), and
[Publicus/legal-ir-autoencoder](https://huggingface.co/Publicus/legal-ir-autoencoder).
The library's `published_384_checkpoints.py` contains full immutable commit and
manifest hashes. Fresh-cache download and offline reload produced exactly the
same numerical inference as the local packages for all four domains. Existing
Legal source artifacts and upstream checkpoint datasets were not overwritten.

These are separate models from the complete-feature family heads above. The
three native source decoders inherit the trained Legal projection, conditioning
and GRU tensors, with mapped lexical rows and trained means for new tokens.
They consume genuine pinned GTE-small embeddings through the shared 384D
framework. The public Legal package retains its own sparse core and trained
formula head; an explicit source-binding compatibility fork replayed all 32
original training and 8 tuning inputs with unchanged neural/optimizer weights.

**Source-decoder quality is not yet adequate:** Intent, Security and UI/UX each
produced 2/2 structurally valid held-out fragments but **0/2 exact semantic target
reconstructions**. Their small authored corpus has 12 training and 2 tuning rows;
the held-out paraphrases share semantic targets with training. These checkpoints
were not trained on the complete CVEFixes/SkillCenter corpora. Weight ablations
and shuffled embeddings change outputs, demonstrating numerical dependence
without demonstrating correct meaning. No fresh Legal source-accuracy claim is
made by packaging its existing head. The 15/9/8/6 family-coverage figures belong
only to the separate native-feature experiment.

```python
from ipfs_datasets_py.logic.security_ir import open_autoencoder

runtime = open_autoencoder()  # explicit opt-in; exact release, not mutable main
candidate = runtime.infer_texts([source_code], snapshot_path=verified_gte_snapshot)
# Subsequent reload can use open_autoencoder(local_files_only=True).
```

Each IR package also exposes `formalize_with_autoencoder(source_text,
autoencoder=runtime)`. `open_runtime(domain, "published_384_v1", ...)` uses the
same implementation. Imports remain offline; loading requires the matching
source-pinned development checkout and checkpoint cache. Source inference also
requires verified local GTE-small assets and rejects inputs beyond 512 tokens.
No LLM fallback or compiler replacement occurs. Candidates remain unqualified
and cannot establish proof, admission or source fidelity. The public model cards
record the failed exact-reconstruction check and provenance/license limitations.

Release evidence: [pinned releases](../implementation/reports/evidence/ir-384-release-20261002/published-pins.json),
[remote replay](../implementation/reports/evidence/ir-384-release-20261002/remote-qualification.json),
[decoder evaluation](../implementation/reports/evidence/ir-384-release-20261002/native-decoder-evaluation.json).

The shared interface covers `intent_ir`, `security_ir`, `ui_ux_ir`, and `legal_ir`,
with independent weights, vocabularies, projections, provenance, and split
histories. It reconstructs supplied native logic features. The existing learned
source-language decoders remain separate; their formula fidelity is not measured
by this feature loss. Existing v1/v2 trainers, the 8D linguistic decoder, and the
384D latent-to-formula runtime are unchanged.

## Run training and inference

Use the pinned package checkout, with thread limits set before importing Torch
or NumPy. A bare editable import can resolve to HACC instead.

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
export PYTHONPATH="$PWD"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export CUDA_VISIBLE_DEVICES=''
```

```python
from pathlib import Path
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    domain_family_training_prepared as training,
)

result = training.train_domain_family_autoencoder(
    "intent_ir", training_rows, tuning_rows,
    output_dir=Path("workspace/my-intent-candidate").resolve(),
    numerical_backend="prepared",  # explicit; default remains "v2"
    requested_families=None,        # inventory all 40; fit actual ready targets
    epochs=12, latent_width=16, minibatch_size=32,
    learning_rate=.001, denoising=.05, ridge=.001,
    patience=4, seed=1729, max_seconds=120,
)
assert result["report"]["status"] == "complete", result["report"]["family_error"]
inferred = training.infer_domain_family_autoencoder(result["descriptor"], evaluation_rows)
assert inferred["training_steps"] == 0
```

Directories must be fresh, absolute paths. Every input row is a closed mapping:

```python
{
    "source_id": "immutable-row-identity",
    "group_id": "document-or-application-group",
    "split": "train",  # validation/tuning for selection; test only for inference
    "inputs": {...},
}
```

| Domain | Required native `inputs` |
|---|---|
| Intent | `document`: complete rich AST; `source_text`: exact instruction accepted by the native grammar. Optional `context` and `supplemental_inputs`. |
| Security | `code_unit`: native `CodeUnit`; `source_bytes`: exact body; `typed_inputs`: native `CodeLogicEvidence` records. Optional `supplemental_inputs`. |
| UI/UX | `ui_training_row`: validated DOM/ARIA, verified interface descriptor and binding, declared behavior and event provenance. Optional `supplemental_inputs`. |
| Legal | `document`: `CanonicalRoundTripIR`, `ModalIRDocument`, or `MultiViewLegalIRReport`; `source_text`: exact source. Optional `supplemental_inputs`. |

Labels, model scores, or family names do not substitute for typed inputs.
Supplementary models use `TypedFamilyEvidence` and its exact source join.
Unverified events remain supplied observations. A UI timeout cannot become an
untimed state transition by dropping its timing semantics.

`prepare_domain_family_rows(...)` runs preflight without fitting.
`load_domain_family_recipe(descriptor)` verifies metadata and model provenance.
`infer_domain_family_autoencoder(...)` reads saved weights only. This API does
not generate source formulas, populate a supervisor, publish to the Hub, or
promote a model. Existing Security joint/source and Intent aligned-source
training entry points remain intact; source-stage options cannot silently enter
this structural-only API.

For continuation, supply the previous recipe as `parent_descriptor` and a new
output directory. Domain, backend, projection basis, fixed tuning panel,
producer versions, and historical source/group separation must match. Intent
also quarantines complete AST and tokenized full-source aliases, while allowing
known atoms in new compounds. Bare numerical checkpoints cannot be adopted by
this recipe without their domain split history. The low-level prepared trainer
can separately inherit complete compatible v1/v2 numerical heads.

Continuation currently starts fresh Adam; it is not an optimizer-cursor resume.
`max_seconds` bounds the existing optimization phase, not target preparation,
serialization, or the complete call. The atom cache has 8,192 entries per call,
not a total RSS byte cap. Workers should own separate candidate directories.
These APIs do not create another DuckDB writer or change sparse publication.

## Objective and optimization

Loss averages MSE plus `0.1 * cosine_loss` within each native projection, then
within each family, then across families. Missing targets are masked.
Population-frequency correction preserves this weighting in minibatches.

V2/prepared first fit a training-only ridge correction to decoder blocks.
Tuning can select improved families independently while the encoder is fixed.
Joint Adam refinement uses 75% clean and 25% denoised reconstruction, warmup,
cosine learning-rate decay, clipping, and tuning patience. A candidate must
improve aggregate tuning loss without regressing any selected family. Held-out
rows do not enter vocabulary fitting, updates, or selection.

Prepared execution caches structural atom serialization and prepares minibatch
masks/family denominators once. It avoids detailed metrics discarded by the
training loop. Loss arithmetic, gradients, selection, and retained tensors match
v2 exactly in the paired tests. Temperature, context and proof gates are unchanged.

## Logic coverage

The catalog contains 40 canonical families. Existing target adapters have
potential native routes for 15 Intent, 9 Security, 8 UI/UX, and 6 Legal families.
Successful source-bound native evidence is still required. Registry presence
elsewhere in `logic/` is not enough to establish domain training support.

`logic.formalization.autoencoder.family_coverage_audit.audit_family_training_coverage`
accepts separate training/tuning/held-out reports, actual numerical training and
inference receipts, and explicit `required_families` and `required_profiles`:

```python
required_profiles = [{"family_id": "transition_system", "profile": "tla_plus"}]
```

The audit inventories all 40 families, validates producer pins and split
identities, checks native/numerical coverage, and counts unknown atoms. Missing
fitting evidence cannot pass the numerical floor. This is receipt-consistency
validation, not checkpoint execution or authentication; retain actual execution
receipts with it. It does not establish source semantics or qualification.

Do not expand aliases into extra coverage. An older Legal `cec`/`dcec` alias maps
to `event_calculus`; it cannot satisfy a required `dcec` family. Likewise
`tdfol/temporal_first_order` does not establish every temporal/deontic composition.
A generated TLA+ artifact is not a TLC verification.

Exact profile audits found `transition_system/tla_plus` targets in Intent and
UI/UX. Security's trained profile is `transition_system/action_system`; an
embedded TLA artifact does not establish a separate trained TLA+ projection.
Legal's `tdfol/temporal_first_order` profile is present structurally. Complete
DFOL and cognitive-CEC compositions remain unverified. Separate retained profile
audits add these distinctions without changing the frozen experiment.

The authored panel exercised all ready projections in these families:

| Domain | Numerically trained and covered on held-out features |
|---|---|
| Intent | first_order, deontic, dcec, tdfol, frame_logic, program, temporal, transition_system, datalog, horn_chc, higher_order |
| Security | program, transition_system, temporal, separation_logic, hyperproperty |
| UI/UX | frame_logic, event_calculus, tdfol, dcec, transition_system, temporal |
| Legal | deontic, frame_logic, tdfol |

Other requested families remain explicit in the frontier. The complete coverage
floor is false for all four panels. Legal does not establish the complete FOL,
DFOL, TFOL, TDFOL, cognitive CEC, DCEC, frame and propositional floor. More native
evidence/adapters are needed; missing formulas are not fabricated.

## Held-out reconstruction

Each domain has 24 training, 8 tuning, and 8 held-out authored rows. Related
actor/action pairs and both variants stay together across splits. These are four
held-out composition groups, not eight independent real-world documents. All
actors and actions already occur in training.

All 24 candidates (four domains, three seeds, reference/prepared) were frozen
before any held-out target was generated. Each fit used 24 epochs, 96 updates,
batch 6 and latent width 8. This width is for an auxiliary feature head; it does
not replace either legal autoencoder lineage.

| Domain | Initial objective | Trained mean objective | Reduction | Distinct held-out feature vectors |
|---|---:|---:|---:|---:|
| Intent | 0.0001352171 | 0.0001278817 | 5.42% | 8/8 |
| Security | 0.0001615739 | 0.0001612234 | 0.22% | **2/8** |
| UI/UX | 0.0005844967 | 0.0005419430 | 7.28% | 8/8 |
| Legal | 0.0000130895 | 0.0000104714 | 20.00% | 8/8 |

No measured family regressed against the training-only initializer. Reference
and prepared weights, histories, selection and held-out results matched exactly.
The quality gain is training versus initialization, **not** prepared versus v2.
Unknown held-out atoms are omitted by this feature codec; Security's collision
makes its small improvement weak evidence of generalization. These are not exact
typed-declaration, formula-generation, or source-decoder reconstruction scores.

“Unknown” means absent from the retained basis, including training atoms removed
by the 4,096-feature budget; it does not necessarily mean novel held-out content.
Intent retains 4,096 of 13,100 distinct training atoms and UI/UX 4,096 of 5,494.
Security retains all 1,693 training atoms, but unseen composite names still make
its eight held-out sources collapse to two vectors. Held-out atom occurrences
excluded by the retained basis are Intent 64.40%, Security 3.24%, UI/UX 10.15%,
Legal 0%; Intent already excludes 64.28% of training atom occurrences.

For Intent, Security and UI/UX, calibration supplied the selected weights;
subsequent Adam updates did not beat the per-family tuning gate. Legal selected
epochs 19, 21 and 22. More executed updates are not automatically more useful
training. Normal runs retain the smaller default patience; this comparison used
equal complete budgets to isolate implementation throughput.

The held-outs are now exposed development data. Do not reuse them as a fresh
canary or select further candidates using these results. No model was promoted.

## Throughput and reproduction

The short comparison includes validation, feature preparation, optimization,
serialization and reload in each timed numerical call. Native target generation
runs once and is shared between arms. CPU runs are warm on a shared host, one
worker, float64 heads, OMP/MKL/OpenBLAS limits one, CUDA hidden. No embedding
weights were loaded.

| Domain | Reference row presentations/s | Prepared row presentations/s | Mean wall speed ratio |
|---|---:|---:|---:|
| Intent | 402 | 388 | 0.964 (slower) |
| Security | 1,307 | 1,376 | 1.047 |
| UI/UX | 686 | 774 | 1.126 |
| Legal | 3,255 | 3,357 | 1.031 |

Each arm presents 576 training rows. Fixed setup costs matter on short jobs:
backend selection remains explicit and the default stays v2. A separate longer
Intent diagnostic with six projections, 24 training/2 tuning rows and 1,024
updates measured 2,221 to 2,486 row presentations/s (1.120 mean wall ratio).
That is a different family/sample set, not a replacement for this full panel.

A subsequent **training-only** throughput run used the same four-domain
development specification and full family inventory, 256 epochs and 1,024
updates per arm. Three alternating pairs per domain produced:

| Domain | Reference row presentations/s | Prepared row presentations/s | Throughput gain |
|---|---:|---:|---:|
| Intent | 994 | 1,085 | 9.2% |
| Security | 2,419 | 2,547 | 5.3% |
| UI/UX | 1,557 | 1,727 | 10.9% |
| Legal | 5,723 | 6,216 | 8.6% |

All retained weights, loss/selection histories, saved inference and actual-update
continuations matched. Each domain requested 40 families; only its actual ready
projections received loss. No held-out target was prepared, read or scored in
this later run; it supplies no additional quality evidence. The short Intent
regression remains valid. Peak RSS was 914 MB for this sequential benchmark.

```bash
python3 scripts/ops/autoencoder/benchmark_domain_training_throughput.py \
  --output-directory /absolute/fresh/throughput \
  --epochs 256 --repetitions 3 --minibatch-size 6
```

Warm inference wall seconds/span (reference/prepared), including preparation
and reload: Intent 0.02970/0.03391; Security 0.00674/0.00569; UI/UX
0.01589/0.01306; Legal 0.00269/0.00256. Bridge names `[]`, legal-IR metric targets
`0`, prover evaluation false, metric disk cache false, sample memory unused,
workers one: **these are not bridge-on legal-IR evaluation timings**.

```bash
python3 scripts/ops/autoencoder/benchmark_domain_reconstruction.py \
  --phase prepare --output-directory /absolute/fresh/experiment
python3 scripts/ops/autoencoder/benchmark_domain_reconstruction.py \
  --phase fit --output-directory /absolute/fresh/experiment
# The fit prints the digest only after every candidate has completed.
python3 scripts/ops/autoencoder/benchmark_domain_reconstruction.py \
  --phase evaluate --output-directory /absolute/fresh/experiment \
  --freeze-sha256 <exact-printed-digest>
```

Source and input hashes, exact arm identities, completed update budgets and
one-shot markers guard the freeze. An interrupted benchmark needs a fresh output
directory. It is not the distributed resumable runner; existing fleet/Hub and
sparse-update services remain separate.

Development target preparation for 32 rows took Intent 1.426 s, Security
2.132 s, UI/UX 0.656 s, Legal 2.167 s. The separate canonical compiler gate took
0.05564 s/span for its three sentences. Different input paths must not be
combined into a corpus conversion rate.

## Lean and evidence limits

Separate authored native instances passed four actual `lake build DecoderSchema`
checks. The canonical minimum-duration path passed `lake build Legal`; deadline,
prohibition, minimum-duration and empty-vocabulary gates passed. No Mathlib or
downloads were used. Schema builds concern those authored instances, not learned
feature-head outputs, complete domain schemas, or source semantics. No
Constitution span is marked formalized or `roundtrip_ok`.

Future source-decoder work needs independent free-running formula/text holdouts.
The existing aligned Intent source continuation starts fresh Adam and checks its
deadline at epoch boundaries. Persisting moments, cursor and RNG state needs a
versioned continuation and an equal-budget fidelity comparison; this feature
benchmark does not supply that evidence.

The combined test run passed 246 tests. Four existing aligned-source tests were
skipped because their local legal-initialized development parent is absent from
the isolated export; those skipped tests do not establish source-decoder health.
All new preparation, training, continuation, coverage and benchmark tests passed.

Retained artifacts are under
`docs/implementation/reports/evidence/multidomain-training-20261001/`.
Measurements used a clean export of package commit `4425e503a` plus the additive
files in this change, with explicit `PYTHONPATH` and source hashes. Concurrent
uncommitted parser/compiler edits were not included or altered.
