# Richer Legal IR development evaluation

| Field | Value |
| --- | --- |
| Status | canonical |
| Owner | formalization / autoencoder development |
| Source of truth | `alignment_richer_panel.py`, `alignment_richer_evaluation.py`, `alignment_richer_experiment.py`, and the existing canonical Legal IR compiler and decompiler |
| Last verified | 2026-10-03 |
| Audience | developer |

This development stage checks actual construction of Legal IR with nonempty
conditions, exceptions, and temporal qualifiers. It also measures whether the
existing categorical formal-feature codec collapses distinct authored targets.
The fixtures are manually authored, synthetic, and unreviewed. Agreement with
these references is a regression diagnostic; independently adjudicated source
fidelity and native-checker-accepted useful proof coverage remain separate
outcomes.

The stage extends the [initial development study](alignment_study.md). It runs
the existing deterministic compiler and source-withheld decompiler. It loads
no encoder, autoencoder, projection checkpoint, or Leanstral weights, performs
no numerical model training, and invokes no provider or prover. The protected
AF-002 final-test material is outside its input scope.

## Run from the datasets repository root

Use the [richer configuration](../../configs/autoencoders/alignment_richer_development_v1.json)
and a fresh output directory:

~~~bash
python scripts/ops/legal_ir/run_alignment_richer_experiment.py \
  --config configs/autoencoders/alignment_richer_development_v1.json \
  --output-directory /tmp/alignment-richer-development-01
~~~

The [CLI](../../scripts/ops/legal_ir/run_alignment_richer_experiment.py) uses the
same enclosing-workspace path convention as the initial study. Supply
`--workspace-root` for another repository layout. An existing destination or
symlink is rejected. Preserve each evidence generation and choose another
fresh path after changing its configuration, input, or implementation.

The configuration binds the original study configuration by its exact bytes.
That study supplies the protected protocol bindings and original exposed
training corpus. The richer panel is authored by the
[panel helper](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_panel.py)
and serialized into the fresh evidence directory. The runner binds its listed
source files and rechecks inputs before sealing its report. These bindings
cover the listed sources, rather than a complete transitive dependency closure.

The evidence directory contains `panel.json`, `constructions.json`,
`representation_assays.json`, and `report.json`, with recorded byte digests.
The deadline is cooperative: checks occur between cases and cannot preempt an
individual synchronous compiler call. A deadline failure stops publication of
the completed report. Completion establishes execution of the declared
development checks; it does not qualify the scheme or admit it to production.

## Authored fixtures and source boundaries

Source-only positive bundles exercise obligation, permission, and prohibition;
multiple conditions; multiple exceptions; and temporal qualifier atoms. Their
train/development identities are explicit. Conditions are flat conjunctions,
exceptions are flat alternatives, and temporal values are retained as flat
constraints. This Canonical IR contract does not supply quantified binders,
arbitrary logical scope, interpreted clock arithmetic, or native deontic
semantics.

The panel also includes authored unsupported and ambiguous cases, and separate
explicit-context bundles. Their expected abstention or clarification is an
unreviewed expectation. An emitted candidate on an unsupported case must remain
visible; parser acceptance is insufficient evidence that its interpretation is
faithful. An observed empty or failed output does not establish a general
ability to recognize unsupported semantics.

Context bundles bind their exact source and explicit assumptions separately.
The current canonical compiler accepts source text with its measured general
document configuration and has no context-resolution input. These bundles are
therefore unavailable under this stage's source-only contract. A source-only
accessor rejects them rather than silently dropping their assumptions. The
panel's input identity distinguishes different assumptions attached to the
same source.

No source vectors are computed for this richer panel. In particular, the
original cached 384D producer's `exact_source_no_truncation` policy does not
establish context-aware embeddings. Contextual inputs will require their own
explicit encoding policy and actual encoder receipts.

## Actual construction and post-construction scoring

The [evaluation adapter](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_evaluation.py)
accepts source text and a frozen training vocabulary. It constructs a compiler
request, runs the
[canonical compiler](../../ipfs_datasets_py/logic/legal_ir/canonical_compiler.py),
renders an accepted candidate through the
[source-withheld decompiler](../../ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py),
and runs the compiler again on that rendering. The authored development target
is not an input to construction. Training references alone supply the atom
vocabulary; development references do not extend it.

An emitted candidate is also passed through the existing canonical bridge
wrapper. That operation records typed transport views and unsupported
constructs. Its execution is distinct from checking satisfiability, running a
native solver, or obtaining a kernel proof.

Reference scoring follows construction. It reports core-facet agreement and
qualifier true positives, false positives, and false negatives, including
migration between condition, exception, and temporal facets. Compiler errors
and missing candidates remain in case accounting. Exact reference agreement
and candidate round-trip agreement answer different questions: an incorrect
candidate can render and reparse consistently.

The existing
[round-trip contract](../../ipfs_datasets_py/logic/legal_ir/canonical_roundtrip.py)
defines successful execution as completion of the stages and their evidence
chain. It explicitly leaves semantic parity to separate scoring. Schema
acceptance alone is also a different check from running the source compiler.

## Train-only formal-feature collision assay

The runner compares the old training-only codec with a codec fit on the richer
panel's training references. It encodes authored targets using the existing
[categorical and bag-feature codec](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_projection.py).
No projection head is fit or loaded. Development targets enter only this
post-construction diagnostic, after both codecs are frozen.

Each facet has an explicit unknown bucket. Two distinct unseen qualifier
atoms in the same facet can produce the same vector; equal numbers of unseen
atoms can also collide. Duplicate wordings of an identical target do not count
as distinct-target collisions. The assay reports distinct payloads, distinct
feature vectors, collision groups and pairs, differing facets, unknown atom
counts, and per-row feature bindings. Collision pairs with identical core
facets are reported separately from collisions of unknown core values.

Equal feature vectors necessarily remain equal through a deterministic head.
Distinct feature vectors may still collide after projection. The assay
therefore diagnoses information loss in this codec, without establishing
encoder quality, learned geometry, or preservation of binder and scope
semantics. Adding known training qualifier atoms can remove some collisions
while leaving collisions among unseen development atoms.

## Evidence limits and verification

Reports retain `qualified=false` and `production_admitted=false`. Primary
source fidelity remains unavailable without independent adjudication. Native
useful proof coverage remains unrun. Installing or discovering a prover,
constructing Lean source, or finding a saved historical receipt supplies no
new proof for these cases. The existing
[qualified Legal-to-Lean path](../../ipfs_datasets_py/logic/formalization/autoencoder/native_legal_qualified_lean.py)
requires explicit caller-supplied qualifier interpretations and actual scoped
native execution; flat atoms do not provide those interpretations.

The original 40-item review queue belongs to the earlier empty-qualifier panel.
It does not review this richer panel. Independent review and formal
interpretations need new source-bound evidence before any stronger claim.

Focused validation from the datasets root:

~~~bash
python -m pytest -q tests/unit/logic/formalization/autoencoder/test_alignment_richer_experiment.py
~~~

Use the produced report for the measured case counts, statuses, qualifier
losses, collision results, source bindings, and timing of a particular run.
The [autoencoder handbook](README.md) and
[parallel lane contract](parallel_lineage_execution.md) continue to own the
independent 8D, 384D, and 768D encoder/autoencoder lanes.
