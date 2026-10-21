# Definition evidence for exact norm term uses

`logic.autoformal.legal_norm_definition_evidence_v1` connects an existing norm
interpretation preparation to separately replayed contextual definition-review
correspondences. The new record is an unsigned companion. Neither the norm
subject nor the definition subject is rewritten, and their signatures do not
cover this new association.

This extends evidence transport to arbitrary supported variable or predicate
occurrences in the relational norm grammar. The existing V2 definition-use
adapter instead combines two unary definitions under an explicit alias
assumption. That adapter and its signing domain remain unchanged.

## Original inputs

```python
report = prepare_norm_definition_evidence_v1(
    norm_preparation,
    request_raw,
    expected_norm_preparation_sha256=retained_norm_preparation_hash,
    expected_request_sha256=retained_request_byte_hash,
    norm_inputs=original_norm_preparation_arguments,
    definitions=ordered_definition_evidence,
)
```

`norm_inputs` contains all original arguments to
`prepare_norm_review_evidence_v1`, including the source correspondence, full
replay inputs and shared contextual packet. The complete preparation is
regenerated and compared exactly. A stored success flag or a newly recomputed
hash cannot substitute for original-source replay.

Each definition endpoint has these closed fields:

- `alternative_id`: an explicit local alternative identity.
- `correspondence` and `expected_correspondence_sha256`: the complete contextual
  definition-review correspondence and its independently retained canonical hash.
- `correspondence_inputs`: all original named arguments to
  `prepare_contextual_definition_review_correspondence_v2`, including
  `binding_result`, `review_subject`, original candidate bytes and pins, physical
  context population, dependency manifest and complete contextual replay inputs.
- `review_evidence`: explicit `None`, or `assessment`,
  `expected_assessment_sha256` and `assessment_inputs`. The latter contains the
  complete named arguments to `assess_definition_reviews_v2`, including its
  independently selected trust inputs, explicit evaluation time, dependency
  observations and evidence bytes.

The contextual correspondence is always replayed. A supplied assessment is
also replayed against the exact same definition candidate, subject, physical
context population and manifest. An absent assessment remains explicitly absent.
An empty review population remains pending; supplied pending, rejected or
authenticated evidence statuses are preserved. None establishes an approved
definition meaning.

## Explicit occurrence links

The original UTF8 request has exactly `schema`, `interpretation_status`,
`norm_preparation_sha256` and `links`. Its schema is
`legal-norm-definition-evidence-request/v1`; its interpretation status is
`authored_unreviewed_definition_nomination`.

Each link contains `alternative_id`, `target`, `source_paths`,
`nomination_sha256` and a bounded authored `rationale`.

`target` is the complete existing structural-mapping record for one variable or
predicate occurrence. A symbol name alone cannot identify an occurrence.
`source_paths` must equal that target's complete ordered inverse source mapping;
an authored scaffolding node does not qualify as a source-linked term use.
Binder, argument position and modal ancestry remain attached to the exact
occurrence. They do not establish an entity's real-world referent.

`nomination_sha256` hashes the complete selected row in the norm preparation's
`context_evidence.nominations`. This is distinct from the inner attachment
nomination hash. The link must target the exact norm source/unit and support a
required scope or contributor subject of the chosen definition. Another unit
in the same source, a different edition or an unrelated attachment is not a
substitute. Both endpoint replay groups must retain the same complete shared
context packet, source population and attachment population.

Competing alternatives may be linked to the same occurrence. Repeated variable
or predicate uses have separate paths and separate links. Every supplied
alternative must be referenced; duplicate links are rejected. The result
accounts for the declared links, not every possible interpretation or every
term in a statute.

## Authority and downstream use

The companion retains evidence commitments, exact occurrence context and
unresolved source obligations. It makes no alias assumption and does not create
an admitted `USES_DEFINITION` graph edge. `governing_definition_use` remains null;
semantic, applicability, admission, proof and training authority remain false,
with integer-zero training and evaluation masks.

Authentication of a definition review, if supplied, only establishes the
reviewer's statement under the selected trust configuration. It does not review
the new norm-to-definition association. Actual governing use requires a separate
source/meaning/applicability decision; the companion supplies no reviewer,
registry, policy or clock default.

Use `norm_definition_evidence_sha256(report)` for the complete canonical output
commitment. `validate_norm_definition_evidence_v1(report, ...,
expected_report_sha256=retained_hash)` takes the same original arguments,
regenerates the report and compares exact canonical bytes. The new record
requires the full external replay inputs; its compact commitments do not make
those inputs optional.

The profile accepts 1–16 alternatives and 1–128 explicit links. It bounds the
original request at 1 MiB, the complete detached input population at 128 MiB
and the canonical output at 8 MiB. Existing endpoint limits also apply.
The companion's aggregate snapshot has an explicit 4,000,000-node ceiling;
ordinary norm snapshots retain their 1,500,000-node default. This accommodates
the repeated full shared context in independently replayed endpoints. It keeps
all copies and counts each traversal, with the same aggregate byte accounting,
depth ceiling of 96 and 32-MiB limit on an individual byte body. It does not
multiply the allowance by the number of alternatives. The same aggregate
profile applies to both original and detached mutation fences, before replay
and after each operation. Individual endpoint owners and component equality
checks retain their existing limits. This changes a resource admission
profile, not meaning, applicability, review or training acceptance.
Alternative identities are at most 256 characters, rationales 8,192 characters
and each link's source-path population 2,048 entries. Oversize complete evidence
is rejected without truncation; these byte bounds are not process-memory quotas.

No model, training, solver, Lean build, publication or automatic corpus admission
is performed. Native Lean qualification and independently reviewed learning
targets remain downstream requirements.
