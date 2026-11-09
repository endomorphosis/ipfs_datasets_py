# Selected paired payload intake

`logic.autoformal.legal_paired_payload_intake_v1` connects a pinned local
paired-v1/v2 cache bundle to the existing opaque corpus-candidate adapter.
It requires neither a feed database nor a model invocation. The durable feed
and stateless API share `span_cache_feed.load_paired_payload` and the existing
strict `paired_span_census.load_paired_census_bundle` validator.

The metadata-only entry point remains
[the selected manifest inventory](legal_paired_manifest_inventory_v1.md).
Its row counts are declarations; this intake reads the actual three tables and
validates their schemas, hashes, row identities, comparisons, referenced
artifacts and reciprocal goal links. It also reuses `paired_source_records` to
check source/producer/model consistency, including legacy rows.

```python
from ipfs_datasets_py.logic.autoformal.legal_paired_payload_intake_v1 import (
    prepare_paired_payload_intake,
    paired_payload_report_sha256,
    validate_paired_payload_intake,
)

# Values come from an independently retained acquisition/selection receipt.
inputs = dict(
    repository_root=retained_revision_directory,
    repository_id="justicedao/uscode-autoformal-span-cache",
    revision=exact_commit,
    manifest_path_in_repo=selected_manifest_path,
    expected_manifest_sha256=selected_manifest_sha256,
)
report = prepare_paired_payload_intake(**inputs)
commitment = paired_payload_report_sha256(report)
validate_paired_payload_intake(report, expected_report_sha256=commitment, **inputs)
```

The root must be an absolute, unaliased directory containing the repository
layout. The revision is a caller-supplied acquisition identity; local files
alone do not authenticate their remote revision. The manifest commitment is
checked before table reads. Default bounds are 64 physical rows, 64 MiB
compressed inputs, 64 MiB aggregate decoded/represented inputs and a 16 MiB
complete report. `limits` accepts positive lower-only overrides. These input
byte limits are not process-memory guarantees.

Every verified physical row retains its ordinal, observation identity, derived
JSON and SHA256. JSON is serialized from the verified Parquet row using sorted
keys, ASCII escaping and compact separators. It is **not** original producer
JSON. Candidate interpretation routes and duplicate formal outputs remain
separate. Dispositions are `candidate_unbound`, `candidate_bound` or
`adapter_rejected`; a refused candidate retains the complete derived row and
bounded error. Whole-bundle integrity failures raise before adaptation. A
report-size failure does not return a truncated population.

An optional `source_bindings` list must cover every physical row in order.
Each entry is `None` or the existing corpus adapter's six-field source binding:
source version, source occurrence, context declaration, expected raw hash,
complete extracted text and expected extracted hash. The source owner checks
the supplied geometry and commitments. It does not authenticate the publisher
or establish legal meaning. No supplied parent source means unresolved; it
does not mean that a search found zero occurrences. No similarity, legal ID or
text equality silently chooses a physical occurrence.

The complete binding population is committed even when a binding is refused.
It uses the manifest inventory's ordinary-JSON guard (100,000 visited values,
depth at most 32, finite numbers and the decoded-input byte bound). Full replay
requires the original binding population again; a different rejected binding
with the same error message is still different input evidence.

`source_pins` records selected owner file observations. Its explicit scope does
not claim a complete execution closure or independently verified loaded bytecode.
For execution provenance, retain the fresh-process source manifest and loaded
module observations alongside acquisition receipts and the report commitment.

This boundary does not migrate unsupported exporters. Historical migration has
its own exact producer/layout eligibility contract. It does not interpret
opaque payloads, select governing definitions, qualify training targets, or
admit graph semantics or Lean proofs. Those remain later reviewed stages.

Focused tests:

```text
tests/unit/logic/test_span_cache_paired_payload.py
tests/unit/logic/test_span_cache_paired_feed.py
tests/unit/logic/autoformal/test_legal_paired_payload_intake_v1.py
tests/unit/logic/autoformal/test_legal_paired_manifest_inventory_v1.py
tests/unit/logic/autoformal/test_corpus_span_adapter.py
```
