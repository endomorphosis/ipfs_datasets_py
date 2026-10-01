# Historical 8D teacher: fidelity, corrections and performance

Use the preserved 8D model for linguistic feature supervision with explicit
provenance. Its deterministic text-to-IR compiler is a separate producer from
its learned sparse numerical heads. A copied source sentence, target-aware
reconstruction loss, or compiler/model agreement is not independent evidence
that the emitted formulas faithfully represent a law.

## Historical reference

“Two weeks ago” is anchored to September 17, 2026, commit
`21f2dc2c52940c8552be1515d893e107d0564387`, the latest first-parent commit on that
date. All 23 modules in the frozen numerical manifest and the linguistic codec
are byte-identical there and at the previously selected September 19 reference
`ddf6b79467b68159650df81befc288c8553df664`. Snapshot import relocations are
recorded and verified separately.

The history replay loads already-local Git blobs under isolated module names;
it never substitutes another editable package for the current canonical legal
compiler. The panel covers obligations, prohibitions, permissions, exceptions,
conditions, durations, epistemic/doxastic expressions, malformed and nonoperative
text, and existing legal excerpts. Exact equality checks cover token/cue
encodings, full modal IR, vectors, features and all registry family logits.
Equality includes historical errors and abstentions; it is a regression test,
not a semantic accuracy score.

The historical daemon additionally used `DeterministicModalLogicCodec` with
BM25 and F-logic. Later alias and citation changes in that wrapper can change
predicates, frames, vectors and family targets even though the underlying spaCy
codec is unchanged. The history tool also replays that fuller pipeline and
retains its differences. Do not equate the bare linguistic profile with the
complete daemon.

Historical daemon constructor defaults also differ from the bare numerical
constructor. The history receipt records their source expressions and available
literal defaults. Neither those defaults nor the retained June teacher's weight
hash recover the actual CLI configuration of an unseen historical training run.
There is no recovered independent held-out quality curve for that checkpoint.

## Restore the full historical teacher

Use `HistoricalDaemonAutoencoder` when reproducing the old daemon, including
its BM25/F-logic features. It preserves the September 17 wrapper and its 71
constructor defaults. The separate bare `LinguisticAutoencoder` profile remains
available for focused linguistic experiments; those profiles are not equivalent.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.daemon_teacher import (
    HistoricalDaemonAutoencoder, load_checkpoint, load_training_checkpoint,
)

teacher_model = load_checkpoint(
    "/home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json",
    expected_sha256="7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be",
    compute_device="cpu",
)
sample = teacher_model.build_sample(
    title="fixture", section="prohibition",
    text="The agency shall not disclose records.",
)
observation = teacher_model.linguistic_observation(sample)
historical_ir = observation["modal_ir"]
```

`describe()` discloses the assumed historical defaults and any explicit
overrides. Original external prover availability is not reconstructed. Training
uses the original sparse numerical objective and requires disjoint validation
samples. `save_training_checkpoint()` and this module's
`load_training_checkpoint()` bind weights, configuration and source identity.
They reject cross-profile or experimental formula-head bundles.

One inherited bug is intentionally corrected: the old numerical feature cache
key omitted metadata that feature extraction uses. Identical text under a
different title, section, citation or IR could receive stale features, producing
order-dependent updates and different results after reload. The new daemon and
cached linguistic profiles key that cache by the complete legal sample and
limit it to 128 entries by default. Tests compare against fresh historical
models and verify training/reload parity. The frozen baseline retains the bug
for historical comparison; polluted baseline-cache output is not a fidelity
target. Numerical cache entries have no byte cap, so the codec's byte cap below
must not be interpreted as a bound on total model or process memory.

The daemon profile also releases temporary F-logic frames after each observation.
The historical check only reads the current triples but appended frames forever;
repeating a span therefore increased resident bookkeeping. The wrapper delegates
the same checks, preserves caller-preloaded ontology, and removes only frames
added by that call, including on failure. It checks mutable BM25/F-logic/registry
configuration before inference and saving. These changes preserve observed
outputs while preventing silent configuration drift and cumulative frame growth.

## Use the bounded cache and original training

The cache profile preserves the baseline checkpoint's semantic identity. It
stores detached linguistic encodings and modal IR, not live spaCy documents or
weights. Each worker owns a cache bounded by both entry count and retained bytes
(128 entries and 8 MiB by default). Keys include source text, sample ID, citation
and source type. Returned mutable structures are copied; configuration drift
refuses cache reuse.

This codec cache speeds up the **bare linguistic profile**. The full preserved
daemon wrapper above does not use it: wrapper output also depends on BM25 and
F-logic state. It retains the historical computation and its associated costs.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_cached import (
    CachedLinguisticAutoencoder, load_cached_checkpoint,
    load_cached_training_checkpoint,
)

# Existing local teacher, immutable hash; no downloads.
teacher_model = load_cached_checkpoint(
    "/home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json",
    expected_sha256="7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be",
    backend="historical_blank_en", compute_device="cpu",
)

# An independent fresh model for a bounded old-method training check.
student = CachedLinguisticAutoencoder(compute_device="cpu", feature_family_logit_scale=1.0)
training = student.build_sample(title="fixture", section="training",
                               text="The agency shall submit reports.")
tuning = student.build_sample(title="fixture", section="tuning",
                             text="The agency shall submit notices.")
report = student.train_generalizable_projection(
    [training], validation_samples=[tuning], epochs=1, learning_rate=0.01,
    max_seconds=30, max_line_search_attempts=1,
    projection_max_update_families=4, projection_update_backend="python_sparse_batch",
    legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
)
student.save_training_checkpoint("workspace/test-logs/new-cached-linguistic-bundle")
resumed = load_cached_training_checkpoint("workspace/test-logs/new-cached-linguistic-bundle")
```

The feature vectors generated by `build_sample` are deterministic linguistic
hashes, not verified pretrained semantic embeddings. The old target-aware
objective is unchanged. Never infer independent reconstruction quality from its
perfect cosine or zero MSE. Inspect actual accepted sparse updates and evaluate
generalization with separately sourced, disjoint examples.

`StreamedCachedLinguisticAutoencoder` additionally reuses the already tested
streamed transaction-norm implementation. It preserves proposals, objectives,
acceptance and resulting weights. It is explicit opt-in; a small fresh-core
benchmark does not establish the best backend for full-checkpoint training.
Full proposal copying remains a separate performance cost. Neither profile
activates the experimental latent-to-formula head.

Use a private model per training worker. The codec and temporary-frame locks do
not make concurrent training and inference on one mutable weight object safe.
Loading the retained JSON teacher materializes substantially more memory than
its 398 MB file size; cache bounds do not address that weight-storage cost.
The measurements below use CPU and do not establish CUDA throughput.

## Prepare corrected symbolic supervision

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_teacher import LegacyLinguisticTeacher

teacher = LegacyLinguisticTeacher(teacher_model)
sample = teacher_model.build_sample(title="fixture", section="prohibition",
                                   text="The agency shall not disclose records.")
row = teacher.distillation_row(sample, corpus="authored_fixture")
assert row["distillation_mask"]["historical_formula"] is False
feature_target = row["feature_target"]
formula_target = row["formula_target"]  # None if screened out.
```

`feature_target` is the unchanged 8D model output. `formula_target`, when present,
comes from the pinned canonical compiler and is labeled compiler supervision.
The adapter preserves the original linguistic IR alongside corrected canonical
rules, explicit temporal records, diagnostics and a source/producer binding.
It never changes old samples or sparse weights. This is not a new neural decoder
and not independent compiler validation.

The initial candidate policy covers a single direct obligation, prohibition or
permission. It checks actor/action preservation, numeric coverage, explicit
conditions/exceptions/temporal information and exact canonical cycle identity
under the original parser-supplied vocabulary. Empty vocabulary still abstains.
The prohibition correction retains `F`; the deadline keeps `within_duration`
with quantity 10; the minimum keeps `minimum_duration` with quantity 20.
The deadline is never rendered as a Lean minimum threshold.

The historical IR itself still emits `O` for “shall not disclose records” and
omits quantities from explicit formula fields for the 10-day deadline and
20-day minimum examples. These are historical limitations, not newly learned
repairs. The new adapter fixes which labels a distillation job consumes without
silently changing the historical teacher. Its canonical prohibition target is
inspectable structured logic, for example:

```json
{"rules": [{"actor": "agency", "modality": "F", "action": "disclose",
            "object": "records", "conditions": [], "exceptions": [], "temporal": []}]}
```

Known ambiguous or unsupported cases are excluded from formula targets: “may
not,” negated requirements, “not only,” coordinated or multiple norms, unsupported
temporal scopes, quoted/interpretive text, and missing source bindings.
Unrepresented restrictions such as “only if,” “without,” and object quantifiers also
exclude formulas. Samples are checked against a fresh profile-built source
sample before reuse, so matching text with a substituted IR is rejected.
Constitution and unknown-corpus inputs cannot produce formula targets. They can
still retain diagnostic feature observations. Unsupported logic families are
reported; their presence in the registry does not make them qualified targets.

The adapter's compiler-target cache is also bounded, and it checks producer
source identity before and after each observation. A concurrent producer edit
requires a fresh process instead of returning stale evidence. A cached target
does not cache model predictions: subsequent training still changes numerical
inference normally.

Rows record the lineage/profile, codec identity and initial checkpoint digest.
The initial digest identifies loaded weights; it does not attest the current
weights after training. A current-weight digest must be attached at the batch
or checkpoint boundary when publishing a distillation corpus.

Candidate masks permit deliberately labeled weak supervision. They do not
establish full source equivalence, a legal judgment, or proof admission. Keep
them distinct from independently reviewed semantic labels when distilling the
new architecture. Use `distillation_row()` so screened-out formulas become
`None` in the target field while their evidence remains available for repair.

## Reproduce the checks

Run in a fresh process from the canonical dataset checkout, with its directory
first on `PYTHONPATH`. All data and models must already exist locally.

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/legacy_teacher_history.py --help
PYTHONPATH="$PWD" IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0 \
python3 scripts/ops/legal_ir/validate_legacy_linguistic_teacher.py \
  --output-directory workspace/test-logs/new-legacy-teacher-audit \
  --retained-teacher /home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json
```

The integrated audit compares original/cached outputs, bounded real training,
checkpoint resume, sampled teacher targets, and an actual `lake build Legal`
for the supported minimum-duration rendering. It preserves within-duration
non-renderability and does not mark the Constitution formalized. Real US Code
excerpts have retained source offsets and hashes but no invented gold labels.

Timing receipts state sample counts, cache warmness, bridge names, prover flag,
workers and device. Bridge-off runs with zero targets are feature diagnostics,
not bridge-on legal-IR speed measurements. Benchmarks do not download weights,
upload rows, replace archived checkpoints, or restart the running census.

## October 1 validation results

[Recorded evidence](../implementation/reports/evidence/legacy-teacher-20261001/evidence-index.json)
includes the [historical replay](../implementation/reports/evidence/legacy-teacher-20261001/history.json),
[release report](../implementation/reports/evidence/legacy-teacher-20261001/release-report.json),
source hashes, exact sampled texts, actual Lean source, and test receipts.
Production Python files were tested from an isolated Git export of staged tree
`31ef6db45c7851457f3fd1e2f8bfda5583f95470`; the separately recorded workspace
gate check resolves to the canonical checkout. No HACC parser was substituted.

- All 76 historical bare-codec comparisons matched (38 cases, two backends).
  Full-wrapper replay exposed drift in three of six current-wrapper examples;
  the preserved daemon passes seven short historical comparisons and two long
  US Code IR comparisons.
- The retained teacher's numerical predictions match the old daemon on four
  cases, including both long US Code examples. Its SHA-256 is unchanged. The
  cached bare profile also matches the retained teacher on eight probes under
  each backend. This is source/runtime parity under the stated configuration,
  not recovery of an unrecorded original producer configuration.
- All 256 selected regression checks pass. The initial export passed 254;
  two existing joint-formula Lake tests rejected its missing Git metadata.
  Both passed after initializing that isolated validation repository, without
  changing production code or weakening the tree pin.
- The final end-to-end run passed in 182.59 seconds, with peak RSS 3.03 GiB.
  It checked 58 spans under both backends: 32 authored probes, 12 existing
  round-trip fixtures, six historical repository US Code excerpts and eight
  locally sampled excerpts from eight titles. No fresh independent gold labels
  were created for those legal excerpts.
- Original and cached training accepted bounded epochs with identical complete
  states, exact reload predictions and exact resumed-versus-uninterrupted
  states. Tests also cover the full daemon's original trainer and the optional
  streamed norm method. These train fresh small cores, not the archived 398 MB
  teacher. The tiny training/tuning split is not a generalization canary.
- Actual `lake build Legal` passed for the numeric 19/20 boundary derived from
  the minimum-duration example. The three canonical gates and empty-vocabulary
  abstention passed. The within-duration deadline remains non-renderable by the
  threshold renderer. This is not admission of the sampled laws.

The target policy retained nine compiler-supervised weak-label candidates and
49 feature-only rows per backend. All eight newly sampled US Code excerpts
remained feature-only. The Constitution remains unformalized. Historical
formula mistakes were not promoted into neural or independently verified gold
labels; the new latent-to-formula decoder remains a separate experiment.

### Performance and remaining costs

These are wall times from the same release run, baseline → optional cached
**bare linguistic profile**. Inference uses 58 spans; the first numerical pass
comes after linguistic preparation, so it is not a cold-process benchmark.
Warm values are medians of three passes including that first pass.

| Measurement | Blank English | Local `en_core_web_sm` |
| --- | ---: | ---: |
| Preparation, ms/span | 9.84 → 11.37 | 21.31 → 23.99 |
| First numerical inference pass, ms/span | 102.84 → 38.06 | 116.08 → 43.50 |
| Warm numerical inference, ms/span | 14.05 → 13.90 | 15.32 → 15.78 |
| Bridge-off evaluate, four spans | 25.65 → 26.30 ms | 29.93 → 31.41 ms |
| One fresh-core epoch, one train/one tuning span | 0.459 → 0.324 s | 0.630 → 0.352 s |

Configuration: CPU, `python_sparse_batch`, four update families, one line-search
attempt, 30-second cap per training call; bridge names `[]`, prover evaluation
false, one worker, metric disk cache disabled, sample memory false, temperature
zero. The process and linguistic features were warm before numerical inference;
the codec cache started empty before preparation. `legal_ir_target_count` is
zero. **Bridge-on evaluate was not measured**, and none of these numbers is a
faster legal-IR bridge result.

Caching clearly helped the first numerical pass in this run. It did not improve
steady-state performance consistently: retained-checkpoint warm inference on
eight probes was 32.79 → 33.40 ms/span for blank English and 34.17 → 37.08
ms/span for local spaCy. Small-core epoch timing is noisy and does not establish
a sustained training speedup. Cache and streamed profiles therefore remain
explicit choices. The full preserved daemon is a separate, more expensive path:
on the two long passages its retained-model numerical inference was 1.843 →
1.876 s/span and 3.068 → 3.185 s/span (one observation each, after IR preparation),
with exact outputs and additional context/source checks. No full-daemon speedup
is claimed.

The frame-retention fix prevents cumulative temporary ontology growth. Reporting
now retains identical historical/preserved long-span IR once, with hashes for
both, reducing that artifact from about 79.5 MB to 39.8 MB and avoiding its
duplication in the 0.875 MB summary. Full artifacts remain in the local evidence
directory with checksums. Weight materialization, full wrapper/decompiler work,
and proposal copying still need separate profiling before production-scale
training claims. This run neither uploads to Hugging Face nor restarts a worker.

## Optional reuse of identical readouts within one encode call

The separate `legacy_v1.linguistic_view_reuse` module avoids recomputing an
identical LegalIR view distribution several times during numerical encoding.
It supports both preserved linguistic profiles and does not modify their frozen
code, representations, objectives or checkpoint formats. Select it explicitly;
it is not enabled automatically by hardware detection.

| Loader `profile` | Model class |
| --- | --- |
| `historical_daemon` | `ViewReuseHistoricalDaemonAutoencoder` |
| `cached` | `ViewReuseCachedLinguisticAutoencoder` |
| `streamed_cached` | `ViewReuseStreamedCachedLinguisticAutoencoder` |

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_view_reuse import (
    load_checkpoint, load_training_checkpoint,
)

teacher_model = load_checkpoint(
    "/home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json",
    expected_sha256="7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be",
    profile="historical_daemon", compute_device="cpu",
)
sample = teacher_model.build_sample(
    title="fixture", section="prohibition",
    text="The agency shall not disclose records.",
)
encoded = teacher_model.encode(sample, use_sample_memory=False)
decoded_vector = teacher_model.decode(encoded)
assert teacher_model.describe()["view_reuse"]["last_encode"]["retained_after_encode"] == 0

# Resume an existing bundle created by this selected preserved profile:
# resumed = load_training_checkpoint(existing_bundle, profile="historical_daemon")
```

Direct model construction and `train_generalizable_projection()` use the same
arguments as their corresponding preserved classes. The strict loaders verify
existing local files and retain checkpoint provenance; they never download
weights. A bundle must match the selected profile. The `cached` and
`streamed_cached` bundle loaders also accept the existing runtime cache bounds.
The historical daemon retains its fixed cache configuration.

The memo exists only inside one `encode()` call. Its key includes a SHA-256 of
the complete legal sample, the weight-state object and tracked revision,
sample-memory mode, actual target distribution and ordered family candidates.
The complete sample includes citation/title/section and nested IR/parser/frame
metadata, preserving the corrected source isolation. Existing configuration and
source guards run on memo hits as well as misses. Different weights or targets
cannot reuse an earlier readout. The first readout executes the original
numerical method, and callers receive independently mutable dictionaries.

At most eight readouts are retained, and all are discarded when encoding
returns or raises. Source JSON is hashed transiently rather than retained as a
large key. This is an entry bound, not a byte bound: temporary readout size
depends on the number of IR families. There is no prediction cache across
calls, samples or epochs. Optimizer updates outside `encode()` still execute
the original methods, and training evaluations can use the optimization without
changing the acceptance criteria. Use separate model instances for concurrent
training; this does not provide atomic inference over concurrently mutated
weights.

Nineteen focused regression tests passed, covering weighted output equality,
configuration/source guards, state and target changes, mutable source metadata,
failure cleanup, accepted training reports, complete weight states, checkpoint
reload and resumed updates for all three profiles. The reports match after
excluding wall-clock timing fields. This establishes numerical parity on the
tested cases, not formula fidelity or proof admission.

### Additional October 1 numeric benchmark

The [recorded receipt](../implementation/reports/evidence/teacher-student-improvements-20261001/legacy-view-reuse.json)
binds the implementation source hash and records every timing repetition. On
one machine using CPU, three authored gate cases were measured after warming
the existing feature caches. Each timing group made ten passes over all three
cases; seven groups alternated baseline and optimized order. The table reports
median wall time per span for numerical `encode()` only.

| Profile | Existing implementation | With encode-local reuse |
| --- | ---: | ---: |
| Cached bare linguistic profile | 9.128 ms/span | 8.708 ms/span |
| Full historical daemon profile | 19.198 ms/span | 11.986 ms/span |

Configuration: bridge names `[]`, `legal_ir_target_count=0`, prover evaluation
false, metric disk cache disabled (`IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0`),
one worker, `use_sample_memory=False`. These are warm numeric measurements with
fresh small cores. No bridge-on evaluate or actual Lake build ran in this
benchmark, and it did not measure full wrapper compilation/decompilation,
retained-checkpoint throughput, CUDA or multiple machines.

Five fresh one-epoch runs per implementation, each using one training and one
validation span, accepted identical updates and produced identical complete
states. Their timing varied: the cached profile was slightly slower in this
receipt, while the daemon was faster; an earlier measurement showed no daemon
epoch improvement. **No stable training speedup is established.** Proposal
copying and bookkeeping remain separate costs. The numerical inference result
above is not a faster legal-IR bridge run and does not change qualification.
