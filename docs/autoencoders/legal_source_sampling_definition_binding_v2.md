# Bind sampled-source review to a V2 definition candidate

`logic/autoformal/legal_source_sampling_definition_binding_v2.py` connects an
explicit V2 interpretation request to the existing complete sampled-source
review bundle, definition compiler and definition-only corpus adapter. Source
findings and meaning proposals remain independently retained declarations.
Reviewer prose is never parsed into an AST.

The supported interpretation is the existing caller-declared unary definition
profile: `forall x, head(x) iff body(x)` with bounded Boolean body expressions,
through either `fol` or `tdfol`. The original bridge and corpus adapter retain
their validation and producer identities. Unsupported scope, operators, arity or
source declarations refuse through those owners.

## Input commitments and replay

Retain the exact original request JSON bytes, complete review bundle, original
HTML and acquisition descriptor. The bundle contains the complete sampler
report once, including unselected units and unresolved context. Independently
retain each input commitment before passing it to this adapter.

```python
from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_definition_binding_v2 as binding,
)

trusted = dict(
    expected_request_sha256=original_request_file_sha256,
    expected_bundle_sha256=complete_bundle_canonical_sha256,
    expected_response_sha256s=ordered_complete_response_canonical_sha256s,
    expected_sampling_report_sha256=complete_sampler_canonical_sha256,
    descriptor=original_acquisition_descriptor,
    expected_descriptor_sha256=descriptor_canonical_sha256,
    expected_raw_sha256=original_html_sha256,
    expected_raw_bytes=original_html_length,
)
result = binding.prepare_definition_binding_v2(
    original_request_json_bytes, complete_bundle, supplied_responses,
    original_html_bytes, **trusted,
)
# Store this commitment independently of a later incoming result.
expected_result_sha256 = binding.definition_binding_sha256(result)
binding.validate_definition_binding_v2(
    result, original_request_json_bytes, complete_bundle, supplied_responses,
    original_html_bytes, expected_binding_sha256=expected_result_sha256,
    **trusted,
)
```

The request commitment hashes its original bytes, preserving whitespace and
transport custody. Bundle, response, sampler and result commitments hash the
complete canonical JSON, including their internal hashes and CIDs. These are
distinct from payload hashes. Computing a hash from an incoming artifact alone
does not make it an independently trusted input.

Public import uses only the standard library. Before loading operation owners,
the adapter checks finite bounded ordinary JSON, duplicate-free original
request bytes, exact HTML bytes, complete input commitments and ordered
response pins. Then the public review owner regenerates the complete bundle
and every response. The existing bridge replays source extraction and compiles
the explicit request; the corpus adapter independently regenerates its report
and candidate. Validation regenerates the complete output envelope, so a
resealed changed AST, source binding, population or authority field is refused.

Bounds are 1 MiB per request, response or output companion; 64 MiB for a bundle
and the aggregate response input; 8,192 responses; 4,096 guide subjects; and
4 MiB for the complete result. Overflow refuses instead of truncating evidence.
Existing source/view/sampling owners enforce their own additional bounds.

## Source roles and population

The result has exactly five top-level fields:

| Field | Contents |
| --- | --- |
| `schema` | `legal-source-sampling-definition-binding/v2` |
| `binding` | Sealed input, producer and companion commitments; exact selected subjects and role mappings |
| `definition_report` | Regenerated existing V2 native AST, emitted Lean text and source/context bindings |
| `candidate` | Regenerated existing definition-only corpus candidate with closed graph endpoints |
| `population` | Complete ordered review population, including unselected subjects |

Both the whole scope unit and every contributor unit become required subjects.
Every compiler report binding maps its exact occurrence interval to all
intersected original blocks. Repeated atoms preserve separate occurrences even
when they share a native predicate symbol. Multiple roles in one physical
subject remain separate role bindings. Intersecting withheld parent contexts
also become required review subjects; missing evidence is refused.

Every supplied response must address a required selected subject. Preserve all
revisions and competing declarations with their original ordered references;
there is no latest-wins selection. Empty responses are valid: the caller's
explicit interpretation can produce a candidate while every subject remains
pending. An absent selected response never becomes a completed declaration.
The full population retains unselected pending subjects instead of shrinking
the denominator to the selected definition.

The binding reports `pending`, `disputed`, `unsupported` or
`declarations_recorded` using existing intake states. These states describe
recorded declarations, not agreement with the caller's AST or independent legal
review. Even a complete declaration population leaves all authority flags false
and training/evaluation gold masks at zero.

## What the candidate establishes

Exact source custody, native AST round trips and emitted Lean text remain
separate from source authenticity, governing applicability, complete legal
meaning, independent review, model quality and actual Lean compilation. This
adapter authenticates no reviewer, resolves no external definition, creates no
definition-use relation and grants no semantic or corpus admission.

A body such as “a person in an enlisted grade” can be explicitly declared as an
opaque unary predicate. That declaration does not infer person/grade sorts,
membership relations or complete statutory meaning. A later reviewed mapping
and supported semantic compiler must establish those boundaries.

See [V2 source definitions](legal_source_definition_v2.md),
[sampled-source declarations](legal_source_sampling_review.md) and
[V2 definition review](corpus_definition_review_v2.md) for the existing owners.

## Current validation status

The [native integration](legal_definition_use_review_v2_integration_20261015.md)
now records 244 passing cases across seven complete source/binding modules,
including all 59 focused binding cases and 28 blank-handoff migration cases.
They cover full FOL/TDFOL owner paths, ordered response commitments,
edition/source substitutions, resealed output changes and retained parents of
fragmented scope paragraphs. The
[integration receipt](evidence/legal-ir-definition-use-review-v2-integration-20261015/receipt.json)
retains the selected inventories and execution/native closeout evidence.

The separately executed actual §101 binding replay passed 15 named checks,
including six refusal controls. Its explicit “enlisted member” declaration retains the
complete body as one opaque predicate under caller-declared title scope. Both
families retain all 560 pending subjects, 8,400 blank question slots and 3,360
original open context obligations; each candidate graph has 15 nodes and 26
edges. Actual responses and reviews remain zero. This establishes declared
source geometry and candidate regeneration, not reviewed legal meaning,
authenticated exposure, gold labels or native Lean execution.

The earlier refused requests, unexecuted historical driver and closeout evidence
remain under `artifacts/legal-ir-definition-candidate-binding-20261015-01`.
The current replay has its own pinned driver and does not call the handoff
migration API. Passing migration fixtures does not establish an actual-source
handoff migration. Checked correspondence from unsigned source/exposure
declarations to authenticated interpretation subjects remains separate work.
