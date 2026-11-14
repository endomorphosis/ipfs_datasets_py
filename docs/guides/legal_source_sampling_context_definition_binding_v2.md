# Contextual source review beside a V2 definition candidate

The existing `legal_source_sampling_definition_binding_v2` owner now exposes a
separate contextual profile. It connects a pinned explicit definition request to
the complete cross-source review packet without converting contextual responses
into the older single-source response schema.

This is a source/reference handoff. It does not infer a definition from source
text, interpret reviewer prose, rewrite the caller's AST, authenticate a reviewer,
resolve applicability, qualify training data or run Lean.

## Public API

Import from the existing owner:

```python
from ipfs_datasets_py.logic.autoformal.legal_source_sampling_definition_binding_v2 import (
    prepare_contextual_definition_binding_v2,
    contextual_definition_binding_sha256,
    validate_contextual_definition_binding_v2,
)

pins = {
    "expected_request_sha256": original_request_bytes_sha256,
    "expected_definition_bundle_sha256": complete_definition_source_bundle_sha256,
    "expected_context_sha256": complete_context_packet_sha256,
    "expected_response_sha256s": ordered_complete_context_response_sha256s,
    "expected_attachments_sha256": ordered_attachment_nominations_sha256,
}
result = prepare_contextual_definition_binding_v2(
    request_raw, context, responses, sources, attachments, **pins
)
checked = validate_contextual_definition_binding_v2(
    result, request_raw, context, responses, sources, attachments,
    expected_binding_sha256=contextual_definition_binding_sha256(result),
    **pins,
)
```

The example names already retained inputs and independently recorded commitments;
it does not acquire or invent them. Production loading of package roots may have
other startup behavior; the public owner itself retains its standard-library-only
cold-import contract, and loads operation owners lazily.

`request_raw` is the original bounded JSON byte sequence for an explicit V2
definition request. Its transport hash remains separate from canonical JSON
hashes. No request is synthesized from the contextual declarations.

`sources`, `attachments` and `context` retain the contracts in the
[cross-source review guide](legal_source_sampling_review_context_20261015.md).
Each source supplies a complete original review bundle, raw HTML or explicitly
missing raw source, an independent bundle pin and the complete sampling replay
inputs. The selected definition source must have available raw bytes, as required
by the existing definition-binding owner. The independent definition-bundle pin
selects exactly one replayed source; list order and text similarity are not source
selection rules. The selected definition request must still match that source's
version, document, occurrence and unit identities.

`responses` contains only the distinct contextual response schema, in the order
bound by `expected_response_sha256s`. An empty list is valid. Exact duplicates,
old-schema responses, unrelated targets and stale or altered inputs are rejected.
Every supplied response is checked by the existing context owner against its
original declaration and complete packet before the definition companion uses it.

## Separate states and records

The result has schema `legal-source-sampling-context-definition-binding/v2` and
three companions:

| Field | Retained meaning |
| --- | --- |
| `base_binding` | Unchanged original V2 definition envelope, prepared with an explicitly empty **v1** response population. Its candidate, source-role geometry and full single-source population keep their original owners. |
| `contextual_population` | Existing context owner's complete population, including every source guide and withheld parent. Context declarations keep their own schema and namespace. |
| `contextual_binding` | Sealed mechanical join with input/producer pins, exact required subjects, nomination links and separate direct/related response references. |

A **direct response** targets an exact required definition subject in the pinned
definition source. The existing context owner additionally requires that subject
to be a nominated attachment target. Required subjects include affected withheld
parents from the original binding. Only these direct responses affect the
companion's required-subject review state. Even `declarations_recorded` denotes
unverified declarations, not meaning approval or agreement.

A **related target response** targets another contextual subject and must actually
cite an exact namespaced attached-evidence reference whose supporting subject is
one of the definition's required subjects. A shared bare evidence hash, similar
text, a reference from a different target, or an uncited attachment is insufficient.
All matching nominations and their actual citations are retained; no first match
is selected. A related response gives no review credit to the supporting
definition subject. A related-only population therefore leaves direct definition
review pending.

`required_support_nominations` records all attachment nominations pointing to
required definition subjects, even when there are no responses. Each row preserves
the nominated target, exact supporting subject, available evidence commitments
and required definition roles. A role may be only `scope_unit`; a scope match does
not establish a definition-contributor match or applicability. Per-subject
`supporting_nomination_sha256s` also makes missing contributor links explicit.

All meaning/admission/proof/training flags remain false, and training/evaluation
gold masks remain zero. Source review declarations are not converted to signed
meaning reviews or training targets.

## Replay and bounds

The complete context packet is an **external required validation dependency**.
It is not truncated or duplicated inside the output envelope. Validation still
requires all sources, attachments, original request bytes and responses. The
whole output is independently pinned and regenerated byte for byte, including
false/zero distinctions.

The companion bounds the context packet to 96 MiB, source inputs plus attachments
to 96 MiB, response inputs to 96 MiB, and final output to 4 MiB. It admits at most
four sources, 8,192 total subjects, 128 attachments and 256 contextual responses.
Existing per-record/source limits still apply, as do lower limits retained in the
context packet. These are input/output bounds, not a total-process memory claim.
Large populations fail explicitly rather than being truncated. Producer pins
include both the existing owners and the contextual implementation, and are
checked before and after preparation.

## Current source qualification boundary

The retained source packet contains §101 scope and officer-definition support for
§§7213–7214 target candidates. The separately retained explicit definition request
available for this handoff instead concerns **enlisted member**, with §101 scope
unit 48 and contributor unit 54. The executed actual-source control preserved
both inputs unchanged. It exposed two shared-scope links and no contributor
link; it cannot be reported as an officer-definition or definition-use result.

Independent meaning review, authenticated review evidence, complete definition
applicability and richer norm grammar remain separate work. See the
[qualification report](../autoencoders/legal_ir_context_definition_binding_20261015.md)
for the exact executed scope and retained outcomes.
