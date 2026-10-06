# Recovered IR checkpoint and cached replay interfaces

The October 6, 2026 integration review found that Git retained earlier decoder work in its ancestry while later canonical source snapshots omitted callable modules and tests. This recovery restores the optional interfaces from `73db2c8f3edb9fbdfc5decb0e8f12bb4e86e10f3` and appends their four public entry points to the current checkpoint loader. All existing loader code, immutable checkpoint descriptors, and default Legal inference optimizations remain intact.

These interfaces connect explicitly selected, existing checkpoint packages to their authenticated cached inputs and original fitting corpora. They preserve useful source and decoder work for subsequent experiments. The recovery does not establish that a checkpoint can autoformalize arbitrary new text.

## Public entry points

Import `checkpoint_hub` from the selected workspace package tree:

```python
from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub
```

| Entry point | Additional required bindings | Returned scope |
| --- | --- | --- |
| `open_ir_cell_autoencoder` | Package manifest pin, cached split, ordered row IDs | An optional runtime with `infer_cached()` for the fixed authenticated rows |
| `preflight_ir_cell_cached_targets` | The same package/cache bindings | Metadata and canonical target encoding coverage; no model loading |
| `open_ir_original_corpus_autoencoder` | Package manifest pin, original corpus pin, corpus split, ordered row IDs | Fixed original Intent/Security corpus replay |
| `open_ir_decoder_format_autoencoder` | The original corpus bindings and an explicit format request | Original Intent/Security fragment replay with a bound output format |

Every entry point also requires the directory plan pin, inventory pins, and a closed request containing `ir_family_id`, `dimension`, `dimension_role`, `task_id`, and `checkpoint_sha256`. A file pin contains its exact path, byte count, and SHA256. Select a checkpoint explicitly; an inventory row or matching width cannot supply this choice.

The optional replay path supports authenticated existing 384D assets. Original fragment contracts support `intent_ir/intent_rich_ast` at `intent-rich-grammar/v1`, and `security_ir/program_expression` at `program-ir/v1`. These are distinct native output fragments. A fragment decoder cannot substitute for a complete document, original source text, a different schema, or all logic-family projections.

## What is authenticated

[Cell routing](../../ipfs_datasets_py/logic/formalization/autoencoder/ir_cell_routing.py) checks the declared family, width, role, task, inventory provenance, and exact asset bytes. [Cached replay](../../ipfs_datasets_py/logic/formalization/autoencoder/ir_cell_runtime.py) binds the selected package and ordered source/vector rows. [Original corpus replay](../../ipfs_datasets_py/logic/formalization/autoencoder/ir_original_corpus_runtime.py) additionally verifies the checkpoint fitting manifest and original source/vector identities. [Format replay](../../ipfs_datasets_py/logic/formalization/autoencoder/ir_decoder_format_runtime.py) binds the native output format and its implementation source. Repeated file and endpoint checks detect drift; they do not provide an atomic cross-file snapshot.

Model calls receive authenticated source inputs and cached vectors. Gold targets and native validation evidence remain in the evaluator. The optional path generates no new embeddings, launches no new source encoder, and performs no optimizer update. Legal cached replay records its parser-assisted scope explicitly; loading a Legal package may execute its existing stored numerical fixture.

[Decoder profile inventory](../../ipfs_datasets_py/logic/formalization/autoencoder/ir_decoder_profile_inventory.py) records stable output-format and decoder-profile identities separately from concrete packages, corpora, weights, and operator-assigned run names. It preserves all twelve declared family/width lanes. Availability, supported fragment formats, initialization weights, trained decoder quality, and runtime admission remain distinct observations. This metadata interface creates no DuckDB database or remote repository. Future control-plane integration can store its explicit records using the existing registry infrastructure.

The preserved producer pins are:

| Producer | Bytes | SHA256 |
| --- | ---: | --- |
| `domain_384_autoencoder.py` | 34,679 | `66c5ee320f9c7aacd3b246d0666c7fc3ee928e4679892e1e90c838e1b291dbc6` |
| `legal_formula_codec.py` | 14,622 | `f90769a3d99131da5ba48bb84c6f830f521c92d98122bdaaa8dd88fc65042290` |
| `modal_latent_formula.py` | 35,427 | `ec5bdcd752d157c9fc0257a45551cfe9ce7be172af767e8ed769bf1bc8a31d36` |

These pins authenticate the explicitly supported historical codec/runtime contracts. Do not rewrite a checkpoint producer pin to match changed source without independently establishing compatibility.

## Evidence and remaining work

The recovered modules and four additive loader entry points passed 774 targeted tests against an isolated copy of current `origin/main`. Tests exercise exact asset selection, format separation, target exclusion, malformed requests, missing assets, provenance drift, file changes, detached results, and explicit authority boundaries. Numerical owners are simulated in these boundary tests; they grant no model-quality or statutory fidelity claim. The canonical workspace also passed the same 774 tests, and 25 existing public-loader regression tests passed. The integration review retains the full logs and source inventories.

Useful next work is to select authenticated checkpoint/corpus pairs, run separately budgeted numerical reconstruction comparisons, and connect resulting candidates to the existing per-modality projection and proof gates. The 8D linguistic teacher, new 384D/768D decoders, and 4096D experiments retain their separate architecture and producer identities. Width alone does not select a decoder, produce an embedding, or prove compatibility.

Only a real `lake build <Lib>` grants Lean admission. Schema validity, target coverage, syntax checks, cosine similarity, reconstruction loss, compiler output, database records, and these interface tests grant none. Every required logic family and its applicable native semantics must retain its own validation. The US Constitution remains unformalized.
