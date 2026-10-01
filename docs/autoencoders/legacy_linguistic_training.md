# Preserved 8D linguistic feature training

Use `legacy_v1.linguistic.LinguisticAutoencoder` for the old linguistic/IR
feature method. It owns a frozen spaCy codec and the original 8D numerical
trainer. It rejects latent-to-formula targets and checkpoints. The experimental
[joint latent formula head](modal_joint_formula_training.md) remains a separate
opt-in path and has not established real legal fidelity.

See the [2026-10-01 validation report](legacy_linguistic_validation_20261001.md)
for actual training, retained-teacher compatibility, resume checks and observed
historical semantic limitations.

## What is preserved

The codec comes from `ddf6b79467b68159650df81befc288c8553df664`.
Its only source changes relocate four imports to the already frozen legacy
parser, samples, registry and IR modules. A separate manifest verifies the codec;
the original numerical snapshot and archived checkpoints are unchanged.

The flow is text → linguistic tokens and modal cues → deterministic modal IR
and feature-hashed 8D vectors → sparse learned corrections and family/view
heads. `decode()` returns a vector. `linguistic_observation()` returns inspectable
tokens, features and structured formulas. These formulas come from the
deterministic linguistic compiler, not a learned latent formula decoder.

The old spaCy feature decoder is deterministic and has no trainable parameters.
Original projection training updates the sparse numerical weights around that
feature decoder. It does not train spaCy or a formula-token neural network.

Two explicit backend configurations are available:

| Backend | Linguistic pipeline | Purpose |
| --- | --- | --- |
| `historical_blank_en` (default) | Blank English tokenizer and sentencizer | Preserve the fallback feature configuration used in the historical daemon |
| `local_en_core_web_sm` | Already installed trained spaCy pipeline | POS, lemma and dependency features; fails if unavailable, never downloads |

This conserves the bare historical spaCy feature codec. The historical daemon
also wrapped it with `DeterministicModalLogicCodec`, BM25 and F-logic. It is not
a replay of that entire daemon configuration. Canonical typed-deontic
compiler/decompiler and proof services remain the current pinned workspace.

## Build, infer, train and resume

Start a fresh process from the canonical checkout:

```bash
cd /home/barberb/lift_coding/external/ipfs_datasets
export PYTHONPATH="$PWD"
export IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0
```

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import (
    LinguisticAutoencoder, load_training_checkpoint,
)

model = LinguisticAutoencoder(backend="historical_blank_en", compute_device="cpu")
train = model.build_sample(title="5", section="fixture-training",
                          text="The agency shall submit reports.")
tuning = model.build_sample(title="5", section="fixture-tuning",
                           text="The agency shall submit notices.")

observation = model.linguistic_observation(train)
print(observation["modal_ir"]["formulas"])
vector = model.decode(model.encode(train, use_sample_memory=False))
metrics = model.evaluate([tuning], use_sample_memory=False,
                         legal_ir_bridge_names=(), legal_ir_evaluate_provers=False)
report = model.train_generalizable_projection(
    [train], validation_samples=[tuning], epochs=1, learning_rate=0.01,
    max_seconds=30, max_line_search_attempts=1,
    projection_max_update_families=4,
    projection_update_backend="python_sparse_batch",
    legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
)

# Choose a new directory; saving refuses to overwrite an existing bundle.
model.save_training_checkpoint("workspace/test-logs/my-legacy-linguistic-checkpoint")
resumed = load_training_checkpoint("workspace/test-logs/my-legacy-linguistic-checkpoint")
```

The profile requires nonempty training and validation sets with disjoint sample
IDs and normalized text. Repeatedly using validation for selection makes it a
tuning set, not a held-out generalization canary. Training keeps the original
objective, update proposals, line search and acceptance logic. A deadline bounds
attempted work; it does not guarantee an accepted epoch.

The checkpoint bundle records the sparse state, configuration, codec and local
pipeline identity. Resume checks those bindings. A bare old JSON state cannot
establish its historical linguistic configuration: supply and document that
configuration explicitly instead of guessing from vector width.

`decode_formal_logic()` defaults to the separately attributed canonical compiler
in this profile. The generic guided-compiler mode is rejected because its
default codec is a different pipeline. Use `linguistic_observation()` to inspect
the conserved linguistic IR itself.

`build_sample()` gives deterministic linguistic feature vectors explicit
provenance. They are not pretrained semantic embeddings. The unchanged lower
level 8D API still supports externally supplied vectors when their actual
provenance is known.

## Reproduce the bounded smoke

```bash
PYTHONPATH="$PWD" IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE=0 \
python3 scripts/ops/legal_ir/smoke_legacy_linguistic_autoencoder.py \
  --output-directory workspace/test-logs/legacy-linguistic-local-smoke
```

Use a fresh output directory. The smoke exercises feature/IR extraction,
deterministic text rendering, original sparse training, checkpoint reload and
resumed-versus-uninterrupted updates. It records actual backend identities,
sample counts, elapsed times, vector losses, reusable weight changes and the
separate canonical compiler gates. It does not start a corpus service or upload
weights.

## Interpret the evidence

Historical reconstruction is target-aware: the safety projection can return
the target exactly. With linguistic hashes as both the feature base and target,
reconstruction may already be perfect before training. Neither case establishes
learned reconstruction fidelity or semantic formula correctness. Inspect actual
sparse state changes and the reported family/view objectives as well.

The authored smoke exposes known historical semantic limitations on both
backends. The linguistic IR for “The agency shall not disclose records.” emits
deontic `O` (obligation), while the pinned canonical compiler correctly emits
`F` (prohibition). Numeric durations in the 10-day deadline and 20-day minimum
are not explicit in the emitted linguistic formula fields. The deterministic
decompiler still reproduces the source text from provenance, so a matching text
round trip does not fix these omissions. The smoke records operational success
separately from these conflicts and coverage gaps. The frozen codec is preserved
for reproducibility and training; it is not a qualified legal formalizer.

For bridge-off feature training with a small proposal budget, the optional
[active-family scheduler](reconstruction_training.md) can reach the existing
family update directly. It keeps the historical strict objective and regression
checks, rolls back rejected or late candidates, and supports bounded adaptive
learning rates. It does not replace this preserved training API or make its
target-aware reconstruction an independent fidelity measurement.

Bridge-off evaluation has `legal_ir_target_count == 0`; its time is not a
legal-IR performance measurement. The smoke reports that distinction, leaves
sample memory disabled, and records whether the metric disk cache is disabled.

The profile does not confer admission. Canonical compiler output, matching
decompiled text and low loss remain evidence with separate meanings. Only the
actual required `lake build <Lib>` admission path can admit Lean. The
Constitution remains unformalized. The new latent-to-formula head still needs
independent legal fidelity testing before it can replace this preserved path.
