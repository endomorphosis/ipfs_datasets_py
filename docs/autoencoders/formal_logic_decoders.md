# Formal output from the versioned autoencoders

Use `decode_formal_logic()` for formal candidates. The historical legal
`decode()` method returns an embedding vector; `infer()` remains numerical
inference. A vector is not a formula. The common runtime previously lacked a
formal-output method, even though compiler-guided legal formulas were available
through a separate census implementation.

| Runtime | Formal output | Important limit |
| --- | --- | --- |
| Legal `legacy_v1`, `legacy_v1_optimized`, `current_v2` | Complete modal ASTs from the model-guided compiler, or strict typed-deontic compiler rules | These checkpoints have no independent learned formula-token decoder |
| Security, Intent, UI/UX `native_v1` | Native expressions reconstructed from model output scores and a training-fitted structural head | Input is compiler-prepared structural features; the head supports fixed shapes and known vocabulary |
| Security, Intent, UI/UX `native_v2` | Same structural readout over the saved v2 numerical decoder | Read-only formal factory; the common v2 training/registry adapter is still separate work |

All paths preserve the domain's projection descriptors. They do not translate
every domain into legal deontic logic or claim that every downstream logic
backend accepts their output. None grants proof, qualification or formalization.
Only the separate source-bound `lake build <Lib>` path can grant a Lean admit.
The Constitution remains unformalized.

## Legal formulas

Start in a fresh process with `PYTHONPATH` pointing at the canonical checkout.
Use the existing lineage-specific sample builder and correctly dimensioned
vectors; the formal API validates their provenance and dimensions.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes

runtime = runtimes.open_formal_decoder(
    "legal_ir", "legacy_v1", checkpoint=local_checkpoint,
    expected_sha256=checkpoint_sha256, compute_device="cpu",
)
report = runtime.decode_formal_logic(samples, mode="guided_compiler")
for row in report["rows"]:
    print(row["status"], row["sample_id"])
    for formula in row["formal_outputs"]:
        print(formula["formula_text"])
        print(formula["expression_format"], formula["payload"])
```

The same method is available directly on each lineage's `Autoencoder` facade.
It runs inference/compilation only. It does not train, load additional weights,
call external provers or execute Lake. Keep one mutable model/decoder instance
per worker, or serialize access.

`guided_compiler` uses the existing autoencoder-guided compiler. It retains
model guidance, full formal ASTs, origin and target-conditioning metadata, and a
separate strict canonical compiler observation. Their comparison is diagnostic:
agreement is not independent validation. `canonical_compiler` explicitly uses
the typed-deontic compiler and parser-supplied string atoms; `model_used=false`.
Empty vocabulary still abstains. `independent` returns
`checkpoint_has_no_learned_formula_decoder` and emits no formula.

Smoke observations exposed an existing disagreement for
“The agency shall not disclose records.” The guided route emits `O` with
prohibition metadata; the canonical route emits an `F` rule. The report labels
this `semantic_conflict` and preserves both results. It does not silently
substitute the canonical formula for a model result. Minimum-duration scope can
also be missing from the guided formula, producing `comparison_incomplete`.
Callers must inspect these statuses instead of treating a nonempty output as
semantic success. Multi-formula comparisons can be `not_comparable`.

`formula_text` is readable notation. The full typed AST is authoritative, with
conditions, exceptions and temporal metadata retained. Batches are bounded to
128 spans and 64 MiB of serialized output. Duplicate full codec documents are
explicitly omitted by default; request `include_observation_documents=True`
when needed. ASTs, guidance and document hashes remain in the compact report.

## Native expression reconstruction and persistence

```python
runtime = runtimes.build_native_runtime(
    "ui_ux_ir", "native_v1", training_targets,
    projection_ids=["ui_ux_ir:flogic"], ir_schema="ui_ux_ir/my-schema-v1",
)
runtime.train(training_targets, validation_samples=tuning_targets, epochs=16)
formulas = runtime.decode_formal_logic(tuning_targets)
candidate = runtime.register_candidate(registry, fresh_candidate_directory)
reloaded = runtimes.load_version(
    registry, candidate["version_id"], domain="ui_ux_ir", version="native_v1",
)
assert reloaded.decode_formal_logic(tuning_targets) == formulas
```

The default builder fits structural metadata from the original training targets
only. It adds no new neural parameters: leaf values come from the trained
autoencoder's reconstructed scores. Ties, nonpositive evidence, unsupported
shapes and invalid native structures abstain. No inference target is copied as
a fallback. See [native formal decoders](native_formal_decoders.md) for exact
score gates, validation scopes and projection output fields.

New candidates save the structural head with numerical weights and Adam state.
Their immutable registry variant binds the modality contract, feature basis and
head digest; load verifies the artifact, source identities and exact parent.
Changing the structural head creates a different variant. Later numerical
training may use new rows compatible with the original basis; it does not
refit that basis or head implicitly.

Old numeric checkpoints remain readable. Without a structural head, formal
decoding returns `decoder_head_required`. Fit a head with
`native_formal_decoder.train_formal_decoder(feature_space, original_training_targets)`
and pass it explicitly to `decode_formal_logic(..., decoder_head=head)` for
read-only inspection. This does not migrate the saved candidate. Use
`with_formal_decoder=False` only when intentionally building a numeric-only
runtime.

For native v2, fit the head against the exact streamed feature space and open:

```python
decoder = runtimes.open_formal_decoder(
    "security_ir", "native_v2", feature_space=v2_space,
    state=v2_state, decoder_head=v2_head,
)
result = decoder.decode_formal_logic(evaluation_targets)
```

Predicted source references, hashes, review status and confidence inside a
candidate are model outputs, not verified provenance. Native syntax validation
does not establish held-out semantic accuracy, open-vocabulary generation,
execution authority or compatibility with all logic-family backends.

## Reproducible checks

The unit tests cover every listed runtime/domain, old checkpoint compatibility,
head persistence and resume, cross-domain rejection, source/head tampering,
ambiguity abstention and actual numerical training. Small authored inputs and
synthetic legal vectors are plumbing diagnostics, not semantic qualification.

Actual full output samples are retained in
[legal smoke evidence](../implementation/reports/evidence/legal-lineages-20260930/formal-decoder-smoke.json)
and [native trained smoke evidence](../implementation/reports/evidence/legal-lineages-20260930/native-formal-decoder-smoke.json).
The legal run has no metric bridges and zero legal-IR targets; its timings must
not be presented as bridge-on legal-IR performance.
