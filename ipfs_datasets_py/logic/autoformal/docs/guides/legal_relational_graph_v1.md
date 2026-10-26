# Ordered relational requests in proposed legal graphs

`legal_semantic_graph` accepts the explicit `relational_norm_v1` profile in its
existing `build_graph`, `graph_to_ast` and `validate_graph` APIs. It transports a
complete authored [`legal_relational_norm_v1`](legal_relational_norm_v1.md)
request through the existing ordered JSON tree representation. No additional
AST or graph codec is introduced.

The graph nominates one source paragraph and an explicit scope. This is custody
and declared association, not a reviewed translation of that paragraph. The
relational request's `source_binding` remains null. Adding an outer graph source
does not populate it or establish source meaning, applicability or authority.

## Input and validation

Pass the complete existing relational request as `ast`, including its typed
expression, signature, namespace identities and ordered argument roles:

```python
request = {
    "schema": "legal-relational-norm-request/v1",
    "interpretation_status": "authored_unreviewed_declaration",
    "expression": typed_expression.to_dict(),
    "argument_roles": [
        {"symbol": "Assign", "roles": ["actor", "recipient", "origin", "destination"]},
        # Supply exactly one ordered role list for every declared predicate.
    ],
    "source_binding": None,
}

inputs = {
    "profile": "relational_norm_v1",
    "source": source_occurrence,
    "scope": explicit_scope,
    "scope_request": None,
    "semantic_declarations": None,
    "dependency_refs": [],
    "evidence_refs": [],
}
proposal = legal_semantic_graph.build_graph(request, **inputs)
restored_request = legal_semantic_graph.graph_to_ast(proposal)
validation = legal_semantic_graph.validate_graph(proposal, ast=request, **inputs)
```

`source_occurrence` must come from the existing `bind_source_occurrence` over
an independently retained normalized document, exact HTML, selector and revision.
`explicit_scope` uses the existing `bind_scope`. The source selector still must
lie within one paragraph, and source and scope editions must agree. The example
uses an already constructed typed expression; it supplies no prose-to-formula
inference or actual legal interpretation.

The relational branch requires `scope_request=None` and calls the existing
public `prepare_relational_norm_v1` on canonical request bytes with their exact
SHA256. This invokes the existing strict typed/native structural validation.
It neither substitutes a weaker schema check nor repairs an unsupported request.
The original `canonical_rules_v1` and `normative_scope_v1` routes remain separate.

The relational owner enforces bound Object variables, declared predicate arity,
ordered roles, binary Boolean operators, unary negation, individual quantifiers
and the existing O/P/F extension. Free variables, binder shadowing, unsupported
extensions, extra fields, constants, equality, counting, purpose and anaphora
remain unsupported. Actor/recipient or other role names remain caller labels,
not inferred legal sorts or validated source roles.

The existing 4,096-node and 1 MiB graph-JSON limits remain unchanged. Tree
depth is profile-specific: `relational_norm_v1` accepts at most 32, while
`canonical_rules_v1` and `normative_scope_v1` retain 24. The relational owner's
independent request and grammar limits still apply. Inputs above their selected
profile bounds are refused, never truncated or flattened to fit.

## What the round trip preserves

The transported value is the complete request, not only its typed expression.
`ast_sha256` hashes the canonical full request; it is distinct from the typed
expression's own content identity or the complete relational report hash. The
tree retains every declared field and ordered array, including predicate roles,
argument order, quantifier order, negation and modal/connective nesting. It does
not sort or deduplicate expression arguments or silently normalize formulas.

The existing decoder checks node and graph commitments, paths, node kinds,
edge order, endpoint existence, single-parent structure, cycles, orphan nodes,
source/scope bindings and exact AST reconstruction. It then invokes relational
validation again. `validate_graph` additionally regenerates the whole proposal
from independently supplied request, source, scope and declaration inputs.
Replacing a request and recomputing hashes does not authenticate the replacement
as the original; retain the independent input commitments.

This is exact structured JSON preservation. Original whitespace and object-key
serialization order are not part of the AST identity. Retain original raw
request bytes and their independent hash separately when raw-file provenance
is required. The graph does not retain a previous relational preparation report
or claim that its producer-dependent report bytes were replayed unchanged.

The optional existing entity/assertion declarations remain separately authored
and unreviewed. They are not inferred from relational argument roles. Preserving
a relational predicate does not create a validated legal entity, definition-use
edge or governing norm.

## Existing corpus custody and exchange

[`corpus_proposed_graph_adapter`](legal_corpus_proposed_graph_adapter.md) can
validate this proposal through the existing graph API and retain the original
proposal bytes, complete AST companion, input commitments and independent
source custody. Its projection remains `ordered_ast_custody_only`. The opaque
proposal retains semantic declarations; the adapter does not reinterpret them
as qualified relational role or legal-definition graph edges.

For this profile, the adapter uses the versioned
`legal-corpus-proposed-ast-custody/v2` AST companion. It contains `ast_json`, the
UTF8 text of the full request's canonical DAG-JSON bytes, plus `ast_sha256` and
`ast_cid`. The profile, source-occurrence CID, custody status and false semantic
authority are retained. This avoids nesting the rich request inside additional
envelopes past the corpus contract's existing depth limit. It does not increase
any shared limit, flatten the request, or omit expression/role fields. Older
graph profiles keep their original v1 embedded `ast` companion shape and bytes.

Use `restore_proposed_graph_ast(candidate, **validation_inputs)` with the same
independently pinned source/proposal inputs required by
`validate_proposed_graph_candidate`. The restore API first performs that complete
regeneration. For v2 it then checks the stored byte hash using the existing
bounded JSON loader and verifies canonical bytes and AST CID before returning
the complete request. V1 companions restore their detached embedded AST. A
changed JSON string, repaired local hash or changed role ledger cannot bypass
independently retained proposal/input commitments. Shared corpus depth and
aggregate byte limits still apply to the independently supplied inputs and the
serialized candidate; graphs that exceed those limits remain unsupported.

The existing [`corpus_graph_exchange`](legal_corpus_graph_exchange.md) can export
and import the adapter's corpus graph envelopes. Its Parquet bundle carries
nodes, edges and snapshot records; it does not embed the full proposal/AST
companion by implication. Retain and independently pin the complete candidate
record alongside the bundle, then use the validated restore API to recover the
relational request. An exchange
round trip alone establishes envelope custody, not AST recovery from the bundle
alone or semantic admission.

## Review and execution boundaries

The generic `legal_graph_review` subject builder can receive this profile through
the shared graph validator. It binds the graph and full request hash, the six
generic source-context dependency slots and the supplied dependency closure.
It does not supply the dedicated norm interpretation question/issue population
or replace [`legal_norm_interpretation_review_v1`](legal_norm_interpretation_review_v1.md).
Generic review prerequisites must not be interpreted as
`norm_interpretation_ready`. No actual review, selected signer or trust policy is
created by constructing a relational graph.

The graph stays `proposed_unreviewed`, with `original_task_acceptance` equal to
`preparatory_subset_only` and every graph authority flag false. The corpus
adapter likewise leaves admission, formalization, source semantics and
definition semantics false. This profile grants no training/gold eligibility,
accepted view, governing binding or proof authority.

Relational validation uses native parsing and generates Lean text internally.
No `lake build`, solver execution, model inference, training, network access or
publication is introduced by this profile. A structural qualification should
report exact round trips and negative controls separately from any later actual
statutory review or Lean qualification. The contract sections above do not assert execution outcomes. The retained
qualification below records its original engineering and data-operation scopes
separately.

## Profile-specific depth and retained qualification

The existing owner uses `RELATIONAL_MAX_DEPTH=32` only for `relational_norm_v1`.
`canonical_rules_v1` and `normative_scope_v1` retain `MAX_DEPTH=24`, and existing
node, wire, schema, grammar and ordered-identity contracts remain unchanged.
Unknown profiles and over-depth requests refuse rather than truncate.

The [original focused qualification](../../../../../docs/autoformalization/evidence/legal-ir-source7346-relational-graph-depth-focused-20261025.json)
passed 13 cases (10 new, three legacy) across eight selectors, on exact b7 source
and unchanged c841 owning tests. Phase events were not counted; no 39-phase
result is claimed. The explicit `semantic-graph-depth-parent:numbered_false/v1`
fixture proxy changes only `tmp_path_factory.mktemp` for one basename to avoid
its best-effort `current` symlink; no legal AST/source helper is replaced.
Ordinary unadapted pytest and the whole current public runtime were not
qualified. Earlier failures keep zero credit; the unselected test-fix candidate
is not part of this delivery.

The [separate original parent-graph observation](../../../../../docs/autoformalization/evidence/legal-ir-source7346-parent-proposed-graphs-20261025.json)
retains 837 parent records and 16 cache rows. Both unchanged authored A/B
alternatives have 693 nodes, 692 edges and depth27, beyond the old depth24
relational boundary. Four shared proposed lexical mentions lie within the same
one selected `(c)` physical occurrence, with zero relationship assertions.
They supply neither two distinct statutory uses nor selected meaning, edition,
governing definition or accepted entity resolution. The relational request's
source binding remains null; earlier scope/correspondence generation is retained
as inert references, without fresh current scope/correspondence qualification.

The earlier HTML example keeps its paragraph-selector contract. The existing
literal-parent route instead uses `bind_parent_source_occurrence` and
`bind_parent_scope` with complete independently pinned physical parent/producer
inputs and an undeclared edition. A parent occurrence is not thereby a
paragraph or governing legal source.

These exact source/test and literal evidence files reuse their original
qualifications. This adoption runs no new tests, model/training, SQL, solver or
Lean process. Current public use requires fresh original inputs and exact current
producer commitments; do not normalize paths/hashes, reseal or relabel private
packets/preparations/index identities or old receipts as a new generation.
Graphs stay proposed/unreviewed, authority false and learning/gold masks zero.
The separately bounded corpus adapter, complete context/meaning review,
definition/two-use closure, reconstructable corpus and Lean admission keep their
own gates. Prior depth24 deployment observations retain their historical scope.
