# Paired legal conversion: capabilities and evidence

The legacy legal autoencoder reconstructs vectors. Its `decode` method does
not generate formulas or natural language. `compiler_guidance_for_sample`
exports learned features and distributions that an existing deterministic
modal compiler can consume. These two capabilities must remain distinct in
the span dataset. Source-derived bridge targets are a third evidence source;
they are not learned decoder outputs.

## Optional guided compiler observation

`legacy_span_guided_compiler.GuidedLegacyCompiler` accepts the already loaded
autoencoder owned by the CUDA worker. It loads no weights and creates one
reusable deterministic codec. Its `observe(sample)` method must run after
bridge evaluation, before the owner clears its per-sample target caches.
Calls are serialized within that model owner because the existing model and
codec maintain caches. Parallel CPU compilation continues in the worker pool.

```python
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_guided_compiler import GuidedLegacyCompiler

observer = GuidedLegacyCompiler(model, top_k=8, model_identity=checkpoint_identity)
observation = observer.observe(sample)
```

The caller supplies the exact checkpoint identity it already verified. The
adapter does not repeatedly hash or reload the checkpoint. It requests
`use_sample_memory=False` and `include_causal_attribution=False`; `top_k` is
bounded from 1 to 32. Expensive FLogic scoring and external provers are off.
The compiler retains its actual modal formulas and native frame triples.

The observation stores two formula collections in the same native format:

| Collection | Actual producer |
| --- | --- |
| `direct_formal_outputs` | The same deterministic modal codec with `compiler_guidance=None` |
| `model_formal_outputs` / `guided_formal_outputs` | The deterministic modal codec consuming learned autoencoder guidance |

Both calls use identical source text, document ID, citation, source name, and
source embedding. This comparison isolates the guidance input rather than
comparing differently structured parser pipelines. It adds one unguided codec
pass; `direct_compiler_seconds` and `guided_compiler_seconds` expose the cost.
Both retain every emitted formula's complete payload. Full direct and guided
modal documents are retained with hashes. The original sample parser document
is preserved separately as `source_parser_document`; it is not the comparison
baseline. Raw equality uses the exact AST,
including source provenance, formula identifiers, and metadata. It is a
diagnostic comparison: differences can arise from those fields as well as
semantic content. It does not establish logical equivalence. No field is
removed merely to increase agreement.

The guided collection is labeled `origin=autoencoder_guided_compiler`,
`independent=false`, `source_derived=true`, and
`learned_formula_generation=false`. `target_conditioned=true` means guidance
contained a nonempty source-derived LegalIR target distribution. An empty
target distribution does not make this compiler an independent model decoder.
The producer records which family each emitted operator actually names; it
does not infer family coverage from enabled bridge names.

Native modal dataclasses have serialization methods but no general syntax
validator. Consequently `syntax_status=not_checked` remains explicit. The
adapter runs no Lake command and grants no admission, semantic qualification,
or formalized status. Constructor/source failures and malformed observations
produce explicit error rows. Complete guidance above 2 MiB or combined direct
and guided documents plus the source parser document above 16 MiB are deferred with their size/hash instead of
being truncated. These are capture limits, not larger model context windows.

## Actual learned sequence decoder inventory

The shared `autoencoder_paired_text` and `autoencoder_paired_copy` backends do
perform learned token generation without parser labels or teacher targets at
inference. The copy backend uses a GRU encoder, attention decoder, and learned
pointer-generator gate. Existing local checkpoints fit IntentIR supervision.
They are not LegalIR natural-language decoders.

The audited local checkpoint was:

```text
/home/barberb/lift_coding/artifacts/intent-ir-compositional-20260930/curriculum-nomask-01
```

Its descriptor schema is `intent-copy-roundtrip-checkpoint/v1` and manifest
SHA256 is `504bb6874d591c0899396b712224bdee3b977044d2aa15a30c864b7950057c27`.
Its backend `model/candidate.json` has SHA256
`bb61009a96d30e0c70cbf287ee702c9fff10e5ad3a913bb52bc5284c23f35e07`.
It has 113,535 trainable parameters and 3,122 reported training pairs. The
manifest describes a controlled single-clause actor/action/object/modality
language, weak source/authored supervision, and excludes temporal conditions,
quantifiers, and workflows. Its inherited LegalIR lexical rows are not an
inherited trained LegalIR formula decoder.

A read-only CPU smoke on 2026-09-30 loaded the exact backend with its existing
source-provenance checks and generated these unedited predictions:

| Input | Actual generated sequence |
| --- | --- |
| The agency shall not disclose records. | `<actor> unspecified <action> disclose <object> records not <modality> intended` |
| The officer shall retain the file for at least 20 days. | `<actor> unspecified <action> for <object> for at .` |
| Company A shall submit backup report within 10 days unless emergency. | `<actor> unspecified <action> report <object> report <modality> intended` |

These predictions lose prohibition, duration, and exception semantics. The
second is incomplete even though the generator reported an end token. That
generator status is not syntax or semantic validation. This checkpoint must
not silently substitute for a legal-trained decoder.

The artifact was 3,409,346 bytes. Loading took 0.107 seconds, first generation
0.072 seconds, and subsequent generations 0.0025 and 0.0020 seconds. Peak RSS
was 510,396 KiB for the whole Python/PyTorch process. These are a tiny CPU
capability diagnostic, not a legal conversion or legacy CUDA speed benchmark.
The run used one PyTorch thread, no CUDA, no training, no target access, no
provider calls, and no downloads.

## Enabling an independent legal decoder later

Reuse the sequence backend with a legal-specific wire codec and a fitted local
checkpoint whose training-source and implementation provenance are recorded.
Retain actor, action, object, force, negation, exception, temporal, and scope
structure in the targets. Keep unsupported structures explicit. Split held-out
legal source families before training, and validate polarity, temporal scope,
exceptions, malformed outputs, out-of-vocabulary inputs, and weight ablations.

Load one validated model per designated inference owner. The public
`infer_paired_copy` helper reloads weights each call; a campaign should reuse
the result of `load_paired_copy` and perform frozen generation on that loaded
instance. The existing backend has a 192-token input/output cap and a
CPU-only checkpoint contract. CUDA support or a different cap requires a
separately validated implementation rather than silently changing this one.

Until a legal decoder exists, record its capability as unavailable separately
from guided compiler diagnostics. A deferred supervisor goal should request
that missing capability and distinguish it from a pair with two actual formal
outputs that disagree. Regardless of decoder quality, only the required
source-bound `lake build <Lib>` path can establish a Lean admission.
