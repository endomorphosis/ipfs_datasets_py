# Source span LegalIR runtime

Select `legal_ir:source_span_formula_v1` to load an existing source-span
checkpoint through the shared runtime interface. The adapter uses
`legal_span_formula.load_checkpoint` and `SpanLegalFormulaDecoder`; predictions,
copied Unicode spans, diagnostics, abstentions and authority flags pass through
unchanged.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry

runtime = autoencoder_runtime_registry.open_formal_decoder(
    "legal_ir", "source_span_formula_v1",
    checkpoint_path=local_checkpoint_path,
    checkpoint_sha256=independently_retained_file_sha256,
)
result = runtime.infer(["The agency shall disclose records."])
```

`open_runtime` accepts the same binding. Both factories require a local path
and an exact lowercase SHA256 of its raw bytes. The existing loader checks
canonical path, regular-file bounds, read stability, unique JSON keys, schema,
lineage, implementation, configuration, tensor shapes and optimizer state.
Checkpoint compatibility includes the original owner's Torch-version and
implementation checks. Older states require a separately qualified migration
when those contracts differ.

For a checkpoint configured with a 384-dimensional context, supply one vector
per source string:

```python
result = runtime.decode_formal_logic(
    source_texts, context_vectors, latent_ablation="none",
)
```

The direct owner's `none`, `zero`, `rotate` and `disabled` controls are available.
Rotation requires at least two rows. A checkpoint with dimension zero accepts
source strings alone; a checkpoint with dimension 384 requires matching finite
vectors, including when conditioning is disabled. No width conversion, default
vector or source normalization is introduced.

`runtime.describe()` distinguishes `checkpoint_file_sha256`, the raw loaded
file identity, from `checkpoint_sha256`, the direct decoder's canonical content
identity. Retain both in an execution receipt. It also reports the actual latent
dimension/enabled flag and optimizer-step count. The prediction report retains
its original canonical checkpoint hash and schema.

Capabilities are `load_checkpoint`, `infer` and `decode_formal_logic`. Training,
candidate registration and persistent DuckDB `load_version` require separate
compatible interfaces. This profile remains distinct from the fixed-vocabulary
`source_conditioned_formula_v1` and the caller-scope
`source_conditioned_grouped_v2` decoder.

The existing one-rule grammar, 256-source-token cap, source-copy restrictions
and refusal behavior remain in force. Runtime compatibility establishes an
execution route; semantic qualification and promotion require their own
evidence.

The enclosing workspace's `artifacts/legal-source-span-runtime-20261016-01/`
retains the focused qualification attempts, exact executed source and tests.
Fixtures use small untrained CPU checkpoints and controlled heads for successful
Unicode decoding. They measure interface compatibility, not learned legal
accuracy. No archived model or statutory training run is used.
