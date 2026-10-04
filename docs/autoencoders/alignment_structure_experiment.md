# Canonical structural features and richer review preparation

| Field | Value |
| --- | --- |
| Status | experimental exposed-development diagnostic |
| Owner | formalization / Legal IR |
| Source of truth | `alignment_structure.py`, `alignment_richer_review.py`, and `alignment_structure_experiment.py` |
| Last verified | 2026-10-03 |
| Audience | developer and review organizer |

This stage preserves the existing seven-facet Legal declaration in an
open-vocabulary structural feature artifact and prepares a separate blank
source/context review packet. It does not change statement generation. The
[prior parser comparison](alignment_parser_improvement.md) supplies the frozen
construction baseline, including its prior 22/24 positive authored-reference
matches. Representation changes cannot increase that count by themselves.

The richer corpus remains synthetic, authored, unreviewed, and exposed during
development. Its 34 available inputs comprise 24 positive references, six
unsupported cases, two ambiguous cases, and two explicit-context
interpretations. Authored targets are admissible structural diagnostic inputs;
they are not independently reviewed source meaning.

## Existing owner and exact preservation

The [structural extractor](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_structure.py)
accepts an existing
[CanonicalRoundTripIR](../../ipfs_datasets_py/logic/legal_ir/canonical_contracts.py)
object or its closed `{"rules": [...]}` wire shape. The owner normalizes rule
order, preserves duplicate rule occurrences, and sorts and deduplicates each
qualifier list. The extractor binds that normalized declaration rather than
the original ordering or repeated qualifier spelling.

Each rule retains modality, actor, action, object, conditions, exceptions, and
temporal atoms. Atom strings are exact and opaque. The structural profile
declares conditions as `all`, exceptions as `any`, and temporal atoms as
`all_opaque_constraints`. Those declarations describe the controlled flat
grammar; they do not supply calendar interpretation, legal activation rules,
nested scope, variable binding, or a proof of equivalence to source prose.

The feature dictionary includes complete rules, core tuples, typed atoms,
qualifier lists with their declared connectives, and core-associated qualifier
atoms. Complete-rule descriptors retain the relationship between every
qualifier list and every other facet of that rule. Local descriptors provide
shared features without replacing the complete rules. Rule multiplicity is a
count, so a second identical rule remains a second occurrence. Reordering
rules preserves the structural artifact.

`restore_structural_ir` reconstructs the normalized declaration from complete
rule descriptors and their counts. Validation rebuilds the features from the
bound owner IR and rejects altered dictionaries, counts, identities, and
authority claims. Exact reconstruction means preservation of the normalized
seven-facet rule multiset. It establishes neither source correspondence nor
logical equivalence beyond that representation.

The extractor supports at most 64 rules, 16 qualifiers per facet, 256
characters per atom, 8,192 distinct features, and an 8 MiB artifact. It accepts
only this deontic Legal profile; additional families or fields require their
own explicit contracts. It does not parse binders or relabel flat declarations
as validated `TypedExpression` formulas.

## Sparse names and fixed hashed coordinates

Descriptor names bind their complete typed JSON content with SHA-256. The
profile uses sorted compact UTF-8 JSON without Unicode normalization. Its
dictionary checks that an already encountered name never denotes a different
descriptor. SHA identities still rely on the hash assumption; they are
integrity bindings, not semantic proofs.

The existing
[FormalizationFeatures](../../ipfs_datasets_py/logic/formalization/features.py)
envelope carries finite immutable sparse numeric counts. Source text, original
case identities, compiler outcomes, reviewer answers, and proof results are
absent from the feature coordinates. Formal declaration atoms and rule
descriptors are intentionally present in the accompanying dictionary. Source
and audit bindings remain separate from numeric model input.

Open-vocabulary sparse values require their names. Two value arrays with
different feature names do not share coordinates merely because their lengths
match. The envelope's values-only `model_input` cannot by itself make such
arrays comparable.

`encode_structural_features` supplies a separate fixed-coordinate baseline at
2,048 or 4,096 dimensions. SHA-256 maps each feature name, profile, and declared
seed to a coordinate modulo the dimension. Counts are positive unnormalized
integer sums. No vocabulary is fitted, no projection is trained, and these
counts are not learned embeddings or an autoencoder latent representation.

Finite coordinates introduce collisions. The hashed artifact retains token
assignments, collided buckets, and distinct-feature collision-pair counts.
Complete reconstruction uses the exact dictionary; it is unavailable from
hashed counts alone. Per-record collision traces do not prove the absence of
collisions between aggregate vectors of different declarations. Likewise,
observed separation on this small panel cannot establish general injectivity
or preservation after a subsequent learned projection.

The 2,048D/4,096D formal count spaces are independent of the existing 8D,
384D, and 768D source representations. This stage does not load or compare
those source encoders, retrain their autoencoders, or extract Leanstral states.

## Candidate-blind human review handoff

The [review preparation helper](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review.py)
includes every available input from the
[richer panel](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_panel.py).
All 34 annotations start blank and pending. Item ordering and pseudonyms depend
on source/context input identity, never reference targets or construction
scores. Preparation creates no completed reviews or reviewer attestations.

Give reviewers **only the reviewer payload and its reviewer audience
manifest**, published as `reviewer_items.json` and `reviewer_manifest.json`.
Keep `review_bundle_private.json`, `organizer_private.json`, and
`organizer_manifest_private.json` private. These audience names do not enforce
filesystem access control; the organizer must control distribution. The
organizer key contains original identities, partitions, case
types, authored expectations, and reference targets. Sending it would expose
the proposed answers.

Each reviewer item contains exact source text and digest, its separately
declared context and digest, the combined input binding, a pseudonymous item
ID, and blank annotations. It withholds references, candidates, expected
dispositions, case groups, training/development partitions, vectors, and
compiler outcomes. The same source under two distinct explicit assumptions
remains two different input-bound items. Context bindings are disclosed
caller assumptions; they are not inferred from the source or proposed by a
model.

Annotations permit interpretation status, ambiguity, unsupported meaning,
normative rules, free-form qualifier scope, notes, reviewer identity, and UTC
review time. Reviewers can explain relationships, alternative meanings,
binders, and timing that seven flat facets cannot express. A null field means
unanswered. An explicit empty normative-rule list requires an actual
interpretation and reasons; blank preparation cannot establish absence of
meaning.

`validate_richer_review_bundle` validates only the closed blank preparation and
its integrity bindings. Submitted annotations require a separate admission
interface. The original 40-item review schema and receipt cannot be reused for
this richer packet. A declared reviewer name alone supplies no authenticated
identity or author-independence evidence. Qualification, independent fidelity,
and proof authority remain false.

## Reproduce the development diagnostic

From the canonical datasets repository, use the
[configuration](../../configs/autoencoders/alignment_structure_development_v1.json)
and a fresh output directory:

~~~bash
python scripts/ops/legal_ir/run_alignment_structure_experiment.py \
  --config configs/autoencoders/alignment_structure_development_v1.json \
  --output-directory /home/barberb/lift_coding/artifacts/autoformalization-alignment-20261003/structure-01
~~~

The [CLI](../../scripts/ops/legal_ir/run_alignment_structure_experiment.py)
calls the
[runner](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_structure_experiment.py).
The run publishes `report.json` and `representation_assays.json`, covering
`authored_positive_references`, `emitted_candidates`, and
`structural_challenges`, together with the five audience-separated review
files above. The challenge targets are explicit structural regressions, not
new source meaning or independently reviewed evaluation gold.

Preserve each run's report and its bound feature, collision, reconstruction,
and review artifacts together. Consult the produced report for exact artifact
paths, hashes, counts, and completion status. This runbook states the protocol
and makes no new measured-result claim.

Construction receipts remain bound to the prior parser composition. References
enter the representation assay and post-construction authored diagnostics;
they do not enter source construction or reviewer sampling. Structural
reconstruction, numerical collision rates, authored-reference agreement,
candidate round-trip preservation, and completed human review are separate
endpoints. A new structural feature artifact is not an improved generated
formal statement.

Explicit-context construction remains unavailable under the current source-only
compiler. The review packet exposes assumptions to humans without making an
automatic contextual resolution claim. Unsupported binders, nested scope, and
native legal or temporal semantics remain outside this structural profile.
No LLM, encoder, provider, native solver, or kernel proof is required. All
evidence remains an unqualified exposed-development diagnostic, with
independent source fidelity unavailable and useful native proof coverage unrun.

Focused helper verification:

~~~bash
python -m pytest -q \
  tests/unit/logic/formalization/autoencoder/test_alignment_structure.py \
  tests/unit/logic/formalization/autoencoder/test_alignment_richer_review.py
~~~
