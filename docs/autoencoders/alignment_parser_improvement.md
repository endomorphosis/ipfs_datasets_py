# Opt-in complete qualifier parsing

| Field | Value |
| --- | --- |
| Status | experimental |
| Owner | formalization / Legal IR |
| Source of truth | `canonical_explicit_qualifiers.py`, `canonical_source_guards.py`, and `alignment_parser_experiment.py` |
| Last verified | 2026-10-03 |
| Audience | developer |

The [richer evaluation](alignment_richer_evaluation.md) exposed a parser gap:
its legacy converter inferred procedure chains from event-like words, while
compound qualifier phrases could map to one atom and combined deadlines could
disappear. Suppressing the procedure diagnostic would expose those losses.
This increment instead provides a separately identified, opt-in controlled
English compiler. The frozen default compiler, benchmark identities, parser,
and evaluation fixtures remain unchanged.

The [compiler](../../ipfs_datasets_py/logic/legal_ir/canonical_explicit_qualifiers.py)
uses the existing `CompilerRequest` and `CompilerResult` contracts. It accepts
one complete rule with exact caller-declared actor, action, object, and
qualifier surfaces. It retains each conjunction of conditions, alternative
exception, and conjunction of temporal atoms. Unknown surfaces and unsupported
scope cause an explicit abstention; there is no converter or model fallback.

## Declared grammar

The sentence contains a named actor, `must`, `shall`, `may`, `must not`, or
`shall not`, a named action, an optional named object, optional temporal atoms,
an optional `if` condition, and an optional final `unless` exception. A leading
`if` clause is also accepted when separated from the rule by a comma. A final
period is optional. Only declared clause-separating commas are accepted.

Conditions use `and`, exceptions use `or`, and temporal atoms use `and`.
Opposite or mixed connectives are unsupported. Temporal surfaces must begin
with `within`, `before`, `after`, `during`, or `until`; their names remain
opaque constraints without calendar or solver interpretation.

Atoms use lowercase ASCII words or digits separated by underscores. Their
direct surfaces replace underscores with spaces. Named actors and objects can
take an article. Conditions additionally accept the declared copula forms
`is`, `are`, `has been`, and `have been` before the last atom word. Exceptions
accept the suffix `applies`; both qualifier forms can take an article. Surface
collisions among caller atoms cause abstention. No fuzzy matching, stemming,
synonym inference, hidden reference vocabulary, or development vocabulary
extension occurs.

Sources are bounded to 16,384 characters, each vocabulary slot to 256 atoms,
and complete-parse attempts to 4,096. The profile rejects unsupported
punctuation, multiple sentences or rules, nested scope, undeclared trailing
prose, repeated qualifier atoms, and ambiguous complete parses. Reserved
connectives, modalities, pronouns, and quantifiers cannot be supplied as atom
words to bypass those restrictions. These restrictions define a controlled
language; rejection does not establish that an input has no legal meaning.

The [source guard](../../ipfs_datasets_py/logic/legal_ir/canonical_source_guards.py)
adds a narrow clarification diagnostic for attributed norms with two distinct
named participants and a third-person pronoun as the deontic subject. For
example, “The clerk told the custodian that they must retain the application”
does not identify a unique actor. The guard records the pronoun's exact source
span and competing participant surfaces. It is a pattern detector, not a
general coreference resolver; other unsupported reported-speech structures are
rejected by complete grammar matching.

## Explicit use and composition

~~~python
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CanonicalAtomVocabulary, CompilerRequest,
)
from ipfs_datasets_py.logic.legal_ir.canonical_explicit_qualifiers import (
    ExplicitQualifierCanonicalCompiler,
)

vocabulary = CanonicalAtomVocabulary(
    actors=("agency",), actions=("file",), objects=("notice",),
    qualifiers=("public_interest", "public_safety", "emergency", "legal_hold",
                "within_48_hours"),
)
result = ExplicitQualifierCanonicalCompiler().compile(CompilerRequest(
    "The agency must file notice within 48 hours if public interest and "
    "public safety, unless emergency or legal hold.",
    "explicit-qualifier-example", vocabulary,
))
~~~

The configuration CID differs from the frozen typed-deontic configuration.
Result provenance identifies the opt-in profile, complete-source consumption,
and absence of benchmark admission or default replacement. Source maps use
the whole rule span as coarse attribution for each facet; they do not identify
individual token-to-atom alignments.

The existing frozen `CanonicalSemanticRoundTrip` rejects this different
configuration CID before execution. The experiment explicitly invokes the new
compiler, constructs an IR-only request to the existing source-withheld
renderer, and invokes the new compiler again on its rendering. This separately
identified composition is a preservation diagnostic, with no claim of frozen
benchmark admission. It never provides the renderer with the original source,
reference target, source map, or compiler provenance.

## Reproduce the development comparison

Use the [configuration](../../configs/autoencoders/alignment_parser_development_v1.json)
and a fresh output directory:

~~~bash
python scripts/ops/legal_ir/run_alignment_parser_experiment.py \
  --output-directory /tmp/alignment-parser-development-01
~~~

The [CLI](../../scripts/ops/legal_ir/run_alignment_parser_experiment.py) accepts
`--config` and `--workspace-root` for other layouts. The
[runner](../../ipfs_datasets_py/logic/formalization/autoencoder/alignment_parser_experiment.py)
requires the frozen richer report, panel, construction records, and assays to
match their configured hashes. It verifies the prior source bindings and
protected protocol bytes, rebuilds the training-only vocabulary, and reruns the
old source compiler. All 34 old construction records must match exactly before
the alternative profile is scored.

The new compiler receives only source text, request identity, and the frozen
training vocabulary. Explicit-context inputs remain separately bound and
unavailable; no assumption is inferred or injected. References enter posthoc
scoring after construction. The deadline is cooperative between cases and
cannot preempt one synchronous call. Failure before completion prevents
publication of a completed report.

The run publishes `constructions.json` and `report.json`, retaining the prior
panel, baseline, and representation artifact bindings. It rechecks source and
input bytes before publication. Bindings cover the listed implementation files,
rather than a complete transitive dependency closure or process-access trace.

## Evidence limits

This grammar was designed after examining the exposed development diagnostics.
Its report declares `development_used_to_design_grammar=true`; improvement on
this panel is exploratory regression evidence, not a new held-out result.
The panel remains synthetic, authored, and unreviewed. All reports retain
`qualified=false` and `production_admitted=false`.

Schema acceptance, exact authored-reference agreement, candidate round-trip
preservation, and bridge transport are distinct outcomes. The same ambiguity
example passed the old compiler and round-trip check; preservation alone could
not detect its unresolved actor. New negative-case abstentions also do not
establish general semantic detection or the ability to conduct clarification.
The application must surface the diagnostic to obtain an explicit answer.

No encoder, autoencoder, Leanstral weights, provider, solver, or kernel runs.
The independent 8D, 384D, and 768D source lanes and the 22D/27D formal codecs
remain as described by their existing contracts. Native interpretations,
independent review, structural representations, and matched numerical
retrieval-conditioned generation comparisons remain subsequent work.

Focused verification:

~~~bash
python -m pytest -q \
  tests/unit/logic/legal_ir/test_canonical_source_guards.py \
  tests/unit/logic/legal_ir/test_canonical_explicit_qualifiers.py \
  tests/unit/logic/formalization/autoencoder/test_alignment_parser_experiment.py
~~~
