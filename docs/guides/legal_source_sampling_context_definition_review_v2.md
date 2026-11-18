# Contextual evidence alongside a V2 definition review subject

The existing `legal_source_sampling_definition_review_v2` correspondence owner
is now available in this checkout. Its original prepare/hash/validate APIs join
an exact sampled-source binding to an existing V2 definition review subject.
They preserve the candidate, original report transport, physical contexts and
dependency manifest. The implementation was reused from the retained isolated
Datasets checkout, not replaced by another review engine.

Three additive public APIs accept the separately qualified contextual binding:

```python
from ipfs_datasets_py.logic.autoformal import (
    legal_source_sampling_definition_review_v2 as correspondence,
)

result = correspondence.prepare_contextual_definition_review_correspondence_v2(
    contextual_binding,
    review_subject,
    expected_binding_sha256=retained_contextual_binding_sha256,
    expected_subject_sha256=retained_subject_sha256,
    contextual_replay_inputs=contextual_replay_inputs,
    candidate_inputs=original_candidate_inputs,
    expected_candidate_pin=retained_candidate_pin,
    context_inputs=original_physical_context_inputs,
    expected_context_population=retained_physical_context_population,
    dependency_manifest=original_dependency_manifest,
    expected_manifest_sha256=retained_manifest_sha256,
    required_dependency_ids=retained_required_dependency_ids,
)
output_pin = correspondence.contextual_definition_review_correspondence_sha256(result)
```

Retain that output commitment independently before receiving a later artifact.
`validate_contextual_definition_review_correspondence_v2` accepts the result,
the same original arguments and `expected_correspondence_sha256`; it regenerates
the whole envelope and compares canonical bytes, preserving false/zero types.

`contextual_replay_inputs` has exactly the five input values `request_raw`,
`context`, `responses`, `sources`, `attachments`, and the five independent pins
documented by the [contextual binding API](legal_source_sampling_context_definition_binding_v2.md).
The complete context packet, source bundles and response payloads remain external
required replay inputs. They cannot be replaced with selected excerpts.

The six original candidate byte inputs, twelve candidate pins, physical context
inputs and dependency manifest keep the contracts of
[V2 review preparation](../autoencoders/corpus_definition_review_v2.md).
The original report's transport bytes matter: formatting an equivalent decoded
report can change the candidate's dependency identity. Inputs must describe the
exact candidate in `contextual_binding.base_binding`, not an earlier candidate
with similar source text or a different producer identity.

## Two separate records

The closed result uses schema
`legal-source-sampling-context-definition-review-correspondence/v1`:

| Field | Meaning |
| --- | --- |
| `definition_correspondence` | Existing owner's unchanged unsigned correspondence to the original review subject, using an explicitly empty v1 response population. |
| `contextual_correspondence` | Separate sealed record binding the full contextual result, complete population reference/counts, exact required subjects, support nominations and direct/related declarations. |

Each supplied contextual response retains its ordered response/declaration
commitment, exact subject, direct-or-related role, reviewer-declaration commitment
and unverified exposure declaration. Conflicting revisions stay separate.
Attached evidence alone cannot complete a supporting definition's review, and
reviewer prose never rewrites the caller's AST.

The original subject and dependency manifest remain unchanged, with their
canonical commitments preserved. **A signature
on that subject does not sign this new contextual record or its responses.**
Both coverage flags are explicitly false. This API creates no signature,
assessment, authority decision or new signing domain. Even direct declarations
remain unverified declarations. Meaning, applicability, exposure authentication,
training/gold and admission flags stay false; masks stay integer zero.

All inputs are bounded and detached before operation owners run. Existing source,
binding and review input limits still apply; the aggregate companion input ceiling
is 384 MiB and the complete output ceiling is 4 MiB. The record ceiling remains
1 MiB. These are byte/population constraints, not process memory guarantees.
Producer hashes and input snapshots are checked before and after replay.

## Actual source qualification

The retained officer-definition requests provide two alternatives: an opaque
whole-body predicate and an explicitly supplied disjunction. Neither is selected
as the law's meaning. They share scope unit 48 and contributor unit 49 and use the
same eight prior cross-section nominations. Their four matching links comprise
two scope links and two contributor links. The alternate definitions have six
and seven physical contexts; overlap means these are not thirteen independent
source examples.

The [qualification report](../autoencoders/legal_ir_context_review_correspondence_20261015.md)
records the executed tests and actual replay. Actual source reviews, signed
meaning decisions, governing norm uses and training targets remain separate
requirements. The [norm grammar gap report](../autoencoders/legal_ir_statutory_norm_profile_gaps_20261015.md)
specifies the semantic distinctions still needed for the two use provisions.
