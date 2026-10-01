# Historical modal decoding and the missing learned formula head

The legacy system did use spaCy and an intermediate representation. Its saved
8-dimensional autoencoder did **not** contain a learned decoder from that vector
to a formula. It had vector reconstruction, deterministic text-to-IR compilation,
deterministic IR-to-text decompilation, and trainable diagnostic projections.
Those are separate operations even where their names contain “decoder” or
“round trip.”

This audit reads local Git objects at
`ddf6b79467b68159650df81befc288c8553df664` (2026-09-19), the corresponding frozen
runtime, and subsequent history through the decoder-integration release. It does
not execute a historical service, infer the contents of an unseen Hub checkpoint,
or download weights. Historical line references below point to that exact commit;
the frozen snapshot retains the numerical implementation with recorded import
relocations in its `MANIFEST.json`.

## What the historical paths actually did

| Path | Input and output | Learned behavior |
| --- | --- | --- |
| `build_us_code_sample` | Text → deterministic modal IR, BM25 frames, explicit or default vector | No learned formula generation |
| `SpaCyLegalEncoder` | Text → tokens, lemmas, POS/dependencies, sentences and modal cues | Uses an installed spaCy pipeline; the autoencoder does not train it |
| `SpaCyModalIRCompiler` | spaCy features → modal formulas with operator, predicate, conditions, exceptions and provenance | Deterministic rules |
| `SpaCyModalDecoder.decode_embedding` | spaCy features → normalized feature-hashed vector | No trainable decoder parameters |
| `AdaptiveModalAutoencoder.encode` / `decode` | Sample → projected vector and metadata → vector | Sparse learned residuals and classification/view heads; no formula sequence output |
| Deterministic modal decompiler | Modal IR → reconstructed text and audit metadata | Rule-based text rendering |
| Grammar decoder experiments | Supplied structured candidates or prefix logits → constrained candidate/token output | Separate experimental architecture; not the saved modal autoencoder's latent decoder |

The historical sample builder defaults to `mock:stable-sha256`; its eight values
come from a seeded pseudo-random generator, not a semantic embedding model.
Explicit vectors may replace that default. Therefore eight dimensions alone do
not establish semantic provenance, and a checkpoint cannot tell us which encoder
generated its training vectors without corresponding metadata.
See [legal_samples.py, lines 22 and 100](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_samples.py#L22).

`SpaCyLegalEncoder` loads an installed `en_core_web_sm`, falling back to
`spacy.blank("en")` with a sentencizer if it is unavailable. The fallback can lack
the trained POS/dependency information, so it is a distinct representation that
needs explicit provenance. `SpaCyModalIRCompiler` builds formulas from eligible
modal cues and token-derived predicates, then uses deterministic parser coverage
rules. `SpaCyModalCodec.compile_sample_ir` exposes that compiler independently of
`decode_sample_embedding`.
See [spacy_modal_codec.py, lines 1225, 1813, 1829 and 2197](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py#L1225).

The spaCy “decoder” hashes document length, lemmas, POS tags, dependencies, modal
cues and modal-family counts into vector slots, then L2-normalizes the result.
It does not render a formula or recover text from a learned latent vector.
The optional autoencoder `feature_codec` calls this method for its base vector;
without a codec, the base is a scaled, pairwise-rotated version of the supplied
input embedding.
See [spacy_modal_codec.py, lines 2087–2223](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py#L2087)
and [modal_autoencoder.py, line 8093](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L8093).

The adaptive encoder returns `family_distribution`, `sample_id`, `selected_frame`,
target-family metadata and `embedding_projection`. Its `decode` method simply
returns that projection as floating-point values. Learned dictionaries add vector
corrections and logits keyed by text features, semantic slots, predicates,
compiler-quality signals, decompiler plans, modal families and legal-IR views.
A head named `decompiler_plan_embedding_weights` changes a vector; it does not
generate decompiler text or formula tokens.
See [modal_autoencoder.py, lines 4291 and 4360](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L4291),
[line 7805](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L7805)
and [line 22462](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L22462).

## Why reconstruction losses did not establish learned formula decoding

The training objective combines embedding MSE, embedding cosine gap,
modal-family cross-entropy and legal-IR-view cross-entropy. Bridge-produced
compiler/decompiler metrics and structural targets are collected separately.
The presence of `source_decompiled_text_token_loss` means a deterministic
compiler/decompiler round trip was measured; it does not imply a model-generated
token sequence. The deterministic decompiler explicitly describes its output as
provenance-backed reconstruction of text carried by the IR.
See [modal_autoencoder.py, line 7764](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L7764),
[line 25647](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L25647),
[line 26535](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L26535)
and [logic/modal/decompiler.py, line 1](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/logic/modal/decompiler.py#L1).

Two historical conveniences particularly limit reconstruction evidence:

- `use_sample_memory=True` can return a stored per-sample reconstruction directly.
- `_reconstruction_safe_projection` observes the target embedding and can return
  that target exactly when a correction has positive alignment. A perfect cosine
  under this path is not evidence of a learned symbolic decoder.

See [modal_autoencoder.py, lines 7805 and 8054](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py#L8054).
The newer `current_v2` profile explicitly defaults to raw reconstruction and
disables sample memory. Preserving the old profile's behavior is useful for
reproducibility; a new formula head must not treat its target-assisted projection
as independent evidence.

## Decoder-like experiments that did exist

History contains more than the vector-only runtime. The typed grammar decoder
can reject invalid supplied productions and constrain token search. The
`CompatibleLearnedArchitecture` experiment accepts **already structured IR**,
pools frozen-vocabulary token embeddings, and emits family, view, reconstruction
and uncertainty logits. Its `step` updates family-classifier weights and biases;
it does not update reconstruction weights, despite exposing reconstruction
logits. The grammar decoder can consume its prefix logits, but that mechanism is
not attached to `AdaptiveModalAutoencoder`'s 8D checkpoint or jointly trained with
that autoencoder.
See [legal_ir_grammar_decoder.py, line 3390](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_grammar_decoder.py#L3390),
[line 3757](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_grammar_decoder.py#L3757)
and [line 1644](https://github.com/endomorphosis/ipfs_datasets_py/blob/ddf6b79467b68159650df81befc288c8553df664/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_grammar_decoder.py#L1644).

Relevant historical milestones are:

- `8100f637034dad8da15a1c53cca8d280d05d51ec`: learned features promoted into
  deterministic IR guidance, not independent formula generation.
- `43d9949262f294f36cd9f16863ef7a03f2d8f2eb`: trainable legal-IR heads connected to
  evaluated objectives.
- `5ed17a216`: typed grammar candidate validation.
- `371f36b8d` and `5b9953710`: compatible learned architecture experiments and
  constrained token decoding.
- `3675513ea`: explicit raw-decoder feature pretraining after the historical
  snapshot.
- `43ad58936`: the separately versioned source-conditioned legal GRU formula
  decoder. Its input is source text, not the old autoencoder latent vector.

## Integration design supported by this research

Keep the frozen numerical snapshot and archived checkpoints unchanged. Add an
explicitly versioned trainable projection and formula head owned by each selected
autoencoder lineage and modality. For legal 8D and 384D, the new head must consume
the actual raw model representation with sample memory and target-assisted safety
projection excluded. A decoder that instead receives the gold IR, source tokens
or compiler-generated formula cannot be reported as latent-only decoding.

Train the new latent projection, vector-reconstruction head and formula head in
one optimizer step with separately reported reconstruction and formula losses.
The original numerical core can remain frozen as an explicit feature extractor;
the report must distinguish this from gradients updating the historical sparse
core itself. The new decoder then belongs to the combined training/checkpoint
process, rather than being a separately trained source-text model.

Bind checkpoint state to lineage, vector width, feature-extractor identity,
modality, vocabulary, projection schema and target codec. Store separate weights
for legacy legal, current legal, Intent, Security and UI/UX. Their logical output
contracts are different; share orchestration and persistence, not an assumed
universal legal schema. Existing native reconstruction paths remain explicitly
compiler-structure-conditioned until a separate source/latent input contract is
implemented and tested.

Reusable pieces include canonical formula codecs, typed grammar masks, source
provenance, deterministic comparison, immutable parent-bound checkpoints,
bounded training deadlines and domain-specific schema checks. Training must
record decoder and projection parameter changes, formula loss, reconstruction
loss and exact resumed optimizer state. Inference must need no targets, reject
incompatible dimensions or lineages, and abstain on unsupported vocabulary or
schemas. Held-out evaluation and latent-ablation checks are needed before
claiming useful generalization.

The formula family's semantic tests and actual `lake build <Lib>` remain
separate qualification checks. A schema build, low loss, matching compiler output
or database row does not establish legal admission. The known dropped emergency
exception remains a failure until corrected and tested; the Constitution remains
unformalized. This research document describes the integration design, not a
claim that all of these checks have already passed.
