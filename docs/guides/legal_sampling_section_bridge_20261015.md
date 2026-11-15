# Connect sampled source-review subjects to primary section candidates

The sampled-source profile in `logic/autoformal/legal_span_section_bridge.py`
connects the existing official-source sampler and review bundle to the guarded
`PrimarySectionIndex`. It supplies an exact source-to-navigation connection for
review preparation. A section match remains a candidate association.

The [qualification report](../autoencoders/legal_ir_sampled_primary_bridge_20261015.md)
records 119 passing tests, the real three-section replay and its retained first
failure. Edition correspondence and legal meaning remain unreviewed.

The earlier `reconcile_span_sections` contract and its cache/source-mapping
policy are unchanged. That profile expects Git source revisions. Official HTML
has its own acquisition, edition, normalized-view and occurrence identities;
the sampled-source profile preserves those identities without converting an
edition into a fabricated Git revision.

## Prepare and replay a connection

Use a previously pinned complete review bundle, original HTML bytes, existing
sampler replay inputs and an open `PrimarySectionIndex`. The index constructor
requires independent candidate and reconstruction-report commitments and checks
the entire candidate. Reuse its guarded context across related page lookups.

```python
from ipfs_datasets_py.logic.autoformal import legal_span_section_bridge as bridge

# Select exact original unit subject references, in original source order.
# Preserve this selection and its commitment before running the connection.
selection_pin = bridge.sampling_section_subjects_sha256(selected_subject_refs)
trusted = dict(
    expected_bundle_sha256=independent_complete_bundle_pin,
    selected_subject_refs=selected_subject_refs,
    expected_selected_subjects_sha256=selection_pin,
    section_index=opened_primary_index,
    expected_section_index_sha256=independent_index_receipt_pin,
    **sampling_replay_inputs,
)
report = bridge.reconcile_sampling_sections(bundle, original_html, **trusted)
report_pin = bridge.sampling_section_bridge_sha256(report)
bridge.validate_sampling_section_bridge(
    report, bundle, original_html,
    expected_bridge_sha256=report_pin, **trusted,
)
```

`sampling_replay_inputs` belongs to the existing sampler/review owners:
`expected_sampling_report_sha256`, `descriptor`,
`expected_descriptor_sha256`, `expected_raw_sha256`, `expected_raw_bytes`,
and optional `view_limits` and `sampling_limits`. Bundle and report commitments
hash complete canonical JSON, including existing seals. A file's raw-byte hash
is a different commitment. A hash computed from an incoming artifact alone is
not an independently retained input pin.

The new output schema is `legal-sampled-source-section-review-candidates/v1`.
The input bundle is replayed in full before selected units are joined to the
index. Selections must be distinct, source-ordered, exact `unit` references.
Foreign references, changed hashes, missing reference fields, duplicate indices and selected
withheld paragraph fragments are refused. Withheld contexts remain part of the
whole bundle; this profile does not turn them into complete selectable units.

## Evidence retained

The result contains:

- Complete bundle, sampler, acquisition, raw-source, selection and index pins.
- Original population counts and ordered guide commitment, including unselected
  subjects. The complete original bundle remains a required dependency.
- Each selected original guide, unit, version, occurrence and open context record.
- One complete primary lookup shared by those units, with every literal section
  candidate, source-package observation, `HAS_SOURCE` relationship and recognized
  release-point observation supplied by the existing index.
- Separate official edition/package and primary release/source-revision fields,
  explicit missing or ambiguous section dispositions, and unresolved provenance
  or applicability issues.

No first-match selection, legal-ID normalization, label-based identity inference
or source-package checksum reinterpretation occurs. Empty and ambiguous lookup
results stay explicit. Even a unique candidate with healthy transport does not
verify that its primary source package contains the official HTML or that the
two releases represent the same governing law. Different source namespaces are
not themselves proof that the statutory text differs.

Validation regenerates the full sampling bundle and guarded lookup before
comparing the complete output as canonical bytes. Changing a row, selection,
lookup, mask, authority flag or edition and merely resealing the result cannot
replace independent source evidence. Bounds cover the full bundle, combined
input bytes, selected population and output; overflow refuses rather than
returning a truncated result. The existing index and extraction owners retain
their own bounds.

## Downstream boundaries

The selected units are nominated for review. `meaning_target` and `typed_IR`
remain null, training/evaluation masks stay zero, and semantic, admission and
proof flags remain false. No graph assertion or review response is manufactured.
Original open context requirements remain intact.

This connection does not extend the review recorder's evidence allowlist across
bundles. A review of one page still cannot cite another page's exact subject
without a separately supported cross-bundle evidence attachment. It also does
not sign reviews, resolve legal applicability, qualify training targets, invoke
an autoencoder or build Lean. Those stages retain their existing owners and
independent prerequisites.

Full index construction and replay belong under the existing shared validation
resource lease. No scheduler or admission policy is created by this API. The
focused integration tests reuse actual sampler and primary-index fixture owners
in `tests/unit/logic/autoformal/test_legal_sampling_section_bridge.py`.
