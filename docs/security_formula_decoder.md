# Security source-to-formula development decoder

The original Security-CVE checkpoint reconstructs AST features and scores
classification candidates. It remains unchanged. A separate, datasets-owned
production head now consumes source token observations and frozen inherited
LegalIR lexical rows. Training reuses the native modal-autoencoder loss,
gradient, and microbatch routines. New security head parameters have an explicit
initialization; the inherited lexical rows and LegalIR checkpoint are preserved.

This is a bounded supervised grammar decoder. The parser supplies topology,
names, constants, and declared source scaffolding. Learned logits select grammar
productions. Candidate reconstruction uses those predictions; incorrect outputs
are rejected by an independently reparsed AST comparison. Target productions
are never substituted when a prediction fails. This is not arbitrary software
formalization or a learned security specification.

## Complete source inputs and retrieval windows

`security_formula_source_units.decode_security_source_units` accepts a pinned
complete Python source file and selects complete functions for the unchanged
frozen production head. It reuses the existing function span extractor and
independent byte-map verifier. It also compares the normalized function AST to
the original source AST: indentation removal that changes a multiline string is
refused. Multi-function modules and class methods can therefore reach learned
inference without removing surrounding source or fabricating function wrappers.

```python
from ipfs_datasets_py.logic.formalization.autoencoder.security.security_formula_source_units import (
    decode_security_source_units,
)

report = decode_security_source_units(
    source_bytes=complete_file_bytes,
    source_sha256=independently_pinned_source_sha256,
    source_path="package/module.py",
    checkpoint=decoder_descriptor,
    window_start_byte=window_start,
    window_end_byte=window_end,
)
```

The default decodes only functions wholly contained in the window. Explicit
`recover_context=True` can recover complete intersecting functions from the
supplied source; these successes are counted separately from standalone window
coverage. Every function stays in the inventory, including unsupported and
unselected functions. Supply `language="python"` to retain an original path that
does not end in `.py`; without a declared language, the `.py` filename gate stays
in force. Module initialization, enclosing scopes, unsupported
grammar, and native lowering remain explicit limitations. Incomplete fragments,
serialized changed-line fields, diffs, prose, and other languages are not turned
into Python by rewriting or wrapping them. Use the existing complete-source
recovery workflow for those corpus records before applying a Python decoder.

This adapter does not alter, re-pin, or train the existing decoder package.
Actual production predictions still come from the checkpoint, and model-off or
zero-head controls cannot receive deterministic production fallback.

## Source and training workflow

`security_cve_source_context.recover_security_source_context` resolves complete
changed Python files for a pinned canonical Publicus corpus. The fixing commit
and its unique parent are distinct. Git tree/blob preimages, body SHA256, native
SourceRecord/CodeUnit identities, splits, budgets, and exclusions survive offline
replay. Missing parents, renames, unsupported encodings, and unavailable objects
remain explicit frontiers. The commit-parent relationship is HTTPS API metadata,
not a locally reconstructed Git commit-object proof.

`security_formula_corpus.build_security_formula_corpus` visits every recovered
function. Supported source samples keep their file/source identities and exact
byte maps. Cross-split body or normalized-shape collisions are quarantined.
Unsupported functions remain in the report. Corpus polarity and CWE labels do
not become function-level security truths or input features.

Train from an explicit local sample selection and parent descriptor:

```bash
CUDA_VISIBLE_DEVICES='' PYTHONPATH=. python3 \
  scripts/training/train_security_formula_decoder.py \
  --samples /absolute/samples.json \
  --initializer-descriptor /absolute/initializer.json \
  --published-binding /absolute/published-binding.json \
  --provenance /absolute/selection-provenance.json \
  --training-data-scope publicus_and_authored_development_controls \
  --output /absolute/fresh-formula-package
```

Samples contain `id`, `split`, `source`, and optionally `source_sha256`.
The command returns a pinned decoder descriptor. The four-file inference
package contains JSON weights/configuration/training lineage and a manifest;
it requires neither the original LegalIR state nor training source bodies at
inference. Development controls and development holdout reuse are recorded;
their scores are not estimates of general vulnerability-repair accuracy.

## Formal evaluation

The strict arithmetic guard admits native ProgramIR only within its declared
integer model. Reviewed header context admits exact learned normalizer
candidates into native string-SMT obligations. Native compilation is
deterministic and separately attributed. Header specifications, ordinary string
conversion, dynamic bindings, and normalization preservation remain explicit
premises. A solver result concerns that local model, not whole-program security.

```bash
CUDA_VISIBLE_DEVICES='' PYTHONPATH=. python3 \
  scripts/evaluation/security_formula_pipeline.py \
  --repository /absolute/permitted-inputs \
  --source-ledger /absolute/sources.json \
  --decoder-descriptor /absolute/decoder.json \
  --protocol /absolute/header-protocol.json \
  --check-headers --output /absolute/fresh-evaluation
```

The optional protocol JSON has exactly `review_ref` and `callback_parameter`.
It represents an explicit caller review. It is not inferred from a model score.
Without it, header AST candidates do not count as formal formulas.

Run the same command with `--model-off --allow-diagnostic-only` for the control.
The learned formula count must fall to zero while deterministic source models
remain identical. The default command exits 2 if no learned formal candidate is
accepted. Counts include abstentions; unsupported source files prevent a complete
coverage claim. Every saved evaluation can be replayed against source, weights,
candidate productions, native artifacts, and optional solver results. CLI solver
accounting separates generation and validation passes.

## Supervisor consumer

The accelerate supervisor imports this implementation. Its
`prepare_security_advice(..., formula_decoder=..., header_protocol=...)` option
registers the new capability with ModelManager, persists the source-bound
observation and native proof-work plan, and links the decoder, AST evidence, and
plan graph in DuckLake. Changed source invalidates advice; refresh recomputes it
with the same frozen weights. Existing Doctor admission, independent proof,
validation, and publication rules still control code repairs.

The container runtime and runtime archive accept an optional formula decoder
descriptor and reviewed header protocol. The no-index arm excludes those assets.
No inference path trains, downloads a replacement model, or silently uses an LLM.
The general seven-family code projection APIs remain available for explicitly
typed evidence; this head does not claim learned coverage of every family.

With both repositories importable and the native Quack, DuckLake, Lean and Z3
dependencies installed, the accelerate consumer can exercise an authored repair
through the admitted supervisor:

```bash
CUDA_VISIBLE_DEVICES='' python3 -m \
  benchmarks.agent_supervisor.container_coding.native_header_supervision \
  --output /absolute/fresh-supervisor-qualification \
  --security-checkpoint /absolute/classifier-package \
  --security-checkpoint-manifest-sha256 CLASSIFIER_MANIFEST_SHA256 \
  --formula-decoder-descriptor /absolute/decoder.json
```

Set `DOCTOR_COMPOSITION_LEAN` to the installed Lean executable when it is not
available through `elan`. The qualification uses its own declared header
specification and public regression fixture. It verifies native repair,
publication, stale-observation rejection, refreshed formal plans and six
DuckLake catalogs, unchanged checkpoints, and a clean supervisor stop. This
command measures an authored integration task; it does not produce a Terminal
Bench score. The corresponding live integration test additionally checks
learned coverage for the qualified development decoder.
