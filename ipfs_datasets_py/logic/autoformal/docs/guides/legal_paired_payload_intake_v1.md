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

## Explicit coordinate payload profile

`prepare_paired_payload_intake_v2` accepts only paired-v3 bundles and additionally
requires `expected_source_coordinate_report_sha256`. Its corresponding
`validate_paired_payload_intake_v2` replays both independent input pins and the
complete original population. The original payload entry points accept only
paired-v1/v2, so a v3 report cannot silently lose its coordinate carrier.

The v2 report schema is `legal-paired-payload-intake/v2`. The existing stateless
feed loader and `paired_span_census.validate_paired_source_coordinates` perform
the full report, original-index and exact-reference replay. Each physical row
additionally retains `source_provenance_json` as its original canonical string,
`source_coordinate_report_sha256` and `source_coordinate_span_index`. Equal
text at different original indices remains distinct. Legacy paired row
serializations, observation IDs and the three Arrow schemas remain unchanged.

Exactly one top-level `source_coordinates` carrier holds `report_raw_utf8`,
`report_bytes`, `report_artifact_sha256` and `report_sha256`. `report_raw_utf8`
is the complete decoded artifact as a string, preserving source metadata
insertion order when the outer report is serialized with sorted keys. It is
not a reserialized nested report object. Its UTF8 byte length and artifact
digest remain separate from the independently supplied complete-report pin.
The full report is not duplicated in each physical row.

Existing positive lower-only limits apply, including the complete report byte
bound; adding the carrier can cause an explicit bound refusal. No partial
report or truncated occurrence population is returned. The coordinate report
does not select a separately supplied corpus occurrence: optional six-field
`source_bindings` remain explicit. Unbound rows remain unbound, all authority
flags stay false, and opaque formal outputs never become source context,
semantic admission or training permission. Fresh engineering qualification is
required for this profile; historical source-pinned receipts are unchanged.

The focused companion is
`tests/unit/logic/autoformal/test_legal_paired_coordinate_intake_v2.py`.
