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
Every authoritative report binding maps its exact occurrence interval to all
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

The October 15 owned validation passed **154 tests with no failures, errors or
skips**: 59 binding cases and 95 existing compiler, corpus-adapter and review
regressions. The new cases include both family paths, ordered commitments,
edition substitutions, resealed changes and retained parents of split scope
paragraphs.

The real §101 replay passed fourteen checks, including six refusal controls.
It encoded the explicit unreviewed “enlisted member” definition with its
separate scope preamble through FOL and TDFOL. Each candidate graph has fifteen
nodes, twenty-six edges and one `DEFINES` edge. Both retain all 560 pending
source subjects, zero actual responses and all 3,360 original open context
requirements. No meaning, identity, training or proof authority was granted.

Independent readback verified all twenty-six exports, their 7,026,566 bytes,
29 producer files, 2,407 CID seals, 1,131 all-false authority objects and 2,250
strict integer-zero masks. The original storage and source-watcher refusals
remain retained evidence. The large bundle is checked by the unchanged
driver's fixed transport/canonical pins and complete replay; launcher source
monitoring retains its four-MiB bound.

The [qualification receipt](../../../../../../../artifacts/legal-ir-definition-candidate-binding-qualification-20261015-01/qualification-receipt.json)
records these results. The separate
[V2 native build adapter](legal_source_sampling_definition_lake_v2.md) subsequently
compiled both family projects and checked all six expected modules. Its receipt
records that observation; the immutable binding and its candidate retain their
original review, proof, training and admission flags.
