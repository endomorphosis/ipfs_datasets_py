# V2 definition-only context and review evidence

`legal_statutory_context_v2` prepares exact V2 source selectors and six open
context obligations. `corpus_definition_review_v2` replays a
[V2 definition candidate](legal_source_definition_v2.md), every physical context
and the complete declared dependency inventory before delegating signature and
authorization checks to the existing `legal_graph_review` engine.

This is an engineering review interface. It supplies no production keys, signer,
registry, reviewer, clock or network defaults. Authenticated statements under
selected keys remain distinct from actual legal meaning, human independence,
source applicability, corpus admission and Lean qualification.

## Exact source contexts

```python
from ipfs_datasets_py.logic.autoformal import legal_statutory_context_v2 as contexts

packet = contexts.build_context_packet_v2(
    original_view_report, original_html,
    char_start=occurrence["start_char"], char_end=occurrence["end_char"],
    expected_report_sha256=independent_full_view_report_hash,
    descriptor=original_descriptor,
    expected_descriptor_sha256=independent_full_descriptor_hash,
    expected_raw_sha256=independent_html_hash,
    expected_raw_bytes=independent_html_length,
    limits=original_view_limits,
    dependency_requests=explicit_six_requests_or_none,
)
```

Each public context operation replays the complete original V2 view through its
existing owner. Selectors retain exact Unicode and UTF8 half-open geometry and
the original V2 view/occurrence identities. The compact packet binds that view,
descriptor and raw bytes; it does not embed another full source document.

The fixed six dependency kinds and availability rules use a small pure helper
matching the legacy context owner's contract. The active repository retains
the legacy context source, packet identities and validators unchanged. V2
packet/slot identities have distinct namespaces.
Same-view candidate content remains open, external locators remain locators,
and another expected local view produces an explicit stale disposition. These
are checklist slots, not inferred attachments or an exhaustive legal dependency
inventory. Available content never closes a slot automatically.

## Original inputs and independent pins

`prepare_definition_review_evidence_v2` requires a closed `candidate_inputs`
mapping of six independently retained byte bodies:

- `candidate_raw`, `report_raw`, `request_raw`;
- `raw_html`, `sampling_report_raw`, `descriptor_raw`.

The closed `expected_candidate_pin` has twelve fields:

| Field | Commitment |
| --- | --- |
| `candidate_sha256`, `candidate_cid`, `graph_cid` | Original candidate file and exact candidate/graph record identities |
| `request_sha256`, `report_sha256` | Original definition request/report file bytes |
| `raw_sha256`, `raw_bytes` | Exact original HTML hash and independent integer length |
| `extracted_sha256` | Complete normalized source text |
| `sampling_report_sha256` | Original complete sampling-report JSON file bytes |
| `sampling_report_full_canonical_sha256` | Full canonical sampling report, including its internal digest |
| `descriptor_sha256` | Original descriptor JSON file bytes |
| `descriptor_full_canonical_sha256` | Complete canonical descriptor |

File hashes do not replace full canonical commitments. The adapter checks all
original input bounds and transport hashes before lazy operation owners or
candidate compilation. Duplicate keys/nonfinite JSON are rejected. The complete
sampling report remains external bounded evidence. Recorded view, sampler and
compiler limits are passed back to their respective existing validators; those
owners enforce their closed, lower-only limits again during replay.

`context_inputs` is an ordered list of closed mappings containing
`source_occurrence_cid`, `packet_raw` and `dependency_requests`. The independently
retained `expected_context_population` supplies matching ordered
`{source_occurrence_cid, packet_sha256}` commitments. Every unique physical
candidate occurrence must appear exactly once in its original order, including
full source contributors and derived head/cue/body subspans. Both character and
UTF8 geometry are checked against the original candidate occurrence.

```python
from ipfs_datasets_py.logic.autoformal import corpus_definition_review_v2 as review
from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as deps

replay = dict(
    candidate_inputs=original_six_byte_inputs,
    expected_candidate_pin=independent_twelve_field_pin,
    context_inputs=original_context_byte_inputs,
    expected_context_population=independent_ordered_context_population,
)
preparation = review.prepare_definition_review_evidence_v2(**replay)
manifest = deps.build_dependency_manifest(
    preparation["artifacts"], preparation["edges"],
    expected_artifact_ids=preparation["expected_artifact_ids"],
)
subject = review.build_definition_review_subject_v2(
    preparation, manifest, **replay,
    expected_manifest_sha256=independent_manifest_hash,
    required_dependency_ids=independent_complete_ordered_dependency_ids,
)
```

Retain independent manifest/dependency commitments before signing. The complete
source byte inputs, companions, occurrences, original context declarations,
V2 context packets and actual producer-policy pins are all dependencies. A
missing edge, record or changed dependency cannot be removed to make review
pass. Subject construction replays the preparation; a repaired seal cannot
authorize a changed AST, scope, symbol binding or physical population.

## Authentication domain and assessment

The V2 subject, claim schema, action and audience are fixed by this adapter's
code. They are separate from the canonical graph and legacy definition-plus-norm
domains. Relabeling an old claim invalidates its signature and does not change
what its key was authorized to review.

`assess_definition_reviews_v2(subject, registry, policy, reviews, manifest, ...)`
requires the same original replay inputs, independent subject/registry/policy/
complete-review-population/manifest hashes, explicit `at_time_utc`, current
artifact and pin observations, and exact context evidence bodies. It delegates
to the existing fixed-domain verifier. That engine checks signatures, distinct
authorized legal/formal principals and keys, scope, validity windows, revocation,
context claims and current complete dependency closure.

No reviews produces a pending evidence assessment and named blockers. Invalid
or stale evidence is rejected or blocked under the existing policy rules.
Synthetic credentials exercise authentication and supply no production review
authority. A caller-supplied external-policy wire shape alone establishes no
human identity, competence, independence or legal truth.

Keep the candidate immutable and retain the assessment separately. The
assessment records authenticated evidence and unresolved prerequisites while
leaving source meaning, context closure, independent human review, accepted-view
eligibility, semantic/training admission and Lean authority false.
`validate_definition_review_assessment_v2` replays those same inputs and rejects
assessment changes even if its digest is repaired.

## Bounds and scope

Candidates, compiler reports, requests, descriptors, context packets,
preparations and subjects retain the one-MiB sealed-record ceiling. The complete
sampling transport has its separate 32 MiB cap; HTML is at most 8,000,000 bytes;
aggregate original inputs/context requests and packets are at most 48 MiB.
The shared authentication engine retains its separate eight-MiB assessment-input
ceiling. Maximums are 256 physical contexts and 1,536 obligations, subject to
the tighter byte bounds. Oversize complete evidence refuses without truncation.

Producer files are bound at import/first explicit operation and checked before
and after review operations. These checks pin the actual signature-owner source;
they do not authenticate the installed cryptographic distribution or continuous
filesystem custody. The original v1 APIs and signing domains remain available.
This profile adds no norm, automatic `USES_DEFINITION` edge, external legal-source
adoption, statutory gold or native Lean build. Actual independent interpretation,
a complete real use, native symbol/lookup binding and separate downstream
admission remain necessary.
