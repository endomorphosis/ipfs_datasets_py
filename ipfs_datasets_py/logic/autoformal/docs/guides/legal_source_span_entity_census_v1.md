# Original-bound entity census companion

`logic/autoformal/legal_source_span_entity_census_v1.py` attaches an
independently pinned, previously completed entity-index v2 census to the
existing source/span/entity join. It preserves that join unchanged and uses
the existing public owners for both checks:

1. `legal_entity_index_intake.validate_census_bindings` verifies the retained
   census seal, complete population and endpoint diagnostics, then rehashes the
   original file and checks its Parquet schema, footer and resource bounds.
   It does **not** decode the entity rows again.
2. `legal_source_span_entity_join_v1.validate_source_span_entity_join_manifest`
   regenerates the complete selected join from its original inputs.

The entity repository, immutable revision, configuration, declared population
and twelve-field schema must agree across the two results. The order above
rejects malformed census evidence before expensive join replay. These are
ordered custody observations, not an atomic snapshot across all files.

## API and exact inputs

```python
prepare_source_span_entity_census_v1(
    request_raw, join_report, census_raw, entity_path,
    *, expected_request_sha256, join_originals,
)
source_span_entity_census_sha256(report)
validate_source_span_entity_census_v1(
    report, request_raw, join_report, census_raw, entity_path,
    *, expected_report_sha256, expected_request_sha256, join_originals,
)
```

The request is duplicate-free UTF-8 JSON with exactly these keys:

```text
schema = legal-source-span-entity-census-request/v1
join_report_sha256
census_raw_sha256
census_sha256
entity = {
  repository_id, revision, configuration, file_sha256, file_bytes, rows
}
census_limits = {
  max_rows, batch_size, max_file_bytes, max_decoded_bytes,
  max_row_group_bytes, max_batch_bytes, max_row_bytes, max_scratch_bytes
}
```

The repository is `justicedao/uscode-autoformal-entity-cache`; configuration is
`autoformal_uscode`; revision is an explicit lowercase forty-hex identity.
These are caller-supplied acquisition identities, not authenticated remote
history. All eight census limits must exactly match the original census and
remain within the existing intake owner's bounds. They cannot be silently
widened for replay. `endpoint_details=True` is mandatory; a v1 census is not a
substitute for the detailed v2 evidence.

`join_originals` is a closed mapping of the unchanged join owner's inputs:

```text
request_raw
source_request_raw
source_metadata_bytes
paired_inventory_request_raw
paired_manifest_bytes
entity_info_raw
expected_request_sha256
legacy_join_inputs
```

The two metadata mappings contain exact original bytes. `legacy_join_inputs`
is the original mapping or `None`, not a reconstructed report projection. Each
provided legacy entry retains its complete expected population, receipt bytes
or unavailable `None`, independent receipt pin, source sections and independent
section expectations. Its exact fields and source commitments remain the
existing join owner's responsibility.

`entity_path` must be the original absolute physical path recorded in the
census. The public binding validator compares the entire reconstructed source
descriptor. Copying a file does not authorize rewriting the historical census
path and resealing it. A relocated evidence package needs a separately designed
custody contract; this adapter does not silently relax the existing one.

## Hashes and retention

Keep these three different identities distinct:

| Identity | Recipe |
| --- | --- |
| `census_raw_sha256` | SHA-256 of the exact original JSON file bytes, including formatting. |
| `census_sha256` | Existing census owner's SHA-256 of compact, sorted, non-ASCII-escaped UTF-8 JSON with only the self-seal field `census_sha256` omitted. |
| `source_span_entity_census_sha256(report)` | SHA-256 of the complete bounded canonical companion report; no report field is omitted. |

The join has its own existing canonical report identity. An independently
supplied request pin binds these identities; reading a census's self-seal and
presenting it as an independent pin is insufficient provenance.

The companion retains the exact census UTF-8 bytes and its complete parsed
report, including missing endpoints, duplicate physical rows, legacy boolean
observations and all negative dispositions. It retains the full replayed join
unchanged. The nested join's historical `verified_file_rows=0` still describes
that metadata-only join; the separate companion describes the additional
physical-file evidence rather than rewriting its predecessor.

`join_originals_sha256` is an input-custody commitment. Raw original byte
arguments and metadata byte values are represented by their SHA-256 and byte
length. Legacy ordinary arguments are canonically encoded and committed the
same way, with receipt bytes committed separately. The resulting identity
mapping is canonically encoded and hashed. This commitment does not replace
the original join's independent request, receipt and source pins.

## Coverage and custody limits

`prior_entity_census_rows` is the historical complete decoded population from
the independently pinned census. `fresh_entity_rows_decoded=0` describes this
adapter's actual work. Fresh verification covers file bytes, schema and footer;
`fresh_entity_row_replay_performed` remains false. Original rows remain in the
immutable entity file. The adapter does not select entity rows, reconstruct
edges, verify current source-table rows or infer section coverage.

Each selected paired reference retains its order, physical identity and raw
row identity. `entity_semantic_binding` remains `null`, with reason
`semantic_companions_not_supplied`; the aggregate semantic binding count also
remains `null`. A missing binding is not a measured zero-error result. All
semantic, training, evaluation, graph and proof authority flags remain false;
training and evaluation masks remain zero. Labels, IDs and legacy admitted or
formalized flags cannot establish scoped definitions or governing use.

Original join arguments are detached before delegated calls. On success and
failure, closing checks inspect the offered originals, offered join report and
selected owner source hashes. The outer validator also checks the offered
companion report after replay. All closing checks are attempted; secondary
custody failures are attached as exception notes without replacing the first
operational exception. These fences do not claim arbitrary concurrent-writer
or complete loaded-byte attestation. The producer-pin scope is explicitly the
selected source files; `loaded_byte_identity_verified` remains false.

Bounds are 128 KiB for the request, 1 MiB for raw census JSON, 16 MiB for the
original join report, 64 MiB aggregate original argument bytes and 32 MiB for
the companion. The original-argument bound excludes the separately checked
Parquet file. The entity owner's limits govern that file and its footer.
Over-limit evidence is rejected rather than truncated or sampled.

This API creates no scheduler, reservation or controller. Qualification must
use the existing resource and source-lease owners. A real retained fixture can
prepare and replay the companion without network, new scans, models, training,
semantic reviews or Lean execution. Self-resealed report-tampering cases require
full original replay and should be explicitly budgeted; fixed-pin mismatches
can be tested before that work. Negative unit fault injections must remain
separate from actual retained-evidence qualification.
