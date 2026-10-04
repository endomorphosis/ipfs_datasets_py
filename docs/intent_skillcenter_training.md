# SkillCenter Intent feature training

`Publicus/skillcenter-ir` is a source and retrieval corpus. Its current release
does not contain reviewed natural-language instructions paired with formal
IntentIR constraints. The development training path therefore learns **native
structural projection features**. It does not train a natural-language logic
decoder or establish the correctness of an instruction's meaning.

The implementation lives in `ipfs_datasets_py`; Accelerate consumes a frozen
checkpoint descriptor. It reuses the shared projection-feature autoencoder.
The Intent feature space is separate from the LegalIR and SecurityIR spaces;
development initialization is explicitly seeded from scratch, and existing
domain weights are neither imported as incompatible heads nor overwritten.

## Reproducible local export

Download a pinned release's `manifest.json`, its `indexes/corpus_chunks.parquet`,
and one or more corpus shards. No remote script, skill, or dataset content is
executed. The exporter verifies each file against the release manifest/index,
checks content and entry CIDs, and reapplies the existing native source policy.

```bash
python scripts/training/train_intent_autoencoder.py export \
  --release-root /path/to/local/pinned-release \
  --release-revision 2cc11a73403d03c0679ffa909c893ef6a850048a \
  --manifest-sha256 0b62b6d81c04dcfa678218a9fc0773204097e103d251f77759ab3870f2bce2e4 \
  --shard data/corpus/part-000000.parquet \
  --max-examples 32 \
  --output /path/to/fresh/intent-corpus > corpus-descriptor.json
```

Only source-policy-approved content enters candidate training records. Before
bounded selection, the native split builder groups source families, exact and
near duplicates, repository sources, and registry package versions. These are
local development partitions of the public `train` shards, not official
independent held-out data. Existing test partitions are never reassigned to
training or tuning.

## Small CPU development run

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python scripts/training/train_intent_autoencoder.py train \
  --corpus-descriptor corpus-descriptor.json \
  --epochs 3 --latent-width 4 --max-seconds 60 \
  --output /path/to/fresh/intent-feature-checkpoint > training-receipt.json
```

The command is bounded to 32 source examples, eight epochs, and 60 seconds of
trainer time. It preflights every example with the same Prompt adapter used at
supervisor inference. The scoped feature envelope contains complete native
action/fact/workflow projections. The original full envelope, opaque goal
frontier, failed whole-document readiness, and unrun proof obligations remain
explicit. Source-policy and frontend failures are excluded with source IDs and
reason codes; they are not silently relabeled.

The package and training receipt pin the source corpus, source adapters,
projection producers, feature space, model state, initialization, and selected
partitions. Validation is used for development tuning. A useful semantic
decoder will additionally need independently reviewed instruction-to-IntentIR
examples, code-bound predicates/contracts, negative and ambiguous examples,
and independently held-out semantic tests. Successful structural feature
reconstruction does not satisfy those requirements.

Runtime advice remains an unverified candidate. Missing, invalid, or untrained
models leave the original instruction available to the existing planner. A
feature score grants no tool, execution, completion, or proof authority.

## Sentence spans for paired IntentIR training

The span path adapts the deterministic sentence method used by the
[`justicedao/uscode-autoformal-span-cache`](https://huggingface.co/datasets/justicedao/uscode-autoformal-span-cache)
ingestion code: normalize whitespace and split after `.`, `!`, or `?` followed
by whitespace. `logic/formalization/text_spans.py` implements that boundary rule
with exact character and UTF-8 byte selectors. The SkillCenter adapter applies
it inside Markdown blocks and preserves headings, list ancestry, and surrounding
scope. It uses an Intent-specific export; it does not relabel skills as law or
write to the LegalIR span cache.

Every source character is represented, including whitespace, headings, fences,
and excluded blocks. Each span keeps its parent content hash, entry identity,
license, and existing source-family partition. IDs depend on source identity and
location, not corpus ordering. Cross-partition duplicate sentences are excluded
without moving parent documents between partitions.

Long sentences remain intact with an explicit gap. Conditions, quantifiers,
anaphora, code, examples, and unresolved list scope do not become unconditional
training labels simply because their text was split. The report distinguishes
spans eligible for attempted lowering from spans with an actual bounded target.
All targets remain unreviewed weak supervision.

Starting with a pinned source corpus descriptor from the export above, run from
the datasets repository root and use fresh output directories:

```bash
PYTHONPATH=. python scripts/training/build_intent_span_corpus.py \
  --source-corpus-descriptor /path/to/source-corpus-descriptor.json \
  --output /path/to/new-span-corpus
```

This writes `spans.json`, its pinned `descriptor.json`, and `paired-corpus.json`.
The pair builder carries heading modality into the existing conservative clause
adapter, reconstructs native typed IntentIR, and checks the frame round trip.
It records exact original source fragments separately from the normalized model
input. Unsupported spans and cross-partition instruction/frame collisions remain
in the report with reasons. Loading a descriptor replays source, policy, offsets,
context, producer hashes, and split decisions; a recomputed file digest alone
cannot validate a changed label.

Train through the same paired numerical backend as the existing Intent model:

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
PYTHONPATH=. python scripts/training/train_intent_roundtrip.py \
  --span-corpus-descriptor /path/to/new-span-corpus/descriptor.json \
  --lexical-initializer /path/to/read-only/legal-lexical-fork/initializer.json \
  --epochs 100 --max-seconds 300 \
  --output /path/to/new-span-checkpoint
```

Public span pairs are the default for this path. A corpus must contain distinct
training and validation families. `--include-authored` explicitly adds the
existing authored development controls when needed for a bounded experiment;
evaluation reports public and authored groups separately. Neither the source
export nor the trainer reassigns a held-out source to create a missing partition.

The new checkpoint retains the existing single-clause codec. This path provides
smaller training inputs; it does not add learned workflow, condition, or effect
targets, nor change how the supervisor handles a long original instruction.
Existing IntentIR, LegalIR, and SecurityIR checkpoints remain separate. See
[the paired model guide](intent_roundtrip_training.md) for the inherited lexical
initialization, inference limits, evaluation, and explicit checkpoint selection.

## Richer source targets and codec eligibility

An additional, separately versioned exporter expands the bounded English action
grammar and retains explicit two-action sequences and self-contained `if`
conditions. It replays the existing span inventory without changing its source
partitions or earlier export. Vocabulary expansion is developed on the training
partition; validation/test results remain development measurements.

```bash
PYTHONPATH=. python scripts/training/build_intent_rich_span_targets.py \
  --span-corpus-descriptor /path/to/span-corpus/descriptor.json \
  --output /path/to/new-rich-targets
```

The output contains `targets.json` and `descriptor.json`. Every accepted target
has exact source selectors, a closed target shape, native IntentIR, and a compact
projection qualification. Omissions and cross-partition input/target collisions
are retained. Cases with unknown scope, unsupported language in headings,
unresolved conjunctions, quantifiers, or conflicting modalities abstain. An
omitted actor remains `unspecified`.

| Target | Native representation | Existing learned codec |
| --- | --- | --- |
| One lowercase lexical action | Typed action and its declared modal goal | Eligible after text bounds and source replay |
| Case-sensitive object phrase | Exact object case in native arguments and action references | Excluded; the frozen codec is lowercase-only |
| Two actions with explicit `then` ordering | Two action/goal nodes and a `NEXT` edge | Excluded; the frozen codec predicts one action |
| Explicit `if` condition | Implication candidate AST plus an opaque native goal retaining the whole conditional | Excluded; native conditional modality and a learned conditional codec are not implemented |

The conditional representation intentionally emits no standalone obligation
about its action. An action precondition cannot encode `condition → obligation`
in the current native modal projectors. The bridge therefore does not invent
that relation, an execution precondition, or guard truth. DCEC/TDFOL and Lean
qualification retain the unsupported conditional frontier. A successful TLA+
check of its abstract program counter does not prove the conditional statement.

To train compatible actions through the shared backend:

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
PYTHONPATH=. python scripts/training/train_intent_roundtrip.py \
  --rich-target-descriptor /path/to/new-rich-targets/descriptor.json \
  --lexical-initializer /path/to/read-only/legal-lexical-fork/initializer.json \
  --epochs 100 --max-seconds 300 \
  --output /path/to/new-rich-action-checkpoint
```

As with span training, `--include-authored` is explicit and results are separated
by source group. Conditional, sequential, and case-sensitive targets stay in the
target export; they are never flattened into single-action training examples.
Mixed public/authored input collisions are checked using the trainer's exact
lowercase and whitespace normalization and the shared model's tokenization,
while retained source text and labels remain intact. Conflicting labels for the
same model input are quarantined even within one partition. Unsupported native
lexical bounds become explicit omissions;
unexpected native qualification failures still abort the export.
No existing checkpoint, runtime default, or frozen codec changes when using
this path.

## Optional learned source copying

The separate `autoencoder_paired_copy` backend mixes learned generator and
source-attention probabilities. Unseen input tokens receive temporary copy IDs
local to that invocation. The fitted vocabulary still contains training tokens
only. A seeded training-only masking rate makes the model practice copying;
validation, test, and inference never apply that masking or update weights.
No input parser or expected target supplies semantic slots during inference.

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
PYTHONPATH=. python scripts/training/train_intent_copy_roundtrip.py \
  --rich-target-descriptor /path/to/new-rich-targets/descriptor.json \
  --include-authored \
  --lexical-initializer /path/to/read-only/legal-lexical-fork/initializer.json \
  --epochs 100 --max-seconds 300 --copy-dropout 0.20 \
  --output /path/to/new-copy-checkpoint
```

This produces `intent-copy-roundtrip-checkpoint/v1`, backed by the shared
`shared-paired-copy-autoencoder/v1` package. Its loader, inference, and training
live in datasets; Accelerate explicitly dispatches this schema and transports
the inert package in `frozen_copy_roundtrip_inference` mode. Previous checkpoint
schemas and their pinned producers remain unchanged. Explicitly select the
new descriptor to try it; training does not replace the runtime default.

The codec remains a lowercase single action with the same 48-word instruction
bound. Conditions, workflows, and case-sensitive objects are outside its learned
contract. Runtime checks reject empty or oversized inputs and failed
reconstructions, but cannot reliably detect every out-of-scope instruction. The
inverse receives only predicted typed IR, and all reports retain the original
instruction binding and unverified advisory authority. Unknown-token coverage
is reported separately from frame accuracy. A copied, syntactically valid,
self-consistent frame can still misrepresent the instruction and influence
planning if included as advice.

Evaluation writes source-group metrics and two inference ablations:
`disable_copy` and `zero_output_head`. These test numerical dependencies;
neither is a semantic-quality baseline. Actual public experiments must keep
incorrect valid candidates in the accuracy denominator. Formal syntax or
abstract-state checks do not establish fidelity to the original instruction.

## Authored compositional curriculum

`formalize/compositional_curriculum.py` adds a deterministic supplement to the
rich-span corpus and its existing authored controls. It preserves those rows
and source partitions, then adds 1,600 training, 180 validation, and 180
development-test examples. The supplement covers five modalities, explicit
and omitted actors, familiar and generated action atoms, and object phrases.
Training has four object phrases with lengths one through four; validation
and test use separate generated banks with lengths two and three. These are
bounded composition checks, not representative natural-language instructions.

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
PYTHONPATH=. python scripts/training/train_intent_compositional.py \
  --rich-target-descriptor /path/to/new-rich-targets/descriptor.json \
  --lexical-initializer /path/to/read-only/legal-lexical-fork/initializer.json \
  --epochs 100 --max-seconds 600 --copy-dropout 0.20 \
  --output /path/to/new-compositional-checkpoint
```

Before fitting, the trainer replays the public source decisions, authored
templates, native IR labels, and producer hashes. New families that conflict
with retained data are quarantined as a whole; retained rows are never moved
or relabeled. Training delegates to the existing shared copy backend. The
result uses the same checkpoint and supervisor-consumer interfaces as the
optional copy model above. The LegalIR lexical initializer is read-only; it
does not initialize every sequence-model parameter.

Reports expose separate `source_groups` for public weak targets, original
authored controls, and the new curriculum. Keep those denominators separate
when reporting results. A supplementary diagnostic used to identify training
gaps is development evidence, even if its exact examples were never fitted.
Freeze a separate evaluation suite before training for a fresh comparison.

Setting `--copy-dropout 0` provides a useful control, with a limitation: the
frozen backend shares its random generator between masking and shuffling.
Changing masking therefore also changes later epoch orders. Equal corpora,
initial weights, seed, and epoch counts do not isolate masking as the only
stochastic difference. Some masked training inputs can also erase modal
distinctions; this is a training ambiguity, not an inference error bound.

This path retains the lowercase, single-action codec and advisory authority
limits. It does not establish semantic correctness, train conditional or
sequential intent, publish a checkpoint, or replace a runtime default.

## Supervisor instruction scope

The supervisor now calls datasets-owned
`formalize.instruction_scope.assess_intent_instruction_scope()` before loading
a semantic copy or lexical checkpoint. The complete instruction must match
the declared bounded grammar. Instructions detected outside that grammar,
including conditional or compound forms, unresolved references, questions,
unsupported negation, and case-sensitive code, receive
`fail_open_instruction_scope`. No learned inference
or optional projection-context loading occurs on that path. Planning continues
with the complete original instruction and independent domain constraints.

The assessor recognizes declared actor/modal forms, deontic paraphrases,
modal headings, and a vocabulary of ordinary imperative commands. It permits
opaque action atoms in explicit modal positions; unfamiliar bare commands can
be conservatively rejected. It distinguishes limited whole-object mentions
such as `the if statement` from conditional scope. This finite grammar does
not resolve arbitrary natural language. Accepted instructions can still
produce incorrect model predictions, and some valid single-action wording
falls outside the policy.

Reports bind the exact input, policy, producer, reasons, and coverage decision.
They contain no semantic slots or expected targets. The existing learned
adapter receives the original instruction; scope assessment never supplies a
replacement frame. `validate_instruction_scope_report()` independently
replays the assessment. All authority and semantic-verification fields remain
false.

Accelerate's `ipfs-accelerate-intent-preplanning-advice@2` envelope carries this
`scope_report` alongside the unchanged native report. A rejected instruction
has no native report and retains only a shape-validated attempted checkpoint
descriptor, which is not loaded. Saved `@1` semantic advice remains readable,
but must pass the current scope policy before numerical replay or planner
delivery. Rehashed or altered `@2` scope receipts fail validation. Feature-only
advice and disabled preprocessing retain their existing behavior.

Frozen numerical adapters, checkpoint formats, weights, and Docker inference
modes remain unchanged. Direct calls to those older numerical adapters still
expose their original behavior; this scope policy applies through the current
supervisor advisor. Other consumers can use the shared assessment and replay
APIs explicitly. A scope-eligible result is grammar coverage, never proof of
intent fidelity or permission to execute the candidate.
