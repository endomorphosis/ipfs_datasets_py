# Statutory review recording API

Import `ipfs_datasets_py.logic.legal_ir.statutory_review_recording` through the repository's inert package bootstrap. The new owner depends on the unchanged `statutory_source_review` packet owner; it does not import the authored recorder or alignment-signature owner. The resolver accepts an independently selected `{sha256, bytes}` content reference and returns a canonical absolute ordinary singly linked file path.

```python
pin = recording.digest(blank_packet)  # full canonical packet, including its embedded body seal
guide = recording.submission_guide(
    blank_packet, expected_packet_sha256=pin, artifact_resolver=resolver)

# Only separately supplied caller declarations belong here. [] records pending items.
receipt = recording.record_reviews(
    blank_packet, submitted_payloads,
    expected_packet_sha256=pin, artifact_resolver=resolver)
validation = recording.validate_recording(
    receipt, blank_packet, submitted_payloads,
    expected_packet_sha256=pin, artifact_resolver=resolver)
```

`submission_guide` contains detached blank per-item slots, not a completed submission. A separately supplied submission has exactly `schema`, `packet_sha256`, `submission_id`, and `items`. Its schema is `statutory-source-context-review-submission/v1`. Per-item keys are the exact guide item's keys: immutable physical/source/context envelope, `review`, `context_review`, `evidence`, and `exposure_declaration`. There are at most 20 submissions and 32 physical items per submission. No item may repeat within a submission; no declared reviewer/item pair may repeat across submissions. Renaming an otherwise identical submission cannot create another declaration.

Null means unanswered; typed empty findings express a declared absence. All 14 review and seven context questions must be filled for structural completeness. Reviewer ID and valid UTC calendar time are declarations. Complete deontic rules have `modality` O/P/F, nonempty actor/action strings, an object string that may be empty, and ordered conditions/exceptions/temporal string lists. Unsupported, ambiguous, needs-context and no-rule declarations carry explicit absent rules. This recorder establishes no legal truth from these slots.

Source-role anchors have exactly `anchor_id`, `rule_index`, `facet`, `coordinate_space`, `char_start`, `char_end`, and `text`. They use `selected_source_unicode_characters` and must match the exact selected literal slice. Trigger anchors omit ID/rule/facet fields. Full-section boundary anchors use `complete_raw_section_unicode_characters`, add exact `context_artifact` and `kind` (`operative`, `editorial`, `undetermined`), and match that complete context slice. Byte and character coordinates must not be interchanged.

Qualifier attachments have `attachment_id`, `rule_index`, `facet`, `anchor_ids`, `affected_rule_indices`, `scope_kind`, and `scope_text`. Referenced anchors must match the declared rule and qualifier facet. Scope kind `rule` addresses its single rule; `shared_rules` addresses at least two rules; `undetermined` remains a declared unresolved scope. Repeated surfaces, overlapping spans, multiple rules and multiple qualifiers remain in declarations without being flattened into a decoder target.

Evidence has exactly nullable `identity_evidence`, `independence_evidence`, and `review_process_evidence` artifact references. Context source-authority/currentness evidence is a nullable list of artifact references. The owner opens and closes their exact bytes under a shared 16-artifact/1MiB bound. Arbitrary evidence contents are not interpreted or authenticated. Exposure fields are nullable `candidate_or_reference_exposed`, `organizer_metadata_exposed`, and `other_exposure`; omission cannot prove blindness.

`record_adjudications(blank_packet, submitted_payloads, declaration_package, ...)` records a separate declared adjudication package. It requires the selected packet SHA and exact full recording SHA. Package items bind considered and accepted `{submission_sha256, declaration_sha256}` references, declared distinct adjudicator ID/time, decision, unresolved scope, rationale and the same evidence shape. Decisions are `accept_unique`, `accept_alternatives`, `no_normative_rule`, `needs_context`, `unsupported`, `abstain`, `reject`, or `unresolved`. Declared acceptance validates reference cardinality, but leaves actual adjudication and every admission pending. `validate_adjudication_recording` replays this separate receipt.

```python
# This diagnostic needs one separately supplied complete normative declaration
# and an explicit review-process evidence artifact. It neither edits nor admits it.
geometry = recording.assess_declaration_geometry(
    blank_packet, submitted_payloads, submission_index=0, item_id=declared_item_id,
    expected_packet_sha256=pin, artifact_resolver=resolver)
```

Geometry uses the unchanged one-flat-rule copied-span profile. The declarations preserve wider structures; geometry reports limits independently. All APIs retain zero masks and false legal-gold, identity/independence, source/current-law, family/Lake and training/evaluation authority. They make no model, encoder, network, compiler, prover or fitting call.

`parse_json_bytes(raw_bytes)` rejects duplicate keys, invalid UTF8, nonfinite values and oversized ordinary JSON. `digest(value)` hashes full canonical content. Output `content_sha256` seals the output body excluding that field; neither digest establishes the original file's byte hash. A file workflow must separately verify byte pins and safely persist results. Synthetic executable examples are authored only in the new inert tests; no completed declaration for the eight actual US Code cases was created.
