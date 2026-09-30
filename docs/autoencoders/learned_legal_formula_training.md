# Train a source-conditioned legal formula decoder

`source_conditioned_formula_v1` is a separate, explicit learned sequence model.
It maps source text to one complete typed-deontic rule. Its training loss updates
the source encoder, autoregressive decoder and formula output matrix. Inference
accepts source strings only and emits actual canonical IR candidates.

This starts from fresh parameters. It does not reinterpret the legacy 8D or
current 384D weights as formula-decoder parameters. Those lineages keep their
existing numerical objectives, checkpoint formats and compiler-guided modes.

## Why a separate codec and lineage

The historical PGIR implementation already supplied grammar validators,
token-logit machinery and a constrained beam search. Its training step updated
family classification only. Its tokenizer also hashed identifiers into buckets,
discarded numeric/list structure and could truncate token sequences. Its source
surface IDs did not encode the source words. Wiring those IDs to a new loss
would not yield a reversible source-to-formula model.

The new `legal_formula_codec` retains the existing `CanonicalRoundTripIR` and
`CanonicalRule` contracts and reuses the PGIR deontic validator after an explicit
validation projection. It supplies a separately versioned reversible token
grammar. Every rule facet survives: modality, actor, action, object, conditions,
exceptions and temporal atoms. Exact multiword atoms remain strings. Input
qualifier arrays must already be sorted and unique; normalization is never
performed silently.

This is deliberately a bounded first implementation:

- One rule per input; `O`, `P` and `F` modalities.
- At most 64 source tokens and 64 target tokens; no truncation or context increase.
- At most four atoms per qualifier facet and 4,096 entries per vocabulary.
- Source words and exact output atoms are fitted from training examples only.
- Unknown source words, unknown target atoms, invalid structures and ambiguous
  generation abstain or reject explicitly. There is no retrieval or compiler fallback.

Temporal and exception atoms are preserved in typed-deontic IR. This does not
claim a learned TDFOL, DCEC, FOL or frame-logic serializer, nor validation by
every downstream family backend. The historical tokenizer and numerical
autoencoders remain unchanged.

## Inputs and training

Run from the canonical package checkout in a fresh process with `PYTHONPATH`
pointing at that checkout. A source pin rejects the separate HACC tree.
Each training or tuning example is a closed object:

```json
{
  "id": "authored-prohibition-1",
  "source_text": "The agency shall not disclose records.",
  "canonical_ir": {
    "rules": [{
      "modality": "F", "actor": "agency", "action": "disclose",
      "object": "records", "conditions": [], "exceptions": [], "temporal": []
    }]
  }
}
```

Targets are supplied explicitly for supervision. The trainer does not call a
compiler to invent labels. Compiler-produced targets need their own evidence
and quality policy before a production training campaign. Training and tuning
source identities and IDs must be disjoint; the API does not require different
complete targets. The checked-in diagnostic fixture additionally separates
complete targets across training, tuning and held-out splits.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes

runtime = runtimes.open_runtime("legal_ir", "source_conditioned_formula_v1")
result = runtime.train(
    training_examples, validation_samples=tuning_examples,
    epochs=100, max_seconds=120, batch_size=8, learning_rate=0.008,
)
generated = runtime.decode_formal_logic([
    "The agency shall not disclose records."
])
```

The model is a small GRU source encoder, attention GRU decoder and output linear
layer, trained with teacher-forced token cross-entropy and Adam. Generation is
greedy at temperature zero under structural grammar masks. Grammar masks constrain
syntax; the model selects semantic values. No gold rule or teacher token is an
inference argument. A zeroed output head abstains instead of letting a grammar
mask appear to generate a learned formula.

Training and inference are separate methods. The first version uses CPU float32
with explicit bounded batch/model sizes. Sessions belong to one worker. Thread
allocation belongs to the caller; the CLI uses one PyTorch thread. No automatic
CUDA switch, pretrained model download or fleet launch is performed.

## Save, reload and resume

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_learning as learning

artifact = learning.save_checkpoint(result["checkpoint"], fresh_checkpoint_path)
decoder = runtimes.open_formal_decoder(
    "legal_ir", "source_conditioned_formula_v1",
    checkpoint=artifact["path"], expected_sha256=artifact["sha256"],
)
report = decoder.infer(source_strings)
```

Checkpoints are bounded JSON, written exclusively to a new path. They contain
model tensors, Adam moments, the vocabulary, configuration, implementation
hashes, exact training/tuning manifest hashes, completed epochs, optimizer steps
and the row cursor. They do not store training examples or a retrieval index.
Vocabulary atoms are necessarily retained as model metadata.

Resuming requires the same ordered manifests and optimizer/model settings.
Epoch shuffles derive deterministically from seed plus epoch; there are no
stochastic layers. `epochs` requests additional completed epochs, including
completion of an already partial epoch. Deadlines are checked before each
batch; an in-flight batch finishes and its complete state/cursor is retained.
Preparation, serialization and one in-flight batch can extend wall time beyond
the training deadline. Incomplete metric passes report their actual coverage.

The existing owner-controlled DuckDB registry also supports this lineage:

```python
first = runtime.register_candidate(registry, fresh_candidate_directory)
resumed = runtimes.load_version(
    registry, first["version_id"], domain="legal_ir",
    version="source_conditioned_formula_v1",
)
resumed.train(training_examples, validation_samples=tuning_examples,
              epochs=10, max_seconds=60, batch_size=8, learning_rate=0.008)
second = resumed.register_candidate(registry, another_fresh_directory)
```

Register a pending candidate before training another version. Versions bind the
exact numerical parent; changed vocabularies, source implementations, settings
or manifests cannot silently resume under the old variant. Registration stores
the artifact and report without granting inference promotion or proof authority.
This adapter does not add native fleet transport, sparse sequence-model updates
or Hugging Face synchronization. Those require a separately validated wire codec.

Use `load_version` when continuing a registered candidate. Opening a standalone
checkpoint file does not establish its registry parent; registration of that
resumed file session is rejected until the exact registry lineage is used.

## Local commands

The diagnostic fixture is authored synthetic data, not US Code or Constitution
gold supervision. Its held-out split is never consumed by the training command.

```bash
PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/train_learned_formula_decoder.py train \
  --corpus tests/fixtures/legal_formula_learning/v1.json \
  --output workspace/my-formula-run --epochs 100 --seconds 120

PYTHONPATH="$PWD" python3 scripts/ops/legal_ir/train_learned_formula_decoder.py infer \
  --checkpoint workspace/my-formula-run/checkpoint.json \
  --sha256 '<hash returned by training>' \
  --input /absolute/path/source-strings.json --output workspace/my-formula-inference.json
```

For CLI continuation, supply `--resume` and `--resume-sha256` to `train`, with a
fresh output directory and matching settings. Input sources for `infer` are a
JSON array of strings. Output includes full canonical ASTs, readable formula
notation, generation status and abstention reasons.

## How to interpret results

Teacher-forced token loss shows whether the reconstruction objective is being
optimized. Free-running exact-rule accuracy and per-facet errors measure the
separate generation task. Compare a fixed held-out panel against an untrained
initialization, zeroed head and shuffled-source control. Preserve polarity,
exception and temporal failures in reports. In-sample exact reconstruction does
not establish semantic generalization.

All checkpoints and candidates remain unqualified, unadmitted and unformalized.
Only the existing source-bound `lake build <Lib>` path can grant a Lean admit;
no Lake call occurs in this trainer. No Constitution span becomes `roundtrip_ok`.

The [measured smoke](learned_legal_formula_smoke_20260930.md) retains all predictions,
including a held-out exception omission. The installed CLI was also exercised
through [training, source-only inference and resume](../implementation/reports/evidence/legal-lineages-20260930/learned-formula-cli-smoke.json).
