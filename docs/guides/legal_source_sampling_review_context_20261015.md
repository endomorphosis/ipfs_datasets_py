# Cross-section evidence for source-sampling reviews

The existing `legal_source_sampling_review` owner exposes a separately versioned
context-packet interface. It allows a declaration about one source subject to
cite a specific supporting subject from another complete, pinned source bundle.
The implementation is in the sibling `legal_source_sampling_review_context`;
the public entry points remain in the existing review owner.

The [qualification report](../autoencoders/legal_ir_sampling_review_context_20261015.md)
records 243 passing tests and successful replay of the three actual source
bundles. Those statutory review subjects remain pending with zero training masks.

The original review bundle and v1 response contracts remain available. Contextual
responses use a distinct schema and bind both the unchanged declaration and
the complete context packet. A contextual response is not a signed review or a
v1 response, and cannot be fed silently into an existing v1 admission consumer.

## Prepare and replay

Each source entry has exactly these fields:

```python
source = dict(
    bundle=complete_original_review_bundle,
    raw=original_html_bytes,
    expected_bundle_sha256=independently_retained_bundle_pin,
    replay_inputs=original_sampling_replay_inputs,
)
```

Replay inputs are those already used by the existing review owner: the complete
sampler report commitment, acquisition descriptor and pin, raw-source hash and
byte count, and any declared extraction/sampling bounds. The source bundle is
regenerated in full; canonical-byte equality preserves type distinctions such
as `False` versus `0`.

Each attachment identifies an exact target and an exact supporting subject:

```python
attachment = dict(
    target_bundle_sha256=target_bundle_pin,
    target_subject_ref=exact_original_target_subject_ref,
    supporting_bundle_sha256=supporting_bundle_pin,
    supporting_subject_ref=exact_original_supporting_subject_ref,
    role="definition_candidate",
)
```

Roles are unreviewed nomination labels. `definition_candidate`, `scope_candidate`
and `adjacent_definition_context_candidate` describe proposed uses of evidence;
none proves the evidence governs the target provision. Subject references retain
their original kind, ordinal and content commitment. Matching labels or statutory
section names do not replace those references.

```python
from ipfs_datasets_py.logic.autoformal import legal_source_sampling_review as review

packet = review.prepare_sampling_review_context(
    sources, attachments,
    expected_attachments_sha256=independently_retained_attachment_list_pin,
)
packet_pin = review.sampling_review_context_sha256(packet)
review.validate_sampling_review_context(
    packet, sources, attachments,
    expected_context_sha256=packet_pin,
    expected_attachments_sha256=independently_retained_attachment_list_pin,
)
```

Attachment commitments hash the complete ordered list as canonical UTF-8 JSON
with sorted keys, compact separators, `ensure_ascii=False` and `allow_nan=False`.
These commitments differ from hashes of pretty-printed JSON files. Store an
expected packet commitment independently before accepting an incoming packet;
hashing a changed incoming object alone does not authenticate it.

The packet retains complete original bundles once, including unselected guides
and withheld parent contexts. It adds exact target-specific supporting evidence
references. It does not edit original source contexts, merge equal-text
occurrences, choose a governing edition, or complete missing-context requirements.
Closed schemas and finite population/byte bounds refuse invalid or oversized
requests rather than trimming their contents.

The initial profile allows up to four distinct bundles, 128 attachments and
8,192 total subjects. Source-plus-attachment input and output packets each have
a 96 MiB bound. Response-list input has its own bound; these are separate
serialization limits, not a limit on all live Python memory. Individual sealed
responses and population summaries retain the existing 1 MiB record contract.
Callers may lower bounds; larger profiles require an explicit extension.

## Record declarations in the new domain

Use `record_sampling_review_context_response` with the packet, an explicitly
supplied declaration, original source inputs and attachments. Supply independent
commitments for the packet, declaration and attachments. Its validator also
requires the expected complete response commitment. The response wrapper binds
the declaration to the exact context packet; the original declaration retains
its target-bundle identity and ordered question catalog.

A response can cite local evidence allowed by its original guide and exact
supporting evidence envelopes authorized for that target in the packet. An
attachment for a different target does not authorize its evidence here. Keep
the complete generated envelope when citing supporting evidence, including its
supporting bundle, subject, nominated role and original evidence reference.

The original guide's shared full-document view remains available. Scoping
restricts specific occurrence/context references; it is not information isolation
of the other passages in that retained view.

The existing declaration checks still require explicit reviewer and exposure
declarations, all ordered questions, valid dispositions, rationale and structured
unresolved requirements. The recorder does not supply answers or authenticate
the declared reviewer. Tests using authored fictional declarations exercise this
transport contract; they are not statutory meaning reviews.

`summarize_sampling_review_context_population` validates independently pinned
contextual responses and accounts for every original subject in every supplied
bundle. It preserves unresolved, unsupported and disputed declarations without
selecting a winner. An empty response list records a pending population; a full
list of declarations still does not establish semantic agreement or admission.

## Training and formalization remain separate

All authority flags remain false and training/evaluation masks remain zero.
Attaching a definition passage cannot establish source correspondence, legal
applicability, complete meaning or a qualified typed target. Edition and source
occurrence identities remain separate even when text is equal.

Existing definition-binding and training consumers require an explicit supported
handoff for this new response domain, along with their independent review and
admission gates. Complete statutory norms may also require richer grammar than
the current unary compiler. The context API performs no model inference,
training, signing, graph admission or Lean build.
