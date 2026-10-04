# Richer source embeddings and demonstration retrieval

| Field | Value |
| --- | --- |
| Status | canonical |
| Owner | formalization / autoencoder development |
| Source of truth | `alignment_embedding_experiment.py`, `alignment_embedding_development_v1.json`, the pinned source producers, and `alignment_structure.py` |
| Last verified | 2026-10-03 |
| Audience | developer |

This exposed-development experiment measures demonstration retrieval from real
source representations in three independent widths: 8D, 384D, and 768D. It
compares raw source retrieval with fixed ridge alignment to formal structural
features, using the same training candidates and retrieval budget. The authored
richer panel has nonempty qualifiers and explicit unsupported/context cases;
its references remain synthetic and unreviewed.

Pretrained source encoders, spaCy feature extraction, trained autoencoders, and
alignment heads are separate assets. This experiment does not establish the
quality of the existing autoencoder checkpoints or replace their independent
lanes. It measures source representations and newly fit small ridge heads. The
shared 2048-coordinate formal input is a hashed count representation, described
by the [structural feature extractor](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_structure.py),
with disclosed collisions. Its coordinate width is distinct from every source
encoder width and from Leanstral's native hidden width.

## Run from the datasets repository root

Use the [configuration](../../configs/autoencoders/alignment_embedding_development_v1.json)
and a fresh destination:

~~~bash
python scripts/ops/legal_ir/run_alignment_embedding_experiment.py \
  --config configs/autoencoders/alignment_embedding_development_v1.json \
  --output-directory /tmp/richer-embedding-01
~~~

The [CLI](../../scripts/ops/legal_ir/run_alignment_embedding_experiment.py) uses
the enclosing workspace for bound evidence paths; another layout requires
`--workspace-root`. Preserve the existing predecessor evidence and choose a new
output path after changing configuration, implementation, or input bytes. The
workspace run named `richer-embedding-01` is a separate evidence generation.
Completion alone grants no qualification or production admission.

## Representation and input policies

The 8D arm uses the existing frozen spaCy Legal encoder and modal embedding
decoder to hash lexical, part-of-speech, dependency, and modal-cue features to
eight signed coordinates. Citation and record IDs are excluded from the
feature stream. The output is L2 normalized and rounded to six decimals. The
encoder receives exact source text and internally collapses whitespace; its
receipt records that preprocessing. This is a small source-feature baseline.
Hash collisions are possible, and these values do not identify a trained 8D
autoencoder latent or establish preservation of formal meaning.

The 384D arm uses `thenlper/gte-small` at revision
`17e1f347d17fe144873b1201da91788898c639cd`, mean pooling,
L2 normalization, and CPU execution. Exact input is token checked before a
forward pass; overlong input is rejected. Pinning the producer, tokenizer,
pooling, precision, and assets establishes the representation identity. The
encoder checkpoint is separate from the 384D autoencoder and its decoder.

The 768D arm uses pinned
[`Alibaba-NLP/gte-multilingual-base`](https://huggingface.co/Alibaba-NLP/gte-multilingual-base)
at revision `9bbca17d9273fd0d03d5725c7a4b0f6b45142062`, with
`Alibaba-NLP/new-impl` at revision `40ced75c3017eb27626c9d4ea981bde21a2662f4`,
CLS pooling, L2 normalization, and the
CPU float32 reference profile. The complete token-classification model loads
all expected encoder and classifier tensors. Missing, unexpected, or mismatched
tensors are failures. The embedding uses the CLS hidden state; classifier
logits are excluded. A partial model load cannot provide accepted embeddings.
Staging the roughly 628 MB asset set is
different from admitting and executing it, and the encoder is separate from
any trained 768D autoencoder or IR decoder.

The [complete-checkpoint adapter](../../ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768_complete.py)
preserves the earlier bare-encoder producer and its historical evidence.
It verifies that the complete model and its unmodified encoder produce
bitwise-equal hidden states on the first admitted source. That single-source
check does not qualify maximum-context numerical behavior or semantic quality.

The embedding request contains only the exact text of each of the 34 panel
sources. Authored targets, expectations, source partitions, compiler output,
and review suggestions are outside that input boundary. Context assumptions
are not appended, rewritten into the source, or otherwise consumed by these
encoders. This source-only representation omits the declared assumptions
needed to interpret the two explicit-context cases, which are excluded from
semantic retrieval scoring. Equal source text under different declared assumptions must remain
distinguishable in evidence identities even though this source-only encoding
cannot resolve those assumptions.

## Fixed training and retrieval comparison

The candidate pool contains the 16 unique positive training references and
their training source texts. The development comparison has eight positive
queries. Every arm ranks the same 16 candidate IDs and retains five examples.
The full pool is available to all arms, so differences do not come from unequal
shortlist sizes or candidate availability.

The raw arm ranks source vectors against training source vectors. Each aligned
lane fits one ridge mapping from unit source vectors in its native width to
unit formal hashed-count vectors, using the 16 training pairs only. The fixed
recipe solves ridge in its dual form, with no intercept, dimension 2048,
hash seed 0, and regularization alpha 1. The formal training vectors remain
fixed candidate anchors; no formal-to-formal head is trained.
Development references do not fit the source encoder, formal representation,
ridge weights, preprocessing statistics, or retrieval policy. No seed,
regularization value, checkpoint, or fusion policy is selected using these
eight queries. This tiny ridge prototype does not implement paired
contrastive autoencoder training or the full ProofBridge objective. The
experiment does not measure benefits from combining heads.

Ranking receives source-derived query representations. Development references
enter scoring afterward. Existing source-compiler receipts may describe
construction outcomes, but an abstained or missing candidate cannot be replaced
with an authored query target to rank examples.

## Retrieval diagnostics and attainable ceilings

No complete development target or complete core tuple occurs in the training
pool. Exact counterpart recall and direct target-copy accuracy are therefore
unavailable as improvement targets for this panel. The best individual core
match is two of four facets for the four clerk-retention queries and three of
four for the four officer-notification queries.

The earlier complementary actor/action support metric also has a zero ceiling:
no training demonstration matches any development query's actor, object, and
modality together. Reusing that metric would obscure useful partial
demonstration coverage. Instead, the experiment measures post-ranking graded
structural relevance and unscoped qualifier identity coverage, with nDCG
normalized to the attainable ranking in this actual training pool.
Each candidate's relevance is the mean of seven equally weighted comparisons:
four exact core-facet matches and three qualifier-set Jaccard scores. DCG uses
this linear relevance with rank discounting; the ideal ranking is computed
from all 16 training candidates after retrieval.

| Development qualifier occurrences | Present somewhere in training | Pool ceiling |
| --- | --- | --- |
| Conditions | 8 of 10 | 0.8 |
| Exceptions | 10 of 10 | 1.0 |
| Temporal atoms | 10 of 10 | 1.0 |

The condition `identity_verified` is absent from training in two development
queries. Complete qualifier-list bundles are available for six of the eight
queries. The table uses occurrence-weighted coverage. The report's mean of
per-query condition recall has an attainable ceiling of 6/8, or 0.75; the two
queries with unseen conditions contribute zero. Exceptions and temporal
qualifiers retain a 1.0 per-query ceiling. These pool ceilings depend on the bound panel and must be recomputed
after changing it. Unscoped atom coverage reports whether examples contain
named qualifiers; it does not establish their interpretation or their correct
attachment to the query's actor and action. A useful retrieval set can still
lead a generator to produce an incorrect rule.

These are demonstration-retrieval diagnostics. No downstream RAG generation,
repair success, independently adjudicated source fidelity, native theorem
acceptance, or useful proof coverage follows from them. The separate richer
review preparation retains 34 pending items and zero completed independent
reviews. Its source/context-only reviewer payload remains unchanged by this
experiment; the older 40-item review packet is a different panel.

## Evidence artifacts and remaining Leanstral work

Encoder receipts bind exact source hashes, producer profiles, admitted assets,
token counts, normalization, and output vector hashes. Learned ridge-head
artifacts bind the training rows, fixed hyperparameters, numerical recipe, and
their own weights. Each source-only query prediction is ranked by cosine
against the fixed formal training anchors. Ranking artifacts bind selected
candidate IDs and scores; authored relevance and coverage fields are posthoc
scoring evidence. The report
binds these distinct artifact roles and retains separate quality/admission
flags. Source bindings cover their explicitly listed scope, rather than a
complete transitive dependency closure.

`embedding_inputs.json` records the closed source inputs. The three production
artifacts are `legacy8_embeddings.json`, `native384_embeddings.json`, and
`native768_embeddings.json`. Each successfully evaluated lane also writes
`{lane}_ridge.json` and `{lane}_retrieval.json`. `report.json` records all lane
statuses and bindings. An unavailable lane has no fabricated head or retrieval
result. Eight unsupported or ambiguous development inputs may have unscored
diagnostic rankings; those ranks do not grant interpretation or abstention
authority.

The configured deadline is cooperative between lanes and queries. It does not
preempt an encoder's native call. A surrounding process timeout can impose an
additional wall-clock cap when running the CLI.

Leanstral numerical embeddings do not run in this stage. The inspected GGUF
metadata reports native width 4096. Its cached llama.cpp source assigns the
final normalized hidden state before the vocabulary output layer to the
embedding tensor, and supports last-token pooling. That source capability
provides an experimental route; it supplies no measured embedding quality.

The current bounded runner is configured for chat, with no embedding mode.
Its 62.525 GiB GGUF produces a conservative host-memory admission estimate of
about 72.78 GiB plus a 12 GiB reserve, or roughly 84.78 GiB available RAM. The
initial preflight reported 45,126,360 KiB available (about 43.0 GiB), below that floor.
No GGUF weights are loaded and no native forward pass runs. A future separate
embedding process must share the GPU lock, pin the backend and tokenization
policy, and obtain actual resource and numerical receipts. Last-token pooling
can split supported causal sequences across physical batches; mean pooling
requires the complete sequence within the admitted physical batch. Neither
4096D hidden vectors nor a later projection should be relabeled as the existing
8D, 384D, or 768D encoder/autoencoder assets.

## Related checks

The [richer evaluation guide](alignment_richer_evaluation.md) explains authored
reference and qualifier-loss boundaries. The
[parser improvement guide](alignment_parser_improvement.md) describes the
separate opt-in parser profile and its frozen baseline. The
[autoencoder handbook](README.md) and
[parallel lane contract](parallel_lineage_execution.md) own checkpoint lineage.

Use the specific run's report for actual timings, resource outcomes, ranking
metrics, failed or unavailable lanes, and byte bindings. No observed embedding
or retrieval result is asserted here before the numerical run completes.
